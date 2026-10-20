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
DEFAULT_SHAPE = 'beltmodel14__mtGrass'


def _geometry(vertices, faces):
    if not vertices or not faces or len(vertices) > 65535:
        raise ValueError('Mesh needs 1..65535 vertices and polygon faces')
    vertices = [tuple(float(v) for v in xyz) for xyz in vertices]
    if any(len(xyz) != 3 or not all(math.isfinite(v) and abs(v) <= 100000 for v in xyz)
           for xyz in vertices):
        raise ValueError('Mesh coordinates must be finite and within 100000 units')
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
    return vertices, triangles, normals


def replace_rigid_mesh(data, vertices, faces, model=DEFAULT_MODEL, shape=DEFAULT_SHAPE):
    """Return (new_bfres, report), replacing exactly one existing rigid shape.

    OBJ units are used directly as model-local game units. Smooth normals and
    planar XZ UVs are generated; OBJ material/UV/normal definitions are not read.
    Existing terrain elsewhere remains visible. In-game appearance needs Cemu QA.
    """
    vertices, indices, normals = _geometry(vertices, faces)
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
    if set(attrs) != {'_p0', '_n0', '_u0', '_u1'} or {n:f for n,(_,f) in attrs.items()} != {'_p0':0x811,'_n0':0x20b,'_u0':0x80d,'_u1':7}:
        raise ValueError('Unsupported vertex attribute layout; expected tested grass format')
    buffer = r.ptr(v+24)
    r.bounds(buffer, 24)
    size, stride = r.u32(buffer+4), r.u16(buffer+12)
    if r.u16(buffer+14) != 1 or stride < 28 or size < capacity*stride:
        raise ValueError('Invalid vertex allocation')
    start = r.ptr(buffer+20)
    r.bounds(start, size)
    for name, width in (('_p0',12),('_n0',4),('_u0',8),('_u1',4)):
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
        uv = [(p[k]-lo[k])/max(hi[k]-lo[k],.01) for k in (0,2)]
        struct.pack_into('>2f',out,at+attrs['_u0'][0],*uv)
        struct.pack_into('>2H',out,at+attrs['_u1'][0],*(round(x*65535) for x in uv))
    struct.pack_into('>'+str(index_capacity)+'H',out,index_start,*(indices+[0]*(index_capacity-len(indices))))
    for i in range(bounds_count):
        struct.pack_into('>6f',out,bounds_start+i*24,*(center+extent))
    radius = max(math.sqrt(sum(x*x for x in p)) for p in vertices)
    struct.pack_into('>f',out,s+28,radius)
    return bytes(out), {'model':model,'shape':shape,'vertices':len(vertices),
        'triangles':len(indices)//3,'vertex_capacity':capacity,'index_capacity':index_capacity,
        'material_reused':True,'uvs':'generated planar XZ','normals':'generated smooth',
        'unused_triangles':'degenerate','game_verified':False}
