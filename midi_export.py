#!/usr/bin/env python3
"""
Decode a Yamaha Playcard's melody, obbligato and chords to MIDI, statically.

    python midi_export.py <card.bin> [-o out.mid]
    python midi_export.py --all            # convert every card in this folder

Three tracks come out: melody, obbligato and the chord chart.  A two-sided card
is written once, from its side A - see "TWO-SIDED CARDS" below.

No emulator involved.  The card carries its own tempo and its durations are
exact tick counts, so the timing here is precise rather than a recording of a
performance - which is the main reason to prefer this over capturing the FM
chip while the cartridge plays.

WHAT IS EXACT
    Tempo, from the header's metronome mark.
    Durations, in ticks where 24 = one quarter note; rests included.
    Note letters, confirmed against known melodies and against the YM2151's
        own key-code table.
    Which events are notes at all - the "no note" code is the YM2151's unused
        note value, and it alone marks a rest.  The duration track's top bit is
        a LIFT flag - the finger comes off at the end of that event - so a run
        of equal pitches ties into one note only while the PRECEDING event left
        the finger down.
    Articulation.  A lifted event does not sound for its whole length: the
        keyboard releases the key four ticks early, or a sixth of the event,
        whichever is less, measured on the firmware.  This file renders that
        (16.7% of the corpus's notes), which is what stops a card sounding
        legato throughout.  card_decompile.py deliberately does NOT - it writes
        the card's stored lengths, because its output has to compile back.

HOW THE HARDER PARTS WORK
    Octaves.  The cartridge keeps a running
        OCTAVE REGISTER, exactly like the YM2151 key code it ends up writing:
        modifier 1 raises it, modifier 2 lowers it, modifier 0 sharpens the one
        following note.  A note's pitch is then just octave plus note code,
        where the code's block runs C# D D# E F F# G G# A A# B C, so C sits at
        the top of a block rather than the bottom.  Against a firmware capture
        this reproduces the obbligato's first 30 notes EXACTLY, and gives a
        range of C#3-B5 against the firmware's identical C#3-B5.  The starting
        register is 4.
    Repeat structure.  playcard_resolve reproduces the cartridge's own
        back-fill pass, so repeats resolve to the same calls and returns the
        firmware builds.  A duration track and its pitch stream must expand to
        the same number of events, since they pair one to one; that holds for
        all 261 cards.
    Key.  The header's key field is itself a YM2151 note code, so the
        transposition is that note's position in the chromatic order, taken in
        the octave nearest zero.  Seven values occur across the corpus and the
        rule accounts for all of them.

HOW WELL IT MATCHES
    Against a five-minute capture of the firmware playing Jingle Bells:
        melody      194 notes, EVERY ONE identical to the firmware, in order
        obbligato   234 notes, EVERY ONE identical to the firmware, in order
    Similarity 1.000 on both parts - the decoded note sequences are exactly
    what the cartridge plays.
    The melody is voiced across TWO of the chip's channels, alternating, so it
    has to be compared against both merged - against either one alone it looks
    half missing.

    Obbligato level.  The obbligato plays quieter while the melody is running,
        and the card says where: opcode 0x14 means the melody starts here and
        0x13 that it has run out of material.  The firmware answers by writing
        0x60 and 0x80 to the obbligato's level, which reaches the YM2151 as a
        Total Level step on that channel's carrier - 34 to 36 and back, within
        45 ms of each opcode.  Here it becomes note VELOCITY, scaled by the
        firmware's own 0x60/0x80, so 100 drops to 75.  Velocity rather than a
        volume controller because it survives soloing a track, merging, and
        import into notation software.
        These are ASSERTIONS, not brackets - 0x14 is restated at every melody
        re-entry, so only about 70% of cards alternate and it has to be tracked
        as a state.  80.6% of all obbligato notes in the corpus are ducked.

    Chords.  The section table's values are the chord chart, packed as
        (type << 4) | YM2151 note code, the types being major, minor, seventh
        and minor seventh.  Across 10220 entries the low nibble never lands on
        the chip's unused codes 7 and 11 - the same signature that identifies
        the pitch opcodes.  Someday My Prince Will Come reads out as
        F A7 Bb Bbm C#7 C7 F A7 Bb Am7 D7 Gm ..., which is the song, and its
        changes land exactly on the bar lines the user hears them on.  Types
        major and seventh are confirmed by ear; minor and minor seventh are
        read from the progressions making harmonic sense.
        Chords are stored at SOUNDING pitch and are NOT transposed by the key
        field, unlike the melody and obbligato.
        Value 0xFF is not a chord but an ACCOMPANIMENT MUTE: the chord stops
        sounding there and the next real chord starts it again.

TWO-SIDED CARDS
    A side-A card is a type-1 card carrying no section at all - header and both
    duration tracks, with the pitches on the other side of the strip.  Its
    partner is a type-2 continuation carrying only that section.  Given a
    side-A file this joins the two and writes one .mid under the name with the
    side suffix dropped; given a side-B file it declines, since that card is
    already covered by its side A.

Bass and drums are still not here: those come from the instrument's own pattern
generator rather than from the card, and would need the pattern tables.  What
the card does carry about them - the rhythm style, and the standard/alternate
pattern selection - is decoded but not rendered.  (pcs30_arrange.py does render
them, from the PCS-30's tables, which is that keyboard's accompaniment and not
a universal one.)

WHOSE FIRMWARE, WHERE THIS FILE SAYS "THE FIRMWARE"

The UPA-01's, per the naming in playcard_decode.py.  It matters twice below.
The note-for-note agreement figures are against that cartridge, so they say the
static decode reads the card the way the cartridge does.  And the two rendering
choices that are NOT on the card - the duck ratio 0x60/0x80 and the lift gap -
are copied from that cartridge because it is the machine that can be measured;
another instrument may well duck by a different amount.  Neither affects which
notes come out, only how they are voiced in the .mid.

Nor is free tempo, which is not a property of the file: the same 0x14/0x13 pair
tells the keyboard when a melody section is in progress, and instruments with
that feature hold playback until the player plays the right note, follow their
speed, and return to this tempo when the section ends.  A .mid is a fixed
performance, so what it can show is the level, not the waiting.
"""

import argparse, os, struct, sys

import playcard_decode as P
import playcard_resolve as R

# note letter -> semitone within an octave, and the card's letter numbering
LETTER_SEMI = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
CODE_LETTER = {1: 'A', 2: 'B', 3: 'C', 4: 'D', 5: 'E', 6: 'F', 7: 'G'}
PITCHVAL = [3, 10, 13, 14, 1, 4, 5, 8]        # opcode -> ROM byte (YM2151 note code)

# The YM2151 key code is an octave field plus a note field, and the note field
# runs C# D D# . E F F# . G G# A . A# B C - so C sits at the TOP of a block.
# The cartridge keeps a running octave register and the card's modifiers move
# it; there is no "nearest note" rule.  This index is that ordering.
OPM_INDEX = {0: 0, 1: 1, 2: 2, 4: 3, 5: 4, 6: 5, 8: 6, 9: 7, 10: 8, 12: 9, 13: 10, 14: 11}

# One copy of this, in playcard_decode: it takes the header field either signed
# or as a raw note code, and getting that wrong costs a fourth on 50 cards.
key_shift = P.key_shift

TICKS_PER_QUARTER = 24                         # the card's own unit
VELOCITY = 100                                 # the note velocity everything starts from


START_OCTAVE = 4          # fitted against the firmware; see the module docstring

# The cartridge maps each voice field into the SFG-01's 48-voice bank through
# two adjacent tables: the melody's at ROM 0x5C3F, the obbligato's at 0x5C4B.
# Both were confirmed by loading cards and reading the names off the cartridge's
# own screen.
# One copy of these, in playcard_decode.  The names written out are the PC-100's
# own panel names rather than the SFG-01's screen labels; both are accepted back.
SFG_NAMES = P.SFG_NAMES
MELODY_VOICE = P.MELODY_VOICE                                   # index = field value
OBBLIGATO_VOICE = P.OBBLIGATO_VOICE                             # index = field value


def voice_name(table, field):
    return P.voice(table, field)


def pitch_events(ops, start_octave=START_OCTAVE):
    """Resolved opcode stream -> one MIDI note (or None for a rest) per slot.

    The octave is a register carried from note to note: modifier 1 raises it,
    modifier 2 lowers it, modifier 0 sharpens the next note only."""
    out = []
    octave = start_octave
    sharp = 0
    pending = 0
    for kind, val in ops:
        if kind == 'byte':
            if val not in PITCHVAL:
                continue
            if val == 3:                     # the YM2151's unused code: a rest
                out.append(None)
                sharp = 0
                continue
            octave += pending
            pending = 0
            out.append(12 * (octave + 1) + OPM_INDEX[val] + 1 + sharp)
            sharp = 0
        elif kind == 'oct':
            if val == 0:
                sharp = 1
            elif val == 1:
                pending += 1
            elif val == 2:
                pending -= 1
    return out


# The obbligato plays quieter under the melody.  Opcode 0x14 says the melody
# starts here and 0x13 that it has run out of material; the firmware answers by
# writing 0x60 and 0x80 to the obbligato's level (ROM 0x5F99/0x5FAD, the field
# at block+0x23, initialised to 0x80 at 0x5D54).  On the chip that arrives as a
# Total Level step on the obbligato's carrier - 34 to 36 and back on Edelweiss,
# within 45 ms of each opcode.
#
# These are ASSERTIONS, not brackets: 0x14 is restated at every melody re-entry,
# the same way bar-mark 0 is restated for each bar the drums stay out, so only
# about 70% of cards alternate.  Tracking it as a state rather than a toggle is
# therefore the only thing that works.
DUCK_ON = 0x14
DUCK_OFF = 0x13
DUCK_RATIO = 0x60 / 0x80          # the firmware's own two levels


def duck_states(ops):
    """One flag per pitch slot: was the obbligato ducked when it sounded?

    Pairs index-for-index with pitch_events over the same stream."""
    out = []
    ducked = False
    for kind, val in ops:
        if kind == 'byte':
            if val not in PITCHVAL:
                continue
            out.append(ducked)
        elif kind == 'ctl':
            if val == DUCK_ON:
                ducked = True
            elif val == DUCK_OFF:
                ducked = False
    return out


def durations(track):
    """Resolved duration track -> list of (ticks, is_rest)."""
    return [(v & 0x7F, bool(v & 0x80)) for k, v in track if k == 'byte']


# ---------------------------------------------------------------- the chords

# A section-table value is a chord: (type << 4) | YM2151 note code.  The low
# nibble never lands on the chip's unused codes 7 and 11, exactly as the pitch
# opcodes never do.  0xFF is not a chord but an ACCOMPANIMENT MUTE - the chord
# stops sounding there and resumes at the next real chord.
CHORD_INTERVALS = {0: (0, 4, 7),        # major
                   1: (0, 3, 7),        # minor
                   2: (0, 4, 7, 10),    # seventh
                   3: (0, 3, 7, 10)}    # minor seventh
CHORD_SUFFIX = {0: '', 1: 'm', 2: '7', 3: 'm7'}
CHORD_ROOT_MIDI = 48                    # roots land in the octave below middle C


def chord_chart(track, ops):
    """Resolved duration track + opcode stream -> [(tick, note code, type)].

    The table's positions are opcode indices, so the only way to place a chord
    in time is to walk the stream and accumulate the durations it pairs with.
    Both streams receive the table's records, since the cartridge walks it once
    per decoded opcode in whichever stream is running; the obbligato is the one
    whose hits form the actual chart, and it is also where every accompaniment
    control opcode lives."""
    durs = [v & 0x7F for k, v in track if k == 'byte']
    out = []
    t = i = 0
    for kind, val in ops:
        if kind == 'byte':
            if i < len(durs):
                t += durs[i]
                i += 1
        elif kind == 'tbl':
            if val == 0xFF:
                out.append((t, None, None))       # accompaniment mute
            else:
                n, ty = val & 0x0F, (val >> 4) & 0x0F
                if n in OPM_INDEX and ty in CHORD_INTERVALS:
                    out.append((t, n, ty))
    return out


def chord_part(chords, end_tick):
    """Chart -> sustained triads, each held until the next change.

    Chords are stored at SOUNDING pitch and are not transposed by the key
    field, unlike the melody and obbligato."""
    seq = []
    for t, n, ty in chords:
        if seq and seq[-1][0] == t:
            seq[-1] = (t, n, ty)             # a later record at the same tick wins
        elif seq and seq[-1][1:] == (n, ty):
            continue                          # the same chord again: hold it
        else:
            seq.append((t, n, ty))
    notes = []
    for j, (t, n, ty) in enumerate(seq):
        if n is None:
            continue                          # a mute: sounds nothing, but stops
        stop = seq[j + 1][0] if j + 1 < len(seq) else end_tick
        dur = max(1, stop - t)
        root = CHORD_ROOT_MIDI + (OPM_INDEX[n] + 1) % 12
        for iv in CHORD_INTERVALS[ty]:
            notes.append((t, dur, root + iv, False, VELOCITY))
    return notes, [x for x in seq if x[1] is not None]


def chord_name(n, ty):
    names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'Bb', 'B']
    return names[(OPM_INDEX[n] + 1) % 12] + CHORD_SUFFIX[ty]


LIFT_GAP = 4                    # ticks a lifted event is cut short by


def lift_gap(ticks):
    """How much sooner a LIFTED event releases the key than it lasts.

    Measured on the firmware, capturing the YM2151's key on/off register while
    it plays cards that differ in nothing but this bit: the gap is 4.02, 4.03
    and 3.96 ticks on events of 24, 48 and 96, and 2.12 on an event of 12 -
    where four ticks would be a third of the note.  So it is four ticks, capped
    at a sixth of the event.  Lengths other than those four are extrapolated;
    new-cards/make_lift_test.py builds the cards that measured it."""
    return min(LIFT_GAP, ticks // 6)


def build_part(track, ops, shift, lo=0, hi=127, duck=False, vel=VELOCITY,
               articulate=False):
    """Pair one duration track with one pitch stream into timed notes.

    With duck=True the stream's 0x14/0x13 opcodes scale each note's velocity,
    which is how the obbligato's level under the melody is rendered.

    With articulate=True a note whose LAST event carries the lift bit is
    shortened by lift_gap(), which is what the keyboard does with it and what
    makes a rendering sound like the instrument rather than legato throughout.
    Leave it off for anything that has to survive a round trip: the card stores
    the event's full length, and handing back a shortened note would compile to
    a different card."""
    durs = durations(track)
    pit = pitch_events(ops)
    ducked = duck_states(ops) if duck else []
    notes = []
    tail = []                   # (ticks, lift) of each note's LAST event
    cur = None
    prev_lift = True
    t = 0
    for i in range(min(len(durs), len(pit))):
        ticks, dur_rest = durs[i]
        m = pit[i]
        v = vel
        if duck and i < len(ducked) and ducked[i]:
            v = max(1, int(round(vel * DUCK_RATIO)))
        # The duration track's top bit is a LIFT flag: it says the player takes
        # their finger off at the end of THIS event, so a following event on the
        # same pitch is struck again rather than held on.  A run of equal
        # pitches therefore ties into one note only while the preceding event
        # left the finger down.  Testing the bit on the event itself instead of
        # its predecessor merges notes that should repeat - two E4s becoming one
        # long E4, four D5s becoming three.
        if m is None:
            cur = None
            prev_lift = True
        else:
            m += shift
            if 0 <= m <= 127:
                if cur is not None and m == notes[cur][2] and not prev_lift:
                    st, du, pit_, mk, pv = notes[cur]
                    notes[cur] = (st, du + ticks, pit_, mk, pv)
                    tail[cur] = (ticks, dur_rest)
                else:
                    notes.append((t, ticks, m, dur_rest, v))
                    tail.append((ticks, dur_rest))
                    cur = len(notes) - 1
            else:
                cur = None
            prev_lift = dur_rest
        t += ticks
    if articulate:
        notes = [(st, max(1, du - lift_gap(last)) if lift else du, m, mk, v)
                 for (st, du, m, mk, v), (last, lift) in zip(notes, tail)]
    return notes, t, len(durs), len(pit)


# ---------------------------------------------------------------- MIDI output

def varlen(n):
    out = bytearray([n & 0x7F])
    n >>= 7
    while n:
        out.insert(0, (n & 0x7F) | 0x80)
        n >>= 7
    return bytes(out)


def write_midi(path, parts, bpm, tpq=24, beats=4):
    """`beats` sets the time signature: a waltz card is written in 3/4."""
    chunks = []
    chunks.append(struct.pack('>4sIHHH', b'MThd', 6, 1, len(parts) + 1, tpq))
    us = int(60000000 / bpm)
    tempo = varlen(0) + b'\xFF\x51\x03' + us.to_bytes(3, 'big')
    tempo += varlen(0) + b'\xFF\x58\x04' + bytes([beats, 2, 24, 8])
    tempo += varlen(0) + b'\xFF\x2F\x00'
    chunks.append(struct.pack('>4sI', b'MTrk', len(tempo)) + bytes(tempo))
    for ch, (name, notes) in enumerate(parts):
        # Two notes of the SAME pitch overlapping on one channel produce a
        # doubled note-on, and synths disagree about which note-off ends it -
        # heard as a note ringing on too long, but only on some of them.
        # Merging such runs into one note removes the ambiguity.
        by_pitch = {}
        for start, dur, m, marked, vel in notes:
            by_pitch.setdefault(m, []).append((start, start + max(1, dur), vel))
        merged = []
        for m, spans in by_pitch.items():
            spans.sort()
            cs, ce, cv = spans[0]
            for s0, e0, v0 in spans[1:]:
                if s0 < ce:
                    ce, cv = max(ce, e0), max(cv, v0)
                else:
                    merged.append((cs, ce, m, cv))
                    cs, ce, cv = s0, e0, v0
            merged.append((cs, ce, m, cv))

        ev = []
        for start, stop, m, vel in merged:
            ev.append((start, 0x90 | ch, m, vel))
            ev.append((stop, 0x80 | ch, m, 0))
        ev.sort(key=lambda e: (e[0], e[1] & 0xF0))
        body = bytearray()
        body += varlen(0) + b'\xFF\x03' + bytes([len(name)]) + name.encode()
        last = 0
        for tick, status, d1, d2 in ev:
            body += varlen(max(0, tick - last)) + bytes([status, d1, d2])
            last = tick
        body += varlen(0) + b'\xFF\x2F\x00'
        chunks.append(struct.pack('>4sI', b'MTrk', len(body)) + bytes(body))
    with open(path, 'wb') as f:
        for c in chunks:
            f.write(c)


def load(card):
    """A parsed card, or P.WrongFile naming what the path actually holds."""
    return P.parse_card(P.tobits(P.check_card(card)))


def side_b_for(card):
    """A side-A card is a type-1 card carrying no section: header and both
    duration tracks, with the pitches on the other side of the strip.  Its
    partner is the type-2 continuation, which carries only that section."""
    if '_side-a' not in os.path.basename(card):
        return None
    mate = card.replace('_side-a', '_side-b')
    return mate if os.path.isfile(mate) else None


def convert(card, out=None, quiet=False):
    h = load(card)
    joined = False

    if h['type'] == 2:
        # the pitches half of a two-sided card; converted from its side A
        if not quiet:
            print('%s: side B, converted with its side A' % os.path.basename(card))
        return None

    if h['type'] != 1:
        if not quiet:
            print('%s: unknown block type %s, skipped' % (os.path.basename(card), h['type']))
        return None

    if not h['sections']:
        mate = side_b_for(card)
        if mate is None:
            if not quiet:
                print('%s: no section and no side B found, skipped' % os.path.basename(card))
            return None
        hb = load(mate)
        if hb['type'] != 2 or not hb['sections']:
            if not quiet:
                print('%s: side B is not a continuation, skipped' % os.path.basename(card))
            return None
        h['sections'] = hb['sections']       # durations from side A, pitches from side B
        joined = True

    key = h['transpose'] if h['transpose'] >= 0 else h['transpose'] + 16
    shift = key_shift(key)
    t1, t2, s0, s1 = R.resolve(h)
    mel, tm, dm, pm = build_part(t1, s0, shift, articulate=True)
    obb, to, do, po = build_part(t2, s1, shift, duck=True, articulate=True)
    chords, seq = chord_part(chord_chart(t2, s1), max(tm, to))

    if out is None:
        base = os.path.splitext(card)[0]
        if joined:
            base = base.replace('_side-a', '')
        out = base + '.mid'

    parts = [('melody %s' % voice_name(MELODY_VOICE, h['field4']), mel),
             ('obbligato %s' % voice_name(OBBLIGATO_VOICE, h['field6']), obb)]
    if chords:
        parts.append(('chords', chords))
    # rhythm 7 is the waltz, the one style in three
    write_midi(out, parts, h['tempo'], beats=3 if h['rhythm'] == 7 else 4)

    if not quiet:
        print('%-52s %3d bpm  %-10s key=%-2d shift=%+d' %
              (os.path.basename(card)[:52], h['tempo'], P.RHYTHM[h['rhythm']], key, shift))
        if joined:
            print('     joined with %s' % os.path.basename(side_b_for(card)))
        print('     melody   : %4d notes over %5.1f bars   %s'
              % (len(mel), tm / 96.0, voice_name(MELODY_VOICE, h['field4'])))
        nduck = sum(1 for x in obb if x[4] != VELOCITY)
        print('     obbligato: %4d notes over %5.1f bars   %s%s'
              % (len(obb), to / 96.0, voice_name(OBBLIGATO_VOICE, h['field6']),
                 '   (%d ducked under the melody)' % nduck if nduck else ''))
        if seq:
            print('     chords   : %4d changes   %s%s'
                  % (len(seq), ' '.join(chord_name(n, t) for _, n, t in seq[:12]),
                     ' ...' if len(seq) > 12 else ''))
        else:
            print('     chords   : none in the table')
        print('     -> %s' % out)
    return out


def main():
    ap = argparse.ArgumentParser(description="Decode a Playcard's melody and obbligato to MIDI.")
    ap.add_argument('card', nargs='?')
    ap.add_argument('-o', '--out')
    ap.add_argument('--all', action='store_true',
                    help='convert the whole card corpus')
    ap.add_argument('--out-dir', default=os.path.join(P.HERE, 'midi'),
                    help='where --all writes its .mid files (default: midi/)')
    a = ap.parse_args()
    if a.all:
        try:
            files = P.corpus()
        except P.Missing as e:
            sys.exit(str(e))
        # Derived files go to their own folder rather than in among the cards.
        os.makedirs(a.out_dir, exist_ok=True)
        ok = bad = 0
        for f in files:
            # A two-sided card is written once, under its name with the side
            # suffix dropped - the same naming convert() picks for itself.
            base = os.path.basename(os.path.splitext(f)[0]).replace('_side-a', '')
            base = os.path.join(a.out_dir, base)
            try:
                if convert(f, out=base + '.mid', quiet=True):
                    ok += 1
                else:
                    bad += 1
            except Exception as e:
                bad += 1
                print('%s: %s' % (os.path.basename(f), e))
        print('%d cards converted into %s, %d skipped' % (ok, a.out_dir, bad))
    elif a.card:
        convert(a.card, a.out)
    else:
        ap.print_help()


if __name__ == '__main__':
    P.run(main)
