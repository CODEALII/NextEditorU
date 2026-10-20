"""Strict Yaz0/SARC reader and layout-preserving resource replacement.

SARC replacements retain the original FAT order, offsets and allocation. This
avoids changing BFRES alignment. A larger table must fit its existing slot.
Yaz0 output uses legal literal groups; compression ratio is deliberately modest.
"""
from dataclasses import dataclass
import struct


MAX_SIZE = 256 * 1024 * 1024


def decompress(data: bytes) -> bytes:
    if data[:4] != b'Yaz0':
        return data
    if len(data) < 16:
        raise ValueError('Truncated Yaz0 header')
    size = struct.unpack_from('>I', data, 4)[0]
    if size > MAX_SIZE:
        raise ValueError('Yaz0 exceeds resource size limit')
    out = bytearray()
    pos = 16
    try:
        while len(out) < size:
            code = data[pos]
            pos += 1
            for bit in range(7, -1, -1):
                if len(out) == size:
                    break
                if code & (1 << bit):
                    out.append(data[pos])
                    pos += 1
                else:
                    first, second = data[pos], data[pos + 1]
                    pos += 2
                    distance = ((first & 15) << 8 | second) + 1
                    count = first >> 4
                    if count:
                        count += 2
                    else:
                        count = data[pos] + 18
                        pos += 1
                    if distance > len(out) or len(out) + count > size:
                        raise ValueError('Invalid Yaz0 backreference')
                    for _ in range(count):
                        out.append(out[-distance])
    except IndexError as exc:
        raise ValueError('Truncated Yaz0 stream') from exc
    return bytes(out)


def compress(data: bytes) -> bytes:
    if len(data) > MAX_SIZE:
        raise ValueError('Resource exceeds size limit')
    return b'Yaz0' + struct.pack('>I', len(data)) + bytes(8) + b''.join(
        b'\xff' + data[i:i + 8] for i in range(0, len(data), 8))


@dataclass(frozen=True)
class Entry:
    name: str
    start: int
    end: int
    fat: int


class Archive:
    def __init__(self, data: bytes):
        self.original = data
        self.compressed = data[:4] == b'Yaz0'
        self.data = decompress(data)
        d = self.data
        if len(d) < 0x20 or d[:4] != b'SARC' or d[6:8] not in (b'\xfe\xff', b'\xff\xfe'):
            raise ValueError('Not a supported SARC archive')
        self.endian = '>' if d[6:8] == b'\xfe\xff' else '<'
        u16 = lambda p: struct.unpack_from(self.endian + 'H', d, p)[0]
        u32 = lambda p: struct.unpack_from(self.endian + 'I', d, p)[0]
        if u32(8) != len(d):
            raise ValueError('SARC declared size mismatch')
        self.offset = u32(12)
        sfat = u16(4)
        if sfat + 12 > len(d) or d[sfat:sfat + 4] != b'SFAT':
            raise ValueError('Missing SFAT')
        count = u16(sfat + 6)
        nodes = sfat + u16(sfat + 4)
        sfnt = nodes + count * 16
        if sfnt + 8 > len(d) or d[sfnt:sfnt + 4] != b'SFNT':
            raise ValueError('Missing SFNT')
        names = sfnt + u16(sfnt + 4)
        if not names <= self.offset <= len(d):
            raise ValueError('Invalid SARC data offset')
        self.entries = {}
        for i in range(count):
            fat = nodes + i * 16
            key, attr, start, end = struct.unpack_from(self.endian + '4I', d, fat)
            if not 0 <= start <= end <= len(d) - self.offset:
                raise ValueError('Invalid SARC entry bounds')
            if attr >> 24 != 1:
                raise ValueError('Unnamed SARC entries are unsupported')
            p = names + (attr & 0xffffff) * 4
            if not names <= p < self.offset:
                raise ValueError('Invalid SARC name offset')
            z = d.find(b'\0', p, self.offset)
            if z == -1:
                raise ValueError('Unterminated SARC name')
            name = d[p:z].decode('utf-8')
            if name in self.entries:
                raise ValueError('Duplicate SARC name')
            self.entries[name] = Entry(name, start, end, fat)
        spans = sorted((e.start, e.end) for e in self.entries.values())
        if any(b[0] < a[1] for a, b in zip(spans, spans[1:])):
            raise ValueError('Overlapping SARC entries')

    def read(self, name):
        e = self.entries[name]
        return self.data[self.offset + e.start:self.offset + e.end]

    def replace(self, replacements: dict[str, bytes]) -> bytes:
        if not replacements or all(self.read(n) == v for n, v in replacements.items()):
            return self.original
        out = bytearray(self.data)
        for name, payload in replacements.items():
            e = self.entries[name]
            next_start = min((n.start for n in self.entries.values() if n.start > e.start), default=len(out) - self.offset)
            if len(payload) > next_start - e.start:
                raise ValueError(f'{name}: {len(payload)} bytes exceed preserved allocation {next_start - e.start}')
            pos = self.offset + e.start
            out[pos:pos + len(payload)] = payload
            if len(payload) < e.end - e.start:
                out[pos + len(payload):self.offset + e.end] = bytes(e.end - e.start - len(payload))
            struct.pack_into(self.endian + 'I', out, e.fat + 12, e.start + len(payload))
        return compress(bytes(out)) if self.compressed else bytes(out)
