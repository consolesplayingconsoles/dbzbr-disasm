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

# capstone's 68000 mode still decodes 68020+ forms: memory-indirect and scaled-index addressing,
# and the 32-bit multiply/divide, bit-field and other later instructions. A 68000 cannot run
# them, so they are data the walk reached, never code.
LATER = ('extb', 'chk2', 'cmp2', 'cas', 'pack', 'unpk', 'bf', 'rtd', 'trapcc', 'callm', 'rtm',
         'divs.l', 'divu.l', 'divsl', 'divul', 'muls.l', 'mulu.l', 'chk.l', 'link.l', 'move16')
SCALED = re.compile(r'\*\s*[248]|\[')


def is68000(ins):
    return not (ins.mnemonic.startswith(LATER) or SCALED.search(ins.op_str))


def plausible(a, need=4):
    """Does `a` decode as a short run of sane 68k?"""
    pc, n = a, 0
    while n < need and pc < END:
        try:
            ins = next(md.disasm(ROM[pc:pc + 16], pc, count=1))
        except StopIteration:
            return False
        if ins.id == 0 or ins.mnemonic in ('illegal', 'reset') or not is68000(ins):
            return False
        if not any(ROM[pc:pc + ins.size]):     # zero words read as `ori.b #0,d0`: a table, not code
            return False
        if ins.mnemonic.split('.')[0] in ('rts', 'rte', 'jmp', 'bra'):
            return n >= 1 or ins.mnemonic == 'rts'   # a bare rts is an empty handler
        pc += ins.size; n += 1
    return True


LOADREG = re.compile(r'\$([0-9a-f]+)\(pc, *d[0-7]\.[wl]\), *(a[0-7])')   # movea.l $X(pc,d0.w),aN
LEAPC   = re.compile(r'\$([0-9a-f]+)\(pc\), *(a[0-7])')                   # lea $X(pc),aN
IDXREG  = re.compile(r'\((a[0-7]), *d[0-7]\.[wl]\), *(a[0-7])')           # movea.l (aY,d0.w),aN
BASEREL = re.compile(r'^\(a[0-7], *d[0-7]\.[wl]\), *a[0-7]$')             # adda.w (aY,d0.w),aN

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

EMPTY_SLOT = 0x4E714E75                  # nop ; rts


def jump_table(base):
    """A pc-indexed dispatch table is a run of `bra.w` (0x6000) slots.

    Every slot must be a `bra.w` (or `nop ; rts`, an empty slot), because an
    identical call site can instead jump into *unrolled code*: a block copy or
    fill written out N times, where landing partway in skips the first k
    iterations. That has no 0x6000 in it, so the slot test tells the two apart.
    """
    out, a = [], base
    for _ in range(4):                      # base may point just before slot 0
        if a + 4 <= END and (struct.unpack_from('>H', ROM, a)[0] == 0x6000 or be32(a) == EMPTY_SLOT):
            break
        a += 2
    while a + 4 <= END:
        op = struct.unpack_from('>H', ROM, a)[0]
        if be32(a) == EMPTY_SLOT:           # `nop ; rts`: an empty slot, the table goes on
            a += 4
            continue
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
# A facts module among them (a path ending .py) adds its SEEDS list: keep hand seeds there, so the
# tracked trace can be regenerated exactly (trace.py <rom> <out.json> tools/facts.py).
seeds = {}
args = []
for a in sys.argv[3:]:
    if a.endswith('.py'):
        import importlib.util, os
        sys.path.insert(0, os.path.dirname(os.path.abspath(a)))
        _spec = importlib.util.spec_from_file_location('facts', a)
        _facts = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_facts)
        args += ['%X' % v for v in getattr(_facts, 'SEEDS', [])]
    else:
        args.append(a)
for i, a in enumerate(args):
    v = int(a, 16)
    if v % 2 == 0 and 0x200 <= v < END:
        seeds[v] = 'manual_%d' % i

for i in range(1, 64):
    v = be32(i * 4) & 0xFFFFFF
    if 0x200 <= v < END and v % 2 == 0:
        seeds.setdefault(v, 'vector_%02d' % i)

def walk(seedlist):
    for a, kind in seedlist.items():         # every seed is an entry point with a label of its own
        labels.setdefault(a, kind)
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
            if not is68000(ins):
                labels[pc] = 'bad'; break      # a 68020+ form: the walk has run into data
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
            # Idiom A through an absolute lea: `lea table.l,aN` (absolute long, not pc-relative) to a run of
            # bra.w slots, dispatched later by `jmp (aN,dM.w)`, here or in a shared dispatcher the
            # routine jumps to. The slot signature ($6000 at the address itself, two or more slots)
            # is the test; anything else stays a plain data reference.
            if ins.mnemonic.startswith('lea'):
                mo = re.match(r'^\$([0-9a-f]+)\.l, *a[0-7]$', ins.op_str.strip())
                if mo:
                    t = int(mo.group(1), 16)
                    if t + 8 <= END and struct.unpack_from('>H', ROM, t)[0] == 0x6000:
                        ents = jump_table(t)
                        if len(ents) >= 2 and ents[0] == t:
                            tables[t] = max(tables.get(t, 0), len(ents))
                            labels.setdefault(t, 'table')
                            for e in ents:
                                labels.setdefault(e, 'jt')
                                tgt = e + 2 + struct.unpack_from('>h', ROM, e + 2)[0]
                                labels.setdefault(tgt, 'mode')
                                if not code[e] and e not in queued:
                                    queued.add(e); work.append(e)
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
                    ents = ({'word': word_table, 'keyed': keyed_table, 'bra': bra_targets,
                             'word_base': word_table_base}.get(kind, pointer_table))(base)
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

def word_table_base(base, limit=512):
    """Entries are signed words measured from the table's own base."""
    out, a, misses = [], base, 0
    while a + 2 <= END and len(out) < limit:
        d = struct.unpack_from('>h', ROM, a)[0]
        t = base + d
        if d == 0:
            a += 2; continue
        if t % 2 or not (0x200 <= t < END) or not plausible(t, need=6):
            misses += 1
            if misses >= 2:
                break
            a += 2; continue
        misses = 0
        out.append(t); a += 2
        if any(base < x <= a for x in out):   # the table ends where a handler after it begins
            break
    return out


def keyed_table(base):
    """[key.w][self-relative offset.w] pairs from base+4, ended by a negative key."""
    out, a = [], base + 4
    while a + 4 <= END:
        if struct.unpack_from('>h', ROM, a)[0] < 0:
            break
        t = a + 2 + struct.unpack_from('>h', ROM, a + 2)[0]
        if t % 2 or not (0x200 <= t < END) or not plausible(t, need=6):
            break
        out.append(t); a += 4
    return out


def bra_targets(base):
    """A bra.w slot table reached through a register: the slots are the entry points."""
    ents = jump_table(base)
    tables[base] = max(tables.get(base, 0), len(ents))
    for e in ents:
        labels.setdefault(e, 'jt')
    return [e + 2 + struct.unpack_from('>h', ROM, e + 2)[0] for e in ents]


def word_table(base, limit=512):
    """Self-relative word table: target = entry address + signed word there."""
    out, a, misses = [], base, 0
    while a + 2 <= END and len(out) < limit:
        d = struct.unpack_from('>h', ROM, a)[0]
        t = a + d
        if any(base < x <= a for x in out):   # the table ends where a handler after it begins
            break
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
    # bra.w slot table through a register: lea table(pc),aN ; jsr (aN,dM.w) 
    mo = re.search(r'^\((a[0-7]), *d[0-7]\.[wl]\)$', ins.op_str.strip())
    if mo:
        for mn, ops in reversed(recent[-6:]):
            m = LEAPC.search(ops) or re.search(r'\$([0-9a-f]+)\.l, *(a[0-7])', ops)
            if mn.startswith('lea') and m and m.group(2) == mo.group(1):
                return ('bra', int(m.group(1), 16))
        return None
    mo = re.search(r'\((a[0-7])\)', ins.op_str)
    if not mo:
        return None
    reg = mo.group(1)
    tail = recent[-6:]
    # base-relative word table, offset fetched first:
    #   lea base(pc,d0.w),aN ; move.w (aN),dM ; lea base(pc),aN ; adda.l dM,aN ; jsr (aN) 
    if any(mn.startswith('adda') and re.match(r'^d[0-7], *%s$' % reg, ops.strip()) for mn, ops in tail[-3:]):
        for mn, ops in reversed(tail):
            m = LEAPC.search(ops)
            if mn.startswith('lea') and m and m.group(2) == reg:
                if any(mn2.startswith('move.w') and ops2.startswith('(%s)' % reg) for mn2, ops2 in tail):
                    return ('word_base', int(m.group(1), 16))
                break
    # keyed table: lea base(pc),aN ; loop: addq.w #4,aN ; key=(aN) (stop on negative) ;
    #   match when 0 <= d - key < k ; addq.w #2,aN ; adda.w (aN),aN ; jsr (aN) 
    if (len(tail) >= 2 and tail[-1][0].startswith('adda') and tail[-1][1].replace(' ', '') == '(%s),%s' % (reg, reg)
            and tail[-2][0].startswith('addq') and tail[-2][1].replace(' ', '') == '#$2,%s' % reg):
        for mn, ops in reversed(recent):
            m = LEAPC.search(ops)
            if mn.startswith('lea') and m and m.group(2) == reg:
                return ('keyed', int(m.group(1), 16))
    # base-relative word table: lea base,aX ; adda.w (aX,dN.w),aX ; jsr (aX)
    # Same family as the entry-relative form below, different origin: entries
    # are displacements from the TABLE BASE, not from the entry holding them.
    # Which one it is has to come from this instruction, not from the data.
    tail = recent[-6:]
    if any(mn.startswith('adda') and BASEREL.match(ops) and ops.rstrip().endswith(reg)
           for mn, ops in tail):
        for mn, ops in reversed(tail):
            if mn.startswith('lea'):
                m = PCIX.search(ops) or LEAPC.search(ops) or ABSL.search(ops)
                if m and ops.rstrip().endswith(reg):
                    return ('word_base', int(m.group(1), 16))

    # entry-relative word table: lea base(pc,dN.w),aX ; adda.w (aX),aX ; jsr (aX)
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

def calls_through(pc):
    try:
        ins = next(md.disasm(ROM[pc:pc + 16], pc, count=1))
    except StopIteration:
        return False
    mo = re.search(r',\s*(a[0-7])$', ins.op_str.strip())
    if not mo:
        return False
    reg, p = mo.group(1), pc + ins.size
    for _ in range(4):
        try:
            i2 = next(md.disasm(ROM[p:p + 16], p, count=1))
        except StopIteration:
            return False
        if i2.mnemonic in ('jsr', 'jmp') and i2.op_str.strip() == '(%s)' % reg:
            return True
        p += i2.size
    return False


walk(seeds)

# --- fixpoint: harvest longword pointer tables that real code points at -----
harvest_rounds = 0
while True:
    harvest_rounds += 1
    fresh = []
    for base in [a for a in list(datarefs) if a < END]:
        # A long-pointer table is harvested as code only when an instruction that loads from it is
        # followed, within four instructions, by a jsr/jmp through the register it loaded. Without
        # this, tables of data pointers (per-level art and load lists) pass plausible() and their
        # data is traced as code.
        if not any(calls_through(r) for r in datarefs[base]):
            continue
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
