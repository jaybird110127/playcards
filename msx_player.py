#!/usr/bin/env python3
"""Play a Playcard on an emulated CX5M, in Python, with no emulator installed.

    python msx_player.py card.bin                  # play it, report what sounded
    python msx_player.py card.bin --seconds 40
    python msx_player.py card.bin --log out.fmlog  # the raw register capture
    python msx_player.py --roms                    # check the ROMs are present

THE ROMS IT NEEDS

Three, all Yamaha's and none of them in this repository.  They go in `Roms/`,
or wherever `PLAYCARD_ROMS` points:

    cx5m_basic-bios1.rom                                32768 bytes
        The CX5M's BIOS and BASIC.  The machine is booted from reset, so this
        is what brings it up and calls each cartridge's INIT.

    SFG01.ROM                                           65536 bytes
        The SFG-01 FM module: its BIOS and the YM2151 behind it.  A 16K ROM
        mirrored four times across its slot, which is not incidental - see
        "how the cartridge reaches the FM chip" below.  SFG05.rom carries the
        same "MCHFM0" signature and should work, but is untested here.

    Play Card System (UPA-01) (1985) (Yamaha) (J).rom   16384 bytes
        The Play Card cartridge itself.  This one is already what the rest of
        the tools use, through playcard_decode.rom().

`python msx_player.py --roms` says which are present and which are not.

WHAT A CAPTURE FROM THIS IS EVIDENCE OF

One machine.  What comes out is the UPA-01 cartridge's rendering of the card on
an SFG-01's YM2151 - not "how a Playcard sounds", and not what the PC-100 these
cards were written for would make of the same bytes.  That cartridge is a 1985
port with known bugs: it drops chord notes, gives every drum fill a fixed feel
instead of the rhythm's, and falls silent on a same-root chart entry.

Which is still enormously useful, because for anything the card TELLS the
machine to do, this is Yamaha's own code doing the reading and nothing here
understands the format.  Just keep the two apart: a capture settles what the
card asked for, and only suggests what any other instrument would play.

WHY

Every measurement of what a card SOUNDS like has gone through openMSX: a real
emulator driven by a Tcl script, with breakpoints standing in for the CR-01
reader.  It works, but it puts a large moving part between the question and the
answer, it cannot be stepped or inspected from Python, and its timing is not
ours to control - which matters, because the cartridge's sequencer wants 100
ticks a second and no MSX VDP delivers that (see "The cartridge's sequencer
ticks at 100 a second" in playcard-format.md).  Here the tick rate is an
argument.

WHAT IS EMULATED

Only what the cartridge touches, which is not much:

  * the Z80, out of `z80run.py`
  * the primary slot register on port 0xA8, and four 16K pages
  * the keyboard matrix on ports 0xAA/0xA9, enough to press a key
  * the VDP's two ports, as a sink with a working vblank flag - nothing reads
    video back except the interrupt gate at 0x7DD1
  * the PSG's three ports, recorded rather than synthesised
  * the SFG-01's YM2151 at 0x3FF0/0x3FF1, recorded the same way

and the card reader, which is not emulated at all: the two ROM routines that
read a bit from the CR-01 are intercepted and answered from the card image,
exactly as the openMSX harness does it with breakpoints.

The interrupt is asserted by hand at whatever rate is asked for, so a run is
deterministic: the same card gives the same capture, byte for byte, every time.
That also fixes the tempo for free: the sequencer wants 100 ticks a second and
gets exactly that, instead of the 50 a PAL VDP delivers.

WHAT WORKS

    the machine boots                    BIOS, then both cartridge INITs
    the FM module is found and started   "MCHFM0" at 0x0080 names its slot
    F1 reads the card                    through the cartridge's own UI, all
                                         of it, decoded by the ROM into 0xD377
    F2 starts the player                 the FM driver runs and keys notes

Two pieces of hardware had to be right before any of that worked, and both are
worth knowing:

  * **The SFG answers across its whole slot**, the same 16K four times over.
    Its YM2151 is at 0x3FF0, in PAGE 0, while its ROM is read at 0x4000 in page
    1 - and the cartridge finds the FM module by hunting for the signature
    "MCHFM0" at 0x0080.  Mapped only at 0x4000 it is invisible, and the machine
    boots to a cartridge that can make no sound.

  * **The YM2151's timer A is programmed at 109.24 Hz** (register 0x14 = 0x3F
    starts both timers with their interrupts enabled).  That is the clock the
    music was meant to run on, and it is why a card plays at half speed under
    an emulator that only supplies the VDP's 50.

HOW THE CARTRIDGE REACHES THE FM CHIP

It never writes the YM2151 itself - there is not one 0x3FF0 in its 16K.  Its
INIT hunts every slot for the signature "MCHFM0" at 0x0080, and when it finds it
**deliberately leaves page 0 mapped to the SFG** (0x40B3 jumps over the restore).
From then on the SFG's BIOS entry points sit at 0x0090, 0x009C and friends, its
YM2151 at 0x3FF0, and the cartridge simply CALLs them.

Three things had to be right before a note would sound, and each was invisible
until it was wrong:

  * **The SFG answers across its whole slot**, the same 16K four times over, so
    the signature is readable at 0x0080 and the chip at 0x3FF0 while the ROM is
    read at 0x4000.
  * **The YM2151's status is read from the DATA port, 0x3FF1**, not the address
    port.  Published to the wrong one, the FM module's self-check never sees its
    timer flags, decides the chip is dead, and the cartridge comes up PAUSED -
    silently, with everything else working.
  * **LD A,I has to set P/V from IFF2.**  The ROM uses the standard
    "LD A,I / PUSH AF / DI ... POP AF / RET PO" idiom, so a no-op version
    restores interrupts to OFF for ever and the music stops after one note.

WHERE THE PAUSE FLAG COMES FROM

Worth knowing, because it is where a silent card will send you.  The frame
handler at 0x4813 is a rate divider: it calls one handler every frame, then runs
a second handler as many times as a table at 0xCC6B says for this frame - which
is how a tick rate that is not a multiple of the frame rate is made.  All of that
is skipped when the gate at 0xCC6A is non-zero.  The gate is set from 0xCC55,
and 0xCC55 is **the return value of command 0**, the FM voice load.  So a
cartridge that cannot see its FM module does not complain: it just never plays.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playcard_decode as P
from z80run import Z80, Unimplemented

ROMS = P.ROM_DIR
BIOS = 'cx5m_basic-bios1.rom'
SFG = 'SFG01.ROM'

# name -> (expected size, what it is for).  The size is a sanity check rather
# than a hash: a differently sized file is a different dump and the slot
# mapping here would be wrong for it.
NEEDED = [
    (BIOS, 32768, "the CX5M's BIOS and BASIC, to boot the machine"),
    (SFG, 65536, 'the SFG-01 FM module, mirrored across its slot'),
    (P.CART_ROM, 16384, 'the Play Card cartridge'),
]


def rom_report():
    """[(name, path, present, size, note)] for every ROM this needs."""
    out = []
    for name, size, note in NEEDED:
        path = os.path.join(ROMS, name)
        have = os.path.isfile(path)
        got = os.path.getsize(path) if have else 0
        out.append((name, path, have, got, size, note))
    return out


def check_roms():
    """Raise P.Missing naming everything absent, rather than dying on open()."""
    missing = [r for r in rom_report() if not r[2]]
    if not missing:
        return
    lines = ['msx_player.py needs ROM images that are not in this repository.',
             'They are Yamaha\'s. Put them in %s,' % ROMS,
             'or set PLAYCARD_ROMS to the folder holding them.', '']
    for name, path, have, got, want, note in missing:
        lines.append('   missing: %-52s %6d bytes  (%s)' % (name, want, note))
    raise P.Missing('\n'.join(lines))

SLOT_BIOS, SLOT_CART, SLOT_SFG, SLOT_RAM = 0, 1, 2, 3

# The two routines that fetch a bit from the reader.  The ROM asks the hardware
# whether a bit is ready at 0x6892 and takes it at 0x68B2; both are answered
# here and skipped, which is what the openMSX harness does with breakpoints.
CR01_POLL, CR01_POLL_RET = 0x6892, 0x6895
CR01_BIT, CR01_BIT_RET = 0x68B2, 0x68B5

OPM_BASE = 0x3FF0                      # the SFG's registers, in ITS page 0

# MSX key matrix: row 6 bit 5 is F1, bit 6 is F2.
KEY = {'F1': (6, 0x20), 'F2': (6, 0x40), 'F3': (6, 0x80),
       'F4': (7, 0x01), 'F5': (7, 0x02), 'RETURN': (7, 0x80), 'SPACE': (8, 0x01)}


class CX5M(Z80):
    """A Yamaha CX5M with the Play Card cartridge in it."""

    def __init__(self, card=b'', trailer=4000):
        check_roms()
        Z80.__init__(self)
        self.trace = False                       # no per-write log; far too big

        self.rom = {}
        self.rom[SLOT_BIOS] = self._image(BIOS, 0x0000)
        self.rom[SLOT_CART] = self._image(P.CART_ROM, 0x4000)
        self.rom[SLOT_SFG] = self._mirror(SFG)
        self.ram = bytearray(0x10000)

        # which slot each 16K page is reading, and whether it is writable
        self.page = [SLOT_BIOS, SLOT_BIOS, SLOT_RAM, SLOT_RAM]
        self.writable = [False, False, True, True]
        for i in range(4):
            self._map(i, self.page[i], force=True)

        self.keys = [0xFF] * 16                  # the matrix, 1 = not pressed
        self.krow = 0
        self.vdp_flag = False
        self.opm = []                            # (tick, register, value)
        self.psg = []                            # (tick, register, value)
        self.opmreg = 0
        self.tick = 0

        # The YM2151's timers.  The SFG starts both with IRQ enabled (register
        # 0x14 = 0x3F) and drives the music off timer A: without it the FM
        # driver never advances and a card sounds one note and stops.
        self.clka = 0
        self.clkb = 0
        self.t_load = 0
        self.t_irqen = 0
        self.opm_status = 0
        self.timer_a_hits = 0

        self.bits = ''.join(format(b, '08b') for b in card) + '0' * trailer
        self.bitpos = 0
        self.card_done = False

    # ---------------------------------------------------------- memory
    def _image(self, name, at, limit=None):
        data = open(os.path.join(ROMS, name), 'rb').read()  # checked by check_roms
        if limit:
            data = data[:limit]
        buf = bytearray(0x10000)
        buf[at:at + len(data)] = data
        return buf

    def _mirror(self, name):
        """The SFG answers across its whole slot, the same 16K four times over.

        That is not a convenience: its YM2151 sits at 0x3FF0, in PAGE 0, while
        its ROM is read at 0x4000 in page 1, and the cartridge hunts for the
        signature "MCHFM0" at 0x0080 to find which slot the FM module is in.
        A 16K image mapped only at 0x4000 is invisible to that search."""
        data = open(os.path.join(ROMS, name), 'rb').read()[:0x4000]
        buf = bytearray()
        for _ in range(4):
            buf += data
        return buf

    def _map(self, page, slot, force=False):
        """Point one 16K page at a slot, saving the RAM it is leaving."""
        if not force and self.page[page] == slot:
            return
        lo, hi = page * 0x4000, (page + 1) * 0x4000
        if self.page[page] == SLOT_RAM:
            self.ram[lo:hi] = self.mem[lo:hi]
        src = self.ram if slot == SLOT_RAM else self.rom.get(slot)
        self.mem[lo:hi] = src[lo:hi] if src else bytearray(0x4000)
        self.page[page] = slot
        self.writable[page] = (slot == SLOT_RAM)
        if page == 0 and slot == SLOT_SFG:
            self.publish_status()

    def poke(self, a, v):
        a &= 0xFFFF
        page = a >> 14
        if page == 0 and self.page[0] == SLOT_SFG and OPM_BASE <= a <= OPM_BASE + 7:
            if a == OPM_BASE:
                self.opmreg = v & 0xFF
            elif a == OPM_BASE + 1:
                # timestamped by instruction count, not by frame: a capture is
                # meant to be rendered to audio, and one frame of resolution
                # would quantise every note onset onto a 20 ms grid
                self.opm.append((self.steps, self.opmreg, v & 0xFF))
                self.opm_write(self.opmreg, v & 0xFF)
            return
        if self.writable[page]:
            self.mem[a] = v & 0xFF

    # ---------------------------------------------------------- the OPM timers
    CLOCK = 3579545.0                   # the YM2151's own clock
    CYCLES_PER_INSTRUCTION = 4.0        # a rough Z80 average, good enough here

    def opm_write(self, reg, val):
        if reg == 0x10:
            self.clka = (self.clka & 3) | (val << 2)
        elif reg == 0x11:
            self.clka = (self.clka & ~3) | (val & 3)
        elif reg == 0x12:
            self.clkb = val
        elif reg == 0x14:
            self.t_load = val & 3
            self.t_irqen = (val >> 2) & 3
            if val & 0x10:
                self.opm_status &= ~1
            if val & 0x20:
                self.opm_status &= ~2
            self.publish_status()

    def timer_a_instructions(self):
        """How many instructions one timer-A period lasts."""
        period = 64.0 * (1024 - self.clka) / self.CLOCK
        return max(1, int(period * self.CLOCK / self.CYCLES_PER_INSTRUCTION))

    def timer_a_hz(self):
        return self.CLOCK / (64.0 * (1024 - self.clka)) if self.clka < 1024 else 0.0

    def publish_status(self):
        """Put the status byte where the driver actually reads it.

        On a YM2151 the status comes back from the DATA port, not the address
        port: the SFG's own code reads 0x3FF1.  Publishing to 0x3FF0 instead
        means the FM module's self-check never sees its timer flags, reports
        the chip dead, and the cartridge starts up PAUSED."

        Writing it into the page rather than intercepting reads keeps `peek` on
        its fast path, which matters: the machine executes tens of millions of
        instructions for one card."""
        if self.page[0] == SLOT_SFG:
            self.mem[OPM_BASE + 1] = self.opm_status

    def fire_timer_a(self):
        self.opm_status |= 1
        self.timer_a_hits += 1
        self.publish_status()
        if self.t_irqen & 1:
            return self.interrupt()
        return False

    # ---------------------------------------------------------- ports
    def port_out(self, port, value):
        port &= 0xFF
        if port == 0xA8:                          # primary slot select
            for page in range(4):
                self._map(page, (value >> (page * 2)) & 3)
            return
        if port == 0xAA:                          # keyboard row + misc
            self.krow = value & 0x0F
            return
        if port == 0xA0:
            self.psgreg = value & 0x0F
            return
        if port == 0xA1:
            self.psg.append((self.tick, getattr(self, 'psgreg', 0), value & 0xFF))
            return
        # the VDP and everything else is a sink

    def port_in(self, port):
        port &= 0xFF
        if port == 0xA8:
            return sum(self.page[p] << (p * 2) for p in range(4))
        if port == 0xA9:                          # the selected keyboard row
            return self.keys[self.krow & 0x0F]
        if port == 0x99:                          # VDP status: bit 7 is vblank
            v = 0x80 if self.vdp_flag else 0x00
            self.vdp_flag = False                 # reading it clears it
            return v
        if port == 0x98:
            return 0xFF
        if port == 0xA2:
            return 0xFF
        return 0xFF

    # ---------------------------------------------------------- the reader
    def feed(self):
        """Answer the two CR-01 routines from the card image.

        Gated on the cartridge actually being paged in, or the same addresses
        in the BASIC ROM would be hijacked whenever BASIC ran through them."""
        if self.page[1] != SLOT_CART:
            return False
        if self.pc == CR01_POLL:
            self.reg['A'] = 0x80 if self.bitpos < len(self.bits) else 0x00
            self.pc = CR01_POLL_RET
            return True
        if self.pc == CR01_BIT:
            if self.bitpos >= len(self.bits):
                self.reg['A'] = 0x00
                self.card_done = True
            else:
                b = self.bits[self.bitpos]
                self.bitpos += 1
                self.reg['A'] = 0xC0 | (0x20 if b == '1' else 0x00)
            self.pc = CR01_BIT_RET
            return True
        return False

    # ---------------------------------------------------------- keys
    def press(self, name):
        row, mask = KEY[name]
        self.keys[row] &= ~mask & 0xFF

    def release(self, name):
        row, mask = KEY[name]
        self.keys[row] |= mask

    # ---------------------------------------------------------- running
    # ---------------------------------------------------------- running
    SENTINEL = 0xF00D

    def call_rom(self, addr, a=0, limit=8000000):
        """Call a cartridge routine and run until it returns."""
        self._map(1, SLOT_CART)
        self.sp = (self.sp - 2) & 0xFFFF
        self.mem[self.sp] = self.SENTINEL & 0xFF
        self.mem[self.sp + 1] = self.SENTINEL >> 8
        self.reg['A'] = a
        self.pc = addr
        n = 0
        while n < limit and self.pc != self.SENTINEL:
            self.feed()
            self.step()
            n += 1
        return n

    def boot(self, steps=2500000, every=40000):
        """Reset, let the BIOS come up and initialise both cartridges.

        `every` is how many instructions between interrupts during boot; it
        only has to be in the right ballpark for the BIOS to make progress."""
        self.pc = 0x0000
        self.sp = 0xF000
        for n in range(1, steps + 1):
            self.feed()
            self.step()
            if n % every == 0:
                self.vdp_flag = True
                self.interrupt()
        return steps

    def read_card(self):
        """Have the firmware read the card, exactly as a swipe would.

        Operation 1 of the dispatcher at 0x66AF. The bits come from the image
        through `feed`, the firmware decodes them into its buffer at 0xD377,
        and nothing here parses anything: the card is understood by the ROM."""
        n = self.call_rom(0x66AF, 1)
        return n, self.bitpos

    def setup_voices(self):
        """Command 0 of the dispatcher at 0x4850: load the FM voices."""
        before = len(self.opm)
        self.call_rom(0x4850, 0)
        return len(self.opm) - before

    def run(self, seconds, vdp_hz=50.0):
        """Run the machine for `seconds` of emulated time.

        Two interrupt sources share the Z80's one INT line, as they do in the
        machine: the VDP at its frame rate, and the YM2151's timer A at
        whatever the SFG programmed - about 109 Hz.  The sequencer rides the
        second of those, which is why it plays at half speed under an emulator
        that only supplies the first."""
        per_instruction = self.CYCLES_PER_INSTRUCTION / self.CLOCK
        total = int(seconds / per_instruction)
        vdp_every = int((1.0 / vdp_hz) / per_instruction)
        a_every = self.timer_a_instructions() if self.clka else 0
        n = 0
        next_vdp = vdp_every
        next_a = a_every if a_every else total + 1
        while n < total:
            self.feed()
            self.step()
            n += 1
            if n >= next_vdp:
                next_vdp += vdp_every
                self.tick += 1
                self.vdp_flag = True
                self.interrupt()
            if n >= next_a:
                next_a += a_every
                self.fire_timer_a()
        return n

    def run_ticks(self, ticks, instructions=9000):
        """Tick the cartridge's frame state machine `ticks` times.

        One tick is one pass of 0x431F, which is one step of the sequencer, so
        the tempo is set here rather than by a video standard: the firmware
        wants 100 a second."""
        taken = 0
        for _ in range(ticks):
            self.tick += 1
            self.vdp_flag = True
            if self.interrupt():
                taken += 1
            for _ in range(instructions):
                self.feed()
                self.step()
        return taken

    def seconds(self, steps):
        """An instruction count as emulated seconds."""
        return steps * self.CYCLES_PER_INSTRUCTION / self.CLOCK

    def keyons(self):
        """[(seconds, channel)] for every note struck."""
        return [(self.seconds(t), v & 7) for t, r, v in self.opm
                if r == 8 and (v >> 3) & 0x0F]


def main():
    ap = argparse.ArgumentParser(description='Play a Playcard in pure Python.')
    ap.add_argument('card', nargs='?')
    ap.add_argument('--roms', action='store_true',
                    help='report which ROM images are present, and stop')
    ap.add_argument('--seconds', type=float, default=12.0,
                    help='emulated seconds to play after starting')
    ap.add_argument('--vdp-hz', type=float, default=50.0)
    ap.add_argument('--log', help='write the register capture here')
    a = ap.parse_args()

    if a.roms:
        print('ROM images, looked for in %s' % ROMS)
        for name, path, have, got, want, note in rom_report():
            state = ('present' if got == want else
                     'PRESENT, but %d bytes not %d' % (got, want)) if have else 'MISSING'
            print('   %-52s %s' % (name, state))
            print('        %s' % note)
        return
    if not a.card:
        ap.error('give a card image, or --roms')

    try:
        m = CX5M(P.check_card(a.card))
    except P.Missing as e:
        sys.exit(str(e))
    except IOError as e:
        sys.exit('cannot read the card: %s' % e)
    print('%s' % os.path.basename(a.card))
    m.boot(steps=8000000)
    print('  booted, FM initialised with %d register writes' % len(m.opm))
    print('  YM2151 timer A programmed at %.2f Hz' % m.timer_a_hz())

    m.run(1.0, a.vdp_hz)
    m.press('F1'); m.run(0.4, a.vdp_hz); m.release('F1')
    m.run(6.0, a.vdp_hz)
    print('  F1: card read, %d of %d bits, buffer starts %s'
          % (m.bitpos, len(m.bits),
             ' '.join('%02X' % b for b in m.mem[0xD377:0xD383])))

    before = len(m.opm)
    m.press('F2'); m.run(0.4, a.vdp_hz); m.release('F2')
    m.run(a.seconds, a.vdp_hz)
    keys = m.keyons()
    print('  F2: %d FM register writes, %d key-ons on channels %s'
          % (len(m.opm) - before, len(keys),
             sorted(set(ch for t, ch in keys)) or '-'))
    if len(keys) < 8:
        print()
        print('  Almost nothing sounded. The usual cause is the FM module not')
        print('  being seen - check the gate at 0xCC6A, the return value of')
        print('  command 0, which is non-zero when the chip looks dead.')
    if a.log:
        with open(a.log, 'w') as f:
            for t, r, v in m.opm:
                f.write('%.6f %02X %02X' % (m.seconds(t), r, v) + chr(10))
        print('  capture written to %s (%d writes)' % (a.log, len(m.opm)))


if __name__ == '__main__':
    P.run(main)
