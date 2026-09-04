#!/usr/bin/env python3
"""Compare the text of two builds, to find what a translation missed.

Walks every $FFFF-terminated glyph run in the reference ROM and decodes the same
address in the other. Flags fields that went blank, or that hold tiles the font
does not cover, which is what a patch leaves behind when it blanks a label
instead of translating it.

    txtdiff.py <reference-rom> <other-rom>
"""
import sys, struct
from text import FONT

def runs(rom, minlen=3):
    """Addresses of glyph runs: at least `minlen` letters, then $FFFF."""
    out, start, n = [], None, 0
    a = 0
    while a < len(rom) - 1:
        w = struct.unpack_from('>H', rom, a)[0]
        if w == 0xFFFF:
            if start is not None and n >= minlen:
                out.append((start, (a - start) // 2))
            start, n = None, 0
        elif FONT.get(w & 0x7FF):
            if start is None:
                start = a
            n += 1
        else:
            start, n = None, 0
        a += 2
    return out

def show(rom, a, width):
    return ''.join(FONT.get(struct.unpack_from('>H', rom, a + 2 * i)[0] & 0x7FF, '?')
                   for i in range(width))

if __name__ == '__main__':
    ref = open(sys.argv[1], 'rb').read()
    other = open(sys.argv[2], 'rb').read()
    bad = []
    for a, width in runs(ref):
        if a + 2 * width > len(other):
            continue
        s_ref, s_other = show(ref, a, width), show(other, a, width)
        if s_ref == s_other:
            continue                       # untranslated or identical, not our concern here
        if '?' in s_other or not s_other.strip():
            bad.append((a, s_ref, s_other))
    print('fields the other ROM blanked or filled with unmapped tiles: %d\n' % len(bad))
    for a, r, o in bad[:40]:
        print('   %06X  %-28r -> %r' % (a, r.strip(), o.strip()))
