#!/usr/bin/env python3
"""The UPA-01 cartridge's accompaniment and drum patterns, over any chord.

    python upa_rhythm.py                      # every rhythm, over C
    python upa_rhythm.py --chord G7           # over a G seventh
    python upa_rhythm.py --rhythm march       # one style
    python upa_rhythm.py --alternate          # the other pattern of each
    python upa_rhythm.py --fills              # the six drum fills
    python upa_rhythm.py --raw                # the table bytes themselves

The card selects an accompaniment but does not carry one; the pattern lives in
the cartridge. The patterns are Yamaha's and are not in this repository: run
`upa_extract.py` once against your own cartridge ROM and this will find them.
What it prints is those patterns, so keep the output to yourself.

Every block is two bars and this never folds them: some rhythms really do differ
between the two, rhumba among them.

WHAT THE TABLES SAY, AND WHAT THIS DECIDES

The tables give a bass note as a **chord-tone number** and a bare strike for the
chord part - see "The accompaniment patterns" in `HANDOFF.md`. Turning those into
pitches needs decisions the cartridge does not make for us, because what the
cartridge itself plays is unusable as written:

* its **chord part always keys the same two notes**, a root and a flattened
  third, and gets the real chord out of the FM multipliers - so its key codes
  spell nonsense and cannot be exported;
* its **bass puts every root in one octave band** whose top note is C, so a
  chord on B sits eleven semitones under a chord on C.

So this module carries the owner's own voicing, which is what any MIDI or other
export should use:

**The chord** is sounded as root, third and fifth, with the flattened seventh
added on a seventh chord, each note placed in the octave band that **ends at C5**
- anything that would go above C5 drops an octave. C major seventh comes out
E4 G4 A#4 C5, and E major seventh D4 E4 G#4 B4.

**The bass** root is C2 for a C chord and rises to F#2, and then **G and above
drop an octave**, G1 to B1, so the bass never climbs out of its register. The
pattern's other chord tones sit above that root at the intervals the cartridge
uses: third (minor on a minor chord), fifth, sixth, flattened seventh, octave.

Both are conventions, not findings. The findings are in `HANDOFF.md`.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playcard_decode as P
import upa_extract as X

NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

# The export voicing, in MIDI numbers with middle C as C4 = 60.
CHORD_TOP = 72                     # C5: the highest note the chord part may use
BASS_ROOT = 36                     # C2 for a C chord
BASS_BREAK = 7                     # G and above drop an octave, to G1

# What the cartridge's own eight chord tones are, measured off the engine's
# table at RAM 0xD207 on C, G and E in all four chord types: intervals above the
# root, with the third following the chord's quality.
TONE = [None, 0, None, 7, 9, 10, 12, None]
QUALITY = ['major', 'minor', 'seventh', 'minor 7th']
THIRD = [4, 3, 4, 3]               # a quality apiece
HAS_SEVENTH = [False, False, True, True]


def name(midi):
    return '%s%d' % (NAMES[midi % 12], midi // 12 - 1)


def chord_notes(root, quality):
    """The chord part's notes for a chord, as MIDI numbers.

    Root, third and fifth, plus the flattened seventh on a seventh chord, each
    put in the one octave band that ends at C5.
    """
    steps = [0, THIRD[quality], 7] + ([10] if HAS_SEVENTH[quality] else [])
    top = CHORD_TOP - 11                                   # C#4, the band's foot
    return sorted(top + (root + s - top) % 12 for s in steps)


def bass_root(root):
    """Where the bass puts a chord's root: C2 up to F#2, then G1 up to B1."""
    return BASS_ROOT + root - (12 if root >= BASS_BREAK else 0)


def bass_note(root, tone, quality):
    """The bass note a pattern's chord-tone number means, or None for silence."""
    if tone in (0, 7) or tone >= len(TONE):
        return None
    step = THIRD[quality] if tone == 2 else TONE[tone]
    return bass_root(root) + step


def parse_chord(text):
    """"G7" or "Am" or "Bbm7" -> (root, quality)."""
    s = text.strip()
    flat = {'Db': 1, 'Eb': 3, 'Gb': 6, 'Ab': 8, 'Bb': 10}
    root = None
    for k, v in sorted(flat.items(), key=lambda kv: -len(kv[0])):
        if s.upper().startswith(k.upper()):
            root, s = v, s[len(k):]
            break
    if root is None:
        for i, n in sorted(enumerate(NAMES), key=lambda kv: -len(kv[1])):
            if s.upper().startswith(n.upper()):
                root, s = i, s[len(n):]
                break
    if root is None:
        raise SystemExit('upa_rhythm: no chord root in "%s"' % text)
    rest = s.strip().lower()
    quality = {'': 0, 'maj': 0, 'm': 1, 'min': 1, '7': 2, 'm7': 3, 'min7': 3}.get(rest)
    if quality is None:
        raise SystemExit('upa_rhythm: the cartridge has major, minor, seventh and '
                         'minor seventh, not "%s"' % rest)
    return root, quality


def steps_of(row):
    return [int(row['steps'][k:k + 2], 16) for k in range(0, len(row['steps']), 2)]


def print_drums(row, title):
    steps = steps_of(row)
    print('  %-11s %s  %d ticks a step, %d beats a bar, %d steps'
          % (title, row['at'], row['ticks_a_step'], row['beats'], len(steps)))
    for bit, drum, where in X.DRUM_BITS:
        line = X.grid(steps, lambda v, b=bit: v >> b & 1, len(steps) // 2)
        if 'X' in line:
            print('     %-10s %s' % (drum, line))


def print_accomp(row, title, root, quality, alternate):
    steps = steps_of(row)
    shift = 4 if alternate else 0
    bar = len(steps) // 2
    print('  %-11s %s  %d ticks a step, %d beats a bar, %s pattern'
          % (title, row['at'], row['ticks_a_step'], row['beats'],
             'alternate' if alternate else 'standard'))
    bass, chord, played = '', '', []
    for k, v in enumerate(steps):
        if k and k % bar == 0:
            bass += '|'
            chord += '|'
        tone, was = v >> shift & 7, steps[k - 1] >> shift & 7
        if tone and tone != was:
            n = bass_note(root, tone, quality)
            bass += str(tone)
            played.append(name(n) if n else '-')
        else:
            bass += '-' if tone else '.'
        chord += 'X' if v >> shift & 8 and not steps[k - 1] >> shift & 8 \
            else ('-' if v >> shift & 8 else '.')
    print('     bass       %s' % bass)
    print('     chord      %s' % chord)
    print('     bass plays %s' % ' '.join(played))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--chord', default='C', help='the chord to voice it over')
    ap.add_argument('--rhythm', help='one style by name')
    ap.add_argument('--alternate', action='store_true',
                    help="the rhythm's other accompaniment pattern")
    ap.add_argument('--fills', action='store_true', help='the six drum fills')
    ap.add_argument('--raw', action='store_true', help='the table bytes')
    ap.add_argument('--tables', default=X.TABLES, help='where the tables are')
    a = ap.parse_args()

    try:
        doc = X.load(a.tables)
    except X.Missing as e:
        print(e)
        return 1
    root, quality = parse_chord(a.chord)

    which = range(X.NRHYTHM)
    if a.rhythm:
        if a.rhythm not in X.RHYTHM:
            print('upa_rhythm: no rhythm called "%s"; it has %s'
                  % (a.rhythm, ', '.join(X.RHYTHM)))
            return 1
        which = [X.RHYTHM.index(a.rhythm)]

    print('%s %s: chord %s, bass root %s\n'
          % (NAMES[root], QUALITY[quality],
             ' '.join(name(n) for n in chord_notes(root, quality)),
             name(bass_root(root))))

    if a.raw:
        for what in ('drums', 'fills', 'accompaniment'):
            print('%s' % what)
            for i, row in enumerate(doc[what]):
                print('  %s %02X %02X  %s' % (row['at'], 0x80 if row['beats'] == 4 else 0,
                                              row['ticks_a_step'], row['steps']))
        return 0

    if a.fills:
        print('DRUM FILLS\n')
        for i, row in enumerate(doc['fills']):
            print_drums(row, 'fill %d' % (i + 1))
        return 0

    print('DRUMS - a strike where a bit rises; both bars, a bar line between\n')
    for r in which:
        print_drums(doc['drums'][r], X.RHYTHM[r])
    print('\nACCOMPANIMENT - the bass by chord tone, then as notes\n')
    for r in which:
        print_accomp(doc['accompaniment'][r], X.RHYTHM[r], root, quality, a.alternate)
    return 0


if __name__ == '__main__':
    P.run(main)
