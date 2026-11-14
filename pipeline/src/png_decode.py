"""Minimal stdlib PNG decoder -> rows of (R, G, B, A) 8-bit tuples.

Supports non-interlaced PNGs: grayscale, RGB, palette (with tRNS), gray+alpha, RGBA.
Bit depth 8 for all types; 1/2/4 also for palette and grayscale.
"""
from __future__ import annotations

import struct
import zlib

PNG_SIG = b"\x89PNG\r\n\x1a\n"
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _unfilter(ftype: int, line: bytearray, prev: bytes, bpp: int) -> None:
    if ftype == 0:
        return
    for x in range(len(line)):
        a = line[x - bpp] if x >= bpp else 0
        b = prev[x]
        c = prev[x - bpp] if x >= bpp else 0
        if ftype == 1:
            line[x] = (line[x] + a) & 0xFF
        elif ftype == 2:
            line[x] = (line[x] + b) & 0xFF
        elif ftype == 3:
            line[x] = (line[x] + ((a + b) >> 1)) & 0xFF
        elif ftype == 4:
            line[x] = (line[x] + _paeth(a, b, c)) & 0xFF
        else:
            raise ValueError(f"unknown PNG filter type {ftype}")


def _samples(line: bytes, width: int, bit_depth: int, channels: int) -> list[int]:
    if bit_depth == 8:
        return list(line[: width * channels])
    out: list[int] = []
    mask = (1 << bit_depth) - 1
    per_byte = 8 // bit_depth
    for byte in line:
        for k in range(per_byte):
            out.append((byte >> (8 - bit_depth * (k + 1))) & mask)
    return out[: width * channels]


def read_png(data: bytes) -> tuple[int, int, list[list[tuple[int, int, int, int]]]]:
    if data[:8] != PNG_SIG:
        raise ValueError("not a PNG (server may have returned an XML error)")
    pos = 8
    idat: list[bytes] = []
    palette: list[tuple[int, int, int]] | None = None
    trns: bytes | None = None
    ihdr = None
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", chunk)
        elif ctype == b"PLTE":
            palette = [tuple(chunk[i:i + 3]) for i in range(0, len(chunk), 3)]  # type: ignore[misc]
        elif ctype == b"tRNS":
            trns = chunk
        elif ctype == b"IDAT":
            idat.append(chunk)
        elif ctype == b"IEND":
            break
    if ihdr is None:
        raise ValueError("PNG without IHDR")
    width, height, bit_depth, color_type, _comp, _filt, interlace = ihdr
    if interlace:
        raise ValueError("interlaced PNG not supported")
    if color_type not in _CHANNELS:
        raise ValueError(f"unsupported color type {color_type}")
    if bit_depth != 8 and not (color_type in (0, 3) and bit_depth in (1, 2, 4)):
        raise ValueError(f"unsupported bit depth {bit_depth} for color type {color_type}")
    if color_type == 3 and palette is None:
        raise ValueError("palette PNG without PLTE")

    channels = _CHANNELS[color_type]
    bits_pp = channels * bit_depth
    stride = (width * bits_pp + 7) // 8
    bpp = max(1, bits_pp // 8)
    raw = zlib.decompress(b"".join(idat))

    gray_scale = 255 // ((1 << bit_depth) - 1)
    trns_gray = struct.unpack(">H", trns[:2])[0] if (trns and color_type == 0) else None
    trns_rgb = struct.unpack(">HHH", trns[:6]) if (trns and color_type == 2) else None

    rows: list[list[tuple[int, int, int, int]]] = []
    prev = bytes(stride)
    i = 0
    for _ in range(height):
        ftype = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        _unfilter(ftype, line, prev, bpp)
        prev = bytes(line)
        s = _samples(line, width, bit_depth, channels)
        row: list[tuple[int, int, int, int]] = []
        for x in range(width):
            if color_type == 6:
                r, g, b, a = s[4 * x:4 * x + 4]
            elif color_type == 2:
                r, g, b = s[3 * x:3 * x + 3]
                a = 0 if trns_rgb == (r, g, b) else 255
            elif color_type == 3:
                idx = s[x]
                r, g, b = palette[idx]  # type: ignore[index]
                a = trns[idx] if (trns and idx < len(trns)) else 255
            elif color_type == 4:
                r = g = b = s[2 * x]
                a = s[2 * x + 1]
            else:  # 0
                v = s[x]
                a = 0 if trns_gray == v else 255
                r = g = b = v * gray_scale
            row.append((r, g, b, a))
        rows.append(row)
    return width, height, rows
