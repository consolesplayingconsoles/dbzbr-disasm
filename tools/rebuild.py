#!/usr/bin/env python3
"""rebuild.py: turn a ROM into assembly source that rebuilds it byte for byte, and record how much
of that source reads as source. The step that makes a map a disassembly (SKILL.md step 12).

  rebuild.py <rom> <trace.json> <out dir> --as <dir with asl and p2bin>
             [--facts facts.py] [--names NAMES] [--blocks BLOCKS] [--pointers POINTERS]
             [--not-code NOT_CODE] [--record rebuild.json]

Writes, under <out dir> (keep it in build/: it holds the game):
  main.asm         the whole ROM, in address order: includes and bincludes
  code/<name>.asm  one file per routine, labels for every branch and reference target
  data/<name>.bin  the bytes between code, split at every label and every block boundary
  rom.bin          what AS builds from main.asm, compared against the ROM

Code comes from the trace: its "starts" (every instruction it decoded, exactly those) if it has
them, else "code_ranges" ([start, end) pairs, decoded linearly). Each instruction is written in AS syntax with its ROM operands as labels.
Every instruction is checked on its own first (one AS run, each in its own slot under
`phase <address>`); one that does not assemble to its own bytes is written as `dc.w` with the
instruction in a comment, and its routine is not symbolic. Then the whole ROM is assembled and
compared. Nothing is ever "fixed" by hand in the output: change the tool or the facts and rerun.

The facts module is where the work happens (the output is regenerated, never edited); all optional:
  NAMES     address -> name; routines, labels and data blocks take these names
  BLOCKS    (start, end inclusive, name, format) per known data block; format is what decodes it
            ("rnc", "frames", "palette", "text", ...), "raw" when nothing does
  POINTERS  addresses of instructions whose immediate is a ROM address (`move.l #$12F0, a0` loading
            a table): the immediate becomes a label. An immediate in the ROM's range that is not
            listed here, nor a reference the trace recorded, leaves its routine not symbolic
  NOT_CODE  (start, end inclusive) ranges the trace took for code that are data: they become data
  FIELDS    offset -> name: struct fields (`obVelX` = $10). A displacement off an address register
            ($10(a0), $4(a2,d0.w)) prints as its field's name; one with no name leaves the routine
            not symbolic, like a ROM address left as a number
  FIELD_AT  instruction address -> (name, ...): the field names for that instruction's
            displacements, in operand order, where FIELDS' name for that offset is the wrong struct
  CONSTANTS addresses of instructions whose immediate falls in the ROM's range but is a number
            (a count, a mask, a VDP command): it stays a number and the routine can still be
            symbolic. An immediate moved to SR or CCR is always a number.
  PTR_TABLES  (start, end inclusive, name) tables of absolute longs pointing into the ROM: written
            as `dc.l <label>`, so they follow what they point at (the block's format is "pointers")
Each code block records its inner labels and struct displacements, and how many are named; a data block written as source
(not a binary file) records "source": true. The record (--record) holds addresses, names and formats only, no game bytes: track it. progress.py
reads it for the main metric.

AS is Alfred Arnold's macro assembler (asl, p2bin): http://john.ccac.rwth-aachen.de:8000/as/
(prebuilt binaries for most hosts are also bundled with several public Mega Drive disassemblies).
"""
import argparse, hashlib, importlib.util, json, os, re, subprocess, sys
import capstone as cs

ap = argparse.ArgumentParser()
ap.add_argument('rom'); ap.add_argument('trace'); ap.add_argument('out')
ap.add_argument('--as', dest='asdir', required=True)
ap.add_argument('--facts'); ap.add_argument('--names', default='NAMES'); ap.add_argument('--blocks', default='BLOCKS')
ap.add_argument('--pointers', default='POINTERS'); ap.add_argument('--not-code', dest='not_code', default='NOT_CODE')
ap.add_argument('--ptr-tables', dest='ptr_tables', default='PTR_TABLES')
ap.add_argument('--constants', default='CONSTANTS')
ap.add_argument('--fields', default='FIELDS'); ap.add_argument('--field-at', dest='field_at', default='FIELD_AT')
ap.add_argument('--record')
a = ap.parse_args()

ROM = open(a.rom, 'rb').read()
SIZE = len(ROM)
tr = json.load(open(a.trace))
NAMES, BLOCKS, POINTERS, NOT_CODE, PTR_TABLES, CONSTANTS, FIELDS, FIELD_AT = {}, [], set(), [], [], set(), {}, {}
if a.facts:
    sys.path.insert(0, os.path.dirname(os.path.abspath(a.facts)))
    spec = importlib.util.spec_from_file_location('facts', a.facts)
    facts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(facts)
    NAMES = dict(getattr(facts, a.names, {}))
    BLOCKS = list(getattr(facts, a.blocks, []))
    POINTERS = set(getattr(facts, a.pointers, ()))
    NOT_CODE = list(getattr(facts, a.not_code, []))
    PTR_TABLES = list(getattr(facts, a.ptr_tables, []))
    CONSTANTS = set(getattr(facts, a.constants, ()))
    FIELDS = dict(getattr(facts, a.fields, {}))
    FIELD_AT = dict(getattr(facts, a.field_at, {}))
for _ts, _te, _tn in PTR_TABLES:
    NAMES.setdefault(_ts, _tn)               # a pointer table is a label of its own
# A block or a pointer table was checked whole as data: it wins over whatever the trace decoded there.
NOT_CODE = NOT_CODE + [(b[0], b[1]) for b in BLOCKS] + [(t[0], t[1]) for t in PTR_TABLES]

md = cs.Cs(cs.CS_ARCH_M68K, cs.CS_MODE_M68K_000 + cs.CS_MODE_BIG_ENDIAN)

# ---- code: every instruction, from the trace --------------------------------------------------
insns = {}                                   # address -> (size, mnemonic, op_str) or (size, None, None)


def outside_not_code(p, n):
    return not any(ns <= q <= ne for ns, ne in NOT_CODE for q in (p, p + n - 1))


if 'starts' in tr:
    # Exactly the instructions the trace decoded: bytes between them are data, never swept.
    taken_end = 0
    for p in sorted(set(tr['starts'])):
        i = next(md.disasm(ROM[p:p + 10], p, 1), None)
        if i is None or not outside_not_code(p, i.size) or p < taken_end:
            continue                         # undecodable, declared data, or inside the last one
        insns[p] = (i.size, i.mnemonic, i.op_str)
        taken_end = p + i.size
else:
    # Ranges ([start, end) pairs) of code: decoded linearly from each range's start.
    cut = []                                 # the code ranges minus NOT_CODE
    for s, e in tr['code_ranges']:
        pieces = [(s, e)]
        for ns, ne in NOT_CODE:
            nxt = []
            for ps, pe in pieces:
                if ne + 1 <= ps or ns >= pe:
                    nxt.append((ps, pe))
                    continue
                if ps < ns:
                    nxt.append((ps, ns))
                if ne + 1 < pe:
                    nxt.append((ne + 1, pe))
            pieces = nxt
        cut += pieces
    for s, e in sorted(cut):
        p = s
        while p < e:
            i = next(md.disasm(ROM[p:e], p, 1), None)
            if i is None or p + i.size > e:
                n = 2 if e - p >= 2 else 1
                insns[p] = (n, None, None)
                p += n
            else:
                insns[p] = (i.size, i.mnemonic, i.op_str)
                p += i.size

labels_kind = {int(k, 16): v for k, v in tr.get('labels', {}).items()}
drefs = {}                                   # instruction address -> ROM targets it references
for t, sites in tr.get('datarefs', {}).items():
    for site in sites:
        drefs.setdefault(int(site, 16), set()).add(int(t, 16))

BRANCH = re.compile(r'^(b(ra|sr|hi|ls|cc|cs|ne|eq|vc|vs|pl|mi|ge|lt|gt|le|hs|lo)|db\w+)(\.\w)?$')
PCREL = re.compile(r'(-?)\$([0-9a-f]+)\(pc')
ABS = re.compile(r'(?<![\w#(-])\$([0-9a-f]+)\.([lw])\b')
IMM = re.compile(r'#\$([0-9a-f]+)')
BARE = re.compile(r'(?<![\w#(-])\$([0-9a-f]+)$')

# ---- targets: everything code points at becomes a label -----------------------------------------
targets = set()


def rom_target(v):
    return 0 <= v < SIZE


for p, (n, m, ops) in insns.items():
    if m is None:
        continue
    for x in PCREL.finditer(ops):
        targets.add(int(x.group(2), 16) * (-1 if x.group(1) else 1))
    for x in ABS.finditer(ops):
        v = int(x.group(1), 16)
        if rom_target(v):
            targets.add(v)
    if BRANCH.match(m):
        x = BARE.search(ops)
        if x:
            targets.add(int(x.group(1), 16))
    for x in IMM.finditer(ops):
        v = int(x.group(1), 16)
        if v in drefs.get(p, ()) or p in POINTERS:
            targets.add(v)
for p in labels_kind:
    targets.add(p)
for p in NAMES:
    if rom_target(p):
        targets.add(p)
for b in BLOCKS:
    targets.add(b[0])
for ts, te, tn in PTR_TABLES:
    targets.add(ts)
    for q in range(ts, te + 1, 4):
        targets.add(int.from_bytes(ROM[q:q + 4], 'big'))
targets = {t for t in targets if rom_target(t)}

# A label can only sit on an instruction start or in data; one inside an instruction stays a number.
inside = set()
for p, (n, m, ops) in insns.items():
    for q in range(p + 1, p + n):
        inside.add(q)
labelable = {t for t in targets if t not in inside}
data_label = {t for t in labelable if t not in insns}
# A label inside a pointer table but not on an entry: written as table+offset, not a cut.
inner = {t: pt for t in data_label for pt in PTR_TABLES if pt[0] < t <= pt[1] and (t - pt[0]) % 4}
data_label -= set(inner)

AUTO = {'sub': 'sub', 'loc': 'loc', 'jt': 'jt', 'mode': 'mode', 'table': 'tbl', 'ptrtable': 'ptr', 'bad': 'bad'}


def name_of(t):
    if t in NAMES:
        return NAMES[t]
    if t in insns:
        k = labels_kind.get(t, 'loc')
        return '%s_%06X' % (AUTO.get(k, 'vec' if str(k).startswith('vector') else 'loc'), t)
    return 'off_%06X' % t


# ---- one instruction, in AS syntax -------------------------------------------------------------
# RAM and hardware operands are names too: a routine is symbolic only when every absolute operand is.
RAM_NAMES = {a & 0xFFFFFF: n for a, n in NAMES.items() if (a & 0xFFFFFF) >= 0xFF0000}
HW = {0xA00000: 'Z80_RAM', 0xA04000: 'YM2612_A0', 0xA04001: 'YM2612_D0', 0xA04002: 'YM2612_A1',
      0xA04003: 'YM2612_D1', 0xA10000: 'IO_VERSION', 0xA10002: 'IO_DATA1', 0xA10004: 'IO_DATA2',
      0xA10006: 'IO_DATA3', 0xA10008: 'IO_CTRL1', 0xA1000A: 'IO_CTRL2', 0xA1000C: 'IO_CTRL3',
      0xA11100: 'Z80_BUSREQ', 0xA11200: 'Z80_RESET', 0xA14000: 'TMSS', 0xC00000: 'VDP_DATA',
      0xC00004: 'VDP_CTRL', 0xC00008: 'VDP_HV', 0xC00011: 'PSG'}
EQUS = {}                                    # name -> value, for RAM and hardware names used


def ram_or_hw(full, size):
    """The operand as a name (or name+offset), or None."""
    a24 = full & 0xFFFFFF
    if a24 >= 0xFF0000:
        n = RAM_NAMES.get(a24)
        if n is None:
            return None
        EQUS[n] = 0xFF000000 | a24           # sign-extended, so .w and $FFFFxxxx.l both encode
        return n if size == 'w' or full >> 24 == 0xFF else '%s&$FFFFFF' % n
    base = max((h for h in HW if h <= full < h + 2), default=None)
    if base is None:
        return None
    EQUS[HW[base]] = base
    return HW[base] + ('+%d' % (full - base) if full > base else '')


DISP = re.compile(r'(?<![\w$])(-?)\$([0-9a-f]+)\((a[0-7]|sp)([,)])')


def render(p, m, ops):
    """(text, symbolic): the instruction with its ROM, RAM and hardware operands as names where it
    can; symbolic only when every one of them is."""
    sym = [True]

    def lab(v):
        if v in labelable:
            return name_of(v)
        if v in inside:                      # a table base inside an instruction (an index that starts
            for k in range(1, 9):            # above 0): the next label, minus the difference
                if v + k in labelable:
                    return '%s-%d' % (name_of(v + k), k)
        sym[0] = False
        return '$%X' % v

    if m in ('btst.l', 'bset.l', 'bclr.l', 'bchg.l', 'btst.b', 'bset.b', 'bclr.b', 'bchg.b'):
        m = m[:-2]                           # AS takes the size from the operand
    o = PCREL.sub(lambda x: lab(int(x.group(2), 16) * (-1 if x.group(1) else 1)) + '(pc', ops)

    def absr(x):
        v, size = int(x.group(1), 16), x.group(2)
        full = v | 0xFFFF0000 if size == 'w' and v >= 0x8000 else v    # a short address sign-extends
        if rom_target(full):
            return '(%s).%s' % (lab(full), size)
        n = ram_or_hw(full, size)
        if n is None:
            sym[0] = False                   # RAM or hardware nobody has named yet
            return '($%X).%s' % (full, size)
        return '(%s).%s' % (n, size)
    o = ABS.sub(absr, o)
    if m == 'moveq':                         # its immediate is a signed byte
        o = re.sub(r'#\$([0-9a-f]+)', lambda x: '#%d' % (int(x.group(1), 16) - (256 if int(x.group(1), 16) > 127 else 0)), o)
    if BRANCH.match(m):
        o = BARE.sub(lambda x: lab(int(x.group(1), 16)), o)

    def immr(x):
        v = int(x.group(1), 16)
        if (v in drefs.get(p, ()) or p in POINTERS) and rom_target(v):
            return '#' + lab(v)
        if 0x200 <= v < SIZE and m != 'moveq' and p not in CONSTANTS and not re.search(r',\s*(sr|ccr)$', ops):
            sym[0] = False                   # may be a ROM pointer nobody has labelled: not counted
        return x.group(0)
    o = IMM.sub(immr, o)
    fields, named_fields, at = [0], [0], list(FIELD_AT.get(p, ()))

    def dispr(x):
        v = int(x.group(2), 16) * (-1 if x.group(1) else 1)
        fields[0] += 1
        n = at.pop(0) if at else FIELDS.get(v)
        zero = v == 0 and x.group(4) == ')'  # AS would shorten 0(a6) to (a6): (0.w,a6) keeps it
        if n is None:
            sym[0] = False                   # a struct offset nobody has named yet
            return '(0.w,%s)' % x.group(3) if zero else x.group(0)
        EQUS[n] = v
        named_fields[0] += 1
        return '(%s.w,%s)' % (n, x.group(3)) if zero else '%s(%s%s' % (n, x.group(3), x.group(4))
    o = DISP.sub(dispr, o)
    return ('\t%s\t%s' % (m, o)).rstrip(), sym[0], fields[0], named_fields[0]


def dcw(p, n, why=''):
    b = ROM[p:p + n]
    if n % 2:
        return '\tdc.b\t' + ', '.join('$%02X' % c for c in b) + why
    return '\tdc.w\t' + ', '.join('$%04X' % int.from_bytes(b[i:i + 2], 'big') for i in range(0, n, 2)) + why


ASL = os.path.join(a.asdir, 'asl')
P2BIN = os.path.join(a.asdir, 'p2bin')


def assemble(src, name):
    path = os.path.join(a.out, name)
    open(path + '.asm', 'w').write(src)
    r = subprocess.run([ASL, '-q', '-xx', '-c', '-A', '-U', '-i', a.out, name + '.asm'], cwd=a.out,
                       capture_output=True, text=True)
    errs = [int(x) for x in re.findall(r'\.asm\((\d+)\)', r.stdout + r.stderr)]
    if errs or not os.path.exists(path + '.p'):
        return None, errs, r.stdout + r.stderr
    subprocess.run([P2BIN, name + '.p', name + '.bin'], cwd=a.out, capture_output=True)
    return open(path + '.bin', 'rb').read(), [], ''


os.makedirs(os.path.join(a.out, 'code'), exist_ok=True)
os.makedirs(os.path.join(a.out, 'data'), exist_ok=True)
HEAD = '\tcpu 68000\n\tsupmode on\n\tpadding off\n'

# ---- pass 1: each instruction on its own -------------------------------------------------------
fallback = {}                                # address -> why it is dc.w
order = sorted(insns)
rendered = {}
for p in order:
    n, m, ops = insns[p]
    if m is None:
        fallback[p] = 'not decodable'
    else:
        rendered[p] = render(p, m, ops)
SLOT = 16
while True:
    lines, line_of = HEAD.rstrip('\n').split('\n'), {}
    lines += ['%s equ $%X' % (name_of(t), t) for t in sorted(labelable)]
    lines += ['%s equ %s$%X' % (n, '-' if v < 0 else '', abs(v)) for n, v in sorted(EQUS.items())]
    live = [p for p in order if p not in fallback]
    for k, p in enumerate(live):
        lines += ['\torg $%X' % (k * SLOT), '\tphase $%X' % p, rendered[p][0], '\tdephase']
        line_of[len(lines) - 1] = p          # AS counts lines from 1: this is the instruction's
    src = '\n'.join(lines) + '\n'
    out, errs, log = assemble(src, 'check')
    if out is None and not errs:
        sys.exit('rebuild.py: AS failed without a line number:\n' + log[-2000:])
    if errs:
        hit = [line_of[e] for e in errs if e in line_of]
        if not hit:
            sys.exit('rebuild.py: AS error outside an instruction:\n' + log[-2000:])
        for p in hit:
            fallback[p] = 'AS rejects it'
        continue
    for k, p in enumerate(live):
        n = insns[p][0]
        if out[k * SLOT:k * SLOT + n] != ROM[p:p + n]:
            fallback[p] = 'AS encodes it differently'
    break

# ---- pass 2: the whole ROM ----------------------------------------------------------------------
cuts = set(data_label) | {b[0] for b in BLOCKS} | {b[1] + 1 for b in BLOCKS} \
    | {t[0] for t in PTR_TABLES} | {t[1] + 1 for t in PTR_TABLES}
block_of = {}
for b in BLOCKS:
    block_of[b[0]] = b
segments = []                                # (start, end, kind)
p = 0
code_starts = order
ci = 0
while p < SIZE:
    if p in insns:
        s = p
        while p in insns:
            p += insns[p][0]
        segments.append((s, p, 'code'))
    else:
        s = p
        p += 1
        while p < SIZE and p not in insns and p not in cuts:
            p += 1
        segments.append((s, p, 'data'))

# A routine starts where the trace found an entry (a call target, a dispatch target, a seed). A name
# on any other code address names a label inside its routine; it never splits the routine.
ENTRY = ('sub', 'mode', 'harvest', 'vector', 'manual')
routine_starts = sorted(t for t in labelable if t in insns and str(labels_kind.get(t, '')).startswith(ENTRY))
main = [HEAD] + ['%s equ %s$%X' % (n, '-' if v < 0 else '', abs(v)) for n, v in sorted(EQUS.items())] + ['\torg 0']
blocks = []
cur = None                                   # the routine being written: [start, name, lines, symbolic]


def flush():
    global cur
    if cur:
        open(os.path.join(a.out, 'code', cur[1] + '.asm'), 'w').write('\n'.join(cur[2]) + '\n')
        main.append('\tinclude "code/%s.asm"' % cur[1])
        blocks.append({'start': cur[0], 'end': cur[3] - 1, 'kind': 'code', 'name': cur[1], 'symbolic': cur[4],
                       'labels': cur[5], 'named_labels': cur[6], 'fields': cur[7], 'named_fields': cur[8]})
        cur = None


rs = set(routine_starts)
for s, e, kind in segments:
    if kind == 'data':
        flush()
        pt = next((t for t in PTR_TABLES if t[0] <= s <= t[1]), None)
        if pt and (s - pt[0]) % 4 == 0 and (e - s) % 4 == 0 and e <= pt[1] + 1:
            vals = [int.from_bytes(ROM[q:q + 4], 'big') for q in range(s, e, 4)]
            if all(v in labelable for v in vals):
                if s in labelable:
                    main.append('%s:' % name_of(s))
                for k in range(0, len(vals), 4):
                    main.append('\tdc.l\t' + ', '.join(name_of(v) for v in vals[k:k + 4]))
                for t, tpt in sorted(inner.items()):
                    if s <= t < e:
                        main.append('%s equ %s+$%X' % (name_of(t), name_of(s), t - s))
                blocks.append({'start': s, 'end': e - 1, 'kind': 'data', 'name': pt[2], 'format': 'pointers', 'source': True})
                continue
        b = next((x for x in BLOCKS if x[0] <= s <= x[1]), None)   # a label inside a block splits it:
        nm = b[2] if b else (name_of(s) if s in labelable else 'data_%06X' % s)   # each piece keeps its name
        fmt = b[3] if b else 'raw'
        fn = '%s_%06X.bin' % (re.sub(r'[^\w]', '_', nm), s)
        open(os.path.join(a.out, 'data', fn), 'wb').write(ROM[s:e])
        if s in labelable:
            main.append('%s:' % name_of(s))
        main.append('\tbinclude "data/%s"' % fn)
        blocks.append({'start': s, 'end': e - 1, 'kind': 'data', 'name': nm, 'format': fmt})
        continue
    p = s
    while p < e:
        if cur is None or p in rs:
            flush()
            nm = name_of(p) if p in labelable else 'code_%06X' % p
            cur = [p, nm, [], p, True, 0, 0, 0, 0]
        if p in labelable:
            cur[2].append('%s:' % name_of(p))
            if p != cur[0]:                  # a label inside the routine: named, or still loc_
                cur[5] += 1
                cur[6] += p in NAMES
        n = insns[p][0]
        if p in fallback:
            m, ops = insns[p][1], insns[p][2]
            cur[2].append(dcw(p, n, '\t; %s %s (%s)' % (m or '?', ops or '', fallback[p])))
            cur[4] = False
            m, ops = insns[p][1], insns[p][2]
        else:
            text, sym, nf, nnf = rendered[p]
            cur[2].append(text)
            cur[4] = cur[4] and sym
            cur[7] += nf
            cur[8] += nnf
        p += n
        cur[3] = p
flush()

out, errs, log = assemble('\n'.join(main) + '\n', 'main')
if out is None:
    sys.exit('rebuild.py: the whole-ROM build failed:\n' + log[-3000:])
os.replace(os.path.join(a.out, 'main.bin'), os.path.join(a.out, 'rom.bin'))
identical = out == ROM
if not identical:
    first = next((i for i in range(min(len(out), SIZE)) if out[i] != ROM[i]), min(len(out), SIZE))
    print('rebuild.py: NOT identical: %d bytes built, %d in the ROM, first difference at $%06X'
          % (len(out), SIZE, first))
code_n = sum(1 for b in blocks if b['kind'] == 'code')
print('rebuild.py: %s; %d routines (%d symbolic), %d data blocks, %d instructions as dc.w'
      % ('identical (SHA-1 %s)' % hashlib.sha1(out).hexdigest() if identical else 'DIFFERENT',
         code_n, sum(1 for b in blocks if b['kind'] == 'code' and b['symbolic']),
         len(blocks) - code_n, len(fallback)))
if a.record:
    json.dump({'rom_sha1': hashlib.sha1(ROM).hexdigest(), 'identical': identical, 'blocks': blocks},
              open(a.record, 'w'), indent=0)
