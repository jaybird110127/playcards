#!/usr/bin/env python3
"""A Playcard as a full MIDI arrangement, using the UPA-01's own accompaniment.

    python upa_arrange.py card.bin [-o out.mid]
    python upa_arrange.py card.bin --drums upa         # no PCS-30 ROM needed
    python upa_arrange.py card.bin --as-is             # what the cartridge plays
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

Where this does not do what the cartridge does
---------------------------------------------
Every one of these is either a fault of the cartridge or a fact about MIDI, and
every one is the owner's decision rather than a reading of the ROM. `--as-is`
turns the lot off and plays what the cartridge plays.

* **Chords land on the beat.** The cartridge plays its chord part one step late -
  every chord in every rhythm - which is why slow-rock's busy alternate sounds
  off the beat on the real thing. Drop that step and all ten rhythms' chords fall
  on a clean sixteenth, or a triplet eighth on the swung ones. The bass is never
  late.

* **Bossa-nova's last chord is moved onto the clave.** That pattern is the bossa
  clave, 3+3+4+3+3 sixteenths - beats 1, 2 1/2, 4, 6, 7 1/2 over its two bars -
  and its last stroke is written a sixteenth late, at 7 3/4. Two things say so
  rather than one: every other stroke is exactly on the clave, and every other
  chord in the block is held a quarter note while that one is held a quarter less
  a sixteenth, exactly as a stroke starting two steps late would be. It is the
  only asymmetry of its kind in the twenty patterns, and it is audible.

* **The chord is voiced for a synthesizer.** The cartridge keys the same two
  notes for every chord - a root and a flattened third - and gets the real chord
  from the FM multipliers, so its key codes cannot be exported. `upa_rhythm.py`
  holds the voicing used instead: root, third and fifth, plus the flattened
  seventh on a seventh chord, in the octave band that ends at C5, and a bass root
  of C2 that drops an octave from G upwards.

* **A chord change forces the next bass note to the new root**, whatever the
  pattern holds at that step, and the flag waits through rests so the root lands
  on the next actual strike. That is the PCS-30's own rule (its ROM 0x173E), and
  it is what keeps the bass line following the harmony.

* **A fill's feel follows the rhythm.** The cartridge stores each fill in one
  feel and plays it that way whatever the rhythm - fills 1 and 2 straight, 3 and
  4 swung, 5 and 6 for the waltz - while the PC-100 and the PCS-30 play any fill
  in the rhythm's own feel. Since the authoring system chose fills to match
  (across the corpus, 1 and 2 appear on straight cards, 3 and 4 on swing and
  slow-rock, 5 and 6 only on waltzes), the disagreement bites about fifty marks,
  of which the biggest group is fill 3 on disco and rock cards. `--fill-feel
  rhythm`, the default, swaps in the fill of the same rank in the group that
  matches. Fills 1 and 3 are the same figure in the two feels, so that swap is
  exact; the others are not, so the figure changes with the feel.

* **Notes hold, but not for ever.** A bass note runs until the next bass note.
  A chord rings **to the next beat**, which is what stops the texture smearing,
  and where the chart mutes the accompaniment it is held out to the bar line
  instead - both as `pcs30_arrange.py` does it. A chord change stops whatever is
  held rather than letting it ring under the new harmony; the cartridge instead
  rewrites its multipliers, so one note changes pitch, which MIDI cannot do
  without a new strike.

Whose drums
-----------
Both machines have the same five drums - kick, latin drum, snare, and a long and
a short cymbal - so their patterns can be mixed, and `--drums` says how. The
default, `mixed`, is what sounds best: **the PCS-30's patterns for the ten
rhythms**, because the cartridge's have oddities the keyboard's do not, **the
cartridge's own fills 1 to 4**, which are the better ones, and **the PCS-30's for
the waltz pair 5 and 6**. `--drums upa` is all the cartridge's and needs no
PCS-30 ROM; `--drums pcs30` is all the keyboard's, which is `pcs30_arrange.py`'s
drum track with this card's accompaniment.

All five stay separate on the GM kit, even though the cartridge itself plays the
snare and the latin drum with one voice - which is why it sounds as though it has
three drums. So a samba's congas are congas.
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
import pcs30_tables as PT               # its drum patterns, for --drums
import upa_extract as X
import upa_rhythm as U

# Both machines have the same five drums, so the GM kit is addressed by name and
# each machine's bits are mapped onto it.  The two cymbals are the cartridge's
# two channel-6 voices, close enough by ear that the ROM is the only place they
# are plainly different, so they go to the two hi-hats; the latin drum is a conga
# (`pcs30_arrange.py` makes it claves, because there it plays the son clave).
GM = {'kick': 36, 'snare': 38, 'latin': 63, 'cymbal-short': 42, 'cymbal-long': 46}
VEL = {'kick': 96, 'snare': 92, 'latin': 72, 'cymbal-short': 60, 'cymbal-long': 66}

# bit -> drum, for each machine's own strike mask
UPA_BITS = {7: 'cymbal-short', 6: 'cymbal-long', 5: 'kick', 4: 'latin', 3: 'snare'}
PCS_BITS = {4: 'cymbal-short', 3: 'cymbal-long', 2: 'snare', 1: 'latin', 0: 'kick'}

# A correction to the pattern data itself, in steps, by card rhythm.
#
# Bossa-nova's chord pattern is the bossa clave - 3+3+4+3+3 sixteenths, which is
# beats 1, 2 1/2, 4, 6, 7 1/2 over its two bars - except that its last stroke is
# written a sixteenth late, at 7 3/4.  Two things say so rather than one: every
# other stroke is exactly on the clave, and every other chord in the block is
# held a quarter note while that one is held a quarter less a sixteenth, as a
# stroke starting two steps late would be.  It is audible, and it is the only
# asymmetry of its kind in any of the twenty patterns.  `--as-is` leaves it.
CHORD_FIX = {4: {54: -2}}               # bossa-nova, block step 54, two earlier

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


def fills_from(fill, source):
    """Whose fill to play.  The cartridge's four-beat fills are the better ones
    by ear; its waltz pair, 5 and 6, are not, so those come from the PCS-30."""
    if source in ('upa', 'pcs30'):
        return source
    return 'pcs30' if fill in (5, 6) else 'upa'


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

    def hold(self, tick):
        """Push a scheduled end later - an accompaniment mute does this, so a
        chord caught by one rings to the bar line instead of to the next beat."""
        if self.notes and self.deadline is not None:
            self.deadline = max(self.deadline, tick)

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
            tables=X.TABLES, source='mixed', as_is=False):
    vv = dict(melody=A.MELODY_VEL, obbligato=A.OBBLIGATO_VEL,
              bass=A.BASS_VEL, chord=CHORD_VEL)
    vv.update(vel or {})
    if as_is:
        source, fill_feel = 'upa', 'card'
    doc = X.load(tables)
    tab30 = None
    if source != 'upa':
        try:
            tab30 = PT.load()
        except PT.Missing as e:
            raise SystemExit('%s\nOr arrange with the cartridge\'s own drums: '
                             '--drums upa' % e)

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
    fills = muted_bars = alt_bars = roots_forced = fixed = 0

    # ---- the accompaniment: bass where its number changes, chord where its bit
    # rises.  The cartridge sends the chord a step later than this; see the
    # docstring.
    prev_chord, prev_root, pending = None, None, False
    fix = {} if as_is else CHORD_FIX.get(rhythm, {})
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
                # The chart's accompaniment mute.  The bass rings to the bar
                # line, and a chord caught by the mute is held out to it too
                # rather than stopping at the next beat.
                bass_v.release(t0 + bar_ticks)
                chord_v.hold(t0 + bar_ticks)
                chord_v.release(t0 + bar_ticks)
                prev_chord, prev_root = None, None
                continue
            root, minor, seventh = ch
            quality = (1 if minor else 0) + (2 if seventh else 0)
            if prev_chord is not None and (root, quality) != prev_chord:
                bass_v.off(tick)
                chord_v.off(tick)
            prev_chord = (root, quality)
            if prev_root is not None and root != prev_root:
                # The chord has moved, so the next bass note to sound is the new
                # ROOT rather than whatever the pattern holds at that step - the
                # PCS-30's own rule (its ROM 0x173E).  The flag waits through
                # rests, so the root lands on the next actual strike.
                pending = True
            prev_root = root

            if now & 7 and (now & 7) != (was & 7):
                tone = now & 7
                if pending and not as_is:
                    tone, pending = 1, False
                    roots_forced += 1
                n = U.bass_note(root, tone, quality)
                if n is not None:
                    bass_v.strike(tick, n)      # holds until the next strike
            if now & 8 and not was & 8:
                at = tick + (acc_ticks if as_is else 0)
                if k in fix:
                    at += fix[k] * acc_ticks    # a correction, in steps
                    fixed += 1
                chord_v.strike(at, U.chord_notes(root, quality))
                # a chord rings to the next beat, unless a mute holds it longer
                chord_v.release((at // 24 + 1) * 24)

    for v in (bass_v, chord_v):
        v.settle(end)
        v.off(end)

    # ---- the drums.  Two machines' patterns can be mixed, because both have the
    # same five drums: by default the PCS-30's for the rhythms, the cartridge's
    # own for fills 1 to 4, and the PCS-30's for the waltz pair 5 and 6.
    def upa_block(row_):
        steps, _, play = played(row_, bar_ticks)
        return steps, play, {(hf, st): j for j, (hf, st, _) in enumerate(play)}

    def upa_strikes(row_, bar, t0):
        """What a cartridge block strikes in this bar: {tick: [drum, ...]}."""
        steps, play, where = upa_block(row_)
        out = {}
        for j, (half, st, k) in enumerate(play):
            if half != bar % 2:
                continue
            now, was = steps[k], steps[play[j - 1][2]]
            hit = [d for bit, d in UPA_BITS.items()
                   if now >> bit & 1 and not was >> bit & 1]
            if hit:
                out[t0 + st] = hit
        return out

    pcs_steps = 12 if rhythm in A.TRIPLET or rhythm == WALTZ else 16
    pcs_step_ticks = bar_ticks // pcs_steps

    def pcs_strikes(bank_bit, bar, t0, separate):
        """What a PCS-30 bank entry strikes in this bar, on the rhythm's grid."""
        bank, bit = bank_bit
        out = {}
        for s in range(pcs_steps):
            m = tab30.drum_mask(bank, bit, (bar % 2) * 16 + s)
            if separate and m & (1 << A.KICK) and m & (1 << A.SNARE):
                # pcs30_arrange's rule, kept so the two tools agree: a doubled
                # step is cluttered on a GM kit, the downbeat belongs to the
                # kick, and disco is the exception that gives it to the snare.
                if s == 0:
                    m &= ~(1 << A.SNARE)
                elif rhythm in A.SNARE_TAKES_THE_BACKBEAT:
                    m &= ~(1 << A.KICK)
            hit = [d for bit_, d in PCS_BITS.items() if m >> bit_ & 1]
            if hit:
                out[t0 + s * pcs_step_ticks] = hit
        return out

    row30 = rhythm - 1
    pcs_rhythm_at = (0, 7 - row30) if row30 < 8 else (1, 15 - row30)
    fill_used = {}
    for bar in range(nbars):
        t0 = bar * bar_ticks
        here = [(t, v) for t, v in marks if t0 <= t < t0 + bar_ticks]
        if any(v == 0 for _, v in here):
            muted_bars += 1
        asked = [v for _, v in here if 1 <= v <= 6]
        if asked:
            fills += 1

        # the pattern in force at the start of the bar, and where it changes
        plan = []                               # (from tick, {tick: [drum,...]})
        mark_ticks = [t0] + [t for t, v in here if v == 0 or 1 <= v <= 6]
        for at in sorted(set(mark_ticks)):
            active = [v for t, v in here if t <= at]
            if 0 in active:
                plan.append((at, {}))           # the drum mute
                continue
            asked_now = [v for v in active if 1 <= v <= 6]
            if asked_now:
                f = fill_for(rhythm, asked_now[-1], fill_feel)
                fill_used[f] = fill_used.get(f, 0) + 1
                if fills_from(f, source) == 'pcs30':
                    bit = A.BIT_OF_RAW[A.RAW_OF_MARK[f]]
                    plan.append((at, pcs_strikes((1, bit), bar, t0, False)))
                else:
                    plan.append((at, upa_strikes(doc['fills'][f - 1], bar, t0)))
            elif source == 'upa':
                plan.append((at, upa_strikes(drum_row, bar, t0)))
            else:
                plan.append((at, pcs_strikes(pcs_rhythm_at, bar, t0, True)))

        for i, (at, strikes) in enumerate(plan):
            until = plan[i + 1][0] if i + 1 < len(plan) else t0 + bar_ticks
            for tick in sorted(strikes):
                if at <= tick < min(until, end):
                    for d in strikes[tick]:
                        drums.append((tick, DRUM_LEN, GM[d], VEL[d]))

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
        print('  bass     : %4d notes, held to the next strike%s'
              % (len(bass), ', %d forced to the root by a chord change' % roots_forced
                 if roots_forced else ''))
        print('  chord    : %4d notes, %s, each ringing to the next beat%s'
              % (len(chord_out),
                 'a step late, as the cartridge plays it' if as_is else 'on the beat',
                 ', %d moved onto the bossa clave' % fixed if fixed else ''))
        print('  drums    : %4d hits, %d bar%s muted, %d bar%s with a fill%s'
              % (len(drums), muted_bars, '' if muted_bars == 1 else 's',
                 fills, '' if fills == 1 else 's',
                 ('  fills used: %s' % ' '.join('%d x%d' % kv
                                                for kv in sorted(fill_used.items()))
                  if fill_used else '')))
        print('  patterns : from %s' % (
            'the cartridge' if source == 'upa' else
            ('the PCS-30' if source == 'pcs30' else
             "the PCS-30, with the cartridge's own fills 1-4")))
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
    ap.add_argument('--drums', choices=('mixed', 'upa', 'pcs30'), default='mixed',
                    help="whose drum patterns: mixed (default) takes the rhythms and "
                         "the waltz fills 5 and 6 from the PCS-30 and fills 1 to 4 from "
                         "the cartridge, which is how they sound best; upa is all the "
                         "cartridge's and needs no PCS-30 ROM; pcs30 is all the keyboard's")
    ap.add_argument('--as-is', action='store_true',
                    help="what the CARTRIDGE plays: its own drums, its fixed fill feel, "
                         'its chord part a step late and its bossa-nova clave uncorrected')
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
                        fill_feel=a.fill_feel, vel=vel, drop=drop, quiet=True,
                        source=a.drums, as_is=a.as_is)
                done += 1
            except SystemExit as e:
                print('  %s: %s' % (os.path.basename(c), e))
        print('%d cards arranged into %s' % (done, a.out_dir))
        return 0

    if not a.card:
        ap.error('give a card, or --all')
    arrange(a.card, a.out, fill_feel=a.fill_feel, vel=vel, drop=drop,
            source=a.drums, as_is=a.as_is)
    return 0


if __name__ == '__main__':
    P.run(main)
