"""Narrow Wii U BFRES skeleton reader (not a mesh importer).

Field layout cross-checked with MIT BfresLibrary, Wii U Bone/Skeleton/Model
loaders at commit 65c005275deed1e085069e72fea523247f955b87. No game offsets.
"""
from dataclasses import dataclass
import math
import struct


@dataclass
class Bone:
    model: str
    name: str
    offset: int
    index: int
    parent: int
    flags: int
    scale: tuple
    rotation: tuple
    position: tuple


class Skeletons:
    def __init__(self, data):
        self.data = data
        if len(data) < 0x40 or data[:4] != b'FRES' or data[8:10] != b'\xfe\xff':
            raise ValueError('Only Wii U big-endian BFRES supported')
        self.version = self.u32(4)
        self.models = {}
        self.bones = {}
        for model_name, model in self.dictionary(self.ptr(0x20)):
            if data[model:model + 4] != b'FMDL':
                raise ValueError('Invalid FMDL')
            skel = self.ptr(model + 12)
            if not skel:
                continue
            if data[skel:skel + 4] != b'FSKL':
                raise ValueError('Invalid FSKL')
            count = self.u16(skel + 8)
            bones = []
            for name, offset in self.dictionary(self.ptr(skel + 16)):
                self.bounds(offset, 64)
                bone = Bone(model_name, name, offset, self.u16(offset + 4),
                    struct.unpack_from('>h', data, offset + 6)[0], self.u32(offset + 16),
                    struct.unpack_from('>3f', data, offset + 20),
                    struct.unpack_from('>4f', data, offset + 32),
                    struct.unpack_from('>3f', data, offset + 48))
                if self.string(self.ptr(offset)) != name:
                    raise ValueError('Bone dictionary/name mismatch')
                if not all(math.isfinite(v) for v in (*bone.scale, *bone.rotation, *bone.position)):
                    raise ValueError('Non-finite bone transform')
                bones.append(bone)
                self.bones.setdefault(name, []).append(bone)
            if len(bones) != count:
                raise ValueError('Skeleton bone count mismatch')
            self.models[model_name] = bones

    def bounds(self, offset, size):
        if offset < 0 or offset + size > len(self.data):
            raise ValueError('BFRES offset outside file')

    def u32(self, offset):
        self.bounds(offset, 4)
        return struct.unpack_from('>I', self.data, offset)[0]

    def u16(self, offset):
        self.bounds(offset, 2)
        return struct.unpack_from('>H', self.data, offset)[0]

    def ptr(self, offset):
        v = self.u32(offset)
        if v == 0:
            return 0
        result = (offset + v) & 0xffffffff
        self.bounds(result, 1)
        return result

    def string(self, offset):
        end = self.data.find(b'\0', offset, min(offset + 4096, len(self.data)))
        if end < 0:
            raise ValueError('Unterminated BFRES string')
        return self.data[offset:end].decode('utf-8')

    def dictionary(self, offset):
        if not offset:
            return []
        count = self.u32(offset + 4)
        if count > 65535:
            raise ValueError('BFRES dictionary exceeds limit')
        self.bounds(offset, 8 + 16 * (count + 1))
        return [(self.string(self.ptr(offset + 8 + 16 * (i + 1) + 8)),
                 self.ptr(offset + 8 + 16 * (i + 1) + 12)) for i in range(count)]

    def unique(self, name):
        matches = self.bones.get(name, [])
        if len(matches) != 1:
            raise ValueError(f'{name}: expected one bone, found {len(matches)}')
        return matches[0]

    def patch_positions(self, changes):
        out = bytearray(self.data)
        for name, xyz in changes.items():
            b = self.unique(name)
            if len(xyz) != 3 or not all(math.isfinite(float(v)) and abs(float(v)) <= 1e7 for v in xyz):
                raise ValueError(f'{name}: invalid position')
            xyz = tuple(float(v) for v in xyz)
            if xyz == b.position:
                continue
            struct.pack_into('>3f', out, b.offset + 48, *xyz)
            # Clear local/cumulative TranslateZero optimizations.
            struct.pack_into('>I', out, b.offset + 16, b.flags & ~((1 << 27) | (1 << 31)))
        return bytes(out)
