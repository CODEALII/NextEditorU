"""Capacity-bounded rigid Wii U BFRES mesh replacement.

This is deliberately not a general BFRES converter. It preserves every pointer,
material, allocation, vertex/index count and submesh partition. Unused triangles
become degenerate. Only the tested rigid float-position/packed-normal grass
layout is accepted. Layout researched against MIT BfresLibrary commit
65c005275deed1e085069e72fea523247f955b87; no Nintendo data is embedded here.
"""
import math
import struct

from .bfres import Skeletons


DEFAULT_MODEL = 'CS_W1_World'
DEFAULT_SHAPE = 'polySurface1489__mtGrass'
MAX_FACE_CORNERS = 1024
_UV_ATTRIBUTE_BYTES = {0x80d: 8, 0x7: 4, 0x207: 4, 0x4: 2}


def _decode_uv_attribute(data, offset, fmt):
    if fmt == 0x80d:  # GX2 Format_32_32_Single
        return struct.unpack_from('>2f', data, offset)
    if fmt == 0x7:  # GX2 Format_16_16_UNorm
        return tuple(value / 65535. for value in struct.unpack_from('>2H', data, offset))
    if fmt == 0x207:  # GX2 Format_16_16_SNorm
        return tuple(max(-1., value / 32767.) for value in struct.unpack_from('>2h', data, offset))
    if fmt == 0x4:  # GX2 Format_8_8_UNorm
        return tuple(value / 255. for value in struct.unpack_from('>2B', data, offset))
    return None


def extract_rigid_model(data, model=DEFAULT_MODEL):
    """Read static triangle shapes from a single identity-root Wii U model.

    This reader intentionally supports the tested world-model subset only:
    big-endian float32x3 positions, packed 10:10:10:2 normals, and contiguous
    u16 triangle lists. Textures, animations, skinning and non-identity root
    transforms are not evaluated.
    """
    r = Skeletons(data)
    if r.version != 0x03000001:
        raise ValueError('3D preview only supports BFRES version 0x03000001')
    models = dict(r.dictionary(r.ptr(32)))
    if model not in models:
        raise ValueError(f'Missing BFRES model: {model}')
    model_offset = models[model]
    roots = [bone for bone in r.models.get(model, ()) if bone.parent == -1]
    if len(roots) != 1 or roots[0].index != 0 or roots[0].position != (0., 0., 0.) or \
            roots[0].scale != (1., 1., 1.) or roots[0].rotation != (0., 0., 0., 1.):
        raise ValueError('3D preview requires one identity root bone')
    materials = r.dictionary(r.ptr(model_offset + 24))
    result = []
    for shape_name, shape in r.dictionary(r.ptr(model_offset + 20)):
        r.bounds(shape, 64)
        if data[shape:shape+4] != b'FSHP' or data[shape+22] or data[shape+23] != 1 or \
                data[shape+24] or r.u16(shape+20):
            raise ValueError(f'{shape_name}: skinned, morphed or multi-mesh shapes are not supported')
        if r.u16(shape+16) != roots[0].index:
            raise ValueError(f'{shape_name}: shape does not bind to the identity root')
        vertex = r.ptr(shape+32)
        r.bounds(vertex, 32)
        if data[vertex:vertex+4] != b'FVTX' or data[vertex+5] != 1 or data[vertex+12]:
            raise ValueError(f'{shape_name}: unsupported vertex-buffer layout')
        attrs = {}
        for name, attr in r.dictionary(r.ptr(vertex+20)):
            if data[attr+4] != 0:
                raise ValueError(f'{shape_name}: multiple vertex buffers are not supported')
            attrs[name] = (r.u16(attr+6), r.u32(attr+8))
        if attrs.get('_p0', (None, None))[1] != 0x811 or attrs.get('_n0', (None, None))[1] != 0x20b:
            raise ValueError(f'{shape_name}: expected float positions and packed normals')
        buffer = r.ptr(vertex+24)
        r.bounds(buffer, 24)
        size, stride = r.u32(buffer+4), r.u16(buffer+12)
        if r.u16(buffer+14) != 1:
            raise ValueError(f'{shape_name}: unexpected vertex-buffer memory pool')
        count = r.u32(vertex+8)
        start = r.ptr(buffer+20)
        r.bounds(start, size)
        for key, width in (('_p0', 12), ('_n0', 4)):
            if attrs[key][0] + width > stride or size < count * stride:
                raise ValueError(f'{shape_name}: vertex attribute exceeds its allocation')
        uv_attribute = attrs.get('_u0')
        uv_width = _UV_ATTRIBUTE_BYTES.get(uv_attribute[1]) if uv_attribute else None
        if uv_width is not None and (
                uv_attribute[0] + uv_width > stride or size < count * stride):
            raise ValueError(f'{shape_name}: texture-coordinate attribute exceeds its allocation')
        positions, normals = [], []
        uvs = [] if uv_width is not None else None
        for index in range(count):
            base = start + index * stride
            position = struct.unpack_from('>3f', data, base + attrs['_p0'][0])
            packed = struct.unpack_from('>I', data, base + attrs['_n0'][0])[0]
            uv = _decode_uv_attribute(data, base + uv_attribute[0], uv_attribute[1]) \
                if uvs is not None else None
            def signed10(value):
                value &= 0x3ff
                return value - 0x400 if value & 0x200 else value
            normal = [signed10(packed >> shift) / 511. for shift in (0, 10, 20)]
            norm = math.sqrt(sum(v*v for v in normal))
            if not all(math.isfinite(v) and abs(v) <= 1e7 for v in position) or norm < 1e-6:
                raise ValueError(f'{shape_name}: invalid position or normal at vertex {index}')
            if uv is not None and not all(math.isfinite(v) and abs(v) <= 1e5 for v in uv):
                raise ValueError(f'{shape_name}: invalid texture coordinates at vertex {index}')
            positions.append(position)
            normals.append(tuple(v / norm for v in normal))
            if uv is not None:
                uvs.append(uv)
        mesh = r.ptr(shape+36)
        r.bounds(mesh, 28)
        if r.u32(mesh) != 4 or r.u32(mesh+4) != 4 or r.u32(mesh+24):
            raise ValueError(f'{shape_name}: expected a zero-based u16 triangle list')
        index_count = r.u32(mesh+8)
        if index_count % 3:
            raise ValueError(f'{shape_name}: index count is not a triangle list')
        index_buffer = r.ptr(mesh+20)
        r.bounds(index_buffer, 24)
        if r.u16(index_buffer+14) != 1 or r.u32(index_buffer+4) < index_count * 2:
            raise ValueError(f'{shape_name}: invalid index-buffer allocation')
        index_start = r.ptr(index_buffer+20)
        r.bounds(index_start, index_count * 2)
        submeshes = r.ptr(mesh+16)
        submesh_count = r.u16(mesh+12)
        r.bounds(submeshes, submesh_count * 8)
        expected_count = 0
        for part in range(submesh_count):
            offset, length = r.u32(submeshes+part*8), r.u32(submeshes+part*8+4)
            if offset != expected_count * 2 or length % 3:
                raise ValueError(f'{shape_name}: non-contiguous triangle submesh')
            expected_count += length
        if expected_count != index_count:
            raise ValueError(f'{shape_name}: submeshes do not cover the index buffer')
        indices = list(struct.unpack_from('>' + str(index_count) + 'H', data, index_start))
        if any(index >= count for index in indices):
            raise ValueError(f'{shape_name}: index exceeds vertex count')
        material_index = r.u16(shape+14)
        if material_index >= len(materials):
            raise ValueError(f'{shape_name}: missing material reference')
        extracted = {
            'name': shape_name,
            'material': materials[material_index][0],
            'positions': positions,
            'normals': normals,
            'indices': indices,
            'vertexAttributes': {
                name: {'format': fmt, 'offset': offset}
                for name, (offset, fmt) in attrs.items()
            },
        }
        if uvs is not None:
            extracted['uvs'] = uvs
        result.append(extracted)
    if not result:
        raise ValueError(f'{model}: no supported shapes found')
    return result


def _nearest_uvs(points, source_points, source_uvs):
    """Transfer baked-light UVs by exact nearest source XZ vertex."""
    cell_size = 128.
    grid = {}
    for i, point in enumerate(source_points):
        key = math.floor(point[0] / cell_size), math.floor(point[2] / cell_size)
        grid.setdefault(key, []).append(i)
    if not grid:
        raise ValueError('Original shape has no lightmap source vertices')

    def build_tree(cells, axis=0):
        if not cells:
            return None
        cells.sort(key=lambda item: item[0][axis])
        middle = len(cells) // 2
        key, indices = cells[middle]
        left = build_tree(cells[:middle], 1 - axis)
        right = build_tree(cells[middle + 1:], 1 - axis)
        child_bounds = [child[4] for child in (left, right) if child is not None]
        bounds = (
            min([key[0], *(box[0] for box in child_bounds)]),
            max([key[0], *(box[1] for box in child_bounds)]),
            min([key[1], *(box[2] for box in child_bounds)]),
            max([key[1], *(box[3] for box in child_bounds)]),
        )
        return key, indices, left, right, bounds

    tree = build_tree(list(grid.items()))

    def bounds_distance_squared(point, bounds):
        min_x, max_x, min_z, max_z = bounds
        low_x, high_x = min_x * cell_size, (max_x + 1) * cell_size
        low_z, high_z = min_z * cell_size, (max_z + 1) * cell_size
        dx = max(low_x - point[0], 0., point[0] - high_x)
        dz = max(low_z - point[2], 0., point[2] - high_z)
        return dx * dx + dz * dz

    result = []
    for point in points:
        best, best_distance = None, float('inf')

        def visit(node):
            nonlocal best, best_distance
            if node is None or bounds_distance_squared(point, node[4]) > best_distance:
                return
            for index in node[1]:
                distance = _xz_distance_squared(point, source_points[index])
                if distance < best_distance:
                    best, best_distance = index, distance
            children = [child for child in (node[2], node[3]) if child is not None]
            children.sort(key=lambda child: bounds_distance_squared(point, child[4]))
            for child in children:
                if bounds_distance_squared(point, child[4]) <= best_distance:
                    visit(child)

        visit(tree)
        result.append(source_uvs[best])
    return result


def _xz_distance_squared(point, source):
    return (point[0] - source[0]) ** 2 + (point[2] - source[2]) ** 2


def _triangulate_face(vertices, face):
    """Triangulate a simple planar polygon without changing its winding.

    Convex polygons retain the historical fan order. Concave polygons use
    projected ear clipping so the triangles stay inside the source outline.
    The returned values are indices into the original vertex list, preserving
    each corner's UV and normal association.
    """
    if len(face) > MAX_FACE_CORNERS:
        raise ValueError(f'OBJ polygon exceeds the {MAX_FACE_CORNERS}-corner triangulation limit')
    if len(face) == 3:
        return [tuple(face)]

    points3 = [vertices[index] for index in face]
    extent = max(max(point[axis] for point in points3) -
                 min(point[axis] for point in points3) for axis in range(3))
    scale = max(extent, 1.0)
    length_tolerance = scale * 1e-9
    area_tolerance = scale * scale * 1e-12

    # Newell's method gives a stable plane normal for arbitrary polygon winding.
    normal = [0.0, 0.0, 0.0]
    for point, following in zip(points3, points3[1:] + points3[:1]):
        normal[0] += (point[1] - following[1]) * (point[2] + following[2])
        normal[1] += (point[2] - following[2]) * (point[0] + following[0])
        normal[2] += (point[0] - following[0]) * (point[1] + following[1])
    normal_length = math.sqrt(sum(value * value for value in normal))
    if normal_length <= area_tolerance:
        raise ValueError('Degenerate source polygon')
    normal = [value / normal_length for value in normal]
    plane_tolerance = max(1e-7, scale * 1e-6)
    origin = points3[0]
    if any(abs(sum((point[axis] - origin[axis]) * normal[axis]
                   for axis in range(3))) > plane_tolerance for point in points3):
        raise ValueError('Non-planar source polygon cannot be triangulated')

    drop_axis = max(range(3), key=lambda axis: abs(normal[axis]))
    axes = tuple(axis for axis in range(3) if axis != drop_axis)
    points = [(point[axes[0]], point[axes[1]]) for point in points3]

    def cross(a, b, c):
        return ((b[0] - a[0]) * (c[1] - a[1]) -
                (b[1] - a[1]) * (c[0] - a[0]))

    def on_segment(point, start, end):
        return (min(start[0], end[0]) - length_tolerance <= point[0] <=
                max(start[0], end[0]) + length_tolerance and
                min(start[1], end[1]) - length_tolerance <= point[1] <=
                max(start[1], end[1]) + length_tolerance)

    # Coincident corners make both the boundary and attribute association
    # ambiguous. Reject them rather than silently dropping a corner.
    for first in range(len(points)):
        for second in range(first + 1, len(points)):
            dx = points[first][0] - points[second][0]
            dy = points[first][1] - points[second][1]
            if dx * dx + dy * dy <= length_tolerance * length_tolerance:
                raise ValueError('OBJ polygon has duplicate corners')

    signed_area = sum(point[0] * following[1] - following[0] * point[1]
                      for point, following in zip(points, points[1:] + points[:1])) * 0.5
    if abs(signed_area) <= area_tolerance:
        raise ValueError('Degenerate source polygon')
    winding = 1.0 if signed_area > 0.0 else -1.0

    # Non-adjacent edges crossing or touching mean the input boundary is not
    # a simple polygon, so ear clipping has no well-defined result.
    count = len(points)
    for first in range(count):
        a, b = points[first], points[(first + 1) % count]
        for second in range(first + 1, count):
            if second == first or second == (first + 1) % count or \
                    (second + 1) % count == first:
                continue
            c, d = points[second], points[(second + 1) % count]
            abc, abd = cross(a, b, c), cross(a, b, d)
            cda, cdb = cross(c, d, a), cross(c, d, b)
            intersects = (
                ((abc > area_tolerance and abd < -area_tolerance) or
                 (abc < -area_tolerance and abd > area_tolerance)) and
                ((cda > area_tolerance and cdb < -area_tolerance) or
                 (cda < -area_tolerance and cdb > area_tolerance)))
            intersects = intersects or (abs(abc) <= area_tolerance and on_segment(c, a, b))
            intersects = intersects or (abs(abd) <= area_tolerance and on_segment(d, a, b))
            intersects = intersects or (abs(cda) <= area_tolerance and on_segment(a, c, d))
            intersects = intersects or (abs(cdb) <= area_tolerance and on_segment(b, c, d))
            if intersects:
                raise ValueError('Self-intersecting OBJ polygon cannot be triangulated')

    turns = [cross(points[(index - 1) % count], points[index], points[(index + 1) % count]) * winding
             for index in range(count)]
    if all(turn > area_tolerance for turn in turns):
        return [(face[0], face[index], face[index + 1])
                for index in range(1, len(face) - 1)]

    remaining = list(range(count))
    triangles = []
    while len(remaining) > 3:
        ear_found = False
        for position, current in enumerate(remaining):
            previous = remaining[position - 1]
            following = remaining[(position + 1) % len(remaining)]
            if cross(points[previous], points[current], points[following]) * winding <= area_tolerance:
                continue
            contains_corner = False
            for candidate in remaining:
                if candidate in (previous, current, following):
                    continue
                sides = (cross(points[previous], points[current], points[candidate]) * winding,
                         cross(points[current], points[following], points[candidate]) * winding,
                         cross(points[following], points[previous], points[candidate]) * winding)
                if all(side >= -area_tolerance for side in sides):
                    contains_corner = True
                    break
            if contains_corner:
                continue
            triangles.append((face[previous], face[current], face[following]))
            del remaining[position]
            ear_found = True
            break
        if not ear_found:
            raise ValueError('OBJ polygon cannot be triangulated safely')

    final = tuple(face[index] for index in remaining)
    if cross(*(points[index] for index in remaining)) * winding <= area_tolerance:
        raise ValueError('Degenerate source polygon')
    triangles.append(final)
    return triangles


def transform_obj_geometry(vertices, faces, uvs=None, normals=None, *,
                           scale=(1., 1., 1.), rotation_degrees=(0., 0., 0.),
                           translation=(0., 0., 0.)):
    """Apply scale, X/Y/Z rotation, then translation to imported OBJ geometry.

    Normals use the inverse-transpose of the scale/rotation matrix. A mirrored
    transform reverses face winding so the transformed normals stay consistent.
    """
    def finite_vector(values, label, limit):
        if len(values) != 3:
            raise ValueError(f"OBJ {label} must contain three values")
        vector = tuple(float(value) for value in values)
        if not all(math.isfinite(value) and abs(value) <= limit for value in vector):
            raise ValueError(f"OBJ {label} must be finite and within ±{limit:g}")
        return vector

    if not vertices or not faces:
        raise ValueError("OBJ transform needs vertices and polygon faces")
    scale = finite_vector(scale, "scale", 1e4)
    rotation = finite_vector(rotation_degrees, "rotation", 36000.)
    translation = finite_vector(translation, "translation", 1e5)
    if any(abs(value) < 1e-12 for value in scale):
        raise ValueError("OBJ scale components must be nonzero")
    for face in faces:
        if len(face) < 3 or any(type(index) is not int or not 0 <= index < len(vertices)
                                 for index in face):
            raise ValueError("OBJ transform found an invalid polygon face")
    if uvs is not None:
        if len(uvs) != len(vertices) or any(
                uv is not None and (len(uv) != 2 or not all(math.isfinite(float(value)) and
                                                               abs(float(value)) <= 1e5 for value in uv))
                for uv in uvs):
            raise ValueError("OBJ texture coordinates must have one finite value per vertex")
    if normals is not None and len(normals) != len(vertices):
        raise ValueError("OBJ normals must have one value per vertex")

    rx, ry, rz = (math.radians(value % 360.) for value in rotation)
    sx, sy, sz = math.sin(rx), math.sin(ry), math.sin(rz)
    cx, cy, cz = math.cos(rx), math.cos(ry), math.cos(rz)

    def rotate(vector):
        x, y, z = vector
        x, y, z = x, y * cx - z * sx, y * sx + z * cx
        x, y, z = x * cy + z * sy, y, -x * sy + z * cy
        return x * cz - y * sz, x * sz + y * cz, z

    transformed_vertices = []
    for vertex in vertices:
        point = finite_vector(vertex, "vertex", 1e5)
        rotated = rotate(tuple(point[axis] * scale[axis] for axis in range(3)))
        translated = tuple(rotated[axis] + translation[axis] for axis in range(3))
        if not all(math.isfinite(value) and abs(value) <= 1e5 for value in translated):
            raise ValueError("Transformed OBJ coordinates exceed ±100,000 units")
        transformed_vertices.append(translated)

    transformed_normals = None
    if normals is not None:
        transformed_normals = []
        for normal in normals:
            if normal is None:
                transformed_normals.append(None)
                continue
            vector = finite_vector(normal, "normal", 1e7)
            rotated = rotate(tuple(vector[axis] / scale[axis] for axis in range(3)))
            length = math.sqrt(sum(value * value for value in rotated))
            if not math.isfinite(length) or length < 1e-12:
                raise ValueError("OBJ normals must be nonzero after transformation")
            transformed_normals.append(tuple(value / length for value in rotated))

    transformed_faces = [tuple(reversed(face)) if scale[0] * scale[1] * scale[2] < 0 else tuple(face)
                         for face in faces]
    return transformed_vertices, transformed_faces, list(uvs) if uvs is not None else None, transformed_normals


def _geometry(vertices, faces, uvs=None, imported_normals=None):
    if not vertices or not faces or len(vertices) > 65535:
        raise ValueError('Mesh needs 1..65535 vertices and polygon faces')
    vertices = [tuple(float(v) for v in xyz) for xyz in vertices]
    if any(len(xyz) != 3 or not all(math.isfinite(v) and abs(v) <= 100000 for v in xyz)
           for xyz in vertices):
        raise ValueError('Mesh coordinates must be finite and within 100000 units')
    for values, label, width in ((uvs, 'texture coordinates', 2),
                                 (imported_normals, 'normals', 3)):
        if values is not None and (len(values) != len(vertices) or any(
                value is not None and (len(value) != width or not all(math.isfinite(float(v)) for v in value))
                for value in values)):
            raise ValueError(f'OBJ {label} must have one finite value per vertex')
    triangles = []
    normals = [[0., 0., 0.] for _ in vertices]
    for face in faces:
        if len(face) < 3 or any(type(i) is not int or not 0 <= i < len(vertices) for i in face):
            raise ValueError('Invalid mesh face')
        for tri in _triangulate_face(vertices, face):
            a, b, c = [vertices[i] for i in tri]
            ab = [b[k] - a[k] for k in range(3)]
            ac = [c[k] - a[k] for k in range(3)]
            n = [ab[1]*ac[2]-ab[2]*ac[1], ab[2]*ac[0]-ab[0]*ac[2], ab[0]*ac[1]-ab[1]*ac[0]]
            if sum(x*x for x in n) <= 1e-12:
                raise ValueError('Degenerate source triangle')
            triangles.extend(tri)
            for i in tri:
                normals[i] = [normals[i][k] + n[k] for k in range(3)]
    for i, n in enumerate(normals):
        length = math.sqrt(sum(v*v for v in n))
        normals[i] = tuple(v / length for v in n) if length > 1e-12 else (0., 1., 0.)
    if imported_normals is not None:
        for i, source in enumerate(imported_normals):
            if source is None:
                continue
            length = math.sqrt(sum(float(v)*float(v) for v in source))
            if length <= 1e-12:
                raise ValueError('OBJ normals must not be zero vectors')
            normals[i] = tuple(float(v)/length for v in source)
    return vertices, triangles, normals, uvs


def replace_rigid_mesh(data, vertices, faces, model=DEFAULT_MODEL, shape=DEFAULT_SHAPE,
                       uvs=None, imported_normals=None):
    """Return (new_bfres, report), replacing exactly one existing rigid shape.

    OBJ units are used directly as model-local game units. OBJ corner UVs and
    normals are kept when supplied; positions are split at attribute seams
    because BFRES stores one set of attributes per vertex. Existing terrain
    elsewhere remains visible. OBJ vt/vn data is kept when
    present; missing channels receive the documented planar/smooth defaults.
    In-game appearance still needs Cemu QA.
    """
    vertices, indices, normals, uvs = _geometry(vertices, faces, uvs, imported_normals)
    r = Skeletons(data)
    if r.version != 0x03000001:
        raise ValueError('Rigid mesh replacement only supports BFRES version 0x03000001')
    models = dict(r.dictionary(r.ptr(32)))
    if model not in models:
        raise ValueError(f'Missing BFRES model: {model}')
    model_offset = models[model]
    shapes = dict(r.dictionary(r.ptr(model_offset + 20)))
    if shape not in shapes:
        raise ValueError(f'Missing BFRES shape: {shape}')
    s = shapes[shape]
    r.bounds(s, 64)
    if data[s:s+4] != b'FSHP' or data[s+22] or data[s+23] != 1 or data[s+24] or r.u16(s+20):
        raise ValueError('Only rigid single-mesh shapes without skinning or morphs supported')
    bone_index = r.u16(s+16)
    roots = [b for b in r.models[model] if b.index == bone_index]
    if len(roots) != 1 or roots[0].parent != -1 or roots[0].position != (0., 0., 0.) or roots[0].scale != (1., 1., 1.) or roots[0].rotation != (0., 0., 0., 1.):
        raise ValueError('Mesh must bind to an identity root bone')
    v = r.ptr(s+32)
    r.bounds(v, 32)
    if data[v:v+4] != b'FVTX' or data[v+5] != 1 or data[v+12]:
        raise ValueError('Only one unskinned vertex buffer supported')
    for other_model in models.values():
        for _, other_shape in r.dictionary(r.ptr(other_model+20)):
            if other_shape != s and r.ptr(other_shape+32) == v:
                raise ValueError('Shared vertex buffer cannot be replaced independently')
    capacity = r.u32(v+8)
    if len(vertices) > capacity:
        raise ValueError(f'OBJ exceeds vertex capacity {capacity}')
    attrs = {}
    for name, a in r.dictionary(r.ptr(v+20)):
        if data[a+4] != 0:
            raise ValueError('Unexpected vertex buffer index')
        attrs[name] = (r.u16(a+6), r.u32(a+8))
    base_attrs = {'_p0':0x811,'_n0':0x20b,'_u0':0x80d,'_u1':7}
    formats = {n:f for n,(_,f) in attrs.items()}
    if formats not in (base_attrs, {**base_attrs, '_c0':0x0A}):
        raise ValueError('Unsupported vertex attribute layout; expected tested grass format with optional RGBA color')
    material_list = r.dictionary(r.ptr(model_offset + 24))
    material_index = r.u16(s+14)
    if material_index >= len(material_list):
        raise ValueError('Shape references a missing material')
    material_name = material_list[material_index][0]
    buffer = r.ptr(v+24)
    r.bounds(buffer, 24)
    size, stride = r.u32(buffer+4), r.u16(buffer+12)
    if r.u16(buffer+14) != 1 or stride < 28 or size < capacity*stride:
        raise ValueError('Invalid vertex allocation')
    start = r.ptr(buffer+20)
    r.bounds(start, size)
    for name, width in (('_p0',12),('_n0',4),('_u0',8),('_u1',4),('_c0',4)):
        if name not in attrs:
            continue
        if attrs[name][0]+width > stride:
            raise ValueError('Vertex attribute exceeds stride')
    mesh = r.ptr(s+36)
    r.bounds(mesh, 28)
    if r.u32(mesh) != 4 or r.u32(mesh+4) != 4 or r.u32(mesh+24):
        raise ValueError('Only triangles with big-endian u16 indices and FirstVertex=0 supported')
    index_capacity = r.u32(mesh+8)
    if len(indices) > index_capacity or index_capacity % 3:
        raise ValueError(f'OBJ exceeds triangle index capacity {index_capacity}')
    ib = r.ptr(mesh+20)
    r.bounds(ib, 24)
    index_start = r.ptr(ib+20)
    if r.u32(ib+4) < index_capacity*2 or r.u16(ib+14) != 1:
        raise ValueError('Invalid index allocation')
    r.bounds(index_start, r.u32(ib+4))
    source_points = [struct.unpack_from('>3f', data, start+i*stride+attrs['_p0'][0])
                     for i in range(capacity)]
    source_uvs = [tuple(value/65535. for value in struct.unpack_from(
        '>2H', data, start+i*stride+attrs['_u1'][0])) for i in range(capacity)]
    lightmap_uvs = _nearest_uvs(vertices, source_points, source_uvs)
    sub = r.ptr(mesh+16)
    count = r.u16(mesh+12)
    r.bounds(sub, count*8)
    partitions = [(r.u32(sub+i*8), r.u32(sub+i*8+4)) for i in range(count)]
    expected = 0
    for offset, length in partitions:
        if offset != expected*2 or length % 3:
            raise ValueError('Unsupported noncontiguous submesh index partition')
        expected += length
    if expected != index_capacity:
        raise ValueError('Submesh partitions do not cover index allocation')
    bounds_count = r.u16(s+26)
    bounds_start = r.ptr(s+52)
    if not bounds_count or not bounds_start:
        raise ValueError('Explicit existing bounding boxes required')
    r.bounds(bounds_start, bounds_count*24)
    lo = [min(p[k] for p in vertices) for k in range(3)]
    hi = [max(p[k] for p in vertices) for k in range(3)]
    center = [(lo[k]+hi[k])/2 for k in range(3)]
    extent = [max((hi[k]-lo[k])/2, .01) for k in range(3)]
    out = bytearray(data)
    for i in range(capacity):
        source = i if i < len(vertices) else 0
        p, n = vertices[source], normals[source]
        at = start+i*stride
        struct.pack_into('>3f',out,at+attrs['_p0'][0],*p)
        packed = sum((round(max(-1.,min(1.,n[k]))*511)&1023) << (10*k) for k in range(3))
        struct.pack_into('>I',out,at+attrs['_n0'][0],packed)
        planar = [(p[k]-lo[k])/max(hi[k]-lo[k],.01) for k in (0,2)]
        uv = planar if uvs is None or uvs[source] is None else [float(x) for x in uvs[source]]
        struct.pack_into('>2f',out,at+attrs['_u0'][0],*uv)
        # `_u1` is the source mesh's baked-light channel, not OBJ's diffuse UV.
        # Project new vertices onto the original XZ lightmap layout.
        uv1 = lightmap_uvs[source]
        struct.pack_into('>2H',out,at+attrs['_u1'][0],*(round(max(0.,min(1.,x))*65535) for x in uv1))
        if '_c0' in attrs:
            out[at+attrs['_c0'][0]:at+attrs['_c0'][0]+4] = b'\xff\xff\xff\xff'
    struct.pack_into('>'+str(index_capacity)+'H',out,index_start,*(indices+[0]*(index_capacity-len(indices))))
    for i in range(bounds_count):
        struct.pack_into('>6f',out,bounds_start+i*24,*(center+extent))
    radius = max(math.sqrt(sum(x*x for x in p)) for p in vertices)
    struct.pack_into('>f',out,s+28,radius)
    return bytes(out), {'model':model,'shape':shape,'vertices':len(vertices),
        'triangles':len(indices)//3,'vertex_capacity':capacity,'index_capacity':index_capacity,
        'material_reused':True,'material':material_name,
        'uvs':'OBJ vt or generated planar XZ; baked channel projected from original XZ mesh',
        'normals':'OBJ vn with smooth fallback' if imported_normals is not None else 'generated smooth',
        'imported_normals':imported_normals is not None and any(n is not None for n in imported_normals),
        'unused_triangles':'degenerate','game_verified':False}
