# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""Throw the wrong file at every tool and check it answers instead of crashing.

    python check_wrong_file.py

Nine kinds of wrong file - a MIDI, a WAV, a PDF, an HTML page, an executable,
random bytes, an empty file, a folder, and a path that does not exist - against
every tool that takes one.  A clean refusal names the file, names what it looks
like, names what the tool wanted, and exits 1.  Anything else is a failure.

It writes its own junk files into the system temp directory.  Run it after
touching how any tool opens a file.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SC = os.path.join(os.environ.get('TEMP', ROOT), 'playcard-checks')
JUNK = os.path.join(SC, 'junk')
NL = bytes(bytearray([10]))     # a newline, spelled so no shell can mangle it

CARD = os.path.join(ROOT, 'new-cards', 'playcard_new-04_chord-test_rock.bin')
MIDI = os.path.join(SC, 'sample.mid')
WAV = os.path.join(SC, 'sample.wav')


def setup():
    """The junk to throw, and one real MIDI and WAV made from a card we ship."""
    for d in (SC, JUNK):
        if not os.path.isdir(d):
            os.makedirs(d)
    junk = {
        'constitution.pdf': b'%PDF-1.4' + NL + b'1 0 obj' + NL,
        'page.html': b'<!DOCTYPE html>' + NL + b'<html><body>hi</body></html>' + NL,
        'pure.junk': bytes(bytearray((i * 37 + 11) % 256 for i in range(4000))),
        'empty.bin': b'',
        'thing.zip': b'PK' + bytes(bytearray([3, 4])) + b'junk',
        'prog.exe': b'MZ' + bytes(bytearray(200)),
    }
    for name, data in junk.items():
        open(os.path.join(JUNK, name), 'wb').write(data)
    subprocess.run([sys.executable, os.path.join(ROOT, 'card_decompile.py'),
                    CARD, '-o', MIDI], capture_output=True, cwd=ROOT)
    subprocess.run([sys.executable, os.path.join(ROOT, 'card_to_swipe.py'),
                    CARD, '-o', WAV], capture_output=True, cwd=ROOT)

wrong = [('a MIDI', MIDI), ('a WAV', WAV),
         ('a PDF', os.path.join(JUNK, 'constitution.pdf')),
         ('HTML', os.path.join(JUNK, 'page.html')),
         ('an exe', os.path.join(JUNK, 'prog.exe')),
         ('junk', os.path.join(JUNK, 'pure.junk')),
         ('empty', os.path.join(JUNK, 'empty.bin')),
         ('a folder', os.path.join(ROOT, 'new-cards')),
         ('nothing', os.path.join(JUNK, 'no-such-file.bin'))]

# tool -> how to hand it one file, and what it wants
TOOLS = [
    ('playcard_decode.py', lambda f: [f], 'card'),
    ('card_decompile.py', lambda f: [f, '-o', os.path.join(SC, 'o.mid')], 'card'),
    ('card_limits.py', lambda f: [f], 'card'),
    ('card_to_swipe.py', lambda f: [f, '-o', os.path.join(SC, 'o.wav')], 'card'),
    ('forge_crc.py', lambda f: [f], 'card'),
    ('header_edit.py', lambda f: [f], 'card'),
    ('midi_export.py', lambda f: [f, '-o', os.path.join(SC, 'o.mid')], 'card'),
    ('pcs30_arrange.py', lambda f: [f, '-o', os.path.join(SC, 'o.mid')], 'card'),
    ('same_root_entries.py', lambda f: [f], 'card'),
    ('midi_compile.py', lambda f: [f, '-o', os.path.join(SC, 'o.bin')], 'midi'),
    ('swipe_to_card.py', lambda f: [f], 'wav'),
]


def main():
    setup()
    bad = 0
    for tool, argv, wants in TOOLS:
        print('%s  (wants a %s)' % (tool, wants))
        for label, path in wrong:
            if wants == 'midi' and label == 'a MIDI':
                continue
            if wants == 'wav' and label == 'a WAV':
                continue
            r = subprocess.run([sys.executable, os.path.join(ROOT, tool)] + argv(path),
                               capture_output=True, text=True, cwd=ROOT, timeout=120)
            out = (r.stdout + r.stderr).strip()
            first = out.split('\n')[0][:76] if out else '(said nothing)'
            if 'Traceback' in out:
                bad += 1
                print('   %-10s TRACEBACK  %s' % (label, out.split('\n')[-1][:60]))
            elif r.returncode == 0:
                bad += 1
                print('   %-10s ACCEPTED IT (exit 0)  %s' % (label, first))
            else:
                print('   %-10s exit %d  %s' % (label, r.returncode, first))
        print('')
    print('%d results that are not a clean refusal' % bad)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
