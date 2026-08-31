#!/usr/bin/env python3
"""A small Z80 interpreter - enough to execute routines out of these ROMs.

The companion to `z80dis.py`: that one reads code, this one runs it.  Written
because some questions about a firmware are answered far more cheaply by
executing a subroutine with a made-up machine state than by reading a
disassembly and hoping every jump target was followed correctly.

MACHINE-NEUTRAL: it is a CPU, not a Playcard tool.  It has been run against
both the UPA-01 cartridge and the PCS-30 keyboard ROM, and whose code is in the
image is the caller's business.  "Silent" and "silently" below mean an
instruction quietly doing the wrong thing, not an instrument going quiet.

    import z80run
    cpu = z80run.Z80(rom, base=0)
    cpu.reg['E'] = 5
    cpu.call(0x2AEC, stop=0x2A67)
    print(cpu.peek(0x80CF))

RAM is a flat 64K overlay: reads fall through to the ROM image where one is
mapped and to RAM elsewhere, writes always go to RAM.  Unimplemented opcodes
raise rather than being silently skipped, which is the whole point - a wrong
answer from a quietly ignored instruction would be worse than no answer.
"""


class Unimplemented(Exception):
    pass


R8 = ['B', 'C', 'D', 'E', 'H', 'L', '(HL)', 'A']
RP = ['BC', 'DE', 'HL', 'SP']


class Z80(object):
    def __init__(self, rom=b'', base=0x0000):
        self.mem = bytearray(0x10000)
        if rom:
            self.mem[base:base + len(rom)] = rom
        self.rom_lo, self.rom_hi = base, base + len(rom)
        self.reg = dict(A=0, B=0, C=0, D=0, E=0, H=0, L=0, F=0)
        self.alt = dict(A=0, B=0, C=0, D=0, E=0, H=0, L=0, F=0)   # the shadow set
        self.ix = 0
        self.iy = 0
        self.sp = 0xFFFE
        self.pc = 0
        self.steps = 0
        self.writes = []          # (pc, addr, value), in order
        self.trace = True         # False stops recording writes, for long runs
        self.iff = 0              # interrupts enabled (IFF1)
        self.iff2 = 0             # the copy LD A,I reports in P/V
        self.i = 0
        self.r = 0
        self.im = 1
        self.halted = False
        self.ports = {}           # port -> value, for the default IN

    # ---- memory -------------------------------------------------------
    def peek(self, a):
        return self.mem[a & 0xFFFF]

    def poke(self, a, v):
        a &= 0xFFFF
        self.mem[a] = v & 0xFF
        if self.trace:
            self.writes.append((self.pc, a, v & 0xFF))

    # ---- the outside world -------------------------------------------
    # A bare Z80 has none; a machine subclasses these.  IN returns 0xFF, which
    # is what an unconnected bus reads on real hardware.
    def port_in(self, port):
        return self.ports.get(port & 0xFF, 0xFF)

    def port_out(self, port, value):
        self.ports[port & 0xFF] = value & 0xFF

    def interrupt(self):
        """Assert INT.  Returns True if the CPU took it.

        Only IM 1 is implemented, which is what an MSX uses: push PC and jump to
        0x0038.  A HALT is released whether or not interrupts are enabled."""
        if self.halted:
            self.halted = False
            self.pc = (self.pc + 1) & 0xFFFF
        if not self.iff:
            return False
        self.iff = self.iff2 = 0
        self.sp = (self.sp - 2) & 0xFFFF
        self.poke(self.sp, self.pc & 0xFF)
        self.poke(self.sp + 1, self.pc >> 8)
        self.pc = 0x0038
        return True

    def peek16(self, a):
        return self.peek(a) | (self.peek(a + 1) << 8)

    # ---- register pairs ----------------------------------------------
    def get_rp(self, n):
        if n == 3:
            return self.sp
        hi, lo = RP[n][0], RP[n][1]
        return (self.reg[hi] << 8) | self.reg[lo]

    def set_rp(self, n, v):
        v &= 0xFFFF
        if n == 3:
            self.sp = v
            return
        hi, lo = RP[n][0], RP[n][1]
        self.reg[hi], self.reg[lo] = v >> 8, v & 0xFF

    def get_r(self, n):
        if n == 6:
            return self.peek(self.get_rp(2))
        return self.reg[R8[n]]

    def set_r(self, n, v):
        v &= 0xFF
        if n == 6:
            self.poke(self.get_rp(2), v)
        else:
            self.reg[R8[n]] = v

    # ---- flags (S Z - H - P/V N C in bits 7..0) -----------------------
    def _sz(self, v):
        self.reg['F'] = (self.reg['F'] & 0x01) | (0x40 if v == 0 else 0) | (v & 0x80)

    def cond(self, n):
        f = self.reg['F']
        z, c = bool(f & 0x40), bool(f & 0x01)
        p, s = bool(f & 0x04), bool(f & 0x80)
        return [not z, z, not c, c, not p, p, not s, s][n]

    def _sub(self, v, store=True):
        a = self.reg['A']
        r = (a - v) & 0xFF
        f = (r & 0x80) | (0x40 if r == 0 else 0) | 0x02
        if a < v:
            f |= 0x01
        if ((a ^ v) & (a ^ r)) & 0x80:
            f |= 0x04
        self.reg['F'] = f
        if store:
            self.reg['A'] = r

    def _adc(self, v):
        self._add(v + (self.reg['F'] & 1))

    def _sbc(self, v, store=True):
        """SBC A,r - subtract with borrow.  The cartridge uses it at 0x6231 to
        compare the card-image pointer against the end of the image, which is
        the one bounds check anywhere in the read path."""
        a = self.reg['A']
        c = self.reg['F'] & 1
        r = (a - v - c) & 0xFF
        f = (r & 0x80) | (0x40 if r == 0 else 0) | 0x02
        if a < v + c:
            f |= 0x01
        if ((a ^ v) & (a ^ r)) & 0x80:
            f |= 0x04
        self.reg['F'] = f
        if store:
            self.reg['A'] = r

    def _add(self, v):
        a = self.reg['A']
        r = a + v
        f = (r & 0x80) | (0x40 if (r & 0xFF) == 0 else 0)
        if r > 0xFF:
            f |= 0x01
        self.reg['F'] = f
        self.reg['A'] = r & 0xFF

    def _logic(self, v, op):
        a = self.reg['A']
        r = {'and': a & v, 'or': a | v, 'xor': a ^ v}[op]
        self.reg['A'] = r
        par = bin(r).count('1') % 2 == 0
        self.reg['F'] = (r & 0x80) | (0x40 if r == 0 else 0) | (0x04 if par else 0)

    # ---- run ----------------------------------------------------------
    def _index(self, prefix, imm8, imm16, push, pop):
        """DD/FD: the same instruction set with IX or IY standing in for HL.

        Only the forms these ROMs use are here.  An unimplemented one raises
        rather than being taken as the HL version, which would be a silent
        wrong answer."""
        name = 'ix' if prefix == 0xDD else 'iy'
        idx = getattr(self, name)
        op = imm8()

        def addr():                       # (IX+d), d signed
            d = imm8()
            return (idx + (d - 256 if d > 127 else d)) & 0xFFFF

        if op == 0x21:                                   # LD IX,nn
            setattr(self, name, imm16()); return
        if op == 0x22:                                   # LD (nn),IX
            a = imm16()
            self.poke(a, idx & 0xFF); self.poke(a + 1, idx >> 8); return
        if op == 0x2A:                                   # LD IX,(nn)
            setattr(self, name, self.peek16(imm16())); return
        if op == 0x23:                                   # INC IX
            setattr(self, name, (idx + 1) & 0xFFFF); return
        if op == 0x2B:                                   # DEC IX
            setattr(self, name, (idx - 1) & 0xFFFF); return
        if op == 0xE5:                                   # PUSH IX
            push(idx); return
        if op == 0xE1:                                   # POP IX
            setattr(self, name, pop()); return
        if op == 0xE9:                                   # JP (IX)
            self.pc = idx; return
        if op == 0xF9:                                   # LD SP,IX
            self.sp = idx; return
        if (op & 0xCF) == 0x09:                          # ADD IX,rp
            n = (op >> 4) & 3
            v = idx if n == 2 else self.get_rp(n)
            r = idx + v
            setattr(self, name, r & 0xFFFF)
            self.reg['F'] = (self.reg['F'] & 0xC4) | (0x01 if r > 0xFFFF else 0)
            return
        if op == 0x36:                                   # LD (IX+d),n
            a = addr(); self.poke(a, imm8()); return
        if op == 0x34 or op == 0x35:                     # INC/DEC (IX+d)
            a = addr()
            v = self.peek(a)
            v = (v + 1) & 0xFF if op == 0x34 else (v - 1) & 0xFF
            self.poke(a, v)
            self._sz(v)
            if op != 0x34:
                self.reg['F'] |= 0x02
            return
        if 0x40 <= op <= 0x7F and op != 0x76:            # LD r,(IX+d) / LD (IX+d),r
            dst, src = (op >> 3) & 7, op & 7
            if src == 6:
                self.set_r(dst, self.peek(addr())); return
            if dst == 6:
                self.poke(addr(), self.get_r(src)); return
        if 0x80 <= op <= 0xBF and (op & 7) == 6:         # ALU A,(IX+d)
            v = self.peek(addr())
            mid = (op >> 3) & 7
            if mid == 0: self._add(v)
            elif mid == 1: self._adc(v)
            elif mid == 2: self._sub(v)
            elif mid == 3: self._sbc(v)
            elif mid == 4: self._logic(v, 'and')
            elif mid == 5: self._logic(v, 'xor')
            elif mid == 6: self._logic(v, 'or')
            else: self._sub(v, store=False)
            return
        if op == 0xCB:                                   # bit ops on (IX+d)
            a = addr()
            sub2 = imm8()
            kind, bit, _ = sub2 >> 6, (sub2 >> 3) & 7, sub2 & 7
            v = self.peek(a)
            if kind == 1:
                z = not (v >> bit) & 1
                self.reg['F'] = (self.reg['F'] & 0x01) | (0x40 if z else 0) | 0x10
                return
            if kind == 2:
                self.poke(a, v & ~(1 << bit) & 0xFF); return
            if kind == 3:
                self.poke(a, v | (1 << bit)); return
            c = self.reg['F'] & 1                        # rotates and shifts
            if bit == 0:   nv, nc = ((v << 1) | (v >> 7)) & 0xFF, v >> 7
            elif bit == 1: nv, nc = ((v >> 1) | ((v & 1) << 7)) & 0xFF, v & 1
            elif bit == 2: nv, nc = ((v << 1) | c) & 0xFF, v >> 7
            elif bit == 3: nv, nc = ((v >> 1) | (c << 7)) & 0xFF, v & 1
            elif bit == 4: nv, nc = (v << 1) & 0xFF, v >> 7
            elif bit == 5: nv, nc = ((v >> 1) | (v & 0x80)) & 0xFF, v & 1
            elif bit == 6: nv, nc = ((v << 1) | 1) & 0xFF, v >> 7
            else:          nv, nc = (v >> 1) & 0xFF, v & 1
            self.poke(a, nv)
            par = bin(nv).count('1') % 2 == 0
            self.reg['F'] = ((nv & 0x80) | (0x40 if nv == 0 else 0)
                             | (0x04 if par else 0) | nc)
            return
        raise Unimplemented('%02X %02X at %04X' % (prefix, op, self.pc))

    def call(self, addr, stop=None, limit=200000):
        """Run from addr until RET pops the sentinel, or PC reaches stop."""
        SENTINEL = 0xF00D
        self.sp -= 2
        self.poke(self.sp, SENTINEL & 0xFF)
        self.poke(self.sp + 1, SENTINEL >> 8)
        self.pc = addr
        while self.steps < limit:
            if stop is not None and self.pc == stop:
                return 'stop'
            if self.pc == SENTINEL:
                return 'ret'
            self.step()
        raise Unimplemented('ran past %d steps' % limit)

    def step(self):
        self.steps += 1
        op = self.peek(self.pc)
        pc = self.pc
        self.pc = (self.pc + 1) & 0xFFFF

        def imm8():
            v = self.peek(self.pc)
            self.pc = (self.pc + 1) & 0xFFFF
            return v

        def imm16():
            v = self.peek16(self.pc)
            self.pc = (self.pc + 2) & 0xFFFF
            return v

        def push(v):
            self.sp = (self.sp - 2) & 0xFFFF
            self.poke(self.sp, v & 0xFF)
            self.poke(self.sp + 1, v >> 8)

        def pop():
            v = self.peek16(self.sp)
            self.sp = (self.sp + 2) & 0xFFFF
            return v

        if op == 0x00:                                   # NOP
            return
        if op == 0xED:
            sub = imm8()
            # LD rp,(nn) and LD (nn),rp - the cartridge loads its 16-bit parse
            # variables this way, e.g. ED 5B 84 E4 = LD DE,(0xE484)
            if (sub & 0xCF) == 0x4B:                     # LD rp,(nn)
                self.set_rp((sub >> 4) & 3, self.peek16(imm16()))
                return
            if (sub & 0xCF) == 0x43:                     # LD (nn),rp
                a = imm16()
                v = self.get_rp((sub >> 4) & 3)
                self.poke(a, v & 0xFF)
                self.poke(a + 1, v >> 8)
                return
            if sub in (0x44, 0x4C, 0x54, 0x5C, 0x64, 0x6C, 0x74, 0x7C):   # NEG
                v = self.reg['A']
                self.reg['A'] = 0
                self._sub(v)
                return
            if sub in (0x45, 0x4D, 0x55, 0x5D, 0x65, 0x6D, 0x75, 0x7D):   # RETN/RETI
                self.pc = self.peek16(self.sp)
                self.sp = (self.sp + 2) & 0xFFFF
                self.iff = self.iff2
                return
            if sub in (0x46, 0x4E, 0x56, 0x5E, 0x66, 0x6E, 0x76, 0x7E):   # IM n
                return
            if sub == 0x47:                              # LD I,A
                self.i = self.reg['A']; return
            if sub == 0x4F:                              # LD R,A
                self.r = self.reg['A']; return
            if sub in (0x57, 0x5F):                      # LD A,I / LD A,R
                # P/V comes from IFF2, and the ROM leans on it: the idiom
                #     LD A,I / PUSH AF / DI ... POP AF / RET PO
                # restores interrupts only if they were on.  Left as a no-op
                # this silently leaves them off for ever, and the sequencer
                # stops after its first note.
                v = self.i if sub == 0x57 else self.r
                self.reg['A'] = v
                self.reg['F'] = ((v & 0x80) | (0x40 if v == 0 else 0)
                                 | (0x04 if self.iff2 else 0)
                                 | (self.reg['F'] & 0x01))
                return
            if (sub & 0xCF) == 0x42:                     # SBC HL,rp
                hl = self.get_rp(2)
                v = self.get_rp((sub >> 4) & 3) + (self.reg['F'] & 1)
                r = (hl - v) & 0xFFFF
                self.set_rp(2, r)
                f = ((r >> 8) & 0x80) | (0x40 if r == 0 else 0) | 0x02
                if hl < v:
                    f |= 0x01
                self.reg['F'] = f
                return
            if (sub & 0xCF) == 0x4A:                     # ADC HL,rp
                hl = self.get_rp(2)
                v = self.get_rp((sub >> 4) & 3) + (self.reg['F'] & 1)
                r = hl + v
                self.set_rp(2, r & 0xFFFF)
                f = ((r >> 8) & 0x80) | (0x40 if (r & 0xFFFF) == 0 else 0)
                if r > 0xFFFF:
                    f |= 0x01
                self.reg['F'] = f
                return
            if sub in (0xA0, 0xA8, 0xB0, 0xB8):          # LDI LDD LDIR LDDR
                step = 1 if sub in (0xA0, 0xB0) else -1
                hl, de, bc = self.get_rp(2), self.get_rp(1), self.get_rp(0)
                self.poke(de, self.peek(hl))
                self.set_rp(2, (hl + step) & 0xFFFF)
                self.set_rp(1, (de + step) & 0xFFFF)
                bc = (bc - 1) & 0xFFFF
                self.set_rp(0, bc)
                self.reg['F'] &= ~0x04 & 0xFF
                if bc:
                    self.reg['F'] |= 0x04
                if sub in (0xB0, 0xB8) and bc:
                    self.pc = (self.pc - 2) & 0xFFFF     # repeat
                return
            if sub in (0xA1, 0xA9, 0xB1, 0xB9):          # CPI CPD CPIR CPDR
                step = 1 if sub in (0xA1, 0xB1) else -1
                hl, bc = self.get_rp(2), self.get_rp(0)
                v = self.peek(hl)
                a = self.reg['A']
                r = (a - v) & 0xFF
                self.set_rp(2, (hl + step) & 0xFFFF)
                bc = (bc - 1) & 0xFFFF
                self.set_rp(0, bc)
                f = (self.reg['F'] & 0x01) | 0x02
                f |= (r & 0x80) | (0x40 if r == 0 else 0)
                if bc:
                    f |= 0x04
                self.reg['F'] = f
                if sub in (0xB1, 0xB9) and bc and r:
                    self.pc = (self.pc - 2) & 0xFFFF
                return
            if (sub & 0xC7) == 0x40:                     # IN r,(C)
                v = self.port_in(self.get_rp(0) & 0xFF)
                n = (sub >> 3) & 7
                if n != 6:
                    self.set_r(n, v)
                self._sz(v)
                return
            if (sub & 0xC7) == 0x41:                     # OUT (C),r
                n = (sub >> 3) & 7
                self.port_out(self.get_rp(0) & 0xFF, 0 if n == 6 else self.get_r(n))
                return
            if sub in (0x67, 0x6F):                      # RRD / RLD
                hl = self.get_rp(2)
                m, a = self.peek(hl), self.reg['A']
                if sub == 0x6F:                          # RLD
                    self.poke(hl, ((m << 4) | (a & 0x0F)) & 0xFF)
                    self.reg['A'] = (a & 0xF0) | (m >> 4)
                else:                                    # RRD
                    self.poke(hl, ((a << 4) | (m >> 4)) & 0xFF)
                    self.reg['A'] = (a & 0xF0) | (m & 0x0F)
                self._sz(self.reg['A'])
                return
            raise Unimplemented('ED %02X at %04X' % (sub, pc))
        if op in (0xDD, 0xFD):
            return self._index(op, imm8, imm16, push, pop)
        if op == 0xCB:
            sub = imm8()
            kind, bit, r = sub >> 6, (sub >> 3) & 7, sub & 7
            v = self.get_r(r)
            if kind == 1:                                # BIT
                z = not (v >> bit) & 1
                self.reg['F'] = (self.reg['F'] & 0x01) | (0x40 if z else 0) | 0x10
                return
            if kind == 2:                                # RES
                self.set_r(r, v & ~(1 << bit))
                return
            if kind == 3:                                # SET
                self.set_r(r, v | (1 << bit))
                return
            # rotates/shifts
            c = self.reg['F'] & 1
            if bit == 0:      nv, nc = ((v << 1) | (v >> 7)) & 0xFF, v >> 7        # RLC
            elif bit == 1:    nv, nc = ((v >> 1) | ((v & 1) << 7)) & 0xFF, v & 1   # RRC
            elif bit == 2:    nv, nc = ((v << 1) | c) & 0xFF, v >> 7               # RL
            elif bit == 3:    nv, nc = ((v >> 1) | (c << 7)) & 0xFF, v & 1         # RR
            elif bit == 4:    nv, nc = (v << 1) & 0xFF, v >> 7                     # SLA
            elif bit == 5:    nv, nc = ((v >> 1) | (v & 0x80)) & 0xFF, v & 1       # SRA
            elif bit == 6:    nv, nc = ((v << 1) | 1) & 0xFF, v >> 7               # SLL
            else:             nv, nc = (v >> 1) & 0xFF, v & 1                      # SRL
            self.set_r(r, nv)
            par = bin(nv).count('1') % 2 == 0
            self.reg['F'] = (nv & 0x80) | (0x40 if nv == 0 else 0) | (0x04 if par else 0) | nc
            return

        hi, mid, lo = op >> 6, (op >> 3) & 7, op & 7

        if hi == 1:                                      # LD r,r'
            if op == 0x76:                               # HALT
                self.halted = True
                self.pc = pc                             # sit here until INT
                return
            self.set_r(mid, self.get_r(lo))
            return
        if hi == 2:                                      # ALU A,r
            v = self.get_r(lo)
            if mid == 0:   self._add(v)
            elif mid == 1: self._adc(v)
            elif mid == 2: self._sub(v)
            elif mid == 3: self._sbc(v)
            elif mid == 4: self._logic(v, 'and')
            elif mid == 5: self._logic(v, 'xor')
            elif mid == 6: self._logic(v, 'or')
            elif mid == 7: self._sub(v, store=False)
            else: raise Unimplemented('ALU %d at %04X' % (mid, pc))
            return
        if hi == 0:
            if lo == 6:                                  # LD r,n
                self.set_r(mid, imm8())
                return
            if lo == 4:                                  # INC r
                v = (self.get_r(mid) + 1) & 0xFF
                self.set_r(mid, v); self._sz(v); return
            if lo == 5:                                  # DEC r
                v = (self.get_r(mid) - 1) & 0xFF
                self.set_r(mid, v); self._sz(v)
                self.reg['F'] |= 0x02; return
            if op in (0x01, 0x11, 0x21, 0x31):           # LD rp,nn
                self.set_rp(op >> 4, imm16()); return
            if op in (0x03, 0x13, 0x23, 0x33):           # INC rp
                n = op >> 4; self.set_rp(n, self.get_rp(n) + 1); return
            if op in (0x0B, 0x1B, 0x2B, 0x3B):           # DEC rp
                n = op >> 4; self.set_rp(n, self.get_rp(n) - 1); return
            if op in (0x09, 0x19, 0x29, 0x39):           # ADD HL,rp
                n = op >> 4
                r = self.get_rp(2) + self.get_rp(n)
                self.reg['F'] = (self.reg['F'] & 0xFC) | (1 if r > 0xFFFF else 0)
                self.set_rp(2, r); return
            if op == 0x32: self.poke(imm16(), self.reg['A']); return       # LD (nn),A
            if op == 0x3A: self.reg['A'] = self.peek(imm16()); return      # LD A,(nn)
            if op == 0x22:                                                  # LD (nn),HL
                a = imm16(); self.poke(a, self.reg['L']); self.poke(a + 1, self.reg['H']); return
            if op == 0x2A:                                                  # LD HL,(nn)
                a = imm16(); self.reg['L'] = self.peek(a); self.reg['H'] = self.peek(a + 1); return
            if op == 0x02: self.poke(self.get_rp(0), self.reg['A']); return
            if op == 0x12: self.poke(self.get_rp(1), self.reg['A']); return
            if op == 0x0A: self.reg['A'] = self.peek(self.get_rp(0)); return
            if op == 0x1A: self.reg['A'] = self.peek(self.get_rp(1)); return
            if op == 0x07:                                                  # RLCA
                a = self.reg['A']; self.reg['A'] = ((a << 1) | (a >> 7)) & 0xFF
                self.reg['F'] = (self.reg['F'] & 0xC4) | (a >> 7); return
            if op == 0x0F:                                                  # RRCA
                a = self.reg['A']; self.reg['A'] = ((a >> 1) | ((a & 1) << 7)) & 0xFF
                self.reg['F'] = (self.reg['F'] & 0xC4) | (a & 1); return
            if op == 0x17:                                                  # RLA
                a = self.reg['A']; c = self.reg['F'] & 1
                self.reg['A'] = ((a << 1) | c) & 0xFF
                self.reg['F'] = (self.reg['F'] & 0xC4) | (a >> 7); return
            if op == 0x1F:                                                  # RRA
                a = self.reg['A']; c = self.reg['F'] & 1
                self.reg['A'] = ((a >> 1) | (c << 7)) & 0xFF
                self.reg['F'] = (self.reg['F'] & 0xC4) | (a & 1); return
            if op == 0x2F:                                                  # CPL
                self.reg['A'] ^= 0xFF; return
            if op == 0x37:                                                  # SCF
                self.reg['F'] |= 0x01; return
            if op == 0x3F:                                                  # CCF
                self.reg['F'] ^= 0x01; return
            if op == 0x18:                                                  # JR d
                d = imm8(); self.pc = (self.pc + (d - 256 if d > 127 else d)) & 0xFFFF; return
            if op in (0x20, 0x28, 0x30, 0x38):                              # JR cc,d
                d = imm8()
                if self.cond((op >> 3) & 3):
                    self.pc = (self.pc + (d - 256 if d > 127 else d)) & 0xFFFF
                return
            if op == 0x10:                                                  # DJNZ
                d = imm8()
                self.reg['B'] = (self.reg['B'] - 1) & 0xFF
                if self.reg['B']:
                    self.pc = (self.pc + (d - 256 if d > 127 else d)) & 0xFFFF
                return
            if op == 0x08:                                                  # EX AF,AF'
                return
        if hi == 3:
            if op == 0xC3: self.pc = imm16(); return                        # JP nn
            if lo == 2:                                                     # JP cc,nn
                a = imm16()
                if self.cond(mid): self.pc = a
                return
            if op == 0xCD:                                                  # CALL nn
                a = imm16(); push(self.pc); self.pc = a; return
            if lo == 4:                                                     # CALL cc,nn
                a = imm16()
                if self.cond(mid): push(self.pc); self.pc = a
                return
            if op == 0xC9: self.pc = pop(); return                          # RET
            if lo == 0:                                                     # RET cc
                if self.cond(mid): self.pc = pop()
                return
            if lo == 5 and mid & 1 == 0:                                    # PUSH rp2
                n = (op >> 4) & 3
                push((self.reg['A'] << 8) | self.reg['F'] if n == 3 else self.get_rp(n)); return
            if lo == 1 and mid & 1 == 0:                                    # POP rp2
                n = (op >> 4) & 3
                v = pop()
                if n == 3: self.reg['A'], self.reg['F'] = v >> 8, v & 0xFF
                else: self.set_rp(n, v)
                return
            if lo == 6:                                                     # ALU A,n
                v = imm8()
                if mid == 0:   self._add(v)
                elif mid == 1: self._adc(v)
                elif mid == 2: self._sub(v)
                elif mid == 3: self._sbc(v)
                elif mid == 4: self._logic(v, 'and')
                elif mid == 5: self._logic(v, 'xor')
                elif mid == 6: self._logic(v, 'or')
                elif mid == 7: self._sub(v, store=False)
                else: raise Unimplemented('ALU n %d at %04X' % (mid, pc))
                return
            if op == 0xE9: self.pc = self.get_rp(2); return                 # JP (HL)
            if op == 0xE3:                                                  # EX (SP),HL
                v = self.peek16(self.sp)
                self.poke(self.sp, self.reg['L']); self.poke(self.sp + 1, self.reg['H'])
                self.reg['L'], self.reg['H'] = v & 0xFF, v >> 8
                return
            if op == 0xEB:                                                  # EX DE,HL
                self.reg['D'], self.reg['H'] = self.reg['H'], self.reg['D']
                self.reg['E'], self.reg['L'] = self.reg['L'], self.reg['E']
                return
            if op == 0xF9: self.sp = self.get_rp(2); return                 # LD SP,HL
            if op == 0xF3:                                                  # DI
                self.iff = self.iff2 = 0; return
            if op == 0xFB:                                                  # EI
                self.iff = self.iff2 = 1; return
            if op == 0xD9:                                                  # EXX
                for r in 'BCDEHL':
                    self.reg[r], self.alt[r] = self.alt[r], self.reg[r]
                return
            if op == 0xD3:                                                  # OUT (n),A
                self.port_out(imm8(), self.reg['A']); return
            if op == 0xDB:                                                  # IN A,(n)
                self.reg['A'] = self.port_in(imm8()); return
            if lo == 7:                                                     # RST
                push(self.pc); self.pc = mid * 8; return
        raise Unimplemented('opcode %02X at %04X' % (op, pc))
