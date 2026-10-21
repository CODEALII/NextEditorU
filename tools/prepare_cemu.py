"""Prepare an isolated portable Cemu test folder without launching it.

Inputs are only read/copied. Existing destinations are refused. No saves,
controller profiles, settings or enabled packs from the source are imported.
Schema evidence: inspected local Cemu 1.26.2f controller0.xml/settings.xml;
https://github.com/cemu-project/Cemu/blob/main/src/input/InputManager.cpp
https://github.com/cemu-project/Cemu/blob/main/src/input/api/Keyboard/KeyboardController.cpp
https://github.com/cemu-project/Cemu/blob/main/src/input/emulated/VPADController.h
https://github.com/cemu-project/Cemu/blob/main/src/gui/wxgui/wxWindowSystem.cpp
https://github.com/cemu-project/Cemu/blob/main/src/config/LaunchSettings.cpp
Current upstream confirms schema, but the installed legacy binary still needs
runtime confirmation. The generated profile uses Windows virtual key codes.
"""
from pathlib import Path
import argparse
import json
import shutil
import xml.etree.ElementTree as ET


# Cemu 1.26.2f's live Input Settings UI showed ID 17 as Right Axis click and
# IDs 18-21 as Left Axis up/down/left/right. Use those runtime-confirmed IDs in
# both formats; newer VPADController.h numbering does not match this binary.
KEYBOARD_BINDINGS = {1: 90, 2: 88, 3: 67, 4: 86, 5: 81, 6: 69,
                     7: 49, 8: 51, 9: 13, 10: 8, 11: 38, 12: 40,
                     13: 37, 14: 39, 18: 87, 19: 83, 20: 65, 21: 68}


def legacy_keyboard_profile(controller_type="Wii U GamePad"):
    """Cemu 1.26 INI; decimal key_ values verified by v2.0 migration code."""
    header = (f"[General]\nemulate = {controller_type}\napi = Keyboard\n"
              "\n[Controller]\nrumble = 0\nleftRange = 1\nrightRange = 1\n"
              "leftDeadzone = 0.15\nrightDeadzone = 0.15\nbuttonThreshold = 0.5\n")
    return header + "".join(f"{mapping} = key_{button}\n"
                            for mapping, button in KEYBOARD_BINDINGS.items())


def xml_write(path, root):
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def configure(out: Path, *, enabled_packs=("WorldStudioChain", "CrashFix"),
              controller_type="Wii U GamePad"):
    """Write new configs only; safe for a folder pre-created by the caller."""
    if controller_type not in {"Wii U GamePad", "Wii U Pro Controller"}:
        raise ValueError("Controller type must be Wii U GamePad or Wii U Pro Controller")
    for name in ("settings.xml", "controllerProfiles/controller0.xml", "controllerProfiles/controller0.txt"):
        if (out / name).exists():
            raise FileExistsError(out / name)
    (out / "mlc01").mkdir(exist_ok=True)
    root = ET.Element("content")
    values = {"logflag": "0", "mlc_path": str(out / "mlc01"),
              "permanent_storage": "false", "language": "0",
              "use_discord_presence": "false", "check_update": "false",
              # Legacy Cemu: gp_download means setup wizard already shown.
              # It does not enable background graphic-pack downloading.
              "gp_download": "true", "fullscreen": "false",
              "console_language": "1", "open_pad": "false"}
    for name, value in values.items():
        ET.SubElement(root, name).text = value
    graphics = ET.SubElement(root, "Graphic")
    ET.SubElement(graphics, "api").text = "1"  # Vulkan, observed local setting.
    ET.SubElement(graphics, "GX2DrawdoneSync").text = "true"
    packs = ET.SubElement(root, "GraphicPack")
    for name in enabled_packs:
        ET.SubElement(packs, "Entry", filename=f"graphicPacks\\{name}\\rules.txt")
    account = ET.SubElement(root, "Account")
    ET.SubElement(account, "PersistentId").text = "2147483649"
    ET.SubElement(account, "OnlineEnabled").text = "false"
    xml_write(out / "settings.xml", root)

    root = ET.Element("emulated_controller")
    ET.SubElement(root, "type").text = controller_type
    controller = ET.SubElement(root, "controller")
    for name, value in (("api", "Keyboard"), ("uuid", "keyboard"),
                        ("display_name", "Keyboard")):
        ET.SubElement(controller, name).text = value
    mappings = ET.SubElement(controller, "mappings")
    # Mapping IDs are verified against the installed Cemu 1.26.2f UI.
    for mapping, button in KEYBOARD_BINDINGS.items():
        entry = ET.SubElement(mappings, "entry")
        ET.SubElement(entry, "mapping").text = str(mapping)
        ET.SubElement(entry, "button").text = str(button)
    (out / "controllerProfiles").mkdir(exist_ok=True)
    xml_write(out / "controllerProfiles/controller0.xml", root)
    # Cemu 1.26 reads INI; later versions read XML or migrate INI when absent.
    # Both represent the same mappings. Never use controller button bitmasks
    # for keyboard mappings: the legacy prefix is key_, followed by decimal VK.
    (out / "controllerProfiles/controller0.txt").write_text(
        legacy_keyboard_profile(controller_type), encoding="utf-8")


def prepare(cemu: Path, patch: Path | None, out: Path, *, baseline=False,
            pack_name="WorldStudioChain", controller_type="Wii U GamePad"):
    if controller_type not in {"Wii U GamePad", "Wii U Pro Controller"}:
        raise ValueError("Controller type must be Wii U GamePad or Wii U Pro Controller")
    cemu, out = cemu.resolve(), out.resolve()
    source = cemu.parent if cemu.is_file() else cemu
    exe = source / "Cemu.exe"
    patch = patch.resolve() if patch is not None else None
    if not exe.is_file():
        raise ValueError("Cemu.exe is required")
    if baseline and patch is not None:
        raise ValueError("A clean baseline does not use --patch")
    if not pack_name or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in pack_name):
        raise ValueError("Graphic pack name may contain only ASCII letters, digits, dash and underscore")
    if not baseline and (patch is None or not (patch / "content").is_dir()):
        raise ValueError("A patched test folder needs a patch/content directory")
    if out.exists():
        raise FileExistsError(f"Refusing existing output: {out}")
    # Do not allow the output inside either input tree.
    for original in (source, patch):
        if original is None:
            continue
        if out == original or original in out.parents:
            raise ValueError("Output must be separate from input trees")
    crashfix = source / "graphicPacks/downloadedGraphicPacks/NewSuperMarioBrosU/Workarounds/CrashFix"
    if not crashfix.is_dir():
        crashfix = source / "graphicPacks/CrashFix"
    if not (crashfix / "rules.txt").is_file():
        raise FileNotFoundError("Source Cemu CrashFix graphic pack not found")
    out.mkdir(parents=True)
    shutil.copy2(exe, out / "Cemu.exe")
    for dll in source.glob("*.dll"):
        shutil.copy2(dll, out / dll.name)
    if (source / "resources").is_dir():
        shutil.copytree(source / "resources", out / "resources")
    shutil.copytree(crashfix, out / "graphicPacks/CrashFix")
    enabled_packs = ("CrashFix",) if baseline else (pack_name, "CrashFix")
    if not baseline:
        pack = out / "graphicPacks" / pack_name
        shutil.copytree(patch / "content", pack / "content")
        # Generated test pack only; no unknown source graphic-pack settings copied.
        (pack / "rules.txt").write_text(
            '[Definition]\ntitleIds = 0005000010101D00\n'
            f'name = {pack_name}\n'
            f'path = "New Super Mario Bros. U/Mods/{pack_name}"\n'
            'description = Experimental World Studio route test.\nversion = 6\ndefault = 1\n', encoding="utf-8")
    # System font installation is optional and read-only copied. Never copy saves
    # or installed game updates, which could override the requested input dump.
    sys_title = source / "mlc01/sys/title"
    if sys_title.is_dir():
        shutil.copytree(sys_title, out / "mlc01/sys/title")
    configure(out, enabled_packs=enabled_packs, controller_type=controller_type)
    (out / "launch.ps1").write_text(
        'param([Parameter(Mandatory=$true)][string]$GameRpx)\n'
        '$ErrorActionPreference = "Stop"\n'
        'if (-not (Test-Path -LiteralPath $GameRpx -PathType Leaf)) { throw "RPX not found" }\n'
        'Push-Location -LiteralPath $PSScriptRoot\n'
        'try { & "$PSScriptRoot/Cemu.exe" -g $GameRpx -m "$PSScriptRoot/mlc01" }\n'
        'finally { Pop-Location }\n', encoding="utf-8")
    purpose = (f"Clean baseline comparison folder. {pack_name} is disabled.\n"
               if baseline else "Patched experimental topology test folder.\n")
    pack_list = ", ".join(enabled_packs)
    (out / "README.txt").write_text(
        purpose
        + "Isolated test folder. No emulator has been launched by this tool.\n"
        + "Run launch.ps1 -GameRpx <absolute path to supplied code/red-pro2.rpx>\n"
        + "Keyboard: Z=A, X=B, C=X, V=Y, Enter=Plus; arrows=D-pad. Verify WASD is left stick in Input Settings.\n"
        + "Fresh saves and cache stay here. Source game files are not modified.\n"
        + f"Enabled graphic packs: {pack_list}. Check log.txt after launch.\n",
        encoding="utf-8")
    return {"output": str(out), "settings": str(out / "settings.xml"),
            "launch": str(out / "launch.ps1"), "launched": False,
            "baseline": baseline, "enabled_packs": list(enabled_packs)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cemu", required=True, type=Path)
    parser.add_argument("--patch", type=Path,
                        help="Patch folder with content/; required for patched tests")
    parser.add_argument("--pack-name", default="WorldStudioChain",
                        help="Cemu graphic-pack folder name (default: WorldStudioChain)")
    parser.add_argument("--controller-type", choices=("Wii U GamePad", "Wii U Pro Controller"),
                        default="Wii U GamePad",
                        help="Emulated player controller (default: Wii U GamePad)")
    parser.add_argument("--baseline", action="store_true",
                        help="Prepare a clean baseline with CrashFix only; does not use --patch")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.baseline and args.patch is not None:
        parser.error("--baseline cannot be combined with --patch")
    if not args.baseline and args.patch is None:
        parser.error("--patch is required unless --baseline is selected")
    print(json.dumps(prepare(args.cemu, args.patch, args.out,
                             baseline=args.baseline,
                             pack_name=args.pack_name,
                             controller_type=args.controller_type), indent=2))
