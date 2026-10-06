#!/usr/bin/env python3
"""progress.py: the disassembly's state, in several measures. Run from the repo root
after tracing (build/trace.json, see the README's Build section).

  traced       code the tracer reached, and the indirect calls it still can't follow
  named        subroutines and RAM variables with a name (tools/facts.py NAMES)
  mapped       facts.REGIONS by confidence, and the bytes the solid and likely ones cover
  art, text    fighter frames identified (GOKU_POSES), font glyphs decoded (tools/text.py)
"""
import json, os, sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import facts, text

ROM_SIZE = facts.ROM_SIZE
if not os.path.exists('build/trace.json'):
    sys.exit('progress.py: no build/trace.json (trace the ROM first)')
t = json.load(open('build/trace.json'))

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
mapped = sum(e - s + 1 for s, e, _, level in facts.REGIONS if level != 'guess')

empty = 7                                    # Goku's empty frames: 49, 50, 54-57, 81 (facts.py)
goku = facts.GOKU_FRAMES - empty


def pct(a, b):
    return '%5.1f%%' % (100.0 * a / b) if b else '-'


rows_out = [
    ('CODE (French ROM, traced)', '', '%d bytes, %d instructions' % (code, len(t['starts']))),
    ('  traced code, of the ROM', pct(code, ROM_SIZE), 'the rest is art and data'),
    ('  named subroutines', pct(named_subs, len(subs)), '%d of %d' % (named_subs, len(subs))),
    ('  named RAM variables', pct(named_ram, len(ram)), '%d of %d referenced' % (named_ram, len(ram))),
    ('  dispatch tables', '-', '%d jump, %d pointer, %d mode' % (kinds.get('jt', 0), kinds.get('ptrtable', 0), kinds.get('mode', 0))),
    ('  indirect calls unresolved', '-', '%d' % len(t['unresolved'])),
    ('ROM MAP (facts.REGIONS)', '', '%d regions: %d solid, %d likely, %d guess' % (len(facts.REGIONS), conf['solid'], conf['likely'], conf['guess'])),
    ('  mapped, bytes', pct(mapped, ROM_SIZE), 'solid and likely ranges'),
    ('ART AND TEXT', '', ''),
    ('  Goku frames identified', pct(len(facts.GOKU_POSES), goku), '%d of %d' % (len(facts.GOKU_POSES), goku)),
    ('  font glyphs decoded', '-', '%d' % len(text.FONT)),
]
for label, p, rest in rows_out:
    print(('%-28s %6s  %s' % (label, p, rest)).rstrip())
