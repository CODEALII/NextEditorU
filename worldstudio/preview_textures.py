"""Build bounded, shared material-texture catalogs for the 3D preview."""
from __future__ import annotations

import base64

from .bfres_texture import (extract_base_color_texture, extract_normal_map_texture,
                            extract_sampler_diagnostic_texture,
                            extract_sampler_wrap_modes)
from .bfres_material import extract_texture_srt_parameters
from .texture_preview import (decode_bc1, decode_bc3, decode_bc4_unorm, decode_bc5_snorm,
                              decode_bc5_unorm, detile_bc1_thin1, detile_bc3_thin1,
                              detile_bc4_thin1, detile_bc5_snorm_thin1,
                              detile_bc5_unorm_thin1)


def attach_texture_srt_parameters(model_data, shapes):
    """Attach validated read-only ``texmtxN`` metadata to matching shapes."""
    by_material = {}
    failed_materials = set()
    for shape in shapes:
        shape.pop("textureSrt", None)
        material = shape.get("material")
        if not isinstance(material, str) or material in failed_materials:
            continue
        if material not in by_material:
            try:
                by_material[material] = extract_texture_srt_parameters(
                    model_data, "CS_W1_World", material)
            except (ValueError, KeyError, TypeError, OverflowError):
                failed_materials.add(material)
                continue
        if by_material[material]:
            shape["textureSrt"] = by_material[material]
    return failed_materials


def attach_base_color_textures(model_data, shapes, *, model_name="CS_W1_World",
                               max_texture_pixels=4 * 1024 * 1024,
                               max_scene_pixels=16 * 1024 * 1024):
    """Attach supported material albedos to UV meshes and return one shared catalog.

    Only BC1/BC3, one-layer, one-sample, GX2 2D Thin1 base-color maps are
    decoded. Failed or unsupported materials remain visible with preview color.
    The pixel limits bound decoded RGBA allocations for malformed local files.
    """
    if type(max_texture_pixels) is not int or max_texture_pixels <= 0:
        raise ValueError("max_texture_pixels must be a positive integer")
    if type(max_scene_pixels) is not int or max_scene_pixels <= 0:
        raise ValueError("max_scene_pixels must be a positive integer")

    textures = {}
    material_textures = {}
    material_wrap_modes = {}
    material_warnings = {}
    failed_materials = set()
    decoded_pixels = 0
    for shape in shapes:
        shape.pop("texture", None)
        shape.pop("textureWarning", None)
        shape.pop("textureWrap", None)
        if shape.get("uvs") is None:
            continue
        material = shape["material"]
        if material not in material_textures:
            try:
                texture = extract_base_color_texture(model_data, model_name, material)
                try:
                    material_wrap_modes[material] = extract_sampler_wrap_modes(
                        model_data, model_name, material, sampler_slot="_a0",
                        texture_name=texture["name"])
                except (ValueError, KeyError, TypeError, OverflowError) as error:
                    reason = str(error).strip() or type(error).__name__
                    material_wrap_modes[material] = {
                        "samplerSlot": "_a0", "s": "repeat", "t": "repeat",
                        "gx2": None, "labels": {"s": "Unavailable", "t": "Unavailable"},
                        "warnings": [f"Sampler state unavailable ({reason}); using Repeat on both axes."],
                    }
                if texture["name"] not in textures:
                    pixels = texture["width"] * texture["height"]
                    if pixels > max_texture_pixels:
                        raise ValueError(f"{texture['name']}: preview texture exceeds the pixel limit")
                    if decoded_pixels + pixels > max_scene_pixels:
                        raise ValueError("preview base textures exceed the scene pixel limit")
                    if texture["format"] == 0x31:
                        compact = detile_bc1_thin1(
                            texture["data"], texture["width"], texture["height"], texture["pitch"],
                            tile_mode=texture["tile_mode"], swizzle=texture["swizzle"],
                            depth=texture["depth"], aa=0,
                        )
                        rgba = decode_bc1(compact, texture["width"], texture["height"])
                    elif texture["format"] == 0x33:
                        compact = detile_bc3_thin1(
                            texture["data"], texture["width"], texture["height"], texture["pitch"],
                            tile_mode=texture["tile_mode"], swizzle=texture["swizzle"],
                            depth=texture["depth"], aa=0,
                        )
                        rgba = decode_bc3(compact, texture["width"], texture["height"])
                    else:
                        raise ValueError(f"{texture['name']}: unsupported preview format")
                    textures[texture["name"]] = {
                        "name": texture["name"], "width": texture["width"],
                        "height": texture["height"], "format": texture["format"],
                        "rgbaBase64": base64.b64encode(rgba).decode("ascii"),
                    }
                    decoded_pixels += pixels
                material_textures[material] = texture["name"]
            except (ValueError, KeyError, TypeError, OverflowError) as error:
                material_textures[material] = None
                failed_materials.add(material)
                reason = str(error).strip() or type(error).__name__
                material_warnings[material] = reason[:240]
        texture_name = material_textures[material]
        if texture_name:
            shape["texture"] = texture_name
            shape["textureWrap"] = material_wrap_modes[material]
        else:
            shape["textureWarning"] = material_warnings[material]
    return textures, failed_materials


def attach_normal_map_textures(model_data, shapes, *, max_texture_pixels=4 * 1024 * 1024,
                               max_scene_pixels=8 * 1024 * 1024):
    """Attach supported BC5 SNORM maps for diagnostic channel viewing only.

    Decoded channels are independent of game shader state and are never used
    to shade the preview geometry. Pixel limits protect the offline viewer
    from unexpectedly large local texture payloads.
    """
    if type(max_texture_pixels) is not int or max_texture_pixels <= 0:
        raise ValueError("max_texture_pixels must be a positive integer")
    if type(max_scene_pixels) is not int or max_scene_pixels <= 0:
        raise ValueError("max_scene_pixels must be a positive integer")

    textures = {}
    material_textures = {}
    failed_materials = set()
    decoded_pixels = 0
    for shape in shapes:
        if shape.get("uvs") is None:
            continue
        material = shape["material"]
        if material not in material_textures:
            try:
                texture = extract_normal_map_texture(model_data, "CS_W1_World", material)
                if texture["name"] not in textures:
                    pixels = texture["width"] * texture["height"]
                    if pixels > max_texture_pixels:
                        raise ValueError(f"{texture['name']}: preview texture exceeds the pixel limit")
                    if decoded_pixels + pixels > max_scene_pixels:
                        raise ValueError("preview normal maps exceed the scene pixel limit")
                    compact = detile_bc5_snorm_thin1(
                        texture["data"], texture["width"], texture["height"], texture["pitch"],
                        tile_mode=texture["tile_mode"], swizzle=texture["swizzle"],
                        depth=texture["depth"], aa=0,
                    )
                    rgba = decode_bc5_snorm(compact, texture["width"], texture["height"])
                    textures[texture["name"]] = {
                        "name": texture["name"], "width": texture["width"],
                        "height": texture["height"], "format": texture["format"],
                        "rgbaBase64": base64.b64encode(rgba).decode("ascii"),
                    }
                    decoded_pixels += pixels
                material_textures[material] = texture["name"]
            except (ValueError, KeyError, TypeError, OverflowError):
                material_textures[material] = None
                failed_materials.add(material)
        texture_name = material_textures[material]
        if texture_name:
            shape["normalTexture"] = texture_name
    return textures, failed_materials


def attach_sampler_diagnostic_textures(model_data, shapes, *, sampler_slot="_o0",
                                       max_texture_pixels=4 * 1024 * 1024,
                                       max_scene_pixels=8 * 1024 * 1024):
    """Attach supported BC channel maps from an observed W1 sampler slot.

    `_o0` supplies BC5 UNorm, `_o1`/`_b0`/`_s0`/`_x2` supply BC4 UNorm, and
    the locally observed `_x0`/`_x1` slots supply BC3 UNorm. Stored values
    remain diagnostic only; material semantics are not inferred.
    """
    if sampler_slot not in ("_o0", "_o1", "_b0", "_s0", "_x2", "_x0", "_x1"):
        raise ValueError("Unsupported diagnostic sampler slot")
    shape_field = {"_o0": "diagnosticTexture", "_o1": "maskTexture"}.get(sampler_slot)
    if type(max_texture_pixels) is not int or max_texture_pixels <= 0:
        raise ValueError("max_texture_pixels must be a positive integer")
    if type(max_scene_pixels) is not int or max_scene_pixels <= 0:
        raise ValueError("max_scene_pixels must be a positive integer")

    textures = {}
    material_textures = {}
    failed_materials = set()
    decoded_pixels = 0
    for shape in shapes:
        if shape.get("uvs") is None:
            continue
        material = shape["material"]
        if material not in material_textures:
            try:
                texture = extract_sampler_diagnostic_texture(
                    model_data, "CS_W1_World", material, sampler_slot)
                catalog_key = (texture["name"] if sampler_slot in ("_o0", "_o1")
                               else f"{sampler_slot}:{texture['name']}")
                if catalog_key not in textures:
                    pixels = texture["width"] * texture["height"]
                    if pixels > max_texture_pixels:
                        raise ValueError(f"{texture['name']}: diagnostic texture exceeds the pixel limit")
                    if decoded_pixels + pixels > max_scene_pixels:
                        raise ValueError("diagnostic textures exceed the scene pixel limit")
                    if texture["format"] == 0x35:
                        compact = detile_bc5_unorm_thin1(
                            texture["data"], texture["width"], texture["height"], texture["pitch"],
                            tile_mode=texture["tile_mode"], swizzle=texture["swizzle"],
                            depth=texture["depth"], aa=0,
                        )
                        rgba = decode_bc5_unorm(compact, texture["width"], texture["height"])
                    elif texture["format"] == 0x34:
                        compact = detile_bc4_thin1(
                            texture["data"], texture["width"], texture["height"], texture["pitch"],
                            tile_mode=texture["tile_mode"], swizzle=texture["swizzle"],
                            depth=texture["depth"], aa=0,
                        )
                        rgba = decode_bc4_unorm(compact, texture["width"], texture["height"])
                    elif texture["format"] == 0x33 and sampler_slot in ("_x0", "_x1"):
                        compact = detile_bc3_thin1(
                            texture["data"], texture["width"], texture["height"], texture["pitch"],
                            tile_mode=texture["tile_mode"], swizzle=texture["swizzle"],
                            depth=texture["depth"], aa=0,
                        )
                        rgba = decode_bc3(compact, texture["width"], texture["height"])
                    else:
                        raise ValueError(f"{texture['name']}: unsupported diagnostic preview format")
                    textures[catalog_key] = {
                        "name": texture["name"], "width": texture["width"],
                        "height": texture["height"],
                        "format": texture["format"], "samplerSlot": sampler_slot,
                        "rgbaBase64": base64.b64encode(rgba).decode("ascii"),
                    }
                    decoded_pixels += pixels
                material_textures[material] = catalog_key
            except (ValueError, KeyError, TypeError, OverflowError):
                material_textures[material] = None
                failed_materials.add(material)
        texture_name = material_textures[material]
        if texture_name:
            payload = textures[texture_name]
            if shape_field:
                shape[shape_field] = payload["name"]
            shape.setdefault("samplerTextures", {})[sampler_slot] = texture_name
            if payload["format"] == 0x34:
                shape.setdefault("bc4Samplers", {})[sampler_slot] = texture_name
    return textures, failed_materials
