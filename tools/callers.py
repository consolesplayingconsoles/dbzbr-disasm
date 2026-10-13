#!/usr/bin/env python3
"""Who references an address: every traced instruction whose operand names it.

    callers.py <rom> <trace.json> <hex address> [...]

Reads the trace's instruction starts and decodes each one: branches and calls, PC-relative
operands, absolute operands (RAM through its sign-extended short form too) and immediates.
Self-relative word tables are another way in: scripts/xref.py finds those.
"""
import json, re, sys
import capstone as cs

ROM = open(sys.argv[1], 'rb').read()
tr = json.load(open(sys.argv[2]))
want = {int(a, 16) & 0xFFFFFF for a in sys.argv[3:]}
md = cs.Cs(cs.CS_ARCH_M68K, cs.CS_MODE_M68K_000 + cs.CS_MODE_BIG_ENDIAN)
starts = tr['starts'] if 'starts' in tr else [p for s, e in tr['code_ranges'] for p in range(s, e, 2)]
NUM = re.compile(r'\$([0-9a-f]+)(?:\.([wl]))?')
for p in sorted(set(starts)):
    i = next(md.disasm(ROM[p:p + 10], p, 1), None)
    if i is None:
        continue
    for x in NUM.finditer(i.op_str):
        v = int(x.group(1), 16)
        if x.group(2) == 'w' and v >= 0x8000:
            v |= 0xFF0000
        if v & 0xFFFFFF in want:
            print('%06X  %-8s %s' % (p, i.mnemonic, i.op_str))
            break
