from pathlib import Path
import tempfile
import unittest
from worldstudio.__main__ import DEFAULT_SOURCE
from worldstudio.camera import OffsetTable
from worldstudio.project import WorldProject


@unittest.skipUnless(DEFAULT_SOURCE.is_file(), 'Local user-owned game dump unavailable')
class CameraProjectTests(unittest.TestCase):
    def test_companion_patch_roundtrip_and_no_archive_changes(self):
        project = WorldProject.open(DEFAULT_SOURCE)
        name = 'MarioOffsetDataW1.bin'
        original = project.camera_original[name]
        table = project.camera_table(name)
        record = table.record(0, 1)
        changed = (record.vector[0] + 10, *record.vector[1:])
        project.set_camera_vector(name, 0, 1, changed)
        self.assertEqual(project.validate(), [])
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            project.save(folder / 'camera.json')
            loaded = WorldProject.load(folder / 'camera.json')
            self.assertEqual(loaded.camera_edits, project.camera_edits)
            manifest = loaded.export(folder / 'content/Common/course_select/CS_W1.szs')
            self.assertEqual(manifest['changed_entries'], [])
            self.assertEqual((folder / 'content/Common/course_select/CS_W1.szs').read_bytes(), DEFAULT_SOURCE.read_bytes())
            encoded = (folder / 'content/Common/course_select' / name).read_bytes()
            parsed = OffsetTable.parse(encoded, 'mario')
            self.assertEqual(parsed.record(0, 1).vector, changed)
            self.assertEqual(parsed.record(0, 1).name_raw, record.name_raw)
            self.assertEqual(parsed.record(0, 1).unknown_u32, record.unknown_u32)
            allowed = set(range(21 + 5, 21 + 17))
            self.assertTrue(all(a == b or i in allowed for i,(a,b) in enumerate(zip(original, encoded))))
            self.assertEqual(set(manifest['camera_files']), {name})
        self.assertEqual((DEFAULT_SOURCE.parent / name).read_bytes(), original)

    def test_existing_companion_blocks_all_outputs(self):
        project = WorldProject.open(DEFAULT_SOURCE)
        name = 'LookOffsetDataW1.bin'
        project.set_camera_vector(name, 0, 0, (1, 2, 3))
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / name).write_bytes(b'preserve existing user export')
            with self.assertRaises(FileExistsError):
                project.export(folder / 'CS_W1.szs')
            self.assertFalse((folder / 'CS_W1.szs').exists())
            self.assertEqual((folder / name).read_bytes(), b'preserve existing user export')


if __name__ == '__main__':
    unittest.main()
