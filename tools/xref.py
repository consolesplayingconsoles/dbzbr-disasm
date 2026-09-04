#!/usr/bin/env python3
"""Find self-relative word entries that point at an address.

The engine addresses both code and data the same way: a signed word whose own
address plus its value gives the target. So `who points at X?` is a scan.
"""
import sys, struct
ROM = open(sys.argv[1], 'rb').read(); N = len(ROM)
target = int(sys.argv[2], 16)
lo = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0
hi = int(sys.argv[4], 16) if len(sys.argv) > 4 else N
for a in range(lo, min(hi, N) - 1, 2):
    d = struct.unpack_from('>h', ROM, a)[0]
    if a + d == target:
        print('%06X  word %+05X' % (a, d))
