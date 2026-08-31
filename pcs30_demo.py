#!/usr/bin/env python3
"""Pull the three built-in demo tunes out of the Yamaha PCS-30 keyboard ROM.

    python pcs30_demo.py            # all three, decoded
    python pcs30_demo.py --raw      # span hexdumps as well

The PCS-30 is a Playcard-capable keyboard, so the question is whether its demos
are card images, the decoded form, or something of the keyboard's own.  They are
**the decoded form**: each demo is the exact RAM image a swiped card produces,
with the span index precomputed.  A block is

    12 words   six (start, end) offsets into the body, in the order the loader
               files them away; bit 15 of a pitch-stream offset selects the
               nibble within the byte
     3 bytes   copied to 0x802D - the performance settings
     1 word    body length
     body      alphabet, two duration tracks, chord table, two pitch streams

What settles it is that the twelve offsets go into the *same twelve RAM slots*
(0x805D..0x806B, 0x80B5/B7/BB/BD) and the body into the *same buffer* (0x80DA)
that the card-reading path at ROM 0x0383 fills a byte at a time from the reader
at 0xE020.  The demo loader at 0x0820 is a block copy where the card path is a
parser; downstream, playback cannot tell them apart.

Card-native, unchanged:
  * the pitch streams - 4-bit opcodes, escape 0x0F, the same note letters and
    running octave register, read at 0x25BC (low nibble) and 0x2626 (high)
  * the alphabet, still ordered most-frequent-first
  * the chord table, and the convention that bar marks and control opcodes
    appear only in the obbligato stream, never the melody

Expanded, no longer card-shaped:
  * the duration tracks.  On a card these are alternating-run prefix codewords
    indexing the alphabet; here they are the alphabet's *values*, one byte per
    read (0x2561: LD B,(HL) / INC DE).  The codeword reading fails outright.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playcard_decode as P

DEMOS = (0x3726, 0x3873, 0x39BC)

# The span the twelve header words describe, in the order they are read, and
# where the loader at ROM 0x0820 files each one away.
SLOTS = ('alphabet.start', 'alphabet.end',
         'melody-stream.start', 'obb-stream.start', 'melody-stream.end', 'obb-stream.end',
         'melody-track.start', 'obb-track.start', 'melody-track.end', 'obb-track.end',
         'chords.start', 'chords.end')

SPAN_NAME = ('alphabet', 'melody durations', 'obbligato durations',
             'chord table', 'melody pitches', 'obbligato pitches')

# The card's own master table, for saying which alphabet entries are lengths.
TICKS = {3, 4, 6, 8, 9, 12, 16, 18, 24, 36, 48, 72, 96}


def blocks(rom):
    """Each demo, cut into its six spans."""
    for base in DEMOS:
        words = [rom[base + i] | (rom[base + i + 1] << 8) for i in range(0, 24, 2)]
        head = rom[base + 24:base + 27]
        n = rom[base + 27] | (rom[base + 28] << 8)
        body = rom[base + 29:base + 29 + n]
        # The high bit turns up on a couple of offsets; mask it to get the value.
        offs = sorted(w & 0x7FFF for w in words)
        bounds = [offs[i] for i in range(0, 12, 2)] + [n]
        spans = [body[bounds[i]:bounds[i + 1]] for i in range(6)]
        yield base, words, head, body, spans


def nibbles(b):
    for x in b:
        yield x >> 4
        yield x & 15


def decode_stream(blob):
    """Walk a pitch stream with the FORMAT's opcode rules.

    Not the cartridge's, despite where they were first read: the opcodes are
    the Playcard ones and the PCS-30 uses the same set, which is half the point
    of this script.  1-7 note letters, 0 rest, 8/9/A modifiers, B/C/D the
    control trio, E return, F escape, and the octave a running register
    starting at 4, exactly as on a card.
    """
    ns = list(nibbles(blob))
    octave, sharp = 4, False
    out, marks, ctl = [], [], []
    i = 0
    while i < len(ns):
        op = ns[i]
        i += 1
        if 1 <= op <= 7:
            code = P.OP07[op]
            idx = P.OPM_INDEX[code] + (1 if sharp else 0)
            out.append(('note', 12 * (octave + 1) + idx + 1))
            sharp = False
        elif op == 0:
            out.append(('rest', None))
        elif op == 8:            # emits 0xE8 01 - raise the octave register
            octave += 1
        elif op == 9:            # emits 0xE8 02 - lower it
            octave -= 1
        elif op == 0xA:          # emits 0xE8 00 - sharpen the next note only
            sharp = True
        elif op in (0xB, 0xC, 0xD):
            ctl.append({0xB: 0x11, 0xC: 0x13, 0xD: 0x14}[op])
            out.append(('ctl', {0xB: 0x11, 0xC: 0x13, 0xD: 0x14}[op]))
        elif op == 0xE:
            out.append(('end', None))
            break
        elif op == 0xF:
            if i >= len(ns):
                break
            sub = ns[i]
            i += 1
            if sub < 8:
                marks.append(sub)
                out.append(('mark', sub))
            else:
                out.append(('loop', sub - 8))
    return out, marks, ctl


NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def pitch_name(m):
    return '%s%d' % (NAMES[m % 12], m // 12 - 1)


def main():
    raw = '--raw' in sys.argv
    try:
        rom = open(P.rom('PCS-30.rom'), 'rb').read()
    except P.Missing as e:
        sys.exit(str(e))

    for n, (base, words, head, body, spans) in enumerate(blocks(rom), 1):
        print('=' * 72)
        print('demo %d at ROM %04X   body %d bytes' % (n, base, len(body)))
        print('=' * 72)
        print('  header words :', ' '.join('%04X' % w for w in words))
        print('  slots        :', ', '.join(
            '%s=%04X' % (s, w) for s, w in zip(SLOTS, words)))
        print('  3-byte head  : %s  -> 0x802D' % head.hex())
        for i, s in enumerate(spans):
            print('  span %d  %-20s %3d bytes' % (i, SPAN_NAME[i], len(s)))
        if raw:
            for i, s in enumerate(spans):
                print('    [%d] %s' % (i, s.hex()))

        alpha = list(spans[0])
        used = set(spans[1]) | set(spans[2])
        print('\n  -- alphabet (span 0, %d symbols, most-frequent-first) --' % len(alpha))
        print('     ' + '  '.join(
            '%02X=%s' % (b, ('%d%s' % (b & 0x7F, "'" if b & 0x80 else '')
                             if (b & 0x7F) in TICKS else 'ctl'))
            for b in alpha))
        print('     exactly the set the duration tracks use: %s'
              % ('yes' if used == set(alpha) else 'NO'))

        for label, si in (('melody', 4), ('obbligato', 5)):
            ev, marks, ctl = decode_stream(spans[si])
            notes = [p for k, p in ev if k == 'note']
            print('\n  -- %s (span %d, %d nibbles) --' % (label, si, len(spans[si]) * 2))
            print('     %d notes, %d rests, marks=%s, control=%s'
                  % (len(notes), sum(1 for k, _ in ev if k == 'rest'),
                     sorted(set(marks)) or 'none',
                     ['%02X' % c for c in sorted(set(ctl))] or 'none'))
            print('     ' + ' '.join(pitch_name(p) for p in notes[:28])
                  + (' ...' if len(notes) > 28 else ''))
        print()


if __name__ == '__main__':
    P.run(main)
