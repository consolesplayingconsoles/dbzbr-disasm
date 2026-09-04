#!/usr/bin/env python3
"""Read and write the fighter palettes.

Two banks of 12 palettes, 16 colours each, 32 bytes per palette:
  bank A  $080064   normal
  bank B  $0801E4   used only when both players pick the same fighter
A Mega Drive colour word is 0000 BBB0 GGG0 RRR0, so each channel is 0..14 even.
"""
import sys, struct

BANK_A, BANK_B, STRIDE, SLOTS = 0x080064, 0x0801E4, 0x20, 12

def to_rgb(w):
    r = (w & 0x00E) >> 1; g = (w & 0x0E0) >> 5; b = (w & 0xE00) >> 9
    return tuple(round(c * 255 / 7) for c in (r, g, b))

def from_rgb(r, g, b):
    q = lambda c: min(7, max(0, round(c * 7 / 255)))
    return (q(b) << 9) | (q(g) << 5) | (q(r) << 1)

def read_pal(rom, base, slot):
    a = base + STRIDE * slot
    return [struct.unpack_from('>H', rom, a + 2 * i)[0] for i in range(16)]

if __name__ == '__main__':
    rom = open(sys.argv[1], 'rb').read()
    slot = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    for tag, base in (('A', BANK_A), ('B', BANK_B)):
        pal = read_pal(rom, base, slot)
        print('bank %s slot %d  @%06X' % (tag, slot, base + STRIDE * slot))
        for i, w in enumerate(pal):
            r, g, b = to_rgb(w)
            print('   %2d  %04X  #%02X%02X%02X' % (i, w, r, g, b))
