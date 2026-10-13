# Dragon Ball Z: L'Appel du Destin disassembly

A traced disassembly of the Mega Drive **Dragon Ball Z: L'Appel du Destin** (the French release of
*Buyuu Retsuden*): a recursive-descent tracer, a labelled listing, a functional map of the ROM and a
facts module that states every address and layout once.

**This repository contains no game code or data.** You supply your own ROM: every tool takes its
path, and the trace and the listing are generated on your machine into `build/`, which git ignores.

## Supported version

| Release | Size | SHA-1 | Used for |
|---|---|---|---|
| L'Appel du Destin (France) | 2,097,152 | `5ff71986f4911b5dfd16598a5a3a9ba398c92c60` | the trace target: every address in `tools/facts.py` |
| Buyuu Retsuden (Japan) | 2,097,152 | `dc6336dfbbe76c24ada735009d0d667ce27843f6` | diff partner, and the base of the third-party patches |
| France + English fan translation | not recorded | `cf7be325e6387e7d27c853a018139db1833434d2` | diff partner: the text |

Diffing the French ROM against the English patch gives 43 KiB across 40 tight
regions, and that diff *is* the text map: far cheaper than searching for it. The Japanese ROM differs from the French one across ~500 KiB
(`002296-07C623` plus `1A8EA4-1B7684`), so it is a layout change, not a simple
language swap; do not assume JP offsets carry over.

## Building

```bash
python3 -m venv .venv && .venv/bin/pip install capstone
.venv/bin/python tools/trace.py <rom> build/trace.json
.venv/bin/python tools/emit.py  <rom> build/trace.json build/dbz.asm
```

Directories: `dist/` source ROMs and third-party patches, `build/` regenerable
analysis. Both untracked. This repo builds no ROMs; mods do that, into their own
`rom/`.

Outputs (all under `build/`, untracked):

| file | what |
|---|---|
| `trace.json` | instruction starts, labels, dispatch tables, data refs, untraced gaps |
| `dbz.asm` | labelled + symbolised listing, one line per instruction, xref comments |
| `dbz-MAP.md` | mode table, offset tables, work-RAM variable index |

## What is here

| | |
|---|---|
| `tools/facts.py` | every address and layout, measured where measurement was needed, and the listing's names |
| `REGIONS.md` | the functional map of the ROM, with a confidence marker per row (its ranges are `REGIONS` in `tools/facts.py`) |
| `tools/` | the tracer and the analysis tools (below) |
| `tools/progress.py` | the Progress block below |

* `tools/trace.py`: recursive-descent 68000 tracer. Seeds from the vector table
  and follows every statically resolvable branch, plus two dispatch idioms this
  engine uses everywhere (see below). Prints coverage, gaps, and the sites where
  the trace still loses the trail.
* `tools/emit.py`: turns a trace into the listing and the structure map.
* `tools/listing.py`: dump one address range from an existing trace.
* `tools/text.py`: decode on-screen text; `text.py <rom> <start> <end> [font]`.
* `tools/mapdump.py`: coarse entropy/decodability map of the whole ROM.

## Progress

<!-- progress -->
```
ROM MAP (facts.REGIONS)                28 regions: 18 high, 10 medium, 0 low confidence
  mapped, bytes                 27.7%  high and medium confidence ranges
GAME CODE (French ROM, traced)         1189 subroutines, 106254 bytes of code
  named                          1.2%  14 of 1189 subroutines (tools/facts.py NAMES)
  unnamed                       98.8%  1175 subroutines (sub_...)
  documented                     0.3%  3 named subroutines in *.md
  named globals                     -  5 of 384 RAM variables referenced
  traced code, of the ROM        5.1%  the rest is art and data
  dispatch tables                   -  39 jump, 70 pointer, 39 mode
  indirect calls unresolved         -  5
ART AND TEXT
  Goku frames identified        41.8%  33 of 79
  fighters identified          100.0%  11 of 11 (roster order)
  font glyphs decoded               -  74
```
<!-- /progress -->

Updated on every commit by `tools/hooks/pre-commit` from `tools/progress.py` (enable once per
clone: `git config core.hooksPath tools/hooks`; it needs a trace in `build/`).

~106 KiB traced as code across 29.6k instructions and 4.2k labels, with 5
register-indirect call sites still unresolved. The remaining ~1.9 MiB is asset
payload (entropy 6.5 to 7.2, i.e. compressed or dense graphics), not code.

## Engine

* Reset `000206`, boot and checksum at `000300`, VDP init `000596`.
* Main loop `000412`: `ram_E6A4` is the game mode; `jsr tbl_00045E(pc,d0.w)`
  dispatches into a table of `bra.w` slots, one per mode.
* The engine's pervasive dispatch idiom is a **self-relative word table**:

  ```
  lea     base(pc,d0.w), a0
  adda.w  (a0), a0            ; entry is a signed word
  jsr     (a0)                ; target = entry address + word
  ```

  `trace.py` resolves these, which is what takes coverage from 0.2% to ~5%.
* Work RAM starts at `$FFFE00` (stack) with game state from `$FFE000` up;
  the listing names these `ram_XXXX`.

## Text

Text is stored as raw VDP tilemap words, one word per glyph, `$FFFF` terminated.
A stored line is already laid out, padded with spaces to the box width, so a
replacement has to fit the same slot.

Two font banks with different layouts (both solved in `tools/text.py`): the
name font runs `a..k` from `$0E5` and `l..z` from `$100`; the menu font runs
`a..l` from `$064`, `m` at `$080`, `n..z` from `$082`. Uppercase, digits and
most punctuation are still unmapped and print as `{XXX}`.

```
$ .venv/bin/python tools/text.py <rom> 0x35326 0x35460 menu
035326  {0ED}l faut           t'entrainer       plus.
035394  {0EE}e reste le       meilleur.
```

Known text: the move-name table at `00A1E6`, and script/menu data around
`035326`, `047xxx`, `04Bxxx` and `078xxx-07Cxxx`.

## Mods

The mods moved to a separate repository, which uses this repo as a
submodule. This repo describes the stock game; a mod says what it changes, and
imports the addresses from `tools/facts.py` rather than restating them.

The two mod kits below live there now; their sections stay here as the record of how they work.

### Roster mod kit

`tools/roster.py` makes the fighter roster data-driven. Dump it, edit the JSON,
build a new ROM:

```bash
.venv/bin/python tools/roster.py dump  <rom> roster.json
.venv/bin/python tools/roster.py build <rom> roster.json out.md
```

A character is one JSON entry:

```json
{
 "name": "SANGOKU SSJ",
 "name_short": "SSJ",
 "assets_from": 0,
 "moves": [[36, 0], [0, 1], [1, 2], [2, 3], [4, 4], [17, 17],
           [8, 8], [7, 7], [6, 6]]
}
```

`name` is the select screen, `name_short` the second screen. `assets_from`
names the stock fighter whose animation record this one borrows, which is what
lets a new fighter cost no art. Each of the nine moves is
`[move index, command index]`; move indices come from the `move_names` list the
dump writes out, so no new text is needed to add a fighter.

What the builder does for you:

* resizes the four roster tables and, when one outgrows its slot, relocates it,
  preferring space it just reclaimed over guessed filler and never over code
* repoints the reading code, adding a `bsr.w` trampoline where a `lea d16(pc)`
  can no longer reach (the 68000's short-reach addressing is the real
  constraint here, not free space)
* widens the select-screen cursor bounds
* recomputes the header checksum, without which the boot code hangs at `000506`

Two properties worth keeping if you extend it: rebuilding the stock 11-fighter
roster reproduces the original ROM **byte for byte**, and a built ROM dumps back
to the JSON it was built from. Both are quick regression tests.

Roster sizes up to 64 build. Beyond that the record pointer table runs out of
space within reach of the records it points at, and the builder says so instead
of emitting a broken ROM.

**Untested in game.** The tables, the pointers and the checksum are verified by
construction and by round trip, but no build has been run on hardware yet.

### Colour-set picker

`tools/colours.py` makes the second palette bank selectable:

```bash
.venv/bin/python tools/colours.py <rom> rom/out.md --button A
```

Every fighter already has two colour sets: bank A at `$080064` and bank B at
`$0801E4`, the one the game uses by itself when both players pick the same
character. The patch gives each player a variant byte, flips it on a button
press, and has the palette loader honour it. No new art is involved.

Three size-neutral swaps, so no code moves: the input handler's first two
instructions become a call to a stub that repeats them and adds the button
check, and the two `lea palette_bank` become calls to a picker. The variant
bytes live at `$FFEA3C`, work RAM that is cleared at boot and that no
instruction in the ROM names.

C is confirm on that screen, so the toggle defaults to A.

## See it in action

See what mods Pluto has helped me build from disassemblies like this one, with gameplay on real hardware:

- 📸 **Instagram:** [@consolesplayingconsoles](https://www.instagram.com/consolesplayingconsoles/)
- 🔗 **Everything else:** [beacons.ai/consolesplayingconsoles](https://beacons.ai/consolesplayingconsoles)

## Third-party sources

The English fan translation is used only to diff against the French ROM; it is not included.
Dragon Ball Z and its publisher's trademarks belong to their owners. This project is not affiliated
with or endorsed by them.

## Licence

© 2026 consolesplayingconsoles. Free software under the **GNU General Public License v3.0 or later** ([GPL-3.0-or-later](LICENSE)): use it, study it, share it, modify it. Derivative works stay under the same licence, so what gets built on this stays open too.

This covers the tools and notes in this repo. It does not cover the original game, its ROM or its code, none of which are included.
