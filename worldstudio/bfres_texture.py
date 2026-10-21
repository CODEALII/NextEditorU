"""Narrow extraction of static Wii U BFRES material textures.

The layouts are cross-checked against the repository's pinned MIT BfresLibrary
Wii U Material, TextureRef and FTEX readers. This helper intentionally supports
one non-array BC1/BC3 albedo, BC5 SNORM `_n0` map, or evidenced local W1 BC5
UNorm `_o0` / BC4 UNorm `_o1` diagnostic map. It also exposes a read-only
sampler catalog for observed W1 slots. It does not infer sampler semantics or
interpret light maps, shader parameters or animation.
"""
from functools import lru_cache

from .bfres import Skeletons


_BASE_COLOR_FORMATS = {0x31: "BC1 UNorm", 0x33: "BC3 UNorm"}
_NORMAL_MAP_FORMATS = {0x235: "BC5 SNORM"}
_BC4_DIAGNOSTIC_FORMATS = {0x34: "BC4 UNorm"}
_BC5_DIAGNOSTIC_FORMATS = {0x35: "BC5 UNorm"}
_BC3_SAMPLER_DIAGNOSTIC_FORMATS = {0x33: "BC3 UNorm"}
_DIAGNOSTIC_SLOT_FORMATS = {"_o0": _BC5_DIAGNOSTIC_FORMATS,
                            "_o1": _BC4_DIAGNOSTIC_FORMATS,
                            "_b0": _BC4_DIAGNOSTIC_FORMATS,
                            "_s0": _BC4_DIAGNOSTIC_FORMATS,
                            "_x2": _BC4_DIAGNOSTIC_FORMATS,
                            "_x0": _BC3_SAMPLER_DIAGNOSTIC_FORMATS,
                            "_x1": _BC3_SAMPLER_DIAGNOSTIC_FORMATS}
_GX2_TEX_CLAMP_NAMES = (
    "Wrap", "Mirror", "Clamp", "MirrorOnce", "ClampHalfBorder",
    "MirrorOnceHalfBorder", "ClampBorder", "MirrorOnceBorder", "ClampToEdge",
)


def extract_sampler_wrap_modes(data, model_name, material_name, *, sampler_slot="_a0",
                               texture_name=None):
    """Read the GX2 S/T wrap values for one material texture sampler.

    The local preview maps Wrap and Mirror directly to WebGL modes. GX2 Clamp
    and ClampToEdge both use WebGL CLAMP_TO_EDGE; Clamp is marked as an edge
    approximation. Border and MirrorOnce modes fall back to Repeat explicitly
    because WebGL 1 has no equivalent mode.
    """
    r, textures, materials = _texture_context(data, model_name)
    if material_name not in materials:
        raise ValueError(f'Missing BFRES material: {material_name}')
    material = materials[material_name]
    r.bounds(material, 0x48)
    if data[material:material + 4] != b'FMAT':
        raise ValueError(f'{material_name}: invalid BFRES material')

    reference_count = data[material + 17]
    sampler_count = data[material + 16]
    references = r.ptr(material + 40)
    samplers = r.dictionary(r.ptr(material + 48))
    if reference_count != sampler_count or len(samplers) != reference_count:
        raise ValueError(f'{material_name}: texture-reference and sampler counts do not match')
    r.bounds(references, reference_count * 8)

    matches = []
    for index in range(reference_count):
        reference = references + index * 8
        name = r.string(r.ptr(reference))
        texture = r.ptr(reference + 4)
        if name not in textures or textures[name] != texture:
            raise ValueError(f'{material_name}: texture reference does not match BFRES dictionary: {name}')
        sampler_name, sampler = samplers[index]
        if sampler_name == sampler_slot and (texture_name is None or name == texture_name):
            matches.append((sampler_name, sampler))

    if len(matches) != 1:
        expected = f'{sampler_slot} sampler texture'
        if texture_name is not None:
            expected += f' for {texture_name}'
        raise ValueError(f'{material_name}: expected exactly one {expected}, found {len(matches)}')

    _, sampler = matches[0]
    r.bounds(sampler, 12)  # Wii U BFRES Sampler stores three GX2 words first.
    word = r.u32(sampler)

    def decode_axis(code, axis):
        label = _GX2_TEX_CLAMP_NAMES[code] if code < len(_GX2_TEX_CLAMP_NAMES) else f'Unknown ({code})'
        warnings = []
        if code == 0:
            webgl = 'repeat'
        elif code == 1:
            webgl = 'mirror'
        elif code in (2, 8):
            webgl = 'clamp'
            if code == 2:
                warnings.append(f'GX2 Clamp on {axis} is approximated with WebGL CLAMP_TO_EDGE.')
        else:
            webgl = 'repeat'
            warnings.append(f'GX2 {label} on {axis} is unsupported; using Repeat for this preview.')
        return webgl, label, warnings

    gx2_s = word & 0x7
    gx2_t = (word >> 3) & 0x7
    webgl_s, label_s, warnings_s = decode_axis(gx2_s, 'S')
    webgl_t, label_t, warnings_t = decode_axis(gx2_t, 'T')
    return {
        'samplerSlot': sampler_slot,
        's': webgl_s,
        't': webgl_t,
        'gx2': {'s': gx2_s, 't': gx2_t},
        'labels': {'s': label_s, 't': label_t},
        'warnings': warnings_s + warnings_t,
    }


def _build_texture_context(data, model_name):
    """Parse the dictionaries shared by every texture lookup in one BFRES."""
    reader = Skeletons(data)
    textures = dict(reader.dictionary(reader.ptr(0x24)))
    models = dict(reader.dictionary(reader.ptr(0x20)))
    if model_name not in models:
        raise ValueError(f'Missing BFRES model: {model_name}')
    materials = dict(reader.dictionary(reader.ptr(models[model_name] + 24)))
    return reader, textures, materials


@lru_cache(maxsize=1)
def _cached_texture_context(data, model_name):
    """Reuse a read-only BFRES index for repeated W1 sampler lookups."""
    return _build_texture_context(data, model_name)


def _texture_context(data, model_name):
    if isinstance(data, bytes) and isinstance(model_name, str):
        return _cached_texture_context(data, model_name)
    return _build_texture_context(data, model_name)


def _extract_material_texture(data, model_name, material_name, texture_name, *, suffix,
                              formats, kind, expected_slot=None, prefer_slot=None):
    """Return a supported raw GX2 texture referenced by one BFRES material.

    The supported surface is a single-slice 2D, one-sample, 2D Thin1 texture
    stored in the BFRES image payload. The returned bytes remain GX2-tiled.
    """
    r, textures, materials = _texture_context(data, model_name)
    if material_name not in materials:
        raise ValueError(f'Missing BFRES material: {material_name}')
    material = materials[material_name]
    r.bounds(material, 0x48)
    if data[material:material + 4] != b'FMAT':
        raise ValueError(f'{material_name}: invalid BFRES material')
    reference_count = data[material + 17]
    reference_list = r.ptr(material + 40)
    r.bounds(reference_list, reference_count * 8)
    samplers = None

    def load_samplers():
        nonlocal samplers
        if samplers is None:
            sampler_count = data[material + 16]
            samplers = r.dictionary(r.ptr(material + 48))
            if sampler_count != reference_count or len(samplers) != reference_count:
                raise ValueError(f'{material_name}: texture-reference and sampler counts do not match')
        return samplers

    if expected_slot is not None:
        load_samplers()
    matches = []
    for index in range(reference_count):
        reference = reference_list + index * 8
        name = r.string(r.ptr(reference))
        texture = r.ptr(reference + 4)
        if name not in textures or textures[name] != texture:
            raise ValueError(f'{material_name}: texture reference does not match BFRES dictionary: {name}')
        if (texture_name is not None and name == texture_name) or (
                texture_name is None and suffix is not None and name.lower().endswith(suffix)) or (
                texture_name is None and suffix is None and expected_slot is not None and
                samplers[index][0] == expected_slot):
            matches.append((index, name, texture))
    if len(matches) > 1 and prefer_slot is not None:
        sampler_values = load_samplers()
        preferred = [match for match in matches
                     if sampler_values[match[0]][0] == prefer_slot]
        if len(preferred) == 1:
            matches = preferred
    if len(matches) != 1:
        if texture_name is not None:
            expected = texture_name
        elif suffix is not None:
            expected = f'one *{suffix} reference'
            if prefer_slot is not None:
                expected += f' or one unambiguous {prefer_slot} sampler match'
        else:
            expected = f'one {expected_slot} sampler texture'
        raise ValueError(f'{material_name}: expected exactly {expected}, found {len(matches)}')

    reference_index, name, texture = matches[0]
    if expected_slot is not None:
        if samplers[reference_index][0] != expected_slot:
            raise ValueError(f'{material_name}: {name} is in sampler slot {samplers[reference_index][0]}, expected {expected_slot}')
    r.bounds(texture, 0xB8)
    if data[texture:texture + 4] != b'FTEX':
        raise ValueError(f'{name}: invalid BFRES texture')
    width, height, depth, mip_count = (r.u32(texture + offset) for offset in (8, 12, 16, 20))
    surface_format = r.u32(texture + 24)
    aa_mode, use, data_size = (r.u32(texture + offset) for offset in (28, 32, 36))
    mip_size, tile_mode = r.u32(texture + 44), r.u32(texture + 52)
    swizzle, pitch = r.u32(texture + 56), r.u32(texture + 64)
    if not (1 <= width <= 16384 and 1 <= height <= 16384 and depth == 1):
        raise ValueError(f'{name}: unsupported or unreasonable texture dimensions')
    if surface_format not in formats:
        allowed = ", ".join(f"{label} (0x{value:X})" for value, label in formats.items())
        raise ValueError(f'{name}: expected supported {kind} format {allowed}, found 0x{surface_format:X}')
    if aa_mode != 0 or use != 1 or tile_mode != 4:
        raise ValueError(f'{name}: expected single-sample texture-use GX2 2D Thin1 layout')
    if mip_count < 1 or pitch < (width + 3) // 4:
        raise ValueError(f'{name}: invalid mip count or compressed-block pitch')
    data_offset = r.ptr(texture + 0xB0)
    r.bounds(data_offset, data_size)
    if data_size == 0:
        raise ValueError(f'{name}: empty image data')
    return {
        'name': name,
        'width': width,
        'height': height,
        'depth': depth,
        'mip_count': mip_count,
        'format': surface_format,
        'tile_mode': tile_mode,
        'swizzle': swizzle,
        'pitch': pitch,
        'data_size': data_size,
        'mip_size': mip_size,
        'data': data[data_offset:data_offset + data_size],
    }


def extract_base_color_texture(data, model_name, material_name, texture_name=None):
    """Return raw GX2 BC1/BC3 base-color metadata and bytes for a material.

    If multiple ``*_alb`` references exist, the observed ``_a0`` pairing is
    used only when exactly one candidate occupies that sampler. A unique
    suffix match keeps its existing behavior.
    """
    return _extract_material_texture(data, model_name, material_name, texture_name,
                                     suffix="_alb", formats=_BASE_COLOR_FORMATS,
                                     kind="base-color", prefer_slot="_a0")


def extract_normal_map_texture(data, model_name, material_name, texture_name=None):
    """Return raw GX2 BC5 SNORM data for a referenced ``*_nml`` texture.

    This only identifies and bounds-checks the format. It does not infer the
    material shader, tangent basis or channel orientation needed for lighting.
    """
    texture = _extract_material_texture(data, model_name, material_name, texture_name,
                                        suffix="_nml", formats=_NORMAL_MAP_FORMATS,
                                        kind="normal-map", expected_slot="_n0")
    if not texture["name"].lower().endswith("_nml"):
        raise ValueError(f'{texture["name"]}: expected a *_nml normal-map reference')
    return texture


def extract_sampler_diagnostic_texture(data, model_name, material_name, sampler_slot="_o0"):
    """Return one supported BC texture by observed local W1 sampler slot.

    Sampler and texture-reference order must correspond and the table sizes
    must agree. `_o0` accepts BC5 UNorm; the locally observed `_o1`, `_b0`,
    `_s0`, and `_x2` slots accept BC4 UNorm, while `_x0` and `_x1` accept
    BC3 UNorm. Sampler contents are returned for diagnostic display only.
    This identifies the stored format and slot only; it does not infer shader
    meaning. Those mappings are only evidenced for the supplied W1 file.
    """
    if not isinstance(sampler_slot, str) or sampler_slot not in _DIAGNOSTIC_SLOT_FORMATS:
        raise ValueError("Unsupported diagnostic sampler slot")
    return _extract_material_texture(data, model_name, material_name, None, suffix=None,
                                    formats=_DIAGNOSTIC_SLOT_FORMATS[sampler_slot],
                                    kind="diagnostic map", expected_slot=sampler_slot)


def extract_bc1_base_texture(data, model_name, material_name, texture_name=None):
    """Compatibility wrapper that requires a BC1 base-color texture."""
    texture = extract_base_color_texture(data, model_name, material_name, texture_name)
    if texture['format'] != 0x31:
        raise ValueError(f"{texture['name']}: expected GX2 BC1 UNorm (0x31), found 0x{texture['format']:X}")
    return texture
