#!/usr/bin/env python3
"""Recursive-descent M68K code tracer for a Mega Drive ROM.

Walks from the 68000 vector table, follows every statically-resolvable
branch/call, and reports what is code, what is data, and where the walk
loses the trail (jump tables / computed flow).
"""
import sys, re, struct, json
from collections import defaultdict
from capstone import *

ROM = open(sys.argv[1], 'rb').read()
END = len(ROM)
OUT = sys.argv[2] if len(sys.argv) > 2 else None

md = Cs(CS_ARCH_M68K, CS_MODE_BIG_ENDIAN | CS_MODE_M68K_000)

def be32(a): return struct.unpack_from('>I', ROM, a)[0]

ABSL = re.compile(r'\$([0-9a-f]+)\.l\b')             # $a10008.l  absolute long
ABSW = re.compile(r'\$([0-9a-f]+)\.w\b')             # $e6a4.w    absolute short (sign-extended)
PCR  = re.compile(r'\$([0-9a-f]+)\(pc\)')            # $294(pc)   pc-relative
PCIX = re.compile(r'\$([0-9a-f]+)\(pc, *d[0-7]')     # $45e(pc,d0.w)  jump table
BARE = re.compile(r'^\$([0-9a-f]+)$')                # bra target
IND  = re.compile(r'\((a[0-7]|pc)[,)]')              # (a0) / (pc,d0.w) computed

def plausible(a, need=4):
    """Does `a` decode as a short run of sane 68k?"""
    pc, n = a, 0
    while n < need and pc < END:
        try:
            ins = next(md.disasm(ROM[pc:pc + 16], pc, count=1))
        except StopIteration:
            return False
        if ins.id == 0 or ins.mnemonic in ('illegal', 'reset'):
            return False
        if ins.mnemonic.split('.')[0] in ('rts', 'rte', 'jmp', 'bra'):
            return n >= 1
        pc += ins.size; n += 1
    return True


LOADREG = re.compile(r'\$([0-9a-f]+)\(pc, *d[0-7]\.[wl]\), *(a[0-7])')   # movea.l $X(pc,d0.w),aN
LEAPC   = re.compile(r'\$([0-9a-f]+)\(pc\), *(a[0-7])')                   # lea $X(pc),aN
IDXREG  = re.compile(r'\((a[0-7]), *d[0-7]\.[wl]\), *(a[0-7])')           # movea.l (aY,d0.w),aN

TERMINAL = {'rts', 'rte', 'rtr', 'jmp', 'bra', 'illegal', 'stop', 'reset', 'trap'}
BRANCHY  = ('b', 'j')

code   = bytearray(END)
starts = set()
labels = {}
datarefs = defaultdict(set)
unresolved = []
tables = {}          # bra.w table base -> entry count
ptables = {}         # pointer table base -> entry count

def pointer_table(base, limit=512):
    """Longword pointer table: even ROM addresses, stops at the first bad entry."""
    out, a = [], base
    while a + 4 <= END and len(out) < limit:
        v = struct.unpack_from('>I', ROM, a)[0]
        if v % 2 or not (0x200 <= v < END):
            break
        out.append(v)
        a += 4
    return out

def sxw(v):
    return (0xFF0000 | v) if v >= 0x8000 else v

def scan(ins):
    """-> (branch targets, data refs, jump-table bases, is_computed_flow)"""
    m, ops = ins.mnemonic.split('.')[0], ins.op_str
    br, dr, tbl = [], [], []
    isjump = m in ('jmp', 'jsr')
    bare = BARE.match(ops.strip())
    if bare and m[0] in BRANCHY:
        return [int(bare.group(1), 16)], dr, tbl, False
    seen = []
    for mo in PCIX.finditer(ops):
        seen.append(mo.span())
        (tbl if isjump else dr).append(int(mo.group(1), 16))
    def fresh(mo):
        return not any(s0 <= mo.start() < e0 for s0, e0 in seen)
    for mo in ABSL.finditer(ops):
        if fresh(mo): (br if isjump else dr).append(int(mo.group(1), 16))
    for mo in ABSW.finditer(ops):
        if fresh(mo): (br if isjump else dr).append(sxw(int(mo.group(1), 16)))
    for mo in PCR.finditer(ops):
        if fresh(mo): (br if isjump else dr).append(int(mo.group(1), 16))
    computed = isjump and not br and not tbl
    return br, dr, tbl, computed

def jump_table(base):
    """A pc-indexed dispatch table is a run of `bra.w` (0x6000) slots."""
    out, a = [], base
    for _ in range(4):                      # base may point just before slot 0
        if a + 2 <= END and struct.unpack_from('>H', ROM, a)[0] == 0x6000:
            break
        a += 2
    while a + 4 <= END:
        op = struct.unpack_from('>H', ROM, a)[0]
        if op != 0x6000:
            break
        disp = struct.unpack_from('>h', ROM, a + 2)[0]
        t = a + 2 + disp
        if not (0 <= t < END) or t % 2:
            break
        out.append(a)
        a += 4
    return out

# Extra entry points, passed as hex on the command line. Mode handlers and
# their step tables are reached through word-offset tables the tracer resolves,
# but a step table found by hand (or a routine spotted in a screenshot hunt)
# can be seeded here so the next pass sees everything below it.
seeds = {}
for i, a in enumerate(sys.argv[3:]):
    v = int(a, 16)
    if v % 2 == 0 and 0x200 <= v < END:
        seeds[v] = 'manual_%d' % i

for i in range(1, 64):
    v = be32(i * 4) & 0xFFFFFF
    if 0x200 <= v < END and v % 2 == 0:
        seeds.setdefault(v, 'vector_%02d' % i)

def walk(seedlist):
    work = list(seedlist); queued = set(work)
    while work:
        pc = work.pop()
        recent = []
        while True:
            if pc < 0 or pc >= END or pc % 2 or code[pc]:
                break
            try:
                ins = next(md.disasm(ROM[pc:pc + 16], pc, count=1))
            except StopIteration:
                labels[pc] = 'bad'; break
            for b in range(ins.size):
                code[pc + b] = 1
            starts.add(pc)
            br, dr, tbl, computed = scan(ins)
            for base in tbl:
                n = tables.get(base, 0)
                ents = jump_table(base)
                tables[base] = max(n, len(ents))
                for a in ents:
                    labels.setdefault(a, 'jt')
                    labels.setdefault(a + 2 + struct.unpack_from('>h', ROM, a + 2)[0], 'mode')
                    if not code[a] and a not in queued:
                        queued.add(a); work.append(a)
                labels.setdefault(base, 'table')
            for a in dr:
                datarefs[a].add(pc)
            for a in br:
                if 0 <= a < END and a % 2 == 0:
                    labels.setdefault(a, 'sub' if ins.mnemonic.startswith(('jsr', 'bsr')) else 'loc')
                    if not code[a] and a not in queued:
                        queued.add(a); work.append(a)
            if computed:
                res = resolve_indirect(ins, recent)
                if res is None:
                    unresolved.append((pc, ins.mnemonic, ins.op_str))
                else:
                    kind, base = res
                    ents = word_table(base) if kind == 'word' else pointer_table(base)
                    if ents:
                        ptables[base] = len(ents)
                        labels.setdefault(base, 'ptrtable')
                        for a in ents:
                            labels.setdefault(a, 'sub')
                            if not code[a] and a not in queued:
                                queued.add(a); work.append(a)
                    else:
                        unresolved.append((pc, ins.mnemonic, ins.op_str))
            recent.append((ins.mnemonic, ins.op_str))
            del recent[:-16]
            if ins.mnemonic.split('.')[0] in TERMINAL:
                break
            pc += ins.size

def word_table(base, limit=512):
    """Self-relative word table: target = entry address + signed word there."""
    out, a, misses = [], base, 0
    while a + 2 <= END and len(out) < limit:
        d = struct.unpack_from('>h', ROM, a)[0]
        t = a + d
        if d == 0:                       # unused slot: skip, table continues
            a += 2; continue
        if t % 2 or not (0x200 <= t < END) or not plausible(t, need=6):
            misses += 1
            if misses >= 2:
                break
            a += 2; continue
        misses = 0
        out.append(t); a += 2
    return out


def resolve_indirect(ins, recent):
    """`jsr (aN)` — find the pc-relative pointer table aN was loaded from."""
    mo = re.search(r'\((a[0-7])\)', ins.op_str)
    if not mo:
        return None
    reg = mo.group(1)
    # word-offset table:  lea base(pc,dN.w),aX ; adda.w (aX),aX ; jsr (aX)
    tail = recent[-6:]
    if any(mn.startswith('adda') and ops.startswith('(%s)' % reg) for mn, ops in tail):
        for mn, ops in reversed(tail):
            if mn.startswith('lea'):
                m = PCIX.search(ops) or LEAPC.search(ops) or ABSL.search(ops)
                if m and ops.rstrip().endswith(reg):
                    return ('word', int(m.group(1), 16))
    for mn, ops in reversed(recent):
        if not mn.startswith(('movea', 'lea')):
            continue
        m1 = LOADREG.search(ops)
        if m1 and m1.group(2) == reg:
            return ('long', int(m1.group(1), 16))
        m2 = IDXREG.search(ops)
        if m2 and m2.group(2) == reg:
            src = m2.group(1)
            for mn2, ops2 in reversed(recent):
                m3 = LEAPC.search(ops2)
                if m3 and m3.group(2) == src:
                    return ('long', int(m3.group(1), 16))
            return None
        if re.search(r', *%s\b' % reg, ops):
            return None            # aN loaded some other way; give up
    return None

walk(seeds)

# --- fixpoint: harvest longword pointer tables that real code points at -----
def _unused_plausible(a, need=4):
    """Does `a` decode as a short run of sane 68k?"""
    pc, n = a, 0
    while n < need and pc < END:
        try:
            ins = next(md.disasm(ROM[pc:pc + 16], pc, count=1))
        except StopIteration:
            return False
        if ins.id == 0 or ins.mnemonic in ('illegal', 'reset'):
            return False
        if ins.mnemonic.split('.')[0] in ('rts', 'rte', 'jmp', 'bra'):
            return n >= 1
        pc += ins.size; n += 1
    return True

harvest_rounds = 0
while True:
    harvest_rounds += 1
    fresh = []
    for base in [a for a in list(datarefs) if a < END]:
        a = base
        got = []
        while a + 4 <= END and len(got) < 256:
            v = struct.unpack_from('>I', ROM, a)[0]
            if v % 2 or not (0x200 <= v < END) or not plausible(v):
                break
            got.append(v); a += 4
        if len(got) >= 2:                    # a lone pointer is too weak a signal
            ptables[base] = len(got)
            labels.setdefault(base, 'ptrtable')
            for t in got:
                if not code[t]:
                    labels.setdefault(t, 'sub'); fresh.append(t)
    if not fresh or harvest_rounds > 8:
        break
    walk(dict.fromkeys(fresh, 'harvest'))

print('harvest rounds    : %d' % harvest_rounds)

covered = sum(code)
print('ROM               : 0x%06X (%d KiB)' % (END, END // 1024))
print('reset PC          : %06X   vector seeds: %d' % (be32(4), len(seeds)))
print('instructions      : %d' % len(starts))
print('bytes reached     : 0x%06X  (%.2f%% of ROM)' % (covered, 100.0 * covered / END))
print('labels            : %d' % len(labels))
print('bra.w dispatch tables: %d (%d slots total)' % (len(tables), sum(tables.values())))
print('pointer tables    : %d (%d entries)' % (len(ptables), sum(ptables.values())))
print('computed jmp/jsr  : %d  (register-indirect — trace stops here)' % len(unresolved))

runs, cur, start = [], code[0], 0
for a in range(1, END + 1):
    v = code[a] if a < END else -1
    if v != cur:
        runs.append((start, a, cur)); start, cur = a, v
gaps = [r for r in runs if r[2] == 0]
codr = [r for r in runs if r[2] == 1]
print('\ntop unreached gaps:')
for s, e, _ in sorted(gaps, key=lambda r: r[0] - r[1])[:12]:
    print('  %06X-%06X %8d' % (s, e - 1, e - s))
print('\ntop traced code runs:')
for s, e, _ in sorted(codr, key=lambda r: r[0] - r[1])[:12]:
    print('  %06X-%06X %8d' % (s, e - 1, e - s))

ram = sorted(a for a in datarefs if a >= 0xFF0000)
hw  = sorted(a for a in datarefs if 0xA00000 <= a < 0xC00010)
rom = sorted(a for a in datarefs if a < END)
print('\ndata refs: %d work-RAM, %d hardware (VDP/Z80/IO), %d into ROM'
      % (len(ram), len(hw), len(rom)))
print('computed-flow sites:')
for a, m, o in unresolved[:20]:
    print('  %06X  %s %s' % (a, m, o))

if OUT:
    json.dump({'starts': sorted(starts),
               'labels': {'%06X' % k: v for k, v in labels.items()},
               'unresolved': [['%06X' % a, m, o] for a, m, o in unresolved],
               'gaps': [[s, e] for s, e, _ in gaps],
               'tables': {'%06X' % k: v for k, v in tables.items()},
               'ptables': {'%06X' % k: v for k, v in ptables.items()},
               'datarefs': {'%06X' % k: sorted('%06X' % x for x in v) for k, v in datarefs.items()}},
              open(OUT, 'w'))
