#!/usr/bin/env python3
"""Apply an IPS patch. Someone else's hack is often the fastest way to learn
how a thing is done, so being able to run one matters as much as reading it."""
import sys, struct

def apply(rom, patch):
    d = open(patch, 'rb').read()
    if d[:5] != b'PATCH':
        raise SystemExit('%s: not an IPS patch' % patch)
    out, i = bytearray(rom), 5
    while i + 3 <= len(d):
        if d[i:i + 3] == b'EOF':
            break
        off = int.from_bytes(d[i:i + 3], 'big'); i += 3
        size = struct.unpack_from('>H', d, i)[0]; i += 2
        if size == 0:                                   # run-length record
            n = struct.unpack_from('>H', d, i)[0]; b = d[i + 2]; i += 3
            chunk = bytes((b,)) * n
        else:
            chunk = d[i:i + size]; i += size
        if off + len(chunk) > len(out):                 # patches may extend a ROM
            out.extend(b'\x00' * (off + len(chunk) - len(out)))
        out[off:off + len(chunk)] = chunk
    return bytes(out)

if __name__ == '__main__':
    open(sys.argv[3], 'wb').write(apply(open(sys.argv[1], 'rb').read(), sys.argv[2]))
    print('wrote', sys.argv[3])
