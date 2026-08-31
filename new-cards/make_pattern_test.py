#!/usr/bin/env python3
"""
Build a matched pair testing how mark 7 behaves on a card that already starts
on the alternate accompaniment pattern.

    python make_pattern_test.py

There are two ways to reach the alternate pattern, and until now they had only
been seen separately: the header's 3-bit field starts on it and stays, and bar
mark 7 switches to it for a single bar.  No original card does both - none of
the five header-bit cards contains a single mark 7 - so what happens when they
meet has never been heard.

The pair differs in exactly one field.  Card 05 sets the header field to 2, the
value all five original cards use; card 06 leaves it 0.  Everything else is
byte-identical: same rhythm, same chord, same marks, same bars.

    bar   1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16
    mark              7     7     7

Four bars to establish the pattern, then three mark 7s with a plain bar between
each, then a long plain tail to hear whether anything settles back.

WHAT THE ROM SAYS SHOULD HAPPEN, written down before listening:

  0xD352 holds the live pattern state.  Bit 0 is the one-bar alternate, bit 1 is
  the header's persistent one, bit 7 is a dirty flag.  Mark 7 does OR 0xC1
  (ROM 0x5F6F), so it sets bit 0.  The per-bar revert at ROM 0x6005 clears bit 0
  again - but it reads bit 1 first and RETURNS if bit 1 is set.

  The header expands its field to 3, not 2, so it sets bits 0 AND 1 (ROM 0x5CB2).

  So on card 06 mark 7 sets bit 0, the revert clears it, and the alternate
  pattern lasts exactly one bar - the known behaviour.  On card 05 bit 0 is
  already set and bit 1 locks the revert out, so mark 7 can change nothing and
  the alternate pattern runs unbroken from bar 1 to the end.

  Prediction: card 05 sounds the same in every bar, and its mark 7s are
  INAUDIBLE.  Card 06 changes for one bar at 5, 7 and 9 and is otherwise plain.

If card 05 does change at those bars, this reading is wrong.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import playcard_decode as P
import playcard_encode as E
import playcard_resolve as R

HERE = os.path.dirname(os.path.abspath(__file__))

WHOLE = 96
BARS = 16
MARK7_BARS = (5, 7, 9)
C_MAJOR = 0x0E


def pattern_test(f3):
    mel_ops = [('note', 14)] + [('rest', None)] * (BARS - 1)
    obb_ops = []
    for bar in range(1, BARS + 1):
        if bar in MARK7_BARS:
            obb_ops.append(('mark', 7))
        obb_ops.append(('rest', None))

    return E.Card(
        tempo=15, rhythm=4, f3=f3,          # f3=2 is what the five real cards carry
        mel_voice=6, sustain=0, obb_voice=1, key=0,
        alphabet=(WHOLE, 0xE1),
        mel_durs=[WHOLE] * BARS, obb_durs=[WHOLE] * BARS,
        mel_ops=E.terminated(mel_ops), obb_ops=E.terminated(obb_ops),
        chart=[(C_MAJOR, 1)],
    )


def describe(path):
    h = P.parse_card(P.tobits(open(path, 'rb').read()))
    t1, t2, s0, s1 = R.resolve(h)
    durs = [v & 0x7F for k, v in t2 if k == 'byte']
    t = i = 0
    marks = []
    for kind, val in s1:
        if kind == 'byte':
            if i < len(durs):
                t += durs[i]
                i += 1
        elif kind == 'ctl' and val < 8:
            marks.append((t / WHOLE + 1, val))
    print('  %-38s %d bytes  CRC %s'
          % (os.path.basename(path), os.path.getsize(path),
             'VALID' if h['crc_ok'] else 'FAILED'))
    print('     header pattern field = %d  -> %s pattern from bar 1'
          % (h['f3'], 'ALTERNATE' if h['f3'] else 'standard'))
    print('     %d bpm %s, chord %s, marks: %s'
          % (h['tempo'], P.RHYTHM[h['rhythm']],
             ' '.join(P.chord(v) for v, p in h['sections'][0][0]),
             ' '.join('bar %g = mark %d' % (b, m) for b, m in marks)))


def main():
    print('Building the alternate-pattern pair')
    print()
    for name, f3 in (('playcard_new-05_pattern-test_header-set.bin', 2),
                     ('playcard_new-06_pattern-test_header-clear.bin', 0)):
        path = os.path.join(HERE, name)
        with open(path, 'wb') as f:
            f.write(E.build(pattern_test(f3)))
        describe(path)
        print()

    a = open(os.path.join(HERE, 'playcard_new-05_pattern-test_header-set.bin'), 'rb').read()
    b = open(os.path.join(HERE, 'playcard_new-06_pattern-test_header-clear.bin'), 'rb').read()
    diff = [i for i in range(min(len(a), len(b))) if a[i] != b[i]]
    print('  the two images differ in %d byte(s): %s'
          % (len(diff), ', '.join('offset %d (%02X vs %02X)' % (i, a[i], b[i]) for i in diff)))
    print('  (the header field and the CRC that covers it - nothing else)')


if __name__ == '__main__':
    main()
