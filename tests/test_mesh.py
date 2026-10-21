import struct
import unittest
import hashlib
import math
from pathlib import Path
from unittest.mock import patch

import worldstudio.mesh as mesh
from worldstudio.mesh import DEFAULT_SHAPE, _geometry, extract_rigid_model, replace_rigid_mesh
from worldstudio.archive import Archive
from worldstudio.bfres import Skeletons


def fixture():
    """Entirely synthetic BFRES subset, containing no game data."""
    b = bytearray(4096)
    def u(p, n): struct.pack_into('>I',b,p,n)
    def h(p, n): struct.pack_into('>H',b,p,n)
    def ptr(p, target): u(p,(target-p)&0xffffffff if target else 0)
    cursor = 0x900
    def string(text):
        nonlocal cursor
        at = cursor
        data = text.encode()+b'\0'
        b[at:at+len(data)] = data
        cursor += len(data)
        return at
    def dictionary(at, items):
        u(at,8+16*(len(items)+1));u(at+4,len(items))
        for i,(name,target) in enumerate(items):
            q=at+24+16*i
            ptr(q+8,string(name));ptr(q+12,target)
    b[:4]=b'FRES';u(4,0x03000001);b[8:10]=b'\xfe\xff';ptr(32,0x80)
    dictionary(0x80,[('CS_W1_World',0x100)])
    b[0x100:0x104]=b'FMDL';ptr(0x10c,0x140);ptr(0x114,0x240)
    b[0x140:0x144]=b'FSKL';h(0x148,1);ptr(0x150,0x180)
    dictionary(0x180,[('root',0x1c0)])
    ptr(0x1c0,string('root'));h(0x1c6,65535)
    struct.pack_into('>3f',b,0x1d4,1,1,1)
    struct.pack_into('>4f',b,0x1e0,0,0,0,1)
    dictionary(0x240,[(DEFAULT_SHAPE,0x280)])
    dictionary(0x3a0,[('mtGrass',0x780)])
    b[0x780:0x784]=b'FMAT'
    ptr(0x118,0x3a0)
    h(0x28e,0)
    b[0x280:0x284]=b'FSHP';b[0x297]=1;h(0x29a,1)
    ptr(0x2a0,0x300);ptr(0x2a4,0x480);ptr(0x2b4,0x500)
    b[0x300:0x304]=b'FVTX';b[0x304]=4;b[0x305]=1;u(0x308,4)
    ptr(0x314,0x340);ptr(0x318,0x440)
    specs=[('_p0',0,0x811),('_n0',12,0x20b),('_u0',16,0x80d),('_u1',24,7)]
    dictionary(0x340,[(n,0x400+12*i) for i,(n,_,_) in enumerate(specs)])
    for i,(_,offset,fmt) in enumerate(specs):h(0x406+12*i,offset);u(0x408+12*i,fmt)
    u(0x444,112);h(0x44c,28);h(0x44e,1);ptr(0x454,0x600)
    u(0x480,4);u(0x484,4);u(0x488,6);h(0x48c,1);ptr(0x490,0x4e0);ptr(0x494,0x4b0)
    u(0x4b4,12);h(0x4be,1);ptr(0x4c4,0x800);u(0x4e4,6)
    for i, point in enumerate(((0,0,0),(0,0,2),(2,0,0),(0,0,1))):
        struct.pack_into('>3f',b,0x600+i*28,*point)
        struct.pack_into('>I',b,0x600+i*28+12,511<<10)
    struct.pack_into('>6H',b,0x800,0,1,2,0,0,0)
    return bytes(b)


class MeshTests(unittest.TestCase):
    vertices=[(0.,0.,0.),(0.,0.,2.),(2.,0.,0.)]
    faces=[(0,1,2)]

    def test_original_island_assets_have_upward_top_faces(self):
        root=Path(__file__).resolve().parents[1]
        for path,top_count in ((root/'assets/island.obj',6),(root/'examples/island-game.obj',18)):
            vertices=[];faces=[]
            for line in path.read_text().splitlines():
                f=line.split()
                if f and f[0]=='v':vertices.append(tuple(map(float,f[1:4])))
                elif f and f[0]=='f':faces.append(tuple(int(i)-1 for i in f[1:]))
            tops=faces[-6:] if path.name=='island.obj' else faces[:top_count]
            for face in tops:
                a,b,c=[vertices[i] for i in face[:3]]
                normal_y=(b[2]-a[2])*(c[0]-a[0])-(b[0]-a[0])*(c[2]-a[2])
                self.assertGreater(normal_y,0)
            if path.name=='island-game.obj':
                from collections import Counter
                edges=Counter(tuple(sorted((face[i],face[(i+1)%len(face)])))
                              for face in faces for i in range(len(face)))
                self.assertTrue(all(count==2 for count in edges.values()))

    def test_replacement_preserves_layout_and_unused_bytes(self):
        before=fixture()
        after, report=replace_rigid_mesh(before,self.vertices,self.faces)
        self.assertEqual(len(after),len(before))
        self.assertEqual(report['triangles'],1)
        self.assertEqual(struct.unpack_from('>6H',after,0x800),(0,1,2,0,0,0))
        self.assertEqual(struct.unpack_from('>3f',after,0x600+28),(0,0,2))
        self.assertEqual(struct.unpack_from('>6f',after,0x500),(1,0,1,1,.009999999776482582,1))
        self.assertEqual(struct.unpack_from('>I',after,0x600+12)[0],511<<10)
        allowed=set(range(0x600,0x670))|set(range(0x800,0x80c))|set(range(0x500,0x518))|set(range(0x29c,0x2a0))
        self.assertTrue(all(a==b or i in allowed for i,(a,b) in enumerate(zip(before,after))))

    def test_imported_uvs_and_normals_are_written(self):
        uvs=[(0.25,0.75),(0.5,0.25),(1.0,0.0)]
        normals=[(0,0,1),(0,0,1),(0,0,1)]
        after,report=replace_rigid_mesh(fixture(),self.vertices,self.faces,
                                        uvs=uvs,imported_normals=normals)
        self.assertEqual(struct.unpack_from('>2f',after,0x600+16),(0.25,0.75))
        self.assertEqual(struct.unpack_from('>2H',after,0x600+24),(0,0))
        self.assertEqual(struct.unpack_from('>I',after,0x600+12)[0],511<<20)
        self.assertTrue(report['imported_normals'])

    def test_static_model_geometry_round_trips_from_supported_layout(self):
        shapes = extract_rigid_model(fixture())
        self.assertEqual(len(shapes), 1)
        self.assertEqual(shapes[0]['name'], DEFAULT_SHAPE)
        self.assertEqual(shapes[0]['material'], 'mtGrass')
        self.assertEqual(shapes[0]['positions'][:3], self.vertices)
        self.assertEqual(shapes[0]['indices'], [0, 1, 2, 0, 0, 0])
        self.assertEqual(shapes[0]['normals'][0], (0., 1., 0.))
        self.assertEqual(shapes[0]['vertexAttributes']['_u0'],
                         {'format': 0x80d, 'offset': 16})
        self.assertEqual(shapes[0]['vertexAttributes']['_u1'],
                         {'format': 7, 'offset': 24})

    def test_supported_gx2_uv_formats_decode_to_normalized_coordinates(self):
        encodings = (
            (0x80d, lambda data, at: struct.pack_into('>2f', data, at, .25, .75), (.25, .75)),
            (0x7, lambda data, at: struct.pack_into('>2H', data, at, 32768, 16384),
             (32768 / 65535, 16384 / 65535)),
            (0x207, lambda data, at: struct.pack_into('>2h', data, at, -32768, 16384),
             (-1., 16384 / 32767)),
            (0x4, lambda data, at: struct.pack_into('>2B', data, at, 128, 64),
             (128 / 255, 64 / 255)),
        )
        for fmt, encode, expected in encodings:
            with self.subTest(format=hex(fmt)):
                data = bytearray(fixture())
                struct.pack_into('>I', data, 0x420, fmt)
                encode(data, 0x610)
                shape = extract_rigid_model(bytes(data))[0]
                self.assertEqual(len(shape['uvs']), len(shape['positions']))
                for actual, wanted in zip(shape['uvs'][0], expected):
                    self.assertAlmostEqual(actual, wanted, places=6)

    def test_supported_uv_format_must_fit_vertex_stride(self):
        data = bytearray(fixture())
        struct.pack_into('>H', data, 0x41e, 27)
        struct.pack_into('>I', data, 0x420, 0x4)
        with self.assertRaisesRegex(ValueError, 'texture-coordinate attribute exceeds'):
            extract_rigid_model(bytes(data))

    def test_far_uv_projection_is_exact_without_distance_scaled_grid_search(self):
        source_points = [((x - 5) * 256., 0., (z - 5) * 256.)
                         for x in range(10) for z in range(10)]
        source_uvs = [(float(i), float(-i)) for i in range(len(source_points))]
        points = [(99999., 0., 99999.), (-99999., 0., -99999.),
                  (99999., 0., -99999.), (-99999., 0., 99999.)]
        distance_checks = 0
        original_distance = mesh._xz_distance_squared

        def counted_distance(point, source):
            nonlocal distance_checks
            distance_checks += 1
            return original_distance(point, source)

        with patch.object(mesh, '_xz_distance_squared', counted_distance):
            projected = mesh._nearest_uvs(points, source_points, source_uvs)

        for point, uv in zip(points, projected):
            expected_distance = min((point[0] - source[0]) ** 2 +
                                    (point[2] - source[2]) ** 2
                                    for source in source_points)
            actual_index = source_uvs.index(uv)
            actual_source = source_points[actual_index]
            actual_distance = ((point[0] - actual_source[0]) ** 2 +
                               (point[2] - actual_source[2]) ** 2)
            self.assertEqual(actual_distance, expected_distance)
        self.assertLess(distance_checks, len(points) * len(source_points) // 2)

    def test_rejects_capacity_and_bad_input(self):
        with self.assertRaisesRegex(ValueError,'vertex capacity'):
            replace_rigid_mesh(fixture(),self.vertices*2,self.faces)
        with self.assertRaisesRegex(ValueError,'Invalid mesh face'):
            replace_rigid_mesh(fixture(),self.vertices,[(0,1,99)])
        with self.assertRaisesRegex(ValueError,'Degenerate'):
            replace_rigid_mesh(fixture(),self.vertices,[(0,0,0)])

    def test_concave_obj_polygon_triangulates_inside_outline_and_preserves_winding(self):
        # A C-shaped polygon with area 7; a fan from vertex zero crosses the notch.
        vertices = [(0,0,0),(3,0,0),(3,1,0),(1,1,0),
                    (1,2,0),(3,2,0),(3,3,0),(0,3,0)]
        uvs = [(i / 8, i / 16) for i in range(len(vertices))]
        for face, expected_sign in ((tuple(range(8)), 1), (tuple(reversed(range(8))), -1)):
            _, indices, _, result_uvs = _geometry(vertices, [face], uvs=uvs)
            triangles = [indices[i:i+3] for i in range(0, len(indices), 3)]
            areas = []
            for a, b, c in triangles:
                pa, pb, pc = (vertices[index] for index in (a,b,c))
                areas.append(((pb[0]-pa[0])*(pc[1]-pa[1]) -
                              (pb[1]-pa[1])*(pc[0]-pa[0])) / 2)
            self.assertEqual(len(triangles), len(vertices)-2)
            self.assertTrue(all(area * expected_sign > 0 for area in areas), areas)
            self.assertAlmostEqual(sum(abs(area) for area in areas), 7.0)
            self.assertEqual(set(indices), set(range(len(vertices))))
            self.assertEqual(result_uvs, uvs)

    def test_rejects_non_planar_and_self_intersecting_obj_polygons(self):
        non_planar = [(0,0,0),(3,0,0),(3,2,0),(1,1,0.1),(0,2,0)]
        with self.assertRaisesRegex(ValueError, 'Non-planar'):
            _geometry(non_planar, [tuple(range(len(non_planar)))])
        crossing = [(0,0,0),(3,3,0),(0,3,0),(3,0,0),(4,1,0)]
        with self.assertRaisesRegex(ValueError, 'Self-intersecting'):
            _geometry(crossing, [tuple(range(len(crossing)))])

    def test_rejects_polygon_above_triangulation_corner_limit(self):
        vertices = [(float(index), 0.0, 0.0) for index in range(1025)]
        face = tuple(range(len(vertices)))
        with self.assertRaisesRegex(ValueError, '1024-corner triangulation limit'):
            _geometry(vertices, [face])

    def test_rejects_unknown_formats_and_skinning(self):
        data=bytearray(fixture());struct.pack_into('>I',data,0x408,123)
        with self.assertRaisesRegex(ValueError,'Unsupported vertex attribute'):
            replace_rigid_mesh(bytes(data),self.vertices,self.faces)
        data=bytearray(fixture());data[0x296]=1
        with self.assertRaisesRegex(ValueError,'rigid'):
            replace_rigid_mesh(bytes(data),self.vertices,self.faces)


class LocalDumpMeshTests(unittest.TestCase):
    def test_local_dump_world_model_extracts_static_shapes(self):
        root=Path(__file__).resolve().parents[1]
        source=root/'NSMBU Modding Project/content/Common/course_select/CS_W1.szs'
        if not source.is_file():
            self.skipTest('User-provided local W1 dump unavailable')
        archive=Archive(source.read_bytes())
        shapes=extract_rigid_model(archive.read('CS_W1.bfres'))
        self.assertEqual(len(shapes),42)
        self.assertGreater(sum(len(shape['positions']) for shape in shapes),70000)
        self.assertGreater(sum(len(shape['indices']) for shape in shapes),300000)
        from collections import Counter
        self.assertEqual(Counter(shape['vertexAttributes']['_u0']['format'] for shape in shapes),
                         {0x80d: 36, 0x7: 3, 0x207: 2, 0x4: 1})
        self.assertTrue(all(len(shape['uvs']) == len(shape['positions']) for shape in shapes))
        self.assertTrue(all(math.isfinite(value) for shape in shapes for uv in shape['uvs']
                            for value in uv))
        grass=next(shape for shape in shapes if shape['name']=='polySurface1489__mtGrass')
        self.assertEqual(len(grass['uvs']),len(grass['positions']))
        self.assertTrue(all(all(math.isfinite(v) for v in uv) for uv in grass['uvs']))

    def test_local_dump_in_memory_export_and_byte_boundaries(self):
        root=Path(__file__).resolve().parents[1]
        source=root/'NSMBU Modding Project/content/Common/course_select/CS_W1.szs'
        if not source.is_file():
            self.skipTest('User-provided local W1 dump unavailable')
        original=source.read_bytes()
        source_hash=hashlib.sha256(original).digest()
        archive=Archive(original)
        before=archive.read('CS_W1.bfres')
        vertices=[];faces=[]
        for line in (root/'examples/island-game.obj').read_text().splitlines():
            f=line.split()
            if f and f[0]=='v':vertices.append(tuple(map(float,f[1:4])))
            elif f and f[0]=='f':faces.append(tuple(int(i)-1 for i in f[1:]))
        after,report=replace_rigid_mesh(before,vertices,faces)
        self.assertEqual(len(before),len(after))
        self.assertEqual(report['vertices'],len(vertices))
        self.assertEqual(report['triangles'],len(faces))
        r=Skeletons(before)
        self.assertEqual(r.models,Skeletons(after).models)
        model=dict(r.dictionary(r.ptr(32)))['CS_W1_World']
        shape=dict(r.dictionary(r.ptr(model+20)))[DEFAULT_SHAPE]
        vb=r.ptr(shape+32);buf=r.ptr(vb+24);start=r.ptr(buf+20)
        stride=r.u16(buf+12);capacity=r.u32(vb+8)
        attrs={n:r.u16(a+6) for n,a in r.dictionary(r.ptr(vb+20))}
        permitted=bytearray(len(before))
        def allow(at,size):permitted[at:at+size]=b'\1'*size
        for i in range(capacity):
            for name,width in (('_p0',12),('_n0',4),('_u0',8),('_u1',4),('_c0',4)):
                if name not in attrs: continue
                allow(start+i*stride+attrs[name],width)
        mesh=r.ptr(shape+36);ib=r.ptr(mesh+20);istart=r.ptr(ib+20)
        allow(istart,r.u32(mesh+8)*2)
        allow(r.ptr(shape+52),r.u16(shape+26)*24)
        allow(shape+28,4)
        self.assertGreater(sum(a!=b for a,b in zip(before,after)),0)
        self.assertTrue(all(a==b or permitted[i] for i,(a,b) in enumerate(zip(before,after))))
        for i,xyz in enumerate(vertices):
            self.assertEqual(struct.unpack_from('>3f',after,start+i*stride+attrs['_p0']),xyz)
        triangle_indices=struct.unpack_from('>'+str(r.u32(mesh+8))+'H',after,istart)
        expected=tuple(i for face in faces for i in face)
        self.assertEqual(triangle_indices[:len(expected)],expected)
        self.assertTrue(all(i==0 for i in triangle_indices[len(expected):]))
        if '_c0' in attrs:
            self.assertEqual(after[start+attrs['_c0']:start+attrs['_c0']+4],b'\xff'*4)
        self.assertEqual(hashlib.sha256(source.read_bytes()).digest(),source_hash)


if __name__=='__main__':unittest.main()
