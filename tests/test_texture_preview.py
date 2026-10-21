import struct
import unittest

from worldstudio.texture_preview import (
    decode_bc1,
    decode_bc3,
    detile_bc1_thin1,
    detile_bc3_thin1,
)


def solid_block(rgb565):
    other = 0x001F if rgb565 != 0x001F else 0xF800
    first, second = (rgb565, other) if rgb565 > other else (other, rgb565)
    return struct.pack("<HHI", first, second, 0)


def reference_offset(x, y, pitch, swizzle):
    """Test-only scalar transcription of the pinned BfresLibrary address path."""
    index = ((x & 1) | ((y & 1) << 1) | (((x & 2) >> 1) << 2) |
             (((x & 4) >> 2) << 3) | (((y & 2) >> 1) << 4) |
             (((y & 4) >> 2) << 5))
    pipe = ((y >> 3) ^ (x >> 3)) & 1
    bank = (((y >> 5) ^ (x >> 3)) & 1) | (2 * (((y >> 4) ^ (x >> 4)) & 1))
    bank_pipe = (pipe + 2 * bank) ^ (((swizzle >> 8) & 1) + 2 * ((swizzle >> 9) & 3))
    bank_pipe %= 8
    pipe, bank = bank_pipe % 2, bank_pipe // 2
    macro_offset = (x // 32 + (pitch // 32) * (y // 16)) * 4096
    total = index * 8 + macro_offset // 8
    return (bank << 9) | (pipe << 8) | (total & 255) | ((total & ~255) << 3)


def tiled_from_linear(linear, width, height, pitch, swizzle):
    """Build a synthetic physical surface from independent reference offsets."""
    blocks_w, blocks_h = (width + 3) // 4, (height + 3) // 4
    padded_h = ((blocks_h + 15) // 16) * 16
    tiled = bytearray(pitch * padded_h * 8)
    offsets = set()
    for y in range(blocks_h):
        for x in range(blocks_w):
            target = reference_offset(x, y, pitch, swizzle)
            if target in offsets:
                raise AssertionError(f"GX2 address collision at ({x}, {y})")
            offsets.add(target)
            source = (y * blocks_w + x) * 8
            tiled[target:target + 8] = linear[source:source + 8]
    return bytes(tiled)


def reference_bc3_offset(x, y, pitch, swizzle):
    """Test-only address transcription for BfresLibrary's 128-bpp branch."""
    index = ((y & 1) | ((x & 1) << 1) | (((x & 2) >> 1) << 2) |
             ((x & 4) >> 2) << 3 | ((y & 2) >> 1) << 4 |
             ((y & 4) >> 2) << 5)
    pipe = ((y >> 3) ^ (x >> 3)) & 1
    bank = (((y >> 5) ^ (x >> 3)) & 1) | (2 * (((y >> 4) ^ (x >> 4)) & 1))
    bank_pipe = (pipe + 2 * bank) ^ (((swizzle >> 8) & 1) + 2 * ((swizzle >> 9) & 3))
    bank_pipe %= 8
    pipe, bank = bank_pipe % 2, bank_pipe // 2
    macro_offset = (x // 32 + (pitch // 32) * (y // 16)) * 8192
    total = index * 16 + macro_offset // 8
    return (bank << 9) | (pipe << 8) | (total & 255) | ((total & ~255) << 3)


def tiled_bc3_from_linear(linear, width, height, pitch, swizzle):
    blocks_w, blocks_h = (width + 3) // 4, (height + 3) // 4
    padded_h = ((blocks_h + 15) // 16) * 16
    tiled = bytearray(pitch * padded_h * 16)
    offsets = set()
    for y in range(blocks_h):
        for x in range(blocks_w):
            target = reference_bc3_offset(x, y, pitch, swizzle)
            if target in offsets:
                raise AssertionError(f"GX2 BC3 address collision at ({x}, {y})")
            offsets.add(target)
            source = (y * blocks_w + x) * 16
            tiled[target:target + 16] = linear[source:source + 16]
    return bytes(tiled)


class Bc1DecodeTests(unittest.TestCase):
    def test_known_red_block_decodes_to_top_down_rgba(self):
        rgba = decode_bc1(solid_block(0xF800), 4, 4)
        self.assertEqual(len(rgba), 4 * 4 * 4)
        self.assertEqual(rgba, bytes((255, 0, 0, 255)) * 16)

    def test_three_color_mode_preserves_transparency(self):
        # Endpoint0 <= endpoint1 selects BC1's transparent four-color entry.
        transparent = struct.pack("<HHI", 0x001F, 0xF800, 0xFFFFFFFF)
        self.assertEqual(decode_bc1(transparent, 4, 4), bytes((0, 0, 0, 0)) * 16)

    def test_interpolation_and_non_multiple_of_four_crop(self):
        red = struct.pack("<HHI", 0xF800, 0x001F, 0xE4E4E4E4)
        green = struct.pack("<HHI", 0x07E0, 0x001F, 0)
        rgba = decode_bc1(red + green, 5, 3)
        self.assertEqual(len(rgba), 5 * 3 * 4)
        expected_row = bytes((255, 0, 0, 255, 0, 0, 255, 255,
                              170, 0, 85, 255, 85, 0, 170, 255,
                              0, 255, 0, 255))
        self.assertEqual(rgba[:20], expected_row)
        self.assertEqual(rgba[20:40], expected_row)
        self.assertEqual(rgba[40:60], expected_row)

    def test_rejects_wrong_size_and_invalid_dimensions(self):
        with self.assertRaisesRegex(ValueError, "exactly 8 bytes"):
            decode_bc1(b"\0" * 9, 4, 4)
        for width, height in ((0, 4), (4, -1), (True, 4)):
            with self.subTest(width=width, height=height), self.assertRaises(ValueError):
                decode_bc1(b"", width, height)


class Bc3DecodeTests(unittest.TestCase):
    def test_known_red_block_and_alpha_interpolation(self):
        colors = struct.pack("<HHI", 0xF800, 0x001F, 0)
        alpha_indices = sum(2 << (3 * i) for i in range(16))
        block = bytes((0, 255)) + alpha_indices.to_bytes(6, "little") + colors
        self.assertEqual(decode_bc3(block, 4, 4), bytes((255, 0, 0, 51)) * 16)

    def test_bc3_alpha_endpoints_and_partial_edge_crop(self):
        colors = struct.pack("<HHI", 0xF800, 0x001F, 0)
        opaque = bytes((255, 0)) + bytes(6) + colors
        transparent_indexes = sum(6 << (3 * i) for i in range(16))
        transparent = bytes((0, 255)) + transparent_indexes.to_bytes(6, "little") + colors
        rgba = decode_bc3(opaque + transparent, 5, 3)
        self.assertEqual(len(rgba), 5 * 3 * 4)
        self.assertEqual(rgba[:16], bytes((255, 0, 0, 255)) * 4)
        self.assertEqual(rgba[16:20], bytes((255, 0, 0, 0)))

    def test_rejects_wrong_block_count(self):
        with self.assertRaisesRegex(ValueError, "exactly 16 bytes"):
            decode_bc3(bytes(17), 4, 4)


class Bc1Thin1Tests(unittest.TestCase):
    def test_known_gx2_address_vectors(self):
        # Expected offsets are manually evaluated from the pinned C# branches:
        # 64-bpp microtile order, pipe/bank calculation, and 32x16 block macrotiles.
        from worldstudio.texture_preview import _bc1_thin1_block_offset

        vectors = [
            ((0, 0), 0), ((1, 0), 8), ((0, 1), 16), ((7, 7), 2296),
            ((8, 0), 768), ((0, 8), 256), ((16, 0), 1024),
            ((0, 16), 9216), ((32, 0), 4096), ((63, 63), 30968),
        ]
        for (x, y), expected in vectors:
            with self.subTest(x=x, y=y):
                self.assertEqual(_bc1_thin1_block_offset(x, y, 64, 0x20000), expected)
        self.assertEqual(_bc1_thin1_block_offset(0, 0, 64, 0x20100), 256)
        self.assertEqual(_bc1_thin1_block_offset(0, 0, 64, 0x20200), 512)

    def test_detile_roundtrip_across_macro_tiles_and_swizzle(self):
        width, height, pitch, swizzle = 129, 65, 64, 0xD0300
        blocks_w, blocks_h = (width + 3) // 4, (height + 3) // 4
        linear = bytes((i * 37 + 11) & 0xFF for i in range(blocks_w * blocks_h * 8))
        tiled = tiled_from_linear(linear, width, height, pitch, swizzle)
        self.assertEqual(detile_bc1_thin1(tiled, width, height, pitch, swizzle=swizzle), linear)

    def test_detiled_odd_edge_texture_decodes(self):
        width, height, pitch = 5, 3, 32
        blocks = solid_block(0xF800) + solid_block(0x07E0)
        tiled = tiled_from_linear(blocks, width, height, pitch, 0)
        compact = detile_bc1_thin1(tiled, width, height, pitch)
        self.assertEqual(decode_bc1(compact, width, height)[:20],
                         bytes((255, 0, 0, 255)) * 4 + bytes((0, 255, 0, 255)))

    def test_rejects_unsupported_layouts_pitch_swizzle_and_bounds(self):
        data = bytes(32 * 16 * 8)
        cases = [
            ({"tile_mode": 5}, "tileMode 4"),
            ({"dimension": 0}, "dimension 1"),
            ({"depth": 2}, "depth 1"),
            ({"aa": 1}, "Multisampled"),
            ({"swizzle": 1}, "Unsupported GX2 swizzle bits"),
            ({"pitch": 32, "width": 129}, "pitch 32 is smaller"),
            ({"pitch": 33}, "multiple of 32"),
        ]
        for kwargs, message in cases:
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, message):
                detile_bc1_thin1(data, kwargs.pop("width", 4), 4,
                                 kwargs.pop("pitch", 32), **kwargs)
        with self.assertRaisesRegex(ValueError, "exactly 4096 bytes"):
            detile_bc1_thin1(data[:-8], 4, 4, 32)
        with self.assertRaisesRegex(ValueError, "exactly 4096 bytes"):
            detile_bc1_thin1(data + b"extra", 4, 4, 32)


class Bc3Thin1Tests(unittest.TestCase):
    def test_known_128_bpp_gx2_address_vectors(self):
        from worldstudio.texture_preview import _bc3_thin1_block_offset

        vectors = [((0, 0), 0), ((1, 0), 32), ((0, 1), 16), ((1, 1), 48),
                   ((7, 7), 6384), ((8, 0), 768), ((0, 8), 256),
                   ((8, 8), 512), ((31, 15), 7920), ((0, 16), 9216),
                   ((31, 31), 15088), ((0, 32), 16896), ((31, 63), 30960)]
        for (x, y), expected in vectors:
            with self.subTest(x=x, y=y):
                self.assertEqual(_bc3_thin1_block_offset(x, y, 32, 0x10000), expected)

    def test_bc3_address_grid_is_unique_and_in_range(self):
        offsets = {reference_bc3_offset(x, y, 32, 0x10000)
                   for y in range(32) for x in range(32)}
        self.assertEqual(len(offsets), 32 * 32)
        self.assertEqual(min(offsets), 0)
        self.assertLess(max(offsets) + 16, 32 * 64 * 16)

    def test_detile_roundtrip_across_macro_tiles_and_swizzle(self):
        width, height, pitch, swizzle = 129, 65, 64, 0xD0300
        blocks_w, blocks_h = (width + 3) // 4, (height + 3) // 4
        linear = bytes((i * 19 + 7) & 0xFF for i in range(blocks_w * blocks_h * 16))
        tiled = tiled_bc3_from_linear(linear, width, height, pitch, swizzle)
        self.assertEqual(detile_bc3_thin1(tiled, width, height, pitch, swizzle=swizzle), linear)


if __name__ == "__main__":
    unittest.main()
