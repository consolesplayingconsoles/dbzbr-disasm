#!/usr/bin/env python3
"""Emit a labelled, symbolised 68k listing from a trace."""
import sys, json, re, struct
from collections import defaultdict
from capstone import *
from facts import NAMES          # what is known gets its name in the listing

ROM = open(sys.argv[1], 'rb').read(); END = len(ROM)
tr  = json.load(open(sys.argv[2]))
OUT = sys.argv[3]

md = Cs(CS_ARCH_M68K, CS_MODE_BIG_ENDIAN | CS_MODE_M68K_000)
labels  = {int(k, 16): v for k, v in tr['labels'].items()}
starts  = sorted(tr['starts'])
tables  = {int(k, 16): v for k, v in tr.get('tables', {}).items()}
ptables = {int(k, 16): v for k, v in tr.get('ptables', {}).items()}
drefs   = {int(k, 16): v for k, v in tr.get('datarefs', {}).items()}

HW = {0xA10000: 'IO_VERSION', 0xA10002: 'IO_DATA1', 0xA10004: 'IO_DATA2', 0xA10008: 'IO_CTRL1',
      0xA1000A: 'IO_CTRL2', 0xA1000C: 'IO_CTRL3', 0xA11100: 'Z80_BUSREQ', 0xA11200: 'Z80_RESET',
      0xC00000: 'VDP_DATA', 0xC00004: 'VDP_CTRL', 0xC00008: 'VDP_HV', 0xA00000: 'Z80_RAM'}

def lname(a):
    if a in NAMES: return NAMES[a]
    k = labels.get(a, 'loc')
    p = {'sub': 'sub', 'loc': 'loc', 'jt': 'jt', 'mode': 'mode', 'table': 'tbl',
         'ptrtable': 'ptr', 'bad': 'bad'}.get(k, 'vec' if k.startswith('vector') else 'loc')
    return '%s_%06X' % (p, a)

def sym(a, short):
    if a in HW: return HW[a]
    if a in NAMES: return NAMES[a]
    if a >= 0xFF0000 or short and a >= 0xFFFF00 - 0: pass
    if a >= 0xFF0000: return 'ram_%04X' % (a & 0xFFFF)
    if a in labels: return lname(a)
    if 0x200 <= a < END: return 'off_%06X' % a
    return None

ABSL = re.compile(r'\$([0-9a-f]+)\.l\b')
ABSW = re.compile(r'\$([0-9a-f]+)\.w\b')
PCR  = re.compile(r'\$([0-9a-f]+)\(pc\)')
PCIX = re.compile(r'\$([0-9a-f]+)\(pc,')
BARE = re.compile(r'(?<![\w$])\$([0-9a-f]+)(?![\w.(])')

def symbolise(mnem, ops):
    def absl(m):
        s = sym(int(m.group(1), 16), False)
        return (s + '.l') if s else m.group(0)
    def absw(m):
        v = int(m.group(1), 16)
        v = (0xFF0000 | v) if v >= 0x8000 else v
        s = sym(v, True)
        return (s + '.w') if s else m.group(0)
    def pcr(m):
        s = sym(int(m.group(1), 16), False)
        return (s + '(pc)') if s else m.group(0)
    def pcix(m):
        s = sym(int(m.group(1), 16), False)
        return (s + '(pc,') if s else m.group(0)
    def bare(m):
        a = int(m.group(1), 16)
        return lname(a) if a in labels else m.group(0)
    ops = ABSL.sub(absl, ops); ops = ABSW.sub(absw, ops)
    ops = PCIX.sub(pcix, ops); ops = PCR.sub(pcr, ops)
    if mnem[0] in 'bd':                       # branches / dbra
        ops = BARE.sub(bare, ops)
    return ops

# incoming xrefs, computed from the trace's own branch decisions
xref = defaultdict(set)
for pc in starts:
    ins = next(md.disasm(ROM[pc:pc + 16], pc, count=1), None)
    if ins is None: continue
    for m in list(BARE.finditer(ins.op_str)) + list(ABSL.finditer(ins.op_str)):
        a = int(m.group(1), 16)
        if a in labels: xref[a].add(pc)

with open(OUT, 'w') as out:
    out.write("; Dragon Ball Z - L'Appel du Destin (Mega Drive) — traced disassembly\n")
    out.write('; %d instructions, %d labels, %d dispatch tables\n'
              % (len(starts), len(labels), len(tables) + len(ptables)))
    out.write('; ram_XXXX = work RAM $FFxxxx.  Untraced ranges are marked inline.\n\n')
    prev_end = None
    for pc in starts:
        ins = next(md.disasm(ROM[pc:pc + 16], pc, count=1), None)
        if ins is None: continue
        if prev_end is not None and pc != prev_end:
            out.write('\n; ======== untraced %06X-%06X (%d bytes: data, art or unfound code) ========\n\n'
                      % (prev_end, pc - 1, pc - prev_end))
        if pc in labels:
            if labels[pc] in ('sub', 'mode', 'table', 'ptrtable'):
                out.write('\n')
            refs = sorted(xref.get(pc, ()))
            if refs:
                out.write('; xrefs: %s%s\n' % (', '.join('%06X' % r for r in refs[:8]),
                                               ' ...' if len(refs) > 8 else ''))
            out.write('%s:\n' % lname(pc))
        out.write('    %-9s %-40s ; %06X\n' % (ins.mnemonic, symbolise(ins.mnemonic, ins.op_str), pc))
        prev_end = pc + ins.size
print('wrote', OUT)

# --- structure map --------------------------------------------------------
with open(OUT.rsplit('.', 1)[0] + '-MAP.md', 'w') as m:
    m.write('# ROM structure map\n\n## Game-mode dispatch\n\n')
    m.write('`ram_E6A4` holds the game mode; `jsr $45e(pc,d0.w)` at 000420 dispatches it.\n\n')
    for b, n in sorted(tables.items()):
        m.write('- bra.w table `%06X`, %d slots\n' % (b, n))
    m.write('\n## Self-relative word-offset tables (the engine\'s main dispatch idiom)\n\n')
    m.write('`lea base(pc,d0.w),a0 / adda.w (a0),a0 / jsr (a0)` — entries are signed words,\n'
            'target = entry address + word.\n\n')
    for b, n in sorted(ptables.items()):
        m.write('- `%06X` — %d entries\n' % (b, n))
    ram = sorted(a for a in drefs if a >= 0xFF0000)
    m.write('\n## Work-RAM variables touched by traced code (%d)\n\n' % len(ram))
    for a in ram:
        m.write('- `ram_%04X` — %d refs (first at %s)\n' % (a & 0xFFFF, len(drefs[a]), drefs[a][0]))
