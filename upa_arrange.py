#!/usr/bin/env python3
"""A Playcard as a full MIDI arrangement, using the UPA-01's own accompaniment.

    python upa_arrange.py card.bin [-o out.mid]
    python upa_arrange.py card.bin --fill-feel card    # keep the cartridge's bug
    python upa_arrange.py --all                        # a whole folder

What comes out is what the UPA-01 cartridge plays from this card: the melody and
obbligato are the card's own, and the bass, chord and drums are the cartridge's
patterns for its rhythm. `pcs30_arrange.py` does the same job with the PCS-30
keyboard's patterns, and shares most of its machinery with this - the card walk,
the held-note voice and the MIDI writer all come from there.

Five parts:

    ch 1  melody      the card's melody voice, mapped to the nearest GM voice
    ch 2  obbligato   likewise, ducked where the card ducks it
    ch 3  bass        the cartridge's bass line for the card's rhythm
    ch 4  chord       its chord part, voiced as below
    ch 10 drums       its five drums, kept apart on the GM kit

NEEDS DATA THAT IS DELIBERATELY NOT IN THIS REPOSITORY. The card images are
Yamaha's; put your own in `Original Playcards/`, or point `PLAYCARD_CARDS` at
them. So are the patterns: run `upa_extract.py` once against your own cartridge
ROM and this will find them.

Where the patterns come from, and what they say
-----------------------------------------------
`upa_extract.py`'s docstring and "The accompaniment patterns" in `HANDOFF.md`
have the detail. In short: one block a rhythm for the drums and one for the
accompaniment, two bars each, one byte a step. A drum byte is a five-bit mask; an
accompaniment byte holds the standard pattern in its low nibble and the alternate
in its high one, three bits of it a bass note as a chord-tone number and one bit
a chord strike. **Everything happens where a field changes**, so a run of equal
bytes is one held note.

Four places where this does not do what the cartridge does
----------------------------------------------------------
Each is either a fault of the cartridge or a fact about MIDI, and each is the
owner's decision rather than a reading of the ROM.

* **Chords land on the beat.** The cartridge plays its chord part one step late -
  every chord in every rhythm, which is why bossa-nova's syncopated chord and
  slow-rock's alternate sound off the beat on the real thing. Drop that step and
  all ten rhythms' chords fall on a clean sixteenth (or, on the swung rhythms, a
  triplet eighth), which is plainly what was meant. The bass is never late.

* **The chord is voiced for a synthesizer.** The cartridge keys the same two
  notes for every chord - a root and a flattened third - and gets the real chord
  from the FM multipliers, so its key codes cannot be exported. `upa_rhythm.py`
  holds the voicing used instead: root, third and fifth, plus the flattened
  seventh on a seventh chord, in the octave band that ends at C5, and a bass root
  of C2 that drops an octave from G upwards.

* **A fill's feel follows the rhythm.** The cartridge stores each fill in one
  feel and plays it that way whatever the rhythm - fills 1 and 2 straight, 3 and
  4 swung, 5 and 6 for the waltz - while the PC-100 and the PCS-30 play any fill
  in the rhythm's own feel. Since the authoring system chose fills to match
  (across the corpus, 1 and 2 appear on straight cards, 3 and 4 on swing and
  slow-rock, 5 and 6 only on waltzes), the disagreement bites about fifty marks,
  of which the biggest group is fill 3 on disco and rock cards. `--fill-feel
  rhythm`, the default, swaps in the fill of the same rank in the group that
  matches: 3 and 4 become 1 and 2 on a straight rhythm, 1 and 2 become 3 and 4 on
  a swung one, and anything on a waltz card becomes 5 or 6. Fills 1 and 3 are the
  same figure in the two feels, so that swap is exact; the others are not, so the
  figure changes with the feel. `--fill-feel card` keeps the cartridge's choice,
  bug and all.

* **Bass and chord notes hold until something strikes again**, across bar lines
  and through the pattern's own rests, which is how the PCS-30 sounds. They are
  cut at the end of the bar in the two places where nothing will strike again:
  where the chart mutes the accompaniment, and at the end of the card. On a chord
  change whatever is held stops rather than ringing on under the new harmony -
  the cartridge instead rewrites its multipliers, so the same note changes pitch,
  which MIDI cannot do without a new strike.

The drums are kept apart
------------------------
The cartridge plays its five drums with four voices - the snare and the latin
drum are the same one, which is why it sounds as though it has three. On the GM
kit all five stay separate, so a samba's congas are congas.
"""

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playcard_decode as P
import playcard_resolve as R
import midi_export as M
import pcs30_arrange as A               # the card walk, the voice, the MIDI writer
import upa_extract as X
import upa_rhythm as U

# The five mask bits on the GM kit, kept apart.  The second cymbal is the
# cartridge's other channel-6 voice; the two are close enough by ear that the
# ROM is the only place they are plainly different, so they go to the two
# hi-hats.  The latin drum plays rhumba's and samba's busy figure, so it is a
# conga rather than the claves `pcs30_arrange.py` uses for the PCS-30's sparser
# clave line.
DRUM_GM = {7: 42,                       # cymbal        -> closed hi-hat
           6: 46,                       # second cymbal -> open hi-hat
           5: 36,                       # kick          -> bass drum 1
           4: 63,                       # latin         -> open high conga
           3: 38}                       # snare         -> acoustic snare
DRUM_VEL = {42: 60, 46: 66, 36: 96, 63: 72, 38: 92}

CHORD_VEL = 86
DRUM_LEN = 6                            # a sixteenth; long enough for any kit

# Which fills belong to which rhythm, for --fill-feel rhythm.  The groups are
# the cartridge's own: two fills written straight, two written swung, two for
# the waltz, and a card's mark asks for one of the six by number.
FILL_GROUP = {'straight': (1, 2), 'swung': (3, 4), 'waltz': (5, 6)}
SWUNG = {3, 8}                          # swing, slow-rock, by card rhythm number
WALTZ = 7


def fill_group(rhythm):
    return 'waltz' if rhythm == WALTZ else \
        ('swung' if rhythm in SWUNG else 'straight')


def fill_for(rhythm, mark, feel):
    """The fill block to play for a mark, as a 1-based fill number."""
    if feel == 'card':
        return mark
    group = FILL_GROUP[fill_group(rhythm)]
    for g in FILL_GROUP.values():
        if mark in g:
            return group[g.index(mark)]
    return mark


class Chord(object):
    """The chord part: several notes struck and released together.

    The same holding rules as `pcs30_arrange.Voice`, over a set of notes, so a
    chord rings until the next strike and can have its end scheduled for a bar
    line that a strike may cut short."""

    def __init__(self, notes, vel):
        self.out, self.vel = notes, vel
        self.notes, self.start, self.deadline = None, None, None

    def _close(self, tick):
        if self.notes and tick > self.start:
            for n in self.notes:
                self.out.append((self.start, tick - self.start, n, self.vel))
        self.notes = self.start = self.deadline = None

    def off(self, tick):
        self._close(tick)

    def release(self, tick):
        if self.notes:
            self.deadline = tick if self.deadline is None else min(self.deadline, tick)

    def settle(self, now):
        if self.deadline is not None and now >= self.deadline:
            self._close(self.deadline)

    def strike(self, tick, notes):
        end = tick if self.deadline is None else min(self.deadline, tick)
        self._close(end)
        self.notes, self.start = list(notes), tick


def steps_of(row):
    return [int(row['steps'][k:k + 2], 16) for k in range(0, len(row['steps']), 2)]


def played(row, bar_ticks):
    """The step indices a block actually plays, in order, over its two bars.

    A three-beat block is stored on the four-beat grid and the engine skips the
    stored fourth beat of each bar (ROM 0x5111), so those steps never sound and
    the step before the bar line is not the one before it in the table."""
    steps = steps_of(row)
    ticks = row['ticks_a_step']
    half = len(steps) // 2
    out = []
    for bar in (0, 1):
        for i in range(half):
            if i * ticks < bar_ticks:
                out.append((bar, i * ticks, bar * half + i))
    return steps, ticks, out


def arrange(card, out=None, fill_feel='rhythm', vel=None, drop=(), quiet=False,
            tables=X.TABLES):
    vv = dict(melody=A.MELODY_VEL, obbligato=A.OBBLIGATO_VEL,
              bass=A.BASS_VEL, chord=CHORD_VEL)
    vv.update(vel or {})
    doc = X.load(tables)

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
    mel, tm, _, _ = M.build_part(t1, s0, shift, vel=vv['melody'], articulate=True)
    obb, to, _, _ = M.build_part(t2, s1, shift, duck=True, vel=vv['obbligato'],
                                 articulate=True)
    end = max(tm, to)
    marks, chords = A.marks_and_chords(t2, s1)

    rhythm = h['rhythm']                        # 1..10, the card's numbering
    row = rhythm - 1
    drum_row, acc_row = doc['drums'][row], doc['accompaniment'][row]
    beats = drum_row['beats']
    bar_ticks = beats * 24
    nbars = int(end // bar_ticks) + 1
    locked = bool(h['f3'] & 2)                  # the header's alternate lock

    bass, chord_out, drums = [], [], []
    bass_v = A.Voice(bass, vv['bass'])
    chord_v = Chord(chord_out, vv['chord'])

    acc_steps, acc_ticks, acc_play = played(acc_row, bar_ticks)
    fills = muted_bars = alt_bars = 0

    # ---- the accompaniment: bass where its number changes, chord where its bit
    # rises.  The cartridge sends the chord a step later than this; see the
    # docstring.
    prev_chord = None
    for bar in range(nbars):
        t0 = bar * bar_ticks
        here = [(t, v) for t, v in marks if t0 <= t < t0 + bar_ticks]
        if locked or any(v == 7 for _, v in here):
            alt_bars += 1
        for i, (half, st, k) in enumerate(acc_play):
            if half != bar % 2:
                continue
            tick = t0 + st
            if tick >= end:
                break
            alternate = locked or any(v == 7 and t <= tick for t, v in here)
            sh = 4 if alternate else 0
            prev = acc_steps[acc_play[i - 1][2]]
            now, was = acc_steps[k] >> sh, prev >> sh

            for v in (bass_v, chord_v):
                v.settle(tick)
            ch = A.chord_at(chords, tick)
            if ch is None:
                # the chart's accompaniment mute: what is sounding rings on to
                # the bar line, because nothing will strike it off
                for v in (bass_v, chord_v):
                    v.release(t0 + bar_ticks)
                prev_chord = None
                continue
            root, minor, seventh = ch
            quality = (1 if minor else 0) + (2 if seventh else 0)
            if prev_chord is not None and (root, quality) != prev_chord:
                bass_v.off(tick)
                chord_v.off(tick)
            prev_chord = (root, quality)

            if now & 7 and (now & 7) != (was & 7):
                n = U.bass_note(root, now & 7, quality)
                if n is not None:
                    bass_v.strike(tick, n)      # holds until the next strike
            if now & 8 and not was & 8:
                chord_v.strike(tick, U.chord_notes(root, quality))

    for v in (bass_v, chord_v):
        v.settle(end)
        v.off(end)

    # ---- the drums, from the rhythm's block or a fill's.  Each block is walked
    # by (which bar, which tick), so a fill on a different grid still lines up.
    def block(row_):
        steps, ticks_, play = played(row_, bar_ticks)
        return steps, play, {(hf, st): j for j, (hf, st, _) in enumerate(play)}

    rowsteps, rplay, rwhere = block(drum_row)
    fblock = {}
    fill_used = {}
    for bar in range(nbars):
        t0 = bar * bar_ticks
        here = [(t, v) for t, v in marks if t0 <= t < t0 + bar_ticks]
        if any(v == 0 for _, v in here):
            muted_bars += 1
        asked = [v for _, v in here if 1 <= v <= 6]
        if asked:
            fills += 1
        for t, v in here:
            if 1 <= v <= 6:
                f = fill_for(rhythm, v, fill_feel)
                fill_used[f] = fill_used.get(f, 0) + 1
        for half, st, k in rplay:
            if half != bar % 2:
                continue
            tick = t0 + st
            if tick >= end:
                break
            active = [v for t, v in here if t <= tick]
            if 0 in active:
                continue                        # the drum mute
            asked_now = [v for v in active if 1 <= v <= 6]
            if asked_now:
                f = fill_for(rhythm, asked_now[-1], fill_feel)
                if f not in fblock:
                    fblock[f] = block(doc['fills'][f - 1])
                usteps, use, where = fblock[f]
            else:
                usteps, use, where = rowsteps, rplay, rwhere
            idx = where.get((bar % 2, st))
            if idx is None:
                continue                        # a step this block does not have
            now = usteps[use[idx][2]]
            was = usteps[use[idx - 1][2]]
            for bit, gm in DRUM_GM.items():
                if now >> bit & 1 and not was >> bit & 1:
                    drums.append((tick, DRUM_LEN, gm, DRUM_VEL[gm]))

    bass.sort()
    chord_out.sort()
    drums.sort()

    mv = M.voice_name(M.MELODY_VOICE, h['field4'])
    ov = M.voice_name(M.OBBLIGATO_VOICE, h['field6'])
    moct, ooct = A.GM_OCTAVE.get(mv, 0), A.GM_OCTAVE.get(ov, 0)
    parts = [('melody %s' % mv, 0, A.GM_VOICE.get(mv, 0),
              [(a, b, c + moct, e) for a, b, c, _, e in mel]),
             ('obbligato %s' % ov, 1, A.GM_VOICE.get(ov, 0),
              [(a, b, c + ooct, e) for a, b, c, _, e in obb]),
             ('bass', 2, 32, bass),
             ('chord', 3, 24, chord_out),
             ('drums', 9, None, drums)]
    if drop:
        parts = [p for p in parts if p[0].split()[0] not in drop]

    if out is None:
        base = os.path.splitext(os.path.basename(card))[0].replace('_side-a', '')
        out = base + '_upa.mid'
    A.write_midi(out, parts, h['tempo'], beats=beats)
    arrange.parts = parts

    if not quiet:
        print('%s' % os.path.basename(card))
        if joined:
            print('  joined with its side B')
        print('  %d bpm, %s, %d bars of %d beats, %d ticks a step'
              % (h['tempo'], P.RHYTHM[rhythm], nbars, beats, acc_ticks))
        print('  accompaniment: %s pattern%s'
              % ('alternate' if locked else 'standard',
                 ' (locked by the header)' if locked else
                 (', %d bar%s switched by mark 7' % (alt_bars, '' if alt_bars == 1 else 's')
                  if alt_bars else '')))
        print('  melody   : %4d notes  %-8s -> GM %-3d%s'
              % (len(mel), mv, A.GM_VOICE.get(mv, 0), '  +1 octave' if moct else ''))
        print('  obbligato: %4d notes  %-8s -> GM %-3d%s'
              % (len(obb), ov, A.GM_VOICE.get(ov, 0), '  +1 octave' if ooct else ''))
        print('  bass     : %4d notes, held to the next strike' % len(bass))
        print('  chord    : %4d notes, on the beat (the cartridge is a step late)'
              % len(chord_out))
        print('  drums    : %4d hits, %d bar%s muted, %d bar%s with a fill%s'
              % (len(drums), muted_bars, '' if muted_bars == 1 else 's',
                 fills, '' if fills == 1 else 's',
                 ('  fills used: %s' % ' '.join('%d x%d' % kv
                                                for kv in sorted(fill_used.items()))
                  if fill_used else '')))
        print('  fill feel: %s' % ('the rhythm\'s (%s)' % fill_group(rhythm)
                                   if fill_feel == 'rhythm' else "the card's, as the cartridge plays it"))
        print('  -> %s' % out)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('card', nargs='?')
    ap.add_argument('-o', '--out')
    ap.add_argument('--all', action='store_true',
                    help='arrange every card in a folder instead of one')
    ap.add_argument('--in-dir', help='with --all, the folder to read cards from')
    ap.add_argument('--out-dir', default=os.path.join(P.HERE, 'upa-midi'),
                    help='with --all, where the .mid files go (default: upa-midi/)')
    ap.add_argument('--fill-feel', choices=('rhythm', 'card'), default='rhythm',
                    help="whose feel a fill takes: the rhythm's, as the PC-100 and "
                         "the PCS-30 play it (default), or the card's fill number, "
                         'as the cartridge does')
    for part, dflt in (('melody', A.MELODY_VEL), ('obbligato', A.OBBLIGATO_VEL),
                       ('bass', A.BASS_VEL), ('chord', CHORD_VEL)):
        ap.add_argument('--%s-velocity' % part, type=int, default=dflt,
                        help='MIDI velocity for the %s (default %d)' % (part, dflt))
    ap.add_argument('--no-melody', action='store_true', help='leave the melody out')
    ap.add_argument('--no-obbligato', action='store_true', help='and the obbligato')
    a = ap.parse_args()

    vel = dict(melody=a.melody_velocity, obbligato=a.obbligato_velocity,
               bass=a.bass_velocity, chord=a.chord_velocity)
    drop = set()
    if a.no_melody:
        drop.add('melody')
    if a.no_obbligato:
        drop.add('obbligato')

    try:
        X.load()
    except X.Missing as e:
        print(e)
        return 1

    if a.all:
        where = a.in_dir or P.CARD_DIR
        cards = sorted(glob.glob(os.path.join(where, '*.bin')))
        if not cards:
            print('upa_arrange: no cards in %s' % where)
            return 1
        if not os.path.isdir(a.out_dir):
            os.makedirs(a.out_dir)
        done = 0
        for c in cards:
            try:
                h = M.load(c)
                if h['type'] == 2:
                    continue
                base = os.path.splitext(os.path.basename(c))[0].replace('_side-a', '')
                arrange(c, os.path.join(a.out_dir, base + '_upa.mid'),
                        fill_feel=a.fill_feel, vel=vel, drop=drop, quiet=True)
                done += 1
            except SystemExit as e:
                print('  %s: %s' % (os.path.basename(c), e))
        print('%d cards arranged into %s' % (done, a.out_dir))
        return 0

    if not a.card:
        ap.error('give a card, or --all')
    arrange(a.card, a.out, fill_feel=a.fill_feel, vel=vel, drop=drop)
    return 0


if __name__ == '__main__':
    P.run(main)
