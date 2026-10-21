"""Read-only reimport checks for an exported world project archive."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile

from .archive import Archive
from .project import sha


_MANIFEST_FIELDS = (
    'source_sha256', 'changed_entries', 'entry_changes', 'bfres_unchanged',
    'terrain_exported', 'geometry', 'graph_validation', 'bone_renames', 'camera_files',
)


def verify_export(project, output, *, graph_profile=None):
    """Compare an exported archive with a fresh project export and its manifest.

    This verifies local package consistency and re-importability. It does not
    execute the game or validate runtime movement, progression, or rendering.
    """
    output = Path(output).resolve()
    manifest_path = output.with_suffix(output.suffix + '.manifest.json')
    try:
        output_bytes = output.read_bytes()
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except FileNotFoundError as error:
        raise ValueError(f'Missing exported archive or manifest: {error.filename}') from error
    except json.JSONDecodeError as error:
        raise ValueError(f'Export manifest is not valid JSON: {error}') from error

    if not isinstance(manifest, dict):
        raise ValueError('Export manifest must contain a JSON object')
    if manifest.get('output') != str(output):
        raise ValueError('Export manifest points to a different output path')
    if manifest.get('source_sha256') != project.source_sha256:
        raise ValueError('Export manifest does not match this project source')
    if manifest.get('output_sha256') != sha(output_bytes):
        raise ValueError('Exported archive hash does not match its manifest')
    if manifest.get('graph_validation') is not None and graph_profile is None:
        raise ValueError('This export used a graph profile; pass --profile to verify it')

    actual_archive = Archive(output_bytes)
    with tempfile.TemporaryDirectory(prefix='worldstudio-verify-') as temporary:
        expected_path = Path(temporary) / output.name
        if graph_profile is None:
            expected_manifest = project.export(expected_path)
        else:
            expected_manifest = project.export(expected_path, graph_profile=graph_profile)
        expected_archive = Archive(expected_path.read_bytes())
        if set(actual_archive.entries) != set(expected_archive.entries):
            missing = sorted(set(expected_archive.entries) - set(actual_archive.entries))
            unexpected = sorted(set(actual_archive.entries) - set(expected_archive.entries))
            raise ValueError(f'Export archive member list differs; missing={missing}, unexpected={unexpected}')

        changed = []
        for name in expected_archive.entries:
            if actual_archive.read(name) != expected_archive.read(name):
                changed.append(name)
        if changed:
            raise ValueError('Reimported archive differs from the project export in: ' + ', '.join(changed[:20]))

        for field in _MANIFEST_FIELDS:
            if manifest.get(field) != expected_manifest.get(field):
                raise ValueError(f'Export manifest field {field!r} differs from the project export')

        camera_files = expected_manifest.get('camera_files', {})
        for name, camera_report in camera_files.items():
            camera_path = output.parent / name
            expected_camera = Path(temporary) / name
            try:
                actual_camera_bytes = camera_path.read_bytes()
                expected_camera_bytes = expected_camera.read_bytes()
            except FileNotFoundError as error:
                raise ValueError(f'Missing camera companion output: {error.filename}') from error
            if actual_camera_bytes != expected_camera_bytes:
                raise ValueError(f'Camera companion output differs from the project export: {name}')
            if camera_report.get('output_sha256') != sha(actual_camera_bytes):
                raise ValueError(f'Camera companion hash does not match its manifest: {name}')

    return {
        'verified': True,
        'output': str(output),
        'output_sha256': sha(output_bytes),
        'archive_entries': len(actual_archive.entries),
        'changed_entries': manifest.get('changed_entries', []),
        'camera_files': sorted(manifest.get('camera_files', {})),
        'graph_validation': manifest.get('graph_validation'),
        'game_tested': False,
        'note': 'Local archive and companion outputs match a fresh project export; game behavior is not tested.',
    }
