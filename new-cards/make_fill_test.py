#!/usr/bin/env python3
"""
Build the bar-mark test cards.

    python make_fill_test.py

Marks 0, 1, 2, 3 and 7 are identified.  Values 4, 5 and 6 are not, and by
elimination they are most likely further drum fills - but that was never
checked against a card, because no card in the corpus isolates them.  So this
writes cards that do nothing else.

THE DESIGN

One chord, C major, held for the whole card, so the accompaniment is a fixed
reference that any change must be measured against.  Sixteen bars of 4/4 at
100 bpm - 38.4 seconds, slow enough to hear a fill land.

    bar  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16
    mark       1     2     3     4     5     6

Each mark sits on beat 1 of its bar with a plain bar either side, so a fill has
a clean bar to play into and the pattern is re-established before the next one.
Marks 1, 2 and 3 are known fills and are the CONTROL: whatever 4, 5 and 6 turn
out to be, they are being compared against three fills of the same rhythm on
the same card in the same capture, not against a memory of another card.

The melody sounds one C5 at bar 1 and then rests; the obbligato rests
throughout and carries the marks, which is where the firmware expects them -
all 2030 marks in the real corpus are in the obbligato stream.  So after the
first note the only things sounding are the accompaniment and the drums.

Two rhythms are written, because a fill belongs to a style and there is no
reason to assume 4, 5 and 6 mean the same thing in each.  Rock is the primary;
march is the cross-check.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import playcard_decode as P
import playcard_encode as E

HERE = os.path.dirname(os.path.abspath(__file__))

WHOLE = 96                      # one 4/4 bar, in the card's own ticks
DOTTED_HALF = 72                # one 3/4 bar
BARS = 16
MARK_BARS = {3: 1, 5: 2, 7: 3, 9: 4, 11: 5, 13: 6}     # bar -> mark value

C_MAJOR = 0x0E                  # (type 0 = major) << 4 | YM2151 note code 14 = C


def fill_test(rhythm_raw, tempo_raw=15, barlen=WHOLE):
    """One card: C major throughout, one mark per odd bar from 3 to 13.

    barlen is one bar in the card's ticks - 96 for 4/4, 72 for the waltz, so
    that every card is sixteen real bars whatever its metre."""
    mel_ops = [('note', 14)] + [('rest', None)] * (BARS - 1)      # C, then silence

    obb_ops = []
    for bar in range(1, BARS + 1):
        if bar in MARK_BARS:
            obb_ops.append(('mark', MARK_BARS[bar]))
        obb_ops.append(('rest', None))

    return E.Card(
        tempo=tempo_raw,            # index 15 -> 100 bpm
        rhythm=rhythm_raw,          # raw value; style is raw + 1
        f3=0,                       # standard accompaniment pattern, not the alternate
        mel_voice=6,                # -> field 1 -> PICCOLO
        sustain=0,
        obb_voice=1,                # -> field 2 -> FLUTE
        key=0,                      # no transposition, so C major sounds as C major
        alphabet=(barlen, 0xE1),
        mel_durs=[barlen] * BARS,
        obb_durs=[barlen] * BARS,
        mel_ops=E.terminated(mel_ops),
        obb_ops=E.terminated(obb_ops),
        chart=[(C_MAJOR, 1)],       # set at the first opcode and never changed
    )


def describe(path):
    """Read the finished card back and print what the firmware will see."""
    h = P.parse_card(P.tobits(open(path, 'rb').read()))
    import playcard_resolve as R
    t1, t2, s0, s1 = R.resolve(h)

    print('  %-34s %d bytes  CRC %s' % (os.path.basename(path),
                                        os.path.getsize(path),
                                        'VALID' if h['crc_ok'] else 'FAILED'))
    print('     %d bpm, %s, %s pattern, key %+d' %
          (h['tempo'], P.RHYTHM[h['rhythm']],
           'ALTERNATE' if h['f3'] else 'standard', P.key_shift(h['transpose'])))
    print('     melody %s, obbligato %s' %
          (P.voice(P.MELODY_VOICE, h['field4']), P.voice(P.OBBLIGATO_VOICE, h['field6'])))

    table = h['sections'][0][0]
    print('     chord chart: %s' % ' '.join('%s@%d' % (P.chord(v), p) for v, p in table))

    # walk the obbligato in playback order and place every mark on the bar grid
    durs = [v & 0x7F for k, v in t2 if k == 'byte']
    barlen = durs[0]
    t = i = 0
    marks = []
    for kind, val in s1:
        if kind == 'byte':
            if i < len(durs):
                t += durs[i]
                i += 1
        elif kind == 'ctl' and val < 8:
            marks.append((t / barlen + 1, val))
    print('     marks: %s' % ' '.join('bar %g=mark %d' % (b, m) for b, m in marks))
    total = sum(durs)
    print('     %d bars of %d/4, %.1f s at %d bpm'
          % (total / barlen, barlen // 24, total / 24.0 * 60.0 / h['tempo'], h['tempo']))


def main():
    cards = [('playcard_new-01_fill-test_rock.bin', 4, WHOLE),
             ('playcard_new-02_fill-test_march.bin', 8, WHOLE),
             ('playcard_new-03_fill-test_waltz.bin', 6, DOTTED_HALF)]
    print('Building bar-mark test cards')
    print()
    for name, rhythm_raw, barlen in cards:
        path = os.path.join(HERE, name)
        data = E.build(fill_test(rhythm_raw, barlen=barlen))   # build() verifies as it goes
        with open(path, 'wb') as f:
            f.write(data)
        describe(path)
        print()
    print('Marks 1, 2 and 3 are known fills and serve as the control.')
    print('Marks 4, 5 and 6 are what these cards exist to identify.')


if __name__ == '__main__':
    main()
