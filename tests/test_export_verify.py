import json
from pathlib import Path
import struct
import tempfile
import unittest

from worldstudio.archive import Archive, compress
from worldstudio.export_verify import verify_export
from worldstudio.project import sha


def archive_fixture():
    names = b'one\0two\0'
    data = bytearray(160)
    struct.pack_into('>4sHHIIHH', data, 0, b'SARC', 20, 0xfeff, len(data), 96, 0x100, 0)
    struct.pack_into('>4sHHI', data, 20, b'SFAT', 12, 2, 0x65)
    struct.pack_into('>4I', data, 32, 1, 0x01000000, 0, 3)
    struct.pack_into('>4I', data, 48, 2, 0x01000001, 32, 35)
    struct.pack_into('>4sHH', data, 64, b'SFNT', 8, 0)
    data[72:80] = names
    data[96:99] = b'abc'
    data[128:131] = b'xyz'
    return compress(bytes(data))


class ExportProjectFixture:
    def __init__(self):
        self.archive = Archive(archive_fixture())
        self.source_sha256 = sha(self.archive.original)

    def export(self, output):
        output = Path(output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        changes = {'one': b'new'}
        output_bytes = self.archive.replace(changes)
        output.write_bytes(output_bytes)
        camera_bytes = b'offset-data'
        (output.parent / 'MarioOffsetDataW1.bin').write_bytes(camera_bytes)
        entry_changes = {}
        for name, value in changes.items():
            original = self.archive.read(name)
            if value != original:
                entry_changes[name] = {
                    'source_sha256': sha(original),
                    'output_sha256': sha(value),
                    'source_size_bytes': len(original),
                    'output_size_bytes': len(value),
                    'size_delta_bytes': len(value) - len(original),
                }
        manifest = {
            'source_sha256': self.source_sha256,
            'output_sha256': sha(output_bytes),
            'output': str(output),
            'changed_entries': list(entry_changes),
            'entry_changes': entry_changes,
            'bfres_unchanged': True,
            'terrain_exported': False,
            'geometry': None,
            'bone_renames': [],
            'camera_files': {
                'MarioOffsetDataW1.bin': {
                    'source_sha256': sha(b'original-offset-data'),
                    'output_sha256': sha(camera_bytes),
                },
            },
            'game_tested': False,
        }
        output.with_suffix(output.suffix + '.manifest.json').write_text(
            json.dumps(manifest), encoding='utf-8')
        return manifest


class ExportVerificationTests(unittest.TestCase):
    def test_reimports_archive_and_compares_manifest_to_fresh_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'world.szs'
            project = ExportProjectFixture()
            project.export(output)

            result = verify_export(project, output)

            self.assertTrue(result['verified'])
            self.assertEqual(result['archive_entries'], 2)
            self.assertEqual(result['changed_entries'], ['one'])
            self.assertEqual(result['camera_files'], ['MarioOffsetDataW1.bin'])
            self.assertFalse(result['game_tested'])

    def test_rejects_changed_reimported_entry_even_when_manifest_hash_is_updated(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'world.szs'
            project = ExportProjectFixture()
            project.export(output)
            altered = Archive(output.read_bytes()).replace({'two': b'bad'})
            output.write_bytes(altered)
            manifest_path = output.with_suffix(output.suffix + '.manifest.json')
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest['output_sha256'] = sha(altered)
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'two'):
                verify_export(project, output)

    def test_rejects_manifest_from_another_path_or_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'world.szs'
            project = ExportProjectFixture()
            project.export(output)
            manifest_path = output.with_suffix(output.suffix + '.manifest.json')
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest['source_sha256'] = '0' * 64
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'does not match this project source'):
                verify_export(project, output)

    def test_rejects_changed_camera_companion_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'world.szs'
            project = ExportProjectFixture()
            project.export(output)
            (output.parent / 'MarioOffsetDataW1.bin').write_bytes(b'wrong-offset')

            with self.assertRaisesRegex(ValueError, 'Camera companion output differs'):
                verify_export(project, output)


if __name__ == '__main__':
    unittest.main()
