# -*- coding: utf-8 -*-
"""Does anything ever consume the third part's level byte?

    python sweep_block2.py            the whole corpus
    python sweep_block2.py edelweiss  just the cards whose name matches

The cartridge keeps three per-part parameter blocks of stride 0x25:

    block 0  base 0xD2DC  level 0xD2FF   the melody
    block 1  base 0xD301  level 0xD324   the obbligato
    block 2  base 0xD326  level 0xD349   a third part, never identified

Both duck opcodes write blocks 1 and 2 in step, so for a long time it looked as
though some third voice was being ducked along with the obbligato and we had
simply not found it.  Writes are not the question.  The question is whether
block 2 is ever READ, and this answers it by running every card on the C
emulator with `--watch` on both blocks and counting.

The consumer is one instruction, `LD B,(HL)` at 0x5E2E, with HL = block + 0x23;
the watch reports its PC as 0x5E2F, where the Z80 sits while the operand is
fetched.  Reads at 0369, 036C, 7D61, 7D64 are the BIOS sizing RAM at boot and
reads at 5C88 are the cartridge's zero-fill - none of them a consumer, so they
are excluded.

The answer, on all 261 cards: zero.  See "The third block is written and never
read" in playcard-format.md.
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playcard_decode as P

CARDS = 'Original Playcards'
EXE = os.path.join('csrc', 'playcard.exe')
PUMP = '5E2F'                      # the parameter pump's read of +0x23

# Reads that are not anybody consuming a level: the BIOS sizing RAM at boot,
# and the cartridge's zero-fill (an LDIR, which reads the byte it just wrote).
BOOT = set(['0369', '036C', '7D61', '7D64', '5C88'])
BLOCK2 = set(['D349', 'D326'])
# The two duck handlers: 0x13 restores the level, 0x14 reduces it.
DUCKPC = set(['5FAA', '5FBF'])
WATCH = ['0xD2FF', '0xD324', '0xD349', '0xD326', '0xD301']
NAMES = {'D2FF': 'melody', 'D324': 'obbligato', 'D349': 'third',
         'D326': 'third+0', 'D301': 'obb+0'}

tmp = os.environ.get('TEMP', '.')
watchfile = os.path.join(tmp, 'sweep.watch')


def run(path):
    cmd = [EXE, path, '--watch-out', watchfile]
    for w in WATCH:
        cmd += ['--watch', w]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    out = p.stdout + p.stderr
    keyons = re.search(r'([\d]+) key-ons', out)
    ended = re.search(r'ended after ([\d.]+) s', out)
    reads, writes, pumped, live = {}, {}, {}, {}
    if os.path.exists(watchfile):
        for line in open(watchfile):
            f = line.split()
            if len(f) < 5:
                continue
            addr, kind, pc = f[1], f[2], f[4][3:]
            if kind == 'R':
                reads[addr] = reads.get(addr, 0) + 1
                if pc == PUMP:
                    pumped[addr] = pumped.get(addr, 0) + 1
                if pc not in BOOT:
                    live.setdefault(addr, {})
                    live[addr][pc] = live[addr].get(pc, 0) + 1
            else:
                writes[addr] = writes.get(addr, 0) + 1
                if pc in DUCKPC:
                    writes['duck'] = writes.get('duck', 0) + 1
        os.remove(watchfile)
    return (int(keyons.group(1)) if keyons else 0,
            float(ended.group(1)) if ended else None,
            reads, writes, pumped, live, p.returncode, out)


def main():
    names = sorted(n for n in os.listdir(CARDS) if n.lower().endswith('.bin'))
    if len(sys.argv) > 1:
        names = [n for n in names if sys.argv[1] in n]
    hits, dead, failed, ducked = [], 0, [], 0
    print('%-60s %7s %6s %7s %8s' % ('card', 'key-ons', 'ducks', 'obb rd', 'third rd'))
    for n in names:
        try:
            r = run(os.path.join(CARDS, n))
        except subprocess.TimeoutExpired:
            failed.append((n, 'timed out'))
            continue
        keyons, ended, reads, writes, pumped, live, rc, out = r
        third = sum(sum(pcs.values()) for a, pcs in live.items() if a in BLOCK2)
        obb = pumped.get('D324', 0)
        ducks = writes.get('duck', 0)
        if keyons == 0:
            failed.append((n, 'no note played (rc=%d)' % rc))
            print('%-60s %7s' % (n[:60], 'FAILED'))
            sys.stdout.flush()
            continue
        if ducks:
            ducked += 1
        if third:
            hits.append((n, live, obb, ducks))
        else:
            dead += 1
        print('%-60s %7d %6d %7d %8d%s'
              % (n[:60], keyons, ducks, obb, third, '  <-- READ' if third else ''))
        sys.stdout.flush()

    played = len(names) - len(failed)
    print('')
    print('%d cards played, %d of them ducked at all' % (played, ducked))
    if hits:
        print('BLOCK 2 READ by live code on %d cards:' % len(hits))
        for n, live, o, d in hits:
            for a in sorted(live):
                if a in BLOCK2:
                    print('   %-52s %s %s' % (n[:52], a, live[a]))
    else:
        print('block 2 was read by live code on NO card (%d checked)' % played)
    if failed:
        print('%d cards did not play:' % len(failed))
        for n, why in failed:
            print('   %-58s %s' % (n[:58], why))


if __name__ == '__main__':
    P.run(main)
