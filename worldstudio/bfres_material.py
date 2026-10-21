"""Narrow read-only extraction of Wii U BFRES material texture SRT values."""
import math
import struct

from .bfres import Skeletons


_TEXTURE_SRT_SIZE = 28


def decode_texture_srt_record(data):
    """Decode the tested 28-byte Wii U Texture SRT parameter payload.

    This exposes stored fields for inspection only. It deliberately does not
    build a UV matrix or infer which shader sampler consumes the parameter.
    """
    if len(data) != _TEXTURE_SRT_SIZE:
        raise ValueError("Texture SRT record must be exactly 28 bytes")
    mode, scale_u, scale_v, rotation, translate_u, translate_v, matrix_pointer = \
        struct.unpack(">I5fI", data)
    if mode not in (0, 1, 2):
        raise ValueError("Unsupported texture SRT mode")
    values = (scale_u, scale_v, rotation, translate_u, translate_v)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Texture SRT contains a non-finite value")
    if matrix_pointer != 0:
        raise ValueError("Texture SRT matrix pointer is not supported")
    return {
        "mode": mode,
        "scale": [scale_u, scale_v],
        "rotation": rotation,
        "translation": [translate_u, translate_v],
    }


def extract_texture_srt_parameters(data, model_name, material_name):
    """Return ``texmtxN`` values from one tested Wii U FMAT material.

    The parser validates the material parameter dictionary and data range,
    then accepts only type-31, zero-matrix-pointer SRT records. It does not
    make their texture/sampler association or rendering effect claims.
    """
    reader = Skeletons(data)
    models = dict(reader.dictionary(reader.ptr(0x20)))
    if model_name not in models:
        raise ValueError(f"Missing BFRES model: {model_name}")
    materials = dict(reader.dictionary(reader.ptr(models[model_name] + 24)))
    if material_name not in materials:
        raise ValueError(f"Missing BFRES material: {material_name}")
    material = materials[material_name]
    reader.bounds(material, 0x48)
    if data[material:material + 4] != b"FMAT":
        raise ValueError(f"{material_name}: invalid BFRES material")

    parameter_count = reader.u16(material + 18)
    parameters = reader.dictionary(reader.ptr(material + 56))
    if len(parameters) != parameter_count:
        raise ValueError(f"{material_name}: material parameter count mismatch")
    srt_parameters = [(name, entry) for name, entry in parameters
                      if name.startswith("texmtx") and name[6:].isdecimal()]
    if not srt_parameters:
        return {}

    data_size = reader.u16(material + 22)
    data_offset = reader.ptr(material + 60)
    reader.bounds(data_offset, data_size)
    result = {}
    for name, entry in srt_parameters:
        reader.bounds(entry, 12)
        if data[entry] != 31 or data[entry + 1] != 0:
            raise ValueError(f"{material_name}: unsupported {name} parameter record")
        value_offset = reader.u16(entry + 2)
        if value_offset + _TEXTURE_SRT_SIZE > data_size:
            raise ValueError(f"{material_name}: {name} value exceeds material parameter data")
        start = data_offset + value_offset
        result[name] = decode_texture_srt_record(data[start:start + _TEXTURE_SRT_SIZE])
    return result
