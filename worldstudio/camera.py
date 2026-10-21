"""Verified little-endian course-select offset records.

These are serialized numeric fields, not a claim about final camera behavior.
The meanings of the two banks and Mario's trailing u32 remain unverified.
See docs/CAMERA_FINDINGS.md for executable evidence and exact record bounds.
"""
from dataclasses import dataclass, replace
import math
import struct


LAYOUTS = {"mario": (128, struct.Struct("<5s3fI")),
           "look": (31, struct.Struct("<3f"))}


def _vector(value):
    if len(value) != 3:
        raise ValueError("Offset vector must contain exactly three components")
    result = tuple(float(v) for v in value)
    if not all(math.isfinite(v) for v in result):
        raise ValueError("Offset components must be finite")
    try:
        encoded = struct.pack("<3f", *result)
    except (OverflowError, struct.error) as exc:
        raise ValueError("Offset components must fit float32") from exc
    if not all(math.isfinite(v) for v in struct.unpack("<3f", encoded)):
        raise ValueError("Offset components must fit finite float32")
    return result


@dataclass(frozen=True)
class OffsetRecord:
    vector: tuple[float, float, float]
    name_raw: bytes | None = None
    unknown_u32: int | None = None


@dataclass(frozen=True)
class OffsetTable:
    kind: str
    records: tuple[OffsetRecord, ...]

    @classmethod
    def parse(cls, data: bytes, kind: str):
        if kind not in LAYOUTS:
            raise ValueError("Offset kind must be mario or look")
        per_bank, layout = LAYOUTS[kind]
        if len(data) != 2 * per_bank * layout.size:
            raise ValueError(f"Expected {2 * per_bank * layout.size} bytes for {kind} offsets")
        records = []
        for values in layout.iter_unpack(data):
            if kind == "mario":
                name, x, y, z, unknown = values
                records.append(OffsetRecord(_vector((x, y, z)), name, unknown))
            else:
                records.append(OffsetRecord(_vector(values)))
        return cls(kind, tuple(records))

    @property
    def per_bank(self):
        if self.kind not in LAYOUTS:
            raise ValueError("Offset kind must be mario or look")
        return LAYOUTS[self.kind][0]

    def record(self, bank: int, index: int):
        if (not isinstance(bank, int) or not isinstance(index, int)
                or not 0 <= bank < 2 or not 0 <= index < self.per_bank):
            raise ValueError("Offset bank or record index out of bounds")
        return self.records[bank * self.per_bank + index]

    def with_vector(self, bank: int, index: int, vector):
        original = self.record(bank, index)
        records = list(self.records)
        records[bank * self.per_bank + index] = replace(original, vector=_vector(vector))
        return replace(self, records=tuple(records))

    def build(self):
        per_bank = self.per_bank
        layout = LAYOUTS[self.kind][1]
        if len(self.records) != 2 * per_bank:
            raise ValueError("Unexpected offset record count")
        parts = []
        for record in self.records:
            vector = _vector(record.vector)
            if self.kind == "mario":
                if not isinstance(record.name_raw, bytes) or len(record.name_raw) != 5:
                    raise ValueError("Mario offset name must preserve exactly five raw bytes")
                if not isinstance(record.unknown_u32, int) or not 0 <= record.unknown_u32 <= 0xffffffff:
                    raise ValueError("Unknown Mario field must fit unsigned 32 bits")
                parts.append(layout.pack(record.name_raw, *vector, record.unknown_u32))
            else:
                if record.name_raw is not None or record.unknown_u32 is not None:
                    raise ValueError("Look offset records have only three float32 fields")
                parts.append(layout.pack(*vector))
        return b"".join(parts)
