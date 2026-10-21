import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from worldstudio.editor import obj_geometry_summary, read_obj
from worldstudio.mesh import transform_obj_geometry


class ObjAttributeTests(unittest.TestCase):
    def parse(self, source, include_attributes=True):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'seam.obj'
            path.write_text(source,encoding='utf-8')
            return read_obj(path,include_attributes=include_attributes)

    def test_corner_uv_and_normal_seams_split_vertices(self):
        source='''
v 0 0 0
v 1 0 0
v 1 0 1
v 0 0 1
vt 0 0
vt 1 0
vt 1 1
vt 0 1
vt .5 .5
vn 0 1 0
f 1/1/1 2/2/1 3/3/1
f 1/5/1 3/3/1 4/4/1
'''
        vertices,faces,uvs,normals=self.parse(source)
        self.assertEqual(len(vertices),5)
        self.assertEqual(faces,[(0,1,2),(3,2,4)])
        self.assertEqual(uvs[0],(0.,0.))
        self.assertEqual(uvs[3],(.5,.5))
        self.assertTrue(all(value==(0.,1.,0.) for value in normals))

    def test_negative_vertex_indices_and_missing_attributes(self):
        vertices,faces,uvs,normals=self.parse('''
v 0 0 0
v 1 0 0
v 0 0 1
f -3 -2 -1
''')
        self.assertEqual(len(vertices),3)
        self.assertEqual(faces,[(0,1,2)])
        self.assertEqual(uvs,[None,None,None])
        self.assertEqual(normals,[None,None,None])

    def test_preview_read_keeps_simple_vertex_face_shape(self):
        vertices,faces=self.parse('''
v 0 0 0
v 1 0 0
v 0 0 1
vt 0 0
vt 1 0
vt 0 1
f 1/1 2/2 3/3
''',include_attributes=False)
        self.assertEqual(len(vertices),3)
        self.assertEqual(faces,[(0,1,2)])

    def test_bad_attribute_index_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'missing texture'):
            self.parse('''
v 0 0 0
v 1 0 0
v 0 0 1
f 1/1 2/1 3/1
''')

    def test_import_limits_file_size_line_size_and_record_counts(self):
        with patch('worldstudio.editor.MAX_OBJ_FILE_BYTES', 7):
            with self.assertRaisesRegex(ValueError, 'file-size limit'):
                self.parse('v 0 0 0\n')
        with patch('worldstudio.editor.MAX_OBJ_LINE_BYTES', 4):
            with self.assertRaisesRegex(ValueError, 'line limit'):
                self.parse('v 0 0 0\n')
        with patch('worldstudio.editor.MAX_OBJ_RECORDS', 3):
            with self.assertRaisesRegex(ValueError, 'vertex-record limit'):
                self.parse('''
v 0 0 0
v 1 0 0
v 0 0 1
v 1 1 1
''')
        with patch('worldstudio.editor.MAX_OBJ_LINES', 1):
            with self.assertRaisesRegex(ValueError, 'line limit'):
                self.parse('# first line\n# second line\n')

    def test_import_limits_polygon_and_total_face_corners(self):
        source = '''
v 0 0 0
v 1 0 0
v 1 0 1
v 0 0 1
f 1 2 3 4 1
'''
        with patch('worldstudio.editor.MAX_FACE_CORNERS', 4):
            with self.assertRaisesRegex(ValueError, '4-corner limit'):
                self.parse(source)
        with patch('worldstudio.editor.MAX_OBJ_TOTAL_FACE_CORNERS', 5):
            with self.assertRaisesRegex(ValueError, 'total face-corner limit'):
                self.parse(source.replace('f 1 2 3 4 1', 'f 1 2 3\nf 2 3 4'))

    def test_attribute_seam_splitting_obeys_vertex_budget(self):
        source = '''
v 0 0 0
v 1 0 0
v 0 0 1
vt 0 0
vt 1 0
vt 0 1
f 1/1 2/2 3/3
f 1/2 2/3 3/1
'''
        with patch('worldstudio.editor.MAX_OBJ_RECORDS', 3):
            with self.assertRaisesRegex(ValueError, 'attribute-split vertex limit'):
                self.parse(source)

    def test_import_summary_reports_source_vertices_and_polygons(self):
        vertices, faces = self.parse('''
v 0 0 0
v 1 0 0
v 0 0 1
f 1 2 3
''', include_attributes=False)
        self.assertEqual(obj_geometry_summary(vertices, faces), '3 vertices · 1 polygon face')

    def test_checked_in_island_obj_uses_the_bounded_attribute_import_path(self):
        source = Path(__file__).resolve().parents[1] / 'examples' / 'island-game.obj'
        vertices, faces, uvs, normals = read_obj(source, include_attributes=True)
        self.assertEqual((len(vertices), len(faces)), (29, 54))
        self.assertTrue(all(len(face) == 3 for face in faces))
        self.assertEqual(len(uvs), len(normals))
        self.assertEqual(sum(max(0, len(face) - 2) for face in faces), 54)

    def test_z_up_conversion_applies_scale_rotation_offset_and_preserves_attributes(self):
        vertices = [(0., 0., 0.), (1., 0., 0.), (0., 0., 1.)]
        faces = [(0, 1, 2)]
        uvs = [(0., 0.), (1., 0.), (0., 1.)]
        normals = [(0., 0., 1.)] * 3
        transformed = transform_obj_geometry(
            vertices, faces, uvs, normals, scale=(2., 2., 2.),
            rotation_degrees=(-90., 0., 0.), translation=(1., 2., 3.))
        out_vertices, out_faces, out_uvs, out_normals = transformed
        for actual, expected in zip(out_vertices, [(1., 2., 3.), (3., 2., 3.), (1., 4., 3.)]):
            for value, target in zip(actual, expected):
                self.assertAlmostEqual(value, target)
        self.assertEqual(out_faces, faces)
        self.assertEqual(out_uvs, uvs)
        for actual in out_normals:
            self.assertAlmostEqual(actual[0], 0.)
            self.assertAlmostEqual(actual[1], 1.)
            self.assertAlmostEqual(actual[2], 0.)

    def test_obj_transform_uses_inverse_transpose_for_scaled_normals(self):
        _, _, _, normals = transform_obj_geometry(
            [(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)], [(0, 1, 2)], None,
            [(1., 1., 0.)] * 3, scale=(2., 1., 1.))
        self.assertAlmostEqual(normals[0][0], 1 / (5 ** .5))
        self.assertAlmostEqual(normals[0][1], 2 / (5 ** .5))
        self.assertEqual(normals[0][2], 0.)

    def test_mirrored_obj_transform_reverses_winding_and_invalid_scale_is_rejected(self):
        vertices, faces, _, normals = transform_obj_geometry(
            [(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)], [(0, 1, 2)],
            normals=[(0., 0., 1.)] * 3, scale=(-1., 1., 1.))
        self.assertEqual(faces, [(2, 1, 0)])
        self.assertEqual(vertices[1], (-1., 0., 0.))
        self.assertEqual(normals, [(0., 0., 1.)] * 3)
        with self.assertRaisesRegex(ValueError, 'scale components must be nonzero'):
            transform_obj_geometry([(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)],
                                   [(0, 1, 2)], scale=(1., 0., 1.))


if __name__=='__main__':
    unittest.main()
