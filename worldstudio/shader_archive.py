"""Read-only metadata reader for Nintendo Wii U SHARCFB version 8 archives.

Compiled GX2 instruction payloads are only range-checked. The reader exposes
archive/program names, variation declarations, and named shader interfaces;
it does not decompile shaders or infer material behavior from symbol names.
"""
from math import prod
import struct


MAX_ARCHIVE_SIZE = 256 * 1024 * 1024
MAX_SHADER_BINARIES = 100_000
MAX_SHADER_PROGRAMS = 4096
MAX_SECTION_RECORDS = 65_535
MAX_VARIANT_COMBINATIONS = 1_000_000


class _Reader:
    def __init__(self, data, endian):
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise ValueError("SHARCFB input must be bytes")
        self.data = memoryview(data)
        self.endian = endian
        if len(self.data) > MAX_ARCHIVE_SIZE:
            raise ValueError("SHARCFB exceeds the archive size limit")

    def bounds(self, offset, size, limit=None):
        limit = len(self.data) if limit is None else min(limit, len(self.data))
        if offset < 0 or size < 0 or offset > limit or size > limit - offset:
            raise ValueError("SHARCFB record exceeds its containing section")

    def u32(self, offset, limit=None):
        self.bounds(offset, 4, limit)
        return struct.unpack_from(self.endian + "I", self.data, offset)[0]

    def text(self, offset, length, limit):
        self.bounds(offset, length, limit)
        raw = bytes(self.data[offset:offset + length])
        if length < 1 or raw[-1] != 0 or b"\0" in raw[:-1]:
            raise ValueError("SHARCFB string has an invalid terminator")
        try:
            return raw[:-1].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("SHARCFB string is not valid UTF-8") from exc


def _section(reader, offset, limit, *, max_records=MAX_SECTION_RECORDS):
    size = reader.u32(offset, limit)
    count = reader.u32(offset + 4, limit)
    if size < 8 or offset + size > limit:
        raise ValueError("Invalid SHARCFB section size")
    if count > max_records:
        raise ValueError("SHARCFB section record count exceeds limit")
    return size, count, offset + size


def _parse_variations(reader, offset, program_end):
    size, count, end = _section(reader, offset, program_end)
    cursor = offset + 8
    macros = []
    for _ in range(count):
        reader.bounds(cursor, 16, end)
        record_size, name_length, value_count, symbol_length = struct.unpack_from(
            reader.endian + "4I", reader.data, cursor)
        record_end = cursor + record_size
        if record_size < 16 or record_end > end or value_count > MAX_SECTION_RECORDS:
            raise ValueError("Invalid SHARCFB variation macro record")
        name = reader.text(cursor + 16, name_length, record_end)
        value_cursor = cursor + 16 + name_length
        values = []
        for _ in range(value_count):
            reader.bounds(value_cursor, 1, record_end)
            terminator = bytes(reader.data[value_cursor:record_end]).find(b"\0")
            if terminator < 0:
                raise ValueError("Unterminated SHARCFB variation value")
            values.append(reader.text(value_cursor, terminator + 1, record_end))
            value_cursor += terminator + 1
        symbol = reader.text(value_cursor, symbol_length, record_end)
        value_cursor += symbol_length
        if value_cursor != record_end:
            raise ValueError("SHARCFB variation macro size mismatch")
        macros.append({"name": name, "symbol": symbol, "values": values})
        cursor = record_end
    if cursor != end:
        raise ValueError("SHARCFB variation section size mismatch")
    return {"macros": macros, "size": size}


def _parse_symbols(reader, offset, program_end):
    size, count, end = _section(reader, offset, program_end)
    cursor = offset + 8
    symbols = []
    for _ in range(count):
        reader.bounds(cursor, 24, end)
        (record_size, variable_size, variable_name_length,
         symbol_name_length, default_size, variation_count) = struct.unpack_from(
            reader.endian + "6I", reader.data, cursor)
        record_end = cursor + record_size
        if record_size < 24 or record_end > end or variation_count > MAX_SECTION_RECORDS:
            raise ValueError("Invalid SHARCFB shader-symbol record")
        variable_name = reader.text(cursor + 24, variable_name_length, record_end)
        symbol_offset = cursor + 24 + variable_name_length
        symbol_name = reader.text(symbol_offset, symbol_name_length, record_end)
        payload_offset = symbol_offset + symbol_name_length
        reader.bounds(payload_offset, default_size + variation_count, record_end)
        usage = bytes(reader.data[payload_offset + default_size:record_end])
        if len(usage) != variation_count or any(value not in (0, 1) for value in usage):
            raise ValueError("Invalid SHARCFB shader-symbol variation flags")
        if payload_offset + default_size + variation_count != record_end:
            raise ValueError("SHARCFB shader-symbol size mismatch")
        symbols.append({
            "name": variable_name,
            "symbol": symbol_name,
            "value_size": variable_size,
            "default_size": default_size,
            "variation_usage_count": sum(usage),
            "variation_usage_total": len(usage),
        })
        cursor = record_end
    if cursor != end:
        raise ValueError("SHARCFB shader-symbol section size mismatch")
    return {"symbols": symbols, "size": size}


def parse_sharcfb(data):
    """Parse bounded SHARCFB v8 metadata without decoding GX2 instructions."""
    if not isinstance(data, (bytes, bytearray, memoryview)) or len(data) < 32:
        raise ValueError("Truncated SHARCFB header")
    magic = bytes(data[:4])
    if magic == b"BAHS":
        endian, expected_endian = "<", 1
    elif magic == b"SHAB":
        endian, expected_endian = ">", 0
    else:
        raise ValueError("Not a supported SHARCFB archive")
    reader = _Reader(data, endian)
    version = reader.u32(4)
    declared_size = reader.u32(8)
    endian_flag = reader.u32(12)
    reserved = reader.u32(16)
    filename_length = reader.u32(20)
    if version != 8:
        raise ValueError(f"Unsupported SHARCFB version {version}")
    if declared_size != len(reader.data):
        raise ValueError("SHARCFB declared size mismatch")
    if endian_flag != expected_endian or reserved != 0:
        raise ValueError("Unsupported SHARCFB header flags")
    if not 1 <= filename_length <= 4096:
        raise ValueError("Invalid SHARCFB archive-name length")
    try:
        archive_name = reader.text(24, filename_length, len(reader.data))
    except ValueError as exc:
        raise ValueError(f"Invalid SHARCFB archive name: {exc}") from exc
    binary_offset = 24 + filename_length

    binary_size, binary_count, binary_end = _section(
        reader, binary_offset, len(reader.data), max_records=MAX_SHADER_BINARIES)
    binaries = []
    cursor = binary_offset + 8
    for _ in range(binary_count):
        reader.bounds(cursor, 16, binary_end)
        record_size, shader_type, data_offset, data_size = struct.unpack_from(
            endian + "4I", reader.data, cursor)
        record_end = cursor + record_size
        if record_size < 16 or record_end > binary_end:
            raise ValueError("Invalid SHARCFB shader-binary record")
        if shader_type not in (0, 1, 2):
            raise ValueError("Unsupported SHARCFB shader stage")
        if data_offset > record_size - 16 or data_size > record_size - 16 - data_offset:
            raise ValueError("SHARCFB shader payload exceeds its record")
        binaries.append({"type": shader_type, "data_size": data_size})
        cursor = record_end
    if cursor != binary_end:
        raise ValueError("SHARCFB shader-binary section size mismatch")

    program_size, program_count, archive_end = _section(
        reader, binary_end, len(reader.data), max_records=MAX_SHADER_PROGRAMS)
    if archive_end != len(reader.data):
        raise ValueError("Unexpected data after SHARCFB program section")
    programs = []
    cursor = binary_end + 8
    for _ in range(program_count):
        reader.bounds(cursor, 16, archive_end)
        record_size, name_length, shader_flags, base_index = struct.unpack_from(
            endian + "4I", reader.data, cursor)
        record_end = cursor + record_size
        if record_size < 16 or record_end > archive_end:
            raise ValueError("Invalid SHARCFB shader-program record")
        if shader_flags & ~7 or shader_flags & 3 != 3:
            raise ValueError("SHARCFB program must declare vertex and pixel shaders")
        name = reader.text(cursor + 16, name_length, record_end)
        section_cursor = cursor + 16 + name_length
        possible = _parse_variations(reader, section_cursor, record_end)
        possible_end = section_cursor + possible["size"]
        defaults = _parse_variations(reader, possible_end, record_end)
        section_cursor = possible_end + defaults["size"]
        uniforms = _parse_symbols(reader, section_cursor, record_end)
        section_cursor += uniforms["size"]
        uniform_blocks = _parse_symbols(reader, section_cursor, record_end)
        section_cursor += uniform_blocks["size"]
        samplers = _parse_symbols(reader, section_cursor, record_end)
        section_cursor += samplers["size"]
        attributes = _parse_symbols(reader, section_cursor, record_end)
        section_cursor += attributes["size"]
        if section_cursor != record_end:
            raise ValueError("SHARCFB shader-program section size mismatch")

        variation_count = prod(len(macro["values"]) for macro in possible["macros"])
        if variation_count > MAX_VARIANT_COMBINATIONS:
            raise ValueError("SHARCFB program variation count exceeds limit")
        stage_types = [stage for stage in (0, 1, 2) if shader_flags & (1 << stage)]
        binary_end_index = base_index + variation_count * len(stage_types)
        if binary_end_index > binary_count:
            raise ValueError("SHARCFB program references missing shader binaries")
        for variant in range(variation_count):
            start = base_index + variant * len(stage_types)
            if [item["type"] for item in binaries[start:start + len(stage_types)]] != stage_types:
                raise ValueError("SHARCFB program shader-stage order is inconsistent")

        programs.append({
            "name": name,
            "shader_flags": shader_flags,
            "base_index": base_index,
            "variation_count": variation_count,
            "variation_macros": possible["macros"],
            "default_variations": [
                {"name": macro["name"], "symbol": macro["symbol"],
                 "value": macro["values"][0] if macro["values"] else None}
                for macro in defaults["macros"]
            ],
            "uniforms": uniforms["symbols"],
            "uniform_blocks": uniform_blocks["symbols"],
            "samplers": samplers["symbols"],
            "attributes": attributes["symbols"],
        })
        cursor = record_end
    if cursor != archive_end:
        raise ValueError("SHARCFB shader-program section size mismatch")
    names = [program["name"] for program in programs]
    if len(set(names)) != len(names):
        raise ValueError("Duplicate SHARCFB shader-program name")
    return {
        "archive_name": archive_name,
        "version": version,
        "endian": "little" if endian == "<" else "big",
        "shader_binary_count": binary_count,
        "shader_program_count": program_count,
        "programs": programs,
        "metadata_only": True,
    }
