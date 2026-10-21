"""Synthetic offset tables plus optional read-only local-dump round trips."""
from dataclasses import replace
from pathlib import Path
import struct
import unittest

from worldstudio.camera import OffsetRecord, OffsetTable


def mario_fixture():
    return b"".join(struct.pack("<5s3fI", b"W101\x7f", i + 0.5, -0.0, -i,
                                0x89abcdef) for i in range(256))


def look_fixture():
    return b"".join(struct.pack("<3f", i, -i, i + 0.25) for i in range(62))


class CameraOffsetTests(unittest.TestCase):
    def test_little_endian_mario_and_unknown_fields_roundtrip(self):
        data = mario_fixture()
        table = OffsetTable.parse(data, "mario")
        self.assertEqual(table.record(0, 0).vector, (0.5, -0.0, 0.0))
        self.assertEqual(table.record(1, 0).vector[0], 128.5)
        self.assertEqual(table.record(0, 0).unknown_u32, 0x89abcdef)
        self.assertEqual(table.record(0, 0).name_raw, b"W101\x7f")
        self.assertEqual(table.build(), data)  # Includes -0.0 bits and raw name byte.

    def test_edit_changes_only_selected_twelve_vector_bytes(self):
        for kind, fixture, stride, start in (("mario", mario_fixture, 21, 5),
                                              ("look", look_fixture, 12, 0)):
            with self.subTest(kind=kind):
                data = fixture()
                table = OffsetTable.parse(data, kind)
                at = (table.per_bank + 3) * stride + start
                edited = table.with_vector(1, 3, (101, 202, 303)).build()
                self.assertEqual(edited[:at], data[:at])
                self.assertEqual(edited[at + 12:], data[at + 12:])
                self.assertEqual(struct.unpack_from("<3f", edited, at), (101, 202, 303))
                self.assertEqual(table.build(), data)

    def test_look_has_two_banks_of_thirty_one_vectors(self):
        data = look_fixture()
        table = OffsetTable.parse(data, "look")
        self.assertEqual(table.record(1, 0).vector, (31, -31, 31.25))
        self.assertIsNone(table.record(0, 0).unknown_u32)
        self.assertEqual(table.build(), data)

    def test_strict_kind_size_and_index_guards(self):
        for kind, fixture in (("mario", mario_fixture), ("look", look_fixture)):
            data = fixture()
            for invalid in (data[:-1], data + b"\0"):
                with self.subTest(kind=kind, length=len(invalid)), self.assertRaises(ValueError):
                    OffsetTable.parse(invalid, kind)
            table = OffsetTable.parse(data, kind)
            for bank, index in ((-1, 0), (2, 0), (0, -1), (0, table.per_bank), (0, 1.5)):
                with self.subTest(bank=bank, index=index), self.assertRaises(ValueError):
                    table.with_vector(bank, index, (1, 2, 3))
        with self.assertRaises(ValueError):
            OffsetTable.parse(b"", "unknown")

    def test_nonfinite_and_overflow_vectors_refused(self):
        table = OffsetTable.parse(look_fixture(), "look")
        for vector in ((float("nan"), 0, 0), (float("inf"), 0, 0),
                       (1e100, 0, 0), (1, 2)):
            with self.subTest(vector=vector), self.assertRaises(ValueError):
                table.with_vector(0, 0, vector)
        malformed = bytearray(look_fixture())
        struct.pack_into("<f", malformed, 0, float("nan"))
        with self.assertRaises(ValueError):
            OffsetTable.parse(malformed, "look")

    def test_build_refuses_corrupted_names_unknown_field_or_record_counts(self):
        table = OffsetTable.parse(mario_fixture(), "mario")
        for first in (replace(table.records[0], name_raw=b"shorter?"),
                      replace(table.records[0], unknown_u32=-1),
                      replace(table.records[0], unknown_u32=0x100000000)):
            with self.subTest(first=first), self.assertRaises(ValueError):
                replace(table, records=(first,) + table.records[1:]).build()
        with self.assertRaises(ValueError):
            replace(table, records=table.records[:-1]).build()
        look = OffsetTable.parse(look_fixture(), "look")
        with self.assertRaises(ValueError):
            replace(look, records=(OffsetRecord((1, 2, 3), b"hello", 0),) + look.records[1:]).build()

    def test_actual_local_assets_read_only_roundtrip_if_available(self):
        root = Path(__file__).resolve().parents[1] / "NSMBU Modding Project/content/Common/course_select"
        if not (root / "MarioOffsetDataW1.bin").is_file():
            self.skipTest("User-provided game resources are optional and never distributed")
        for world in range(1, 10):
            for prefix, kind in (("Mario", "mario"), ("Look", "look")):
                path = root / f"{prefix}OffsetDataW{world}.bin"
                with self.subTest(path=path.name):
                    before = path.read_bytes()
                    table = OffsetTable.parse(before, kind)
                    self.assertEqual(table.build(), before)
                    self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
