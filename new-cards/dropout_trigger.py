#!/usr/bin/env python3
"""What triggers the UPA-01's chord dropout?  Build the cards and find out.

    python dropout_trigger.py                 # the whole matrix
    python dropout_trigger.py --repaired      # the same, with the bug repaired
    python dropout_trigger.py --keep DIR      # keep the images and captures

The UPA-01 stops sounding the accompaniment's two chord channels partway
through a card and leaves the bass playing.  It is that cartridge's own bug,
not the format's and not the emulator's, and this measures exactly what sets it
off.  See "A firmware bug that looks like card behaviour" in
../playcard-format.md.

The cards are built here rather than committed, because there are eighteen of
them and they exist only to be counted.  Each is sixteen bars of 4/4 at 100 bpm
holding ONE chord, differing only in

    - the header's accompaniment-pattern bit, which locks the alternate
      pattern on from bar 1, and
    - which bar mark, if any, appears at bar 5.

Each is then played on ../csrc/playcard, and the run counts key-ons per bar on
the two chord channels (3 and 4) against the bass (5).  A card whose chord
count goes to zero and stays there has triggered the bug.

csrc/playcard REPAIRS the bug by default, so this runs it --as-is, the machine
untouched.  --repaired runs the same cards with the repair on, and every row
should then hold all sixteen bars.  What the repair is, and the code at fault
(the pattern-change routine at 0x4C63 sends the chord part "no chord"), is in
"The chord dropout" in ../csrc/README.md.

NEEDS the three ROM images and a built ../csrc/playcard - see ../Roms/README.md
and ../csrc/README.md.
"""
import argparse
import collections
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import playcard_decode as P
import playcard_encode as E

WHOLE = 96
BARS = 16
BAR_S = 60.0 / 100 * 4                 # tempo index 15 is 100 bpm, 4/4
C_MAJOR, G_SEVENTH = 0x0E, 0x28
CHORD_CHANNELS = (3, 4)
BASS_CHANNEL = 5


def build(f3=0, mark=None, mark_bar=5, restate=None, restate_bar=9):
    """One card: a held chord, optionally one bar mark, optionally a later
    chart record.  `restate` is the chord value to state at `restate_bar`."""
    mel = [('note', 14)] + [('rest', None)] * (BARS - 1)
    obb, position_of_bar, pos = [], {}, 0
    for bar in range(1, BARS + 1):
        if bar == mark_bar and mark is not None:
            obb.append(('mark', mark))
            pos += 2          # an escape costs two 4-bit reads, and chart
                              # positions count reads: see nibble_positions()
                              # in ../midi_compile.py
        obb.append(('rest', None))
        pos += 1
        position_of_bar[bar] = pos
    chart = [(C_MAJOR, 1)]
    if restate is not None:
        chart.append((restate, position_of_bar[restate_bar]))
    return E.Card(tempo=15, rhythm=4, f3=f3, mel_voice=6, sustain=0,
                  obb_voice=1, key=0, alphabet=(WHOLE, 0xE1),
                  mel_durs=[WHOLE] * BARS, obb_durs=[WHOLE] * BARS,
                  mel_ops=E.terminated(mel), obb_ops=E.terminated(obb),
                  chart=chart)


def emulator():
    for name in ('playcard.exe', 'playcard'):
        p = os.path.join(os.path.dirname(HERE), 'csrc', name)
        if os.path.isfile(p):
            return p
    raise P.Missing(
        'csrc/playcard is not built, and this needs it to play each card.\n'
        'Build it with "cd csrc && make"; it also needs the three ROM images '
        'named in Roms/README.md.')


def keyons(path):
    """{channel: [times]} from an fmlog.  Register 0x08 with any slot bit set
    is a key-on; the low three bits are the channel."""
    out = collections.defaultdict(list)
    for line in open(path):
        p = line.split()
        if len(p) >= 3 and p[1] == '08' and int(p[2], 16) >> 3:
            out[int(p[2], 16) & 7].append(float(p[0]))
    return out


def bars_of(times, t0):
    per = [0] * BARS
    for t in times:
        i = int((t - t0) / BAR_S)
        if 0 <= i < BARS:
            per[i] += 1
    return per


AS_IS = ['--as-is']          # --repaired empties this


def run(card, work, exe, tag):
    img = os.path.join(work, tag + '.bin')
    log = os.path.join(work, tag + '.fmlog')
    open(img, 'wb').write(E.build(card))
    r = subprocess.run([exe, img, '-o', log, '--quiet', '--seconds', '60',
                        '--roms', P.ROM_DIR, '--mix', 'cartridge'] + AS_IS,
                       capture_output=True, text=True)
    if not os.path.isfile(log):
        raise P.Missing('csrc/playcard wrote no capture for %s:\n%s'
                        % (tag, (r.stdout + r.stderr).strip()))
    k = keyons(log)
    chord = sorted(k[CHORD_CHANNELS[0]] + k[CHORD_CHANNELS[1]])
    bass = sorted(k[BASS_CHANNEL])
    if not chord and not bass:
        raise P.Missing('no accompaniment at all in %s - is the SFG ROM '
                        'present?' % tag)
    t0 = min(chord + bass)
    return bars_of(chord, t0), bars_of(bass, t0)


def verdict(per):
    """Where the chord notes stopped, if they did."""
    live = [i for i, n in enumerate(per) if n]
    if not live:
        return 'no chord notes at all'
    if live[-1] >= BARS - 1:
        return 'holds all %d bars' % BARS
    return 'STOPS after bar %d' % (live[-1] + 1)


def show(label, per):
    print('  %-36s %s  %s' % (label[:36], ' '.join('%2d' % n for n in per),
                              verdict(per)))


def main():
    ap = argparse.ArgumentParser(
        description="What triggers the UPA-01's chord dropout?")
    ap.add_argument('--keep', metavar='DIR',
                    help='keep the card images and captures here')
    ap.add_argument('--repaired', action='store_true',
                    help="play with csrc/playcard's repair of the bug on")
    a = ap.parse_args()
    if a.repaired:
        del AS_IS[:]

    exe = emulator()
    work = a.keep or tempfile.mkdtemp(prefix='dropout-')
    if not os.path.isdir(work):
        os.makedirs(work)
    try:
        print('chord key-ons per bar, one chord held for all 16%s\n'
              % (' - WITH THE REPAIR ON' if a.repaired else ''))

        print('WHICH ROUTE TO THE ALTERNATE PATTERN?')
        for label, f3, mark in (
                ('header clear, no mark 7', 0, None),
                ('header clear, mark 7 at bar 5', 0, 7),
                ('header LOCKS alternate, no mark 7', 2, None),
                ('header LOCKS alternate, mark 7 at 5', 2, 7)):
            per, bass = run(build(f3=f3, mark=mark), work, exe,
                            'route-%d-%s' % (f3, mark))
            show(label, per)
        print('  %-36s %s  the bass, unaffected throughout'
              % ('', ' '.join('%2d' % n for n in bass)))

        print('\nIS IT MARK 7, OR ANY BAR MARK?')
        for mark in range(8):
            per, _ = run(build(mark=mark), work, exe, 'mark-%d' % mark)
            show('mark %d at bar 5' % mark, per)

        print('\nWHAT BRINGS THE CHORD NOTES BACK?')
        for label, restate in (('nothing after the mark', None),
                               ('the SAME chord restated at bar 9', C_MAJOR),
                               ('a DIFFERENT chord at bar 9', G_SEVENTH)):
            per, _ = run(build(mark=7, restate=restate), work, exe,
                         'back-%s' % restate)
            show(label, per)

        if a.repaired:
            print('\nWith the repair every row should hold all 16 bars.')
        else:
            print('\nSo: mark 7 alone triggers it, in either header state; the')
            print('header lock never does; no other mark does; and any chart')
            print('record afterwards restores the chord notes, the same chord')
            print('restated as readily as a new one.')
        if a.keep:
            print('\ncards and captures kept in %s' % work)
    finally:
        if not a.keep:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    P.run(main)
