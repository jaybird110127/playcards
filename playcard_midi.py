#!/usr/bin/env python3
"""
The MIDI side of the Playcard round trip, shared by the two tools that use it:

    card_decompile.py    a card image  -> an editable .mid
    midi_compile.py      that .mid     -> a card image

Read midi-roundtrip-design.md for why it is shaped this way, and
playcard-format.md for the format itself.  This module holds only what both
directions need: the channel layout, the control-note map, the MIDI reader and
writer, duration quantisation, and chord recognition.

THE CHANNEL LAYOUT

Four MIDI channels, and they are CHANNELS, not tracks.  Nothing here reads
track structure: a file with four tracks of one channel each and a file with
everything on one track compile to the same card.  The decompiler writes one
track per part because that is easier to edit, not because it means anything.

    channel 1   melody
    channel 2   obbligato
    channel 3   chord chart, as actual chords
    channel 4   control notes - bar marks, the obbligato duck, the mute

CONTROL NOTES

Notes rather than controller changes, so they can be played live on a keyboard
while the rest of the song runs, and they sit under one hand:

    C1  C#1 D1  D#1 E1  F1  F#1 G1     bar marks 0-7
                                       0 = drums off, 1-6 = fills,
                                       7 = alternate pattern for one bar
    C2                                 0x14 - the melody begins here
    D2                                 0x13 - the melody has run out
    E2                                 0x11 - passage division
    G2                                 accompaniment mute

Only the ONSET of a control note matters; its length is ignored.  The
decompiler writes them one tick long.

Every one of these is a REQUEST TO THE INSTRUMENT, and that is the whole of
what the card carries.  Which drum pattern fill 3 plays, what the alternate
accompaniment sounds like, how far the obbligato ducks - none of that is here,
and the machines differ.  The PC-100, the PCS-30 and the UPA-01 cartridge each
have their own patterns, and the cartridge is known to get a fill's FEEL wrong.
So this table is the meaning; the sound belongs to whatever reads the card.

Two traps, both from playcard-format.md:

  * Bar marks and control opcodes belong to the OBBLIGATO stream only.  Not one
    of the 2030 marks in the corpus is in the melody stream, so the compiler
    puts them in stream 1 and never in stream 0.

  * The accompaniment mute is NOT a control opcode.  It is the value 0xFF in
    the chord chart, so G2 routes to the chart rather than to the stream.  It
    looks like an inconsistency six months from now; it is the format's.

THE HEADER

Two text meta events on the tempo track:

    Playcard: tempo=120 rhythm=swing melody=STRING2 obbligato=FLUTE
              transpose=+0 sustain=off pattern=standard
    Playcard-raw: tempo=20 rhythm=2 f3=0 melody=8 sustain=0 obbligato=1 key=0

The friendly line is what a person edits.  The raw line is the header's actual
bit fields, and the compiler prefers it when both are present, so a decompile ->
recompile round trip cannot drift through a name lookup.  Delete the raw line
and the friendly one is used; command-line flags override either.
"""

import struct

import playcard_decode as P

TPQ = 24                       # the card's own unit: 24 ticks to a quarter

MEL_CH, OBB_CH, CHORD_CH, CTL_CH = 0, 1, 2, 3      # MIDI channels 1-4

# ---------------------------------------------------------------- control notes

MARK_BASE = 24                 # C1: bar mark 0, chromatic up to G1 = mark 7
CTL_NOTE = {0x14: 36, 0x13: 38, 0x11: 40}          # C2, D2, E2
NOTE_CTL = {v: k for k, v in CTL_NOTE.items()}
MUTE_NOTE = 43                 # G2 - a chord-chart entry, not a stream opcode

CONTROL_NAMES = {}
for _m in range(8):
    CONTROL_NAMES[MARK_BASE + _m] = 'mark %d' % _m
CONTROL_NAMES[CTL_NOTE[0x14]] = 'duck (0x14)'
CONTROL_NAMES[CTL_NOTE[0x13]] = 'restore (0x13)'
CONTROL_NAMES[CTL_NOTE[0x11]] = 'passage (0x11)'
CONTROL_NAMES[MUTE_NOTE] = 'accompaniment mute'


def control_note_name(pitch):
    return CONTROL_NAMES.get(pitch, 'unknown control note %d' % pitch)


PITCH_NAME = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')


def note_name(pitch):
    """MIDI number -> the name a musician reads, middle C being C4.

    Worth the four lines: a report that says "tick 4248, 29" tells nobody that
    the stray note is an F1, and F1 is the whole diagnosis."""
    return '%s%d' % (PITCH_NAME[pitch % 12], pitch // 12 - 1)


# ---------------------------------------------------------------- durations

# The master symbol table's ten lengths, in ticks.  There is nothing else: no
# 32nds, no 16th triplets, no dotted 16ths.  8 and 16 are the two triplet
# values, which is why the set is not simply the multiples of 6.
DURATIONS = [6, 8, 12, 16, 18, 24, 36, 48, 72, 96]
LIFT = 0x80                    # the finger comes off at the end of this event

_split_cache = {0: []}


def split_duration(n):
    """n ticks -> table values summing to n, largest first, or None.

    A held note is a run of same-pitch events, so any length the table can
    reach is expressible.  Picking ONE canonical decomposition - fewest
    symbols, largest first - is what makes splitting a MIDI note into events
    and merging events back into a MIDI note inverse operations, and therefore
    what makes the round trip exact rather than merely equivalent."""
    if n < 0:
        return None
    if n in _split_cache:
        return list(_split_cache[n])
    for k in range(max(_split_cache) + 1, n + 1):
        best = None
        for v in sorted(DURATIONS, reverse=True):
            if v <= k and (k - v) in _split_cache:
                cand = [v] + _split_cache[k - v]
                if best is None or len(cand) < len(best):
                    best = cand
        if best is not None:
            _split_cache[k] = best
    return list(_split_cache[n]) if n in _split_cache else None


def nearest_length(n):
    """The closest length the table can express, for quantising.

    Everything even from 12 up works, plus 6 and 8; 2, 4 and 10 do not, and
    nothing odd does."""
    if split_duration(n) is not None:
        return n
    for d in range(1, 16):
        for cand in (n - d, n + d):
            if cand > 0 and split_duration(cand) is not None:
                return cand
    return 6


def events_for_note(ticks):
    """One note of `ticks` -> [(length, lift)] events.

    Every event but the last leaves the finger DOWN, so the run ties into one
    note; the last lifts, so a following event on the same pitch re-strikes.
    That is exactly the merge rule midi_export.build_part applies in reverse."""
    parts = split_duration(ticks)
    if parts is None:
        return None
    return [(v, i == len(parts) - 1) for i, v in enumerate(parts)]


# ---------------------------------------------------------------- pitch

# A note's pitch is 12 * (octave + 1) + OPM_INDEX[code] + 1 + sharp, where the
# octave is a plain running register.  The chip's block runs
# C# D D# E F F# G G# A A# B C, so C sits at the TOP of a block and a register
# value spans D up to the C# above it.
LETTER_CODE = {'A': 10, 'B': 13, 'C': 14, 'D': 1, 'E': 4, 'F': 5, 'G': 8}
# pitch class -> (letter, sharp).  Flats are spelled as sharps of the letter
# below; the format offers no choice about it.
SPELLING = {0: ('C', 0), 1: ('C', 1), 2: ('D', 0), 3: ('D', 1), 4: ('E', 0),
            5: ('F', 0), 6: ('F', 1), 7: ('G', 0), 8: ('G', 1), 9: ('A', 0),
            10: ('A', 1), 11: ('B', 0)}
START_OCTAVE = 4               # the register the cartridge starts from


def note_position(pitch):
    """MIDI pitch -> (letter, sharp, octave register) for the card."""
    letter, sharp = SPELLING[pitch % 12]
    x = P.OPM_INDEX[LETTER_CODE[letter]] + 1 + sharp
    return letter, sharp, (pitch - x) // 12 - 1


# ---------------------------------------------------------------- chords

# The card has four chord types and no others.  Anything else in the MIDI has
# to be approximated, and the compiler says so rather than choosing quietly.
CHORD_TEMPLATE = {0: (0, 4, 7), 1: (0, 3, 7), 2: (0, 4, 7, 10), 3: (0, 3, 7, 10)}
CHORD_SUFFIX = {0: '', 1: 'm', 2: '7', 3: 'm7'}
PC_NAME = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'Bb', 'B']

# Corpus frequency decides ties: of 10106 chart entries, 42.9% are major,
# 26.3% seventh, 14.2% minor, 8.5% minor seventh.  So a voicing that could
# equally be either reads as the commoner one.
TYPE_RANK = {0: 0, 2: 1, 1: 2, 3: 3}

# A chord is recognised by its pitch CLASSES, so inversions and spacing are
# free: C3 E3 G3, E3 G3 C4 and G2 E3 C4 are all C major.  What costs is a note
# the chord type cannot account for, and what is nearly free is a fifth left
# out - which is why D3 F3 C4 is a D minor seventh and D3 F#3 C4 a D seventh.
COST_EXTRA = 10                # a pitch class no template of this root explains
COST_MISSING = {0: 12,         # no root at all: see below
                3: 3, 4: 3,    # no third: the chord's quality is unstated
                7: 1,          # no fifth: routinely left out, costs almost nothing
                10: 3}         # no seventh: makes it a triad instead

# Leaving the root out is priced above any single wrong note on purpose.  A
# chord chart is not a jazz voicing: its entries name a root, and the root is
# what the bass pattern plays.  Without that price a C diminished triad reads
# as a rootless G#7 - defensible on paper, since C, D# and F# are the upper
# structure of one, and not what anyone writing C, Eb, Gb into a Playcard
# meant.  Priced this way it reads as Cm with the flat fifth reported, which is
# the nearest chord the card can actually store.  A voicing that genuinely has
# no root still resolves, because then nothing else fits either.


def identify_chord(pitches, context=()):
    """Pitches sounding together -> (root pitch class, type, note).

    `note` is None when the reading is unambiguous, or a string saying what was
    approximated or guessed.  `context` is any melody and obbligato pitch
    classes sounding across the chord, used only to break a tie that turns on
    the third - D3 C4 alone cannot say whether it is D7 or Dm7, but an F# in
    the tune settles it."""
    pcs = set(p % 12 for p in pitches)
    if not pcs:
        return None
    bass = min(pitches) % 12
    cands = []
    for root in range(12):
        for ty, tmpl in CHORD_TEMPLATE.items():
            want = set((root + iv) % 12 for iv in tmpl)
            extra = pcs - want
            missing = want - pcs
            cost = COST_EXTRA * len(extra)
            for pc in missing:
                cost += COST_MISSING[(pc - root) % 12]
            if root == bass:
                cost -= 0.5             # a tie-break only: inversions are legal
            cands.append((cost, TYPE_RANK[ty], (root - bass) % 12, root, ty,
                          frozenset(extra), frozenset(missing)))
    cands.sort()
    cost, _, _, root, ty, extra, missing = cands[0]

    tied = [c for c in cands if abs(c[0] - cost) < 1e-9 and (c[3], c[4]) != (root, ty)]

    # A tie that turns on the third can be settled by what the tune is doing.
    if tied and context:
        ctx = set(p % 12 for p in context)
        same_root = [c for c in cands if abs(c[0] - cost) < 1e-9 and c[3] == root]
        if len(same_root) > 1:
            maj = (root + 4) % 12 in ctx
            minr = (root + 3) % 12 in ctx
            pick = None
            if maj and not minr:
                pick = [c for c in same_root if c[4] in (0, 2)]
            elif minr and not maj:
                pick = [c for c in same_root if c[4] in (1, 3)]
            if pick:
                cost, _, _, root, ty, extra, missing = pick[0]
                return root, ty, ('ambiguous, read as %s from the %s third in the tune'
                                  % (chord_name(root, ty), 'major' if maj else 'minor'))

    note = None
    if extra:
        note = ('%s does not fit %s; %s dropped'
                % (', '.join(sorted(PC_NAME[p] for p in extra)),
                   chord_name(root, ty),
                   'they are' if len(extra) > 1 else 'it is'))
    elif tied:
        alt = tied[0]
        note = ('ambiguous: %s or %s, read as the commoner %s'
                % (chord_name(root, ty), chord_name(alt[3], alt[4]),
                   chord_name(root, ty)))
    elif missing and any((pc - root) % 12 != 7 for pc in missing):
        note = ('incomplete voicing, read as %s' % chord_name(root, ty))
    return root, ty, note


def chord_name(root, ty):
    return PC_NAME[root % 12] + CHORD_SUFFIX[ty]


# ROM 0x6454 loads D = 0x3F, so the parse loop takes at most 63 entries - but
# it stops on the count WITHOUT reading the end-of-table marker, so a table of
# 63 leaves ten bits unread and everything after it is parsed from the wrong
# place.  The usable maximum is therefore 62, and the largest chart in the
# corpus is exactly 62: the format is used right up to the ceiling and never
# past it.  Value-change records do not count against it - real cards reach 83
# records in total.
MAX_CHART = 62


def collapse_chart(entries):
    """Drop any entry that restates the chord already sounding.

    The handler at ROM 0x5FC6 does one thing with a chart value: it writes it
    to the live chord byte at 0xD353.  Writing the same value again changes
    nothing, so consecutive equal entries are a no-op on the instrument and
    dropping them is free.  It is not free in the table, which holds only 63
    entries, so this is also what keeps a chord-heavy arrangement inside it.

    A mute is an entry like any other, so C, mute, C survives as three."""
    out = []
    for tick, key in entries:
        if out and out[-1][1] == key:
            continue
        out.append((tick, key))
    return out


# pitch class -> the YM2151 note code a chart entry stores for that root
CHORD_CODE = {(P.OPM_INDEX[n] + 1) % 12: n for n in P.OPM_INDEX}


def chord_value(root, ty):
    """(root pitch class, type) -> the byte the chord chart stores."""
    return (ty << 4) | CHORD_CODE[root % 12]


def chord_pitches(root, ty, base=48):
    """The chord as MIDI notes, rooted in the octave below middle C."""
    r = base + (root % 12)
    return [r + iv for iv in CHORD_TEMPLATE[ty]]


# ---------------------------------------------------------------- the header

RHYTHM_NAME = {i: n for i, n in enumerate(P.RHYTHM) if i}
NAME_RHYTHM = {n: i for i, n in RHYTHM_NAME.items()}


def header_text(h):
    """The two meta lines, from a parsed card's header."""
    mel = P.voice(P.MELODY_VOICE, h['field4'])
    obb = P.voice(P.OBBLIGATO_VOICE, h['field6'])
    key = h['transpose'] if h['transpose'] >= 0 else h['transpose'] + 16
    friendly = ('Playcard: tempo=%d rhythm=%s melody=%s obbligato=%s '
                'transpose=%+d sustain=%s pattern=%s'
                % (h['tempo'], P.RHYTHM[h['rhythm']], mel, obb,
                   P.key_shift(key), 'on' if h['bit1'] else 'off',
                   'alternate' if (h['f3'] >> 1) & 1 else 'standard'))
    raw = ('Playcard-raw: tempo=%d rhythm=%d f3=%d melody=%d sustain=%d '
           'obbligato=%d key=%d'
           % (P.TEMPO.index(h['tempo']), h['rhythm'] - 1, h['f3'],
              h['field4'] + 5, h['bit1'], h['field6'] - 1, key))
    return friendly, raw


def parse_header_text(texts):
    """Meta text events -> raw header fields, or {} if none of them is ours.

    The raw line wins when both are present: it is the header's actual bit
    fields, so a decompile -> recompile trip cannot drift through a lookup."""
    friendly = {}
    raw = {}
    for t in texts:
        s = t.strip()
        if s.startswith('Playcard-raw:'):
            raw.update(_kv(s.split(':', 1)[1]))
        elif s.startswith('Playcard:'):
            friendly.update(_kv(s.split(':', 1)[1]))
    out = {}
    if friendly:
        out = _from_friendly(friendly)
    for k in ('tempo', 'rhythm', 'f3', 'melody', 'sustain', 'obbligato', 'key'):
        if k in raw:
            out[k] = int(raw[k], 0)
    return out


def _kv(s):
    out = {}
    for tok in s.split():
        if '=' in tok:
            k, v = tok.split('=', 1)
            out[k.strip()] = v.strip()
    return out


def _from_friendly(d):
    out = {}
    if 'tempo' in d:
        bpm = int(round(float(d['tempo'])))
        out['tempo'] = min(range(len(P.TEMPO)), key=lambda i: abs(P.TEMPO[i] - bpm))
    if 'rhythm' in d:
        name = d['rhythm'].lower()
        if name in NAME_RHYTHM:
            out['rhythm'] = NAME_RHYTHM[name] - 1
        elif name.isdigit():
            out['rhythm'] = int(name)
    # Either vocabulary is accepted here: a .mid written before the voices were
    # renamed says `melody=CLARINE`, and one written since says `clarinet`.
    if 'melody' in d:
        f = P.voice_field(P.MELODY_VOICE, d['melody'])
        if f is not None:
            out['melody'] = f + 5
    if 'obbligato' in d:
        f = P.voice_field(P.OBBLIGATO_VOICE, d['obbligato'])
        if f is not None:
            out['obbligato'] = f - 1
    if 'transpose' in d:
        shift = int(d['transpose'], 10)
        for code in P.OPM_INDEX:
            if P.key_shift(code) == shift:
                out['key'] = code
                break
    if 'sustain' in d:
        out['sustain'] = 1 if d['sustain'].lower() in ('on', '1', 'true', 'yes') else 0
    if 'pattern' in d:
        out['f3'] = 2 if d['pattern'].lower().startswith('alt') else 0
    return out


# ---------------------------------------------------------------- MIDI writing

def varlen(n):
    out = bytearray([n & 0x7F])
    n >>= 7
    while n:
        out.insert(0, (n & 0x7F) | 0x80)
        n >>= 7
    return bytes(out)


def write_midi(path, parts, bpm, beats=4, texts=(), tpq=TPQ):
    """parts is [(track name, channel, [(tick, ticks, pitch, velocity)])].

    Notes are written exactly as given - nothing is merged.  Two adjacent
    blocks of the same chord have to survive as two, because the chord chart
    stores two entries and the round trip has to give them back."""
    chunks = [struct.pack('>4sIHHH', b'MThd', 6, 1, len(parts) + 1, tpq)]
    head = bytearray()
    for t in texts:
        b = t.encode('latin-1', 'replace')
        head += varlen(0) + b'\xFF\x01' + varlen(len(b)) + b
    us = int(60000000 / bpm)
    head += varlen(0) + b'\xFF\x51\x03' + us.to_bytes(3, 'big')
    head += varlen(0) + b'\xFF\x58\x04' + bytes([beats, 2, 24, 8])
    head += varlen(0) + b'\xFF\x2F\x00'
    chunks.append(struct.pack('>4sI', b'MTrk', len(head)) + bytes(head))

    for name, ch, notes in parts:
        ev = []
        for order, (tick, dur, pitch, vel) in enumerate(notes):
            ev.append((tick + max(1, dur), 0, order, 0x80 | ch, pitch, 0))
            ev.append((tick, 1, order, 0x90 | ch, pitch, vel))
        # note-offs before note-ons at the same tick, so a chord that changes
        # to another chord sharing a note re-strikes it instead of losing it
        ev.sort(key=lambda e: (e[0], e[1], e[2]))
        body = bytearray()
        nb = name.encode('latin-1', 'replace')
        body += varlen(0) + b'\xFF\x03' + varlen(len(nb)) + nb
        last = 0
        for tick, _, _, status, d1, d2 in ev:
            body += varlen(max(0, tick - last)) + bytes([status, d1, d2])
            last = tick
        body += varlen(0) + b'\xFF\x2F\x00'
        chunks.append(struct.pack('>4sI', b'MTrk', len(body)) + bytes(body))

    with open(path, 'wb') as f:
        for c in chunks:
            f.write(c)


# ---------------------------------------------------------------- MIDI reading

class BadMidi(Exception):
    pass


def _varlen(b, i):
    n = 0
    while True:
        if i >= len(b):
            raise BadMidi('truncated variable-length quantity')
        c = b[i]
        i += 1
        n = (n << 7) | (c & 0x7F)
        if not c & 0x80:
            return n, i


def read_midi(path):
    """Read a .mid into {tpq, bpm, beats, texts, notes}.

    notes is [(tick, channel, pitch, velocity, ticks, order)] sorted by tick
    then by the order the events appear in the file.  That order is what keeps
    several control notes on one tick in the sequence their card had them in.

    Track structure is deliberately thrown away.  A four-track file and a
    one-track file carrying the same four channels read identically."""
    data = open(path, 'rb').read()
    if data[:4] != b'MThd':
        raise BadMidi('not a MIDI file (no MThd)')
    hlen = struct.unpack('>I', data[4:8])[0]
    fmt, ntrk, div = struct.unpack('>HHH', data[8:14])
    if div & 0x8000:
        raise BadMidi('SMPTE time division is not supported; use ticks per quarter')
    i = 8 + hlen

    tpq = div or TPQ
    bpm = 120.0
    beats = 4
    texts = []
    raw = []                   # (tick, track, seq, status, d1, d2)
    track = 0
    while i < len(data) and track < ntrk:
        if data[i:i + 4] != b'MTrk':
            i += 8 + struct.unpack('>I', data[i + 4:i + 8])[0]
            continue
        tlen = struct.unpack('>I', data[i + 4:i + 8])[0]
        j = i + 8
        end = min(len(data), j + tlen)
        tick = 0
        status = 0
        seq = 0
        while j < end:
            delta, j = _varlen(data, j)
            tick += delta
            if j >= end:
                break
            b = data[j]
            if b & 0x80:
                status = b
                j += 1
            if status == 0xFF:
                mtype = data[j]
                j += 1
                mlen, j = _varlen(data, j)
                payload = data[j:j + mlen]
                j += mlen
                if mtype in (0x01, 0x03, 0x06):
                    texts.append(payload.decode('latin-1', 'replace'))
                elif mtype == 0x51 and mlen == 3:
                    us = int.from_bytes(payload, 'big')
                    if us:
                        bpm = 60000000.0 / us
                elif mtype == 0x58 and mlen >= 2:
                    beats = payload[0]
                elif mtype == 0x2F:
                    break
                continue
            if status in (0xF0, 0xF7):
                mlen, j = _varlen(data, j)
                j += mlen
                continue
            hi = status & 0xF0
            if hi in (0xC0, 0xD0):
                j += 1
                continue
            d1, d2 = data[j], data[j + 1]
            j += 2
            if hi in (0x80, 0x90):
                raw.append((tick, track, seq, status, d1, d2))
                seq += 1
        i += 8 + tlen
        track += 1

    raw.sort(key=lambda e: (e[0], e[1], e[2]))
    notes = []
    open_notes = {}
    order = 0
    for tick, trk, seq, status, d1, d2 in raw:
        ch = status & 0x0F
        on = (status & 0xF0) == 0x90 and d2 > 0
        key = (ch, d1)
        if on:
            open_notes.setdefault(key, []).append((tick, d2, order))
            order += 1
        else:
            stack = open_notes.get(key)
            if stack:
                st, vel, o = stack.pop(0)
                notes.append((st, ch, d1, vel, max(1, tick - st), o))
    for (ch, pitch), stack in open_notes.items():
        for st, vel, o in stack:            # a note-on the file never closed
            notes.append((st, ch, pitch, vel, 1, o))
    notes.sort(key=lambda n: (n[0], n[5]))
    return {'tpq': tpq, 'bpm': bpm, 'beats': beats, 'texts': texts, 'notes': notes}


def rescale(notes, tpq):
    """Put a file's notes on the card's 24-ticks-per-quarter grid.

    Returns (notes, drift), where drift counts what the grid could not hold and
    says how far out the worst of it was, in card ticks.  Positions and lengths
    are counted separately, because they are different news: a position that
    moves is the music changing, a length that rounds usually is not.

    A discrepancy of one SOURCE tick or less is not counted at all.  Sequencers
    routinely write a note one tick short so its note-off does not collide with
    the next note-on - 2879 ticks of a 2880 at 960 per quarter - and that
    rounds straight back to the length the writer meant.  Reporting it as
    "timing the card cannot hold" is alarming and untrue."""
    zero = {'ticks': 0, 'lengths': 0, 'worst_tick': 0.0, 'worst_length': 0.0}
    if tpq == TPQ:
        return list(notes), zero
    out = []
    drift = dict(zero)
    scale = TPQ / float(tpq)
    for tick, ch, pitch, vel, dur, order in notes:
        t, d = tick * scale, dur * scale
        for src, exact, count, worst in ((tick, t, 'ticks', 'worst_tick'),
                                         (dur, d, 'lengths', 'worst_length')):
            if abs(src - round(exact) / scale) > 1.0:
                drift[count] += 1
                drift[worst] = max(drift[worst], abs(exact - round(exact)))
        out.append((int(round(t)), ch, pitch, vel, max(1, int(round(d))), order))
    return out, drift
