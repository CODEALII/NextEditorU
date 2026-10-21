"""Small, strict decoders for BC1 textures and one verified GX2 layout.

The Thin1 address calculation is based on the pinned source
``external/BfresLibrary/BfresLibrary/WiiU/Texture/GX2/GX2.cs`` at commit
``65c005275deed1e085069e72fea523247f955b87``. It ports the BCn block-grid
handling in ``swizzleSurf``, BC1's 64-bit block indexing in
``computePixelIndexWithinMicroTile``, and the 2D macro-tiled address path in
``computeSurfaceAddrFromCoordMacroTiled``. This module supports only single
sample, single-layer GX2 2D Thin1 (tileMode 4) BC1 levels.
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


def _bc1_palette(block):
    color0 = block[0] | (block[1] << 8)
    color1 = block[2] | (block[3] << 8)
    c0 = _rgb565(color0)
    c1 = _rgb565(color1)
    palette = [(*c0, 255), (*c1, 255)]
    if color0 > color1:
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
    bits 8 and 9..10; the pinned BfresLibrary's 0xD0000 marker is accepted as
    inert metadata because the reference address function does not consume it.
    """
    width = _positive_int(width, "width")
    height = _positive_int(height, "height")
    pitch = _positive_int(pitch, "pitch")
    if type(tile_mode) is not int or tile_mode != 4:
        raise ValueError("Only GX2 2D Thin1 textures (tileMode 4) are supported")
    if type(dimension) is not int or dimension != 1:
        raise ValueError("Only GX2 2D surfaces (dimension 1) are supported")
    if type(depth) is not int or depth != 1:
        raise ValueError("Only single-layer BC1 surfaces (depth 1) are supported")
    if type(aa) is not int or aa != 0:
        raise ValueError("Multisampled BC1 surfaces are unsupported")
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
        raise ValueError("GX2 Thin1 BC1 pitch must be a multiple of 32 compressed blocks")
    padded_h = ((blocks_h + _THIN1_MACRO_HEIGHT_BLOCKS - 1) // _THIN1_MACRO_HEIGHT_BLOCKS) * _THIN1_MACRO_HEIGHT_BLOCKS
    expected = pitch * padded_h * _BLOCK_BYTES
    if len(source) != expected:
        raise ValueError(f"GX2 Thin1 data must be exactly {expected} bytes for pitch {pitch} and {padded_h} padded block rows; got {len(source)}")

    output = bytearray(blocks_w * blocks_h * _BLOCK_BYTES)
    for y in range(blocks_h):
        for x in range(blocks_w):
            offset = _bc1_thin1_block_offset(x, y, pitch, swizzle)
            if offset < 0 or offset + _BLOCK_BYTES > len(source):
                raise ValueError(f"GX2 Thin1 address out of bounds at block ({x}, {y}): {offset}")
            source_offset = y * blocks_w * _BLOCK_BYTES + x * _BLOCK_BYTES
            output[source_offset:source_offset + _BLOCK_BYTES] = source[offset:offset + _BLOCK_BYTES]
    return bytes(output)
