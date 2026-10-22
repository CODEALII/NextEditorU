import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from worldstudio.archive import Archive
from worldstudio.editor import read_import_mesh, read_obj
from worldstudio.gltf import parse_glb, read_glb
from worldstudio.mesh import (DEFAULT_SHAPE, _geometry, extract_rigid_model,
                              project_terrain_for_preview, replace_rigid_mesh)
from worldstudio.project import WorldProject
from worldstudio.__main__ import DEFAULT_SOURCE


def _fixture(*, uv_component=5126, node=None, primitive=None):
    positions = struct.pack("<9f", 0, 0, 0, 0, 0, 1, 1, 0, 0)
    if uv_component == 5123:
        uvs = struct.pack("<6H", 0, 0, 0, 65535, 65535, 0)
        uv_format = {"componentType": uv_component, "normalized": True}
    else:
        uvs = struct.pack("<6f", 0, 0, 0, 1, 1, 0)
        uv_format = {"componentType": uv_component}
    normals = struct.pack("<9f", 0, 1, 0, 0, 1, 0, 0, 1, 0)
    indices = struct.pack("<3H", 0, 1, 2)
    binary = positions + uvs + normals + indices
    views = [
        {"buffer": 0, "byteOffset": 0, "byteLength": len(positions)},
        {"buffer": 0, "byteOffset": len(positions), "byteLength": len(uvs)},
        {"buffer": 0, "byteOffset": len(positions) + len(uvs), "byteLength": len(normals)},
        {"buffer": 0, "byteOffset": len(positions) + len(uvs) + len(normals),
         "byteLength": len(indices)},
    ]
    if uv_component == 5123:
        views[1]["byteStride"] = 4
    attributes = {"POSITION": 0, "TEXCOORD_0": 1, "NORMAL": 2}
    accessors = [
        {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
        {"bufferView": 1, "count": 3, "type": "VEC2", **uv_format},
        {"bufferView": 2, "componentType": 5126, "count": 3, "type": "VEC3"},
        {"bufferView": 3, "componentType": 5123, "count": 3, "type": "SCALAR"},
    ]
    base_primitive = {"attributes": attributes, "indices": 3}
    if primitive:
        base_primitive.update(primitive)
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": views,
        "accessors": accessors,
        "meshes": [{"primitives": [base_primitive]}],
        "nodes": [node or {"mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    return document, binary


def _glb(document, binary):
    document = json.loads(json.dumps(document))
    document["buffers"][0]["byteLength"] = len(binary)
    json_chunk = json.dumps(document, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * ((-len(json_chunk)) % 4)
    binary_chunk = binary + b"\0" * ((-len(binary)) % 4)
    chunks = (struct.pack("<II", len(json_chunk), 0x4E4F534A) + json_chunk +
              struct.pack("<II", len(binary_chunk), 0x004E4942) + binary_chunk)
    total = 12 + len(chunks)
    return struct.pack("<III", 0x46546C67, 2, total) + chunks


def _geometry_glb(vertices, faces, uvs, normals, *, node=None):
    """Pack validated terrain arrays as one embedded static GLB mesh."""
    values = []
    for point in vertices:
        values.extend(point)
    positions = struct.pack("<" + "f" * len(values), *values)
    texcoords = [component for uv in uvs for component in uv]
    uv_data = struct.pack("<" + "f" * len(texcoords), *texcoords)
    normal_values = [component for normal in normals for component in normal]
    normal_data = struct.pack("<" + "f" * len(normal_values), *normal_values)
    indexes = [index for face in faces for index in face]
    index_data = struct.pack("<" + "H" * len(indexes), *indexes)
    chunks = []
    offsets = []
    for payload in (positions, uv_data, normal_data, index_data):
        while sum(map(len, chunks)) % 4:
            chunks.append(b"\0")
        offsets.append(sum(map(len, chunks)))
        chunks.append(payload)
    binary = b"".join(chunks)
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": offsets[0], "byteLength": len(positions)},
            {"buffer": 0, "byteOffset": offsets[1], "byteLength": len(uv_data)},
            {"buffer": 0, "byteOffset": offsets[2], "byteLength": len(normal_data)},
            {"buffer": 0, "byteOffset": offsets[3], "byteLength": len(index_data)},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(vertices), "type": "VEC3"},
            {"bufferView": 1, "componentType": 5126, "count": len(uvs), "type": "VEC2"},
            {"bufferView": 2, "componentType": 5126, "count": len(normals), "type": "VEC3"},
            {"bufferView": 3, "componentType": 5123, "count": len(indexes), "type": "SCALAR"},
        ],
        "meshes": [{"primitives": [{
            "attributes": {"POSITION": 0, "TEXCOORD_0": 1, "NORMAL": 2},
            "indices": 3,
        }]}],
        "nodes": [{"mesh": 0, **(node or {})}], "scenes": [{"nodes": [0]}], "scene": 0,
    }
    return _glb(document, binary)


class GlbReaderTests(unittest.TestCase):
    def test_reads_positions_normals_uvs_and_triangles_from_glb(self):
        document, binary = _fixture()
        geometry, warnings = parse_glb(_glb(document, binary))
        vertices, faces, uvs, normals = geometry
        self.assertEqual(vertices, [(0., 0., 0.), (0., 0., 1.), (1., 0., 0.)])
        self.assertEqual(faces, [(0, 1, 2)])
        self.assertEqual(uvs, [(0., 0.), (0., 1.), (1., 0.)])
        self.assertEqual(normals, [(0., 1., 0.)] * 3)
        self.assertEqual(warnings, ())

    def test_reads_normalized_unsigned_short_uvs(self):
        document, binary = _fixture(uv_component=5123)
        geometry, _ = parse_glb(_glb(document, binary))
        self.assertEqual(geometry[2], [(0., 0.), (0., 1.), (1., 0.)])

    def test_accepts_tightly_packed_u16x2_uvs(self):
        document, binary = _fixture(uv_component=5123)
        document["bufferViews"][1].pop("byteStride")
        geometry, _ = parse_glb(_glb(document, binary))
        self.assertEqual(geometry[2], [(0., 0.), (0., 1.), (1., 0.)])

    def test_reads_interleaved_vertex_attributes_with_declared_stride(self):
        rows = ((0, 0, 0, 0, 0, 0, 1, 0),
                (0, 0, 1, 0, 1, 0, 1, 0),
                (1, 0, 0, 1, 0, 0, 1, 0))
        binary = b"".join(struct.pack("<3f2f3f", *row) for row in rows)
        binary += struct.pack("<3H", 0, 1, 2)
        document = {
            "asset": {"version": "2.0"},
            "buffers": [{"byteLength": len(binary)}],
            "bufferViews": [
                {"buffer": 0, "byteLength": 96, "byteStride": 32},
                {"buffer": 0, "byteOffset": 96, "byteLength": 6},
            ],
            "accessors": [
                {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
                {"bufferView": 0, "byteOffset": 12, "componentType": 5126,
                 "count": 3, "type": "VEC2"},
                {"bufferView": 0, "byteOffset": 20, "componentType": 5126,
                 "count": 3, "type": "VEC3"},
                {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"},
            ],
            "meshes": [{"primitives": [{
                "attributes": {"POSITION": 0, "TEXCOORD_0": 1, "NORMAL": 2},
                "indices": 3,
            }]}],
        }
        geometry, _ = parse_glb(_glb(document, binary))
        self.assertEqual(geometry[1], [(0, 1, 2)])
        self.assertEqual(geometry[2], [(0., 0.), (0., 1.), (1., 0.)])
        self.assertEqual(geometry[3], [(0., 1., 0.)] * 3)

    def test_editor_import_path_returns_attributes_and_format_diagnostics(self):
        document, binary = _fixture(primitive={"material": 0})
        data = _glb(document, binary)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "terrain.glb"
            path.write_bytes(data)
            geometry, warnings = read_import_mesh(
                path, include_attributes=True, include_report=True)
            preview_geometry = read_import_mesh(path)
        self.assertEqual(len(geometry), 4)
        self.assertEqual(len(geometry[2]), 3)
        self.assertEqual(len(preview_geometry), 2)
        self.assertTrue(any("materials and textures are ignored" in warning for warning in warnings))

    def test_merges_multiple_primitives_and_reports_ignored_materials(self):
        document, binary = _fixture(primitive={"material": 0})
        document["meshes"][0]["primitives"].append(
            {"attributes": {"POSITION": 0, "TEXCOORD_0": 1, "NORMAL": 2}, "indices": 3})
        document["materials"] = [{}]
        geometry, warnings = parse_glb(_glb(document, binary))
        self.assertEqual(len(geometry[0]), 6)
        self.assertEqual(geometry[1], [(0, 1, 2), (3, 4, 5)])
        self.assertEqual(geometry[2][3:], [(0., 0.), (0., 1.), (1., 0.)])
        self.assertIn("GLB materials and textures are ignored", warnings[0])

    def test_rejects_mixed_primitive_attributes_and_compressed_buffer_views(self):
        document, binary = _fixture()
        document["meshes"][0]["primitives"].append({"attributes": {"POSITION": 0}, "indices": 3})
        with self.assertRaisesRegex(ValueError, "consistently provide NORMAL and TEXCOORD_0"):
            parse_glb(_glb(document, binary))
        document, binary = _fixture()
        document["bufferViews"][0]["extensions"] = {"EXT_meshopt_compression": {}}
        with self.assertRaisesRegex(ValueError, "bufferView extensions are unsupported"):
            parse_glb(_glb(document, binary))

    def test_rejects_boolean_buffer_indexes_and_boolean_node_transforms(self):
        document, binary = _fixture()
        document["bufferViews"][0]["buffer"] = False
        with self.assertRaisesRegex(ValueError, "bufferView buffer index"):
            parse_glb(_glb(document, binary))
        document, binary = _fixture(node={"mesh": 0, "translation": [False, 0, 0]})
        with self.assertRaisesRegex(ValueError, "finite numbers"):
            parse_glb(_glb(document, binary))

    def test_reads_multiple_identity_mesh_nodes_without_reusing_meshes(self):
        document, binary = _fixture()
        document["meshes"].append({"primitives": [document["meshes"][0]["primitives"][0]]})
        document["nodes"] = [{"mesh": 0}, {"mesh": 1}]
        document["scenes"] = [{"nodes": [0, 1]}]
        geometry, _ = parse_glb(_glb(document, binary))
        self.assertEqual(geometry[1], [(0, 1, 2), (3, 4, 5)])

    def test_applies_node_trs_and_nested_parent_transforms(self):
        document, binary = _fixture(node={
            "mesh": 0,
            "translation": [2, 3, 4],
            "rotation": [0, 2 ** -0.5, 0, 2 ** -0.5],
            "scale": [2, 1, 0.5],
        })
        geometry, _ = parse_glb(_glb(document, binary))
        expected_positions = [(2., 3., 4.), (2.5, 3., 4.), (2., 3., 2.)]
        for actual, expected in zip(geometry[0], expected_positions):
            for value, target in zip(actual, expected):
                self.assertAlmostEqual(value, target)
        self.assertEqual(geometry[3], [(0., 1., 0.)] * 3)

        document, binary = _fixture()
        document["nodes"] = [
            {"children": [1], "translation": [1, 0, 0]},
            {"mesh": 0, "translation": [0, 2, 0]},
        ]
        document["scenes"] = [{"nodes": [0]}]
        geometry, _ = parse_glb(_glb(document, binary))
        self.assertEqual(geometry[0][0], (1., 2., 0.))
        self.assertEqual(geometry[0][1], (1., 2., 1.))

    def test_applies_affine_matrix_inverse_transpose_normals_and_mirror_winding(self):
        document, binary = _fixture()
        document["nodes"][0] = {
            "mesh": 0,
            "matrix": [-1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 2, 0, 0, 1],
        }
        geometry, _ = parse_glb(_glb(document, binary))
        self.assertEqual(geometry[0], [(2., 0., 0.), (2., 0., 1.), (1., 0., 0.)])
        self.assertEqual(geometry[1], [(0, 2, 1)])

        document, binary = _fixture()
        position_bytes = binary[:36]
        uv_bytes = binary[36:60]
        normals = struct.pack("<9f", *([1., 1., 0.] * 3))
        binary = position_bytes + uv_bytes + normals + binary[96:]
        document["buffers"][0]["byteLength"] = len(binary)
        document["nodes"][0] = {"mesh": 0, "scale": [2, 1, 0.5]}
        geometry, _ = parse_glb(_glb(document, binary))
        self.assertAlmostEqual(geometry[3][0][0], 1 / (5 ** 0.5))
        self.assertAlmostEqual(geometry[3][0][1], 2 / (5 ** 0.5))

    def test_rejects_invalid_affine_node_transforms_and_skinning(self):
        document, binary = _fixture(node={"mesh": 0, "scale": [0, 1, 1]})
        with self.assertRaisesRegex(ValueError, "invertible"):
            parse_glb(_glb(document, binary))
        document, binary = _fixture(node={"mesh": 0, "rotation": [0, 0, 0, 0]})
        with self.assertRaisesRegex(ValueError, "normalized quaternion"):
            parse_glb(_glb(document, binary))
        matrix = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        matrix[3] = 0.25
        document, binary = _fixture(node={"mesh": 0, "matrix": matrix})
        with self.assertRaisesRegex(ValueError, "must be affine"):
            parse_glb(_glb(document, binary))
        document, binary = _fixture(node={"mesh": 0, "matrix": matrix,
                                         "translation": [0, 0, 0]})
        with self.assertRaisesRegex(ValueError, "both matrix and TRS"):
            parse_glb(_glb(document, binary))
        document, binary = _fixture(node={"mesh": 0, "skin": 0})
        with self.assertRaisesRegex(ValueError, "Skinned GLB"):
            parse_glb(_glb(document, binary))
        document, binary = _fixture(primitive={"attributes": {"POSITION": 0, "WEIGHTS_0": 1}})
        with self.assertRaisesRegex(ValueError, "Skinned GLB vertex"):
            parse_glb(_glb(document, binary))

    def test_rejects_invalid_headers_chunks_and_external_buffers(self):
        document, binary = _fixture()
        data = bytearray(_glb(document, binary))
        data[0] = 0
        with self.assertRaisesRegex(ValueError, "header"):
            parse_glb(data)
        data = bytearray(_glb(document, binary))
        data[8:12] = struct.pack("<I", len(data) - 4)
        with self.assertRaisesRegex(ValueError, "header"):
            parse_glb(data)
        document["buffers"][0]["uri"] = "outside.bin"
        with self.assertRaisesRegex(ValueError, "external or data URI"):
            parse_glb(_glb(document, binary))

    def test_rejects_sparse_accessors_invalid_indices_and_unsupported_modes(self):
        document, binary = _fixture()
        document["accessors"][0]["sparse"] = {"count": 1}
        with self.assertRaisesRegex(ValueError, "Sparse GLB POSITION"):
            parse_glb(_glb(document, binary))
        document, binary = _fixture()
        binary = binary[:-6] + struct.pack("<3H", 0, 1, 3)
        with self.assertRaisesRegex(ValueError, "missing vertex"):
            parse_glb(_glb(document, binary))
        document, binary = _fixture(primitive={"mode": 1})
        with self.assertRaisesRegex(ValueError, "TRIANGLES"):
            parse_glb(_glb(document, binary))

    def test_read_glb_bounds_file_size_before_reading(self):
        document, binary = _fixture()
        data = _glb(document, binary)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mesh.glb"
            path.write_bytes(data)
            with patch("worldstudio.gltf.MAX_GLB_FILE_BYTES", len(data) - 1):
                with self.assertRaisesRegex(ValueError, "file-size limit"):
                    read_glb(path)

    def test_glb_geometry_fits_existing_grass_replacement_pipeline(self):
        root = Path(__file__).resolve().parents[1]
        source = root / "NSMBU Modding Project/content/Common/course_select/CS_W1.szs"
        if not source.is_file():
            self.skipTest("User-provided local W1 archive unavailable")
        model = Archive(source.read_bytes()).read("CS_W1.bfres")
        document, binary = _fixture()
        vertices, faces, uvs, normals = parse_glb(_glb(document, binary))[0]
        output, report = replace_rigid_mesh(
            model, vertices, faces, uvs=uvs, imported_normals=normals)
        self.assertEqual(len(output), len(model))
        self.assertEqual((report["vertices"], report["triangles"]), (3, 1))

    @unittest.skipUnless(DEFAULT_SOURCE.is_file(), "Local user-owned W1 dump unavailable")
    def test_glb_project_export_roundtrip_preserves_native_grass_topology(self):
        root = Path(__file__).resolve().parents[1]
        obj_path = root / "examples" / "island-game.obj"
        vertices, faces, _, _ = read_obj(obj_path, include_attributes=True)
        normalized_vertices, indices, normals, _ = _geometry(vertices, faces)
        normalized_faces = [tuple(indices[index:index + 3])
                            for index in range(0, len(indices), 3)]
        low_x, high_x = min(point[0] for point in normalized_vertices), max(
            point[0] for point in normalized_vertices)
        low_z, high_z = min(point[2] for point in normalized_vertices), max(
            point[2] for point in normalized_vertices)
        uvs = [((point[0] - low_x) / max(1., high_x - low_x),
                (point[2] - low_z) / max(1., high_z - low_z))
               for point in normalized_vertices]
        project = WorldProject.open(DEFAULT_SOURCE)
        original_archive = DEFAULT_SOURCE.read_bytes()

        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            glb_path = folder / "island.glb"
            glb_path.write_bytes(_geometry_glb(
                normalized_vertices, normalized_faces, uvs, normals,
                node={"scale": [0.99, 1., 0.99]}))
            imported, warnings = read_import_mesh(
                glb_path, include_attributes=True, include_report=True)
            self.assertEqual(warnings, ())
            source_model = Archive(original_archive).read(project.model_name)
            preview_shapes = extract_rigid_model(source_model, project.model_name.removesuffix(".bfres") + "_World")
            preview_report = project_terrain_for_preview(
                source_model, preview_shapes, imported[0], imported[1],
                model=project.model_name.removesuffix(".bfres") + "_World",
                uvs=imported[2], imported_normals=imported[3])
            self.assertGreater(preview_report["vertices_displaced"], 0)
            project.geometry = {
                "vertices": imported[0], "faces": imported[1],
                "uvs": imported[2], "normals": imported[3],
            }
            project.terrain = str(glb_path)
            project_path = folder / "terrain.nws.json"
            output_path = folder / "CS_W1-glb-terrain.szs"
            project.save(project_path)
            reopened_project = WorldProject.load(project_path)
            manifest = reopened_project.export(output_path)

            self.assertTrue(manifest["terrain_exported"])
            self.assertTrue(manifest["geometry"]["topology_preserved"])
            self.assertTrue(manifest["geometry"]["indices_preserved"])
            self.assertGreater(manifest["geometry"]["vertices_displaced"], 0)
            archive = Archive(output_path.read_bytes())
            model = archive.read(project.model_name)
            grass = next(shape for shape in extract_rigid_model(model)
                         if shape["name"] == DEFAULT_SHAPE)
            source_grass = next(shape for shape in extract_rigid_model(source_model)
                                if shape["name"] == DEFAULT_SHAPE)
            preview_grass = next(shape for shape in preview_shapes
                                 if shape["name"] == DEFAULT_SHAPE)
            self.assertEqual(grass["indices"], source_grass["indices"])
            self.assertEqual(grass["uvs"], source_grass["uvs"])
            self.assertEqual(len(grass["positions"]), len(source_grass["positions"]))
            self.assertEqual(preview_grass["positions"], grass["positions"])
            self.assertEqual(preview_grass["normals"], grass["normals"])
            self.assertEqual(preview_grass["indices"], grass["indices"])
            self.assertEqual(preview_grass["uvs"], grass["uvs"])
            self.assertTrue(any(abs(actual[1] - before[1]) > 1e-5
                                for actual, before in zip(grass["positions"],
                                                          source_grass["positions"])))

        self.assertEqual(DEFAULT_SOURCE.read_bytes(), original_archive)


if __name__ == "__main__":
    unittest.main()
