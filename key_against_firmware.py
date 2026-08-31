# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""Does our reading of the key field agree with the cartridge?

    python key_against_firmware.py            # every card that uses the field
    python key_against_firmware.py jingle     # one of them

For each card whose key field is not zero, this plays the real card on
`csrc/playcard` and compares the melody the firmware produces, note for note,
against the melody this repository decodes.

It exists because the corpus round trip CANNOT catch a transposition bug: it
decodes and recompiles with the same function, so a wrong shift is wrong in both
directions and agrees with itself perfectly.  For a while it did exactly that,
and 50 cards were read a fourth or a fifth away from what the UPA-01 plays.
The cartridge is the only witness that is not a party to our mistakes.
"""
import collections
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SC = os.environ.get('TEMP', ROOT)
sys.path.insert(0, ROOT)
import playcard_decode as P
import playcard_resolve as R
import midi_export as M

NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def firmware_melody(card):
    log = os.path.join(SC, 'kv.fmlog')
    r = subprocess.run([os.path.join(ROOT, 'csrc', 'playcard.exe'), card,
                        '-o', log, '--quiet'], capture_output=True, cwd=ROOT)
    if not os.path.isfile(log):
        return []
    kc, ev = {}, []
    for line in open(log):
        t, reg, v = line.split()
        reg, v = int(reg, 16), int(v, 16)
        if 0x28 <= reg <= 0x2F:
            kc[reg - 0x28] = v
        elif reg == 0x08 and (v >> 3) & 0x0F:
            ch = v & 7
            if ch in kc and ch in (0, 1):        # the melody's two voices
                code = kc[ch] & 0x0F
                if code in P.NOTE_NAME:
                    ev.append((float(t), P.NOTE_NAME[code]))
    os.remove(log)
    ev.sort()
    return [n for _, n in ev]


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    tally = collections.Counter()
    bad = []
    for f in sorted(P.corpus()):
        h = M.load(f)
        if h.get('type') != 1 or not h['sections']:
            continue
        if h['transpose'] == 0:                  # nothing to get wrong
            continue
        if only and only not in os.path.basename(f):
            continue
        fw = firmware_melody(f)
        if not fw:
            tally['no capture'] += 1
            continue
        t1, t2, s0, s1 = R.resolve(h)
        ours = [NAMES[n[2] % 12]
                for n in M.build_part(t1, s0, M.key_shift(h['transpose']))[0]]
        n = min(len(fw), len(ours))
        same = sum(1 for a, b in zip(fw, ours) if a == b)
        if n and same == n:
            tally['exact'] += 1
        else:
            tally['differs'] += 1
            bad.append((os.path.basename(f)[9:-4], h['transpose'],
                        M.key_shift(h['transpose']), same, n))
    print('cards whose key field is not zero, decoded against the firmware:')
    for k, v in tally.most_common():
        print('   %-12s %d' % (k, v))
    for name, raw, sh, same, n in bad[:10]:
        print('   %-46s field %-3d %+d  %d of %d' % (name[:46], raw, sh, same, n))


if __name__ == '__main__':
    P.run(main)
