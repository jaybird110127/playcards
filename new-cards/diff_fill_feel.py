#!/usr/bin/env python3
"""
Do fills 1-4 have a feel of their own, or take it from the rhythm?

    python diff_fill_feel.py

WHAT THIS SETTLES, AND WHAT IT DOES NOT

**Settled, from the PCS-30's ROM.** Its drum patterns are bit-planes at 0x2BBC
and a fill is bank 1 with the fill NUMBER as the bit index - there is no rhythm
in that lookup at all.  What makes a rhythm swing is the GRID: a bar is 16 steps
under a straight rhythm and 12 under a swing one.  So the same table data lands
on sixteenths under rock and on triplets under swing, and it does so for all
four fills equally.  Printed below, that is unarguable: every fill's onsets move
from multiples of 0.25 to multiples of 1/3 with nothing changed but the rhythm.

**There is no such thing as a swing fill.**  There is a fill played with a swing
feel, and which fill it is has nothing to do with it.

**Not settled: what the UPA-01 does with them.**  The two cards below differ in
one field, and the cartridge plainly treats them differently - the steady bars
carry different patterns and different numbers of onsets.  But pinning a fill's
onsets onto a bar grid needs a bar grid, and for a long time this script could
not get one: the card asks for 100 bpm and the capture folded best at about 95,
with the phase wandering between captures.  That was the EMULATOR - it lost a
timer tick every quarter second until 2026-09-21 - and the capture now folds at
99.9 and 100.0 bpm.  The numbers it prints for the UPA-01 side are still RAW,
and no verdict has yet been drawn from them.

Getting that right needs a firmer anchor than a single melody note - the
accompaniment's own downbeat would do it - and until it exists the fill question
rests on the PCS-30 side, which needs no timing at all because it is read rather
than played.

THE CARDS

    playcard_new-15_fill-feel_rock.bin    rhythm 5, straight
    playcard_new-16_fill-feel_swing.bin   rhythm 3, swing

Sixteen bars of 4/4 at 100 bpm, C major throughout, one mark on beat 1 of every
odd bar from 3 to 13, built by make_swing_fill_test.py.
"""

import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import playcard_decode as P
import pcs30_tables as PT                   # the patterns themselves are not shipped

PLAYCARD = os.path.join(ROOT, 'csrc', 'playcard.exe')
if not os.path.isfile(PLAYCARD):
    PLAYCARD = os.path.join(ROOT, 'csrc', 'playcard')

CARDS = [('rock  (straight)', 'playcard_new-15_fill-feel_rock.bin', 5),
         ('swing            ', 'playcard_new-16_fill-feel_swing.bin', 3)]
MARK_BARS = {3: 1, 5: 2, 7: 3, 9: 4, 11: 5, 13: 6}
BPM = 100.0
BEATS = 4
BAR = BEATS * 60.0 / BPM                    # 2.4 s

DRUM_CH = (6, 7)                            # the two percussion channels


def capture(card):
    """Run the card and return (drum onsets, the first melody note).

    The melody note is the anchor: these cards sound exactly one C5, on beat 1
    of bar 1, and nothing else on the melody channels.  Timing the bar grid from
    the first DRUM hit instead would be off by however far into the pattern the
    drums happen to start."""
    log = os.path.join(HERE, os.path.splitext(card)[0] + '.fmlog')
    subprocess.check_call([PLAYCARD, os.path.join(HERE, card),
                           '-o', log, '--seconds', '60', '--quiet',
                           '--roms', P.ROM_DIR, '--as-is'])
    drums, melody = [], None
    for line in open(log):
        p = line.split()
        if len(p) != 3:
            continue
        t, r, v = float(p[0]), int(p[1], 16), int(p[2], 16)
        if r == 0x08 and (v >> 3) & 0x0F:
            ch = v & 7
            if ch in DRUM_CH:
                drums.append(t)
            elif ch in (0, 1) and melody is None:
                melody = t
    os.remove(log)
    return drums, melody


def period(onsets, lo=2.0, hi=3.0, bins=96):
    """The bar length, measured rather than assumed.

    An accompaniment pattern is two bars long, so folding every onset modulo two
    candidate bars and asking how PEAKY the result is finds the true length: at
    the right one every hit stacks on a few bins, at a wrong one they smear.
    Scoring peakiness rather than a single Fourier component matters here,
    because a drum track is full of harmonics and a plain periodogram happily
    locks onto the eighth-note pulse instead of the bar."""
    best, best_score = None, -1.0
    t = lo
    while t <= hi:
        hist = [0] * bins
        for x in onsets:
            hist[int((x % (2 * t)) / (2 * t) * bins) % bins] += 1
        score = sum(h * h for h in hist)
        if score > best_score:
            best, best_score = t, score
        t += 0.001
    return best


def bars(drums, anchor, barlen):
    out = {}
    for t in drums:
        if t < anchor - 0.05:
            continue
        b = int((t - anchor) / barlen) + 1
        beat = ((t - anchor) - (b - 1) * barlen) / (barlen / BEATS)
        out.setdefault(b, []).append(beat)
    return out


def grid_of(beats, steps):
    """How well a set of onsets fits a `steps`-per-bar grid, worst case."""
    worst = 0.0
    for b in beats:
        step = b * steps / BEATS
        err = abs(step - round(step))
        worst = max(worst, err)
    return worst


def main():
    if not os.path.isfile(PLAYCARD):
        sys.exit('build ../csrc first (make)')

    try:
        tab = PT.load()
    except PT.Missing as e:
        sys.exit(str(e))
    print('PCS-30, read from its tables (bank 1, the fill number as bit index):')
    print('a bar is 16 steps under a straight rhythm and 12 under a swing one\n')
    for label, steps in (('rock  (straight)', 16), ('swing', 12)):
        print('  %s -> %d steps a bar' % (label, steps))
        for fill in (1, 2, 3, 4):
            on = [s * BEATS / float(steps) for s in range(steps)
                  if tab.drum_mask(1, fill, s)]
            print('     fill %d: %s' % (fill, ' '.join('%.2f' % x for x in on)))
        print()

    print('UPA-01, measured from the drum channels:\n')
    for label, card, rhythm in CARDS:
        drums, anchor = capture(card)
        if anchor is None:
            print('  %s: no melody note, cannot anchor' % label)
            continue
        barlen = period([t - anchor for t in drums if t >= anchor])
        by = bars(drums, anchor, barlen)
        P.say('%s  (%d drum onsets; bar folds best at %.3f s = %.1f bpm,'
              ' against the %.0f bpm the card asks for - see the header)'
              % (label, len(drums), barlen, BEATS * 60.0 / barlen, BPM),
              hang='     ')
        for bar, fill in sorted(MARK_BARS.items()):
            if fill > 4:
                continue
            beats = sorted(by.get(bar, []))
            print('     fill %d, bar %2d: %s'
                  % (fill, bar, ' '.join('%.2f' % b for b in beats)[:56]))
        print()


if __name__ == '__main__':
    main()
