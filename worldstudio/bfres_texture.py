"""Narrow extraction of static Wii U BFRES material textures.

The layouts are cross-checked against the repository's pinned MIT BfresLibrary
Wii U Material, TextureRef and FTEX readers. This helper intentionally supports
only one non-array BC1/BC3 albedo or BC5 SNORM normal map on a named material;
it does not interpret samplers, light maps, shader parameters or animation.
"""
from .bfres import Skeletons


_BASE_COLOR_FORMATS = {0x31: "BC1 UNorm", 0x33: "BC3 UNorm"}
_NORMAL_MAP_FORMATS = {0x235: "BC5 SNORM"}
_DIAGNOSTIC_MAP_FORMATS = {0x35: "BC5 UNorm"}


def _extract_material_texture(data, model_name, material_name, texture_name, *, suffix,
                              formats, kind, expected_slot=None):
    """Return a supported raw GX2 texture referenced by one BFRES material.

    The supported surface is a single-slice 2D, one-sample, 2D Thin1 texture
    stored in the BFRES image payload. The returned bytes remain GX2-tiled.
    """
    r = Skeletons(data)
    textures = dict(r.dictionary(r.ptr(0x24)))
    models = dict(r.dictionary(r.ptr(0x20)))
    if model_name not in models:
        raise ValueError(f'Missing BFRES model: {model_name}')
    model = models[model_name]
    materials = dict(r.dictionary(r.ptr(model + 24)))
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
    if expected_slot is not None:
        sampler_count = data[material + 16]
        samplers = r.dictionary(r.ptr(material + 48))
        if sampler_count != reference_count or len(samplers) != reference_count:
            raise ValueError(f'{material_name}: texture-reference and sampler counts do not match')
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
    if len(matches) != 1:
        if texture_name is not None:
            expected = texture_name
        elif suffix is not None:
            expected = f'one *{suffix} reference'
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
    """Return raw GX2 BC1/BC3 base-color metadata and bytes for a material."""
    return _extract_material_texture(data, model_name, material_name, texture_name,
                                     suffix="_alb", formats=_BASE_COLOR_FORMATS,
                                     kind="base-color")


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
    """Return one BC5 UNorm texture by observed sampler slot for inspection.

    Sampler and texture-reference order must correspond and the table sizes
    must agree. This identifies the stored texture and slot only; it does not
    infer the shader meaning of the slot.
    """
    if not isinstance(sampler_slot, str) or not sampler_slot:
        raise ValueError("A non-empty BFRES sampler slot is required")
    return _extract_material_texture(data, model_name, material_name, None, suffix=None,
                                    formats=_DIAGNOSTIC_MAP_FORMATS,
                                    kind="diagnostic map", expected_slot=sampler_slot)


def extract_bc1_base_texture(data, model_name, material_name, texture_name=None):
    """Compatibility wrapper that requires a BC1 base-color texture."""
    texture = extract_base_color_texture(data, model_name, material_name, texture_name)
    if texture['format'] != 0x31:
        raise ValueError(f"{texture['name']}: expected GX2 BC1 UNorm (0x31), found 0x{texture['format']:X}")
    return texture
