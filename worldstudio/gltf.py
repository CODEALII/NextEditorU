"""Bounded static-mesh reader for embedded Binary glTF (GLB) geometry.

This imports geometry for preview and topology-preserving terrain projection.
It does not insert new BFRES meshes or evaluate materials, animation, skinning,
or skinned node poses. Static node transforms are applied to imported geometry.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import struct


MAX_GLB_FILE_BYTES = 64 * 1024 * 1024
MAX_GLB_ELEMENTS = 500_000
MAX_GLB_VERTICES = 65_535
MAX_GLB_TRIANGLES = 200_000
MAX_GLB_PRIMITIVES = 4096

_GLB_MAGIC = 0x46546C67
_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942
_COMPONENTS = {
    5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2),
    5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4),
}
_COMPONENTS_PER_TYPE = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def _integer(value, label, *, minimum=0, maximum=MAX_GLB_FILE_BYTES):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"GLB {label} is outside supported bounds")
    return value


def _list(document, key):
    value = document.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"GLB {key} must be an array")
    if len(value) > MAX_GLB_ELEMENTS:
        raise ValueError(f"GLB {key} exceeds the supported element limit")
    return value


def _array(value, label):
    if not isinstance(value, list):
        raise ValueError(f"GLB {label} must be an array")
    if len(value) > MAX_GLB_ELEMENTS:
        raise ValueError(f"GLB {label} exceeds the supported element limit")
    return value


def _item(values, index, label):
    index = _integer(index, f"{label} index", maximum=max(0, len(values) - 1))
    if index >= len(values):
        raise ValueError(f"GLB {label} index is out of range")
    item = values[index]
    if not isinstance(item, dict):
        raise ValueError(f"GLB {label} must be an object")
    return item


_IDENTITY4 = ((1., 0., 0., 0.), (0., 1., 0., 0.),
              (0., 0., 1., 0.), (0., 0., 0., 1.))


def _finite_vector(node, key, default, length, limit=1e7):
    values = node.get(key, default)
    if not isinstance(values, (list, tuple)) or len(values) != length:
        raise ValueError(f"GLB node {key} must have {length} values")
    if any(type(value) not in (int, float) for value in values):
        raise ValueError(f"GLB node {key} must contain finite numbers")
    try:
        values = tuple(float(value) for value in values)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"GLB node {key} must contain finite numbers") from error
    if not all(math.isfinite(value) and abs(value) <= limit for value in values):
        raise ValueError(f"GLB node {key} must contain finite numbers within supported bounds")
    return values


def _linear_determinant(matrix):
    a, b, c = matrix[0][:3]
    d, e, f = matrix[1][:3]
    g, h, i = matrix[2][:3]
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)


def _node_transform(node):
    """Return one validated glTF node transform as a row-major affine matrix."""
    matrix = node.get("matrix")
    if matrix is not None:
        if any(key in node for key in ("translation", "rotation", "scale")):
            raise ValueError("GLB node cannot define both matrix and TRS transforms")
        values = _finite_vector(node, "matrix", matrix, 16)
        # glTF stores matrices column-major; convert to the row-major form used here.
        result = tuple(tuple(values[column * 4 + row] for column in range(4))
                       for row in range(4))
        if any(not math.isclose(result[3][column], target, rel_tol=0.0, abs_tol=1e-8)
               for column, target in enumerate((0., 0., 0., 1.))):
            raise ValueError("GLB node matrix must be affine")
    else:
        translation = _finite_vector(node, "translation", (0., 0., 0.), 3)
        rotation = _finite_vector(node, "rotation", (0., 0., 0., 1.), 4, limit=1.)
        scale = _finite_vector(node, "scale", (1., 1., 1.), 3)
        length = math.sqrt(sum(value * value for value in rotation))
        if length < 1e-8 or abs(length - 1.) > 1e-4:
            raise ValueError("GLB node rotation must be a normalized quaternion")
        x, y, z, w = (value / length for value in rotation)
        rotation_matrix = (
            (1 - 2 * (y * y + z * z), 2 * (x * y - z * w),
             2 * (x * z + y * w)),
            (2 * (x * y + z * w), 1 - 2 * (x * x + z * z),
             2 * (y * z - x * w)),
            (2 * (x * z - y * w), 2 * (y * z + x * w),
             1 - 2 * (x * x + y * y)),
        )
        result = tuple(tuple(rotation_matrix[row][column] * scale[column]
                             for column in range(3)) + (translation[row],)
                       for row in range(3)) + ((0., 0., 0., 1.),)
    determinant = _linear_determinant(result)
    if not math.isfinite(determinant) or abs(determinant) < 1e-12:
        raise ValueError("GLB node transform must be invertible")
    return result


def _multiply4(left, right):
    return tuple(tuple(sum(left[row][k] * right[k][column] for k in range(4))
                       for column in range(4)) for row in range(4))


def _transform_position(matrix, position):
    result = tuple(sum(matrix[row][column] * position[column] for column in range(3)) +
                   matrix[row][3] for row in range(3))
    if not all(math.isfinite(value) and abs(value) <= 1e7 for value in result):
        raise ValueError("GLB transformed POSITION exceeds supported bounds")
    return result


def _normal_matrix(matrix):
    """Precompute the affine inverse-transpose for one node transform."""
    linear = tuple(row[:3] for row in matrix[:3])
    a, b, c = linear[0]
    d, e, f = linear[1]
    g, h, i = linear[2]
    cofactors = (
        (e * i - f * h, f * g - d * i, d * h - e * g),
        (c * h - b * i, a * i - c * g, b * g - a * h),
        (b * f - c * e, c * d - a * f, a * e - b * d),
    )
    determinant = a * cofactors[0][0] + b * cofactors[0][1] + c * cofactors[0][2]
    return tuple(tuple(value / determinant for value in row) for row in cofactors)


def _transform_normal(normal_matrix, normal):
    """Apply the affine inverse-transpose and normalize the resulting normal."""
    transformed = tuple(sum(normal_matrix[row][column] * normal[column]
                            for column in range(3)) for row in range(3))
    length = math.sqrt(sum(value * value for value in transformed))
    if not math.isfinite(length) or length < 1e-12:
        raise ValueError("GLB transformed NORMAL is invalid")
    return tuple(value / length for value in transformed)


def _scene_mesh_instances(document, mesh_count):
    nodes = _list(document, "nodes")
    if not nodes:
        return [(index, _IDENTITY4) for index in range(mesh_count)]
    scenes = _list(document, "scenes")
    if not scenes:
        child_indexes = set()
        reference_count = 0
        for node in nodes:
            if isinstance(node, dict):
                children = _array(node.get("children", []), "node children")
                reference_count += len(children)
                if reference_count > MAX_GLB_ELEMENTS:
                    raise ValueError("GLB node hierarchy exceeds the supported reference limit")
                child_indexes.update(
                    _integer(child, "node index", maximum=max(0, len(nodes) - 1))
                    for child in children)
        roots = [index for index in range(len(nodes)) if index not in child_indexes]
    else:
        scene_index = document.get("scene", 0)
        scene = _item(scenes, scene_index, "scene")
        roots = _array(scene.get("nodes", []), "scene nodes")

    if len(roots) > MAX_GLB_ELEMENTS:
        raise ValueError("GLB scene roots exceed the supported element limit")

    active_nodes = set()
    referenced_meshes = []
    visiting = set()
    pending = [(index, False, _IDENTITY4) for index in reversed(roots)]
    while pending:
        index, leaving, parent_transform = pending.pop()
        index = _integer(index, "node index", maximum=max(0, len(nodes) - 1))
        if leaving:
            visiting.remove(index)
            continue
        if index in visiting:
            raise ValueError("GLB node hierarchy contains a cycle")
        if index in active_nodes:
            raise ValueError("GLB node is instanced more than once; flatten instances before import")
        node = _item(nodes, index, "node")
        visiting.add(index)
        active_nodes.add(index)
        world_transform = _multiply4(parent_transform, _node_transform(node))
        world_determinant = _linear_determinant(world_transform)
        if not math.isfinite(world_determinant) or abs(world_determinant) < 1e-12:
            raise ValueError("GLB node hierarchy produces a singular transform")
        if node.get("extensions"):
            raise ValueError("GLB node extensions are unsupported; bake node instancing before import")
        if node.get("skin") is not None:
            raise ValueError("Skinned GLB nodes are unsupported; export a static mesh")
        if node.get("weights"):
            raise ValueError("GLB morph weights are unsupported; apply morphs before import")
        if "mesh" in node:
            mesh_index = _integer(node["mesh"], "mesh index", maximum=max(0, mesh_count - 1))
            if mesh_index >= mesh_count:
                raise ValueError("GLB node mesh index is out of range")
            referenced_meshes.append((mesh_index, world_transform))
        children = _array(node.get("children", []), "node children")
        pending.append((index, True, world_transform))
        pending.extend((child, False, world_transform) for child in reversed(children))
    return referenced_meshes


def _accessor_values(document, binary, accessor_index, *, expected_type,
                     role, max_count=MAX_GLB_ELEMENTS):
    accessors = _list(document, "accessors")
    accessor = _item(accessors, accessor_index, "accessor")
    if accessor.get("sparse") is not None:
        raise ValueError(f"Sparse GLB {role} accessors are unsupported")
    if accessor.get("extensions"):
        raise ValueError(f"GLB {role} accessor extensions are unsupported")
    if "bufferView" not in accessor:
        raise ValueError(f"GLB {role} accessor must reference an embedded bufferView")
    if accessor.get("type") != expected_type:
        raise ValueError(f"GLB {role} accessor must use {expected_type}")
    component_type = accessor.get("componentType")
    if type(component_type) is not int or component_type not in _COMPONENTS:
        raise ValueError(f"GLB {role} accessor has an unsupported componentType")
    component_format, component_size = _COMPONENTS[component_type]
    width = _COMPONENTS_PER_TYPE[expected_type]
    normalized = accessor.get("normalized", False)
    if type(normalized) is not bool:
        raise ValueError(f"GLB {role} normalized flag must be boolean")
    if role == "POSITION" and (component_type != 5126 or normalized):
        raise ValueError("GLB POSITION must use unnormalized float32 values")
    if role == "NORMAL" and (component_type != 5126 or normalized):
        raise ValueError("GLB NORMAL must use unnormalized float32 values")
    if role == "TEXCOORD_0" and not (
            (component_type == 5126 and not normalized) or
            (component_type in (5121, 5123) and normalized)):
        raise ValueError("GLB TEXCOORD_0 must use float32 or normalized unsigned byte/short values")
    if role == "indices" and (component_type not in (5121, 5123, 5125) or normalized):
        raise ValueError("GLB indices must use unnormalized unsigned integer values")

    count = _integer(accessor.get("count"), f"{role} count", minimum=1, maximum=max_count)
    view = _item(_list(document, "bufferViews"), accessor["bufferView"], "bufferView")
    if "buffer" not in view or _integer(view["buffer"], "bufferView buffer index", maximum=0) != 0:
        raise ValueError("Only the embedded GLB buffer is supported")
    view_offset = _integer(view.get("byteOffset", 0), "bufferView byteOffset")
    view_length = _integer(view.get("byteLength"), "bufferView byteLength", minimum=1)
    if view.get("extensions"):
        raise ValueError(f"GLB {role} bufferView extensions are unsupported; decompress the mesh before import")
    if view_offset % 4:
        raise ValueError(f"GLB {role} bufferView must be four-byte aligned")
    if view_offset > len(binary) or view_length > len(binary) - view_offset:
        raise ValueError("GLB bufferView exceeds the embedded binary chunk")
    element_size = component_size * width
    accessor_offset = _integer(accessor.get("byteOffset", 0), "accessor byteOffset")
    if view_offset % component_size or accessor_offset % component_size:
        raise ValueError(f"GLB {role} accessor is not aligned to its component type")
    stride = view.get("byteStride", element_size)
    if role == "indices":
        if "byteStride" in view:
            raise ValueError("GLB index bufferViews cannot define byteStride")
        stride = element_size
    else:
        stride = _integer(stride, f"{role} byteStride", minimum=4, maximum=252)
        if "byteStride" in view and (stride < element_size or stride % 4):
            raise ValueError("GLB vertex byteStride must fit the element and be a multiple of four")
        if accessor_offset % 4 or view_offset % 4:
            raise ValueError(f"GLB {role} vertex accessor must be four-byte aligned")
        if element_size % 4 and "byteStride" not in view:
            raise ValueError(f"GLB {role} accessor requires byteStride for four-byte vertex alignment")
    required = accessor_offset + (count - 1) * stride + element_size
    if required > view_length:
        raise ValueError(f"GLB {role} accessor exceeds its bufferView")

    fmt = "<" + component_format * width
    values = []
    for index in range(count):
        start = view_offset + accessor_offset + index * stride
        row = struct.unpack_from(fmt, binary, start)
        if normalized and component_type != 5126:
            if component_type in (5121, 5123):
                denominator = 255. if component_type == 5121 else 65535.
                row = tuple(value / denominator for value in row)
            else:
                denominator = 127. if component_type == 5120 else 32767.
                row = tuple(max(-1., value / denominator) for value in row)
        if role == "indices":
            values.extend(row)
        else:
            limit = 1e7 if role in ("POSITION", "NORMAL") else 1e5
            if not all(math.isfinite(value) and abs(value) <= limit for value in row):
                raise ValueError(f"GLB {role} contains a non-finite or out-of-range value")
            values.append(tuple(row))
    return values


def parse_glb(data):
    """Parse one bounded GLB2 into merged positions, triangles, UVs and normals."""
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ValueError("GLB input must be bytes")
    if len(data) > MAX_GLB_FILE_BYTES:
        raise ValueError(f"GLB exceeds the {MAX_GLB_FILE_BYTES // (1024 * 1024)} MiB file-size limit")
    if len(data) < 20:
        raise ValueError("Truncated GLB header or chunks")
    magic, version, declared_length = struct.unpack_from("<III", data, 0)
    if magic != _GLB_MAGIC or version != 2 or declared_length != len(data):
        raise ValueError("Invalid GLB2 header or total length")

    json_chunk = None
    binary_chunk = None
    data_view = memoryview(data)
    cursor = 12
    chunk_count = 0
    while cursor < len(data):
        if len(data) - cursor < 8:
            raise ValueError("Truncated GLB chunk header")
        length, chunk_type = struct.unpack_from("<II", data, cursor)
        cursor += 8
        if length % 4 or length > len(data) - cursor:
            raise ValueError("Invalid GLB chunk length or alignment")
        chunk = data_view[cursor:cursor + length]
        if chunk_count == 0 and chunk_type != _JSON_CHUNK:
            raise ValueError("GLB JSON chunk must be first")
        if chunk_type == _JSON_CHUNK:
            if json_chunk is not None:
                raise ValueError("GLB contains multiple JSON chunks")
            json_chunk = bytes(chunk)
        elif chunk_type == _BIN_CHUNK:
            if binary_chunk is not None:
                raise ValueError("GLB contains multiple BIN chunks")
            binary_chunk = chunk
        cursor += length
        chunk_count += 1
        if chunk_count > 16:
            raise ValueError("GLB has too many chunks")
    if json_chunk is None:
        raise ValueError("GLB is missing its JSON chunk")
    try:
        document = json.loads(json_chunk.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("GLB JSON chunk is invalid") from error
    if not isinstance(document, dict) or not isinstance(document.get("asset"), dict):
        raise ValueError("GLB JSON must contain an asset object")
    if document["asset"].get("version") != "2.0":
        raise ValueError("Only glTF asset version 2.0 is supported")
    required_extensions = document.get("extensionsRequired", [])
    required_extensions = _array(required_extensions, "extensionsRequired")
    if not all(isinstance(extension, str) for extension in required_extensions):
        raise ValueError("GLB extensionsRequired entries must be strings")
    if required_extensions:
        raise ValueError("Required GLB extensions are unsupported: " + ", ".join(map(str, required_extensions)))
    buffers = _list(document, "buffers")
    if len(buffers) != 1 or not isinstance(buffers[0], dict) or "uri" in buffers[0]:
        raise ValueError("GLB requires one embedded BIN buffer without an external or data URI")
    if binary_chunk is None:
        raise ValueError("GLB is missing its embedded BIN chunk")
    binary_length = _integer(buffers[0].get("byteLength"), "buffer byteLength", minimum=1)
    if binary_length > len(binary_chunk) or len(binary_chunk) - binary_length > 3:
        raise ValueError("GLB BIN chunk does not match the declared buffer length")
    binary = memoryview(binary_chunk)[:binary_length]

    meshes = _list(document, "meshes")
    if not meshes:
        raise ValueError("GLB contains no meshes")
    mesh_instances = _scene_mesh_instances(document, len(meshes))
    if not mesh_instances:
        raise ValueError("GLB active scene contains no mesh primitives")
    if len(mesh_instances) > MAX_GLB_PRIMITIVES:
        raise ValueError(f"GLB exceeds the {MAX_GLB_PRIMITIVES:,}-mesh limit")

    positions, uvs, normals, faces = [], [], [], []
    warnings = set()
    has_uvs = False
    has_normals = False
    optional_attributes = None
    primitive_count = 0
    for mesh_index, node_transform in mesh_instances:
        mirrored = _linear_determinant(node_transform) < 0
        normal_transform = _normal_matrix(node_transform)
        mesh = _item(meshes, mesh_index, "mesh")
        if mesh.get("extensions"):
            raise ValueError("GLB mesh extensions are unsupported")
        if mesh.get("weights"):
            raise ValueError("GLB mesh morph weights are unsupported; apply morphs before import")
        primitives = mesh.get("primitives")
        if not isinstance(primitives, list) or not primitives:
            raise ValueError("GLB mesh must contain primitives")
        for primitive in primitives:
            primitive_count += 1
            if primitive_count > MAX_GLB_PRIMITIVES:
                raise ValueError(f"GLB exceeds the {MAX_GLB_PRIMITIVES:,}-primitive limit")
            if not isinstance(primitive, dict):
                raise ValueError("GLB mesh primitive must be an object")
            if primitive.get("extensions"):
                raise ValueError("GLB primitive extensions are unsupported; export uncompressed geometry")
            mode = primitive.get("mode", 4)
            if type(mode) is not int or mode != 4:
                raise ValueError("Only GLB TRIANGLES primitives are supported")
            if primitive.get("targets"):
                raise ValueError("GLB morph targets are unsupported; apply morphs before import")
            attributes = primitive.get("attributes")
            if not isinstance(attributes, dict) or "POSITION" not in attributes:
                raise ValueError("GLB mesh primitive requires POSITION")
            primitive_attributes = ("NORMAL" in attributes, "TEXCOORD_0" in attributes)
            if optional_attributes is None:
                optional_attributes = primitive_attributes
            elif primitive_attributes != optional_attributes:
                raise ValueError("All GLB primitives must consistently provide NORMAL and TEXCOORD_0")
            if "JOINTS_0" in attributes or "WEIGHTS_0" in attributes:
                raise ValueError("Skinned GLB vertex attributes are unsupported; export a static mesh")
            ignored = set(attributes) - {"POSITION", "NORMAL", "TEXCOORD_0"}
            if ignored:
                warnings.add("GLB vertex attributes ignored: " + ", ".join(sorted(ignored)))
            if primitive.get("material") is not None:
                warnings.add("GLB materials and textures are ignored; the editor preview remains untextured and native replacement keeps its existing game material")
            base = len(positions)
            part_positions = _accessor_values(
                document, binary, attributes["POSITION"], expected_type="VEC3", role="POSITION",
                max_count=MAX_GLB_VERTICES - len(positions))
            count = len(part_positions)
            if "NORMAL" in attributes:
                source_normals = _accessor_values(
                    document, binary, attributes["NORMAL"], expected_type="VEC3", role="NORMAL",
                    max_count=count)
                if len(source_normals) != count:
                    raise ValueError("GLB NORMAL and POSITION accessor counts differ")
                part_normals = [_transform_normal(normal_transform, normal)
                                for normal in source_normals]
                has_normals = True
            else:
                part_normals = [None] * count
            if "TEXCOORD_0" in attributes:
                part_uvs = _accessor_values(
                    document, binary, attributes["TEXCOORD_0"], expected_type="VEC2", role="TEXCOORD_0",
                    max_count=count)
                if len(part_uvs) != count:
                    raise ValueError("GLB TEXCOORD_0 and POSITION accessor counts differ")
                has_uvs = True
            else:
                part_uvs = [None] * count
            if "indices" in primitive:
                part_indices = _accessor_values(
                    document, binary, primitive["indices"], expected_type="SCALAR", role="indices",
                    max_count=MAX_GLB_TRIANGLES * 3)
            else:
                part_indices = list(range(count))
            if len(part_indices) % 3:
                raise ValueError("GLB triangle index count must be divisible by three")
            if len(faces) + len(part_indices) // 3 > MAX_GLB_TRIANGLES:
                raise ValueError(f"GLB exceeds the {MAX_GLB_TRIANGLES:,}-triangle limit")
            if any(index >= count for index in part_indices):
                raise ValueError("GLB index references a missing vertex")
            try:
                positions.extend(_transform_position(node_transform, position)
                                 for position in part_positions)
            except ValueError as error:
                raise ValueError(f"GLB mesh node {mesh_index}: {error}") from error
            uvs.extend(part_uvs)
            normals.extend(part_normals)
            for offset in range(0, len(part_indices), 3):
                triangle = part_indices[offset:offset + 3]
                if mirrored:
                    triangle = (triangle[0], triangle[2], triangle[1])
                faces.append(tuple(base + index for index in triangle))

    if document.get("animations"):
        warnings.add("GLB animations are ignored; imported geometry uses its static source pose")
    if document.get("extensionsUsed"):
        used = _array(document["extensionsUsed"], "extensionsUsed")
        if not all(isinstance(extension, str) for extension in used):
            raise ValueError("GLB extensionsUsed entries must be strings")
        warnings.add("GLB optional extensions are not evaluated: " + ", ".join(map(str, used)))
    if not positions or not faces:
        raise ValueError("GLB contains no indexed triangles")
    if not has_uvs:
        uvs = None
    if not has_normals:
        normals = None
    return (positions, faces, uvs, normals), tuple(sorted(warnings))


def read_glb(path, *, include_report=False):
    """Read one local GLB file, enforcing the import size limit before parsing."""
    path = Path(path)
    size = path.stat().st_size
    if size > MAX_GLB_FILE_BYTES:
        raise ValueError(f"GLB exceeds the {MAX_GLB_FILE_BYTES // (1024 * 1024)} MiB file-size limit")
    with path.open("rb") as stream:
        data = stream.read(MAX_GLB_FILE_BYTES + 1)
    if len(data) > MAX_GLB_FILE_BYTES:
        raise ValueError(f"GLB exceeds the {MAX_GLB_FILE_BYTES // (1024 * 1024)} MiB file-size limit")
    geometry, warnings = parse_glb(data)
    return (geometry, warnings) if include_report else geometry
