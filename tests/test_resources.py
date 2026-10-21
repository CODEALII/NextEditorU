import csv
import io
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from worldstudio.archive import Archive, compress, decompress
from worldstudio.project import WorldProject, Table, sha
from worldstudio.__main__ import chain_demo, direct_route_demo, DEFAULT_SOURCE


def fixture():
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


class ArchiveTests(unittest.TestCase):
    def test_roundtrip_and_growing_entry_preserves_other_offset(self):
        a = Archive(fixture())
        self.assertEqual(a.replace({}), a.original)
        b = Archive(a.replace({'one': b'expanded resource'}))
        self.assertEqual(b.read('one'), b'expanded resource')
        self.assertEqual(b.read('two'), b'xyz')
        self.assertEqual(a.entries['two'].start, b.entries['two'].start)
        with self.assertRaises(ValueError):
            a.replace({'one': bytes(33)})

    def test_reject_bad_streams(self):
        for data in (b'Yaz0', b'Yaz0' + struct.pack('>I', 3) + bytes(8) + b'\x00\x10\x00', b'garbage'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                Archive(data)

    def test_yaz0_overlap(self):
        # Literal A then an overlapping length=4, distance=1 reference.
        raw = b'Yaz0' + struct.pack('>I', 5) + bytes(8) + b'\x80A\x20\x00'
        self.assertEqual(decompress(raw), b'AAAAA')
        self.assertEqual(decompress(compress(bytes(range(256)))), bytes(range(256)))

    def test_csv_lossless_and_japanese(self):
        original = '0,W101,,"W102","RW101W102",,"",,\r\n'.encode('cp932')
        t = Table(original)
        self.assertEqual(t.encode(), original)
        t.rows[0][2] = 'fix,stop'
        loaded = Table(t.encode())
        self.assertEqual(loaded.rows, t.rows)
        self.assertIn(b'"W102","RW101W102"', t.encode())
        t.rows[0][3] = 'W103'
        self.assertIn(b'"W103"', t.encode())
        road = Table('RW101W102,ジャンプ,\r\n'.encode('cp932'))
        self.assertEqual(road.rows[0][1], 'ジャンプ')


@unittest.skipUnless(DEFAULT_SOURCE.is_file(), 'Local user-owned dump not available')
class LocalIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = DEFAULT_SOURCE.read_bytes()

    def test_lossless_dump_and_actual_patch(self):
        p = WorldProject.open(DEFAULT_SOURCE)
        self.assertEqual(p.validate(), [])
        self.assertEqual(p.points.encode(), p.archive.read(p.point_name))
        self.assertEqual(p.routes.encode(), p.archive.read(p.route_name))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            chain_demo(p)
            self.assertEqual(p.validate(), [])
            p.save(out / 'project.json')
            loaded = WorldProject.load(out / 'project.json')
            manifest = loaded.export(out / 'CS_W1.szs')
            changed = Archive((out / 'CS_W1.szs').read_bytes())
            self.assertEqual(manifest['changed_entries'], [p.point_name])
            self.assertEqual(changed.read(p.model_name), p.model)
            rows = Table(changed.read(p.point_name)).rows
            self.assertEqual(rows[2][3:5], ['W103', 'RW102W1T0,RW1T0W103'])
            self.assertEqual(rows[0], p.points.initial[0])
            self.assertEqual(len(rows), len(p.points.initial))
            self.assertEqual(rows[9], p.points.initial[9])
            with self.assertRaises(FileExistsError):
                loaded.export(out / 'CS_W1.szs')
        self.assertEqual(DEFAULT_SOURCE.read_bytes(), self.original)

    def test_bone_patch_changes_only_intended_bytes(self):
        p = WorldProject.open(DEFAULT_SOURCE)
        bone = p.skeletons.unique('W101')
        new = [p.positions['W101'][0] + 12, *p.positions['W101'][1:]]
        result = p.skeletons.patch_positions({'W101': new})
        changed = {i for i,(a,b) in enumerate(zip(p.model, result)) if a != b}
        self.assertTrue(changed)
        self.assertTrue(changed <= set(range(bone.offset + 48, bone.offset + 60)) | set(range(bone.offset + 16, bone.offset + 20)))
        from worldstudio.bfres import Skeletons
        self.assertAlmostEqual(Skeletons(result).unique('W101').position[0], new[0], places=3)

    def test_invalid_new_references_and_index_remap_blocked(self):
        p = WorldProject.open(DEFAULT_SOURCE)
        p.points.rows[1][3] = 'W199'
        self.assertTrue(any('W199' in e for e in p.validate()))
        p.points.rows.pop(0)
        self.assertTrue(any('indices' in e for e in p.validate()))
        with self.assertRaises(ValueError):
            p.export(Path(tempfile.gettempdir()) / 'never-written.szs')

    def test_real_world_route_only_disconnect_blocks_export(self):
        from worldstudio.graph_validation import validate_native_world

        p = WorldProject.open(DEFAULT_SOURCE)
        world_prefix = 'W' + p.point_name.split('pointW', 1)[1][0]
        disconnected = None
        for index, route in enumerate(p.routes.rows):
            candidate = p.routes.rows[:index] + p.routes.rows[index + 1:]
            issues = validate_native_world(
                p.points.rows, candidate, known_references=p.references,
                initial_points=p.points.initial, initial_routes=p.routes.initial,
                world_prefix=world_prefix,
            )
            issue = next((item for item in issues
                          if 'no directed route-segment path' in item), None)
            if issue:
                disconnected = candidate, issue
                break
        self.assertIsNotNone(disconnected, 'expected a stock route to carry a reachable destination')
        p.routes.rows = disconnected[0]
        self.assertIn(disconnected[1], p.validate())
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'disconnected.szs'
            with self.assertRaisesRegex(ValueError, 'no directed route-segment path'):
                p.export(output)
            self.assertFalse(output.exists())

    def test_game_tree_protected_for_projects_and_exports(self):
        p = WorldProject.open(DEFAULT_SOURCE)
        with self.assertRaises(ValueError):
            p.save(p.game_root / 'code' / 'do-not-write.json')
        with self.assertRaises(ValueError):
            p.export(p.game_root / 'content' / 'do-not-write.szs')

    def test_direct_macro_route_export_and_project_roundtrip(self):
        from worldstudio.bfres import Skeletons
        p = direct_route_demo(WorldProject.open(DEFAULT_SOURCE))
        self.assertEqual(p.validate(), [])
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            p.save(folder / 'direct.json')
            restored = WorldProject.load(folder / 'direct.json')
            self.assertEqual(restored.bone_renames, p.bone_renames)
            manifest = restored.export(folder / 'CS_W1.szs')
            self.assertEqual(set(manifest['changed_entries']), {p.point_name, p.route_name, p.model_name})
            a = Archive((folder / 'CS_W1.szs').read_bytes())
            s = Skeletons(a.read(p.model_name))
            self.assertIn('RW102W103', s.bones)
            self.assertNotIn('RW102W1T0', s.bones)
            self.assertIn('W1T0', s.bones)
            self.assertEqual(Table(a.read(p.point_name)).rows[2][3:5], ['W103', 'RW102W103'])
            self.assertIn(['RK02hW103', '坂', ''], Table(a.read(p.route_name)).rows)
            self.assertEqual(s.unique('W101').index, p.skeletons.unique('W101').index)
        self.assertEqual(DEFAULT_SOURCE.read_bytes(), self.original)


class ProjectGraphValidationTests(unittest.TestCase):
    def test_route_only_disconnect_blocks_project_export(self):
        point_rows = [
            ['0', 'W101', '', 'W102', 'RW101W102', '', '', '', ''],
            ['1', 'W102', '', 'W103', 'RW102W103', '', '', '', ''],
            ['2', 'W103', '', '', '', '', '', '', ''],
        ]
        route_rows = [['RW101W102', 'road', ''], ['RW102W103', 'road', '']]
        project = object.__new__(WorldProject)
        project.camera_edits = {}
        project.bone_renames = []
        project.references = {'W101', 'W102', 'W103', *[row[0] for row in route_rows]}
        project.skeletons = SimpleNamespace(
            models={}, bones=set(project.references),
        )
        project.points = SimpleNamespace(
            rows=[row[:] for row in point_rows],
            initial=[row[:] for row in point_rows],
        )
        project.routes = SimpleNamespace(
            rows=[route_rows[0][:]],
            initial=[row[:] for row in route_rows],
        )
        project.point_name = 'pointW1.csv'

        issue = 'W102: no directed route-segment path to W103'
        self.assertIn(issue, project.validate())
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'disconnected.szs'
            with self.assertRaisesRegex(ValueError, 'no directed route-segment path'):
                project.export(output)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
