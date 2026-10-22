import struct
import unittest
import hashlib
import math
from pathlib import Path
from unittest.mock import patch

import worldstudio.mesh as mesh
from worldstudio.mesh import (DEFAULT_SHAPE, _decode_uv_attribute,
                              _decode_vertex_color_attribute, _geometry,
                              extract_rigid_model, replace_rigid_mesh,
                              rigid_shape_bindings)
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


def fixture_with_scaled_child_bone(*, child_flags=0):
    data = bytearray(fixture())

    def rel_ptr(offset, target):
        struct.pack_into('>I', data, offset, (target - offset) & 0xffffffff)

    root_name, child_name = 0xa00, 0xa05
    data[root_name:root_name + 11] = b'root\0child\0'
    struct.pack_into('>H', data, 0x148, 2)
    struct.pack_into('>II', data, 0x180, 56, 2)
    for index, (name, target) in enumerate(((root_name, 0xb00), (child_name, 0xb40))):
        record = 0x180 + 24 + index * 16
        rel_ptr(record + 8, name)
        rel_ptr(record + 12, target)
        rel_ptr(target, name)
        bone_index = index
        parent_index = -1 if index == 0 else 0
        struct.pack_into('>Hh', data, target + 4, bone_index, parent_index)
        struct.pack_into('>I', data, target + 16, child_flags if index else 0)
        scale = (1., 1., 1.) if index == 0 else (2., 3., 1.)
        position = (0., 0., 0.) if index == 0 else (10., 20., 30.)
        struct.pack_into('>3f', data, target + 20, *scale)
        struct.pack_into('>4f', data, target + 32, 0., 0., 0., 1.)
        struct.pack_into('>3f', data, target + 48, *position)
    struct.pack_into('>H', data, 0x290, 1)  # Bind the shape to the child bone.
    for index in range(4):
        struct.pack_into('>I', data, 0x600 + index * 28 + 12, 511 | (511 << 10))
    return bytes(data)


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
        self.assertEqual(report['baked_uv_projection']['max_xz_distance'], 0.0)
        self.assertIsNone(report['baked_uv_projection']['warning'])
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

    def test_topology_preserving_patch_keeps_source_indices_and_uv_channels(self):
        before = fixture()
        patch_vertices = [(0., 10., 0.), (0., 10., 2.), (2., 10., 0.)]
        before_diffuse_uv = before[0x600 + 16:0x600 + 24]
        before_light_uv = before[0x600 + 24:0x600 + 28]

        after, report = replace_rigid_mesh(
            before, patch_vertices, self.faces, preserve_topology=True,
            edge_blend_distance=0)

        self.assertEqual(struct.unpack_from('>6H', after, 0x800), (0, 1, 2, 0, 0, 0))
        self.assertEqual(after[0x600 + 16:0x600 + 24], before_diffuse_uv)
        self.assertEqual(after[0x600 + 24:0x600 + 28], before_light_uv)
        self.assertEqual([struct.unpack_from('>3f', after, 0x600 + index * 28)[1]
                          for index in range(4)], [10., 10., 10., 10.])
        self.assertTrue(report['topology_preserved'])
        self.assertTrue(report['indices_preserved'])
        self.assertTrue(report['diffuse_uvs_preserved'])
        self.assertTrue(report['baked_light_uvs_preserved'])
        self.assertEqual(report['vertices_displaced'], 4)

    def test_topology_preserving_patch_rejects_nonoverlapping_surface(self):
        far_patch = [(100., 10., 100.), (100., 10., 102.), (102., 10., 100.)]

        with self.assertRaisesRegex(ValueError, 'does not overlap'):
            replace_rigid_mesh(fixture(), far_patch, self.faces, preserve_topology=True)

    def test_topology_preserving_patch_blends_to_source_terrain_at_boundary(self):
        patch_vertices = [(-2., 10., -2.), (-2., 10., 10.), (10., 10., -2.)]

        after, report = replace_rigid_mesh(
            fixture(), patch_vertices, self.faces, preserve_topology=True)

        heights = [struct.unpack_from('>3f', after, 0x600 + index * 28)[1]
                   for index in range(4)]
        self.assertTrue(all(0. < height < 10. for height in heights), heights)
        self.assertEqual(report['vertices_edge_blended'], 4)
        self.assertEqual(report['edge_blend_distance'], 128.)

    def test_static_model_geometry_round_trips_from_supported_layout(self):
        shapes = extract_rigid_model(fixture())
        self.assertEqual(len(shapes), 1)
        self.assertEqual(shapes[0]['name'], DEFAULT_SHAPE)
        self.assertEqual(shapes[0]['boundBone'], 'root')
        self.assertEqual(shapes[0]['material'], 'mtGrass')
        self.assertEqual(shapes[0]['positions'][:3], self.vertices)
        self.assertEqual(shapes[0]['indices'], [0, 1, 2, 0, 0, 0])
        self.assertEqual(shapes[0]['normals'][0], (0., 1., 0.))
        self.assertEqual(shapes[0]['vertexAttributes']['_u0'],
                         {'format': 0x80d, 'offset': 16})
        self.assertEqual(shapes[0]['vertexAttributes']['_u1'],
                         {'format': 7, 'offset': 24})
        self.assertEqual(shapes[0]['submeshes'], [{'indexOffset': 0, 'indexCount': 6}])
        self.assertEqual(rigid_shape_bindings(fixture()), {DEFAULT_SHAPE: 'root'})

    def test_static_model_preserves_contiguous_submesh_index_ranges(self):
        data = bytearray(fixture())
        struct.pack_into('>H', data, 0x48c, 2)
        struct.pack_into('>II', data, 0x4e0, 0, 3)
        struct.pack_into('>II', data, 0x4e8, 6, 3)

        shape = extract_rigid_model(bytes(data))[0]

        self.assertEqual(shape['submeshes'], [
            {'indexOffset': 0, 'indexCount': 3},
            {'indexOffset': 3, 'indexCount': 3},
        ])
        self.assertEqual(shape['indices'], [0, 1, 2, 0, 0, 0])

    def test_additional_bfres_uv_formats_decode_half_float_and_signed_normalized_pairs(self):
        data = struct.pack('>2e2b', 0.5, -2.0, -128, 64)

        self.assertEqual(_decode_uv_attribute(data, 0, 0x808), (0.5, -2.0))
        self.assertEqual(_decode_uv_attribute(data, 4, 0x204), (-1.0, 64 / 127))
        self.assertIsNone(_decode_uv_attribute(data, 0, 0x123))

    def test_supported_vertex_color_formats_decode_without_clamping_source_values(self):
        data = struct.pack('>4B4e', 0, 64, 128, 255, 0.25, 1.5, -0.5, 1.0)

        unorm = _decode_vertex_color_attribute(data, 0, 0x0a)
        half_float = _decode_vertex_color_attribute(data, 4, 0x80f)

        self.assertEqual(unorm, (0.0, 64 / 255, 128 / 255, 1.0))
        self.assertEqual(half_float, (0.25, 1.5, -0.5, 1.0))
        with self.assertRaisesRegex(ValueError, 'Unsupported vertex color format'):
            _decode_vertex_color_attribute(data, 0, 0x123)

    def test_half_float_vec4_positions_decode_with_unit_homogeneous_w(self):
        data = bytearray(fixture())
        struct.pack_into('>I', data, 0x408, 0x80f)
        for index, point in enumerate(((0, 0, 0), (0, 0, 2), (2, 0, 0), (0, 0, 1))):
            struct.pack_into('>4e', data, 0x600 + index * 28, *point, 1.0)

        shapes = extract_rigid_model(bytes(data))

        self.assertEqual(shapes[0]['positions'][:4],
                         [(0.0, 0.0, 0.0), (0.0, 0.0, 2.0),
                          (2.0, 0.0, 0.0), (0.0, 0.0, 1.0)])

    def test_half_float_vec4_positions_reject_non_unit_homogeneous_w(self):
        data = bytearray(fixture())
        struct.pack_into('>I', data, 0x408, 0x80f)
        for index, point in enumerate(((0, 0, 0), (0, 0, 2), (2, 0, 0), (0, 0, 1))):
            struct.pack_into('>4e', data, 0x600 + index * 28,
                             *point, 2.0 if index == 0 else 1.0)

        with self.assertRaisesRegex(ValueError, 'homogeneous W of 1'):
            extract_rigid_model(bytes(data))

    def test_translation_only_root_is_applied_to_static_mesh_positions(self):
        data = bytearray(fixture())
        struct.pack_into('>3f', data, 0x1f0, 100.0, 200.0, -50.0)

        shapes = extract_rigid_model(bytes(data))

        self.assertEqual(shapes[0]['positions'][:3],
                         [(100.0, 200.0, -50.0), (100.0, 200.0, -48.0),
                          (102.0, 200.0, -50.0)])

    def test_rotated_root_transforms_static_positions(self):
        data = bytearray(fixture())
        struct.pack_into('>4f', data, 0x1e0, 0.0, 0.7071067811865476, 0.0,
                         0.7071067811865476)

        shapes = extract_rigid_model(bytes(data))

        self.assertAlmostEqual(shapes[0]['positions'][1][0], 2.0, places=6)
        self.assertAlmostEqual(shapes[0]['positions'][1][2], 0.0, places=6)
        self.assertAlmostEqual(shapes[0]['positions'][2][0], 0.0, places=6)
        self.assertAlmostEqual(shapes[0]['positions'][2][2], -2.0, places=6)

    def test_scaled_root_transforms_static_mesh_positions(self):
        data = bytearray(fixture())
        struct.pack_into('>3f', data, 0x1d4, 2.0, 3.0, 4.0)

        shapes = extract_rigid_model(bytes(data))

        self.assertEqual(shapes[0]['positions'][:3],
                         [(0.0, 0.0, 0.0), (0.0, 0.0, 8.0), (4.0, 0.0, 0.0)])

    def test_scaled_shape_bone_transforms_positions_and_normals(self):
        shapes = extract_rigid_model(fixture_with_scaled_child_bone())
        shape = shapes[0]

        self.assertEqual(shape['positions'][:3],
                         [(10.0, 20.0, 30.0), (10.0, 20.0, 32.0),
                          (14.0, 20.0, 30.0)])
        for actual, expected in zip(shape['normals'][0],
                                    (3 / math.sqrt(13), 2 / math.sqrt(13), 0.0)):
            self.assertAlmostEqual(actual, expected, places=6)

    def test_scaled_shape_bone_with_segment_compensation_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unsupported rest-pose transform'):
            extract_rigid_model(fixture_with_scaled_child_bone(child_flags=1 << 23))

    def test_inverse_transpose_normal_transform(self):
        actual = mesh._transform_normal([[2., 0., 0.], [0., 3., 0.], [0., 0., 1.]],
                                        (1., 1., 0.))

        for value, expected in zip(actual, (3 / math.sqrt(13), 2 / math.sqrt(13), 0.0)):
            self.assertAlmostEqual(value, expected, places=6)

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

    def test_extracts_multiple_named_uv_attributes(self):
        data = bytearray(fixture())
        for index, values in enumerate(((32768, 16384), (65535, 0), (0, 65535), (1, 2))):
            struct.pack_into('>2H', data, 0x600 + index * 28 + 24, *values)

        shape = extract_rigid_model(bytes(data))[0]

        self.assertEqual(shape['uvAttributes']['_u0'], shape['uvs'])
        self.assertEqual(shape['uvAttributes']['_u1'][0], (32768 / 65535, 16384 / 65535))
        self.assertEqual(shape['uvAttributes']['_u1'][1], (1., 0.))
        self.assertEqual(len(shape['uvAttributes']['_u1']), len(shape['positions']))

    def test_supported_uv_format_must_fit_vertex_stride(self):
        data = bytearray(fixture())
        struct.pack_into('>H', data, 0x41e, 27)
        struct.pack_into('>I', data, 0x420, 0x4)
        with self.assertRaisesRegex(ValueError, 'texture-coordinate attribute .* exceeds'):
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
            projected, distances = mesh._nearest_uvs(points, source_points, source_uvs)

        for point, uv, distance in zip(points, projected, distances):
            expected_distance = min((point[0] - source[0]) ** 2 +
                                    (point[2] - source[2]) ** 2
                                    for source in source_points)
            actual_index = source_uvs.index(uv)
            actual_source = source_points[actual_index]
            actual_distance = ((point[0] - actual_source[0]) ** 2 +
                               (point[2] - actual_source[2]) ** 2)
            self.assertEqual(actual_distance, expected_distance)
            self.assertAlmostEqual(distance, math.sqrt(expected_distance))
        self.assertLess(distance_checks, len(points) * len(source_points) // 2)

    def test_baked_uvs_interpolate_barycentrically_inside_source_triangle(self):
        source_points = [(0., 0., 0.), (10., 0., 0.), (0., 0., 10.)]
        source_uvs = [(0., 0.), (1., 0.), (0., 1.)]

        uvs, distances, fallback_count = mesh._nearest_triangle_uvs(
            [(2., 0., 3.)], source_points, source_uvs, (0, 1, 2))

        self.assertEqual(fallback_count, 0)
        self.assertEqual(uvs, [(0.2, 0.3)])
        self.assertEqual(distances, [0.])

    def test_baked_uvs_project_to_the_closest_triangle_edge(self):
        source_points = [(0., 0., 0.), (10., 0., 0.), (0., 0., 10.)]
        source_uvs = [(0., 0.), (1., 0.), (0., 1.)]

        uvs, distances, fallback_count = mesh._nearest_triangle_uvs(
            [(20., 0., 0.)], source_points, source_uvs, (0, 1, 2))

        self.assertEqual(fallback_count, 0)
        self.assertEqual(uvs, [(1., 0.)])
        self.assertEqual(distances, [10.])

    def test_baked_uv_projection_rejects_invalid_source_geometry(self):
        points = [(0., 0., 0.), (1., 0., 0.), (0., 0., 1.)]
        uvs = [(0., 0.), (1., 0.), (0., 1.)]
        with self.assertRaisesRegex(ValueError, 'out-of-range triangle index'):
            mesh._nearest_triangle_uvs(points[:1], points, uvs, (0, 1, 3))
        with self.assertRaisesRegex(ValueError, 'counts differ'):
            mesh._nearest_triangle_uvs(points[:1], points, uvs[:2], (0, 1, 2))
        invalid_points = [(float('nan'), 0., 0.), *points[1:]]
        with self.assertRaisesRegex(ValueError, 'invalid coordinates'):
            mesh._nearest_triangle_uvs(points[:1], invalid_points, uvs, (0, 1, 2))

    def test_baked_uvs_fall_back_for_degenerate_and_ambiguous_projections(self):
        line_points = [(0., 0., 0.), (1., 0., 0.), (2., 0., 0.)]
        line_uvs = [(0., 0.), (0.5, 0.5), (1., 1.)]
        projected, distances, fallback_count = mesh._nearest_triangle_uvs(
            [(0.9, 0., 0.)], line_points, line_uvs, (0, 1, 2))
        self.assertEqual(fallback_count, 1)
        self.assertEqual(projected, [(0.5, 0.5)])
        self.assertAlmostEqual(distances[0], 0.1)

        stacked_points = [(0., 0., 0.), (10., 0., 0.), (0., 0., 10.),
                          (0., 5., 0.), (10., 5., 0.), (0., 5., 10.)]
        stacked_uvs = [(0., 0.), (1., 0.), (0., 1.),
                       (0.5, 0.5), (0.5, 1.), (1., 0.5)]
        projected, distances, fallback_count = mesh._nearest_triangle_uvs(
            [(2., 0., 3.)], stacked_points, stacked_uvs,
            (0, 1, 2, 3, 4, 5))
        self.assertEqual(fallback_count, 1)
        self.assertEqual(projected, [(0., 0.)])
        self.assertAlmostEqual(distances[0], math.sqrt(13.))

    def test_baked_uv_triangle_bvh_limits_projection_checks(self):
        side = 30
        source_points = [(float(x), 0., float(z))
                         for z in range(side + 1) for x in range(side + 1)]
        source_uvs = [(x / side, z / side)
                      for z in range(side + 1) for x in range(side + 1)]
        source_indices = []
        for z in range(side):
            for x in range(side):
                lower_left = z * (side + 1) + x
                lower_right = lower_left + 1
                upper_left = lower_left + side + 1
                upper_right = upper_left + 1
                source_indices.extend((lower_left, lower_right, upper_right,
                                       lower_left, upper_right, upper_left))
        points = [(0.37 + index % 25, 0., 0.61 + (index * 7) % 25)
                  for index in range(80)]
        calls = 0
        original_project = mesh._project_xz_triangle

        def counted_project(point, triangle):
            nonlocal calls
            calls += 1
            return original_project(point, triangle)

        with patch.object(mesh, '_project_xz_triangle', counted_project):
            projected, distances, fallback_count = mesh._nearest_triangle_uvs(
                points, source_points, source_uvs, source_indices)

        self.assertEqual(len(projected), len(points))
        self.assertEqual(len(distances), len(points))
        self.assertEqual(fallback_count, 0)
        self.assertLess(calls, len(points) * (len(source_indices) // 3) // 5)

    def test_rigid_replacement_bakes_interpolated_u1_values(self):
        data = bytearray(fixture())
        for index, uv in enumerate(((0., 0.), (1., 0.), (0., 1.))):
            struct.pack_into('>2H', data, 0x600 + index * 28 + 24,
                             *(round(value * 65535) for value in uv))
        vertices = [(0.5, 0., 0.5), (0.75, 0., 0.25), (0.2, 0., 0.75)]

        exported, report = replace_rigid_mesh(bytes(data), vertices, self.faces)

        self.assertEqual(struct.unpack_from('>2H', exported, 0x600 + 24),
                         (round(0.25 * 65535), round(0.25 * 65535)))
        self.assertEqual(report['baked_uv_projection']['method'].split(';')[0],
                         'closest non-degenerate source triangle in XZ with barycentric UV interpolation')
        self.assertEqual(report['baked_uv_projection']['nearest_vertex_fallback_count'], 0)

    def test_baked_uv_projection_warns_for_distant_geometry_and_accepts_threshold_override(self):
        far_vertices = [(1000., 0., 1000.), (1000., 0., 1002.), (1002., 0., 1000.)]
        _, report = replace_rigid_mesh(fixture(), far_vertices, self.faces)
        projection = report['baked_uv_projection']
        self.assertGreater(projection['max_xz_distance'], 128.)
        self.assertEqual(projection['warning_threshold'], 128.)
        self.assertIn('baked-light UV projection', projection['warning'])

        _, reviewed = replace_rigid_mesh(fixture(), far_vertices, self.faces,
                                          lightmap_projection_warning_distance=2000.)
        self.assertIsNone(reviewed['baked_uv_projection']['warning'])
        self.assertEqual(reviewed['baked_uv_projection']['warning_threshold'], 2000.)

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
        self.assertTrue(all(sum(part['indexCount'] for part in shape['submeshes']) ==
                            len(shape['indices']) for shape in shapes))
        from collections import Counter
        self.assertEqual(Counter(shape['vertexAttributes']['_u0']['format'] for shape in shapes),
                         {0x80d: 36, 0x7: 3, 0x207: 2, 0x4: 1})
        self.assertTrue(all(len(shape['uvs']) == len(shape['positions']) for shape in shapes))
        self.assertEqual(Counter(name for shape in shapes
                                 for name in shape.get('uvAttributes', {})),
                         {'_u0': 42, '_u1': 42, '_u2': 13})
        colored_shapes = [shape for shape in shapes if '_c0' in shape['vertexAttributes']]
        self.assertEqual(Counter(shape['vertexAttributes']['_c0']['format']
                                 for shape in colored_shapes), {0x0a: 21, 0x80f: 1})
        self.assertTrue(all(len(shape['vertexColors']) == len(shape['positions'])
                            for shape in colored_shapes))
        self.assertTrue(all(math.isfinite(value)
                            for shape in colored_shapes
                            for color in shape['vertexColors'] for value in color))
        self.assertTrue(all(len(values) == len(shape['positions'])
                            for shape in shapes
                            for values in shape.get('uvAttributes', {}).values()))
        self.assertTrue(all(math.isfinite(value) for shape in shapes for uv in shape['uvs']
                            for value in uv))
        grass=next(shape for shape in shapes if shape['name']=='polySurface1489__mtGrass')
        self.assertEqual(len(grass['uvs']),len(grass['positions']))
        self.assertTrue(all(all(math.isfinite(v) for v in uv) for uv in grass['uvs']))

    def test_local_w9a_world_static_meshes_and_base_colors(self):
        from worldstudio.preview_textures import attach_base_color_textures

        root = Path(__file__).resolve().parents[1]
        source = root / 'NSMBU Modding Project/content/Common/course_select/CS_W9a.szs'
        if not source.is_file():
            self.skipTest('User-provided local W9a dump unavailable')
        archive = Archive(source.read_bytes())
        model = archive.read('CS_W9a.bfres')
        shapes = extract_rigid_model(model, 'CS_W9a_World')
        textures, failed = attach_base_color_textures(model, shapes,
                                                       model_name='CS_W9a_World')

        self.assertEqual(len(shapes), 3)
        self.assertEqual(len(textures), 2)
        self.assertEqual(sum(bool(shape.get('texture')) for shape in shapes), 3)
        self.assertFalse(failed)
        self.assertEqual({texture['format'] for texture in textures.values()}, {0x31})

    def test_local_translation_root_and_half_float_world_static_meshes(self):
        root = Path(__file__).resolve().parents[1]
        expected_shapes = {'W2a': 58, 'W3': 40, 'W4': 53, 'W5a': 76, 'W5b': 27,
                           'W6a': 61, 'W8a': 18, 'W8b': 42, 'W9b': 20}
        for world, expected_count in expected_shapes.items():
            with self.subTest(world=world):
                source = root / 'NSMBU Modding Project/content/Common/course_select' / f'CS_{world}.szs'
                if not source.is_file():
                    self.skipTest(f'User-provided local {world} dump unavailable')
                archive = Archive(source.read_bytes())
                model = archive.read(f'CS_{world}.bfres')
                shapes = extract_rigid_model(model, f'CS_{world}_World')

                self.assertEqual(len(shapes), expected_count)
                self.assertTrue(all(shape['positions'] and shape['indices'] for shape in shapes))
                self.assertTrue(all(math.isfinite(value)
                                    for shape in shapes for point in shape['positions'] for value in point))

    def test_additional_local_world_uv_formats_decode_into_the_3d_preview(self):
        root = Path(__file__).resolve().parents[1]
        expected_formats = {
            'W3': {0x808: 1},
            'W5a': {0x204: 1},
            'W7': {0x808: 1},
            'W8a': {0x808: 1},
            'W8b': {0x808: 2, 0x204: 2},
        }
        for world, expected in expected_formats.items():
            with self.subTest(world=world):
                source = root / 'NSMBU Modding Project/content/Common/course_select' / f'CS_{world}.szs'
                if not source.is_file():
                    self.skipTest(f'User-provided local {world} dump unavailable')
                model = Archive(source.read_bytes()).read(f'CS_{world}.bfres')
                shapes = extract_rigid_model(model, f'CS_{world}_World')
                actual = {}
                for shape in shapes:
                    fmt = shape['vertexAttributes'].get('_u0', {}).get('format')
                    if fmt in (0x808, 0x204):
                        actual[fmt] = actual.get(fmt, 0) + 1
                        self.assertEqual(len(shape['uvs']), len(shape['positions']))
                        self.assertTrue(all(math.isfinite(value)
                                            for uv in shape['uvs'] for value in uv))
                self.assertEqual(actual, expected)

    def test_local_w8b_nonroot_rigid_shape_uses_its_bone_transform(self):
        from worldstudio.mesh import extract_rigid_model

        root = Path(__file__).resolve().parents[1]
        source = root / 'NSMBU Modding Project/content/Common/course_select/CS_W8b.szs'
        if not source.is_file():
            self.skipTest('User-provided local W8b dump unavailable')
        archive = Archive(source.read_bytes())
        model_data = archive.read('CS_W8b.bfres')
        skeletons = Skeletons(model_data)
        model_offset = dict(skeletons.dictionary(skeletons.ptr(32)))['CS_W8b_World']
        shape_offset = dict(skeletons.dictionary(skeletons.ptr(model_offset + 20)))[
            'ring4__mtRW801W804c']
        bone_index = skeletons.u16(shape_offset + 16)
        self.assertEqual(bone_index, 1)
        bone = next(bone for bone in skeletons.models['CS_W8b_World']
                    if bone.index == bone_index)
        self.assertEqual(bone.position, (540.0, 49.0, -480.0))
        vertex = skeletons.ptr(shape_offset + 32)
        attributes = dict(skeletons.dictionary(skeletons.ptr(vertex + 20)))
        buffer = skeletons.ptr(vertex + 24)
        start = skeletons.ptr(buffer + 20)
        local = struct.unpack_from('>3f', model_data,
                                   start + skeletons.u16(attributes['_p0'] + 6))

        shape = next(shape for shape in extract_rigid_model(model_data, 'CS_W8b_World')
                     if shape['name'] == 'ring4__mtRW801W804c')

        self.assertEqual(shape['positions'][0],
                         (local[0] + 540.0, local[1] + 49.0, local[2] - 480.0))

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
