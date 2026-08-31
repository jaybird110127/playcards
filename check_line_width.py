# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""Run the tools down many paths and flag any sentence too wide for a terminal.

    python check_line_width.py

A terminal breaks an over-long line wherever it runs out, which lands in the
middle of a word.  `playcard_decode.say()` wraps at the words instead, and this
checks that nothing has escaped it: the tools are run down some fifty paths -
random data of five sizes, seven differently damaged cards, every complaint the
compiler can raise, bad voice names, wrong files - and every line of output is
measured at 80 columns.

Only PROSE is flagged.  A drum grid and a duration dump have plenty of spaces
and are not sentences, so the test counts DISTINCT words: eight or more, and no
token longer than 40 characters, which excludes paths and hex.

A static scan is not enough here and was not: it saw only constant strings, and
forge_crc's failure report is assembled from an exception's fields.
"""
import os
import random
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SC = os.path.join(os.environ.get('TEMP', ROOT), 'playcard-checks')
JUNK = os.path.join(SC, 'junk')
WIDTH = 80

CARD = os.path.join(ROOT, 'new-cards', 'playcard_new-04_chord-test_rock.bin')
BIG = os.path.join(ROOT, 'Original Playcards', 'playcard_17-542_abba_one_of_us.bin')
MIDI = os.path.join(SC, 'w.mid')
MESSY = os.path.join(SC, 'messy.mid')
MELONLY = os.path.join(SC, 'melody_only.mid')
WAV = os.path.join(SC, 'r.wav')


def make_broken():
    """Cards damaged in several different places, to reach several failures."""
    out = []
    good = open(CARD, 'rb').read()
    rng = random.Random(7)
    for n in (8, 60, 200, 430, 433):
        p = os.path.join(SC, 'rnd%d.bin' % n)
        open(p, 'wb').write(bytes(bytearray(rng.randrange(256) for _ in range(n))))
        out.append(p)
    for at in (0, 1, 3, 6, 12, 25, 40):
        d = bytearray(good)
        if at < len(d):
            d[at] ^= 0xFF
        p = os.path.join(SC, 'bent%d.bin' % at)
        open(p, 'wb').write(bytes(d))
        out.append(p)
    p = os.path.join(SC, 'short.bin')
    open(p, 'wb').write(good[:20])
    out.append(p)
    return out


def cmds():
    broken = make_broken()
    c = []
    for b in broken:
        c.append(['forge_crc.py', b])
        c.append(['card_limits.py', b])
        c.append(['playcard_decode.py', b])
    c += [
        ['midi_compile.py', MESSY, '-o', os.path.join(SC, 'o.bin')],
        ['midi_compile.py', MESSY, '-o', os.path.join(SC, 'o.bin'), '-v'],
        ['midi_compile.py', MELONLY, '-o', os.path.join(SC, 'o.bin')],
        ['midi_compile.py', MIDI, '-o', os.path.join(SC, 'o.bin'), '-v'],
        ['midi_compile.py', MIDI, '-o', os.path.join(SC, 'o.bin'), '--melody-voice', 'tuba'],
        ['card_decompile.py', CARD, '-o', os.path.join(SC, 'o.mid')],
        ['card_limits.py', CARD],
        ['card_limits.py', os.path.join(ROOT, 'Original Playcards',
                                        'playcard_pc-1000-japan_1-09_side-b.bin')],
        ['card_to_swipe.py', BIG, '-o', os.path.join(SC, 'o.wav'), '--strip', '3500'],
        ['card_to_swipe.py', CARD, '-o', os.path.join(SC, 'o.wav'), '--rate', '8000',
         '--bitrate', '4000'],
        ['swipe_to_card.py', os.path.join(SC, 'o.wav')],
        ['swipe_to_card.py', os.path.join(JUNK, 'pure.junk')],
        ['header_edit.py', CARD],
        ['header_edit.py', CARD, '-o', os.path.join(SC, 'o.bin'), '--tempo', '999'],
        ['header_edit.py', CARD, '-o', os.path.join(SC, 'o.bin'), '--melody-voice', 'tuba'],
        ['make_test_midi.py', os.path.join(SC, 'o.mid'), '--form', 'short'],
        ['make_random_card.py', '--seed', '4'],
        ['pcs30_arrange.py', CARD, '-o', os.path.join(SC, 'o.mid')],
        ['pcs30_rhythm.py', '--chord', 'Am7'],
        ['pcs30_drums.py', '--fills'],
        ['pcs30_tables.py'], ['pcs30_extract.py', '--check'],
        ['msx_player.py', '--roms'],
        ['same_root_entries.py', 'fly_me'],
        ['playcard_decode.py', CARD],
        ['playcard_expand.py', CARD],
        ['midi_export.py', CARD, '-o', os.path.join(SC, 'o.mid')],
        ['card_dates.py'],
        # and the wrong-file refusals, which are prose too
        ['forge_crc.py', MIDI], ['card_limits.py', os.path.join(JUNK, 'prog.exe')],
        ['pcs30_arrange.py', os.path.join(JUNK, 'constitution.pdf')],
        ['midi_compile.py', os.path.join(JUNK, 'page.html')],
    ]
    return c


def prose(line):
    """A sentence rather than a table row, a data dump or a path.

    A drum grid is mostly X and dot; a duration dump is one word over and over.
    What tells a sentence apart is VARIETY - so count distinct words.
    """
    words = [t.strip(",.;:'()[]") for t in line.split()]
    words = [t for t in words if len(t) >= 2 and t.isalpha()]
    if len(set(words)) < 8:
        return False
    longest = max((len(t) for t in line.split()), default=0)
    return longest <= 40           # a long token is a path or a hex dump


def main():
    env = dict(os.environ, COLUMNS=str(WIDTH))
    bad = 0
    for c in cmds():
        r = subprocess.run([sys.executable, os.path.join(ROOT, c[0])] + c[1:],
                           capture_output=True, text=True, cwd=ROOT, timeout=300, env=env)
        for line in (r.stdout + r.stderr).split('\n'):
            line = line.rstrip()
            if len(line) > WIDTH and prose(line):
                bad += 1
                print('%3d  %-22s %s' % (len(line), c[0], line[:100]))
    print('\n%d over-wide prose lines' % bad)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
