import struct
import unittest
from pathlib import Path

from worldstudio.archive import Archive
from worldstudio.shader_archive import parse_sharcfb


def _u32(value, endian):
    return struct.pack(endian + 'I', value)


def _section(records, endian):
    return _u32(8 + sum(map(len, records)), endian) + _u32(len(records), endian) + b''.join(records)


def _macro(name, values, symbol, endian):
    name_bytes = name.encode() + b'\0'
    symbol_bytes = symbol.encode() + b'\0'
    values_bytes = b''.join(value.encode() + b'\0' for value in values)
    size = 16 + len(name_bytes) + len(values_bytes) + len(symbol_bytes)
    return struct.pack(endian + '4I', size, len(name_bytes), len(values), len(symbol_bytes)) + name_bytes + values_bytes + symbol_bytes


def _symbol(name, symbol, endian, *, default=b'', use=(1, 1), value_size=0xffffffff):
    name_bytes = name.encode() + b'\0'
    symbol_bytes = symbol.encode() + b'\0'
    size = 24 + len(name_bytes) + len(symbol_bytes) + len(default) + len(use)
    record = struct.pack(endian + '6I', size, value_size, len(name_bytes),
                         len(symbol_bytes), len(default), len(use))
    return record + name_bytes + symbol_bytes + default + bytes(use)


def _fixture(endian='<'):
    magic, endian_flag = (b'BAHS', 1) if endian == '<' else (b'SHAB', 0)
    binaries = []
    for stage in (0, 1, 0, 1):
        binaries.append(struct.pack(endian + '4I', 17, stage, 0, 1) + b'X')
    binary_section = _section(binaries, endian)

    possible = _section([_macro('MODE', ['0', '1'], 'var_mode', endian)], endian)
    defaults = _section([_macro('MODE', ['0'], 'var_mode', endian)], endian)
    uniforms = _section([
        _symbol('texmtx1', 'u_texmtx1', endian, default=b'\0\0\x80\x3f')
    ], endian)
    uniform_blocks = _section([], endian)
    samplers = _section([_symbol('cTexMap0', '_a0', endian)], endian)
    attributes = _section([_symbol('aTexCoord0', '_u0', endian)], endian)
    name = b'fixture_shader\0'
    program_tail = possible + defaults + uniforms + uniform_blocks + samplers + attributes
    program_size = 16 + len(name) + len(program_tail)
    program = struct.pack(endian + '4I', program_size, len(name), 3, 0) + name + program_tail
    program_section = _section([program], endian)

    archive_name = b'fixture\0'
    header = (magic + _u32(8, endian) + bytes(4) + _u32(endian_flag, endian) +
              _u32(0, endian) + _u32(len(archive_name), endian) + archive_name)
    result = bytearray(header + binary_section + program_section)
    result[8:12] = _u32(len(result), endian)
    return bytes(result)


class ShaderArchiveTests(unittest.TestCase):
    def test_reads_little_endian_shader_interfaces_and_variations(self):
        result = parse_sharcfb(_fixture())
        self.assertEqual((result['archive_name'], result['version'], result['endian']),
                         ('fixture', 8, 'little'))
        self.assertEqual(result['shader_binary_count'], 4)
        program = result['programs'][0]
        self.assertEqual(program['variation_count'], 2)
        self.assertEqual(program['variation_macros'], [
            {'name': 'MODE', 'symbol': 'var_mode', 'values': ['0', '1']}])
        self.assertEqual(program['uniforms'][0]['name'], 'texmtx1')
        self.assertEqual(program['uniforms'][0]['variation_usage_count'], 2)
        self.assertEqual(program['uniforms'][0]['variation_usage_total'], 2)
        self.assertNotIn('variation_usage', program['uniforms'][0])
        self.assertEqual(program['samplers'][0]['symbol'], '_a0')
        self.assertEqual(program['attributes'][0]['symbol'], '_u0')

    def test_reads_big_endian_header_and_sections(self):
        self.assertEqual(parse_sharcfb(_fixture('>'))['endian'], 'big')

    def test_rejects_invalid_header_ranges_and_stage_references(self):
        data = bytearray(_fixture())
        data[8:12] = _u32(len(data) + 1, '<')
        with self.assertRaisesRegex(ValueError, 'declared size'):
            parse_sharcfb(data)

        data = bytearray(_fixture())
        # A reversed stage sequence must fail the program's declared stage order.
        binary_start = 24 + struct.unpack_from('<I', data, 20)[0]
        struct.pack_into('<I', data, binary_start + 8 + 4, 1)
        with self.assertRaisesRegex(ValueError, 'stage order'):
            parse_sharcfb(data)

        data = bytearray(_fixture())
        data[4:8] = _u32(9, '<')
        with self.assertRaisesRegex(ValueError, 'version'):
            parse_sharcfb(data)

    def test_rejects_malformed_shader_symbol_and_string(self):
        data = bytearray(_fixture())
        # Corrupt the first shader-stage payload length to escape its record.
        binary_start = 24 + struct.unpack_from('<I', data, 20)[0]
        struct.pack_into('<I', data, binary_start + 8 + 12, 2)
        with self.assertRaisesRegex(ValueError, 'payload exceeds'):
            parse_sharcfb(data)

        data = bytearray(_fixture())
        data[31] = 0xff
        with self.assertRaisesRegex(ValueError, 'archive name'):
            parse_sharcfb(data)

    def test_local_world_and_course_shader_archives_expose_only_metadata(self):
        root = Path(__file__).resolve().parents[1]
        world_source = root / 'NSMBU Modding Project/content/Common/course_select/CS_WorldMap.szs'
        shader_source = root / 'NSMBU Modding Project/content/Common/shader/shaderfb.szs'
        if not world_source.is_file() or not shader_source.is_file():
            self.skipTest('User-provided local game resources unavailable')

        world = Archive(world_source.read_bytes())
        world_data = parse_sharcfb(world.read('CS_WorldMap.sharcfb'))
        self.assertEqual(world_data['programs'][0]['name'], 'mtWorldMap')
        self.assertTrue(world_data['metadata_only'])

        shaders = Archive(shader_source.read_bytes())
        course_data = parse_sharcfb(shaders.read('nw4f_cs_shader.sharcfb'))
        self.assertEqual((course_data['shader_binary_count'],
                          course_data['shader_program_count']), (1782, 5))
        programs = {program['name']: program for program in course_data['programs']}
        course = programs['nw4f_cs_course_shader']
        self.assertIn('texmtx1', {symbol['name'] for symbol in course['uniforms']})
        self.assertEqual({symbol['symbol'] for symbol in course['samplers']},
                         {'_a0', '_b0', '_b1'})
        self.assertIn('_u0', {symbol['symbol'] for symbol in course['attributes']})


if __name__ == '__main__':
    unittest.main()
