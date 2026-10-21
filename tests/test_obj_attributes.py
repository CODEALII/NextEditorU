import tempfile
import unittest
from pathlib import Path

from worldstudio.editor import read_obj


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


if __name__=='__main__':
    unittest.main()
