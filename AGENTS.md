# Working on this disassembly

This repo rebuilds the game's ROM byte for byte. Keep it that way: every change ends with
`bash build.sh` printing `MATCH`.

The disassembly is done when every byte of the ROM is source: code in **named routines with
symbolic operands** (no ROM address left as a number, so an edit that moves code still builds) and
data in **named blocks of a decoded format**. `python3 tools/progress.py` measures exactly that as
its first row, `done: equivalent source`. Nothing else counts toward it: a map of the ROM, traced
code or decoded art are progress, reported below it, not the goal.

## Layout
- `tools/facts.py`: the source of truth. Every address, name and layout is recorded here, and the source
  is generated from it: you change the facts, never the generated files.
  - `NAMES`: address -> name, for routines, labels, RAM variables and data blocks
  - `BLOCKS`: `(start, end, name, format)` per data block; `format` is what decodes it
  - `POINTERS`: instructions whose immediate is a ROM address (it becomes a label)
  - `NOT_CODE`: ranges the trace took for code that are data
- `traces/trace.json`: the trace (addresses only). Re-trace with `python3 tools/trace.py` and new seeds when
  you find code it missed.
- `build/src/`: the generated source (`main.asm`, `code/<routine>.asm`, `data/<block>.bin`). Yours,
  never committed: it holds the game.
- `traces/rebuild.json`: what the last build emitted (addresses, names, formats; no game bytes). Committed:
  the progress report reads it.

## The loop
1. **Read a routine** in `build/src/code/`, with the trace's cross references
   (`python3 tools/xref.py build/rom.bin <addr>`) and the notes.
2. **Name it** in `NAMES` (and its RAM variables). A name is a claim about what it does: name only
   what you have read; leave `sub_<addr>` where you have not.
3. **Make it symbolic**: a routine that is not symbolic still has a ROM address as a number. Most
   are immediates loading a table or a handler (`move.l #$2392, ...`): add the instruction's
   address to `POINTERS`. A `dc.w` with a comment is an instruction AS encodes differently, or
   data the trace took for code (`NOT_CODE`).
4. **Data**: give each block between routines a name and a format in `BLOCKS`, once a tool here
   decodes it (compressed art, sprite frames, palettes, text, tables).
5. `bash build.sh`: `MATCH`, then `python3 tools/progress.py`. Commit; the pre-commit hook writes
   the report into the README.

A name or a format is evidence-backed or it is not there. Never name in bulk from guesses to move
the number: the number then measures nothing.
