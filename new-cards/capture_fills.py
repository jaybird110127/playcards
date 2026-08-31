#!/usr/bin/env python3
"""
Play a bar-mark test card on the real firmware and record what the drums do.

    python capture_fills.py playcard_new-01_fill-test_rock.bin [seconds]

Two files come out beside the card:

    <card>.fmlog     every YM2151 write - where the drums and accompaniment are
    <card>.marks     every write to the three bytes that say what the firmware
                     DECIDED, each with the PC that made it

Both are timestamped by the same emulated clock, which is what makes them
comparable.  Absolute timing in a capture is not trustworthy on its own - see
the trap in HANDOFF.md - so a finding should rest on one stream against the
other rather than on elapsed seconds.

THE THREE BYTES, and why they are the ones to read

    0xD34E   the bar mark, ORed with 0xC0.  A write of C1 from pc=5F66 is
             mark 1 arriving; the 4x echo from 0x611B is it being sent onward.
    0xD352   the accompaniment pattern state - bit 0 the one-bar alternate,
             bit 1 the header's lock.
    0xD353   the live chord byte, written by the chart handler.

These are what the card ASKED FOR.  The key-ons in the .fmlog are what the
cartridge then managed to play, and the two differ: this machine drops the
accompaniment's chord notes after a mark 7 and never brings them back (see
dropout_trigger.py).  Read the decisions here, not the audio.

WHICH MACHINE

The UPA-01, on an emulated CX5M - ../csrc/playcard does the running, so this
needs that built and the three ROM images.  See ../csrc/README.md and
../Roms/README.md.  It used to drive openMSX through a Tcl harness with
breakpoints on 0x5F61, 0x5FC9 and 0x5CB2; the memory watches above see exactly
the same events, about 150x faster and with nothing to install.
"""

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import playcard_decode as P

# What the firmware decided, as against what it played.  See the docstring.
WATCH = ('0xD34E', '0xD352', '0xD353')


def emulator():
    for name in ('playcard.exe', 'playcard'):
        p = os.path.join(ROOT, 'csrc', name)
        if os.path.isfile(p):
            return p
    raise P.Missing(
        'csrc/playcard is not built, and this needs it to play the card.\n'
        'Build it with "cd csrc && make". It also needs the three ROM images '
        'named in Roms/README.md.')


def capture(card, seconds):
    exe = emulator()
    stem = os.path.join(HERE, os.path.splitext(os.path.basename(card))[0])
    fmlog, marks = stem + '.fmlog', stem + '.marks'
    cmd = [exe, card, '-o', fmlog, '--watch-out', marks,
           '--seconds', str(seconds), '--roms', P.ROM_DIR, '--quiet']
    for a in WATCH:
        cmd[6:6] = ['--watch', a]
    P.say('capturing up to %d emulated seconds of %s'
          % (seconds, os.path.basename(card)), prefix='')
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    if not os.path.isfile(fmlog):
        raise P.Missing('csrc/playcard produced no capture:\n%s'
                        % (r.stdout + r.stderr).strip())
    print('done in %.1fs wall clock' % (time.time() - t0))
    for path in (fmlog, marks):
        n = sum(1 for _ in open(path)) if os.path.isfile(path) else 0
        print('  -> %-46s %6d lines' % (os.path.basename(path), n))
    return fmlog, marks


def summarise(marks):
    """The bar marks the firmware saw, in order, from the watch report."""
    seen = []
    for line in open(marks):
        f = line.split()
        if len(f) >= 5 and f[1] == 'D34E' and f[2] == 'W' and f[4] == 'pc=5F66':
            seen.append((float(f[0]), int(f[3], 16) & 0x0F))
    if not seen:
        print('\nno bar marks in this card')
        return
    print('\n%d bar marks reached the dispatcher:' % len(seen))
    t0 = seen[0][0]
    for t, m in seen:
        print('   %7.3f s  (+%6.3f)  mark %d' % (t, t - t0, m))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    card = args[0] if args else os.path.join(
        HERE, 'playcard_new-01_fill-test_rock.bin')
    seconds = int(args[1]) if len(args) > 1 else 90
    P.check_card(card)
    fmlog, marks = capture(card, seconds)
    summarise(marks)


if __name__ == '__main__':
    P.run(main)
