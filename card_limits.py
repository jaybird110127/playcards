#!/usr/bin/env python3
"""
Will the UPA-01 cartridge accept this card?  Run its own parser and find out.

    python card_limits.py mycard.bin [more.bin ...]
    python card_limits.py card_side-a.bin card_side-b.bin
    python card_limits.py --sweep            # find the ceiling from scratch

WHOSE ANSWER THIS IS

The UPA-01's, and only its.  This tool executes that cartridge's own parse
routine out of its own ROM, so a verdict here is exactly what the 1985 MSX
cartridge does with the card - not a statement about the format, and not a
promise about a PC-100 or a PCS-30, whose readers are different code with
limits of their own that this project has never measured.

In practice it is still the check worth running, because the ceiling it finds
is roughly four times what the strip physically holds (see below), so a card
that fails here is malformed rather than merely large.  But if a card is
refused, the honest reading is "the cartridge refuses it".

Cards are fed in the order given INTO ONE READER, state and all, so a
two-sided pair is checked the way it is swiped.  That matters: a side B decodes
its section on top of what its side A left in the buffer, and handed one on its
own the firmware refuses it outright.

The parser's return codes, which are worth knowing:

    0x00  a complete one-sided card
    0x01  a side A - a type-1 card with no section; the reader is now armed
    0x02  a side B, completing the card and clearing the flag
    0x80  refused

No emulator involved.  z80run.py executes the real decode path out of the
cartridge ROM, so the answer is the firmware's own, and the run takes a second.

WHAT THE FIRMWARE ACTUALLY LIMITS

Not the size of the card on the strip - the size it decodes to in RAM.  A card
is read into a raw image at 0x8000 and then decoded into a second buffer at
0xD377, and it is that second buffer the firmware guards:

    6317  LD A,067h / SUB L / LD A,0E3h / SBC A,H / RET C     (duration tracks)
    64C8  LD A,067h / SUB L / LD A,0E3h / SBC A,H / RET C     (opcode streams)

Two hard-coded compares of the buffer pointer against **0xE367**, one checked on
every duration symbol and one on every opcode.  Past it, the decoder returns
with carry set, the section parse fails, and the card is refused with error
0x80.  Nothing is overwritten and nothing crashes: the cartridge's own parse
state begins at 0xE377, and the guard stops 16 bytes short of it.

    0xD377  decode buffer starts
    0xE367  the guard - 4080 bytes of room
    0xE377  the parse state the guard is protecting

So the ceiling is **4080 decoded bytes**.  The 264 original cards decode to
between 158 and 1361, so the largest of them uses a third of it, and at the
corpus's median expansion of 2.4x the ceiling is about a 1700-byte card -
roughly four times what the 433-byte magnetic strip physically holds.  The
strip runs out long before the firmware does.
"""

import argparse, os, sys

import playcard_decode as P
import playcard_resolve as R
from z80run import Z80, Unimplemented

ARMED = 0xE48B                 # set to 1 by a side A, required by a side B

# What the parser returns in A.  Anything else is a refusal.
ACCEPTED = {0x00: 'a complete one-sided card',
            0x01: 'a SIDE A - the reader is now armed for its side B',
            0x02: 'a SIDE B, completing the card'}
BUFFER = 0xD377                # where the decoded card is built
GUARD = 0xE367                 # the address both decoders refuse to pass
STATE = 0xE377                 # the parse state the guard protects
IMAGE = 0x8000                 # where the reader leaves the raw card image
CEILING = GUARD - BUFFER       # 4080 bytes


class Parser(Z80):
    """The cartridge's parser, reading its bits from an image in memory.

    0xE473 is the byte pointer, 0xE477 the byte being shifted, 0xE478 the bit
    count within it and 0xE479 the end of the image - the state the CR-01 loop
    leaves behind before handing over."""

    def __init__(self, rom):
        Z80.__init__(self, rom, 0x4000)
        self.top = 0

    def poke(self, a, v):
        a &= 0xFFFF
        Z80.poke(self, a, v)
        if BUFFER <= a < STATE and a > self.top:
            self.top = a


class Session:
    """One reader, fed cards in the order they are swiped.

    The state between swipes is the point of it.  A side A leaves three things
    behind: the armed flag at 0xE48B, the decode-buffer pointer at 0xE47B where
    its duration tracks stopped, and the bytes already in the buffer.  Its side
    B decodes its section on top of those, so checking one on its own image is
    meaningless - it would decode into whatever the pointer happened to hold.
    """

    def __init__(self):
        self.z = Parser(open(P.rom(), 'rb').read())

    def armed(self):
        return bool(self.z.mem[ARMED])

    def feed(self, data, limit=80000000):
        """Returns (return code, decoded bytes reached, why it stopped)."""
        z = self.z
        image = bytes([0, 0, 0, 1]) + data   # the reader writes its own preamble
        for i, b in enumerate(image):
            z.mem[IMAGE + i] = b
        lo, hi = IMAGE - 1, IMAGE + len(image) - 1
        z.mem[0xE473], z.mem[0xE474] = lo & 0xFF, lo >> 8
        z.mem[0xE478] = 8
        z.mem[0xE479], z.mem[0xE47A] = hi & 0xFF, hi >> 8
        z.sp = 0xEAF6
        why = ''
        try:
            z.call(0x65E3, limit=limit)      # past 8 + 25 bits of preamble
        except Unimplemented as e:
            why = str(e)
        except Exception as e:
            why = '%s: %s' % (type(e).__name__, e)
        code = 0xFF if why else z.reg['A']
        return code, max(0, z.top - BUFFER + 1), why


def run(data, limit=80000000):
    """One card into a fresh reader.  (accepted, bytes reached, why)."""
    code, reached, why = Session().feed(data, limit)
    return code in ACCEPTED, reached, why


def decoded_size(data):
    """What the card decodes to, from the resolver rather than the ROM."""
    h = P.parse_card(P.tobits(data))
    if h['type'] != 1:
        return None                    # a side B is only meaningful joined
    buf = R.Buf()
    R.emit_track(buf, h['track1'])
    R.emit_track(buf, h['track2'])
    if h['sections']:
        table, streams = h['sections'][0]
        R.emit_stream(buf, streams[0], table)
        R.emit_stream(buf, streams[1], table)
    return len(buf.b)


def check(session, path):
    data = P.check_card(path)
    kind = P.parse_card(P.tobits(data))['type']
    was_armed = session.armed()
    code, reached, why = session.feed(data)
    ok = code in ACCEPTED
    want = decoded_size(data)

    note = ''
    if kind == 2:
        # On its own line: the row above is a fixed-width table, and appending
        # to it is what pushes the whole thing past the terminal.
        note = 'a side B, into %s reader' % ('an armed' if was_armed else 'an UNARMED')
    print('%-46s %5d bytes on the strip'
          % (os.path.basename(path)[:46], len(data)))
    if note:
        P.say(note, prefix='   ')
    if want is not None:
        print('   decodes to %d bytes of the %d the firmware allows (%.0f%%)'
              % (want, CEILING, 100.0 * want / CEILING))
    if ok:
        print('   the UPA-01 ACCEPTS it: %s' % ACCEPTED[code])
    else:
        print('   the UPA-01 REFUSES it, error 0x%02X' % code)
        if reached >= CEILING - 8:
            print('   its decoder gave up with the buffer at 0x%04X, against '
                  'the guard at 0x%04X' % (BUFFER + reached - 1, GUARD))
        elif kind == 2 and not was_armed:
            P.say('a side B is refused unless a side A has been read first '
                  '(ROM 0x6606) - give them in order', prefix='   ')
    if why:
        print('   (the interpreter could not finish: %s)' % why)
    if len(data) > 433:
        print('   note: %d bytes will not fit the strip either, which holds 433'
              % len(data))
    print()
    return ok


def sweep():
    """Find the ceiling without being told it, by building longer and longer
    cards until the firmware stops accepting them."""
    import playcard_encode as E

    def card(n):
        return E.build(E.Card(
            tempo=15, rhythm=4, mel_voice=6, sustain=0, obb_voice=1, key=0,
            alphabet=(24, 0xE1), mel_durs=[24] * n, obb_durs=[24] * n,
            mel_ops=E.terminated([('note', 14)] * n),
            obb_ops=E.terminated([('note', 14)] * n), chart=[(0x0E, 1)]))

    lo, hi = 8, 2000
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if run(card(mid))[0]:
            lo = mid
        else:
            hi = mid
    a, b = card(lo), card(hi)
    print('largest card the firmware accepts : %4d notes a part, %4d bytes, '
          'decoding to %d' % (lo, len(a), decoded_size(a)))
    print('smallest it refuses               : %4d notes a part, %4d bytes, '
          'decoding to %d' % (hi, len(b), decoded_size(b)))
    print()
    print('which puts the ceiling at %d decoded bytes - the guard at 0x%04X, '
          '%d bytes\n   above the buffer at 0x%04X and %d below the parse state '
          'at 0x%04X.' % (CEILING, GUARD, CEILING, BUFFER, STATE - GUARD, STATE))


def main():
    ap = argparse.ArgumentParser(
        description="Run the cartridge's own parser over a card image.")
    ap.add_argument('cards', nargs='*')
    ap.add_argument('--sweep', action='store_true',
                    help='find the size ceiling by bisection')
    a = ap.parse_args()
    if a.sweep:
        return sweep()
    if not a.cards:
        ap.print_help()
        return
    session = Session()
    bad = 0
    for f in a.cards:
        if not check(session, f):
            bad += 1
    if bad:
        sys.exit(bad)


if __name__ == '__main__':
    try:
        main()
    except P.Missing as e:
        # This tool runs the cartridge's OWN parser, so there is no doing it
        # without the cartridge.  Say so rather than showing a traceback.
        sys.exit(str(e))
