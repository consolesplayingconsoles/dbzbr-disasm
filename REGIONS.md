# What lives where

Functional map of the French/English ROM, built from the text sweep
(`tools/scan.py`), the pointer idiom (`tools/xref.py`) and the code trace.
Confidence is marked: **solid** = read it and it says so, *likely* = strong
structural evidence, ? = guess.

The ranged rows are also in `REGIONS` in `tools/facts.py`, which the tools and
`tools/progress.py` read: a range that changes here changes there too.

## Code

| range | what | confidence |
|---|---|---|
| `000200-000540` | boot, region/TMSS check, checksum, RAM clear, VDP init | solid |
| `000412` | main loop; `ram_E6A4` = game mode, dispatched via `bra.w` table at `00045E` | solid |
| `003FEA`, `004396` | vertical / horizontal interrupt handlers | solid |
| `1ADE1C-1AF347` | early-boot subsystem called before anything else (`jsr $1ade1c` at `0003DA`); sound driver? | *likely* |
| scattered `004000-04Bxxx` | engine proper; ~106 KiB traced in total | solid |

## Character and stage data

| range | what | confidence |
|---|---|---|
| `00A038-00A04D` | character-name pointer table, 11 self-relative words | solid |
| `00A04E-00A0E9` | **the roster**: GOKU, GOHAN, PICCOLO, VEGETA, TRUNKS, CELL, N°16?, KURILIN, FREEZA, REKUM, GINYU | solid |
| `00A0EA-00A0FF` | 11 words, one per character, pointing into the records below; several characters share a record | solid |
| `00A100-00A14F` | per-character records of `(word, word)` pairs, five distinct records shared across the roster; move-slot or command layout | *likely* |
| `00A9A2-00AA67` | **move-set table**, 18 bytes per fighter: 9 `(move index, command index)` pairs. Read at `0091EE`, stride computed as `18 * id` | solid |
| `00AA68-00AA89` | command icon tiles: one tile word per icon, indexed by the icon code (a byte offset) | solid |
| `00AA8A-00AB38` | **command icon table**: 25 commands x 7 icon codes, the input the move list screen draws for each command (`DrawMoveCommand` at `009998`; codes in `COMMAND_ICONS`, `tools/facts.py`) | solid |
| `00A150-00A1E3` | **move-name pointer table**, 74 self-relative words | solid |
| `00A1E4-00A9A1` | **move names**: TRIPLE BLAST, KAMEHAMEHA, MASENKO, BIG BANG, FINAL FLASH, DEATH BALL, GINYU SMASH … each preceded by a small word (cost or animation id?); `$FFFF` at `00A9A0` ends the last | solid / ? |
| `03A768-03A811` | second copy of the roster names, for another screen | solid |
| `03A812-03A823` | stage-name pointer table, 9 self-relative words | solid |
| `03A824-03A8A2` | **stage list**: SCENE, CLIFF, ROCKS, KAMI TOWER, HIGHWAY, SEA, NAMEK, NAMEK ?, BEACH | solid |

## Roster plumbing

| what | where |
|---|---|
| P1 / P2 fighter id | `ram_8136` / `ram_8137` (`$FF8136`) |
| select-screen cursor wrap | `009A90` `cmpi.b #$a,d1` and `009A9E` `move.b #$a,d1`, both `$0A` |
| random fighter pick | `078384` and `078398`, both `cmpi.b #$a,d0` on the RNG result |
| grid select cursor | `ram_E7B6` (P1) / `ram_E8DE` (P2), feeding `ram_8136` at `008BE2`. Its own wrap is **not located yet** |
| name lookup | `00914E`: `id*2` into the table at `00A038` |
| move-set lookup | `0091D4`: `id*18` into `00A9A2`, each byte indexing `00A150` |
| per-character record | `009810`: `id*2` into `00A0EA` |

Free space for relocated tables (single-byte runs of 2 KiB or more, ~70 KiB
total): `07C624` 14.8 KiB, `1B7A0E` 34.3 KiB, `1C5159` 11.9 KiB, `1DF222`
3.5 KiB, `1F69DF` 5.6 KiB, `0451F8` 2 KiB.

## Palettes

| what | where |
|---|---|
| fighter palettes | bank A `$080064`, bank B `$0801E4`, 32 bytes per fighter |
| chosen at | `00D1E2` (P1), `00D208` (P2), both `lea abs.l` |
| portrait palettes | bank A `$03F55A`, bank B `$03F6BA`, same shape, indexed through a byte table at `$03C30E` |
| chosen at | `007324`/`007398` (VS screen), `03BD7C`/`03BDDC` (select), `034888` (VS, CRAM line 1) |
| portrait loader | `sub_03BD42`, `ram_EA00` picks the player. No direct callers: reached through a word-offset table, and it only runs when the selection changes |

Bank B is the set the game uses by itself when both players pick the same
fighter. Every one of these sites has that same mirror-match test next to it.

Do NOT call the fighter palette load while the select screen is up: it writes
the same CRAM lines the portraits use, and the portraits come out wrong.

## Input

| what | where |
|---|---|
| face buttons, P1 / P2 | `$FFE666` / `$FFE668`. Bit 4 = B, bit 5 = C, bit 6 = A |
| the other pad half | `$FFE667` / `$FFE669`, bit 7 = start. Only lights up in combination, so it is easy to mistake for the button byte |
| pad read | `sub_003FD4`: calls the decoder, then copies a word from each player's block into `$E666` / `$E668`. Called from many screens, the select grid included |

Verified on hardware with a probe ROM that flashed the screen while a candidate
byte showed a button. Do not infer this layout, it cost several rounds.

### Motion commands

`InputHistory` (`$006308`) keeps each fighter's last 16 d-pad changes with how
long each was held; `MatchCommand` (`$0063F0`) reads them when the punch or kick
button is pressed, and again when it is let go. The command tables at
`$006534` (punch), `$0065A6` (kick) and `$0065FD` (punch, another mode) list
each command as: step count, steps newest first, 0, command number (the
`CommandIconTable` index). Directions are relative to the fighter's facing
(4 back, 8 forward, 1 up, 2 down; diagonals combine), and the longer commands
come first. Timing rules and field offsets: `INPUT_HISTORY` in `tools/facts.py`.

## Script

Dialogue records are fixed width (`$6E` bytes, three pre-padded lines), so a
translation must fit its slot.

| range | what | confidence |
|---|---|---|
| `034286-03455A` | short fight quotes, one screen each ("What a strength.", "You beat me.") | solid |
| `035326-038D26` | **script block 1**, ~14.8 KiB: post-fight and progression lines | solid |
| `078ADA-07C624` | **script block 2**, ~15.2 KiB: pre-fight taunts and story lines | solid |
| `03E55E-03F3DC` | the word "versus" repeated: the VS screen's own tilemap, not script | *likely* |
| `04BBE8`, `04C7D2` | punctuation-only hits; number/counter tilemaps? | ? |

## Learned from other people's patches

Five IPS patches for the Japanese ROM (in `dist/`) are a labelled dataset:
`tools/ips.py` prints the regions each one writes.

| patch | writes | so that region is |
|---|---|---|
| colour hack, DONUS | `08006A-080340` | **palettes** (verified: 64/64 words are Mega Drive colour-shaped) |
| Sprites Improvement (replaces every Android 18 frame) | `1038D3-1769C9` | **sprite/animation art** |
| same patch (hitboxes, projectile positions) | `07A726-07D5CF` | frame/hitbox tables (JP offsets) |
| Voice Hack | `1AE067-1B5CF7`, `1D0C78-1D7F4D` | **sound driver + PCM**, confirming `1ADE1C` |
| Voice Hack | `200000-236DA1` | it **expands the ROM past 2 MiB**, so expansion is precedented |
| all of them | `00018E`, and the boot code | the checksum, which they disable rather than fix |

Note JP and EU offsets only agree above `07C623`. Below that the two builds
differ, so a JP patch's offsets do not transfer to the French ROM.

## Graphics

The sweep also reports runs of sequential letters (`abcdefg`, `mnopqrstuvwxyz`).
Those are **not** text: they are uncompressed nametables where tile indices
happen to run consecutively. They mark where the graphics layouts live:
`18D95A-18F2C6`, `1902C2-19140E`, `193A3E-195B76`, `199622-199D9A`,
`19B71C-19E0E0`, and the large `19E6E6-1A6306`.

Everything else above `0C0000` that the trace never reaches, and the big gaps
below it, is asset payload at entropy 6.5 to 7.2.

## Still unknown

* Fighter stats (health, damage, speed): no table identified.
* The grid select screen's cursor bound (the `ram_E7B6` one). Patching the
  `ram_8136` wrap alone may not make a 12th fighter reachable there.
* Which screens the three remaining portrait-palette loads serve (`03390A`,
  `043A28`, `044044`).
* Per-character sprite, animation and AI data: not located. This is the part
  that decides whether a new fighter can be more than a reskin.
* The word before each move name looks like a ki cost (values 1 to 8), unconfirmed.
* Uppercase/lowercase aside, digits and most punctuation are unmapped glyphs.
