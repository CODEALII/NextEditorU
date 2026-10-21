"""Small, strict decoders for BC1/BC3/BC5 textures and one verified GX2 layout.

The Thin1 address calculation is based on the pinned source
``external/BfresLibrary/BfresLibrary/WiiU/Texture/GX2/GX2.cs`` at commit
``65c005275deed1e085069e72fea523247f955b87``. It ports the BCn block-grid
handling in ``swizzleSurf``, BC block indexing in
``computePixelIndexWithinMicroTile``, and the 2D macro-tiled address path in
``computeSurfaceAddrFromCoordMacroTiled``. This module supports only single
sample, single-layer GX2 2D Thin1 (tileMode 4) BC1, BC3 and BC5 levels. BC5
SNORM output is diagnostic; it is not used for lighting because tangent data
and channel orientation are unverified.
"""
from __future__ import annotations

_BLOCK_BYTES = 8
_TEXELS_PER_BLOCK = 4
_THIN1_MACRO_WIDTH_BLOCKS = 32
_THIN1_MACRO_HEIGHT_BLOCKS = 16
_THIN1_MACRO_BYTES = _THIN1_MACRO_WIDTH_BLOCKS * _THIN1_MACRO_HEIGHT_BLOCKS * _BLOCK_BYTES
_KNOWN_SWIZZLE_MASK = 0x000F0700


def _positive_int(value, name):
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _byte_view(data, name="data"):
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(f"{name} must be bytes-like")
    try:
        return memoryview(data).cast("B")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a contiguous byte buffer") from exc


def _rgb565(value):
    red5 = (value >> 11) & 0x1F
    green6 = (value >> 5) & 0x3F
    blue5 = value & 0x1F
    return ((red5 << 3) | (red5 >> 2),
            (green6 << 2) | (green6 >> 4),
            (blue5 << 3) | (blue5 >> 2))


def _bc1_palette(block, force_four_color=False):
    color0 = block[0] | (block[1] << 8)
    color1 = block[2] | (block[3] << 8)
    c0 = _rgb565(color0)
    c1 = _rgb565(color1)
    palette = [(*c0, 255), (*c1, 255)]
    if color0 > color1 or force_four_color:
        palette.append(tuple((2 * c0[i] + c1[i]) // 3 for i in range(3)) + (255,))
        palette.append(tuple((c0[i] + 2 * c1[i]) // 3 for i in range(3)) + (255,))
    else:
        palette.append(tuple((c0[i] + c1[i]) // 2 for i in range(3)) + (255,))
        palette.append((0, 0, 0, 0))
    return palette, int.from_bytes(block[4:8], "little")


def decode_bc1(data, width, height):
    """Decode tightly packed row-major BC1/DXT1 blocks to top-down RGBA8.

    The source must contain exactly ``ceil(width/4) * ceil(height/4)`` blocks;
    partial edge blocks are decoded then cropped to the requested dimensions.
    In the three-color BC1 mode (endpoint0 <= endpoint1), palette entry 3 is
    transparent black as required by DXT1.
    """
    width = _positive_int(width, "width")
    height = _positive_int(height, "height")
    source = _byte_view(data)
    blocks_w = (width + 3) // 4
    blocks_h = (height + 3) // 4
    expected = blocks_w * blocks_h * _BLOCK_BYTES
    if len(source) != expected:
        raise ValueError(f"BC1 data must be exactly {expected} bytes for {width}x{height}; got {len(source)}")

    output = bytearray(width * height * 4)
    for by in range(blocks_h):
        for bx in range(blocks_w):
            offset = (by * blocks_w + bx) * _BLOCK_BYTES
            palette, indices = _bc1_palette(source[offset:offset + _BLOCK_BYTES])
            for py in range(_TEXELS_PER_BLOCK):
                y = by * _TEXELS_PER_BLOCK + py
                if y >= height:
                    break
                for px in range(_TEXELS_PER_BLOCK):
                    x = bx * _TEXELS_PER_BLOCK + px
                    if x >= width:
                        break
                    code = (indices >> (2 * (py * _TEXELS_PER_BLOCK + px))) & 3
                    target = (y * width + x) * 4
                    output[target:target + 4] = bytes(palette[code])
    return bytes(output)


def _bc3_alpha_palette(block):
    alpha0, alpha1 = block[0], block[1]
    palette = [alpha0, alpha1]
    if alpha0 > alpha1:
        palette.extend(((7 - index) * alpha0 + index * alpha1) // 7 for index in range(1, 7))
    else:
        palette.extend(((5 - index) * alpha0 + index * alpha1) // 5 for index in range(1, 5))
        palette.extend((0, 255))
    return palette, int.from_bytes(block[2:8], "little")


def decode_bc3(data, width, height):
    """Decode tightly packed BC3/DXT5 blocks to top-down RGBA8."""
    width = _positive_int(width, "width")
    height = _positive_int(height, "height")
    source = _byte_view(data)
    blocks_w = (width + 3) // 4
    blocks_h = (height + 3) // 4
    expected = blocks_w * blocks_h * 16
    if len(source) != expected:
        raise ValueError(f"BC3 data must be exactly {expected} bytes for {width}x{height}; got {len(source)}")

    output = bytearray(width * height * 4)
    for by in range(blocks_h):
        for bx in range(blocks_w):
            offset = (by * blocks_w + bx) * 16
            alpha_palette, alpha_indices = _bc3_alpha_palette(source[offset:offset + 8])
            color_palette, color_indices = _bc1_palette(source[offset + 8:offset + 16], force_four_color=True)
            for py in range(_TEXELS_PER_BLOCK):
                y = by * _TEXELS_PER_BLOCK + py
                if y >= height:
                    break
                for px in range(_TEXELS_PER_BLOCK):
                    x = bx * _TEXELS_PER_BLOCK + px
                    if x >= width:
                        break
                    pixel = py * _TEXELS_PER_BLOCK + px
                    color = color_palette[(color_indices >> (2 * pixel)) & 3]
                    alpha = alpha_palette[(alpha_indices >> (3 * pixel)) & 7]
                    target = (y * width + x) * 4
                    output[target:target + 4] = bytes((color[0], color[1], color[2], alpha))
    return bytes(output)


def _bc4_snorm_palette(block):
    """Decode the signed endpoint table and packed indices of one BC4 block."""
    endpoint0 = int.from_bytes(block[0:1], "little", signed=True)
    endpoint1 = int.from_bytes(block[1:2], "little", signed=True)
    if endpoint0 == -127 and endpoint1 == -128:
        raise ValueError("BC4 SNORM endpoint order (-127, -128) is implementation-dependent")
    red0 = -1.0 if endpoint0 == -128 else endpoint0 / 127.0
    red1 = -1.0 if endpoint1 == -128 else endpoint1 / 127.0
    palette = [red0, red1]
    if endpoint0 > endpoint1:
        palette.extend(((7 - index) * red0 + index * red1) / 7.0
                       for index in range(1, 7))
    else:
        palette.extend(((5 - index) * red0 + index * red1) / 5.0
                       for index in range(1, 5))
        palette.extend((-1.0, 1.0))
    return palette, int.from_bytes(block[2:8], "little")


def decode_bc5_snorm(data, width, height):
    """Decode BC5 SNORM to diagnostic RGBA8 channel visualization.

    R and G contain the two signed BC4 channels remapped to [0, 255]. Blue is
    neutral gray and alpha is opaque. This does not reconstruct Z or apply
    tangent-space lighting; those interpretations need verified channel
    orientation, vertex tangents and game material state.
    """
    width = _positive_int(width, "width")
    height = _positive_int(height, "height")
    source = _byte_view(data)
    blocks_w = (width + 3) // 4
    blocks_h = (height + 3) // 4
    expected = blocks_w * blocks_h * 16
    if len(source) != expected:
        raise ValueError(f"BC5 SNORM data must be exactly {expected} bytes for {width}x{height}; got {len(source)}")

    output = bytearray(width * height * 4)
    for by in range(blocks_h):
        for bx in range(blocks_w):
            offset = (by * blocks_w + bx) * 16
            red_palette, red_indices = _bc4_snorm_palette(source[offset:offset + 8])
            green_palette, green_indices = _bc4_snorm_palette(source[offset + 8:offset + 16])
            for py in range(_TEXELS_PER_BLOCK):
                y = by * _TEXELS_PER_BLOCK + py
                if y >= height:
                    break
                for px in range(_TEXELS_PER_BLOCK):
                    x = bx * _TEXELS_PER_BLOCK + px
                    if x >= width:
                        break
                    pixel = py * _TEXELS_PER_BLOCK + px
                    red = red_palette[(red_indices >> (3 * pixel)) & 7]
                    green = green_palette[(green_indices >> (3 * pixel)) & 7]
                    r8 = max(0, min(255, int((red + 1.0) * 127.5 + 0.5)))
                    g8 = max(0, min(255, int((green + 1.0) * 127.5 + 0.5)))
                    target = (y * width + x) * 4
                    output[target:target + 4] = bytes((r8, g8, 128, 255))
    return bytes(output)


def _bc1_thin1_block_offset(x, y, pitch, swizzle):
    """Port the pinned GX2 macro-tile address for one compressed BC1 block."""
    # 64 bpp here means one 8-byte BC1 block on the block grid. GX2's
    # microtile bit order is the 64-bpp branch in computePixelIndexWithinMicroTile.
    pixel_index = ((y & 1) << 1) | (x & 1)
    pixel_index |= ((x & 2) >> 1) << 2
    pixel_index |= ((x & 4) >> 2) << 3
    pixel_index |= ((y & 2) >> 1) << 4
    pixel_index |= ((y & 4) >> 2) << 5
    elem_offset = pixel_index * _BLOCK_BYTES

    pipe = ((y >> 3) ^ (x >> 3)) & 1
    bank = (((y >> 5) ^ (x >> 3)) & 1) | (2 * (((y >> 4) ^ (x >> 4)) & 1))
    pipe_swizzle = (swizzle >> 8) & 1
    bank_swizzle = (swizzle >> 9) & 3
    bank_pipe = (pipe + 2 * bank) ^ (pipe_swizzle + 2 * bank_swizzle)
    bank_pipe %= 8
    pipe = bank_pipe % 2
    bank = bank_pipe // 2

    macro_tiles_per_row = pitch // _THIN1_MACRO_WIDTH_BLOCKS
    macro_tile_index_x = x // _THIN1_MACRO_WIDTH_BLOCKS
    macro_tile_index_y = y // _THIN1_MACRO_HEIGHT_BLOCKS
    macro_tile_offset = (macro_tile_index_x + macro_tiles_per_row * macro_tile_index_y) * _THIN1_MACRO_BYTES
    total_offset = elem_offset + (macro_tile_offset >> 3)
    return (bank << 9) | (pipe << 8) | (total_offset & 0xFF) | ((total_offset & ~0xFF) << 3)


def _bc3_thin1_block_offset(x, y, pitch, swizzle):
    """Return the shared 128-bpp GX2 Thin1 address used by BC3 and BC5."""
    # GX2's explicit 128-bpp branch orders y0, x0, x1, x2, y1, y2.
    pixel_index = ((y & 1) | ((x & 1) << 1) | (((x & 2) >> 1) << 2) |
                   (((x & 4) >> 2) << 3) | (((y & 2) >> 1) << 4) |
                   (((y & 4) >> 2) << 5))
    elem_offset = pixel_index * 16

    pipe = ((y >> 3) ^ (x >> 3)) & 1
    bank = (((y >> 5) ^ (x >> 3)) & 1) | (2 * (((y >> 4) ^ (x >> 4)) & 1))
    pipe_swizzle = (swizzle >> 8) & 1
    bank_swizzle = (swizzle >> 9) & 3
    bank_pipe = (pipe + 2 * bank) ^ (pipe_swizzle + 2 * bank_swizzle)
    bank_pipe %= 8
    pipe = bank_pipe % 2
    bank = bank_pipe // 2

    macro_tiles_per_row = pitch // _THIN1_MACRO_WIDTH_BLOCKS
    macro_tile_index_x = x // _THIN1_MACRO_WIDTH_BLOCKS
    macro_tile_index_y = y // _THIN1_MACRO_HEIGHT_BLOCKS
    macro_tile_offset = (macro_tile_index_x + macro_tiles_per_row * macro_tile_index_y) * (
        _THIN1_MACRO_WIDTH_BLOCKS * _THIN1_MACRO_HEIGHT_BLOCKS * 16)
    total_offset = elem_offset + (macro_tile_offset >> 3)
    return (bank << 9) | (pipe << 8) | (total_offset & 0xFF) | ((total_offset & ~0xFF) << 3)


def detile_bc1_thin1(
    data,
    width,
    height,
    pitch,
    *,
    tile_mode=4,
    swizzle=0,
    dimension=1,
    depth=1,
    aa=0,
):
    """Return compact row-major BC1 data from GX2 2D Thin1 storage.

    ``width`` and ``height`` are texels; ``pitch`` is the GX2 surface pitch in
    compressed 4x4 blocks, matching ``surfaceOut.pitch`` for BC1. The data must
    be exactly one padded mip level. GX2 dimension 1 means 2D, and only a
    single sample/layer is supported. The source stores pipe/bank swizzle in
    bits 8 and 9..10; the local BFRES 0x20000 marker is accepted as inert
    metadata because the reference address function does not consume it.
    """
    return _detile_bc_thin1(data, width, height, pitch, 8, tile_mode=tile_mode,
                            swizzle=swizzle, dimension=dimension, depth=depth, aa=aa)


def detile_bc3_thin1(
    data,
    width,
    height,
    pitch,
    *,
    tile_mode=4,
    swizzle=0,
    dimension=1,
    depth=1,
    aa=0,
):
    """Return compact row-major BC3 data from GX2 2D Thin1 storage."""
    return _detile_bc_thin1(data, width, height, pitch, 16, tile_mode=tile_mode,
                            swizzle=swizzle, dimension=dimension, depth=depth, aa=aa)


def detile_bc5_snorm_thin1(
    data,
    width,
    height,
    pitch,
    *,
    tile_mode=4,
    swizzle=0,
    dimension=1,
    depth=1,
    aa=0,
):
    """Return compact row-major BC5 SNORM data from GX2 2D Thin1 storage."""
    return _detile_bc_thin1(data, width, height, pitch, 16, tile_mode=tile_mode,
                            swizzle=swizzle, dimension=dimension, depth=depth, aa=aa)


def _detile_bc_thin1(data, width, height, pitch, block_bytes, *, tile_mode, swizzle,
                     dimension, depth, aa):
    width = _positive_int(width, "width")
    height = _positive_int(height, "height")
    pitch = _positive_int(pitch, "pitch")
    if type(tile_mode) is not int or tile_mode != 4:
        raise ValueError("Only GX2 2D Thin1 textures (tileMode 4) are supported")
    if type(dimension) is not int or dimension != 1:
        raise ValueError("Only GX2 2D surfaces (dimension 1) are supported")
    if type(depth) is not int or depth != 1:
        raise ValueError("Only single-layer BC surfaces (depth 1) are supported")
    if type(aa) is not int or aa != 0:
        raise ValueError("Multisampled BC surfaces are unsupported")
    if type(swizzle) is not int or swizzle < 0 or swizzle > 0xFFFFFFFF:
        raise ValueError("swizzle must be an unsigned 32-bit GX2 value")
    if swizzle & ~_KNOWN_SWIZZLE_MASK:
        raise ValueError(f"Unsupported GX2 swizzle bits: 0x{swizzle & ~_KNOWN_SWIZZLE_MASK:X}")

    source = _byte_view(data)
    blocks_w = (width + 3) // 4
    blocks_h = (height + 3) // 4
    if pitch < blocks_w:
        raise ValueError(f"GX2 block pitch {pitch} is smaller than texture block width {blocks_w}")
    if pitch % _THIN1_MACRO_WIDTH_BLOCKS:
        raise ValueError("GX2 Thin1 block pitch must be a multiple of 32 compressed blocks")
    padded_h = ((blocks_h + _THIN1_MACRO_HEIGHT_BLOCKS - 1) // _THIN1_MACRO_HEIGHT_BLOCKS) * _THIN1_MACRO_HEIGHT_BLOCKS
    expected = pitch * padded_h * block_bytes
    if len(source) != expected:
        raise ValueError(f"GX2 Thin1 data must be exactly {expected} bytes for pitch {pitch} and {padded_h} padded block rows; got {len(source)}")

    output = bytearray(blocks_w * blocks_h * block_bytes)
    for y in range(blocks_h):
        for x in range(blocks_w):
            offset = (_bc1_thin1_block_offset(x, y, pitch, swizzle) if block_bytes == 8 else
                      _bc3_thin1_block_offset(x, y, pitch, swizzle))
            if offset < 0 or offset + block_bytes > len(source):
                raise ValueError(f"GX2 Thin1 address out of bounds at block ({x}, {y}): {offset}")
            source_offset = y * blocks_w * block_bytes + x * block_bytes
            output[source_offset:source_offset + block_bytes] = source[offset:offset + block_bytes]
    return bytes(output)
