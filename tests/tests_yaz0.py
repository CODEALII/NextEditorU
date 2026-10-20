"""Encoder interoperability checks against the existing independent decoder."""
import random
import struct
import unittest

from worldstudio.archive import decompress
from worldstudio.yaz0_encode import encode


class Yaz0EncodeTests(unittest.TestCase):
    def check_roundtrip(self, data):
        packed = encode(data)
        self.assertEqual(packed[:4], b"Yaz0")
        self.assertEqual(struct.unpack_from(">I", packed, 4)[0], len(data))
        self.assertEqual(decompress(packed), data)
        return packed

    def test_empty_and_short_inputs(self):
        for size in range(20):
            with self.subTest(size=size):
                self.check_roundtrip(bytes(range(size)))

    def test_incompressible_and_deterministic(self):
        data = random.Random(58).randbytes(20000)
        packed = self.check_roundtrip(data)
        self.assertEqual(encode(data), packed)
        self.assertLessEqual(len(packed), len(data) + (len(data) + 7) // 8 + 16)

    def test_overlapping_and_extended_references(self):
        for data in [b"x" * 100000, b"abc" * 5000, bytes(range(256)) * 50]:
            with self.subTest(length=len(data)):
                self.assertLess(len(self.check_roundtrip(data)), len(data) // 20)

    def test_window_wrap_and_distant_repeats(self):
        rng = random.Random(118)
        block = rng.randbytes(4096)
        self.check_roundtrip(block + block + rng.randbytes(5000) + block)
        self.check_roundtrip(rng.randbytes(100000))

    def test_match_length_boundaries(self):
        for size in (3, 17, 18, 19, 272, 273, 274, 4095, 4096, 4097):
            with self.subTest(size=size):
                self.check_roundtrip(b"ab" * size + b"Z" + b"ab" * size)


if __name__ == "__main__":
    unittest.main()
