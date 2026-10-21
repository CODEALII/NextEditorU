from pathlib import Path
import hashlib
import unittest

from worldstudio.archive import Archive
from worldstudio.bfres_texture import extract_bc1_base_texture
from worldstudio.texture_preview import decode_bc1, detile_bc1_thin1


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


if __name__ == '__main__':
    unittest.main()
