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
        if uv_attribute and uv_attribute[1] == 0x80d and (
                uv_attribute[0] + 8 > stride or size < count * stride):
            raise ValueError(f'{shape_name}: texture-coordinate attribute exceeds its allocation')
        positions, normals = [], []
        uvs = [] if uv_attribute and uv_attribute[1] == 0x80d else None
        for index in range(count):
            base = start + index * stride
            position = struct.unpack_from('>3f', data, base + attrs['_p0'][0])
            packed = struct.unpack_from('>I', data, base + attrs['_n0'][0])[0]
            uv = struct.unpack_from('>2f', data, base + uv_attribute[0]) if uvs is not None else None
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
        }
        if uvs is not None:
            extracted['uvs'] = uvs
        result.append(extracted)
    if not result:
        raise ValueError(f'{model}: no supported shapes found')
    return result


def _nearest_uvs(points, source_points, source_uvs):
    """Transfer baked-light UVs by nearest source XZ vertex using a grid."""
    cell_size = 128.
    grid = {}
    for i, point in enumerate(source_points):
        key = math.floor(point[0] / cell_size), math.floor(point[2] / cell_size)
        grid.setdefault(key, []).append(i)
    if not grid:
        raise ValueError('Original shape has no lightmap source vertices')
    min_x, max_x = min(k[0] for k in grid), max(k[0] for k in grid)
    min_z, max_z = min(k[1] for k in grid), max(k[1] for k in grid)
    result = []
    for point in points:
        cx, cz = math.floor(point[0] / cell_size), math.floor(point[2] / cell_size)
        best, best_distance = None, float('inf')
        max_ring = max(abs(cx-min_x), abs(cx-max_x), abs(cz-min_z), abs(cz-max_z))
        for ring in range(max_ring + 1):
            for dx in range(-ring, ring + 1):
                for dz in range(-ring, ring + 1):
                    if max(abs(dx), abs(dz)) != ring:
                        continue
                    for i in grid.get((cx+dx, cz+dz), ()):
                        src = source_points[i]
                        distance = (point[0]-src[0])**2 + (point[2]-src[2])**2
                        if distance < best_distance:
                            best, best_distance = i, distance
            if best is not None:
                left = point[0] - (cx-ring)*cell_size
                right = (cx+ring+1)*cell_size - point[0]
                down = point[2] - (cz-ring)*cell_size
                up = (cz+ring+1)*cell_size - point[2]
                outside_distance = max(0., min(left, right, down, up))
                if best_distance <= outside_distance**2:
                    break
        result.append(source_uvs[best])
    return result


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
        # Fan triangulation supports convex polygons; concave faces must be triangulated by the author.
        for j in range(1, len(face) - 1):
            tri = face[0], face[j], face[j + 1]
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
