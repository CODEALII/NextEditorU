"""Read-only Yaz0/SARC inventory for a user-provided NSMBU dump.

Does not extract or redistribute payloads. Standard library only.
"""
from pathlib import Path
import argparse
import hashlib
import json
import struct


def yaz0(data: bytes) -> bytes:
    if data[:4] != b"Yaz0":
        return data
    size = struct.unpack_from(">I", data, 4)[0]
    out = bytearray()
    pos = 16
    while len(out) < size:
        code = data[pos]
        pos += 1
        for shift in range(7, -1, -1):
            if len(out) == size:
                break
            if code & (1 << shift):
                out.append(data[pos])
                pos += 1
            else:
                first, second = data[pos:pos + 2]
                pos += 2
                distance = ((first & 15) << 8 | second) + 1
                count = first >> 4
                if count:
                    count += 2
                else:
                    count = data[pos] + 18
                    pos += 1
                for _ in range(count):
                    if len(out) >= size:
                        raise ValueError("Yaz0 backreference exceeds declared output")
                    out.append(out[-distance])
    return bytes(out)


def sarc(data: bytes):
    if data[:4] != b"SARC":
        raise ValueError("Not SARC")
    endian = ">" if data[6:8] == b"\xfe\xff" else "<"
    header_size = struct.unpack_from(endian + "H", data, 4)[0]
    data_offset = struct.unpack_from(endian + "I", data, 12)[0]
    if data[header_size:header_size + 4] != b"SFAT":
        raise ValueError("Missing SFAT")
    sfat_size, count = struct.unpack_from(endian + "HH", data, header_size + 4)
    nodes = header_size + sfat_size
    sfnt = nodes + count * 16
    if data[sfnt:sfnt + 4] != b"SFNT":
        raise ValueError("Missing SFNT")
    names = sfnt + struct.unpack_from(endian + "H", data, sfnt + 4)[0]
    for i in range(count):
        name_hash, attr, start, end = struct.unpack_from(endian + "4I", data, nodes + i * 16)
        name_start = names + (attr & 0xFFFFFF) * 4
        name = data[name_start:data.index(0, name_start)].decode("utf-8") if attr >> 24 else f"hash_{name_hash:08x}"
        yield name, data[data_offset + start:data_offset + end]


def inspect(path: Path, strings=False):
    original = path.read_bytes()
    unpacked = yaz0(original)
    result = {"path": str(path), "size": len(original), "sha256": hashlib.sha256(original).hexdigest(), "unpacked_size": len(unpacked)}
    if unpacked[:4] == b"SARC":
        result["entries"] = [{"name": name, "size": len(payload), "magic_hex": payload[:16].hex()} for name, payload in sarc(unpacked)]
        if strings:
            import re
            result["strings"] = {name: [s.decode("ascii") for s in re.findall(rb"[ -~]{5,}", payload)][:250] for name, payload in sarc(unpacked)}
    return result


def inspect_rpx(path: Path):
    """List relevant strings in ELF32 big-endian RPX sections in memory."""
    import re
    import zlib
    data = path.read_bytes()
    if data[:6] != b"\x7fELF\x01\x02":
        raise ValueError("Expected ELF32 big-endian RPX")
    table = struct.unpack_from(">I", data, 32)[0]
    stride, count = struct.unpack_from(">HH", data, 46)
    result = []
    for index in range(count):
        _, kind, flags, address, offset, size, *_ = struct.unpack_from(">10I", data, table + index * stride)
        if not size or kind == 8:  # SHT_NOBITS has no file payload.
            continue
        section = data[offset:offset + size]
        if flags & 0x08000000:  # Wii U RPX compressed section.
            expected = struct.unpack_from(">I", section)[0]
            section = zlib.decompress(section[4:])
            if len(section) != expected:
                raise ValueError("RPX section length mismatch")
        for match in re.finditer(rb"[ -~]{6,}", section):
            if re.search(rb"course_select|point.*csv|route.*csv|LookOffset|MarioOffset", match.group()):
                result.append({"section": index, "section_offset": match.start(),
                               "elf_virtual_address": hex(address + match.start()),
                               "string": match.group().decode("ascii")})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--strings", action="store_true")
    parser.add_argument("--rpx", action="store_true", help="Inspect RPX path/CSV strings")
    args = parser.parse_args()
    print(json.dumps([inspect_rpx(p) if args.rpx else inspect(p, args.strings) for p in args.paths], indent=2))
