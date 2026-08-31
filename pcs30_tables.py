#!/usr/bin/env python3
"""The PCS-30's pattern tables, loaded from a file this repository does not ship.

    import pcs30_tables
    t = pcs30_tables.load()          # raises Missing, with instructions, if absent
    t.pitch_byte(table, row, step)
    t.drum_mask(bank, bit, step)

WHY THIS EXISTS

A Playcard selects an accompaniment; it does not carry one. The pattern itself
lives in the instrument, and it is Yamaha's musical content rather than a fact
about the file format - so it stays out of this repository, while the tools that
work with it do not have to.

The split is: **this repository holds the code and the addresses, your PCS-30
ROM holds the music.** `pcs30_extract.py` reads the ROM and writes
`pcs30-tables.json`; everything else reads that file and never touches the ROM.
The generated file is gitignored, and nothing here will work until you make one.

WHAT IS IN THE FILE

Two tables, 2880 bytes between them.

  pitch   eight 320-byte tables from ROM 0x2D26, each ten rows of thirty-two.
          Odd tables are the bass and even ones the chord; within each, one is
          for plain triads and one for sevenths. A byte is a 1-based semitone
          offset from the chord root, 0xFF a rest, 0x00 a dead slot.

  drums   five 64-byte bit-planes from ROM 0x2BBC. Assembling bit b of all five
          planes gives the 5-bit strike mask for one sixteenth-note step.
          Bank 0 bits 7..0 are rhythms 0-7, bank 1 bits 7,6 are rhythms 8,9,
          and bank 1 bits 5..0 are the six drum fills.

The layout is documented in full in playcard-format.md. Nothing about it is
secret; the bytes are simply not ours to publish.
"""

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
TABLES = os.environ.get('PCS30_TABLES') or os.path.join(HERE, 'pcs30-tables.json')

PITCH_LEN = 8 * 0x140                   # eight tables of 320
DRUM_LEN = 5 * 0x40                     # five bit-planes of 64
FORMAT = 1

STYLES = ['rhumba', 'samba', 'swing', 'bossa-nova', 'rock',
          '16-beat', 'waltz', 'slow-rock', 'march', 'disco']

# table index -> (voice, which chord it serves, which of the two variants)
PITCH_TABLES = [(0, 'chord', 'plain', 'A'), (1, 'bass', 'plain', 'A'),
                (2, 'chord', 'seventh', 'A'), (3, 'bass', 'seventh', 'A'),
                (4, 'chord', 'plain', 'B'), (5, 'bass', 'plain', 'B'),
                (6, 'chord', 'seventh', 'B'), (7, 'bass', 'seventh', 'B')]


class Missing(Exception):
    """No table file.  The message is meant to be printed as it stands."""


def _explain(why):
    return Missing(
        '%s\n'
        '\n'
        "The PCS-30's accompaniment and drum patterns are Yamaha's, so they are\n"
        'not in this repository. Generate them from your own ROM:\n'
        '\n'
        '    python pcs30_extract.py\n'
        '\n'
        'That reads Roms/PCS-30.rom (or $PLAYCARD_ROMS/PCS-30.rom) and writes\n'
        '%s, which is all these tools need.\n'
        'Set PCS30_TABLES to keep it somewhere else.'
        % (why, TABLES))


class Tables(object):
    """The two tables, and the two ways anything reads them."""

    def __init__(self, pitch, drums, meta=None):
        if len(pitch) != PITCH_LEN:
            raise _explain('the pitch table is %d bytes, expected %d'
                           % (len(pitch), PITCH_LEN))
        if len(drums) != DRUM_LEN:
            raise _explain('the drum table is %d bytes, expected %d'
                           % (len(drums), DRUM_LEN))
        self.pitch = pitch
        self.drums = drums
        self.meta = meta or {}

    def pitch_byte(self, table, row, step):
        """One step of one pattern: ROM 0x14CD, base + rhythm * 32 + step."""
        return self.pitch[table * 0x140 + row * 32 + step]

    def drum_mask(self, bank, bit, step):
        """The 5-bit strike mask for one step, assembled across the planes."""
        v = 0
        for plane in range(5):
            v = (v << 1) | ((self.drums[plane * 0x40 + bank * 0x20 + step] >> bit) & 1)
        return v


def load(path=None):
    """The tables, or Missing with an explanation of how to make them."""
    path = path or TABLES
    if not os.path.isfile(path):
        raise _explain('no pattern tables at %s' % path)
    try:
        with open(path, 'r') as f:
            d = json.load(f)
        if d.get('format') != FORMAT:
            raise _explain('%s is format %r, this code wants %d'
                           % (path, d.get('format'), FORMAT))
        pitch = bytes(bytearray.fromhex(d['pitch']))
        drums = bytes(bytearray.fromhex(d['drums']))
    except Missing:
        raise
    except (ValueError, KeyError, TypeError) as e:
        raise _explain('%s is not readable as pattern tables (%s)' % (path, e))
    return Tables(pitch, drums, d.get('from'))


def main():
    """Say whether the tables are here, and what they came from."""
    try:
        t = load()
    except Missing as e:
        print(e)
        raise SystemExit(1)
    print('%s' % TABLES)
    for k in sorted(t.meta):
        print('  %-10s %s' % (k, t.meta[k]))
    print('  pitch      %d bytes, %d tables' % (len(t.pitch), len(t.pitch) // 0x140))
    print('  drums      %d bytes, 5 planes' % len(t.drums))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
