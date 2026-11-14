"""Pure-Python TIFF LZW decoder (MSB-first codes, early change), for when imagecodecs is blocked."""
from __future__ import annotations

CLEAR, EOI = 256, 257


def lzw_decode(data: bytes, expected: int | None = None) -> bytes:
    out = bytearray()
    table: list[bytes] = []

    def reset() -> None:
        nonlocal table
        table = [bytes((i,)) for i in range(256)] + [b"", b""]

    reset()
    bits = 9
    buf = 0
    nbuf = 0
    prev: bytes | None = None
    pos = 0
    n = len(data)
    while True:
        while nbuf < bits and pos < n:
            buf = (buf << 8) | data[pos]
            pos += 1
            nbuf += 8
        if nbuf < bits:
            break
        code = (buf >> (nbuf - bits)) & ((1 << bits) - 1)
        nbuf -= bits
        buf &= (1 << nbuf) - 1
        if code == EOI:
            break
        if code == CLEAR:
            reset()
            bits = 9
            prev = None
            continue
        if prev is None:
            if code >= len(table):
                raise ValueError("corrupt LZW stream (first code)")
            entry = table[code]
        else:
            if code < len(table):
                entry = table[code]
                table.append(prev + entry[:1])
            elif code == len(table):
                entry = prev + prev[:1]
                table.append(entry)
            else:
                raise ValueError("corrupt LZW stream (bad code)")
        out += entry
        prev = entry
        size = len(table)
        # TIFF "early change": widen one code before the table is actually full
        if size >= 2047:
            bits = 12
        elif size >= 1023:
            bits = 11
        elif size >= 511:
            bits = 10
        if expected is not None and len(out) >= expected:
            break
    return bytes(out)


def lzw_encode(data: bytes) -> bytes:
    """Reference encoder used only by tests (TIFF LZW, early change)."""
    out = bytearray()
    buf = 0
    nbuf = 0

    def put(code: int, bits: int) -> None:
        nonlocal buf, nbuf
        buf = (buf << bits) | code
        nbuf += bits
        while nbuf >= 8:
            out.append((buf >> (nbuf - 8)) & 0xFF)
            nbuf -= 8
        buf &= (1 << nbuf) - 1

    def fresh() -> dict[bytes, int]:
        return {bytes((i,)): i for i in range(256)}

    table = fresh()
    next_code = 258
    bits = 9
    put(CLEAR, bits)
    w = b""
    for byte in data:
        wc = w + bytes((byte,))
        if wc in table:
            w = wc
            continue
        put(table[w], bits)
        table[wc] = next_code
        next_code += 1
        if next_code >= 4094:
            put(CLEAR, bits)
            table = fresh()
            next_code = 258
            bits = 9
        elif next_code >= 2048:   # entry 2047 added -> next code 12 bits (decoder lags one entry)
            bits = 12
        elif next_code >= 1024:
            bits = 11
        elif next_code >= 512:
            bits = 10
        w = bytes((byte,))
    if w:
        put(table[w], bits)
    put(EOI, bits)
    if nbuf:
        out.append((buf << (8 - nbuf)) & 0xFF)
    return bytes(out)
