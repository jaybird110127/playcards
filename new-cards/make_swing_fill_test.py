#!/usr/bin/env python3
"""
Build the cards that ask whether fills 1-4 have a straight/swing feel of their
own, or take it from the rhythm.

    python make_swing_fill_test.py

WHAT IS IN DOUBT

This project recorded for weeks that fills 1 and 2 were straight and 3 and 4
were swing - a property of the fills.  The card owner's ear says otherwise, and
so does the PCS-30: there the feel belongs to the RHYTHM.  Its drum tables are
read on a grid that is 16 steps to the bar for a straight rhythm and 12 for a
swing one, so the SAME fill data comes out straight under rock and swung under
swing.  Nothing distinguishes fill 3 from fill 1 but the pattern itself.

If that is right, then on the UPA-01 the four fills should differ between the
two cards below in exactly the same way, and any difference BETWEEN 1-2 and 3-4
within one card is the cartridge misrendering them.

THE CARDS

The pair differs in one field, the rhythm, and in nothing else:

    playcard_new-15_fill-feel_rock.bin    rhythm 5, straight, 16 steps a bar
    playcard_new-16_fill-feel_swing.bin   rhythm 3, swing,    12 steps a bar

Sixteen bars of 4/4 at 100 bpm, C major held throughout so the accompaniment is
a fixed reference, and one mark on beat 1 of every odd bar from 3 to 13:

    bar  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16
    mark       1     2     3     4     5     6

Fills 5 and 6 are on the card as a control - they are the waltz pair, and they
are three-beat patterns, so they should look wrong in both cards and wrong in
the same way.  The melody sounds one C5 and then rests and the obbligato rests
throughout, so after the first note only the accompaniment and drums sound.

`diff_fill_feel.py` alongside plays both through ../csrc/playcard and compares
what came out with what the PCS-30's tables say should.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import playcard_decode as P
import playcard_encode as E

HERE = os.path.dirname(os.path.abspath(__file__))

WHOLE = 96                      # one 4/4 bar in the card's ticks
BARS = 16
MARK_BARS = {3: 1, 5: 2, 7: 3, 9: 4, 11: 5, 13: 6}
C_MAJOR = 0x0E

RHYTHM_ROCK = 4                 # raw; style is raw + 1, so 5 = rock
RHYTHM_SWING = 2                # 3 = swing


def card(rhythm_raw):
    mel_ops = [('note', 14)] + [('rest', None)] * (BARS - 1)
    obb_ops = []
    for bar in range(1, BARS + 1):
        if bar in MARK_BARS:
            obb_ops.append(('mark', MARK_BARS[bar]))
        obb_ops.append(('rest', None))

    return E.Card(
        tempo=15,                   # 100 bpm, slow enough to hear a fill land
        rhythm=rhythm_raw,
        f3=0,                       # standard pattern; the alternate has a bug
        mel_voice=6, sustain=0, obb_voice=1, key=0,
        alphabet=(WHOLE, 0xE1),
        mel_durs=[WHOLE] * BARS,
        obb_durs=[WHOLE] * BARS,
        mel_ops=E.terminated(mel_ops),
        obb_ops=E.terminated(obb_ops),
        chart=[(C_MAJOR, 1)],
    )


def build(name, rhythm_raw):
    path = os.path.join(HERE, name)
    data = E.build(card(rhythm_raw))
    with open(path, 'wb') as f:
        f.write(data)
    h = P.parse_card(P.tobits(data))
    print('  %-40s %3d bytes  %s  CRC %s'
          % (name, len(data), P.RHYTHM[h['rhythm']],
             'ok' if h['crc_ok'] else 'BAD'))
    return path


def main():
    print('the fill-feel pair - one field apart\n')
    build('playcard_new-15_fill-feel_rock.bin', RHYTHM_ROCK)
    build('playcard_new-16_fill-feel_swing.bin', RHYTHM_SWING)
    print('\nnow run diff_fill_feel.py')


if __name__ == '__main__':
    main()
