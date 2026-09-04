#!/usr/bin/env python3
"""Decode the game's on-screen text.

Strings are raw VDP tilemap words, one word per glyph, $FFFF terminated. A
stored string is a pre-rendered line: it is padded with spaces to the width of
its text box, so a replacement has to fit the same slot.

There is ONE font, in two blocks:

  uppercase  A..K at $0E5, L..Z at $100          (fixed width)
  lowercase  a..l at $064, m at $080, n..v at $082,
             w at $08B, x..z at $08D             (proportional)

'm' and 'w' are two tiles wide; their second tile ($081, $08C) is a
continuation glyph and decodes to nothing. Move and character names are stored
in the uppercase block. Unmapped tiles print as {XXX}.
"""
import sys, struct

def build(runs, extra):
    m = {}
    for base, first, count in runs:
        for i in range(count):
            m[base + i] = chr(ord(first) + i)
    m.update(extra)
    return m

FONT = build(
    [(0x0E5, 'A', 11), (0x100, 'L', 15),                     # uppercase
     (0x064, 'a', 12), (0x080, 'm', 1), (0x082, 'n', 9),     # lowercase
     (0x08B, 'w', 1), (0x08D, 'x', 3),
     (0x120, '0', 10)],                                      # digits
    {0x081: '', 0x08C: '',            # continuations of the wide m / w
     0x12A: ' ', 0x12C: '.', 0x0E4: '.', 0x16C: "'",
     0x0A0: 'e', 0x0A6: 'i', 0x0AF: '!'})   # accented e / i, and !

# Names are stored uppercase; render them lowercase for readability with -l.
def decode(word, lower=False):
    t = word & 0x7FF
    c = FONT.get(t)
    if c is None:
        return '{%03X}' % t
    return c.lower() if lower else c

def strings(rom, start, end, lower=False):
    out, cur, i, s = [], [], start, start
    while i < end:
        w = struct.unpack_from('>H', rom, i)[0]
        if w == 0xFFFF:
            out.append((s, ''.join(cur))); cur = []; i += 2; s = i; continue
        cur.append(decode(w, lower)); i += 2
    if cur:
        out.append((s, ''.join(cur)))
    return out

if __name__ == '__main__':
    rom = open(sys.argv[1], 'rb').read()
    a, b = int(sys.argv[2], 16), int(sys.argv[3], 16)
    lower = '-l' in sys.argv[4:]
    for off, s in strings(rom, a, b, lower):
        if s.strip():
            print('%06X  %s' % (off, s.rstrip()))
