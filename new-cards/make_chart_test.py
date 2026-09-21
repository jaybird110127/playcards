#!/usr/bin/env python3
"""Build the card that asks where a chord-chart entry actually fires.

A chart entry carries a 10-bit POSITION, and that position is an opcode index
within "the current stream".  The cartridge walks the table on every decoded
opcode of BOTH streams (ROM 0x659E), so an entry at position P is emitted as an
inline 0xE7 record in the melody stream *and* in the obbligato stream - at two
different musical moments, because the two streams run at different opcode
rates.  Every real card places its chords by obbligato index and tolerates
whatever the melody's copy does; nobody has established what that is.

This card makes the two moments impossible to confuse:

    melody      sixteenth notes      16 opcodes per bar
    obbligato   whole notes           1 opcode per bar

    chart entry 1: C major at position 1    - bar 1 in both streams
    chart entry 2: G major at position 17   - bar 2 of the MELODY
                                            - bar 17 of the OBBLIGATO

So watching the cartridge's live chord byte at 0xD353 (written by the 0xE7
handler at ROM 0x5FC6, value OR 0x80 as a dirty flag) answers it outright:

    G arrives near melody note 17   -> the melody's copy fires
    G arrives around bar 17         -> only the obbligato's counts
    G arrives at both               -> both fire, and a card gets two changes

The melody's first note of each bar is G and the rest are C, so the bar grid can
be read straight off the key-ons in the same log - a local comparison, which
survived even the 4% timing fault the emulator had until 2026-09-21.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import playcard_decode as P
import playcard_encode as E

BARS = 20
# The LIFT bit matters here.  Without it a run of equal pitches ties into one
# held note, so the melody would sound twice a bar instead of sixteen times and
# the log would be unreadable.  Opcode positions are unaffected either way, but
# a countable note per event is the whole point of this card.
SIXTEENTH = 6 | 0x80     # ticks; 16 to a 4/4 bar, struck separately
WHOLE = 96 | 0x80        # one bar

C_MAJOR = (0 << 4) | 14  # type 0, YM2151 note code for C
G_MAJOR = (0 << 4) | 8   # type 0, note code for G
NOTE_C, NOTE_G, NOTE_E = 14, 8, 4

SPLIT = 17               # the position that lands in different bars per stream


def chart_test():
    # melody: sixteen sixteenths a bar, the first of each bar a G so the bar
    # lines can be counted off the key-ons
    mel_ops, mel_durs = [], []
    for bar in range(BARS):
        for step in range(16):
            # alternate the pitch every step so each strike is visible, with the
            # bar's first note a G to mark the bar line
            mel_ops.append(('note', NOTE_G if step == 0
                            else (NOTE_C if step % 2 else NOTE_E)))
            mel_durs.append(SIXTEENTH)

    # obbligato: one whole note a bar, so its opcode index crawls
    obb_ops = [('note', NOTE_E) for _ in range(BARS)]
    obb_durs = [WHOLE] * BARS

    return E.Card(
        tempo=28,                 # index 28 -> 176 bpm, so 20 bars is ~27 s
        rhythm=4,                 # raw 4 -> rock, a pattern with an obvious bass
        f3=0,
        mel_voice=6,              # -> field 1 -> PICCOLO, easy to pick out
        sustain=0,
        obb_voice=1,              # -> field 2 -> FLUTE
        key=0,                    # no transposition
        alphabet=(SIXTEENTH, WHOLE, 0xE1),
        mel_durs=mel_durs,
        obb_durs=obb_durs,
        mel_ops=E.terminated(mel_ops),
        obb_ops=E.terminated(obb_ops),
        chart=[(C_MAJOR, 1), (G_MAJOR, SPLIT)])


def describe(path):
    h = P.parse_card(P.tobits(open(path, 'rb').read()))
    import playcard_resolve as R
    t1, t2, s0, s1 = R.resolve(h)
    print('  %-34s %d bytes  CRC %s' % (os.path.basename(path),
                                        os.path.getsize(path),
                                        'VALID' if h['crc_ok'] else 'FAILED'))
    print('     %d bpm, %s, %d bars' % (h['tempo'], P.RHYTHM[h['rhythm']], BARS))
    print('     chord chart: %s'
          % ' '.join('%s@%d' % (P.chord(v), p) for v, p in h['sections'][0][0]))
    d1 = sum(1 for k, v in t1 if k == 'byte')
    d2 = sum(1 for k, v in t2 if k == 'byte')
    print('     melody %d events, obbligato %d events' % (d1, d2))
    print('     position %d is melody note %d (bar %.2f) and obbligato note %d (bar %d)'
          % (SPLIT, SPLIT, (SPLIT - 1) / 16.0 + 1, SPLIT, SPLIT))


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, 'playcard_new-09_chart-position-test.bin')
    with open(path, 'wb') as f:
        f.write(E.build(chart_test()))
    print('Building the chord-chart position test')
    describe(path)


if __name__ == '__main__':
    main()
