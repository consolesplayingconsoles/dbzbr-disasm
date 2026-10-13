#!/usr/bin/env python3
"""DBZ Buyuu Retsuden's own LZSS decompressor, ported from the 68k routine.

Reversed from sub_0017AA / loc_001822 in the DBZ disassembly. DBZ does NOT use
Nemesis (that was a false lead); it uses a custom LZSS with two variants chosen
by bit 15 of the size header:

  header = little-endian word at the start.
    bit 15 clear -> BYTE mode: low 15 bits + 1 = decompressed byte count.
    bit 15 set   -> WORD mode: low 15 bits + 1 = decompressed WORD count.
  then control units, each flagging the next 8 (byte) / 16 (word) symbols:
    bit = 1 -> one literal byte/word, copied verbatim.
    bit = 0 -> a 2-unit back-reference V: length = (V & 0xF) + 3 units,
               distance = V >> 4 units. A distance reaching before the start of
               the output emits zeros (the window is zero-pre-filled).
  BYTE mode reads control bits LSB-first and reference words little-endian;
  WORD mode reads control bits MSB-first and reference words big-endian.

    dbz_lzss.py <rom> <start-hex> [out.bin]      # decompress one stream

As a module: decode(data, ptr) -> (bytes, next_ptr); raises NotLZSS on garbage.
"""
import sys


class NotLZSS(Exception):
    pass


def decode(data, p, max_size=0x8000):
    n = len(data)
    if p + 2 > n:
        raise NotLZSS('truncated header')
    lo, hi = data[p], data[p + 1]
    word_mode = bool(hi & 0x80)
    size = (((hi << 8) | lo) & 0x7FFF) + 1          # units: bytes or words
    p += 2
    start = p
    ceiling = start + size * 2 + 16                 # LZSS never expands much
    out = bytearray()
    unit = 2 if word_mode else 1

    def produced():
        return len(out) // unit

    while produced() < size:
        if p > ceiling or p >= n:
            raise NotLZSS('runaway / truncated')
        if word_mode:
            ctrl = (data[p] << 8) | data[p + 1]; p += 2
            bits = [(ctrl >> (15 - i)) & 1 for i in range(16)]   # MSB first
        else:
            ctrl = data[p]; p += 1
            bits = [(ctrl >> i) & 1 for i in range(8)]           # LSB first
        for bit in bits:
            if produced() >= size:
                break
            if bit:                                  # literal unit
                if p + unit > n:
                    raise NotLZSS('literal past end')
                out += data[p:p + unit]; p += unit
            else:                                    # back-reference
                if p + 2 > n:
                    raise NotLZSS('reference past end')
                if word_mode:
                    V = (data[p] << 8) | data[p + 1]
                else:
                    V = data[p] | (data[p + 1] << 8)
                p += 2
                length = (V & 0x0F) + 3
                dist = V >> 4
                for _ in range(length):
                    if produced() >= size:
                        break
                    src = produced() - dist
                    if src >= 0:
                        out += out[src * unit:src * unit + unit]
                    else:
                        out += b'\x00' * unit
    return bytes(out), p


def scan(data, lo, hi, min_bytes=1024):
    for off in range(lo, hi):
        try:
            out, end = decode(data, off)
        except (NotLZSS, IndexError):
            continue
        if len(out) >= min_bytes and end - off >= 32:
            yield off, len(out), end


def main(argv):
    if argv[1] == '--scan':
        data = bytearray(open(argv[2], 'rb').read())
        for off, sz, end in scan(data, int(argv[3], 16), int(argv[4], 16)):
            print('%06X  %6d bytes out  -> %06X  (%d in)' % (off, sz, end, end - off))
        return
    data = bytearray(open(argv[1], 'rb').read())
    out, end = decode(data, int(argv[2], 16))
    print('%d bytes (%d tiles), stream %06X..%06X' % (len(out), len(out) // 32, int(argv[2], 16), end))
    if len(argv) > 3:
        open(argv[3], 'wb').write(out)
        print('wrote', argv[3])


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv)
