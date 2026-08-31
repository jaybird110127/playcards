#!/usr/bin/env python3
"""
Make a damaged Playcard image pass its own checksum, so a keyboard will accept
it and you can hear what it does with nonsense.

    python forge_crc.py card.bin                 # report only, nothing written
    python forge_crc.py card.bin -o forged.bin   # write it with a repaired CRC

The point is to corrupt a card on purpose - stamp on the melody, put a rhythm
value that no card ever used, aim the key field at one of the chip's unused note
codes - and still have the UPA-01 take it, because the checksum agrees.  A
card whose CRC fails is simply rejected and never reaches the interesting part.

WHAT THIS REFUSES TO DO

Only one thing: repair a file that is not a Playcard image.  Not out of caution
about the contents - garbage contents are the entire point - but because the
checksum has no fixed address.  It sits immediately after the last section, and
where that falls depends on the length of the header, of both duration tracks,
of the chord chart and of both opcode streams.  If any of those cannot be walked
the CRC's position is unknown, and there is nothing to repair.

So the structural walk is the whole test, and when it fails this says which
structure it was standing on, at which bit, and why the walk could not continue.

WHAT THIS DELIBERATELY IGNORES

Values.  A tempo index of 31, a rhythm byte of 13 that maps to no style, a key
field of 7 which is one of the YM2151's unused note codes, a chord type of 15,
an alphabet naming symbols a card would never use - all of these parse, so all
of them are left exactly as found and merely listed.  Whether a keyboard shrugs,
misbehaves or refuses is what you are trying to find out.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playcard_decode as P


class NotACard(Exception):
    """The structural walk could not continue."""

    def __init__(self, where, bit, why, consequence=None):
        self.where, self.bit, self.why = where, bit, why
        self.consequence = consequence
        Exception.__init__(self, why)


class Walk:
    """A bit reader that remembers where it is, so a failure can say where."""

    def __init__(self, bits):
        self.b, self.p = bits, 0
        self.where = 'start of file'

    def get(self, n, where=None):
        if where:
            self.where = where
        if self.p + n > len(self.b):
            raise NotACard(self.where, self.p,
                           'the file ends after %d bits, but %d more were needed here'
                           % (len(self.b), n - (len(self.b) - self.p)),
                           'a Playcard image is never truncated mid-structure')
        v = 0
        for _ in range(n):
            v = (v << 1) | self.b[self.p]
            self.p += 1
        return v


def sym(w, note):
    """The alternating-run prefix code (ROM 0x631E)."""
    b0 = w.get(1, note)
    k = 0
    while True:
        b = w.get(1, note)
        if b != b0:
            return 2 * k + b
        k += 1
        if k > 20:
            raise NotACard(note, w.p,
                           'a duration codeword ran past 20 repeated bits without closing',
                           'the code is self-terminating, so this is not duration data')


def walk_track(w, alpha, which, notes):
    """One duration track.  Returns the events; raises if it will not decode."""
    out, last, pending = [], 0, 0
    for _ in range(4000):
        v = sym(w, '%s duration track' % which)
        if v >= len(alpha):
            raise NotACard('%s duration track' % which, w.p,
                           'a codeword selected symbol %d, but this card’s alphabet '
                           'only has %d entries' % (v, len(alpha)),
                           'the alphabet is what gives the symbols meaning, so the rest '
                           'of the track cannot be read')
        a = alpha[v]
        if a == 0xFF:
            a = last
        if a == 0xE1:
            out.append(0xE1)
            if pending:
                pending = 0
                continue
            w.get(3, '%s duration track' % which)
            notes.append('%s duration track: %d events' % (which, len(out)))
            return out
        if a > 0xE1:
            pending = 1
        else:
            last = a
        out.append(a)
    raise NotACard('%s duration track' % which, w.p,
                   'ran past 4000 events without reaching a terminator',
                   'every real track ends with the 0xE1 symbol')


def walk_stream(w, which, notes):
    ops, pending = [], 0
    for _ in range(4001):
        op = w.get(4, which)
        if op == 15:
            sub = w.get(4, which)
            if sub >= 8:
                pending = 1
        elif op == 14:
            if pending:
                pending = 0
            else:
                notes.append('%s: %d opcodes' % (which, len(ops)))
                return ops
        ops.append(op)
    raise NotACard(which, w.p,
                   'ran past 4000 opcodes without the stream ending',
                   'a stream is closed by opcode E with no repeat span open')


def walk_section(w, n, notes):
    table, dur = [], 15
    while len(table) < 63:
        code = w.get(4, 'section %d chord chart' % n)
        val = w.get(6, 'section %d chord chart' % n)
        if code == 15:
            dur = (val - 1) & 0xFF
            continue
        v = (code << 6) | val
        if v == 0:
            break
        table.append((dur, v))
    notes.append('section %d chord chart: %d entries' % (n, len(table)))
    walk_stream(w, 'section %d melody stream' % n, notes)
    walk_stream(w, 'section %d obbligato stream' % n, notes)
    return table


def structure(bits):
    """Walk the whole image.  Returns (info, notes, warnings) or raises NotACard."""
    notes, warn = [], []
    w = Walk(bits)
    if len(bits) < 64:
        raise NotACard('the file itself', 0,
                       'only %d bits long' % len(bits),
                       'the header alone is 29 bits before its alphabet, and a card '
                       'also needs tracks, a section and a checksum')

    w.get(1, 'preamble bit')
    t = w.get(2, 'block type')
    info = {'type': t}
    if t not in (1, 2):
        raise NotACard('block type', w.p - 2,
                       'read %d; the only values the UPA-01 accepts are 1 for a full '
                       'card and 2 for a side-B continuation' % t,
                       'the UPA-01 rejects anything else outright at ROM 0x663D, and '
                       'every later structure is positioned relative to this field, so '
                       'nothing after it can be located')
    notes.append('block type %d (%s)' % (t, 'full card' if t == 1 else 'continuation'))

    if t == 1:
        info['tempo_raw'] = w.get(5, 'header')
        info['rhythm_raw'] = w.get(4, 'header')
        info['f3'] = w.get(3, 'header')
        info['mel_raw'] = w.get(4, 'header')
        info['sustain'] = w.get(1, 'header')
        info['obb_raw'] = w.get(3, 'header')
        info['key'] = w.get(4, 'header')
        n = w.get(5, 'header')
        info['alpha_n'] = n
        if n >= 26:
            warn.append('alphabet size is %d; the UPA-01 rejects 26 or more at ROM '
                        '0x62D9, so this card will be refused whatever its checksum says' % n)
        if n == 0:
            raise NotACard('header', w.p,
                           'the alphabet is empty, so no duration symbol has any meaning',
                           'the tracks that follow cannot be decoded at all')
        info['alphabet'] = [P.ALPHA[w.get(5, 'header alphabet')] for _ in range(n)]
        notes.append('header: %d-symbol alphabet' % n)
        info['track1'] = walk_track(w, info['alphabet'], 'melody', notes)
        info['track2'] = walk_track(w, info['alphabet'], 'obbligato', notes)
        info['sections'] = []
        while True:
            tag = w.get(2, 'section tag')
            if tag == 0:
                break
            if tag != 2:
                raise NotACard('section tag', w.p - 2,
                               'read %d; a tag is 2 when a section follows and 0 when the '
                               'card is done' % tag,
                               'with the tag unreadable there is no way to tell whether '
                               'more sections follow, so the checksum cannot be located')
            info['sections'].append(walk_section(w, len(info['sections']), notes))
    else:
        info['sections'] = [walk_section(w, 0, notes)]
        tag = w.get(2, 'terminator')
        if tag != 0:
            raise NotACard('terminator', w.p - 2,
                           'a continuation card must end with the 2-bit value 0, but this '
                           'reads %d' % tag)

    info['crc_at'] = w.p
    w.get(16, 'checksum')
    info['end'] = w.p
    notes.append('checksum field at bits %d-%d' % (info['crc_at'], info['end']))

    spare = len(bits) - info['end']
    info['spare'] = spare
    # Across all 267 original cards the file ends between 24 and 32 bits past the
    # checksum: 0 to 8 zero pad bits to reach a byte boundary, then the 24-bit
    # trailer.  A large leftover means the structures did not account for the
    # file, which is what random data looks like when the walk happens to
    # survive a few fields by luck.
    if spare > 32:
        raise NotACard('after the checksum', info['end'],
                       'the structures end at bit %d but the file runs on for %d more '
                       'bits (%.0f%% of it is unaccounted for)'
                       % (info['end'], spare, 100.0 * spare / len(bits)),
                       'every one of the 267 original cards ends between 24 and 32 bits '
                       'past its checksum - up to 8 pad bits and a 24-bit trailer - so a '
                       'card that leaves this much over was not laid out by this format. '
                       'The walk most likely survived the early fields by coincidence')
    if spare < 24:
        warn.append('only %d bits follow the checksum; a real card has 0 to 8 zero pad '
                    'bits and then a 24-bit trailer, so the trailer is missing or short'
                    % spare)
    return info, notes, warn


def crc_over(bits, upto):
    crc = 0x8005
    for i in range(upto):
        msb = (crc >> 15) & 1
        crc = (crc << 1) & 0xFFFF
        if msb ^ bits[i]:
            crc ^= 0x8005
    return crc


# ---------------------------------------------------------------- reporting

def report_values(info):
    """Everything here is printed and nothing is judged - see the module docstring."""
    if info['type'] != 1:
        print('  (a continuation card carries no header)')
        return
    out = []
    t = info['tempo_raw']
    out.append(('tempo', '%d bpm' % P.TEMPO[t], None))
    r = info['rhythm_raw']
    style = P.RHYTHM[P.T640A[r]]
    out.append(('rhythm', '%d -> %s' % (r, style),
                'no style; the UPA-01 maps 10-15 to nothing' if style == '(none)' else None))
    out.append(('accomp pattern', '%d -> %s' % (info['f3'],
                'ALTERNATE, locked' if info['f3'] else 'standard'), None))
    m = P.T641A[info['mel_raw']]
    out.append(('melody voice', '%d -> %s' % (info['mel_raw'], P.voice(P.MELODY_VOICE, m)),
                'raw 0-5 map to voice 0, which is off the end of the table'
                if m == 0 else None))
    o = P.T642A[info['obb_raw']]
    out.append(('obbligato voice', '%d -> %s' % (info['obb_raw'], P.voice(P.OBBLIGATO_VOICE, o)), None))
    out.append(('sustain', 'on' if info['sustain'] else 'off', None))
    k = info['key']
    out.append(('key', 'field %d, transpose %+d, a card in C sounds in %s'
                % (k, P.key_shift(k), P.key_name(k)),
                'one of the four codes the YM2151 leaves unused, so it transposes by 0'
                if k not in P.OPM_INDEX else None))
    out.append(('alphabet', '%d symbols: %s' % (info['alpha_n'],
                ' '.join('%02X' % a for a in info['alphabet'])), None))
    for name, val, note in out:
        line = '    %-16s %s' % (name, val)
        if note and len(line) + len(note) + 4 <= 78:
            print('%s   <- %s' % (line, note))
        elif note:
            print(line)
            P.say(note, prefix='      <- ', hang='         ')
        else:
            print(line)
    for i, table in enumerate(info['sections']):
        # entries are (chord value, opcode position) - value first, as in
        # playcard_decode; reading them the other way round reports positions
        # as chords and makes every real card look corrupt
        odd = [v for v, _ in table if v != 0xFF and ((v >> 4) & 0x0F) > 3]
        bad = [v for v, _ in table if v != 0xFF and (v & 0x0F) not in P.OPM_INDEX]
        print('    %-16s %d entries%s%s'
              % ('section %d chart' % i, len(table),
                 '; %d with a chord type above 3' % len(odd) if odd else '',
                 '; %d on an unused note code' % len(bad) if bad else ''))


def main():
    ap = argparse.ArgumentParser(
        description='Give a corrupted Playcard image a checksum that passes.')
    ap.add_argument('card')
    ap.add_argument('-o', '--out', help='write the forged image here')
    a = ap.parse_args()

    # NOT check_card: this tool exists for images too damaged to parse, so it
    # takes anything that is there and says for itself where the walk stops.
    data = P.check_file(a.card, 'a Playcard image')
    bits = P.tobits(data)
    print('%s  (%d bytes, looks like %s)'
          % (os.path.basename(a.card), len(data), P.kind_of(a.card)))
    print()

    try:
        info, notes, warn = structure(bits)
    except NotACard as e:
        print('  This is not a Playcard image, and the checksum cannot be placed.')
        print()
        print('  The walk got as far as: %s' % e.where)
        print('  and stopped at bit %d (byte %d, bit %d of it).'
              % (e.bit, e.bit // 8, e.bit % 8))
        # e.why and e.consequence are sentences, and long ones - they explain
        # what the firmware would have done - so they are wrapped rather than
        # left to the terminal.
        P.say(e.why)
        if e.consequence:
            print()
            P.say(e.consequence)
        print()
        P.say('The checksum has no fixed address - it sits after the last '
              'section, and where that lands depends on the length of every '
              'structure before it. Nothing can be repaired without walking '
              'those first.')
        return 1

    print('  STRUCTURE - all of this had to hold for the checksum to be locatable')
    for n in notes:
        print('    %s' % n)
    print()
    print('  VALUES - reported only; nothing here is corrected or rejected')
    report_values(info)
    if warn:
        print()
        print('  WORTH KNOWING')
        for x in warn:
            print('    %s' % x)

    stored = 0
    for i in range(info['crc_at'], info['end']):
        stored = (stored << 1) | bits[i]
    correct = crc_over(bits, info['crc_at'])
    print()
    print('  CHECKSUM')
    print('    stored    %04X' % stored)
    print('    correct   %04X   %s' % (correct,
          'already agrees, the card would be accepted as it is'
          if stored == correct else 'does not agree, the card would be rejected'))

    if not a.out:
        print()
        print('  nothing written; pass -o to save a copy with the checksum repaired')
        return 0

    fixed = list(bits)
    for j in range(16):
        fixed[info['crc_at'] + j] = (correct >> (15 - j)) & 1
    out = bytearray()                       # the file is whole bytes in and out
    for i in range(0, len(fixed), 8):
        v = 0
        for b in fixed[i:i + 8]:
            v = (v << 1) | b
        out.append(v)
    open(a.out, 'wb').write(bytes(out))

    check = P.parse_card(P.tobits(bytes(out)))
    print()
    print('    -> %s (%d bytes, %d changed)'
          % (a.out, len(out), sum(1 for x, y in zip(data, out) if x != y)))
    print('       re-read: CRC %s. The card will now be accepted; what it then does'
          % ('VALID' if check['crc_ok'] else 'STILL FAILS'))
    print('       is the experiment.')
    return 0


if __name__ == '__main__':
    P.run(main)
