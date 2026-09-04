#!/usr/bin/env python3
"""Sweep a ROM for tilemap text and cluster the hits into labelled regions."""
import sys, struct
sys.path.insert(0, 'tools')
from text import FONT

ROM = open(sys.argv[1], 'rb').read()
N = len(ROM)
MINLEN = int(sys.argv[2]) if len(sys.argv) > 2 else 4

def sweep():
    m = FONT
    hits, cur, start = [], [], None
    i = 0
    while i + 1 < N:
        w = struct.unpack_from('>H', ROM, i)[0] & 0x7FF
        c = m.get(w)
        if c is not None:
            if start is None: start = i
            cur.append(c)
        else:
            if start is not None and len(cur) >= MINLEN and ''.join(cur).strip():
                hits.append((start, ''.join(cur)))
            cur, start = [], None
        i += 2
    return hits

def clusters(hits, gap=0x400):
    out = []
    for off, s in hits:
        if out and off - out[-1][1] < gap:
            out[-1][1] = off + 2 * len(s)
            out[-1][2].append(s)
            out[-1][3] += len(s)
        else:
            out.append([off, off + 2 * len(s), [s], len(s)])
    return out

if True:
    cs = [c for c in clusters(sweep()) if c[3] >= 40]
    print('==== %d text clusters ====' % len(cs))
    for s, e, strs, n in cs:
        sample = ' | '.join(x.strip() for x in strs if x.strip())[:150]
        print('%06X-%06X %6dB %5d glyphs  %s' % (s, e, e - s, n, sample))
    print()
