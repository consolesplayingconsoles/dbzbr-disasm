#!/usr/bin/env python3
"""progress.py: the disassembly's state, in several measures, the main one first. Run from the repo root
after tracing (traces/trace.json).

  source       the main metric: bytes the source rebuilds identically as named, readable
               code and data (the rebuild record, see source_rows)
  game code    subroutines named, unnamed and documented (named in a *.md), and RAM
               variables named (tools/facts.py NAMES); code the tracer reached, and the
               indirect calls it still can't follow
  mapped       facts.REGIONS by confidence, and the bytes the solid and likely ones cover
  art, text    fighter frames identified (GOKU_POSES), font glyphs decoded (tools/text.py)
"""
import json, os, sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import facts, text

ROM_SIZE = facts.ROM_SIZE
if not os.path.exists('traces/trace.json'):
    sys.exit('progress.py: no traces/trace.json (trace the ROM first)')
t = json.load(open('traces/trace.json'))

code = ROM_SIZE - sum(e - s for s, e in t['gaps'])
kinds = {}
for k in t['labels'].values():
    kinds[k] = kinds.get(k, 0) + 1
subs = {int(a, 16) for a, k in t['labels'].items() if k == 'sub'}
ram = {int(a, 16) for a in t['datarefs'] if a.startswith('FF')}
named_subs = sum(1 for a in facts.NAMES if a in subs)
named_ram = sum(1 for a in facts.NAMES if (a | 0xFF0000) in ram)

conf = {'solid': 0, 'likely': 0, 'guess': 0}
for _, _, _, level in facts.REGIONS:
    conf[level] += 1
covered = set()
for s, e, _, level in facts.REGIONS:
    if level != 'guess':
        covered.update(range(s, e + 1))
for s, e, _, _ in getattr(facts, 'BLOCKS', []):    # checked whole: high confidence
    covered.update(range(s, e + 1))
mapped = len(covered)

empty = 7                                    # Goku's empty frames: 49, 50, 54-57, 81 (facts.py)
goku = facts.GOKU_FRAMES - empty


def pct(a, b):
    return '%5.1f%%' % (100.0 * a / b) if b else '-'


# ── the main metric: equivalent source ──────────────────────────────────────────────────
# The disassembly is done when its source rebuilds the ROM byte for byte and every byte of it
# reads as source: code in named routines with symbolic operands (no raw ROM addresses, so the
# source can be edited and still build), data in named blocks of a decoded format. The rebuild
# tool records what it emitted in REBUILD (tracked: addresses, names and formats, no game bytes):
#   {"identical": bool, "blocks": [{"start", "end" (inclusive), "kind": "code"|"data", "name",
#    "symbolic": bool (code), "format": str (data; "raw" when not decoded)}]}
# A byte counts only when the whole rebuild is identical and its block is named and readable: code
# symbolic; data a leaf asset kept as a binary file in a decoded format (LEAF), or written by the
# rebuild as source ("source": true). Structured data (tables, mappings, frame layouts, scripts,
# text) counts only as source.
import re
LEAF = {'tiles', 'compressed_tiles', 'rnc', 'lzss', 'lzss_frames', 'nemesis', 'kosinski', 'palette',
        'samples', 'pcm', 'fill'}


def readable(b):
    return bool(b.get('source')) or b.get('format', 'raw') in LEAF


AUTO = re.compile(r'^(sub|loc|off|ram|unk|byte|word|dword|tbl|ptr|jt|mode|vec|bad|bin|data|code)_[0-9A-Fa-f]+$')


def source_rows(path, rom_size, release):
    try:
        rb = json.load(open(path))
    except (OSError, ValueError):
        rb = None
    if not rb:
        return [('SOURCE (%s)' % release, '', 'no rebuild recorded yet (%s)' % path),
                ('  done: equivalent source', pct(0, rom_size), 'rebuilds byte-identical; named code with every label and operand named; named leaf assets, structured data as source'),
                ('  rebuilds byte-identical', '-', 'not recorded yet')]
    named = lambda b: bool(b.get('name')) and not AUTO.match(b['name'])
    size = lambda b: b['end'] - b['start'] + 1
    code = [b for b in rb['blocks'] if b['kind'] == 'code']
    data = [b for b in rb['blocks'] if b['kind'] == 'data']
    code_ok = sum(size(b) for b in code if named(b) and b.get('symbolic')
                  and b.get('named_labels', 0) == b.get('labels', 0))
    data_ok = sum(size(b) for b in data if named(b) and readable(b))
    inner = sum(b.get('labels', 0) for b in code)
    inner_named = sum(b.get('named_labels', 0) for b in code)
    flds = sum(b.get('fields', 0) for b in code)
    flds_named = sum(b.get('named_fields', 0) for b in code)
    done = code_ok + data_ok if rb.get('identical') else 0
    code_b, data_b = sum(size(b) for b in code), sum(size(b) for b in data)
    return [('SOURCE (%s)' % release, '', '%d blocks: %d code, %d data' % (len(rb['blocks']), len(code), len(data))),
            ('  done: equivalent source', pct(done, rom_size), 'rebuilds byte-identical; named code with every label and operand named; named leaf assets, structured data as source'),
            ('  rebuilds byte-identical', '-', 'yes' if rb.get('identical') else 'NO: nothing counts until it does'),
            ('  code as source', pct(code_ok, code_b), '%d of %d code bytes: named routine, labels and operands (addresses, struct fields) named' % (code_ok, code_b)),
            ('  data as source', pct(data_ok, data_b), '%d of %d data bytes: named leaf asset, or written as source' % (data_ok, data_b)),
            ('  local labels named', pct(inner_named, inner), '%d of %d labels inside routines' % (inner_named, inner)),
            ('  struct fields named', pct(flds_named, flds), '%d of %d displacements off an address register' % (flds_named, flds)),
            ('  named constants', '-', 'not required: an ID and a count look alike')]


docs = ''.join(open(f, encoding='utf-8').read() for f in sorted(os.listdir('.')) if f.endswith('.md'))
documented = sum(1 for a, n in facts.NAMES.items() if a in subs and n in docs)
level = {'solid': 'high', 'likely': 'medium', 'guess': 'low'}

# The shared layout (the Dreamcast decomps' too): the main metric first, the one that reads
# 100% when the project is complete (equivalent source, above). Then the ROM map, the game
# code, and what this disassembly measures on its own.
rows_out = source_rows('traces/rebuild.json', ROM_SIZE, 'French ROM') + [
    ('ROM MAP (facts.REGIONS)', '', '%d regions: %d high, %d medium, %d low confidence'
     % (len(facts.REGIONS), conf['solid'], conf['likely'], conf['guess'])),
    ('  mapped, bytes', pct(mapped, ROM_SIZE), 'high and medium confidence ranges, and the data blocks'),
    ('GAME CODE (French ROM, traced)', '', '%d subroutines, %d bytes of code' % (len(subs), code)),
    ('  named', pct(named_subs, len(subs)), '%d of %d subroutines (tools/facts.py NAMES)' % (named_subs, len(subs))),
    ('  unnamed', pct(len(subs) - named_subs, len(subs)), '%d subroutines (sub_...)' % (len(subs) - named_subs)),
    ('  documented', pct(documented, len(subs)), '%d named subroutines in *.md' % documented),
    ('  named globals', '-', '%d of %d RAM variables referenced' % (named_ram, len(ram))),
    ('  traced code, of the ROM', pct(code, ROM_SIZE), 'the rest is art and data'),
    ('  dispatch tables', '-', '%d jump, %d pointer, %d mode' % (kinds.get('jt', 0), kinds.get('ptrtable', 0), kinds.get('mode', 0))),
    ('  indirect calls unresolved', '-', '%d' % len(t['unresolved'])),
    ('ART AND TEXT', '', ''),
    ('  Goku frames identified', pct(len(facts.GOKU_POSES), goku), '%d of %d' % (len(facts.GOKU_POSES), goku)),
    ('  fighters identified', pct(len(facts.FIGHTERS), 11), '%d of 11 (roster order)' % len(facts.FIGHTERS)),
    ('  font glyphs decoded', '-', '%d' % len(text.FONT)),
]
for label, p, rest in rows_out:
    print(('%-30s %6s  %s' % (label, p, rest)).rstrip())
