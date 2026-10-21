from pathlib import Path
import hashlib
import struct
import unittest

from worldstudio.archive import Archive
from worldstudio.bfres_texture import (extract_base_color_texture, extract_bc1_base_texture,
                                       extract_normal_map_texture, extract_sampler_diagnostic_texture)
from worldstudio.preview_textures import (attach_base_color_textures, attach_normal_map_textures,
                                          attach_sampler_diagnostic_textures)
from worldstudio.texture_preview import (decode_bc1, decode_bc3, decode_bc4_unorm,
                                         decode_bc5_snorm, decode_bc5_unorm,
                                         detile_bc1_thin1, detile_bc3_thin1, detile_bc4_thin1,
                                         detile_bc5_snorm_thin1, detile_bc5_unorm_thin1)
from tests.test_mesh import fixture as bfres_fixture


def texture_fixture(surface_format, texture_name='Grass_alb', sampler_name=None):
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
    dictionary(0x880, [(texture_name, 0xA00)])
    data[0x790] = 1 if sampler_name else 0
    data[0x791] = 1
    pointer(0x7A8, 0x820)
    pointer(0x820, string(texture_name))
    pointer(0x824, 0xA00)
    if sampler_name:
        pointer(0x7B0, 0x840)
        dictionary(0x840, [(sampler_name, 0xA80)])
    data[0xA00:0xA04] = b'FTEX'
    for offset, value in ((8, 4), (12, 4), (16, 1), (20, 1), (24, surface_format),
                          (28, 0), (32, 1), (36, 4096 if surface_format in (0x31, 0x34) else 8192),
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

    def test_normal_extractor_requires_bc5_snorm_in_n0_sampler_slot(self):
        texture = extract_normal_map_texture(
            texture_fixture(0x235, 'Grass_nml', '_n0'), 'CS_W1_World', 'mtGrass')
        self.assertEqual((texture['name'], texture['format'], texture['data_size']),
                         ('Grass_nml', 0x235, 8192))
        with self.assertRaisesRegex(ValueError, 'supported normal-map format'):
            extract_normal_map_texture(
                texture_fixture(0x35, 'Grass_nml', '_n0'), 'CS_W1_World', 'mtGrass')
        with self.assertRaisesRegex(ValueError, r'expected exactly one \*_nml reference'):
            extract_normal_map_texture(
                texture_fixture(0x235, 'Grass_alb', '_n0'), 'CS_W1_World', 'mtGrass')
        with self.assertRaisesRegex(ValueError, r'expected a \*_nml normal-map reference'):
            extract_normal_map_texture(
                texture_fixture(0x235, 'NamedTexture', '_n0'), 'CS_W1_World', 'mtGrass',
                texture_name='NamedTexture')
        with self.assertRaisesRegex(ValueError, 'sampler slot _o0, expected _n0'):
            extract_normal_map_texture(
                texture_fixture(0x235, 'Grass_nml', '_o0'), 'CS_W1_World', 'mtGrass')
        with self.assertRaisesRegex(ValueError, 'texture-reference and sampler counts do not match'):
            extract_normal_map_texture(
                texture_fixture(0x235, 'Grass_nml'), 'CS_W1_World', 'mtGrass')

    def test_texture_catalog_handles_bc3_and_keeps_unsupported_material_visible(self):
        shape = {'material': 'mtGrass', 'uvs': [(0.0, 0.0)]}
        textures, failed = attach_base_color_textures(texture_fixture(0x33), [shape])
        self.assertEqual(set(textures), {'Grass_alb'})
        self.assertEqual(shape['texture'], 'Grass_alb')
        self.assertFalse(failed)
        self.assertEqual(textures['Grass_alb']['format'], 0x33)
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

    def test_normal_texture_catalog_is_bounded_and_labeled(self):
        fixture = texture_fixture(0x235, 'Grass_nml', '_n0')
        shape = {'material': 'mtGrass', 'uvs': [(0.0, 0.0)]}
        textures, failed = attach_normal_map_textures(fixture, [shape])
        self.assertEqual(set(textures), {'Grass_nml'})
        self.assertEqual(shape['normalTexture'], 'Grass_nml')
        self.assertFalse(failed)
        self.assertEqual(textures['Grass_nml']['format'], 0x235)
        self.assertEqual(len(textures['Grass_nml']['rgbaBase64']), 88)

        limited = {'material': 'mtGrass', 'uvs': [(0.0, 0.0)]}
        textures, failed = attach_normal_map_textures(fixture, [limited], max_texture_pixels=15)
        self.assertFalse(textures)
        self.assertEqual(failed, {'mtGrass'})


class SyntheticSamplerDiagnosticTests(unittest.TestCase):
    def test_diagnostic_extractor_requires_matching_sampler_slot_and_bc5_unorm(self):
        fixture = texture_fixture(0x35, 'Mask', '_o0')
        texture = extract_sampler_diagnostic_texture(fixture, 'CS_W1_World', 'mtGrass')
        self.assertEqual((texture['name'], texture['format'], texture['width'], texture['height']),
                         ('Mask', 0x35, 4, 4))
        with self.assertRaisesRegex(ValueError, 'expected exactly one _o0 sampler texture'):
            extract_sampler_diagnostic_texture(
                texture_fixture(0x35, 'Mask', '_n0'), 'CS_W1_World', 'mtGrass')
        with self.assertRaisesRegex(ValueError, 'supported diagnostic map format'):
            extract_sampler_diagnostic_texture(
                texture_fixture(0x235, 'Mask', '_o0'), 'CS_W1_World', 'mtGrass')
        texture = extract_sampler_diagnostic_texture(
            texture_fixture(0x34, 'RouteW1_msk', '_o1'), 'CS_W1_World', 'mtGrass', '_o1')
        self.assertEqual((texture['name'], texture['format']), ('RouteW1_msk', 0x34))
        with self.assertRaisesRegex(ValueError, 'supported diagnostic map format'):
            extract_sampler_diagnostic_texture(
                texture_fixture(0x35, 'RouteW1_msk', '_o1'), 'CS_W1_World', 'mtGrass', '_o1')
        for slot, name in (('_b0', 'BakeMap'), ('_s0', 'SpecMap'), ('_x2', 'RingSpec')):
            texture = extract_sampler_diagnostic_texture(
                texture_fixture(0x34, name, slot), 'CS_W1_World', 'mtGrass', slot)
            self.assertEqual((texture['name'], texture['format']), (name, 0x34))
        with self.assertRaisesRegex(ValueError, 'Unsupported diagnostic sampler slot'):
            extract_sampler_diagnostic_texture(
                texture_fixture(0x34, 'UnknownMap', '_z0'), 'CS_W1_World', 'mtGrass', '_z0')

    def test_diagnostic_catalog_attaches_bounded_channel_preview(self):
        shape = {'material': 'mtGrass', 'uvs': [(0.0, 0.0)]}
        textures, failed = attach_sampler_diagnostic_textures(
            texture_fixture(0x35, 'Mask', '_o0'), [shape])
        self.assertEqual(set(textures), {'Mask'})
        self.assertEqual(shape['diagnosticTexture'], 'Mask')
        self.assertFalse(failed)
        self.assertEqual(textures['Mask']['format'], 0x35)
        self.assertEqual(len(textures['Mask']['rgbaBase64']), 88)
        limited = {'material': 'mtGrass', 'uvs': [(0.0, 0.0)]}
        textures, failed = attach_sampler_diagnostic_textures(
            texture_fixture(0x35, 'Mask', '_o0'), [limited], max_texture_pixels=15)
        self.assertFalse(textures)
        self.assertEqual(failed, {'mtGrass'})
        shape = {'material': 'mtGrass', 'uvs': [(0.0, 0.0)]}
        textures, failed = attach_sampler_diagnostic_textures(
            texture_fixture(0x34, 'RouteW1_msk', '_o1'), [shape], sampler_slot='_o1')
        self.assertEqual(set(textures), {'RouteW1_msk'})
        self.assertEqual(shape['maskTexture'], 'RouteW1_msk')
        self.assertEqual(textures['RouteW1_msk']['samplerSlot'], '_o1')
        self.assertEqual(textures['RouteW1_msk']['format'], 0x34)
        self.assertFalse(failed)
        spec_shape = {'material': 'mtGrass', 'uvs': [(0.0, 0.0)]}
        textures, failed = attach_sampler_diagnostic_textures(
            texture_fixture(0x34, 'Dokan_spm', '_s0'), [spec_shape], sampler_slot='_s0')
        self.assertEqual(set(textures), {'_s0:Dokan_spm'})
        self.assertEqual(spec_shape['bc4Samplers'], {'_s0': '_s0:Dokan_spm'})
        self.assertEqual(textures['_s0:Dokan_spm']['samplerSlot'], '_s0')
        self.assertFalse(failed)


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

    def test_local_w1_normal_map_slots_are_bc5_snorm_and_decode(self):
        from worldstudio.bfres import Skeletons
        from worldstudio.mesh import extract_rigid_model

        root = Path(__file__).resolve().parents[1]
        source = root / 'NSMBU Modding Project/content/Common/course_select/CS_W1.szs'
        if not source.is_file():
            self.skipTest('User-provided local W1 dump unavailable')
        model = Archive(source.read_bytes()).read('CS_W1.bfres')
        shapes = extract_rigid_model(model)
        reader = Skeletons(model)
        world = dict(reader.dictionary(reader.ptr(0x20)))['CS_W1_World']
        materials = dict(reader.dictionary(reader.ptr(world + 24)))
        texture_dictionary = dict(reader.dictionary(reader.ptr(0x24)))
        self.assertEqual(len(materials), 36)
        for material_name, material in materials.items():
            reference_count = model[material + 17]
            sampler_count = model[material + 16]
            self.assertEqual(reference_count, sampler_count, material_name)
            refs = reader.ptr(material + 40)
            samplers = reader.dictionary(reader.ptr(material + 48))
            self.assertEqual(len(samplers), reference_count, material_name)
            reader.bounds(refs, reference_count * 8)
            for index in range(reference_count):
                texture_name = reader.string(reader.ptr(refs + index * 8))
                if texture_name.lower().endswith('_nml'):
                    self.assertEqual(samplers[index][0], '_n0', material_name)
                    self.assertEqual(reader.u32(texture_dictionary[texture_name] + 24), 0x235,
                                     texture_name)
        textures, failed = attach_normal_map_textures(model, shapes)
        textured = [shape for shape in shapes if shape.get('normalTexture')]
        self.assertEqual(len(textured), 22)
        self.assertTrue(textures)
        self.assertTrue(failed)
        route_texture = extract_normal_map_texture(model, 'CS_W1_World', 'mtRouteOpague')
        self.assertEqual((route_texture['name'], route_texture['width'], route_texture['height'],
                          route_texture['format'], route_texture['pitch'], route_texture['mip_count']),
                         ('RouteW1_nml', 128, 256, 0x235, 32, 9))
        self.assertEqual(hashlib.sha256(route_texture['data']).hexdigest(),
                         'c03491af2d4bc380b4df0147fe1cab318f36bbf66e2d004b32a04b9028def17e')
        route_compact = detile_bc5_snorm_thin1(
            route_texture['data'], route_texture['width'], route_texture['height'],
            route_texture['pitch'], tile_mode=route_texture['tile_mode'],
            swizzle=route_texture['swizzle'], depth=route_texture['depth'])
        self.assertEqual(hashlib.sha256(route_compact).hexdigest(),
                         '23b5fd8bde69c9b2fbb1f63741d6237558bb69b5e5f39cf9df29865dedd39418')
        for shape in textured:
            texture = extract_normal_map_texture(model, 'CS_W1_World', shape['material'])
            self.assertEqual(texture['format'], 0x235)
            compact = detile_bc5_snorm_thin1(
                texture['data'], texture['width'], texture['height'], texture['pitch'],
                tile_mode=texture['tile_mode'], swizzle=texture['swizzle'], depth=texture['depth'])
            rgba = decode_bc5_snorm(compact, texture['width'], texture['height'])
            self.assertEqual(len(rgba), texture['width'] * texture['height'] * 4)
            self.assertEqual(set(rgba[2::4]), {128})
            self.assertEqual(set(rgba[3::4]), {255})

    def test_local_w1_o0_bc5_unorm_maps_are_visible_as_diagnostics(self):
        from worldstudio.mesh import extract_rigid_model

        root = Path(__file__).resolve().parents[1]
        source = root / 'NSMBU Modding Project/content/Common/course_select/CS_W1.szs'
        if not source.is_file():
            self.skipTest('User-provided local W1 dump unavailable')
        model = Archive(source.read_bytes()).read('CS_W1.bfres')
        shapes = extract_rigid_model(model)
        textures, failed = attach_sampler_diagnostic_textures(model, shapes)
        mapped = [shape for shape in shapes if shape.get('diagnosticTexture')]
        self.assertEqual(set(textures), {'Mask', 'MaskOpaque'})
        self.assertEqual(len(mapped), 11)
        self.assertTrue(failed)
        route_map = extract_sampler_diagnostic_texture(
            model, 'CS_W1_World', 'mtRouteOpague', '_o0')
        self.assertEqual((route_map['name'], route_map['format'], route_map['width'],
                          route_map['height'], route_map['pitch']),
                         ('MaskOpaque', 0x35, 8, 64, 32))
        self.assertEqual(hashlib.sha256(route_map['data']).hexdigest(),
                         '3b45a34807619f2b6726903dd9b7f52c223fb8173af81ec8c2b2fc1c4e4c1769')
        compact = detile_bc5_unorm_thin1(
            route_map['data'], route_map['width'], route_map['height'], route_map['pitch'],
            tile_mode=route_map['tile_mode'], swizzle=route_map['swizzle'],
            depth=route_map['depth'])
        self.assertEqual(len(compact), ((8 + 3) // 4) * ((64 + 3) // 4) * 16)
        self.assertEqual(hashlib.sha256(compact).hexdigest(),
                         '022875a9770adbeb855411e8882b097c6018637371803bf8b9e23b545eef44af')
        rgba = decode_bc5_unorm(compact, route_map['width'], route_map['height'])
        self.assertEqual(len(rgba), 8 * 64 * 4)
        self.assertEqual(set(rgba[2::4]), {128})
        self.assertEqual(set(rgba[3::4]), {255})
        for shape in mapped:
            payload = textures[shape['diagnosticTexture']]
            self.assertEqual(len(payload['rgbaBase64']), ((payload['width'] * payload['height'] * 4 + 2) // 3) * 4)

    def test_local_w1_o1_bc4_unorm_route_map_is_visible_as_diagnostic(self):
        from worldstudio.mesh import extract_rigid_model

        root = Path(__file__).resolve().parents[1]
        source = root / 'NSMBU Modding Project/content/Common/course_select/CS_W1.szs'
        if not source.is_file():
            self.skipTest('User-provided local W1 dump unavailable')
        model = Archive(source.read_bytes()).read('CS_W1.bfres')
        shapes = extract_rigid_model(model)
        textures, failed = attach_sampler_diagnostic_textures(model, shapes, sampler_slot='_o1')
        mapped = [shape for shape in shapes if shape.get('maskTexture')]
        self.assertEqual(set(textures), {'RouteW1_msk'})
        self.assertEqual(len(mapped), 7)
        self.assertTrue(failed)
        route_map = extract_sampler_diagnostic_texture(
            model, 'CS_W1_World', 'mtRW101W102a', '_o1')
        self.assertEqual((route_map['name'], route_map['format'], route_map['width'],
                          route_map['height'], route_map['pitch']),
                         ('RouteW1_msk', 0x34, 128, 256, 32))
        self.assertEqual(hashlib.sha256(route_map['data']).hexdigest(),
                         'ee18565ca6c3a515954e2ad9b188b22a2a9b1678cdef688a5a8e107b6f4df629')
        compact = detile_bc4_thin1(
            route_map['data'], route_map['width'], route_map['height'], route_map['pitch'],
            tile_mode=route_map['tile_mode'], swizzle=route_map['swizzle'],
            depth=route_map['depth'])
        self.assertEqual(hashlib.sha256(compact).hexdigest(),
                         'b91f8d978978b099630b23c97cf2ce3ad47dabbe08cae6b6759bd605961d11a6')
        rgba = decode_bc4_unorm(compact, route_map['width'], route_map['height'])
        self.assertEqual(len(rgba), 128 * 256 * 4)
        self.assertEqual(rgba[0::4], rgba[1::4])
        self.assertEqual(rgba[1::4], rgba[2::4])
        self.assertEqual(set(rgba[3::4]), {255})

    def test_local_w1_other_bc4_sampler_slots_have_stable_thin1_fingerprints(self):
        root = Path(__file__).resolve().parents[1]
        source = root / 'NSMBU Modding Project/content/Common/course_select/CS_W1.szs'
        if not source.is_file():
            self.skipTest('User-provided local W1 dump unavailable')
        model = Archive(source.read_bytes()).read('CS_W1.bfres')
        cases = (
            ('_b0', 'mtCourseRing', 'Bake_CS_W1_World_g00_b00_f00', 1024, 512,
             '1ab33ecf1cdfb836c676f1bfcb8cac6b4ba09cd0171f6772d23e2cfb7539d60b',
             'a99d1acaf77fb1a60cfb2b1a6940f672d8fa9f44086262959d70f8181e90da4d'),
            ('_s0', 'mtDokanBlue', 'Dokan_spm', 128, 128,
             '6b614457bb4b92c285a9cad5c8f18ffa00edcaa1f7737f8d511aeb9993ac29f4',
             '7f5180ff330f8a10450ec5c4972e0721cbacdd5a13c94ca7c8ad0046a6b1d87b'),
            ('_x2', 'mtCourseRing', 'CourseRing_spm', 32, 32,
             '03218ed70fcf64f3ef6dc27de2131cd1d803c413893b74c53c1bbd2638d98c0d',
             'a500115ecc1e4cbcdd5b7b53171c5675d42694c672ccc6507f18a83b63693036'),
        )
        for slot, material, name, width, height, raw_hash, compact_hash in cases:
            with self.subTest(slot=slot):
                texture = extract_sampler_diagnostic_texture(model, 'CS_W1_World', material, slot)
                self.assertEqual((texture['name'], texture['format'], texture['width'], texture['height']),
                                 (name, 0x34, width, height))
                self.assertEqual(hashlib.sha256(texture['data']).hexdigest(), raw_hash)
                compact = detile_bc4_thin1(
                    texture['data'], width, height, texture['pitch'], tile_mode=texture['tile_mode'],
                    swizzle=texture['swizzle'], depth=texture['depth'])
                self.assertEqual(hashlib.sha256(compact).hexdigest(), compact_hash)
                rgba = decode_bc4_unorm(compact, width, height)
                self.assertEqual(len(rgba), width * height * 4)
                self.assertEqual(rgba[0::4], rgba[1::4])
                self.assertEqual(rgba[1::4], rgba[2::4])

    def test_local_w1_bc4_catalog_attaches_only_verified_sampler_slot_pairs(self):
        from worldstudio.mesh import extract_rigid_model

        root = Path(__file__).resolve().parents[1]
        source = root / 'NSMBU Modding Project/content/Common/course_select/CS_W1.szs'
        if not source.is_file():
            self.skipTest('User-provided local W1 dump unavailable')
        model = Archive(source.read_bytes()).read('CS_W1.bfres')
        shapes = extract_rigid_model(model)
        expected = {'_o1': (1, 7), '_b0': (1, 36), '_s0': (13, 35), '_x2': (1, 1)}
        for slot, (texture_count, shape_count) in expected.items():
            with self.subTest(slot=slot):
                textures, _ = attach_sampler_diagnostic_textures(model, shapes, sampler_slot=slot)
                mapped = [shape for shape in shapes if slot in shape.get('bc4Samplers', {})]
                self.assertEqual(len(textures), texture_count)
                self.assertEqual(len(mapped), shape_count)
                self.assertTrue(all(payload['format'] == 0x34 and payload['samplerSlot'] == slot
                                    for payload in textures.values()))


if __name__ == '__main__':
    unittest.main()
