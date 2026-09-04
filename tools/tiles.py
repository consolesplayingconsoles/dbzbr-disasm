#!/usr/bin/env python3
"""Render a ROM range as Mega Drive 4bpp tiles, so art can be looked at.

Each tile is 8x8 pixels, two pixels per byte, 32 bytes. Written as a greyscale
PNG with no external libraries.

    tiles.py <rom> <start-hex> <tiles> <out.png> [tiles-per-row]
"""
import sys, zlib, struct

def png(path, w, h, pixels):
    raw = b''.join(b'\x00' + bytes(pixels[y * w:(y + 1) * w]) for y in range(h))
    def chunk(tag, data):
        c = tag + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c))
    open(path, 'wb').write(
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 0, 0, 0, 0))
        + chunk(b'IDAT', zlib.compress(raw))
        + chunk(b'IEND', b''))

def render(rom, start, count, per_row):
    rows = (count + per_row - 1) // per_row
    w, h = per_row * 8, rows * 8
    px = bytearray(w * h)
    for t in range(count):
        base = start + 32 * t
        tx, ty = (t % per_row) * 8, (t // per_row) * 8
        for y in range(8):
            for x in range(0, 8, 2):
                b = rom[base + y * 4 + x // 2]
                for k, v in ((0, b >> 4), (1, b & 15)):
                    px[(ty + y) * w + tx + x + k] = v * 17
    return w, h, px

if __name__ == '__main__':
    rom = open(sys.argv[1], 'rb').read()
    start, count = int(sys.argv[2], 16), int(sys.argv[3])
    per_row = int(sys.argv[5]) if len(sys.argv) > 5 else 32
    png(sys.argv[4], *render(rom, start, count, per_row))
    print('%s: %d tiles from %06X' % (sys.argv[4], count, start))
