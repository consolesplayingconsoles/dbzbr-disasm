#!/usr/bin/env python3
"""Write an IPS patch from a base ROM to a modified one.

A patch is what gets shared: it carries only our own changes, never anyone
else's ROM or translation.

    ips_make.py <base> <modified> <out.ips>
"""
import sys, struct

def make(base, mod):
    if len(mod) < len(base):
        raise SystemExit('modified ROM is smaller than the base')
    out = bytearray(b'PATCH')
    i = 0
    while i < len(mod):
        if i < len(base) and base[i] == mod[i]:
            i += 1
            continue
        start = i
        same = 0
        while i < len(mod) and same < 8:        # close a record after a short run of equal bytes
            same = same + 1 if (i < len(base) and base[i] == mod[i]) else 0
            i += 1
        end = i - same
        chunk = mod[start:end]
        while chunk:                            # IPS records cap at 65535 bytes
            piece, chunk = chunk[:0xFFFF], chunk[0xFFFF:]
            if start == 0x454F46:               # "EOF" cannot be an offset
                start -= 1
                piece = mod[start:start + len(piece) + 1]
            out += start.to_bytes(3, 'big') + struct.pack('>H', len(piece)) + piece
            start += len(piece)
    return bytes(out + b'EOF')

if __name__ == '__main__':
    b = open(sys.argv[1], 'rb').read()
    m = open(sys.argv[2], 'rb').read()
    p = make(b, m)
    open(sys.argv[3], 'wb').write(p)
    print('%s: %d bytes' % (sys.argv[3], len(p)))
