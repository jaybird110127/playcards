#!/usr/bin/env python3
"""
Build the cards that ask what a chord chart entry on an UNPLAYABLE ROOT does.

    python make_mute_test.py [--wav]

47 chart entries across 22 original cards carry a low nibble of 3 - one of the
YM2151's four unused note codes, and the very code the pitch stream emits for a
rest, so the chord they name cannot sound.  The type nibble is valid on every
one, so they are deliberate rather than damage.  Three values occur: 0x23 on 33
of them, 0x13 on 8, 0x33 on 6.

Two cards, because the first answered less than it looked like it did.

CARD 10 - is 0x33 a mute?

    bar   1   2    3   4    5   6    7   8    9  10 11 12
         C   FF   C   33   C   FF   C   33   C   .  .  .

The unknown sits in the same bar position as the known answer, on the same
root, with one byte between them.  On the real firmware the chord channels and
the bass both went to zero key-ons in all four marked bars and came back on the
next chord, with the drums untouched: 0x33 stops the accompaniment exactly as
0xFF does.

CARD 11 - all three values, and does the mute HOLD?

Card 10 left two things open.  It only tested 0x33, and it only ever gave a
mute one bar before the next chord restarted the accompaniment - so it could
not tell a mute that holds from one that lapses on its own after a bar.  This
card gives each value four bars of silence to lapse in, and puts all three
unplayable values against 0xFF as the control:

    bar    1   2  3  4  5    6   7  8  9 10   11  12 13 14 15   16  17 18 19 20   21  22 23 24
          C   FF  .  .  .   C   13  .  .  .   C   23  .  .  .   C   33  .  .  .   C   .  .  .
              \___ 4 bars __/       \___ 4 bars __/       \___ 4 bars __/       \___ 4 bars __/

Each block is one bar of C major, then the mute value, then three bars carrying
no chart entry at all.  If the accompaniment is still silent at the end of
those four bars the mute holds; if it comes back by itself, it does not.  0xFF
gets the identical treatment, so "does it hold" is answered for the known mute
in the same capture.

WHY THESE WANT REAL HARDWARE

The UPA-01 has a bug that drops the accompaniment's chord notes mid-card and
never brings them back - it happens to ORIGINAL cards too, and not on real
Playcard keyboards, because those are not running this firmware.  (It was long
recorded as an openMSX artifact.  It is not: an emulator written from scratch,
../csrc/playcard, reproduces it exactly.  A single bar mark 7 fires it and no
other mark does - see dropout_trigger.py.)

A chord that stops looks exactly like a mute, which is the thing being measured,
so a capture has to be read carefully.  What rules the bug out here is that the
accompaniment RECOVERS, several times, and that the BASS stops too - the bug
leaves the bass playing.  Even so, the ear on a real instrument is the better
oracle, and `--wav` writes the swipe audio for feeding a keyboard through a
coil.

Both cards run the drums throughout - there are no bar marks at all - so the
bar grid stays audible while the accompaniment is silent, and the melody
strikes one C5 on every downbeat as a count.  Neither touches the
accompaniment.
"""

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import playcard_decode as P
import playcard_encode as E
import playcard_resolve as R

HERE = os.path.dirname(os.path.abspath(__file__))

QUARTER = 24 | 0x80             # a struck quarter note: the finger comes off
DOTHALF = 72 | 0x80             # the rest of the bar
WHOLE = 96                      # one obbligato slot per bar
ROOT = 14                       # YM2151 note code for C
C_MAJOR = 0x0E                  # (type 0 << 4) | C
MUTE = 0xFF                     # the known accompaniment mute

# The three values the corpus actually uses, all on note code 3.
UNPLAYABLE = (0x13, 0x23, 0x33)

NAMES = {C_MAJOR: 'C major', MUTE: 'the known mute 0xFF',
         0x13: 'UNPLAYABLE 0x13', 0x23: 'UNPLAYABLE 0x23', 0x33: 'UNPLAYABLE 0x33'}


def card(bars, chart):
    """A card of `bars` bars with `chart` as {bar: value}.

    The melody strikes C5 on beat 1 of each bar and rests for the other three,
    purely so the bars can be counted while the accompaniment is out.  The
    octave register starts at 4, which is where C5 already is, so no modifier
    is needed anywhere.

    One obbligato slot per bar and nothing sounding in it, so a chart position
    is simply the bar number - positions index opcodes in THAT stream, and a
    chart entry fires at the obbligato's index, never the melody's."""
    mel_ops, mel_durs = [], []
    for _ in range(bars):
        mel_ops += [('note', ROOT), ('rest', None)]
        mel_durs += [QUARTER, DOTHALF]

    return E.Card(
        tempo=15, rhythm=4, f3=0,               # 100 bpm, rock
        mel_voice=6, sustain=0, obb_voice=1, key=0,
        alphabet=(WHOLE, QUARTER, DOTHALF, 0xE1),
        mel_durs=mel_durs, obb_durs=[WHOLE] * bars,
        mel_ops=E.terminated(mel_ops),
        obb_ops=E.terminated([('rest', None)] * bars),
        chart=[(chart[b], b) for b in sorted(chart)],
    )


def card10():
    """0x33 against 0xFF, one bar each, twice over."""
    return 12, {1: C_MAJOR, 2: MUTE, 3: C_MAJOR, 4: 0x33, 5: C_MAJOR,
                6: MUTE, 7: C_MAJOR, 8: 0x33, 9: C_MAJOR}


def card11():
    """All three unplayable values and 0xFF, each given four bars to lapse in."""
    chart = {}
    bar = 1
    for value in (MUTE,) + UNPLAYABLE:
        chart[bar] = C_MAJOR                    # the accompaniment is playing
        chart[bar + 1] = value                  # now stop it
        bar += 5                                # three bars carry no entry
    chart[bar] = C_MAJOR                        # and it comes back at the end
    return bar + 3, chart


def build(name, bars, chart, wav):
    path = os.path.join(HERE, name)
    data = E.build(card(bars, chart))
    with open(path, 'wb') as f:
        f.write(data)

    h = P.parse_card(P.tobits(open(path, 'rb').read()))
    print('%s' % name)
    print('   %d bytes  CRC %s  %d bpm %s  %d bars of 4/4'
          % (len(data), 'VALID' if h['crc_ok'] else 'FAILED', h['tempo'],
             P.RHYTHM[h['rhythm']], bars))

    t1, t2, s0, s1 = R.resolve(h)
    d1 = sum(1 for k, v in t1 if k == 'byte')
    p0 = sum(1 for k, v in s0 if k == 'byte')
    d2 = sum(1 for k, v in t2 if k == 'byte')
    p1 = sum(1 for k, v in s1 if k == 'byte')
    if not h['crc_ok'] or d1 != p0 or d2 != p1:
        sys.exit('   card does not verify')

    line = []
    for b in range(1, bars + 1):
        line.append('%-4s' % {C_MAJOR: 'C', MUTE: 'FF'}.get(
            chart.get(b), ('%02X' % chart[b]) if b in chart else '.'))
    print('   bar   %s' % ' '.join('%-4d' % b for b in range(1, bars + 1)))
    print('         %s' % ' '.join(line))

    if wav:
        out = os.path.splitext(path)[0] + '.wav'
        subprocess.check_call(
            [sys.executable, os.path.join(os.path.dirname(HERE), 'card_to_swipe.py'),
             path, '-o', out], stdout=subprocess.DEVNULL)
        print('   swipe audio -> %s' % os.path.basename(out))
    print()


def main():
    ap = argparse.ArgumentParser(
        description='Build the accompaniment-mute test cards.')
    ap.add_argument('--wav', action='store_true',
                    help='also render the swipe audio, for a real keyboard')
    a = ap.parse_args()

    bars, chart = card10()
    build('playcard_new-10_unplayable-root-test.bin', bars, chart, a.wav)
    bars, chart = card11()
    build('playcard_new-11_mute-hold-test.bin', bars, chart, a.wav)

    print('   card 11: in each block the accompaniment plays for one bar, is')
    print('   stopped, and then has three more bars with no chart entry to come')
    print('   back in.  Silent for all four -> the mute holds.  Sounding again')
    print('   before the next C -> it lapses, and 0xFF is the control that says')
    print('   which of those the known mute does.')


if __name__ == '__main__':
    main()
