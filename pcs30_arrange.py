#!/usr/bin/env python3
"""A Playcard as a full MIDI arrangement, using the PCS-30's own accompaniment.

    python pcs30_arrange.py card.bin [-o out.mid]
    python pcs30_arrange.py card.bin --chord-octave 1
    python pcs30_arrange.py card.bin --chip           # the keyboard's own channels
    python pcs30_arrange.py --all                     # the whole card corpus
    python pcs30_arrange.py --all --in-dir . --out-dir out

What comes out is what a PCS-30 would play from this card, not "how the card
sounds": the melody and obbligato are the card's, and the three accompaniment
parts are that keyboard's own patterns.  A PC-100 - the machine these cards
were written for - has its own, and they have never been extracted.

Five parts: melody, obbligato, bass, guitar, and drums on channel 10.

    ch 1  melody      the card's melody voice, mapped to the nearest GM voice
    ch 2  obbligato   likewise, ducked where the card ducks it
    ch 3  bass        the PCS-30's bass pattern for the card's rhythm
    ch 4  guitar      its chord pattern
    ch 10 drums       its drum pattern, on the GM kit

NEEDS DATA THAT IS DELIBERATELY NOT IN THIS REPOSITORY.  The card images are
Yamaha's; put your own in `Original Playcards/`, or point `PLAYCARD_CARDS` at
them.  So are the accompaniment and drum patterns, which are the instrument's
musical content rather than a fact about the file format: they live in a file
this repository does not ship.  Make it once from your own PCS-30 ROM:

    python pcs30_extract.py

and this will find it.  Without it, everything here stops with an explanation
instead of a traceback.

What comes from where
---------------------
The card carries melody, obbligato, chord chart, rhythm choice, per-bar drum
marks and the two mutes.  It does *not* carry the accompaniment; that is the
keyboard's, and this uses the PCS-30's tables:

  * bass and chord patterns at ROM 0x2D26, ten rows of 32 steps, one byte per
    step as a 1-based semitone offset from the chord root
  * drums at 0x2BBC, five bit-planes assembling a 5-bit strike mask
  * a seventh chord switches to a different pattern table; a minor flattens one
    degree in place

Anchoring: a C bass note under a C major chord is **C2**, two octaves below
middle C, so the ROM's computed offset 0 is MIDI 36.  The firmware folds any
offset above 29 down an octave (0x16F2) and this does the same, which is what
keeps the bass from climbing with the root.

Three behaviours are easy to get wrong and are taken from the ROM rather than
guessed:

  * **A pattern byte of 0xFF is a HOLD, not a rest.**  Nothing is struck and
    whatever is sounding carries on; 0x00 is the explicit note off.  ROM 0x16BB
    tells them apart - 0xFF returns immediately, 0x00 calls the key-off alone.
    Treating both as silence makes every part sound clipped, worst on the
    sparse waltz patterns.

  * **When the chord ROOT changes, the next bass note that sounds is forced to
    the root** rather than to whatever the pattern holds at that step (ROM
    0x173E: the change sets bit 7 of 0x8045, and the next struck bass byte is
    replaced by 1).  The flag waits through holds and dead slots, so the root
    lands on the next actual strike.  Only the bass is affected; the chord
    voice keeps following its pattern.

  * The two voices are separate: **odd tables are the bass, even the chord**,
    and 0x14FA plays them with different voice numbers.

Two things this does that the keyboard does not
-----------------------------------------------
Both are about MIDI and a GM kit rather than about the PCS-30, so they are
deliberate departures rather than emulation:

  * **A pitch restruck while it is still sounding ends and starts again.**  Two
    voices share the guitar channel, so the same pitch can be struck while it is
    already ringing, and a doubled note-on is ambiguous - synths disagree about
    which note-off ends it, which is heard as a note holding on too long.
    Ending the first note where the second begins removes the ambiguity and
    keeps the strike.  MERGING them into one long note also removes it and is
    wrong: these patterns restrike inside the bar constantly, and every rhythm
    but march and disco loses strikes to a merge - the standard rock pattern
    loses 16 in one card.

  * **Kick and snare on the same step are separated, unless a fill is running.**
    Five patterns double them and on a GM kit that comes out cluttered - the
    snare is a separate loud hit rather than part of one accent.  Which of the
    two gives way depends on where the step is:

        rhumba      6 14 22 30       both kept - all of them are off the beat
        samba       0 4 12 16 20 28  snare out at 0 and 16, both kept elsewhere
        bossa-nova  0 6              snare out at 0, both kept at 6
        march       0                snare out
        disco       4 12 20 28       KICK out - see below

    The downbeat belongs to the kick, so a double on the first step of a bar
    loses its snare.  A double anywhere else is the pattern's own syncopation
    and both belong.  Disco is the exception: it kicks on all four beats with
    the snare doubling two and four, which on a GM kit is a kick on every beat
    with two of them thickened when the figure wants to be kick, snare, kick,
    snare - so there the kick gives way instead.  A fill keeps everything,
    because its snare is the whole point of it.
"""

import argparse
import glob
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playcard_decode as P
import pcs30_tables as PT
import playcard_resolve as R
import midi_export as M

# ---------------------------------------------------------------- tables
#
# The patterns themselves come from `pcs30_tables`, which reads a file this
# repository does not ship: they are Yamaha's music, not a fact about the card
# format.  Run `pcs30_extract.py` once against your own PCS-30 ROM to make it.

# (chord table, bass table) for [variant][seventh]
TABLES = {('A', False): (0, 1), ('A', True): (2, 3),
          ('B', False): (4, 5), ('B', True): (6, 7)}

# rows are the card's own rhythm numbering, 1..10
TRIPLET = {3, 8}             # swing, slow-rock: 12 slots over four beats
WALTZ = 7                    # 12 slots over three beats

# The escape nibble on the card is remapped by the cartridge (ROM 0x65C8)
# before it is called a "mark"; the PCS-30 dispatches on the RAW nibble.
RAW_OF_MARK = {m: r for r, m in enumerate(P.T65C8)}
# raw nibble -> bit set in 0x80CF (ROM 0x2AEC), confirmed by running that code
BIT_OF_RAW = [3, 2, 1, 0, 5, 4, 6, 7]

# 5-bit strike mask -> GM percussion note
DRUM_GM = {4: 42,            # cymbal short  -> closed hi-hat
           3: 46,            # cymbal long   -> open hi-hat
           2: 38,            # snare         -> acoustic snare
           1: 75,            # latin         -> claves (it plays the son clave)
           0: 36}            # kick          -> bass drum 1
DRUM_VEL = {42: 60, 46: 66, 38: 92, 75: 72, 36: 96}
KICK, SNARE = 0, 2           # bit numbers within the strike mask

# Disco is the one pattern that puts the kick under every snare: it strikes on
# all four beats with the snare doubling it on two and four.  Kept whole on a
# GM kit that is a kick on every beat with two of them thickened, where the
# figure wants to be kick, snare, kick, snare.  So on a doubled step off the
# downbeat this rhythm gives the beat to the SNARE and drops the kick, which is
# the opposite of what the downbeat rule does.
SNARE_TAKES_THE_BACKBEAT = {10}                 # rhythm 10, disco

# Voice name -> nearest General MIDI program.  The names are the PC-100's, from
# playcard_decode.VOICE_NAMES.  The organ is not a pipe organ on these
# instruments - it is percussive, and on the PCS-30 a squarewave electronic
# organ - so it maps to 17 rather than anything churchy.
GM_VOICE = {'piccolo': 72, 'organ': 17, 'strings': 48, 'violin': 48,
            'trumpet': 56, 'oboe': 68, 'clarinet': 71, 'harpsichord': 6,
            'piano': 0, 'vibraphone': 11, 'guitar': 24, 'flute': 73,
            'brass': 61}

# Octave corrections, in semitones.  Most GM synths voice the percussive organ
# an octave below where these keyboards put it, and the real Yamahas play their
# piccolo an octave up (the PCS-30 does not offer piccolo at all, which is
# probably why exactly one German Playcard uses it).
GM_OCTAVE = {'organ': 12, 'piccolo': 12}

BASS_MIDI0 = 36              # offset 0 sounds C2

# Velocities.  The melody is the loudest thing in the file; the accompaniment
# sits under it and the drums under that.  Balance is a matter of taste and of
# whichever synth is playing the file, so all four are options.
MELODY_VEL = 112
OBBLIGATO_VEL = 96           # the card ducks this to 75% where the melody runs
BASS_VEL = 80
GUITAR_VEL = 86

SAME_ROOT = 3                # a note code no chip can play: "keep the root"


# ---------------------------------------------------------------- the card

def marks_and_chords(track, ops):
    """Walk a duration track with its stream, timing every mark and chord."""
    durs = [v & 0x7F for k, v in track if k == 'byte']
    marks, chords = [], []
    cur_n = cur_ty = None                 # the chord now sounding, for SAME_ROOT
    t = i = 0
    for kind, val in ops:
        if kind == 'byte':
            if i < len(durs):
                t += durs[i]
                i += 1
        elif kind == 'mark' or (kind == 'ctl' and val < 8):
            # After resolution a bar mark arrives as 'ctl'; the real control
            # opcodes are 0x11/0x13/0x14, so anything under 8 is a mark.  The
            # value is already remapped through the cartridge's table at
            # ROM 0x65C8, which is why RAW_OF_MARK undoes it below.
            marks.append((t, val))
        elif kind == 'tbl':
            if val == 0xFF:
                chords.append((t, None, None))
                cur_n = cur_ty = None
            else:
                n, ty = val & 0x0F, (val >> 4) & 0x0F
                if n == SAME_ROOT and cur_n is not None:
                    # A root the chip cannot play means "keep the root already
                    # sounding and OR this quality onto it" - the PCS-30's own
                    # rule, at ROM 0x28BA.  With nothing sounding it does
                    # nothing, which is what that routine does too.
                    n, ty = cur_n, (cur_ty or 0) | ty
                if n in M.OPM_INDEX and ty in M.CHORD_INTERVALS:
                    chords.append((t, n, ty))
                    cur_n, cur_ty = n, ty
    return marks, chords


def chord_at(chords, tick):
    """The chord sounding at a tick: (root pitch class, minor, seventh) or None."""
    cur = None
    for t, n, ty in chords:
        if t > tick:
            break
        cur = None if n is None else ((M.OPM_INDEX[n] + 1) % 12, ty in (1, 3), ty in (2, 3))
    return cur


# ---------------------------------------------------------------- patterns

def pattern_byte(tab, table, row, step):
    """The raw pattern byte.  0xFF is a HOLD - nothing is struck and whatever is
    sounding carries on - while 0x00 is an explicit note off (ROM 0x16BB tells
    them apart: 0xFF returns immediately, 0x00 calls the key-off alone)."""
    return tab.pitch_byte(table, row, step)


def note_of(v, root, minor):
    """A struck pattern byte as a MIDI note, by the firmware's own arithmetic.

    Mirrors ROM 0x16CF step for step, because the octave fold is easy to place
    an octave wrong.  The chip note is `root + v` with v the **1-based** value,
    not the degree, and the fold at 0x16F2 tests that sum - so a pattern degree
    of 24 folds under an F root (5 + 25 = 30) but not under a C root (0 + 25 =
    25).  That is the octave shifting that depends on the chord's root."""
    c = root + v                                # ROM 0x16D4: ADD A,E
    red = v
    while red > 12:                             # ROM 0x16D6
        red -= 12
    if minor and red == 5:                      # ROM 0x16E3: major third -> minor
        c -= 1
    if c > 29:                                  # ROM 0x16F2
        c -= 12
    return BASS_MIDI0 - 1 + c                   # value 1 under a C root is C2


class Voice(object):
    """One monophonic voice, holding a note until it is restruck or released.

    A release is *scheduled* rather than immediate, because two of the rules
    here end a note in the future: a bass note runs to the bar line, and an
    accompaniment mute lets whatever is sounding ring on into the next bar.  A
    strike arriving before that deadline simply ends the note early."""

    def __init__(self, notes, vel, shift=0):
        self.notes, self.vel, self.shift = notes, vel, shift
        self.note = self.start = self.deadline = None

    def _close(self, tick):
        if self.note is not None and tick > self.start:
            self.notes.append((self.start, tick - self.start,
                               self.note + self.shift, self.vel))
        self.note = self.start = self.deadline = None

    def off(self, tick):
        self._close(tick)

    def release(self, tick):
        """End the note at `tick`, unless something restrikes first."""
        if self.note is not None:
            self.deadline = tick if self.deadline is None else min(self.deadline, tick)

    def settle(self, now):
        """Close a note whose scheduled end has passed."""
        if self.deadline is not None and now >= self.deadline:
            self._close(self.deadline)

    def strike(self, tick, note):
        end = tick if self.deadline is None else min(self.deadline, tick)
        self._close(end)
        self.note, self.start = note, tick


def drum_mask(tab, bank, bit, step):
    """The 5-bit strike mask for one step, assembled across the bit-planes."""
    return tab.drum_mask(bank, bit, step)


# ---------------------------------------------------------------- MIDI out

def varlen(n):
    out = bytearray([n & 0x7F])
    n >>= 7
    while n:
        out.insert(0, 0x80 | (n & 0x7F))
        n >>= 7
    return out


def write_midi(path, parts, bpm, tpq=24, beats=4):
    """parts: (name, channel, program or None, [(start, dur, note, vel)]).

    `beats` is the bar length, so a waltz card is written in 3/4 rather than
    leaving every player to assume common time."""
    chunks = [struct.pack('>4sIHHH', b'MThd', 6, 1, len(parts) + 1, tpq)]
    us = int(60000000 / bpm)
    head = varlen(0) + b'\xFF\x51\x03' + us.to_bytes(3, 'big')
    head += varlen(0) + b'\xFF\x58\x04' + bytes([beats, 2, 24, 8])
    head += varlen(0) + b'\xFF\x2F\x00'
    chunks.append(struct.pack('>4sI', b'MTrk', len(head)) + bytes(head))
    for name, ch, prog, notes in parts:
        # Two voices share the guitar channel, so the same pitch can be struck
        # while it is already sounding.  That produces a doubled note-on and
        # synths disagree about it - some end the note on the first note-off and
        # some hold it to the second, which is heard as a note ringing on too
        # long.  The ambiguity has to go, but NOT by merging the two into one
        # note: these patterns restrike a pitch inside the bar all the time -
        # the standard rock chord part does it on every beat - and a merge turns
        # that into one held chord, which is audibly wrong.
        #
        # So an overlap ENDS the sounding note where the new one begins, and the
        # strike survives.  Only spans starting at the very same tick are one
        # strike, because there is nothing between them to hear.  Either way the
        # union of the sounding time is preserved, so nothing is cut short.
        merged, by_pitch = [], {}
        for start, dur, note, vel in notes:
            if note is None or not 0 <= note <= 127:
                continue
            by_pitch.setdefault(note, []).append((start, start + max(1, dur), vel))
        for note, spans in by_pitch.items():
            spans.sort()
            cur_s, cur_e, cur_v = spans[0]
            for s0, e0, v0 in spans[1:]:
                if s0 <= cur_s:                 # the same instant: one strike
                    cur_e = max(cur_e, e0)
                    cur_v = max(cur_v, v0)
                elif s0 < cur_e:                # restruck while still sounding
                    merged.append((cur_s, s0, note, cur_v))
                    cur_s, cur_e, cur_v = s0, max(cur_e, e0), max(cur_v, v0)
                else:
                    merged.append((cur_s, cur_e, note, cur_v))
                    cur_s, cur_e, cur_v = s0, e0, v0
            merged.append((cur_s, cur_e, note, cur_v))

        ev = []
        for start, stop, note, vel in merged:
            ev.append((start, 0, 0x90 | ch, note, vel))
            ev.append((stop, -1, 0x80 | ch, note, 0))
        ev.sort(key=lambda e: (e[0], e[1]))
        body = bytearray()
        body += varlen(0) + b'\xFF\x03' + bytes([len(name)]) + name.encode()
        if prog is not None:
            body += varlen(0) + bytes([0xC0 | ch, prog])
        last = 0
        for tick, _, status, d1, d2 in ev:
            body += varlen(max(0, tick - last)) + bytes([status, d1, d2])
            last = tick
        body += varlen(0) + b'\xFF\x2F\x00'
        chunks.append(struct.pack('>4sI', b'MTrk', len(body)) + bytes(body))
    with open(path, 'wb') as f:
        f.write(b''.join(chunks))


# ---------------------------------------------------------------- arrange

def arrange(card, out=None, chord_octave=0, bass_prog=32, chord_prog=24,
            bass_span=11, drop=(), vel=None, quiet=False, chip=False):
    """chip=True writes the parts as the PCS-30's own chip channels play them,
    for pcs30_synth.py rather than a General MIDI synth: the whole bass table
    stays on the bass channel with its own note-offs, and a step that strikes
    kick and snare together keeps both.  The three accommodations it drops are
    all for GM instruments, and each is marked where it happens."""
    vv = dict(melody=MELODY_VEL, obbligato=OBBLIGATO_VEL,
              bass=BASS_VEL, guitar=GUITAR_VEL)
    vv.update(vel or {})
    tab = PT.load()
    h = M.load(card)
    joined = False
    if h['type'] == 2:
        raise SystemExit('%s is a side B; give its side A' % os.path.basename(card))
    if not h['sections']:
        mate = M.side_b_for(card)
        if mate is None:
            raise SystemExit('%s has no section and no side B' % os.path.basename(card))
        h['sections'] = M.load(mate)['sections']
        joined = True

    key = h['transpose'] if h['transpose'] >= 0 else h['transpose'] + 16
    shift = M.key_shift(key)
    t1, t2, s0, s1 = R.resolve(h)

    # The melody carries the tune, so it sits on top; the obbligato is
    # already ducked by the card wherever the melody is playing.
    mel, tm, _, _ = M.build_part(t1, s0, shift, vel=vv['melody'], articulate=True)
    obb, to, _, _ = M.build_part(t2, s1, shift, duck=True, vel=vv['obbligato'],
                                 articulate=True)
    end = max(tm, to)

    marks, chords = marks_and_chords(t2, s1)

    row = h['rhythm'] - 1                       # rhythm 1..10 -> row 0..9
    style = P.RHYTHM[h['rhythm']]
    beats = 3 if h['rhythm'] == WALTZ else 4
    steps = 12 if h['rhythm'] in (WALTZ,) or h['rhythm'] in TRIPLET else 16
    bar_ticks = beats * 24
    step_ticks = bar_ticks // steps
    locked = bool(h['f3'] & 2)                  # header alternate-pattern bit

    nbars = int(end // bar_ticks) + 1
    bass, guitar, drums = [], [], []
    bass_v = Voice(bass, vv['bass'])
    chord_v = Voice(guitar, vv['guitar'], shift=12 * chord_octave)
    # The bass table's higher notes are not bass at all.  With only four-note
    # polyphony the keyboard folds part of the accompaniment into that voice, so
    # anything above the chord's own root note is routed to the guitar instead.
    upper_v = Voice(guitar, vv['guitar'], shift=12 * chord_octave)
    fills = muted_bars = alt_bars = roots_forced = routed = 0
    snares_dropped = kicks_dropped = 0

    # ROM 0x173E: when the chord ROOT changes, a flag is set and the next bass
    # note that actually sounds is forced to the root instead of whatever the
    # pattern says at that step.  The flag waits through holds and dead slots,
    # and the chord voice is never touched by it.
    prev_root, pending, prev_chord = 0x0F, False, None

    for bar in range(nbars):
        t0 = bar * bar_ticks
        # A mark takes effect where it lands, not at the bar line: one on beat
        # 1.75 stops the drums from there, and a fill triggered mid-bar plays
        # only the part of it that would remain had it started on the downbeat.
        here = [(t, BIT_OF_RAW[RAW_OF_MARK[v]]) for t, v in marks
                if t0 <= t < t0 + bar_ticks and v in RAW_OF_MARK]
        if any(b == 6 for _, b in here):
            muted_bars += 1
        if any(b <= 5 for _, b in here):
            fills += 1
        if locked or any(b == 7 for _, b in here):
            alt_bars += 1

        for s in range(steps):
            tick = t0 + s * step_ticks
            if tick >= end:
                break
            slot = (bar % 2) * 16 + s
            ch = chord_at(chords, tick)

            active = [b for t, b in here if t <= tick]
            drums_off = 6 in active
            fill_bits = [b for b in active if b <= 5]
            alternate = locked or (7 in active)

            for v in (bass_v, chord_v, upper_v):
                v.settle(tick)

            if ch is None:
                # The chart's accompaniment mute.  Whatever is sounding rings on
                # to the next bar rather than being cut where the mute lands.
                for v in (bass_v, chord_v, upper_v):
                    v.release(t0 + bar_ticks)
                prev_root, prev_chord = 0x0F, None
            else:
                root, minor, seventh = ch
                if (root, minor, seventh) != prev_chord and prev_chord is not None:
                    # The accompaniment follows the chord, so a note left over
                    # from the previous one stops here rather than ringing into
                    # the new harmony.  Without this a note struck late in a bar
                    # sustains across the bar line under the wrong chord.
                    chord_v.off(tick)
                    upper_v.off(tick)
                prev_chord = (root, minor, seventh)
                if root != prev_root:
                    pending = True
                ct, bt = TABLES[('B' if alternate else 'A', seventh)]
                bv = pattern_byte(tab, bt, row, slot)
                gv = pattern_byte(tab, ct, row, slot)
                # The split between real bass and folded-in accompaniment is the
                # OCTAVE, not the root: the plain bass tables use only degrees
                # 0, 4, 7, 12 and 16, so root/third/fifth are the bass line and
                # 12/16 are the accompaniment sharing the voice.  Seventh tables
                # add the walk notes and the flat seventh, all inside the octave.
                bass_ceiling = BASS_MIDI0 + root + bass_span

                if bv not in (0x00, 0xFF):
                    if pending:
                        bv = 1                  # the root
                        pending = False
                        roots_forced += 1
                    n = note_of(bv, root, minor)
                    if chip:
                        # The keyboard's bass channel plays the whole table,
                        # folded-in accompaniment notes and all, and stops
                        # where the table says.
                        bass_v.strike(tick, n)
                    elif n <= bass_ceiling:
                        # A real bass note.  It runs to the next bass note or to
                        # the bar line, whichever comes first - the pattern's own
                        # note-offs are ignored for this voice.
                        bass_v.strike(tick, n)
                        bass_v.release(t0 + bar_ticks)
                    else:
                        upper_v.strike(tick, n)
                        routed += 1
                elif bv == 0x00:
                    if chip:
                        bass_v.off(tick)
                    else:
                        upper_v.off(tick)       # only the rerouted voice stops

                if gv == 0x00:
                    chord_v.off(tick)
                elif gv != 0xFF:
                    chord_v.strike(tick, note_of(gv, root, minor))
                prev_root = root

            if not drums_off:
                if fill_bits:
                    m = drum_mask(tab, 1, fill_bits[0], slot)
                else:
                    bank, bit = (0, 7 - row) if row < 8 else (1, 15 - row)
                    m = drum_mask(tab, bank, bit, slot)
                    # Kick and snare land on the same step in five of the ten
                    # patterns.  On the real kit that reads as one accent; on a
                    # GM kit the snare is a separate loud hit, so a doubled
                    # step comes out cluttered and one of the two has to go.
                    # WHICH one depends on where the step is, and only the
                    # DOWNBEAT is a general case - a double anywhere else is
                    # the pattern's own syncopation and both belong (rhumba's
                    # are all off the beat, and samba's carry its swing).
                    # A FILL is exempt throughout: its snare is the point of
                    # it, which is why this sits in the non-fill branch.
                    if m & (1 << KICK) and m & (1 << SNARE) and not chip:
                        if s == 0:
                            m &= ~(1 << SNARE)      # the downbeat is the kick's
                            snares_dropped += 1
                        elif h['rhythm'] in SNARE_TAKES_THE_BACKBEAT:
                            m &= ~(1 << KICK)
                            kicks_dropped += 1
                for b, gm in DRUM_GM.items():
                    if m >> b & 1:
                        drums.append((tick, step_ticks, gm, DRUM_VEL[gm]))

    for v in (bass_v, chord_v, upper_v):
        v.settle(end)
        v.off(end)
    guitar.sort()

    mv = M.voice_name(M.MELODY_VOICE, h['field4'])
    ov = M.voice_name(M.OBBLIGATO_VOICE, h['field6'])
    moct, ooct = GM_OCTAVE.get(mv, 0), GM_OCTAVE.get(ov, 0)
    parts = [('melody %s' % mv, 0, GM_VOICE.get(mv, 0),
              [(a, b, c + moct, e) for a, b, c, _, e in mel]),
             ('obbligato %s' % ov, 1, GM_VOICE.get(ov, 0),
              [(a, b, c + ooct, e) for a, b, c, _, e in obb]),
             ('bass', 2, bass_prog, bass),
             ('guitar', 3, chord_prog, guitar),
             ('drums', 9, None, drums)]
    # Dropping the melody leaves a backing track to play or sing over.  The
    # part is removed entirely rather than silenced, so nothing has to be muted
    # in whatever plays the file.
    if drop:
        parts = [p for p in parts if p[0].split()[0] not in drop]

    if out is None:
        base = os.path.splitext(os.path.basename(card))[0].replace('_side-a', '')
        out = base + '_pcs30.mid'
    write_midi(out, parts, h['tempo'], beats=beats)
    arrange.parts = parts                       # kept for inspection by tools

    if not quiet:
        print('%s' % os.path.basename(card))
        if joined:
            print('  joined with its side B')
        print('  %d bpm, %s, %d bars of %d beats, %d steps per bar'
              % (h['tempo'], style, nbars, beats, steps))
        print('  accompaniment: %s pattern%s'
              % ('alternate' if locked else 'standard',
                 ' (locked by the header)' if locked else
                 (', %d bar%s switched by mark 7' % (alt_bars, '' if alt_bars == 1 else 's')
                  if alt_bars else '')))
        if drop:
            print('  dropped  : %s' % ', '.join(sorted(drop)))
        print('  melody   : %4d notes  %-8s -> GM %-3d%s'
              % (len(mel), mv, GM_VOICE.get(mv, 0), '  +1 octave' if moct else ''))
        print('  obbligato: %4d notes  %-8s -> GM %-3d%s'
              % (len(obb), ov, GM_VOICE.get(ov, 0), '  +1 octave' if ooct else ''))
        print('  bass     : %4d notes, %d forced to the root by a chord change'
              % (len(bass), roots_forced))
        print('  guitar   : %4d notes, %d of them rerouted from the bass voice'
              % (len(guitar), routed))
        print('  velocity : melody %d, obbligato %d, bass %d, guitar %d'
              % (vv['melody'], vv['obbligato'], vv['bass'], vv['guitar']))
        print('  drums    : %4d hits, %d bar%s muted, %d bar%s with a fill%s'
              % (len(drums), muted_bars, '' if muted_bars == 1 else 's',
                 fills, '' if fills == 1 else 's',
                 ''.join(x for x in (
                     ', %d snare%s off the downbeat kick' % (
                         snares_dropped, '' if snares_dropped == 1 else 's')
                     if snares_dropped else '',
                     ', %d kick%s off the backbeat snare' % (
                         kicks_dropped, '' if kicks_dropped == 1 else 's')
                     if kicks_dropped else ''))))
        print('  -> %s' % out)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('card', nargs='?')
    ap.add_argument('-o', '--out')
    ap.add_argument('--all', action='store_true',
                    help='arrange every card in a folder instead of one')
    ap.add_argument('--in-dir',
                    help='with --all, the folder to read cards from '
                         '(default: the card corpus; use . for the current one)')
    ap.add_argument('--out-dir', default=os.path.join(P.HERE, 'pcs30-midi'),
                    help='with --all, where the .mid files go (default: pcs30-midi/)')
    ap.add_argument('--chord-octave', type=int, default=0,
                    help='shift the guitar part by whole octaves')
    for part, dflt in (('melody', MELODY_VEL), ('obbligato', OBBLIGATO_VEL),
                       ('bass', BASS_VEL), ('guitar', GUITAR_VEL)):
        ap.add_argument('--%s-velocity' % part, type=int, default=dflt,
                        help='MIDI velocity for the %s (default %d)' % (part, dflt))
    ap.add_argument('--no-melody', action='store_true',
                    help='leave the melody out, for a backing or karaoke track')
    ap.add_argument('--no-obbligato', action='store_true',
                    help='leave the counter-melody out as well')
    ap.add_argument('--bass-span', type=int, default=11,
                    help='semitones above the root that still count as bass; '
                         'anything higher is routed to the guitar (default 11, '
                         'the whole octave - use 7 to stop at the fifth)')
    ap.add_argument('--chip', action='store_true',
                    help="the parts as the PCS-30's own chip channels play them - the "
                         'whole bass table on the bass channel, every drum strike - '
                         'for pcs30_synth.py rather than a General MIDI synth')
    ap.add_argument('--bass-program', type=int, default=32, help='GM program (default 32)')
    ap.add_argument('--chord-program', type=int, default=24, help='GM program (default 24)')
    a = ap.parse_args()
    if not a.all and not a.card:
        ap.error('give a card, or --all to arrange a whole folder')

    drop = set()
    if a.no_melody:
        drop.add('melody')
    if a.no_obbligato:
        drop.add('obbligato')
    vel = dict(melody=a.melody_velocity, obbligato=a.obbligato_velocity,
               bass=a.bass_velocity, guitar=a.guitar_velocity)
    opts = (a.chord_octave, a.bass_program, a.chord_program, a.bass_span, drop, vel)
    extra = dict(chip=a.chip)

    try:
        if not a.all:
            arrange(a.card, a.out, *opts, **extra)
            return

        if a.in_dir:
            cards = sorted(glob.glob(os.path.join(a.in_dir, '*.bin')))
            if not cards:
                sys.exit('no .bin card images in %s' % a.in_dir)
        else:
            cards = P.corpus()
        os.makedirs(a.out_dir, exist_ok=True)

        ok = side_b = bad = 0
        for f in cards:
            # A two-sided card is written once, from its side A, under the name
            # with the suffix dropped - the same naming midi_export.py picks.
            base = os.path.basename(os.path.splitext(f)[0]).replace('_side-a', '')
            try:
                if arrange(f, os.path.join(a.out_dir, base + '.mid'), *opts, quiet=True):
                    ok += 1
                else:
                    bad += 1
            except SystemExit as e:
                # arrange() declines a side B, and says why
                side_b += 1
                if 'side B' not in str(e):
                    print('%s: %s' % (os.path.basename(f), e))
            except Exception as e:
                bad += 1
                print('%s: %s' % (os.path.basename(f), e))
        print('%d cards arranged into %s' % (ok, a.out_dir))
        if side_b or bad:
            print('%d skipped as side-B continuations, %d failed' % (side_b, bad))
    except (P.Missing, PT.Missing) as e:
        sys.exit(str(e))


if __name__ == '__main__':
    P.run(main)
