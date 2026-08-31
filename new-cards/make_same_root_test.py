#!/usr/bin/env python3
"""
Build a card that states the same chords two ways, to see whether a same-root
chart entry does anything a fully spelled chord does not.

    python make_same_root_test.py

THE QUESTION

Some original cards carry chart entries on note code 3, which no chip can play.
They mean "keep the root already sounding and OR this quality onto it", and the
PCS-30 implements exactly that.  Two thirds of them change no harmony at all -
they restate the chord that is already sounding - which raises the obvious
question: do they do something *else*?  Reset the bass, restart the pattern,
re-strike the chord?  A machine that only tracks harmony would never show it.

THE CARD

Ten four-bar blocks on one root, A.  Each block sets a chord on its first bar
and then, two bars later or one bar later, states a chord again in one of the
two forms.  Everything else is held constant, so any difference heard between
two blocks is the difference between the forms and nothing else.

    bars   1-4    A                                   control, nothing else
    bars   5-8    A       then A7   spelled in full   odd bar, real change
    bars   9-12   A       then 0x23 same-root         odd bar, real change
    bars  13-16   A       then A    spelled in full   odd bar, restating no change
    bars  17-20   A7      then A7   spelled in full   odd bar, no change
    bars  21-24   A7      then 0x23 same-root         odd bar, no change
    bars  25-28   A       then A7   spelled in full   EVEN bar, real change
    bars  29-32   A       then 0x23 same-root         EVEN bar, real change
    bars  33-36   A7      then 0x23 same-root         EVEN bar, no change
    bars  37-40   A                                   control again

The accompaniment patterns are 32 steps - two bars - so the odd and even blocks
put the second entry at opposite phases of the pattern.  If restating a chord
resets that phase, blocks 7 to 9 will not sound like blocks 2 to 6.

WHICH MACHINE TO PLAY IT ON

A PCS-30, or a PC-1000 if one can be found.  **The UPA-01 cartridge cannot play
this card**: it has no same-root convention and falls silent on those entries,
which is measured, so blocks 3, 6, 8 and 9 will simply stop.  That is not what
this card is asking about.

WHAT THE ROM ALREADY SAYS

Run rather than guessed: on the PCS-30 the two forms leave the machine in the
same state, byte for byte.  The chord path writes the staging byte at 0x8044 and
the live chord byte at 0x8043 and touches nothing else, and the accompaniment
step counter at 0x8038 has four writers in the whole ROM, none of them in that
path.  So on that machine the answer is already no.  This card is for the
machines whose ROMs are not available.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import playcard_decode as P
import playcard_encode as E
import playcard_resolve as R

HERE = os.path.dirname(os.path.abspath(__file__))

WHOLE = 96
ROOT = 10                       # YM2151 note code for A
A = (0 << 4) | ROOT             # 0x0A, A major
A7 = (2 << 4) | ROOT            # 0x2A, A seventh
SAME7 = 0x23                    # same root, OR a seventh onto it

# (block start bar, set-up chord, [(bar, value, what it is)])
BLOCKS = [
    (1,  A,  [],                                   'A, nothing else'),
    (5,  A,  [(7,  A7,    'A7 in full')],          'odd bar, real change'),
    (9,  A,  [(11, SAME7, '0x23 same-root')],      'odd bar, real change'),
    (13, A,  [(15, A,     'A in full again')],     'odd bar, restating no change'),
    (17, A7, [(19, A7,    'A7 in full again')],    'odd bar, no change'),
    (21, A7, [(23, SAME7, '0x23 same-root')],      'odd bar, no change'),
    (25, A,  [(26, A7,    'A7 in full')],          'even bar, real change'),
    (29, A,  [(30, SAME7, '0x23 same-root')],      'even bar, real change'),
    (33, A7, [(34, SAME7, '0x23 same-root')],      'even bar, no change'),
    (37, A,  [],                                   'A again, to end on'),
]
BARS = 40


def same_root_test(rhythm_raw=4, tempo_raw=15):
    """rhythm 4 is rock: a straight two-bar pattern, nothing tricky."""
    # One melody note on the first bar of each block, so the blocks can be
    # counted by ear.  Everything else is silent.
    starts = set(b[0] for b in BLOCKS)
    mel_ops = [('note', ROOT) if bar in starts else ('rest', None)
               for bar in range(1, BARS + 1)]
    obb_ops = [('rest', None)] * BARS

    chart = []
    for start, setup, tests, _ in BLOCKS:
        chart.append((setup, start))
        for bar, val, _ in tests:
            chart.append((val, bar))

    return E.Card(
        tempo=tempo_raw, rhythm=rhythm_raw, f3=0,
        mel_voice=6, sustain=0, obb_voice=1, key=0,
        alphabet=(WHOLE, 0xE1),
        mel_durs=[WHOLE] * BARS, obb_durs=[WHOLE] * BARS,
        mel_ops=E.terminated(mel_ops), obb_ops=E.terminated(obb_ops),
        chart=chart,
    )


def main():
    path = os.path.join(HERE, 'playcard_new-17_same-root-test.bin')
    data = E.build(same_root_test())
    with open(path, 'wb') as f:
        f.write(data)

    h = P.parse_card(P.tobits(open(path, 'rb').read()))
    print('%s  %d bytes  CRC %s'
          % (os.path.basename(path), len(data), 'VALID' if h['crc_ok'] else 'FAILED'))
    print('   %d bpm, %s, %d bars, %d chart entries of the 62 allowed'
          % (h['tempo'], P.RHYTHM[h['rhythm']], BARS, len(h['sections'][0][0])))
    print()
    print('   %-6s %-28s %s' % ('bars', 'what happens', 'why'))
    for start, setup, tests, why in BLOCKS:
        what = 'chord 0x%02X' % setup
        for bar, val, label in tests:
            what += ', bar %d %s' % (bar, label)
        print('   %-6s %-28s %s' % ('%d-%d' % (start, start + 3), what, why))
    print()
    print('   Play it on a PCS-30 or a PC-1000. The UPA-01 falls silent on the')
    print('   same-root entries, so blocks 3, 6, 8 and 9 stop dead there.')


if __name__ == '__main__':
    main()
