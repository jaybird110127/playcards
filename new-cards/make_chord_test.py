#!/usr/bin/env python3
"""
Build a card that steps through the four chord types on one root.

    python make_chord_test.py

The chord chart packs a chord as (type << 4) | note, and the four types are
believed to be major, minor, seventh and minor seventh.  Major and seventh were
confirmed by ear on original cards; minor and minor seventh were only inferred
from progressions making harmonic sense.

Reading a capture of a C major card raised a sharper question: the accompaniment
channels receive C and D# - a MINOR third - on a card whose chord value is
verifiably 0x0E, C major.  Either the type mapping is wrong, or the third is not
where it looks like it is.

This card settles it by construction.  Same root throughout, nothing else
changing, four bars per chord type:

    bars  1-4    0x0E   type 0 on C
    bars  5-8    0x1E   type 1 on C
    bars  9-12   0x2E   type 2 on C
    bars 13-16   0x3E   type 3 on C

Whatever the accompaniment does differently between those four blocks is the
difference between the types, and nothing else can be responsible.  No bar marks
at all, so the drums stay on their plain pattern and cannot confuse the reading.
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
ROOT = 14                       # YM2151 note code for C
TYPES = [0, 1, 2, 3]            # one per four-bar block


def chord_test(rhythm_raw=4, tempo_raw=15):
    mel_ops = [('note', ROOT)] + [('rest', None)] * (BARS - 1)
    obb_ops = [('rest', None)] * BARS

    # position p fires just before the opcode at index p, and both streams
    # advance one per note, so bar b is position b
    chart = [((t << 4) | ROOT, 1 + 4 * i) for i, t in enumerate(TYPES)]

    return E.Card(
        tempo=tempo_raw, rhythm=rhythm_raw, f3=0,
        mel_voice=6, sustain=0, obb_voice=1, key=0,
        alphabet=(WHOLE, 0xE1),
        mel_durs=[WHOLE] * BARS, obb_durs=[WHOLE] * BARS,
        mel_ops=E.terminated(mel_ops), obb_ops=E.terminated(obb_ops),
        chart=chart,
    )


def main():
    path = os.path.join(HERE, 'playcard_new-04_chord-test_rock.bin')
    data = E.build(chord_test())
    with open(path, 'wb') as f:
        f.write(data)

    h = P.parse_card(P.tobits(open(path, 'rb').read()))
    print('%s  %d bytes  CRC %s'
          % (os.path.basename(path), len(data), 'VALID' if h['crc_ok'] else 'FAILED'))
    print('   %d bpm, %s, key %+d'
          % (h['tempo'], P.RHYTHM[h['rhythm']], P.key_shift(h['transpose'])))
    table = h['sections'][0][0]
    print('   chord chart: %s'
          % ' '.join('%s@%d (0x%02X)' % (P.chord(v), p, v) for v, p in table))
    t1, t2, s0, s1 = R.resolve(h)
    d1 = sum(1 for k, v in t1 if k == 'byte')
    p0 = sum(1 for k, v in s0 if k == 'byte')
    print('   %d bars, melody pairs %d/%d' % (BARS, d1, p0))
    print()
    print('   bars  1-4 type 0, 5-8 type 1, 9-12 type 2, 13-16 type 3, all on C')


if __name__ == '__main__':
    main()
