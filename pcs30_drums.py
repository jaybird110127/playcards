#!/usr/bin/env python3
"""The Yamaha PCS-30's drum patterns.

    python pcs30_drums.py                 # all ten rhythms
    python pcs30_drums.py --rhythm waltz
    python pcs30_drums.py --fills

The patterns this reads are Yamaha's, so they are not in this repository: run
`pcs30_extract.py` once against your own PCS-30 ROM and it will find them.  What
this script writes is those patterns, so keep its output to yourself.

`--card` is the exception - it EXECUTES the PCS-30's own bar-mark handler rather
than reading a table, so that mode needs the ROM itself.

The sounds themselves are not in the ROM.  The percussion voices live in the
YM2142 sound chip; the ROM only says which of them to strike on each step, and
the mask goes straight to the chip at 0xE030 (ROM 0x077C).

Table at 0x2BBC, 320 bytes, addressed (ROM 0x1274) as

    byte = 0x2BBC + plane * 0x40 + bank * 0x20 + step

Five planes, and the *bits* of each byte are the patterns: bit 7 is the first
pattern, bit 0 the eighth.  Assembling bit b of all five planes gives the
5-bit strike mask for that step (ROM 0x142F), written to the chip as one byte.

    bank 0, bits 7..0   rhythms 0..7
    bank 1, bits 7,6    rhythms 8,9
    bank 1, bits 5..0   the six drum fills

A step is a sixteenth.  Patterns are 32 steps = **two bars**, and bit 7 of the
step counter selects which bar (ROM 0x0AB9), which is how a two-bar pattern
differs in its second half.  Swing, waltz and slow-rock use only 12 of each 16
slots (ROM 0x0AA6 returns 11 or 15), so their bars are three beats or a
triplet twelve.

The five voices, read off the patterns and confirmed against the instrument:

    bit 0   kick        disco is four-on-the-floor; waltz beat 1 only
    bit 1   latin       plays the son clave in rhumba and bossa-nova
    bit 2   snare       rock backbeat on 2 and 4; waltz on beats 2 and 3
    bit 3   cymbal long   the open hi-hat - disco's off-beats
    bit 4   cymbal short  the closed hi-hat - rock's straight eighths

There is one cymbal on the chip, struck for a shorter or longer time; bits 3
and 4 are those two lengths rather than two instruments.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playcard_decode as P
import pcs30_tables as PT

STYLES = PT.STYLES
TRIPLE = (2, 6, 7)                      # swing, waltz, slow-rock: 12 of 16
VOICE = [(4, 'cymbal short'), (3, 'cymbal long'), (2, 'snare'),
         (1, 'latin'), (0, 'kick')]


def mask(tab, bank, bit, step):
    return tab.drum_mask(bank, bit, step)


def show(tab, bank, bit, label, steps):
    print('%s' % label)
    head = '  %-13s' % '' + ' '.join('%2d' % s for s in range(steps))
    print(head + '        ' + ' '.join('%2d' % s for s in range(steps)))
    for b, name in VOICE:
        one = ' '.join(' X' if mask(tab, bank, bit, s) >> b & 1 else ' .'
                       for s in range(steps))
        two = ' '.join(' X' if mask(tab, bank, bit, 16 + s) >> b & 1 else ' .'
                       for s in range(steps))
        print('  %-13s%s        %s' % (name, one, two))
    print()


def run_card(rom, path):
    """Play a real card's bar marks through the PCS-30's own code, bar by bar.

    Nothing here is modelled.  Each mark goes through the bar-mark handler at
    0x2AEC, the result is latched the way the per-bar code latches it, and the
    bit-6 test with its call to 0x129F is executed rather than reasoned about.
    0x129F ends by zeroing 0x8042, the pending drum strike - so if the sentinel
    put there comes back as zero, this machine has muted its drums for that bar.

    Note the mark values from playcard_decode are already remapped through
    ROM 0x65C8; the PCS-30 dispatches on the RAW escape nibble, so they have to
    be mapped back first.  Skipping that step is what once made these two
    machines look as though they numbered marks differently.
    """
    import playcard_resolve as R
    import z80run

    h = P.parse_card(P.tobits(P.check_card(path)))
    t1, t2, s0, s1 = R.resolve(h)
    bar_ticks = 72 if h['rhythm'] == 7 else 96

    durs = [v & 0x7F for k, v in t2 if k == 'byte']
    marks, t, i = [], 0, 0
    for kind, val in s1:
        if kind == 'byte':
            if i < len(durs):
                t += durs[i]
                i += 1
        elif kind == 'ctl' and val < 8:
            marks.append((t, val))

    inv = {m: r for r, m in enumerate(P.T65C8)}     # mark -> raw escape nibble
    nbars = int(max(t for t, _ in marks) // bar_ticks) + 3 if marks else 1
    out = []
    for bar in range(nbars):
        here = [v for tt, v in marks if bar * bar_ticks <= tt < (bar + 1) * bar_ticks]
        c = z80run.Z80(rom, base=0)
        c.sp = 0x873F
        c.poke(0x80CF, 0)
        c.poke(0x80D0, 0)
        c.poke(0x80CD, 0x01)          # the gate 0x1E3D tests before calling 0x129F
        c.poke(0x8042, 0xFF)          # a pending drum strike, to see if it survives
        for v in here:
            if v not in inv:
                continue
            c.reg['E'] = 0xF0 | inv[v]
            c.reg['A'] = c.reg['E']
            c.call(0x2AEC, stop=0x2A67)
        c.call(0x1E30, stop=0x1E48)   # latch, test bit 6, maybe call 0x129F
        out.append((bar + 1, here, c.peek(0x80D0), c.peek(0x8042)))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--rhythm', help='one style by name')
    ap.add_argument('--fills', action='store_true', help='the six fills instead')
    ap.add_argument('--card', help="run a real card's marks through the ROM, bar by bar")
    a = ap.parse_args()

    if a.card:
        # This mode does not read a table: it EXECUTES the firmware's bar-mark
        # handler, so it needs the ROM itself and there is no substitute.
        try:
            rom = open(P.rom('PCS-30.rom'), 'rb').read()
        except P.Missing as e:
            sys.exit(str(e))
        print('%-5s %-14s %-7s %s' % ('bar', 'marks on card', '0x80D0', 'drums'))
        for bar, here, sel, strike in run_card(rom, a.card):
            what = []
            if sel & 0x3F:
                what.append('FILL (table bit %d)'
                            % max(b for b in range(6) if sel >> b & 1))
            if sel & 0x40:
                what.append('MUTED' if strike == 0
                            else 'bit 6 set but the strike survived')
            if sel & 0x80:
                what.append('alternate pattern')
            print('%-5d %-14s %02X      %s'
                  % (bar, ','.join(str(v) for v in here) or '-', sel,
                     ', '.join(what) or 'playing'))
        return

    try:
        tab = PT.load()
    except PT.Missing as e:
        sys.exit(str(e))

    print('bar 1                                      bar 2\n')
    if a.fills:
        for bit in range(6):
            steps = 16 if any(mask(tab, 1, bit, s) for s in (12, 13, 14, 15)) else 12
            show(tab, 1, bit, 'fill, table bit %d  (%d-step)' % (bit, steps), steps)
        return

    rows = range(10) if not a.rhythm else [STYLES.index(a.rhythm.lower())]
    for r in rows:
        bank = 0 if r < 8 else 1
        bit = 7 - r if r < 8 else 15 - r
        show(tab, bank, bit, STYLES[r], 12 if r in TRIPLE else 16)


if __name__ == '__main__':
    P.run(main)
