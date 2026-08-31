#!/usr/bin/env python3
"""
Build the pair of cards that ask what the LIFT bit does when nothing repeats.

    python make_lift_test.py [--wav]

Bit 7 of a duration symbol is a lift flag: the finger comes off at the end of
that event.  Reading a card back, it matters in exactly one situation - an
event that repeats the previous pitch ties to it or strikes again depending on
the bit - and NOTHING else in the decode looks at it.  That makes it appear
free everywhere else, and free bits are worth bytes: each distinct symbol costs
5 bits in the header and pushes every other codeword down a rank, so letting a
free event take whichever form of its length is already in the alphabet can
save a symbol outright.

midi_compile.py did exactly that, and cards built with it play STACCATO.  The
corpus agrees that Yamaha never did it - bit 7 is set on 57.7% of the notes a
repeat follows, 2.8% of the ones it does not, and 0 of 20757 rests - but the
corpus cannot say what an INSTRUMENT does with the bit, only what Yamaha
avoided.  These two cards say it - measured on the UPA-01, which is one
machine's answer; `--wav` renders the swipe audio to put the same pair to a
real keyboard.

These two cards say it.  They carry the same 28 notes, the same lengths, the
same header, the same chart and the same three-symbol alphabet.  Not one note
repeats the pitch before it, so by the reading above the bit is free on every
single event, and the two cards should be indistinguishable:

    card 12    D4 E F G A B C5  x4, every duration 24        (bit 7 clear)
    card 13    D4 E F G A B C5  x4, every duration 24 | 0x80 (bit 7 set)

Capture reg 0x08 - key on/off - from both and compare how long each key is
held.  If the two are identical the bit really is free and the alphabet trick
is safe; if card 13's keys go down for a fraction of their event, the flag acts
on the playback path in a way that reading the card back never reveals, and a
generator has to set it only where a tie must become a re-strike.

    python ../card_to_midi.py playcard_new-12_lift-test_plain.bin --keep-log
    python ../card_to_midi.py playcard_new-13_lift-test_lifted.bin --keep-log

The melody is an ascending run inside one octave so that every note is plainly
distinct from its neighbour by ear as well as in the log, and the run repeats
four times so a difference in articulation has time to become obvious.  One
C major chart entry keeps the accompaniment and the drums going, which gives
the ear a steady bar grid to hear the melody's length against.
"""

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import playcard_decode as P
import playcard_encode as E

HERE = os.path.dirname(os.path.abspath(__file__))

QUARTER = 24                    # a quarter note, bit 7 clear
LIFTED = 24 | 0x80              # the same length with the lift flag set
WHOLE = 96                      # one obbligato slot per bar
C_MAJOR = 0x0E                  # (type 0 << 4) | C
LIFT = 0x80

# YM2151 note codes for D E F G A B C, which ascend within one block - the
# block runs C# D D# E F F# G G# A A# B C with C at the top, so this is a run
# from the bottom of the octave register to the top of it and never repeats.
RUN = [1, 4, 5, 8, 10, 13, 14]
CYCLES = 4
NOTES = len(RUN) * CYCLES       # 28 quarter notes = 7 bars of 4/4


def card(lift):
    """The card, with every melody duration plain or every one lifted.

    The obbligato is one whole-note rest a bar, which is what carries the chart
    position - entries index opcodes in THAT stream.  Its durations stay plain
    in both cards: no original ever sets the bit on a rest, and the point here
    is to vary one thing."""
    sym = LIFTED if lift else QUARTER
    mel_ops = [('note', RUN[i % len(RUN)]) for i in range(NOTES)]
    bars = NOTES // 4

    return E.Card(
        tempo=20, rhythm=4, f3=0,               # 120 bpm, rock
        mel_voice=6, sustain=0, obb_voice=1, key=0,
        alphabet=(sym, WHOLE, 0xE1),
        mel_durs=[sym] * NOTES, obb_durs=[WHOLE] * bars,
        mel_ops=E.terminated(mel_ops),
        obb_ops=E.terminated([('rest', None)] * bars),
        chart=[(C_MAJOR, 1)],
    )


# Card 14 asks how the release is measured.  A lifted quarter is held for 3.93
# of its 24 ticks less than a plain one, which is 1/6 of the event and also 4
# ticks flat - the same number.  Lengths that are not 24 tell the two apart:
#
#   length   fixed 4 ticks      1/6 of the event
#     12       8 ticks held        10 ticks held
#     24      20                   20
#     48      44                   40
#     96      92                   80
MIXED = [12, 24, 48, 96]


def mixed_card():
    """Every event lifted, at four different lengths."""
    durs, mel_ops = [], []
    for i in range(len(MIXED) * CYCLES):
        durs.append(MIXED[i % len(MIXED)] | LIFT)
        mel_ops.append(('note', RUN[i % len(RUN)]))
    total = sum(d & 0x7F for d in durs)
    obb = [WHOLE] * (total // WHOLE)
    if total % WHOLE:
        obb.append(total % WHOLE)

    return E.Card(
        tempo=20, rhythm=4, f3=0,
        mel_voice=6, sustain=0, obb_voice=1, key=0,
        alphabet=tuple(sorted(set(durs))) + (WHOLE, 48, 0xE1),
        mel_durs=durs, obb_durs=obb,
        mel_ops=E.terminated(mel_ops),
        obb_ops=E.terminated([('rest', None)] * len(obb)),
        chart=[(C_MAJOR, 1)],
    )


def build(name, lift, wav):
    path = os.path.join(HERE, name)
    data = E.build(mixed_card() if lift == 'mixed' else card(lift))
    with open(path, 'wb') as f:
        f.write(data)

    h = P.parse_card(P.tobits(open(path, 'rb').read()))
    durs = [s for s in h['track1'] if s != 0xE1 and not 0xF0 <= s <= 0xF3]
    lifted = sum(1 for s in durs if s & LIFT)
    print('%s' % name)
    print('   %d bytes, alphabet %s, CRC %s'
          % (len(data), ' '.join('%02X' % s for s in h['alphabet']),
             'ok' if h['crc_ok'] else 'BAD'))
    print('   %d melody events, %d carrying the lift bit' % (len(durs), lifted))

    if wav:
        out = os.path.splitext(path)[0] + '.wav'
        subprocess.check_call([sys.executable,
                               os.path.join(os.path.dirname(HERE), 'card_to_swipe.py'),
                               path, '-o', out])
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    ap.add_argument('--wav', action='store_true',
                    help='also render the swipe audio for a real keyboard')
    a = ap.parse_args()

    print('the lift-bit pair - same music, one bit different\n')
    build('playcard_new-12_lift-test_plain.bin', False, a.wav)
    print()
    build('playcard_new-13_lift-test_lifted.bin', True, a.wav)
    print()
    build('playcard_new-14_lift-test_lengths.bin', 'mixed', a.wav)


if __name__ == '__main__':
    main()
