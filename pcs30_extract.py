#!/usr/bin/env python3
"""Read a PCS-30 ROM and write the pattern tables the other tools need.

    python pcs30_extract.py                  # Roms/PCS-30.rom -> pcs30-tables.json
    python pcs30_extract.py --rom other.rom
    python pcs30_extract.py --check          # is the file here, and does it look right

Run this once. Everything that plays PCS-30 accompaniment - `pcs30_arrange.py`,
`pcs30_rhythm.py`, `pcs30_drums.py` - then reads the generated file and never
touches the ROM again.

WHY

The patterns are Yamaha's musical content, so they are not in this repository
and neither is any ROM. What is here is the *address* of each table, which is a
fact about the machine rather than a piece of its music, and the code to lift
them out. Given a ROM you already own, this reproduces the missing file exactly.

WHAT IT TAKES

  pitch   ROM 0x2D26, 8 x 320 bytes, ending exactly where the demo tunes begin
  drums   ROM 0x2BBC, 5 x 64 bytes of bit-planes

Both regions are checked for shape before they are written: a wrong or corrupt
image is worth catching here rather than three tools later.
"""

import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playcard_decode as P
import pcs30_tables as T

PITCH_BASE = 0x2D26
DRUM_BASE = 0x2BBC
ROM_NAME = 'PCS-30.rom'


def check_pitch(b):
    """A pattern table is degrees, rests and dead slots - nothing else.

    Every byte is either 0x00, 0xFF, or a 1-based degree.  The chord tables run
    to +29 semitones and the bass to +16, so nothing legitimate reaches 0x40.
    A wrong base address lands in code or in the demo tunes and fails this at
    once.
    """
    bad = [v for v in b if v not in (0x00, 0xFF) and v > 0x40]
    if bad:
        return '%d of %d bytes are not playable degrees (e.g. 0x%02X)' \
            % (len(bad), len(b), bad[0])
    live = sum(1 for v in b if v not in (0x00, 0xFF))
    if live < len(b) // 4:
        return 'only %d of %d bytes carry a note - this does not look like ' \
            'the pattern tables' % (live, len(b))
    return None


def check_drums(b):
    """Every rhythm has to strike something, and the planes must differ."""
    if len(set(b)) < 8:
        return 'the five planes are too uniform to be drum patterns'
    empty = [r for r in range(8)
             if not any((b[p * 0x40 + s] >> (7 - r)) & 1
                        for p in range(5) for s in range(32))]
    if empty:
        return 'rhythm %d never strikes a drum' % empty[0]
    return None


def extract(rom):
    pitch = rom[PITCH_BASE:PITCH_BASE + T.PITCH_LEN]
    drums = rom[DRUM_BASE:DRUM_BASE + T.DRUM_LEN]
    for what, b, fn in (('pitch', pitch, check_pitch), ('drums', drums, check_drums)):
        if len(b) != (T.PITCH_LEN if what == 'pitch' else T.DRUM_LEN):
            raise SystemExit('pcs30_extract: the ROM ends inside the %s table - '
                             'is it a PCS-30 image?' % what)
        why = fn(b)
        if why:
            raise SystemExit('pcs30_extract: the %s table does not check out: %s\n'
                             'This does not look like a PCS-30 ROM.' % (what, why))
    return pitch, drums


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--rom', default=ROM_NAME, help='the ROM image to read')
    ap.add_argument('-o', '--out', default=T.TABLES, help='where to write')
    ap.add_argument('--check', action='store_true',
                    help='report on an existing file instead of writing one')
    a = ap.parse_args()

    if a.check:
        try:
            t = T.load(a.out)
        except T.Missing as e:
            print(e)
            return 1
        print('%s looks right' % a.out)
        for k in sorted(t.meta):
            print('  %-10s %s' % (k, t.meta[k]))
        return 0

    try:
        path = P.rom(a.rom)
    except P.Missing as e:
        print(e)
        print('\nThe PCS-30 ROM is the one this needs, and it is not ours to '
              'ship.\nWithout it the accompaniment tools cannot run; everything '
              'else in\nthis repository works without it.')
        return 1

    rom = open(path, 'rb').read()
    need = PITCH_BASE + T.PITCH_LEN
    if len(rom) < need:
        print('pcs30_extract: %s is %d bytes and the tables end at %d - '
              'is this a PCS-30 ROM?' % (path, len(rom), need))
        return 1

    pitch, drums = extract(rom)
    doc = {
        'format': T.FORMAT,
        'what': "Yamaha PCS-30 accompaniment and drum pattern tables, lifted "
                "from a ROM by pcs30_extract.py. Not redistributable.",
        'from': {
            'rom': os.path.basename(path),
            'bytes': len(rom),
            'sha256': hashlib.sha256(rom).hexdigest(),
            'pitch_at': '0x%04X' % PITCH_BASE,
            'drums_at': '0x%04X' % DRUM_BASE,
        },
        'pitch': ''.join('%02x' % b for b in bytearray(pitch)),
        'drums': ''.join('%02x' % b for b in bytearray(drums)),
    }
    with open(a.out, 'w') as f:
        json.dump(doc, f, indent=1, sort_keys=True)
        f.write('\n')

    t = T.load(a.out)                   # read it back the way the tools will
    print('%s' % a.out)
    print('  from %s (sha256 %s...)' % (os.path.basename(path),
                                        doc['from']['sha256'][:16]))
    print('  pitch  %d bytes at 0x%04X, %d tables of ten rows'
          % (len(t.pitch), PITCH_BASE, len(t.pitch) // 0x140))
    print('  drums  %d bytes at 0x%04X, five bit-planes'
          % (len(t.drums), DRUM_BASE))
    print('\nThis file is gitignored on purpose. Keep it, or make it again.')
    return 0


if __name__ == '__main__':
    P.run(main)
