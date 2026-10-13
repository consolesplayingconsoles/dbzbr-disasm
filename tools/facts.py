#!/usr/bin/env python3
"""What the stock game is: addresses, layouts and how to find them.

Everything here describes an UNMODIFIED ROM. Nothing here writes bytes. Mods
import this through the submodule so that a fact is stated once, here, and a
mod only says what it changes.

Addresses marked "measured" were established by running a probe ROM on real
hardware, not by reading the disassembly. Reading alone got several of them
wrong; do not silently "correct" them from code inspection.
"""
import re, struct
from text import FONT

# ---- ROM identity --------------------------------------------------------
KNOWN = {
    'dc6336dfbbe76c24ada735009d0d667ce27843f6': 'Buyuu Retsuden (Japan)',
    '5ff71986f4911b5dfd16598a5a3a9ba398c92c60': "L'Appel du Destin (France)",
    'cf7be325e6387e7d27c853a018139db1833434d2': "L'Appel du Destin (F) + English patch",
}
SIZES = {                 # measured (files at hand); the English build's is not recorded
    'dc6336dfbbe76c24ada735009d0d667ce27843f6': 2097152,
    '5ff71986f4911b5dfd16598a5a3a9ba398c92c60': 2097152,
}
ROM_SIZE = 2097152        # the French ROM, the trace target
CHECKSUM = 0x18E          # boot sums $000200..end and hangs at $000506 on mismatch

# ---- input ---------------------------------------------------------------
# MEASURED. The face buttons are in the EVEN byte; the odd byte next to it is
# the other half of the pad read (bit 7 = start) and only lights in combination.
PAD_P1, PAD_P2 = 0xFFE666, 0xFFE668
BUTTON = {'B': 0x10, 'C': 0x20, 'A': 0x40}
PAD_READ_TAIL = 0x003FE2  # `move.w $e6e2.w,$e668.w` at the end of sub_003FD4;
                          # replacing it is a size-neutral place to hook input

# Motion input (read from the code, $006308 and $0063F0). Per fighter: a ring of
# 16 (value, frames held) entries at $94, next free entry $B6, oldest $B7 (byte
# offsets), neutral frame count $B8, remembered button $B5, the punch/kick
# button bit numbers $BA/$BB, the command found $B9 ($FF = none). A value is
# the held pad byte with left/right swapped when the fighter faces left, so
# bit 2 = back and bit 3 = forward; a change of value is a new entry, neutral
# is not one but 12 neutral frames empty the history, and a value held 30
# frames drops everything older. On a press (or the release of the remembered
# button) the commands are tried in order: steps newest first from the newest
# entry, each matched entry held at most 12 frames, a non-matching entry held
# under 4 frames skipped, otherwise the command fails; a step with bit 7 set
# needs its entry held at least 30 frames (a charge). The history is emptied
# after every press. The command number is the CommandIconTable index.
INPUT_HISTORY = dict(ring=0x94, head=0xB6, tail=0xB7, idle=0xB8, edge=0xB5,
                     command=0xB9, punch_bit=0xBA, kick_bit=0xBB, entries=16,
                     quick=12, noise=4, idle_frames=12, hold=30)
INPUT_COMMANDS = {'punch': 0x006534, 'kick': 0x0065A6, 'punch_alt': 0x0065FD}

# ---- screens -------------------------------------------------------------
MODE_VAR    = 0xFFE6A4    # game mode, dispatched through the bra.w table at $45E
SELECT_MODE = 0x24        # MEASURED. Inferring this from the mode table's
                          # address ranges gives $20, which is wrong.

# ---- palettes ------------------------------------------------------------
# Bank B is what the game uses by itself when both players pick the same
# fighter. 32 bytes (16 colours) per fighter in every bank.
FIGHTER_BANK_A, FIGHTER_BANK_B = 0x080064, 0x0801E4
FIGHTER_SITES = {'P1': [0x00D1E2], 'P2': [0x00D208]}

PORTRAIT_BANK_A, PORTRAIT_BANK_B = 0x03F55A, 0x03F6BA
PORTRAIT_SLOT_TABLE = 0x03C30E    # byte per fighter -> palette slot
PORTRAIT_SITES = {                # read one at a time; proximity guessing lies
    'P1': [0x007324,              # pre-battle VS screen
           0x03BD7C],             # character select
    'P2': [0x007398,              # pre-battle VS screen
           0x034888,              # VS screen, CRAM line 1
           0x03BDDC],             # character select
}
# Mirror-match paths that already force bank B, left alone: $0073A8, $034880,
# $03BDD4. Three more loads of bank A are unclassified: $03390A, $043A28, $044044.
FIGHTER_RELOAD  = 0x00D1D6        # reloads both fighters' palettes (d2 = which)
PORTRAIT_RELOAD = 0x03BD42        # the game's own reload; ram_EA00 picks player.
EA00 = 0xFFEA00                   # Only runs on selection change. Calling it off
                                  # the select screen repaints portraits wrongly.

# ---- what each palette index paints --------------------------------------
# Established on hardware, not guessed: a probe ROM rendered the fighter as a
# black silhouette with one group of indices lit white, cycling on a button, and
# the shape said which part each group covered. Naming them means a recolour can
# say "gi_mid" instead of "5", and be read by someone who has never opened the
# disassembly.
#
# Measured for GOKU. Other fighters very likely share the layout, since they
# share the mirror-match recolour, but none has been checked, so do not assume.
GOKU = {
    'gi_dark':      4,    # the gi. Top and pants share one ramp, so they cannot
    'gi_mid':       5,    # be coloured separately without editing the art.
    'gi_light':     6,
    'trim_mid':     8,    # boots, belt, undershirt and bracelets together. Too
    'trim_light':  11,    # light and the boots look wrong, too dark and the
                          # shirt reads as black.
    'skin_mid':     1,    # skin, and its highlight
    'skin_light':  15,
    'skin_shadow':  9,    # lights with skin and chest, NOT with the trim: it
                          # looks blue in the stock palette but is not the shirt
    'skin_hi_1':    2,
    'skin_hi_2':    3,
    'outline':     14,
    'hair_1':      12,    # the Super Saiyan hair
    'hair_2':      13,
    'shade_1':      0,    # shading on arms and boots
    'shade_2':      7,
    'shade_3':     10,
}

# ---- roster --------------------------------------------------------------
# Fighter index (the art, OAM and palette tables' entry) -> the name in the roster
# list at $00A04E, in the same order. Checked by extracting each fighter's frames
# (the Wait, this is not Namek mod builds its badniks from them).
FIGHTERS = ['SANGOKU', 'SANGOHAN', 'PICCOLO', 'VEGETA', 'TRUNKS', 'CELL', 'N°18',
            'KURILIN', 'FREEZER', 'LIKUM', 'GINIOU']
MOVES_PER_CHAR = 9        # 9 (move index, command index) pairs, 18 bytes each
# The immediate byte is the LAST byte of the instruction, not the address the
# disassembly prints. Getting this wrong points the patch at the high half of an
# immediate word, which reads $00 and silently does nothing.
# The cursor on the character-select GRID (the screen that shows every name at
# once) lives at $03BF98 and moves $58(a0) with four direction cases. Two of
# them carry the roster size, and both must change together:
#   right  $03BFAB  "== last index", $0A -> $0B
#   down   $03C01F  "index + 3 must still be on the grid", $08 -> $09
# Left stops at zero and up stops below the first row, so neither cares.
# Found by widening the trace from the mode $24 step table: this routine sits in
# code the vector-table trace never reaches, which is why reading alone missed
# it through several rounds.
SELECT_GRID_RIGHT = 0x03BFAB
SELECT_GRID_DOWN  = 0x03C01F
# The CPU/demo picker rolls a random number modulo the roster size:
# `divu.w #$b,d0` at $03BF68, so the divisor byte is at $03BF6B.
SELECT_CPU_MODULO = 0x03BF6B
# The roster size is not one number. Known so far: the two grid bounds above,
# this modulo, the two select-cursor bytes the roster kit patches, and the two
# random-pick bytes. Assume there are more until a build proves otherwise.

ROSTER_GRID_BOUNDS = [0x00D30B, 0x00D311]   # a DIFFERENT screen's cursor, $0A
ROSTER_RANDOM_BOUNDS = [0x078387, 0x07839B] # random pick, both $0A
ENABLE_TABLE = 0x080000   # longs per fighter; a zero entry means "skip this slot"

# What a 12th fighter (index 11) finds already in place, and what it does not:
#   enable table       entry 11 is non-zero, so the cursor would not skip it
#   fighter palette    slot 11 exists at $0801C4, before bank B starts, and
#                      already holds colours: something uses index 11 already
#                      (see the `move.b #$b,ram_E7B6` at $04A47A)
#   portrait slots     the byte table at $03C30E reads $FF at index 11: unset
#   portrait art       the word table at $03A448 index 11 points at an odd
#                      address, so it is not a real entry
PORTRAIT_ART_TABLE = 0x03A448     # self-relative words, P1; P2's is at $03A4AA

# ---- fighter sprites -----------------------------------------------------
# ENABLE_TABLE is also the fighter ART table: entry N -> that fighter's block of
# frame pointers (longs), one LZSS stream per frame (LzssToRam's format). Entry
# 11 ($0E6D66) points into fighter 5's art: it is not a real block.
FIGHTER_ART_TABLE = ENABLE_TABLE
FIGHTER_OAM_TABLE = 0x080034   # longs per fighter -> sprite-piece block, after
                               # that fighter's art (fighter 10's is at $17542A)
# OAM block: frame f's entry is blk + f*2, its data at entry + s16(entry), i.e.
# relative to the ENTRY, not the block. Data = count word, then 6-byte pieces:
# word (tile 0-10, xflip bit 11, yflip bit 12), X s8, Y s8 (origin at the feet),
# a byte ($FF/$F0), size (w-1)<<2 | (h-1). Tiles in a piece are column-major; a
# frame's piece tile counts sum to its decompressed art size.
# A frame block does not end at its first bad entry: Goku's has 86 frames, with
# empty 2-byte streams at 49, 50, 54-57 and 81.
GOKU_FRAMES = 86
# Special-move projectiles are not in the fighter frames: LoadSpecialArt loads
# them on demand over the fight-start art at $9000 (tile $480) and $9800 ($4C0).
# Entry 0 is the Kamehameha beam: $0219E8 (35 tiles) + $021B20 (38 tiles),
# matched tile for tile against a screenshot of the beam. Entry 9 (the same
# stream as entry 8, $0234DE) holds Goku's energy blast: tiles 37-39 are the top
# row of the fireball, drawn twice (the bottom y-flipped), tail behind; matched
# tile for tile against a recording.
# The power-up aura (the flame egg before a fight): its 45 tiles are part of the
# fight art at $0088A6 (LoadFightArt, VRAM $A260 = tile $513), and its sprite frame,
# 23 pieces mirrored left and right and filled with colour 15, is at $0070BC (again
# at $021752). Extracted and used by the Wait, this is not Namek mod.
AURA = dict(art=0x0088A6, vram_tile=0x513, tiles=45, frame=0x0070BC, frame_copy=0x021752)
# Goku's poses, named by the operator and matched against gameplay recordings
# (a flight, a Goku vs Vegeta fight, and 30 minutes of story mode matched frame
# by frame), not read from the animation scripts, which are not located yet.
# The special moves' frames are in the order the recording plays them.
GOKU_POSES = {
    0: 'stand', 5: 'fight stance', 7: 'crouch: take-off, landing', 8: 'rising',
    9: 'jump knee lift: rising', 10: 'jump knee lift: crouch', 11: 'jump, falling', 15: 'guard', 16: 'hover',
    17: 'run back', 18: 'run, fly forward', 19: 'dash', 20: 'dash',
    30: 'jab', 31: 'dash elbow', 32: 'dash elbow: lunge',
    35: 'jump knee lift: knee (also the flurry kick, between 38 and 39)',
    36: 'side kick', 37: 'flurry kick: low chamber', 38: 'flurry kick: kick', 39: 'flurry kick: chamber',
    40: 'flurry kick: high kick', 46: 'air punch (down)', 48: 'air kick (down)',
    51: 'energy blast: wind-up', 52: 'energy blast: palm out (held while it flies)',
    63: 'hit: lifted', 64: 'hit: knocked back', 65: 'knocked down',
    66: 'knocked down', 67: 'down', 76: 'Kamehameha: charge',
    77: 'Kamehameha: fire',
}

# ---- move list screen -----------------------------------------------------
# MOVESET (per fighter, 9 x (move index, command index)) gives each move a
# command; CommandIconTable has 7 bytes per command: the icons the screen shows
# for its input, left to right, 0 = blank. Each icon code is a byte offset into
# CommandIconTiles (one tile word per icon). Read from DrawMoveCommand and checked
# against Goku's published move list: every one of his 9 inputs matches.
# Directions are drawn for a fighter facing right.
COMMAND_ICONS = {
    0x04: 'up-forward', 0x06: 'forward', 0x08: 'down-forward', 0x0A: 'down',
    0x0C: 'down-back', 0x0E: 'back', 0x1E: 'punch', 0x20: 'kick',
    # 0x16-0x1C: four icons used only by commands 13 and 20, not identified yet
}

# ---- region map (French ROM) ----------------------------------------------
# (start, end inclusive, what, confidence). solid = read and confirmed; likely =
# strong structural evidence; guess. REGIONS.md tells the story behind each row;
# this list is what the tools and tools/progress.py read. Rows known only in
# Japanese offsets below $07C624 are left out: they do not transfer.
REGIONS = [
    (0x000200, 0x000540, 'boot: region/TMSS check, checksum, RAM clear, VDP init', 'solid'),
    (0x00A038, 0x00A04D, 'character-name pointer table, 11 self-relative words', 'solid'),
    (0x00A04E, 0x00A0E9, 'roster names', 'solid'),
    (0x00A0EA, 0x00A0FF, 'per-character record pointers, one word each', 'solid'),
    (0x00A100, 0x00A14F, 'per-character records, (word, word) pairs', 'likely'),
    (0x00A150, 0x00A1E3, 'move-name pointer table, 74 self-relative words', 'solid'),
    (0x00A1E4, 0x00A9A1, 'move names, each after a small word (ki cost?)', 'solid'),
    (0x00A9A2, 0x00AA67, 'Moveset: 9 (move, command) pairs per fighter', 'solid'),
    (0x00AA68, 0x00AA89, 'CommandIconTiles', 'solid'),
    (0x00AA8A, 0x00AB38, 'CommandIconTable: 25 commands x 7 icon codes', 'solid'),
    (0x006534, 0x006615, 'command tables: punch, kick, punch alt (INPUT_COMMANDS)', 'solid'),
    (0x034286, 0x03455A, 'short fight quotes', 'solid'),
    (0x035326, 0x038D26, 'script block 1: post-fight and progression lines', 'solid'),
    (0x03A768, 0x03A811, 'roster names, second copy', 'solid'),
    (0x03A812, 0x03A823, 'stage-name pointer table, 9 self-relative words', 'solid'),
    (0x03A824, 0x03A8A2, 'stage list', 'solid'),
    (0x03E55E, 0x03F3DC, 'VS screen tilemap', 'likely'),
    (0x078ADA, 0x07C624, 'script block 2: pre-fight taunts and story lines', 'solid'),
    (0x080064, 0x0801C3, 'fighter palettes, bank A, 32 bytes per fighter', 'solid'),
    (0x0801E4, 0x080343, 'fighter palettes, bank B (mirror matches)', 'solid'),
    (0x1038D3, 0x1769C9, 'sprite and animation art (a sprite patch rewrites it)', 'likely'),
    (0x18D95A, 0x18F2C6, 'uncompressed nametables', 'likely'),
    (0x1902C2, 0x19140E, 'uncompressed nametables', 'likely'),
    (0x193A3E, 0x195B76, 'uncompressed nametables', 'likely'),
    (0x199622, 0x199D9A, 'uncompressed nametables', 'likely'),
    (0x19B71C, 0x19E0E0, 'uncompressed nametables', 'likely'),
    (0x19E6E6, 0x1A6306, 'uncompressed nametables', 'likely'),
    (0x1ADE1C, 0x1AF347, 'early-boot subsystem: the sound driver', 'likely'),
]

# ---- names ---------------------------------------------------------------
# Labels for the listing (tools/emit.py uses these over sub_/off_/ram_ names).
# Each is what the code was read to do; nothing here changes a byte.
NAMES = {
    0x0017AA: 'LzssToRam',            # a0 = stream, a1 = destination
    0x0015D2: 'LzssToVram',           # a0 = stream, a1 = VRAM address; the same
    0x0015F0: 'LzssToVram_Data',      #   LZSS, written through a $2000 ring buffer
    0x00EA7C: 'LoadFighterFrames',    # both players: P1, then falls into P2
    0x00EAAC: 'LoadFighterFrame',     # d4 = fighter, d1 = frame, a1 = buffer
    0x006B24: 'LoadFightArt',         # $7A24, $7F48, $88A6 to VRAM $8000, $9000, $A260
    0x021978: 'LoadSpecialArt',       # d0 = special: its art pair to VRAM $9000, $9800
    0x0219A8: 'SpecialArtTable',      # 16 x (2 words, entry-relative; -1 = no second part)
    0x009998: 'DrawMoveCommand',      # move list screen: the selected move's input icons
    0x00A9A2: 'Moveset',              # MOVESET: 9 x (move, command) per fighter
    0x00AA68: 'CommandIconTiles',     # tile word per icon code (code = byte offset)
    0x00AA8A: 'CommandIconTable',     # 7 icon codes per command (COMMAND_ICONS)
    0x0062FC: 'RecordInputs',         # both fighters: InputHistory for P1, then P2
    0x006308: 'InputHistory',         # a0 = fighter: append/extend the d-pad history
    0x0063B6: 'InputFacing',          # swap left/right when the fighter faces left
    0x0063E4: 'MatchCommands',        # both fighters: MatchCommand for P1, then P2
    0x0063F0: 'MatchCommand',         # a0 = fighter: button pressed/released -> $B9 = command
    0x00650A: 'ButtonEdge',           # pressed byte, or the remembered button let go
    0x006534: 'PunchCommands',        # INPUT_COMMANDS: steps newest first, 0, command
    0x0065A6: 'KickCommands',
    0x0065FD: 'PunchCommandsAlt',     # used instead of PunchCommands in a mode ($E73C)
    0x080000: 'FighterArtTable',
    0x080034: 'FighterOamTable',
    0xFFE762: 'P1_Frame', 0xFFE7B6: 'P1_Fighter',
    0xFFE88A: 'P2_Frame', 0xFFE8DE: 'P2_Fighter',
}

# Anchors are matched by masked byte signature, never by fixed address: the
# Japanese ROM is the same engine at different addresses. '..' wildcards the
# bytes that legitimately differ (a lea displacement, the roster bound, and the
# addressing opcode itself once a site has been turned into a trampoline).
SIGS = {
    'name':      ('4240 1038 8136 D040 .... .... D0C0', 8, 1),
    'rec':       ('4240 1038 8136 D040 .... .... D4C0', 8, 1),
    'moves':     ('B038 8137 6700 .... D040 3200 D040 D040 D040 D041 .... ....', 20, 1),
    'moves2':    ('D041 D040 .... .... 4241 1230 0001', 4, 1),
    'name2':     ('1FE6 4240 .... .... 4E71 4241', 4, 3),
    'bounds':    ('1238 8136 0800 0004 660C 5201 0C01 00.. 630C 4201 6008 5301 6A04 123C 00..', 15, 1),
    'movenames': ('323C 0036 22C0 51C9 FFFC .... ....', 10, 1),
}


def rd16(rom, a):  return struct.unpack_from('>H', rom, a)[0]
def rds16(rom, a): return struct.unpack_from('>h', rom, a)[0]


def find_sig(rom, spec):
    pat, off, want = spec
    raw = pat.replace(' ', '')
    body = [None if raw[i:i + 2] == '..' else int(raw[i:i + 2], 16)
            for i in range(0, len(raw), 2)]
    fixed = [(i, b) for i, b in enumerate(body) if b is not None]
    first, fb = fixed[0]
    hits, at = [], -1
    while True:
        at = rom.find(bytes((fb,)), at + 1)
        if at < 0:
            break
        base = at - first
        if base < 0 or base + len(body) > len(rom):
            continue
        if all(rom[base + i] == b for i, b in fixed):
            hits.append(base + off)
    if len(hits) != want:
        raise SystemExit('anchor search found %d matches, expected %d' % (len(hits), want))
    return hits


def follow(rom, site):
    """Where a site points now: a direct lea, or through a trampoline."""
    op = rd16(rom, site)
    if (op & 0xF1FF) == 0x41FA:                       # lea d16(pc), aN
        return site + 2 + rds16(rom, site + 2)
    if op == 0x6100:                                  # bsr.w to a stub
        stub = site + 2 + rds16(rom, site + 2)
        if (rd16(rom, stub) & 0xF1FF) != 0x41F9:
            raise SystemExit('%06X does not look like a trampoline' % stub)
        return struct.unpack_from('>I', rom, stub + 2)[0]
    raise SystemExit('%06X is neither a lea nor a trampoline' % site)


def anchors(rom):
    """Locate every roster patch site in this particular ROM."""
    a = {k: find_sig(rom, v) for k, v in SIGS.items()}
    by_target = {}
    for site in a['name2']:
        by_target.setdefault(follow(rom, site), []).append(site)
    pair = [v for v in by_target.values() if len(v) == 2]
    if len(pair) != 1:
        raise SystemExit('could not tell the name table from the stage table')
    a['name2'] = sorted(pair[0])
    return {
        'LEA_NAME':      a['name'],
        'LEA_REC':       a['rec'],
        'LEA_MOVES':     a['moves'] + a['moves2'],
        'LEA_NAME2':     a['name2'],
        'BOUND_BYTES':   [a['bounds'][0], a['bounds'][0] + 14],
        'LEA_MOVENAMES': a['movenames'],
    }


def names_len(rom, ptrs, n):
    end = ptrs + 2 * n
    for i in range(n):
        a = ptrs + 2 * i + rds16(rom, ptrs + 2 * i)
        while rd16(rom, a) != 0xFFFF:
            a += 2
        end = max(end, a + 2)
    return end - (ptrs + 2 * n)


def layout(rom):
    """Every roster address, resolved from this ROM's own code."""
    a = anchors(rom)
    n = rom[a['BOUND_BYTES'][0]] + 1
    name_ptrs  = follow(rom, a['LEA_NAME'][0])
    rec_ptrs   = follow(rom, a['LEA_REC'][0])
    moveset    = follow(rom, a['LEA_MOVES'][0])
    name2_ptrs = follow(rom, a['LEA_NAME2'][0])
    move_ptrs  = follow(rom, a['LEA_MOVENAMES'][0])
    recs = [rec_ptrs + 2 * i + rds16(rom, rec_ptrs + 2 * i) for i in range(n)]
    a.update({
        'n': n,
        'NAME_PTRS': name_ptrs, 'NAME_END': rec_ptrs,
        'REC_PTRS': rec_ptrs, 'REC_END': min(recs),
        'MOVESET': moveset, 'MOVESET_END': moveset + 18 * n,
        'NAME2_PTRS': name2_ptrs,
        'NAME2_END': name2_ptrs + 2 * n + names_len(rom, name2_ptrs, n),
        'MOVE_PTRS': move_ptrs,
        'MOVE_COUNT': (min(move_ptrs + 2 * i + rds16(rom, move_ptrs + 2 * i)
                           for i in range(4)) - move_ptrs) // 2,
        'recs': recs,
    })
    return a


def fix_checksum(rom):
    """Boot sums $000200 to the end against $00018E. Every patch must do this."""
    total = 0
    for a in range(0x200, len(rom), 2):
        total = (total + rd16(rom, a)) & 0xFFFF
    struct.pack_into('>H', rom, CHECKSUM, total)
    return total

# ---- data blocks for the rebuild (tools/rebuild.py BLOCKS) ----------------------
# (start, end inclusive, name, format): a block counts as source only when every byte of it is what
# the format says, decoded by a tool here. Each range below was checked whole:
#   fighter art: one LZSS stream per frame (tools/lzss.py), after the fighter's frame pointer table
#   (FIGHTER_ART_TABLE entry; not a block: its longs are absolute addresses, source only once they
#   are written as labels), back to back: every stream decodes and ends at the next one's start,
#   or one zero byte before it (word alignment); empty frames are 2-byte streams. Vegeta's frame 97
#   points at the $FF fill after his art, not at a stream: his art ends at $0B5101.
#   sprite pieces: the fighter's OAM block (FIGHTER_OAM_TABLE entry): one self-relative word per
#   frame, a $FFFF terminator, then each frame's count word and 6-byte pieces, back to back, every
#   entry landing on one. Cell's is left out: his entries do not match his art's frame count.
#   palettes: every word a Mega Drive colour ($0BGR, even components). Names and stage list: every
#   word a glyph in text.FONT or $FFFF, the last one $FFFF. Pointer tables: every entry lands
#   inside its strings.
BLOCKS = [
    (0x00A038, 0x00A04D, 'character_name_pointers', 'pointer_table'),
    (0x00A04E, 0x00A0E9, 'roster_names', 'text'),
    (0x03A768, 0x03A811, 'roster_names_copy', 'text'),
    (0x03A812, 0x03A823, 'stage_name_pointers', 'pointer_table'),
    (0x03A824, 0x03A8A3, 'stage_names', 'text'),
    (0x080064, 0x0801C3, 'fighter_palettes_a', 'palette'),
    (0x0801E4, 0x080343, 'fighter_palettes_b', 'palette'),
    (0x0804BC, 0x09441E, 'sangoku_frame_art', 'lzss_frames'),
    (0x095902, 0x0A1702, 'sangohan_frame_art', 'lzss_frames'),
    (0x0A21F4, 0x0B5101, 'vegeta_frame_art', 'lzss_frames'),
    (0x0B61E4, 0x0C7914, 'trunks_frame_art', 'lzss_frames'),
    (0x0C8AA2, 0x0E4F3A, 'piccolo_frame_art', 'lzss_frames'),
    (0x0E6D6A, 0x102096, 'cell_frame_art', 'lzss_frames'),
    (0x103A40, 0x111512, 'c18_frame_art', 'lzss_frames'),
    (0x112722, 0x120B5E, 'kurilin_frame_art', 'lzss_frames'),
    (0x121D64, 0x13320C, 'freezer_frame_art', 'lzss_frames'),
    (0x134728, 0x15786A, 'likum_frame_art', 'lzss_frames'),
    (0x1594C8, 0x175419, 'giniou_frame_art', 'lzss_frames'),
    (0x094434, 0x095775, 'sangoku_sprite_pieces', 'oam_frames'),
    (0x0A1708, 0x0A2067, 'sangohan_sprite_pieces', 'oam_frames'),
    (0x0B5120, 0x0B6047, 'vegeta_sprite_pieces', 'oam_frames'),
    (0x0C7916, 0x0C890D, 'trunks_sprite_pieces', 'oam_frames'),
    (0x0E4F72, 0x0E6BD7, 'piccolo_sprite_pieces', 'oam_frames'),
    (0x11151A, 0x11258F, 'c18_sprite_pieces', 'oam_frames'),
    (0x120B7A, 0x121BC5, 'kurilin_sprite_pieces', 'oam_frames'),
    (0x13322C, 0x134599, 'freezer_sprite_pieces', 'oam_frames'),
    (0x157874, 0x15935F, 'likum_sprite_pieces', 'oam_frames'),
    (0x17542A, 0x1769B9, 'giniou_sprite_pieces', 'oam_frames'),
    # alignment fill: $FF up to a 32 KiB boundary (or the ROM's end), what an `align` writes
    (0x07C624, 0x07FFFF, 'pad_to_080000', 'fill'),
    (0x1B7A0E, 0x1BFFFF, 'pad_to_1C0000', 'fill'),
    (0x1C5159, 0x1C7FFF, 'pad_to_1C8000', 'fill'),
    (0x1CFE73, 0x1CFFFF, 'pad_to_1D0000', 'fill'),
    (0x1D7A28, 0x1D7FFF, 'pad_to_1D8000', 'fill'),
    (0x1DF222, 0x1DFFFF, 'pad_to_1E0000', 'fill'),
    (0x1E7EFA, 0x1E7FFF, 'pad_to_1E8000', 'fill'),
    (0x1EFFE4, 0x1EFFFF, 'pad_to_1F0000', 'fill'),
    (0x1F69DF, 0x1F7FFF, 'pad_to_1F8000', 'fill'),
    (0x1FFD93, 0x1FFFFF, 'pad_to_200000', 'fill'),
]

# Ranges the trace took for code that are data (tools/rebuild.py NOT_CODE): routines where at least 3
# and more than 30% of the "instructions" are encodings a 68000 does not have (68020 addressing modes, extension
# words AS cannot reproduce), mostly zero words read as `ori.b #0`. Tables the tracer walked into.
NOT_CODE = [
    (0x080026, 0x080033),   # FighterArtTable's last entries and its $FFFFFFFF end, read as code
    (0x00BB2C, 0x00BBC5),   # sub_00BB2C: 15 of 39 instructions not 68000 encodings
    (0x00BBC6, 0x00C389),   # sub_00BBC6: 176 of 523 instructions not 68000 encodings
    (0x00C38A, 0x00CA61),   # sub_00C38A: 200 of 479 instructions not 68000 encodings
    (0x00CA62, 0x00CCBB),   # sub_00CA62: 66 of 156 instructions not 68000 encodings
    (0x00D4F0, 0x00D513),   # sub_00D4F0: 9 of 9 instructions not 68000 encodings
    (0x00ED72, 0x00ED91),   # sub_00ED72: 6 of 8 instructions not 68000 encodings
    (0x01C396, 0x01C3B5),   # code_01C396: 3 of 8 instructions not 68000 encodings
    (0x032DCC, 0x032E3B),   # sub_032DCC: 14 of 29 instructions not 68000 encodings
    (0x03E2F2, 0x03E529),   # sub_03E2F2: 62 of 147 instructions not 68000 encodings
    (0x04AE88, 0x04AE95),   # loc_04AE88: 3 of 3 instructions not 68000 encodings
    (0x04DCCE, 0x04DCF7),   # sub_04DCCE: 7 of 10 instructions not 68000 encodings
]

# Tables of absolute longs into the ROM (tools/rebuild.py PTR_TABLES): written as labels, so they
# follow what they point at. Each fighter's frame table runs from its FIGHTER_ART_TABLE entry to
# its first LZSS stream.
PTR_TABLES = [
    (0x080000, 0x08002F, 'FighterArtTable'),       # 12 longs (entry 11 points into Cell's table), then $FFFFFFFF
    (0x080034, 0x080063, 'FighterOamTable'),       # 12 longs (entry 11 points into Cell's sprite pieces)
    (0x080364, 0x0804BB, 'sangoku_frame_art_table'),
    (0x09578A, 0x095901, 'sangohan_frame_art_table'),
    (0x0C890E, 0x0C8AA1, 'piccolo_frame_art_table'),
    (0x0A206C, 0x0A21F3, 'vegeta_frame_art_table'),
    (0x0B6064, 0x0B61E3, 'trunks_frame_art_table'),
    (0x0E6C0E, 0x0E6D69, 'cell_frame_art_table'),
    (0x1038CC, 0x103A3F, 'c18_frame_art_table'),
    (0x112596, 0x112721, 'kurilin_frame_art_table'),
    (0x121BE0, 0x121D63, 'freezer_frame_art_table'),
    (0x1345B8, 0x134727, 'likum_frame_art_table'),
    (0x159368, 0x1594C7, 'giniou_frame_art_table'),
]
