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

    def world_positions(self, model, overrides=None):
        """Rest-pose positions within one model, with hierarchy/rotation applied.

        ``overrides`` contains local translation edits, keyed by bone name.
        """
        return {name: transform[1] for name, transform in
                self.world_transforms(model, overrides).items()}

    def world_transforms(self, model, overrides=None):
        """Return supported rest-pose ``(rotation, position)`` per bone.

        This does not evaluate animations, world-to-world placement or cameras.
        Map path bones in the inspected resources have unit scale; reject other
        scale modes rather than silently mishandling segment scale compensation.
        Unsupported scaled branches are omitted from the returned preview map.
        """
        overrides = overrides or {}
        bones = self.models[model]
        by_index = {b.index: b for b in bones}
        if len(by_index) != len(bones):
            raise ValueError('Duplicate bone index')
        matrices, visiting = {}, set()
        unsupported = set()
        class UnsupportedScale(ValueError):
            pass
        def multiply(a, b):
            return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
        def rotate(a, xyz):
            return [sum(a[i][j] * xyz[j] for j in range(3)) for i in range(3)]
        def evaluate(b):
            if b.index in matrices:
                return matrices[b.index]
            if b.index in unsupported:
                raise UnsupportedScale(b.name)
            if b.index in visiting:
                raise ValueError('Cyclic bone hierarchy')
            visiting.add(b.index)
            x, y, z, w = b.rotation
            if b.flags & (1 << 12):
                cx, cy, cz = math.cos(x), math.cos(y), math.cos(z)
                sx, sy, sz = math.sin(x), math.sin(y), math.sin(z)
                r = [[cz*cy, cz*sy*sx-sz*cx, cz*sy*cx+sz*sx],
                     [sz*cy, sz*sy*sx+cz*cx, sz*sy*cx-cz*sx],
                     [-sy, cy*sx, cy*cx]]
            else:
                norm = x*x + y*y + z*z + w*w
                if abs(norm - 1) > .001:
                    raise ValueError('Non-unit bone quaternion')
                r = [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]
            t = list(overrides.get(b.name, b.position))
            # Only the path skeleton's unscaled rest pose is supported here.
            if b.scale != (1., 1., 1.):
                visiting.remove(b.index)
                unsupported.add(b.index)
                raise UnsupportedScale(b.name)
            if b.parent != -1:
                if b.parent not in by_index:
                    raise ValueError('Missing parent bone')
                try:
                    pr, pt = evaluate(by_index[b.parent])
                except UnsupportedScale:
                    visiting.remove(b.index)
                    unsupported.add(b.index)
                    raise
                t = [a+c for a,c in zip(rotate(pr, t), pt)]
                r = multiply(pr, r)
            visiting.remove(b.index)
            matrices[b.index] = r, t
            return r, t
        result = {}
        for b in bones:
            try:
                result[b.name] = evaluate(b)
            except UnsupportedScale:
                continue
        return result

    def world_affine_transforms(self, model):
        """Return rest-pose ``(linear, position)`` transforms for safe bones.

        Positive scale is composed with rotation and translation through the
        hierarchy. Segment-scale compensation and camera-facing billboard modes
        are omitted because their engine behavior is not reproduced here.
        """
        bones = self.models[model]
        by_index = {b.index: b for b in bones}
        if len(by_index) != len(bones):
            raise ValueError('Duplicate bone index')
        matrices, visiting, unsupported = {}, set(), set()

        class UnsupportedAffine(ValueError):
            pass

        def multiply(a, b):
            return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)]
                    for i in range(3)]

        def apply(matrix, xyz):
            return [sum(matrix[i][j] * xyz[j] for j in range(3)) for i in range(3)]

        def evaluate(b):
            if b.index in matrices:
                return matrices[b.index]
            if b.index in unsupported:
                raise UnsupportedAffine(b.name)
            if b.index in visiting:
                raise ValueError('Cyclic bone hierarchy')
            visiting.add(b.index)
            try:
                if b.flags & (1 << 23):
                    raise UnsupportedAffine(f'{b.name}: segment-scale compensation')
                billboard_mode = (b.flags >> 16) & 0x7
                if billboard_mode > 1:
                    raise UnsupportedAffine(f'{b.name}: camera-facing billboard transform')
                if any(not math.isfinite(value) or value <= 0. or value > 1e7
                       for value in b.scale):
                    raise UnsupportedAffine(f'{b.name}: unsupported scale')

                x, y, z, w = b.rotation
                if b.flags & (1 << 12):
                    cx, cy, cz = math.cos(x), math.cos(y), math.cos(z)
                    sx, sy, sz = math.sin(x), math.sin(y), math.sin(z)
                    rotation = [[cz*cy, cz*sy*sx-sz*cx, cz*sy*cx+sz*sx],
                                [sz*cy, sz*sy*sx+cz*cx, sz*sy*cx-cz*sx],
                                [-sy, cy*sx, cy*cx]]
                else:
                    norm = x*x + y*y + z*z + w*w
                    if not all(math.isfinite(value) for value in b.rotation) or abs(norm - 1) > .001:
                        raise ValueError(f'{b.name}: non-unit bone quaternion')
                    rotation = [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                                [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                                [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]
                linear = [[rotation[i][j] * b.scale[j] for j in range(3)]
                          for i in range(3)]
                position = list(b.position)
                if not all(math.isfinite(value) and abs(value) <= 1e7 for value in position):
                    raise ValueError(f'{b.name}: invalid bone translation')
                if b.parent != -1:
                    if b.parent not in by_index:
                        raise ValueError('Missing parent bone')
                    try:
                        parent_linear, parent_position = evaluate(by_index[b.parent])
                    except UnsupportedAffine:
                        unsupported.add(b.index)
                        raise
                    position = [a + c for a, c in zip(apply(parent_linear, position), parent_position)]
                    linear = multiply(parent_linear, linear)
                if not all(math.isfinite(value) and abs(value) <= 1e12
                           for row in linear for value in row):
                    raise ValueError(f'{b.name}: rest-pose matrix exceeds supported bounds')
                matrices[b.index] = linear, position
                return matrices[b.index]
            except UnsupportedAffine:
                unsupported.add(b.index)
                raise
            finally:
                visiting.discard(b.index)

        result = {}
        for b in bones:
            try:
                result[b.name] = evaluate(b)
            except UnsupportedAffine:
                continue
        return result

    def local_position_for_world(self, model, name, world_position, overrides=None):
        """Convert one desired model-space rest position to a bone translation.

        Parent transforms are applied in the same unscaled rest-pose subset as
        ``world_positions``. This intentionally rejects unsupported branches
        instead of writing a guessed local position.
        """
        bones = [bone for bone in self.models[model] if bone.name == name]
        if len(bones) != 1:
            raise ValueError(f'{name}: expected one bone in model {model}, found {len(bones)}')
        if len(world_position) != 3 or not all(math.isfinite(float(v)) for v in world_position):
            raise ValueError(f'{name}: invalid world position')
        bone = bones[0]
        target = [float(v) for v in world_position]
        if bone.parent == -1:
            return target

        transforms = self.world_transforms(model, overrides)
        by_index = {item.index: item for item in self.models[model]}
        parent = by_index.get(bone.parent)
        if parent is None or parent.name not in transforms:
            raise ValueError(f'{name}: parent rest transform is unsupported')
        rotation, parent_position = transforms[parent.name]
        relative = [target[i] - parent_position[i] for i in range(3)]
        # The supported rotation matrices are orthonormal, so their inverse is
        # the transpose. Scaled branches were excluded by world_transforms.
        return [sum(rotation[j][i] * relative[j] for j in range(3)) for i in range(3)]

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
