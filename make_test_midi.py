#!/usr/bin/env python3
"""Generate a four-channel MIDI to test the compiler on material it has never
seen, and on pieces too long for one side of a card.

    python make_test_midi.py out.mid                    # the long form
    python make_test_midi.py out.mid --form short       # folds into one side
    python make_test_midi.py out.mid --sections 8       # shorter, still 2 sides
    python make_test_midi.py out.mid --chord-bars 2     # a long card that FITS
    python make_test_midi.py out.mid --seed 5           # different material

    python midi_compile.py out.mid -o out.bin --verbose
    python card_limits.py out_side-a.bin out_side-b.bin

WHY THIS EXISTS

Every other input `midi_compile.py` gets tested against is a Yamaha card that
`card_decompile.py` turned into MIDI, and such a file has Yamaha's structural
decisions already baked into it.  Its durations are already exactly on the tick
grid.  Its alphabet is known to fit in 25 symbols, because a real card was built
from it.  Its repeats are already in a shape the compressor can find, because
Yamaha's compressor put them there.  Its chord chart already fits 62 entries,
because it came off a card that stored one.  A round trip over the corpus proves
the compiler can put a card back the way it found it - and proves nothing about
what happens when the music did not come from a card in the first place.

This writes music that never was one.  Compiling it exercises quantising real
note starts onto the grid, building an alphabet with no precedent, finding
repeats nobody planted, and the two limits a corpus card never reaches: the
433-byte strip and the 62-entry chart.  Everything it found the first time it
was run is in `midi-roundtrip-design.md`.

WHAT IT WRITES

The four channels the compiler reads, in that layout:

    ch 1  melody      a singable line, phrases built from bar-length rhythms
    ch 2  obbligato   a sparser counter-line under it, monophonic by
                      construction so nothing is dropped as an overlap
    ch 3  chords      ii-V-I-vi round the form, as triads and sevenths so all
                      four chart types appear.  One chord a bar by default,
                      which is what overflows the chart on a long card;
                      --chord-bars 2 halves it
    ch 4  control     a phrase mark (0x11) every eight bars, landed on the
                      melody note that starts the phrase rather than on the
                      bar line - which is where the originals put them

Rhythm comes from a small vocabulary of bar-length patterns rather than random
durations.  That keeps it sounding like music, keeps the duration alphabet to a
sane size, and repeats pitches often enough that the LIFT bit has something to
do.  Nothing is out of range on purpose: `tmp/silly.mid` already covers what the
compiler does with impossible input, and the point here is length, not abuse.

THE TWO FORMS

    --form short   AABA, 32 bars a chorus, three choruses.  The phrases repeat
                   exactly where the form says they do, so the compressor has
                   real structure to find and the card fits ONE side.
    --form long    every section its own material, with a reprise every third.
                   Far less to fold, so the card needs TWO.

`--sections` sets how many the long form gets, and the boundary is sharp:

    6 sections    one side, 364 bytes       chart 48 of 62
    7 sections    one side, 414 bytes       chart 56 of 62   the last one-sided
    8 sections    two sides, 163 + 306      chart 64 - OVER
    11 sections   two sides, 215 + 402      chart 89 - OVER
    12 sections   two sides, 235 + 450      chart 105 - OVER, side B over by 17

TWO LIMITS, AND THEY DO NOT BITE TOGETHER

The bytes are only half the story, and reading that table as "11 sections is
fine" is the mistake it invites.  A long card runs into the **62-entry chord
chart** at the very same point it goes two-sided, because the chords are one a
bar and a long form has little for the compressor to fold: 8 sections already
needs 64 entries, and the compiler drops everything past 62 and says so.

That is deliberate - reaching both limits is why this file exists - but it means
the default long form is a test of the CHART limit, and the card it produces is
not the music that went in.  For a long card that comes out whole, thin the
chords:

    --sections 11 --chord-bars 2    two sides, 215 + 374, chart 45 of 62

which is a genuine two-sided card the firmware accepts on both halves, and the
right input for testing the two-sided path itself rather than the chart's edge.

Side B is always the bigger half, because opcode streams do not compress the
way duration tracks do, and the split point is the format's own - so there is
nothing to rebalance and no third side.

The MIDI it writes is ours rather than Yamaha's, so unlike `random-cards/` there
is nothing to keep out of the repository.  `tmp/` is a good place to put it.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playcard_decode as P
import playcard_midi as X

Q = 24                                   # ticks in a quarter note
BAR = 4 * Q
BPM = 120

# C major, as MIDI note numbers inside the melody's G3..C6 range
SCALE = [60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77, 79]

# One bar of rhythm each.  Small on purpose: a card's duration alphabet holds 25
# symbols and every one of them costs 5 bits in the header.
PATTERNS = [[Q, Q, Q, Q],
            [Q * 2, Q, Q],
            [Q, Q, Q * 2],
            [Q // 2, Q // 2, Q, Q, Q],
            [Q * 3, Q],
            [Q, Q // 2, Q // 2, Q * 2],
            [Q * 4],
            [Q // 2, Q // 2, Q // 2, Q // 2, Q * 2]]

# ii - V - I - vi, a bar each, which puts all four chart types on the card
PROGRESSION = [(62, 'm7'), (67, '7'), (60, ''), (69, 'm')]
TONES = {'': (0, 4, 7), 'm': (0, 3, 7), '7': (0, 4, 7, 10), 'm7': (0, 3, 7, 10)}

SECTION_BARS = 8


def phrase(seed, bars=SECTION_BARS, low=0, high=11):
    """A singable line of `bars` bars, the same every time for a given seed.

    The melody walks the scale by a step drawn from -2..+2, so a step of 0
    repeats the pitch - which is what gives the LIFT bit something to decide."""
    out = []
    t = 0
    n = seed % (high - low) + low
    for b in range(bars):
        pattern = PATTERNS[(seed + b * 3) % len(PATTERNS)]
        for i, d in enumerate(pattern):
            n = max(low, min(high, n + ((seed + b * 5 + i * 7) % 5) - 2))
            out.append((t, d, SCALE[n], 100))
            t += d
    return out, t


def answer(melody, drop=12):
    """A counter-line under a melody: one note in three, an octave down, each
    held until the next one it keeps.

    Holding to the next kept note rather than to its own length is what keeps
    the part MONOPHONIC.  Two obbligato notes sounding at once are not a card:
    the compiler would drop one and report it, and the test would be measuring
    the overlap rule instead of the thing it is here for."""
    kept = [n for i, n in enumerate(melody) if i % 3 == 0]
    out = []
    for i, (t, d, p, v) in enumerate(kept):
        end = kept[i + 1][0] if i + 1 < len(kept) else t + d
        out.append((t, max(Q // 2, end - t), p - drop, 90))
    return out


def shift(notes, dt):
    return [(t + dt, d, p, v) for t, d, p, v in notes]


def plan_form(form, sections, seed):
    """The order the sections are played in, as [(notes, length)]."""
    if form == 'short':
        a, alen = phrase(11 + seed)
        b, blen = phrase(29 + seed)
        return [(a, alen)] + [(a, alen), (a, alen), (b, blen), (a, alen)] * 3
    out = []
    for i in range(sections):
        part = phrase(7 + seed + i * 13)
        out.append(part)
        if i % 3 == 2:                   # a reprise now and then, so it is not
            out.append(part)             # entirely unfoldable either
    return out


def build(path, form='long', sections=12, seed=0, chord_bars=1):
    melody, obb, chords, control = [], [], [], []

    t = 0
    for part, length in plan_form(form, sections, seed):
        melody += shift(part, t)
        obb += shift(answer(part), t)
        t += length
    end = t

    # One chord every `chord_bars` bars.  At the default of 1 a long form needs
    # more chart entries than the 62 a card holds, which is deliberate - it is
    # one of the two limits this file exists to reach - but it means the chords
    # are not what the card came out with.  Ask for 2 and a long card fits.
    bars = 0
    while bars * BAR < end:
        if bars % chord_bars == 0:
            root, kind = PROGRESSION[(bars // chord_bars) % len(PROGRESSION)]
            for interval in TONES[kind]:
                chords.append((bars * BAR, BAR * chord_bars, root - 12 + interval, 90))
        bars += 1

    # A phrase mark every eight bars, on the melody onset that starts it: 84.3%
    # of the corpus's 0x11 opcodes land on an onset and exactly one of 3109
    # falls part-way through a note, so a mark that missed would not be typical
    # of anything.
    onsets = set(start for start, d, p, v in melody)
    for b in range(0, bars, 8):
        near = min(onsets, key=lambda s: abs(s - b * BAR))
        if abs(near - b * BAR) <= Q:
            control.append((near, 1, X.CTL_NOTE[0x11], 100))

    X.write_midi(path, [('melody', X.MEL_CH, melody),
                        ('obbligato', X.OBB_CH, obb),
                        ('chords', X.CHORD_CH, chords),
                        ('control', X.CTL_CH, control)], BPM, beats=4)
    print('%s   %s form%s' % (path, form,
                              '' if form == 'short' else ', %d sections' % sections))
    P.say('%d bars at %d bpm, %d melody notes, %d obbligato, %d chord blocks, '
          '%d phrase marks'
          % (bars, BPM, len(melody), len(obb), len(chords) // len(TONES['']),
             len(control)), hang='      ')
    return path


def main():
    ap = argparse.ArgumentParser(
        description='Write a four-channel MIDI for testing midi_compile.py.')
    ap.add_argument('out', nargs='?', default='test.mid')
    ap.add_argument('--form', choices=('short', 'long'), default='long',
                    help='short folds onto one side; long needs two')
    ap.add_argument('--sections', type=int, default=12,
                    help='how many sections the long form gets (default 12)')
    ap.add_argument('--chord-bars', type=int, default=1, dest='chord_bars',
                    help='bars per chord; 1 overflows the 62-entry chart on a '
                         'long card, 2 fits')
    ap.add_argument('--seed', type=int, default=0,
                    help='different material, same shape')
    a = ap.parse_args()
    build(a.out, a.form, a.sections, a.seed, a.chord_bars)


if __name__ == '__main__':
    P.run(main)
