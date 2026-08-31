#!/usr/bin/env python3
"""A small Z80 disassembler - enough of the instruction set for this ROM.

    python z80dis.py 5F8B 5FC2                    # a range, addresses in hex
    python z80dis.py 0100 0180 --rom PCS-30.rom --base 0

The UPA-01 cartridge ROM is 16K loaded at 0x4000, which is the default; --rom
names another image in the Roms folder and --base says where it is mapped (the
PCS-30 keyboard ROM, for instance, is a boot ROM based at 0x0000).  Written
for reading the playback engine: the recipe that solved the control opcodes was
to scan the ROM for `CP <suspect value>` (the two bytes FE nn), then disassemble
around each hit until the dispatcher appeared.  Undocumented and duplicated
opcodes are not covered, and neither is anything the cartridge does not use.
"""

R = ['B', 'C', 'D', 'E', 'H', 'L', '(HL)', 'A']
RP = ['BC', 'DE', 'HL', 'SP']
RP2 = ['BC', 'DE', 'HL', 'AF']
CC = ['NZ', 'Z', 'NC', 'C', 'PO', 'PE', 'P', 'M']
ALU = ['ADD A,', 'ADC A,', 'SUB ', 'SBC A,', 'AND ', 'XOR ', 'OR ', 'CP ']
ROT = ['RLC', 'RRC', 'RL', 'RR', 'SLA', 'SRA', 'SLL', 'SRL']


def dis(mem, base, addr):
    """-> (text, length).  mem is bytes; base is its load address."""
    def b(o):
        i = addr - base + o
        return mem[i] if 0 <= i < len(mem) else 0
    def w(o):
        return b(o) | (b(o + 1) << 8)

    op = b(0)
    x, y, z = op >> 6, (op >> 3) & 7, op & 7
    p, q = y >> 1, y & 1

    if op == 0xCB:
        op2 = b(1)
        x2, y2, z2 = op2 >> 6, (op2 >> 3) & 7, op2 & 7
        if x2 == 0:
            return '%s %s' % (ROT[y2], R[z2]), 2
        return '%s %d,%s' % (['', 'BIT', 'RES', 'SET'][x2], y2, R[z2]), 2
    if op == 0xED:
        op2 = b(1)
        x2, y2, z2 = op2 >> 6, (op2 >> 3) & 7, op2 & 7
        if x2 == 1 and z2 == 3:
            if q == 0 or (y2 & 1) == 0:
                return 'LD (0%04Xh),%s' % (w(2), RP[y2 >> 1]), 4
            return 'LD %s,(0%04Xh)' % (RP[y2 >> 1], w(2)), 4
        if x2 == 1 and z2 == 2:
            return '%s HL,%s' % ('SBC' if (y2 & 1) == 0 else 'ADC', RP[y2 >> 1]), 2
        if x2 == 1 and z2 == 0:
            return 'IN %s,(C)' % R[y2], 2
        if x2 == 1 and z2 == 1:
            return 'OUT (C),%s' % R[y2], 2
        if op2 == 0xB0: return 'LDIR', 2
        if op2 == 0xB8: return 'LDDR', 2
        if op2 == 0xA0: return 'LDI', 2
        if op2 == 0x44: return 'NEG', 2
        if op2 == 0x4D: return 'RETI', 2
        if op2 == 0x45: return 'RETN', 2
        if op2 in (0x46, 0x56, 0x5E): return 'IM %d' % {0x46: 0, 0x56: 1, 0x5E: 2}[op2], 2
        return 'ED %02X' % op2, 2
    if op in (0xDD, 0xFD):
        ix = 'IX' if op == 0xDD else 'IY'
        op2 = b(1)
        if op2 == 0x21: return 'LD %s,0%04Xh' % (ix, w(2)), 4
        if op2 == 0x36: return 'LD (%s%+d),0%02Xh' % (ix, b(2) - 256 if b(2) > 127 else b(2), b(3)), 4
        if op2 == 0x2A: return 'LD %s,(0%04Xh)' % (ix, w(2)), 4
        if op2 == 0x22: return 'LD (0%04Xh),%s' % (w(2), ix), 4
        if op2 == 0xE9: return 'JP (%s)' % ix, 2
        if op2 == 0xE5: return 'PUSH %s' % ix, 2
        if op2 == 0xE1: return 'POP %s' % ix, 2
        if (op2 & 0xC0) == 0x40 and (op2 & 7) == 6:
            d = b(2) - 256 if b(2) > 127 else b(2)
            return 'LD (%s%+d),%s' % (ix, d, R[(op2 >> 3) & 7]), 3
        if (op2 & 0xC7) == 0x46:
            d = b(2) - 256 if b(2) > 127 else b(2)
            return 'LD %s,(%s%+d)' % (R[(op2 >> 3) & 7], ix, d), 3
        if (op2 & 0xC7) == 0x86:
            d = b(2) - 256 if b(2) > 127 else b(2)
            return '%s(%s%+d)' % (ALU[(op2 >> 3) & 7], ix, d), 3
        if op2 == 0x23: return 'INC %s' % ix, 2
        if op2 == 0x2B: return 'DEC %s' % ix, 2
        if op2 == 0x19: return 'ADD %s,DE' % ix, 2
        if op2 == 0x09: return 'ADD %s,BC' % ix, 2
        return '%s %02X' % (ix, op2), 2

    if x == 0:
        if z == 0:
            if y == 0: return 'NOP', 1
            if y == 1: return "EX AF,AF'", 1
            if y == 2: return 'DJNZ 0%04Xh' % (addr + 2 + (b(1) - 256 if b(1) > 127 else b(1))), 2
            if y == 3: return 'JR 0%04Xh' % (addr + 2 + (b(1) - 256 if b(1) > 127 else b(1))), 2
            return 'JR %s,0%04Xh' % (CC[y - 4], addr + 2 + (b(1) - 256 if b(1) > 127 else b(1))), 2
        if z == 1:
            if q == 0: return 'LD %s,0%04Xh' % (RP[p], w(1)), 3
            return 'ADD HL,%s' % RP[p], 1
        if z == 2:
            if q == 0:
                if p == 0: return 'LD (BC),A', 1
                if p == 1: return 'LD (DE),A', 1
                if p == 2: return 'LD (0%04Xh),HL' % w(1), 3
                return 'LD (0%04Xh),A' % w(1), 3
            if p == 0: return 'LD A,(BC)', 1
            if p == 1: return 'LD A,(DE)', 1
            if p == 2: return 'LD HL,(0%04Xh)' % w(1), 3
            return 'LD A,(0%04Xh)' % w(1), 3
        if z == 3: return '%s %s' % ('INC' if q == 0 else 'DEC', RP[p]), 1
        if z == 4: return 'INC %s' % R[y], 1
        if z == 5: return 'DEC %s' % R[y], 1
        if z == 6: return 'LD %s,0%02Xh' % (R[y], b(1)), 2
        return ['RLCA', 'RRCA', 'RLA', 'RRA', 'DAA', 'CPL', 'SCF', 'CCF'][y], 1
    if x == 1:
        if z == 6 and y == 6: return 'HALT', 1
        return 'LD %s,%s' % (R[y], R[z]), 1
    if x == 2:
        return '%s%s' % (ALU[y], R[z]), 1
    # x == 3
    if z == 0: return 'RET %s' % CC[y], 1
    if z == 1:
        if q == 0: return 'POP %s' % RP2[p], 1
        return ['RET', 'EXX', 'JP (HL)', 'LD SP,HL'][p], 1
    if z == 2: return 'JP %s,0%04Xh' % (CC[y], w(1)), 3
    if z == 3:
        if y == 0: return 'JP 0%04Xh' % w(1), 3
        if y == 2: return 'OUT (0%02Xh),A' % b(1), 2
        if y == 3: return 'IN A,(0%02Xh)' % b(1), 2
        if y == 4: return 'EX (SP),HL', 1
        if y == 5: return 'EX DE,HL', 1
        if y == 6: return 'DI', 1
        if y == 7: return 'EI', 1
    if z == 4: return 'CALL %s,0%04Xh' % (CC[y], w(1)), 3
    if z == 5:
        if q == 0: return 'PUSH %s' % RP2[p], 1
        if p == 0: return 'CALL 0%04Xh' % w(1), 3
    if z == 6: return '%s0%02Xh' % (ALU[y], b(1)), 2
    if z == 7: return 'RST 0%02Xh' % (y * 8), 1
    return 'DB 0%02Xh' % op, 1


def listing(mem, base, start, end, notes=None):
    notes = notes or {}
    a = start
    out = []
    while a < end:
        txt, n = dis(mem, base, a)
        raw = mem[a - base:a - base + n].hex(' ')
        c = notes.get(a, '')
        out.append('%04X  %-14s %-24s %s' % (a, raw, txt, c))
        a += n
    return '\n'.join(out)


if __name__ == '__main__':
    import argparse, os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import playcard_decode as P

    ap = argparse.ArgumentParser(description='Disassemble a range of a Z80 ROM.')
    ap.add_argument('start', help='first address, hex')
    ap.add_argument('end', help='last address, hex')
    ap.add_argument('--rom', default=P.CART_ROM, help='ROM image in the Roms folder')
    ap.add_argument('--base', default='4000', help='address the image is mapped at, hex')
    a = ap.parse_args()
    try:
        rom = open(P.rom(a.rom), 'rb').read()
    except P.Missing as e:
        sys.exit(str(e))
    print(listing(rom, int(a.base, 16), int(a.start, 16), int(a.end, 16)))
