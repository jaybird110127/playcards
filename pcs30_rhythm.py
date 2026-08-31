#!/usr/bin/env python3
"""The Yamaha PCS-30's accompaniment pattern tables.

    python pcs30_rhythm.py                    # every rhythm, over C
    python pcs30_rhythm.py --chord G7         # over a G seventh
    python pcs30_rhythm.py --rhythm waltz     # one style
    python pcs30_rhythm.py --raw              # the table bytes themselves

The card selects an accompaniment but does not carry one; the pattern lives in
the instrument.  This is that pattern data, for the PCS-30 - a different
machine from the UPA-01 cartridge, so it is *a* set of Yamaha accompaniment
tables rather than the cartridge's own.

The tables are Yamaha's and are not in this repository.  Run `pcs30_extract.py`
once against your own PCS-30 ROM and this will find them; what it prints is
those patterns, so keep the output to yourself.

Eight tables of 320 bytes sit at ROM 0x2D26, ending exactly where the demo
tunes begin.  Each is ten rows of thirty-two, addressed as

    byte = base + rhythm * 32 + step          (ROM 0x14CD)

The ten rows are the Playcard's own rhythm numbering - rhumba, samba, swing,
bossa-nova, rock, 16-beat, waltz, slow-rock, march, disco.  Three of them fill
only 12 of each 16 steps: swing, waltz and slow-rock, which are exactly the
styles that take the swing and waltz drum fills.

The eight divide two ways.  Odd tables hold the bass and even ones the chord
(their value ranges do not overlap: bass spans the root to +16 semitones, chord
+4 to +29).  Within each, one table is used for plain triads and another when
the chord is a seventh - the selector at ROM 0x1620 tests bit 5 of 0x8043.

    0x8043  bits 0-3  chord root, 0-11
            bit 4     minor      - flattens the third
            bit 5     seventh    - switches to the seventh tables

which is the Playcard chord chart's own type encoding, one byte instead of two
nibbles.

A byte is a **1-based semitone offset from the chord root**: 1 is the root, 5
the major third, 8 the fifth, 13 the octave.  0xFF is a rest and 0x00 a dead
slot.  The reader at 0x16CF adds the root, and at 0x16E3 flattens a degree of
exactly 5 when the minor bit is set - a major third becoming a minor one, which
is what fixes the 1-based reading.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playcard_decode as P
import pcs30_tables as PT

STYLES = PT.STYLES
TABLES = PT.PITCH_TABLES        # (index, voice, plain/seventh, variant)

NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def parse_chord(s):
    """'G7' or 'Am' or 'C' -> (root 0-11, minor, seventh)."""
    s = s.strip()
    root = None
    for n in range(2, 0, -1):
        if s[:n].capitalize().replace('B', 'b') in [x.lower() for x in NAMES] \
           or s[:n] in NAMES:
            pass
    # simple parse: letter, optional #, then m / 7 / m7
    i = 1
    if len(s) > 1 and s[1] == '#':
        i = 2
    head = s[:i].upper().replace('#', '#')
    if head not in NAMES:
        raise SystemExit('cannot read chord %r (try C, Am, G7, Dm7)' % s)
    root = NAMES.index(head)
    tail = s[i:].lower()
    minor = tail.startswith('m')
    seventh = tail.endswith('7')
    return root, minor, seventh


def note(v, root, minor):
    """A pattern byte as a sounding note, or None."""
    if v in (0x00, 0xFF):
        return None
    deg = v - 1                              # 1-based
    red = deg
    while red > 12:
        red -= 12
    if minor and red == 4:                   # degree 5 stored, 4 after reduction
        deg -= 1
    return (root + deg) % 12


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--chord', default='C', help='chord to voice the pattern over')
    ap.add_argument('--rhythm', help='one style by name, else all ten')
    ap.add_argument('--variant', default='A', choices=['A', 'B'])
    ap.add_argument('--raw', action='store_true', help='print the table bytes')
    a = ap.parse_args()

    try:
        tab = PT.load()
    except PT.Missing as e:
        sys.exit(str(e))

    root, minor, seventh = parse_chord(a.chord)
    rows = range(10) if not a.rhythm else [STYLES.index(a.rhythm.lower())]

    print('%s  ->  root %s, %s%s' % (a.chord, NAMES[root],
                                     'minor' if minor else 'major',
                                     ' seventh' if seventh else ''))
    print('pattern variant %s, %s tables\n'
          % (a.variant, 'seventh' if seventh else 'plain'))

    for r in rows:
        print('%s' % STYLES[r])
        for idx, voice, kind, var in TABLES:
            if var != a.variant:
                continue
            if (kind == 'seventh') != seventh:
                continue
            row = [tab.pitch_byte(idx, r, st) for st in range(32)]
            if a.raw:
                print('  %-5s t%d  %s' % (voice, idx, ' '.join('%02X' % x for x in row)))
            cells = []
            for v in row:
                n = note(v, root, minor)
                cells.append('.' if v == 0xFF else ('-' if v == 0x00 else NAMES[n]))
            print('  %-5s %s | %s' % (voice,
                                      ' '.join('%-2s' % c for c in cells[:16]),
                                      ' '.join('%-2s' % c for c in cells[16:])))
        print()


if __name__ == '__main__':
    P.run(main)
