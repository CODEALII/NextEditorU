"""Check that an isolated Cemu profile is ready for a controlled NSMBU test.

This validates config and boot-log evidence only. It cannot observe controller
input, the rendered map, traversal, level launch, progression, or save behavior.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


LEFT_STICK_KEYS_CEMU_126 = {18: 87, 19: 83, 20: 65, 21: 68}
GAMEPAD_A_KEY = 90  # Z virtual key, per generated Cemu test profiles
TARGET_MODULE = re.compile(r"Loaded module 'red-pro2' with checksum 0x6caea914")
PACK_LINE = re.compile(r"Activate graphic pack: (.+)$", re.MULTILINE)


def _read_controller(path):
    values = {}
    section = None
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith(('#', ';')):
            continue
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1].strip().casefold()
        elif section == 'general' and '=' in line:
            key, value = line.split('=', 1)
            values[key.strip().casefold()] = value.strip()
        elif section == 'controller' and '=' in line:
            key, value = line.split('=', 1)
            try:
                values[int(key.strip())] = value.strip().casefold()
            except ValueError:
                continue
    return values


def _read_controller_xml(path):
    """Read the Cemu XML profile format used by current and some legacy installs."""
    root = ET.parse(path).getroot()
    controller = root.find('./controller')
    if controller is None:
        return {}
    values = {
        'api': (controller.findtext('api') or '').strip(),
        'emulate': (root.findtext('type') or '').strip(),
    }
    for entry in controller.findall('./mappings/entry'):
        try:
            mapping = int(entry.findtext('mapping', ''))
        except ValueError:
            continue
        button = (entry.findtext('button') or '').strip()
        values[mapping] = f'key_{button}'
    return values


def _pack_key(value):
    return re.sub(r'[^a-z0-9]', '', value.casefold())


def _save_inventory(profile):
    """Hash files in this title's isolated MLC user-save tree."""
    save_root = (profile / 'mlc01/usr/save/00050000/10101D00/user').resolve()
    if not save_root.is_dir():
        return {}
    inventory = {}
    for path in sorted(save_root.rglob('*')):
        if path.is_symlink():
            continue
        if not path.is_file():
            continue
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        inventory[path.relative_to(save_root).as_posix()] = {
            'size': path.stat().st_size,
            'sha256': digest.hexdigest(),
        }
    return inventory


def inspect_profile(profile, *, expected_pack=None, archive=None,
                    forbidden_pack=None, require_keyboard=False, require_gamepad_a=False,
                    require_run=False,
                    compare_save_to=None):
    profile = Path(profile).resolve(strict=True)
    if not profile.is_dir():
        raise ValueError('Cemu profile must be a directory')
    settings_path = profile / 'settings.xml'
    controller_path = profile / 'controllerProfiles' / 'controller0.txt'
    controller_xml_path = profile / 'controllerProfiles' / 'controller0.xml'
    log_path = profile / 'log.txt'
    issues = []

    try:
        settings = ET.parse(settings_path).getroot()
    except (OSError, ET.ParseError) as error:
        raise ValueError(f'Cannot read Cemu settings.xml: {error}') from error
    enabled_pack_paths = [entry.get('filename', '') for entry in
                          settings.findall('./GraphicPack/Entry')]
    enabled_pack_paths = [p.replace('\\', '/') for p in enabled_pack_paths]
    controller_sources = []
    if controller_path.is_file():
        controller = _read_controller(controller_path)
        controller_sources.append('controller0.txt')
    elif controller_xml_path.is_file():
        try:
            controller = _read_controller_xml(controller_xml_path)
        except (ET.ParseError, OSError) as error:
            controller = {}
            issues.append(f'Cannot read controllerProfiles/controller0.xml: {error}')
        else:
            controller_sources.append('controller0.xml')
    else:
        controller = {}
    keyboard_profile = (controller.get('api', '').casefold() == 'keyboard' and
                        controller.get('emulate', '').casefold() in
                        {'wii u gamepad', 'wii u pro controller'})
    left_stick = {mapping: controller.get(mapping) == f'key_{key}'
                  for mapping, key in LEFT_STICK_KEYS_CEMU_126.items()}
    keyboard_left_stick = keyboard_profile and all(left_stick.values())
    gamepad_a_key = controller.get(1)
    gamepad_a_configured = keyboard_profile and gamepad_a_key == f'key_{GAMEPAD_A_KEY}'
    if not controller_sources and not any(
            'controllerProfiles/controller0.xml' in issue for issue in issues):
        issues.append('controllerProfiles/controller0.txt and controller0.xml are missing')
    if require_keyboard and not keyboard_left_stick:
        issues.append('WASD is not configured as the Wii U GamePad left stick')
    if require_gamepad_a and not gamepad_a_configured:
        issues.append('Z is not configured as the Wii U GamePad A button')

    rules = []
    for path in profile.glob('graphicPacks/*/rules.txt'):
        rules.append({'path': path.relative_to(profile).as_posix(),
                      'text': path.read_text(encoding='utf-8', errors='replace')})
    selected = None
    forbidden_configured = None
    if expected_pack:
        needle = expected_pack.casefold()
        selected = next((pack for pack in rules
                         if needle in pack['path'].casefold() or
                         needle in pack['text'].casefold()), None)
        if selected is None:
            issues.append(f'Expected graphic pack {expected_pack!r} has no local rules.txt')
        else:
            rules_path = selected['path'].replace('\\', '/')
            if not any(rules_path.casefold().endswith(p.casefold())
                       for p in enabled_pack_paths):
                issues.append(f'Expected graphic pack {expected_pack!r} is not enabled in settings.xml')
    if forbidden_pack:
        key = _pack_key(forbidden_pack)
        forbidden_configured = (
            any(key in _pack_key(path) for path in enabled_pack_paths) or
            any(key in _pack_key(pack['path']) or key in _pack_key(pack['text'])
                for pack in rules))
        if forbidden_configured:
            issues.append(f'Forbidden graphic pack {forbidden_pack!r} is present or enabled')

    archive_report = None
    if archive is not None:
        archive_path = Path(archive).resolve(strict=True)
        archive_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        archive_report = {'path': str(archive_path), 'sha256': archive_hash}
        if selected is None:
            issues.append('Cannot compare the archive without a selected expected pack')
        else:
            relative_pack = Path(selected['path']).parent
            packaged_archive = profile / relative_pack / 'content/Common/course_select/CS_W1.szs'
            try:
                packaged_hash = hashlib.sha256(packaged_archive.read_bytes()).hexdigest()
            except OSError as error:
                issues.append(f'Packaged CS_W1.szs is missing or unreadable: {error}')
            else:
                archive_report['profile_copy_sha256'] = packaged_hash
                archive_report['matches_profile_copy'] = archive_hash == packaged_hash
                if archive_hash != packaged_hash:
                    issues.append('Expected archive hash does not match the profile pack copy')

    log_text = log_path.read_text(encoding='utf-8', errors='replace') if log_path.is_file() else ''
    latest_title_start = log_text.rfind('------- Loaded title -------')
    current_run_log = log_text[latest_title_start:] if latest_title_start >= 0 else ''
    active_packs = PACK_LINE.findall(current_run_log)
    game_module_loaded = TARGET_MODULE.search(current_run_log) is not None
    title_started = '------- Run title -------' in current_run_log and game_module_loaded
    pack_active = (None if not log_text or expected_pack is None else
                   any(_pack_key(expected_pack) in _pack_key(name)
                       for name in active_packs))
    forbidden_active = (None if not log_text or forbidden_pack is None else
                        any(_pack_key(forbidden_pack) in _pack_key(name)
                            for name in active_packs))
    if require_run:
        if not log_path.is_file():
            issues.append('Cemu log.txt is missing; no run evidence is available')
        if not game_module_loaded:
            issues.append('NSMBU v64 module was not found in log.txt')
        if expected_pack and not pack_active:
            issues.append(f'Expected graphic pack {expected_pack!r} is not active in log.txt')
        if forbidden_pack and forbidden_active:
            issues.append(f'Forbidden graphic pack {forbidden_pack!r} is active in log.txt')

    save_comparison = None
    if compare_save_to is not None:
        reference_profile = Path(compare_save_to).resolve(strict=True)
        if not reference_profile.is_dir():
            raise ValueError('Save comparison reference must be a Cemu profile directory')
        current_saves = _save_inventory(profile)
        reference_saves = _save_inventory(reference_profile)
        matches = bool(current_saves) and current_saves == reference_saves
        save_comparison = {
            'reference_profile': str(reference_profile),
            'profile_files': current_saves,
            'reference_files': reference_saves,
            'matches': matches,
        }
        if not current_saves:
            issues.append('Current Cemu profile has no NSMBU user-save files to compare')
        elif not reference_saves:
            issues.append('Reference Cemu profile has no NSMBU user-save files to compare')
        elif not matches:
            issues.append('NSMBU user-save files differ from the reference profile')

    return {
        'profile': str(profile),
        'enabled_pack_paths': enabled_pack_paths,
        'expected_pack': expected_pack,
        'forbidden_pack': forbidden_pack,
        'active_packs_in_log': active_packs,
        'controller_api': controller.get('api'),
        'controller_emulated_device': controller.get('emulate'),
        'controller_sources': controller_sources,
        'left_stick_key_mapping': left_stick,
        'keyboard_left_stick_configured': keyboard_left_stick,
        'gamepad_a_key_mapping': gamepad_a_key,
        'gamepad_a_configured': gamepad_a_configured,
        'game_module_loaded': game_module_loaded,
        'title_started': title_started,
        'expected_pack_active_in_log': pack_active,
        'forbidden_pack_present_or_enabled': forbidden_configured,
        'forbidden_pack_active_in_log': forbidden_active,
        'run_log_present': bool(current_run_log),
        'archive': archive_report,
        'save_comparison': save_comparison,
        'gameplay_verified': False,
        'issues': issues,
        'ready': not issues,
        'note': ('Preflight and boot-log checks only. No controller input, map movement, '
                 'level launch, progression, persistence, or terrain behavior is observed.'),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', type=Path)
    parser.add_argument('--expect-pack', help='Pack directory or rules text to require')
    parser.add_argument('--forbid-pack', help='Pack directory or rules text that must be absent')
    parser.add_argument('--archive', type=Path,
                        help='Expected CS_W1.szs; hash-checked against the profile copy')
    parser.add_argument('--require-keyboard', action='store_true',
                        help='Require WASD to map to the GamePad left stick')
    parser.add_argument('--require-gamepad-a', action='store_true',
                        help='Require Z to map to the GamePad A button for level-start tests')
    parser.add_argument('--require-run', action='store_true',
                        help='Require v64 and the expected pack in log.txt')
    parser.add_argument('--compare-save-to', type=Path, metavar='PROFILE',
                        help='Require byte-identical NSMBU user-save files to another Cemu profile')
    args = parser.parse_args(argv)
    try:
        report = inspect_profile(args.profile, expected_pack=args.expect_pack,
                                 archive=args.archive,
                                 forbidden_pack=args.forbid_pack,
                                 require_keyboard=args.require_keyboard,
                                 require_gamepad_a=args.require_gamepad_a,
                                 require_run=args.require_run,
                                 compare_save_to=args.compare_save_to)
    except (OSError, ValueError) as error:
        parser.exit(2, f'Preflight failed: {error}\n')
    print(json.dumps(report, indent=2))
    if not report['ready']:
        parser.exit(1, 'Cemu preflight found issues.\n')


if __name__ == '__main__':
    main()
