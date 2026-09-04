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
CHECKSUM = 0x18E          # boot sums $000200..end and hangs at $000506 on mismatch

# ---- input ---------------------------------------------------------------
# MEASURED. The face buttons are in the EVEN byte; the odd byte next to it is
# the other half of the pad read (bit 7 = start) and only lights in combination.
PAD_P1, PAD_P2 = 0xFFE666, 0xFFE668
BUTTON = {'B': 0x10, 'C': 0x20, 'A': 0x40}
PAD_READ_TAIL = 0x003FE2  # `move.w $e6e2.w,$e668.w` at the end of sub_003FD4;
                          # replacing it is a size-neutral place to hook input

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
