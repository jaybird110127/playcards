#!/usr/bin/env python3
"""Read a UPA-01 cartridge ROM and write the accompaniment and drum patterns.

    python upa_extract.py                    # the cartridge ROM -> upa-tables.json
    python upa_extract.py --rom other.rom
    python upa_extract.py --check            # is the file here, and does it look right
    python upa_extract.py --show             # print what is in it

Run this once. Anything that plays the cartridge's own accompaniment reads the
generated file and never touches the ROM again.

WHY

The patterns are Yamaha's musical content, so they are not in this repository
and neither is any ROM. What is here is the *address and shape* of each table,
which is a fact about the machine rather than a piece of its music, and the code
to lift them out. Given a ROM you already own, this reproduces the file exactly.
It is the same line `pcs30_extract.py` draws for the PCS-30 keyboard.

WHAT IS IN THE CARTRIDGE

Three tables of little-endian pointers sit back to back, and the blocks they
name run from 0x5279 to 0x589C - 1572 bytes, with code on either side:

    drums        0x523B   ten pointers, one a rhythm, indexed by the card's
                          raw rhythm value
    drum fills   0x5251   six, indexed by the fill number 1-6 that the card's
                          escape opcode carries (entries 0 and 7 are null)
    accompaniment 0x5261  ten, indexed by the raw rhythm value PLUS ONE

A BLOCK is two header bytes and then one byte a step:

    flags, ticks-a-step, step, step, ...

Every block is 192 ticks - two bars of 4/4 - either as 64 steps of 3 ticks
(a 1/32 note each) or 48 steps of 4 (the swung grid of triplet 1/16s), so it is
66 or 50 bytes long. Bit 7 of the flags clear means THREE-BEAT: the engine
skips the stored fourth beat of each bar, which is how the waltz and the two
waltz fills work, and why those fills leave a hole on beat 4 of a 4/4 bar.

A DRUM byte is a five-bit mask in bits 7 to 3, and a drum sounds where its bit
RISES; bits 2, 1 and 0 are the constant 2 in every byte of every block. An
ACCOMPANIMENT byte holds two patterns, the standard one in its low nibble and
the alternate in its high nibble - bit 1 of the card's 3-bit header field
chooses. Within a nibble, bits 0-2 are a chord-tone number for the bass (0
silence, 1 root, 2 third, 3 fifth, 4 sixth, 5 seventh, 6 octave) which sounds
where it changes, and bit 3 strikes the chord part where it rises.

All of that is measured rather than read off; "The accompaniment patterns" in
HANDOFF.md says how, and what is still open.

WHAT IS CHECKED BEFORE WRITING

The pointer tables have to point where they should, the blocks have to tile the
region exactly, each has to be 66 or 50 bytes with a matching ticks-a-step, and
the drum blocks' low three bits have to be that constant. A wrong or corrupt
image fails here rather than three tools later.
"""

import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playcard_decode as P

TABLES = 'upa-tables.json'
FORMAT = 1

BASE = 0x4000                      # where the cartridge is mapped
DRUMS_PTR = 0x523B                 # ten, by raw rhythm
FILLS_PTR = 0x5251                 # six, by fill number
ACCOMP_PTR = 0x5261                # ten, by raw rhythm + 1
BLOCKS_AT = 0x5279                 # the first block
BLOCKS_END = 0x589D                # one past the last
NRHYTHM = 10
NFILL = 6

RHYTHM = ['rhumba', 'samba', 'swing', 'bossa-nova', 'rock', '16-beat',
          'waltz', 'slow-rock', 'march', 'disco']

# The five mask bits, in the order they sit in a drum byte.  The names are the
# roles their placement gives them - the backbeat one is the snare, the one that
# appears only in rhumba and samba is the latin drum - and the FM channel and
# operator pair each reaches on this cartridge.  Two of the five share a sound
# here, which is why the machine seems to have three drums and not five.
DRUM_BITS = [
    (7, 'cymbal', 'channel 6, operators 1-2'),
    (6, 'cymbal 2', 'channel 6, operators 3-4'),
    (5, 'kick', 'channel 7, operators 1-2'),
    (4, 'latin', 'channel 7, operators 3-4'),
    (3, 'snare', 'channel 7, operators 3-4'),
]
DRUM_LOW = 0x02                    # bits 2-0 of every drum byte, always this

# What a nibble's bits 0-2 name, in the eight-entry table the engine keeps at
# RAM 0xD207 and refills from the card's chord.
CHORD_TONE = ['silence', 'root', 'third', 'fifth', 'sixth', 'seventh',
              'octave', '(unused)']


class Missing(Exception):
    """No tables file, with instructions for making one."""


def word(rom, addr):
    return rom[addr - BASE] | (rom[addr - BASE + 1] << 8)


def pointers(rom, at, n):
    return [word(rom, at + 2 * i) for i in range(n)]


def block(rom, at):
    """-> (flags, ticks, [step bytes]) for the block at `at`."""
    flags, ticks = rom[at - BASE], rom[at - BASE + 1]
    nsteps = 192 // ticks if ticks else 0
    return flags, ticks, list(bytearray(rom[at - BASE + 2:at - BASE + 2 + nsteps]))


def check(rom):
    """-> a complaint about this image, or None.

    Everything here is a structural fact about the cartridge, so an image that
    is not one - or one that has been damaged - trips over it.
    """
    if len(rom) < BLOCKS_END - BASE:
        return 'the image is %d bytes and the patterns end at 0x%04X' \
            % (len(rom), BLOCKS_END)

    drums = pointers(rom, DRUMS_PTR, NRHYTHM + 1)
    fills = pointers(rom, FILLS_PTR, NFILL + 2)
    accomp = pointers(rom, ACCOMP_PTR, NRHYTHM + 2)

    if drums[NRHYTHM] or fills[0] or fills[NFILL + 1] \
            or accomp[0] or accomp[NRHYTHM + 1]:
        return 'the pointer tables do not have their null entries'
    live = drums[:NRHYTHM] + fills[1:NFILL + 1] + accomp[1:NRHYTHM + 1]
    if len(set(live)) != len(live):
        return 'two pointers name the same block'
    for p in live:
        if not BLOCKS_AT <= p < BLOCKS_END:
            return 'a pointer leaves the pattern region: 0x%04X' % p

    # the blocks have to tile the region exactly, in order, with no gaps
    order = sorted(live)
    if order[0] != BLOCKS_AT:
        return 'the first block is 0x%04X, not 0x%04X' % (order[0], BLOCKS_AT)
    for p, nxt in zip(order, order[1:] + [BLOCKS_END]):
        flags, ticks, steps = block(rom, p)
        if ticks not in (3, 4):
            return 'the block at 0x%04X says %d ticks a step' % (p, ticks)
        if flags & ~0x80:
            return 'the block at 0x%04X has unknown flags 0x%02X' % (p, flags)
        if nxt - p != len(steps) + 2:
            return 'the block at 0x%04X is %d bytes, not the %d its header says' \
                % (p, nxt - p, len(steps) + 2)

    for p in drums[:NRHYTHM] + fills[1:NFILL + 1]:
        bad = [v for v in block(rom, p)[2] if v & 0x07 != DRUM_LOW]
        if bad:
            return 'a drum block at 0x%04X has %d bytes whose low bits are ' \
                'not 0x%02X (e.g. 0x%02X)' % (p, len(bad), DRUM_LOW, bad[0])
    for r in range(NRHYTHM):
        if not any(v & 0xF8 for v in block(rom, drums[r])[2]):
            return '%s never strikes a drum' % RHYTHM[r]
    return None


def extract(rom):
    """-> the document that gets written."""
    out = {}
    for name, at, n, first in (('drums', DRUMS_PTR, NRHYTHM, 0),
                               ('fills', FILLS_PTR, NFILL, 1),
                               ('accompaniment', ACCOMP_PTR, NRHYTHM, 1)):
        rows = []
        for i, p in enumerate(pointers(rom, at, n + first + 1)):
            if i < first or i >= first + n:
                continue
            flags, ticks, steps = block(rom, p)
            rows.append({
                'at': '0x%04X' % p,
                'beats': 3 if not flags & 0x80 else 4,
                'ticks_a_step': ticks,
                'steps': ''.join('%02x' % v for v in steps),
            })
        out[name] = rows
    return out


def show(doc):
    """Print the patterns as strikes and chord tones - what they actually say."""
    print('DRUMS - a strike where a bit rises; one column a step\n')
    for what in ('drums', 'fills'):
        for i, row in enumerate(doc[what]):
            steps = [int(row['steps'][k:k + 2], 16)
                     for k in range(0, len(row['steps']), 2)]
            name = RHYTHM[i] if what == 'drums' else 'fill %d' % (i + 1)
            print('  %-11s %s  %d ticks a step, %d beats a bar'
                  % (name, row['at'], row['ticks_a_step'], row['beats']))
            for bit, drum, where in DRUM_BITS:
                line = ''
                for k in range(len(steps) // 2):          # one bar of the two
                    now = steps[k] >> bit & 1
                    was = steps[k - 1] >> bit & 1
                    line += 'X' if now and not was else ('-' if now else '.')
                if 'X' in line:
                    print('     %-9s %s' % (drum, line))
        print()

    print('ACCOMPANIMENT - the bass by chord tone, and where the chord strikes\n')
    for i, row in enumerate(doc['accompaniment']):
        steps = [int(row['steps'][k:k + 2], 16)
                 for k in range(0, len(row['steps']), 2)]
        print('  %-11s %s  %d ticks a step, %d beats a bar'
              % (RHYTHM[i], row['at'], row['ticks_a_step'], row['beats']))
        for shift, which in ((0, 'standard'), (4, 'alternate')):
            bass, chord = '', ''
            for k in range(len(steps) // 2):
                v = steps[k] >> shift
                was = steps[k - 1] >> shift
                bass += str(v & 7) if (v & 7) != (was & 7) and v & 7 else \
                    ('-' if v & 7 else '.')
                chord += 'X' if v & 8 and not was & 8 else ('-' if v & 8 else '.')
            print('     %-9s bass  %s' % (which, bass))
            print('     %-9s chord %s' % ('', chord))
        print()


def load(path=TABLES):
    """The tables as written, for anything that plays them."""
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    if not os.path.isfile(path):
        raise Missing(
            'no %s\n'
            'The cartridge\'s accompaniment and drum patterns are Yamaha\'s and are\n'
            'not in this repository. Make the file from a ROM you own:\n'
            '    python upa_extract.py\n' % path)
    doc = json.load(open(path))
    if doc.get('format') != FORMAT:
        raise Missing('%s was written by another version of upa_extract.py' % path)
    return doc


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--rom', default=P.CART_ROM, help='the ROM image to read')
    ap.add_argument('-o', '--out', default=TABLES, help='where to write')
    ap.add_argument('--check', action='store_true',
                    help='report on an existing file instead of writing one')
    ap.add_argument('--show', action='store_true',
                    help='print the patterns (they are Yamaha\'s - keep it to yourself)')
    a = ap.parse_args()

    if a.check or a.show:
        try:
            doc = load(a.out)
        except Missing as e:
            print(e)
            return 1
        if a.show:
            show(doc)
            return 0
        print('%s looks right' % a.out)
        print('  from %s (sha256 %s...)' % (doc['from']['rom'],
                                            doc['from']['sha256'][:16]))
        for what in ('drums', 'fills', 'accompaniment'):
            print('  %-14s %d blocks, %d bytes of steps'
                  % (what, len(doc[what]),
                     sum(len(r['steps']) // 2 for r in doc[what])))
        return 0

    try:
        path = P.rom(a.rom)
    except P.Missing as e:
        print(e)
        return 1
    rom = open(path, 'rb').read()
    why = check(rom)
    if why:
        print('upa_extract: this does not look like a UPA-01 cartridge ROM: %s' % why)
        return 1

    doc = extract(rom)
    doc.update({
        'format': FORMAT,
        'what': 'Yamaha UPA-01 accompaniment and drum pattern tables, lifted '
                'from a cartridge ROM by upa_extract.py. Not redistributable.',
        'from': {
            'rom': os.path.basename(path),
            'bytes': len(rom),
            'sha256': hashlib.sha256(rom).hexdigest(),
            'drums_at': '0x%04X' % DRUMS_PTR,
            'fills_at': '0x%04X' % FILLS_PTR,
            'accompaniment_at': '0x%04X' % ACCOMP_PTR,
        },
    })
    out = a.out if os.path.isabs(a.out) else \
        os.path.join(os.path.dirname(os.path.abspath(__file__)), a.out)
    with open(out, 'w') as f:
        json.dump(doc, f, indent=1, sort_keys=True)
        f.write('\n')

    load(out)                          # read it back the way the tools will
    print('%s' % a.out)
    print('  from %s (sha256 %s...)' % (os.path.basename(path),
                                        doc['from']['sha256'][:16]))
    for what in ('drums', 'fills', 'accompaniment'):
        rows = doc[what]
        print('  %-14s %2d blocks at 0x%04X-0x%04X, %d bytes of steps'
              % (what, len(rows), int(rows[0]['at'], 16), int(rows[-1]['at'], 16),
                 sum(len(r['steps']) // 2 for r in rows)))
    print('\nThis file is gitignored on purpose. Keep it, or make it again.')
    return 0


if __name__ == '__main__':
    P.run(main)
