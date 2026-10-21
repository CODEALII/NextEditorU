from pathlib import Path
import math
import struct
import unittest

from worldstudio.archive import Archive
from worldstudio.bfres import Skeletons
from worldstudio.bfres_material import (decode_texture_srt_record,
                                        extract_texture_srt_parameters)
from worldstudio.preview_textures import attach_texture_srt_parameters
from tests.test_mesh import fixture as bfres_fixture


def texture_srt_fixture(*, mode=0, scale=(1.0, 1.0), rotation=0.0,
                        translation=(0.0, -3.0), matrix_pointer=0):
    data = bytearray(0x2000)
    source = bfres_fixture()
    data[:len(source)] = source
    material, dictionary, parameter, values, name = 0x780, 0x1200, 0x1300, 0x1400, 0x1800

    def u32(offset, value):
        struct.pack_into(">I", data, offset, value)

    def pointer(offset, target):
        u32(offset, (target - offset) & 0xFFFFFFFF if target else 0)

    def text(offset, value):
        raw = value.encode("ascii") + b"\0"
        data[offset:offset + len(raw)] = raw

    u32(dictionary, 8 + 16 * 2)
    u32(dictionary + 4, 1)
    node = dictionary + 24
    text(name, "texmtx0")
    pointer(node + 8, name)
    pointer(node + 12, parameter)
    pointer(material + 56, dictionary)
    pointer(material + 60, values)
    struct.pack_into(">HHH", data, material + 18, 1, 0, 28)
    data[parameter] = 31
    data[parameter + 1] = 0
    struct.pack_into(">H", data, parameter + 2, 0)
    struct.pack_into(">i", data, parameter + 4, -1)
    pointer(parameter + 8, name)
    struct.pack_into(">I5fI", data, values, mode, *scale, rotation, *translation, matrix_pointer)
    return bytes(data)


class TextureSrtDecoderTests(unittest.TestCase):
    def test_decodes_named_fields_without_building_a_matrix(self):
        record = struct.pack(">I5fI", 0, 1.0, 2.0, 0.25, 0.0, -3.5, 0)
        self.assertEqual(decode_texture_srt_record(record), {
            "mode": 0, "scale": [1.0, 2.0], "rotation": 0.25,
            "translation": [0.0, -3.5],
        })

    def test_rejects_unsupported_or_invalid_records(self):
        with self.assertRaisesRegex(ValueError, "exactly 28 bytes"):
            decode_texture_srt_record(bytes(27))
        with self.assertRaisesRegex(ValueError, "mode"):
            decode_texture_srt_record(struct.pack(">I5fI", 3, 1, 1, 0, 0, 0, 0))
        with self.assertRaisesRegex(ValueError, "non-finite"):
            decode_texture_srt_record(struct.pack(">I5fI", 0, math.nan, 1, 0, 0, 0, 0))
        with self.assertRaisesRegex(ValueError, "matrix pointer"):
            decode_texture_srt_record(struct.pack(">I5fI", 0, 1, 1, 0, 0, 0, 1))

    def test_extracts_and_attaches_synthetic_material_parameter(self):
        data = texture_srt_fixture()
        expected = {"texmtx0": {"mode": 0, "scale": [1.0, 1.0],
                                 "rotation": 0.0, "translation": [0.0, -3.0]}}
        self.assertEqual(extract_texture_srt_parameters(data, "CS_W1_World", "mtGrass"), expected)
        shapes = [{"material": "mtGrass"}, {"material": "mtGrass"}, {"material": "missing"}]
        self.assertEqual(attach_texture_srt_parameters(data, shapes), {"missing"})
        self.assertEqual(shapes[0]["textureSrt"], expected)
        self.assertEqual(shapes[1]["textureSrt"], expected)
        self.assertNotIn("textureSrt", shapes[2])

    def test_rejects_parameter_offsets_outside_declared_data(self):
        data = bytearray(texture_srt_fixture())
        reader = Skeletons(data)
        models = dict(reader.dictionary(reader.ptr(0x20)))
        material_offset = dict(reader.dictionary(
            reader.ptr(models["CS_W1_World"] + 24)))["mtGrass"]
        params = reader.dictionary(reader.ptr(material_offset + 56))
        entry = params[0][1]
        struct.pack_into(">H", data, entry + 2, 28)
        with self.assertRaisesRegex(ValueError, "exceeds material parameter data"):
            extract_texture_srt_parameters(bytes(data), "CS_W1_World", "mtGrass")

    def test_local_w1_texture_srt_metadata_is_bounded_and_stable(self):
        root = Path(__file__).resolve().parents[1]
        source = root / "NSMBU Modding Project/content/Common/course_select/CS_W1.szs"
        if not source.is_file():
            self.skipTest("User-provided local W1 dump unavailable")
        model = Archive(source.read_bytes()).read("CS_W1.bfres")
        reader = Skeletons(model)
        models = dict(reader.dictionary(reader.ptr(0x20)))
        materials = dict(reader.dictionary(reader.ptr(models["CS_W1_World"] + 24)))
        values = {name: extract_texture_srt_parameters(model, "CS_W1_World", name)
                  for name in materials}
        texmtx0 = {name: params["texmtx0"] for name, params in values.items()
                   if "texmtx0" in params}
        texmtx1 = {name: params["texmtx1"] for name, params in values.items()
                   if "texmtx1" in params}
        self.assertEqual((len(materials), len(texmtx0), len(texmtx1)), (36, 11, 36))
        for item in texmtx1.values():
            self.assertEqual(item, {"mode": 0, "scale": [1.0, 1.0],
                                    "rotation": 0.0, "translation": [0.0, 0.0]})
        for item in texmtx0.values():
            self.assertEqual(item["mode"], 0)
            self.assertEqual(item["scale"], [1.0, 1.0])
            self.assertEqual(item["rotation"], 0.0)
            self.assertEqual(item["translation"][0], 0.0)
            self.assertLess(item["translation"][1], 0.0)


if __name__ == "__main__":
    unittest.main()
