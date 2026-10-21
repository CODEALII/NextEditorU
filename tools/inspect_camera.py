"""Read-only offset-table inspection and optional RPX disassembly evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worldstudio.camera import OffsetTable


def inspect(path, kind=None):
    if kind is None:
        kind = "mario" if path.name.startswith("MarioOffsetData") else "look" if path.name.startswith("LookOffsetData") else None
    if kind is None:
        raise ValueError("Specify --kind mario or look for an unnamed input")
    data = path.read_bytes()
    table = OffsetTable.parse(data, kind)
    records = []
    for bank in range(2):
        for index in range(table.per_bank):
            record = table.record(bank, index)
            # Omit zero/default records only from display, never from parsing.
            if (any(record.vector) or record.unknown_u32
                    or record.name_raw not in (None, b"W000\0")):
                records.append({"bank": bank, "index": index, "vector": record.vector,
                                "name_raw_hex": record.name_raw.hex() if record.name_raw else None,
                                "unknown_u32": record.unknown_u32})
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "kind": kind, "banks": 2,
            "records_per_bank": table.per_bank,
            "byte_identical_roundtrip": table.build() == data, "nondefault_records": records}


def rpx_sections(path):
    data = path.read_bytes()
    if data[:6] != b"\x7fELF\x01\x02":
        raise ValueError("Expected ELF32 big-endian RPX")
    table = struct.unpack_from(">I", data, 32)[0]
    stride, count = struct.unpack_from(">HH", data, 46)
    for index in range(count):
        _, kind, flags, va, offset, size, *_ = struct.unpack_from(">10I", data, table + index * stride)
        if kind == 8 or not size:
            continue
        payload = data[offset:offset + size]
        if flags & 0x08000000:
            expected = struct.unpack_from(">I", payload)[0]
            payload = zlib.decompress(payload[4:])
            if len(payload) != expected:
                raise ValueError("RPX section length mismatch")
        yield index, flags, va, payload


def disassemble(path, start, end):
    if start < 0 or end <= start or end - start > 0x10000 or start % 4 or end % 4:
        raise ValueError("Use an aligned increasing range of at most 64 KiB")
    from capstone import Cs, CS_ARCH_PPC, CS_MODE_32, CS_MODE_BIG_ENDIAN
    for index, flags, va, payload in rpx_sections(path):
        if flags & 4 and va <= start < end <= va + len(payload):
            print(f"RPX SHA256 {hashlib.sha256(path.read_bytes()).hexdigest()}, section {index}")
            print("Addresses are specific ELF virtual addresses. Names/semantics are not assigned.")
            print("Capstone may mislabel Wii U paired-single instructions as VMX; inspect raw words.")
            decoder = Cs(CS_ARCH_PPC, CS_MODE_32 | CS_MODE_BIG_ENDIAN)
            for ins in decoder.disasm(payload[start-va:end-va], start):
                print(f"{ins.address:08x} {ins.bytes.hex()} {ins.mnemonic:10} {ins.op_str}")
            return
    raise ValueError("Range is not contained in an executable RPX section")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--kind", choices=("mario", "look"))
    parser.add_argument("--rpx", type=Path)
    parser.add_argument("--range", dest="code_range", help="ELF address range, e.g. 0x029ce124:0x029ce1f4")
    parser.add_argument("--capstone-path", type=Path, help="Optional isolated capstone installation directory")
    args = parser.parse_args()
    if args.rpx:
        if not args.code_range:
            parser.error("--rpx requires --range START:END")
        if args.capstone_path:
            sys.path.insert(0, str(args.capstone_path.resolve()))
        start, end = (int(item, 0) for item in args.code_range.split(":"))
        disassemble(args.rpx, start, end)
    else:
        if not args.paths:
            parser.error("Supply offset files or --rpx")
        print(json.dumps([inspect(p, args.kind) for p in args.paths], indent=2))
