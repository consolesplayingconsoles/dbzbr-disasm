#!/usr/bin/env python3
"""Summarise which ROM regions an IPS patch touches.

Someone else's hack is a labelled dataset: the offsets a sprite hack writes to
are where the sprites are. Prints merged regions, biggest first.
"""
import sys, struct

def records(path):
    d = open(path, 'rb').read()
    if d[:5] != b'PATCH':
        raise SystemExit('%s: not an IPS patch' % path)
    i, out = 5, []
    while i + 3 <= len(d):
        if d[i:i + 3] == b'EOF':
            break
        off = int.from_bytes(d[i:i + 3], 'big'); i += 3
        size = struct.unpack_from('>H', d, i)[0]; i += 2
        if size == 0:                       # run-length record
            n = struct.unpack_from('>H', d, i)[0]; i += 3
            out.append((off, n))
        else:
            out.append((off, size)); i += size
    return out

def merge(recs, gap=0x200):
    out = []
    for off, n in sorted(recs):
        if out and off - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], off + n)
        else:
            out.append([off, off + n])
    return out

for path in sys.argv[1:]:
    recs = records(path)
    total = sum(n for _, n in recs)
    regions = merge(recs)
    name = path.rsplit('/', 1)[-1]
    print('== %s' % name)
    print('   %d records, %d bytes changed, %d regions' % (len(recs), total, len(regions)))
    for s, e in sorted(regions, key=lambda r: r[0] - r[1])[:10]:
        print('      %06X-%06X %8d' % (s, e - 1, e - s))
    print()
