from pathlib import Path
import hashlib
import struct
import unittest

from worldstudio.archive import Archive
from worldstudio.bfres_texture import extract_base_color_texture, extract_bc1_base_texture
from worldstudio.preview_textures import attach_base_color_textures
from worldstudio.texture_preview import decode_bc1, decode_bc3, detile_bc1_thin1, detile_bc3_thin1
from tests.test_mesh import fixture as bfres_fixture


def texture_fixture(surface_format):
    """Small synthetic BFRES material and FTEX record, with no game data."""
    data = bytearray(0x3000)
    data[:len(bfres_fixture())] = bfres_fixture()
    cursor = 0x1000

    def u32(offset, value):
        struct.pack_into('>I', data, offset, value)

    def pointer(offset, target):
        u32(offset, (target - offset) & 0xFFFFFFFF if target else 0)

    def string(value):
        nonlocal cursor
        offset = cursor
        raw = value.encode('utf-8') + b'\0'
        data[offset:offset + len(raw)] = raw
        cursor += len(raw)
        return offset

    def dictionary(offset, entries):
        u32(offset, 8 + 16 * (len(entries) + 1))
        u32(offset + 4, len(entries))
        for index, (name, target) in enumerate(entries):
            node = offset + 24 + 16 * index
            pointer(node + 8, string(name))
            pointer(node + 12, target)

    pointer(0x24, 0x880)
    dictionary(0x880, [('Grass_alb', 0xA00)])
    data[0x791] = 1
    pointer(0x7A8, 0x820)
    pointer(0x820, string('Grass_alb'))
    pointer(0x824, 0xA00)
    data[0xA00:0xA04] = b'FTEX'
    for offset, value in ((8, 4), (12, 4), (16, 1), (20, 1), (24, surface_format),
                          (28, 0), (32, 1), (36, 4096 if surface_format == 0x31 else 8192),
                          (44, 0), (52, 4), (56, 0), (64, 32)):
        u32(0xA00 + offset, value)
    pointer(0xAB0, 0xB80)
    return bytes(data)


class SyntheticTextureReferenceTests(unittest.TestCase):
    def test_generic_extractor_accepts_only_bc1_and_bc3_albedos(self):
        for fmt in (0x31, 0x33):
            with self.subTest(format=fmt):
                texture = extract_base_color_texture(texture_fixture(fmt), 'CS_W1_World', 'mtGrass')
                self.assertEqual((texture['name'], texture['format'], texture['data_size']),
                                 ('Grass_alb', fmt, 4096 if fmt == 0x31 else 8192))
                self.assertEqual(len(texture['data']), texture['data_size'])

        with self.assertRaisesRegex(ValueError, 'expected GX2 BC1'):
            extract_bc1_base_texture(texture_fixture(0x33), 'CS_W1_World', 'mtGrass')
        with self.assertRaisesRegex(ValueError, 'supported base-color format'):
            extract_base_color_texture(texture_fixture(0x35), 'CS_W1_World', 'mtGrass')

    def test_texture_catalog_handles_bc3_and_keeps_unsupported_material_visible(self):
        shape = {'material': 'mtGrass', 'uvs': [(0.0, 0.0)]}
        textures, failed = attach_base_color_textures(texture_fixture(0x33), [shape])
        self.assertEqual(set(textures), {'Grass_alb'})
        self.assertEqual(shape['texture'], 'Grass_alb')
        self.assertFalse(failed)
        self.assertEqual(len(textures['Grass_alb']['rgbaBase64']), 88)

        unsupported = {'material': 'mtGrass', 'uvs': [(0.0, 0.0)]}
        textures, failed = attach_base_color_textures(texture_fixture(0x35), [unsupported])
        self.assertFalse(textures)
        self.assertEqual(failed, {'mtGrass'})
        self.assertNotIn('texture', unsupported)

    def test_texture_catalog_enforces_decoded_pixel_budget(self):
        shape = {'material': 'mtGrass', 'uvs': [(0.0, 0.0)]}
        textures, failed = attach_base_color_textures(
            texture_fixture(0x31), [shape], max_texture_pixels=15)
        self.assertFalse(textures)
        self.assertEqual(failed, {'mtGrass'})


class LocalTextureReferenceTests(unittest.TestCase):
    def test_local_w1_grass_material_resolves_bc1_base_color(self):
        root = Path(__file__).resolve().parents[1]
        source = root / 'NSMBU Modding Project/content/Common/course_select/CS_W1.szs'
        if not source.is_file():
            self.skipTest('User-provided local W1 dump unavailable')
        archive = Archive(source.read_bytes())
        model = archive.read('CS_W1.bfres')
        texture = extract_bc1_base_texture(model, 'CS_W1_World', 'mtGrass')
        self.assertEqual(texture['name'], 'Grass_alb')
        self.assertEqual((texture['width'], texture['height']), (256, 256))
        self.assertEqual((texture['format'], texture['tile_mode'], texture['pitch']), (0x31, 4, 64))
        self.assertEqual((texture['data_size'], len(texture['data'])), (32768, 32768))
        compact = detile_bc1_thin1(
            texture['data'], texture['width'], texture['height'], texture['pitch'],
            tile_mode=texture['tile_mode'], swizzle=texture['swizzle'], depth=texture['depth'])
        self.assertEqual(hashlib.sha256(compact).hexdigest(),
                         '5b3259554630cc41ab604eefaa55cff6035e00db99ddde509c1ee0b60bf65220')
        rgba = decode_bc1(compact, texture['width'], texture['height'])
        self.assertEqual(len(rgba), 256 * 256 * 4)
        self.assertEqual(set(rgba[3::4]), {255})

    def test_local_w1_route_material_resolves_and_decodes_bc3(self):
        root = Path(__file__).resolve().parents[1]
        source = root / 'NSMBU Modding Project/content/Common/course_select/CS_W1.szs'
        if not source.is_file():
            self.skipTest('User-provided local W1 dump unavailable')
        archive = Archive(source.read_bytes())
        model = archive.read('CS_W1.bfres')
        texture = extract_base_color_texture(model, 'CS_W1_World', 'mtRW102W1S0a')
        self.assertEqual(texture['name'], 'RouteW1_alb')
        self.assertEqual((texture['width'], texture['height']), (128, 256))
        self.assertEqual((texture['format'], texture['tile_mode'], texture['pitch']), (0x33, 4, 32))
        self.assertEqual((texture['data_size'], len(texture['data'])), (32768, 32768))
        self.assertEqual(hashlib.sha256(texture['data']).hexdigest(),
                         '34573278d6094c477acec437cef79f518f20d6f22712d2f60b44f451f87617f1')
        compact = detile_bc3_thin1(
            texture['data'], texture['width'], texture['height'], texture['pitch'],
            tile_mode=texture['tile_mode'], swizzle=texture['swizzle'], depth=texture['depth'])
        self.assertEqual(hashlib.sha256(compact).hexdigest(),
                         'e73b121700fbccc80ca7ccf2d6c691df996f487fde4778b5566f8359e6b8f9d3')
        rgba = decode_bc3(compact, texture['width'], texture['height'])
        self.assertEqual(len(rgba), 128 * 256 * 4)
        self.assertTrue(any(alpha < 255 for alpha in rgba[3::4]))

    def test_local_w1_scene_resolves_all_uv_material_albedos(self):
        from worldstudio.mesh import extract_rigid_model

        root = Path(__file__).resolve().parents[1]
        source = root / 'NSMBU Modding Project/content/Common/course_select/CS_W1.szs'
        if not source.is_file():
            self.skipTest('User-provided local W1 dump unavailable')
        model = Archive(source.read_bytes()).read('CS_W1.bfres')
        shapes = extract_rigid_model(model)
        textures, failed = attach_base_color_textures(model, shapes)
        self.assertEqual(len(shapes), 42)
        self.assertEqual(sum(bool(shape.get('texture')) for shape in shapes), 36)
        self.assertEqual(len(textures), 17)
        self.assertFalse(failed)


if __name__ == '__main__':
    unittest.main()
