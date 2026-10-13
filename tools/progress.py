#!/usr/bin/env python3
"""progress.py: the disassembly's state, in several measures. Run from the repo root
after tracing (build/trace.json, see the README's Build section).

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


docs = ''.join(open(f, encoding='utf-8').read() for f in sorted(os.listdir('.')) if f.endswith('.md'))
documented = sum(1 for a, n in facts.NAMES.items() if a in subs and n in docs)
level = {'solid': 'high', 'likely': 'medium', 'guess': 'low'}

# The shared layout (the Dreamcast decomps' too): the main metric first, the one that reads
# 100% when the project is complete; for a disassembly that is the ROM mapped (every byte known
# as code, art or data). Then the game code, and what this disassembly measures on its own.
rows_out = [
    ('ROM MAP (facts.REGIONS)', '', '%d regions: %d high, %d medium, %d low confidence'
     % (len(facts.REGIONS), conf['solid'], conf['likely'], conf['guess'])),
    ('  mapped, bytes', pct(mapped, ROM_SIZE), 'high and medium confidence ranges'),
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
