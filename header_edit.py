#!/usr/bin/env python3
"""
Read or rewrite a Playcard's header, fixing up the checksum so the card stays
valid.

    python header_edit.py card.bin                       # just show the header
    python header_edit.py card.bin -o out.bin --tempo 120 --rhythm waltz
    python header_edit.py card.bin -o out.bin --transpose -3 --sustain on
    python header_edit.py card.bin -o out.bin --melody-voice guitar

Every field the header carries sits at a fixed offset and a fixed width, ahead
of the variable-length alphabet, so changing any of them shifts nothing else in
the card.  That is what makes this safe where editing a duration track is not:
the tracks and opcode streams are self-delimiting, and damaging one moves every
structure after it.

Values are given the way a musician would say them - a tempo in bpm, a rhythm by
name, a transposition in semitones, voices by their SFG-01 names - and anything
out of range is clamped to the nearest thing the format can actually express,
with a note saying so.  The card's own tempo table is coarse, for instance, so
--tempo 121 lands on 120.

For deliberately invalid values, --raw writes a field's bits directly and clamps
only to the width of the field.  A rhythm of 13 maps to no style at all, a key
of 7 is one of the YM2151's unused note codes; the cartridge will still accept
the card, because the checksum is recomputed either way.  See forge_crc.py.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playcard_decode as P
import forge_crc as F


# name -> (bit offset from the start of the file, width in bits)
# The header begins at bit 3: one leftover preamble bit, then the 2-bit type.
FIELDS = {
    'tempo':     (3, 5),
    'rhythm':    (8, 4),
    'pattern':   (12, 3),
    'melody':    (15, 4),
    'sustain':   (19, 1),
    'obbligato': (20, 3),
    'key':       (23, 4),
    'alphabet':  (27, 5),      # readable, never written: it sizes what follows
}

# Both vocabularies, so --melody-voice takes `clarinet` or the SFG-01's own
# `CLARINE`.  The panel names are what gets printed and offered in errors.
MELODY_NAMES = {P.voice(P.MELODY_VOICE, v): v for v in range(1, 11)}
OBB_NAMES = {P.voice(P.OBBLIGATO_VOICE, v): v for v in range(1, 9)}
RHYTHM_NAMES = {n: i for i, n in enumerate(P.RHYTHM) if i}


def get(bits, name):
    off, w = FIELDS[name]
    v = 0
    for i in range(w):
        v = (v << 1) | bits[off + i]
    return v


def put(bits, name, v):
    off, w = FIELDS[name]
    v &= (1 << w) - 1
    for i in range(w):
        bits[off + i] = (v >> (w - 1 - i)) & 1


class Clamp:
    """Collects 'you asked for X, you got Y' so it can all be reported at once."""

    def __init__(self):
        self.notes = []

    def say(self, what, asked, got):
        self.notes.append('%s: %s is not available, using %s' % (what, asked, got))


def pick_tempo(bpm, c):
    """Nearest metronome mark in the card's own 32-entry table."""
    best = min(range(len(P.TEMPO)), key=lambda i: abs(P.TEMPO[i] - bpm))
    if P.TEMPO[best] != bpm:
        c.say('tempo', '%g bpm' % bpm, '%d bpm' % P.TEMPO[best])
    return best


def pick_rhythm(val, c):
    """Style name or number 1-10 -> the raw field value."""
    if isinstance(val, str) and not val.lstrip('-').isdigit():
        key = val.strip().lower()
        if key in RHYTHM_NAMES:
            style = RHYTHM_NAMES[key]
        else:
            near = [n for n in RHYTHM_NAMES if n.startswith(key)]
            if len(near) == 1:
                style = RHYTHM_NAMES[near[0]]
                c.say('rhythm', val, near[0])
            else:
                sys.exit('unknown rhythm %r; choose from: %s'
                         % (val, ', '.join(sorted(RHYTHM_NAMES))))
    else:
        style = int(val)
        if not 1 <= style <= 10:
            style = max(1, min(10, style))
            c.say('rhythm', val, '%d (%s)' % (style, P.RHYTHM[style]))
    return style - 1                       # raw v maps to style v+1


def pick_voice(val, names, table, lo, hi, what, c):
    if isinstance(val, str) and not val.lstrip('-').isdigit():
        field = P.voice_field(table, val)          # either vocabulary, any case
        if field is not None:
            proper = P.voice(table, field)
            if proper.lower() != val.strip().lower():
                c.say(what, val, proper)
            return field
        key = val.strip().lower()
        near = [n for n in names if n.startswith(key)]
        if len(near) == 1:
            c.say(what, val, near[0])
            return names[near[0]]
        sys.exit(P.wrapped('unknown %s voice %r; choose from: %s'
                           % (what, val, ', '.join(sorted(names)))))
    v = int(val)
    if not lo <= v <= hi:
        v2 = max(lo, min(hi, v))
        c.say(what, str(v), '%d (%s)' % (v2, P.voice(table, v2)))
        v = v2
    return v


def pick_transpose(semis, c):
    """Semitones -> the YM2151 note code the key field carries."""
    avail = {P.key_shift(code): code for code in sorted(P.OPM_INDEX)}
    if semis not in avail:
        near = min(avail, key=lambda s: (abs(s - semis), s))
        c.say('transpose', '%+d semitones' % semis, '%+d' % near)
        semis = near
    return avail[semis]


def onoff(v):
    return str(v).strip().lower() in ('on', '1', 'true', 'yes')


def show(bits, info):
    raw = {n: get(bits, n) for n in FIELDS}
    mel = P.T641A[raw['melody']]
    obb = P.T642A[raw['obbligato']]
    style = P.T640A[raw['rhythm']]
    key = raw['key']
    print('  %-18s %-38s raw %d' % ('tempo', '%d bpm' % P.TEMPO[raw['tempo']], raw['tempo']))
    print('  %-18s %-38s raw %d' % ('rhythm', P.RHYTHM[style], raw['rhythm']))
    print('  %-18s %-38s raw %d' % ('accomp pattern',
                                    'ALTERNATE (locked)' if raw['pattern'] else 'standard',
                                    raw['pattern']))
    print('  %-18s %-38s raw %d' % ('melody voice',
                                    '%s (field %d)' % (P.voice(P.MELODY_VOICE, mel), mel),
                                    raw['melody']))
    print('  %-18s %-38s raw %d' % ('obbligato voice',
                                    '%s (field %d)' % (P.voice(P.OBBLIGATO_VOICE, obb), obb),
                                    raw['obbligato']))
    print('  %-18s %-38s raw %d' % ('sustain', 'on' if raw['sustain'] else 'off',
                                    raw['sustain']))
    print('  %-18s %-38s raw %d' % ('transpose',
                                    '%+d semitones, a card in C sounds in %s'
                                    % (P.key_shift(key), P.key_name(key)), key))
    print('  %-18s %-38s raw %d' % ('alphabet size', '%d symbols' % raw['alphabet'],
                                    raw['alphabet']))


def main():
    ap = argparse.ArgumentParser(
        description="Show or change a Playcard's header, keeping the checksum valid.")
    ap.add_argument('card')
    ap.add_argument('-o', '--out', help='write the modified card here')
    ap.add_argument('--tempo', type=float, help='beats per minute (snapped to the card table)')
    ap.add_argument('--rhythm', help='style name or 1-10: %s'
                                     % ', '.join(P.RHYTHM[1:]))
    ap.add_argument('--transpose', type=int, help='semitones, -6 to +5')
    ap.add_argument('--melody-voice', dest='melody', help='voice name, or field 1-10')
    ap.add_argument('--obbligato-voice', dest='obbligato', help='voice name, or field 1-8')
    ap.add_argument('--sustain', help='on or off')
    ap.add_argument('--alt-pattern', dest='pattern',
                    help='on or off: play the alternate accompaniment pattern, locked')
    ap.add_argument('--raw', action='append', metavar='FIELD=N', default=[],
                    help='write a field directly, clamped only to its width. '
                         'Fields: %s' % ', '.join(k for k in FIELDS if k != 'alphabet'))
    a = ap.parse_args()

    data = P.check_card(a.card)
    bits = P.tobits(data)
    print('%s  (%d bytes)' % (os.path.basename(a.card), len(data)))
    print()

    try:
        info, notes, warn = F.structure(bits)
    except F.NotACard as e:
        print('  Not a Playcard image, so there is no header to read.')
        print('  The walk got as far as %s, at bit %d: %s' % (e.where, e.bit, e.why))
        print('  Run forge_crc.py on it for the full diagnosis.')
        return 1

    if info['type'] != 1:
        print('  This is a type-%d continuation card. Only a full card carries a header,'
              % info['type'])
        print('  so there is nothing here to show or change.')
        return 1

    print('  HEADER AS IT STANDS')
    show(bits, info)

    c = Clamp()
    edits = []
    new = list(bits)

    if a.tempo is not None:
        v = pick_tempo(a.tempo, c)
        edits.append(('tempo', get(bits, 'tempo'), v, '%d bpm' % P.TEMPO[v]))
        put(new, 'tempo', v)
    if a.rhythm is not None:
        v = pick_rhythm(a.rhythm, c)
        edits.append(('rhythm', get(bits, 'rhythm'), v, P.RHYTHM[P.T640A[v]]))
        put(new, 'rhythm', v)
    if a.transpose is not None:
        v = pick_transpose(a.transpose, c)
        edits.append(('key', get(bits, 'key'), v,
                      '%+d semitones, a card in C sounds in %s'
                      % (P.key_shift(v), P.key_name(v))))
        put(new, 'key', v)
    if a.melody is not None:
        f = pick_voice(a.melody, MELODY_NAMES, P.MELODY_VOICE, 1, 10, 'melody', c)
        v = f + 5                                   # T641A: raw 6..15 -> field 1..10
        edits.append(('melody', get(bits, 'melody'), v, P.voice(P.MELODY_VOICE, f)))
        put(new, 'melody', v)
    if a.obbligato is not None:
        f = pick_voice(a.obbligato, OBB_NAMES, P.OBBLIGATO_VOICE, 1, 8, 'obbligato', c)
        v = f - 1                                   # T642A: raw 0..7 -> field 1..8
        edits.append(('obbligato', get(bits, 'obbligato'), v, P.voice(P.OBBLIGATO_VOICE, f)))
        put(new, 'obbligato', v)
    if a.sustain is not None:
        v = 1 if onoff(a.sustain) else 0
        edits.append(('sustain', get(bits, 'sustain'), v, 'on' if v else 'off'))
        put(new, 'sustain', v)
    if a.pattern is not None:
        v = 2 if onoff(a.pattern) else 0             # the value all five real cards carry
        edits.append(('pattern', get(bits, 'pattern'), v,
                      'ALTERNATE (locked)' if v else 'standard'))
        put(new, 'pattern', v)
    for spec in a.raw:
        if '=' not in spec:
            sys.exit('--raw wants FIELD=N, for example --raw rhythm=13')
        name, _, val = spec.partition('=')
        name = name.strip().lower()
        if name not in FIELDS or name == 'alphabet':
            sys.exit('unknown field %r; choose from: %s'
                     % (name, ', '.join(k for k in FIELDS if k != 'alphabet')))
        width = FIELDS[name][1]
        v = int(val, 0)
        if not 0 <= v < (1 << width):
            v2 = max(0, min((1 << width) - 1, v))
            c.say('raw %s' % name, str(v),
                  '%d (the field is %d bit%s)' % (v2, width, '' if width == 1 else 's'))
            v = v2
        edits.append((name, get(bits, name), v, 'raw, unchecked'))
        put(new, name, v)

    if not edits:
        print()
        print('  no changes requested; pass options such as --tempo or --rhythm to make some')
        return 0

    print()
    print('  CHANGES')
    for name, old, val, desc in edits:
        print('    %-11s %2d -> %-3d  %s' % (name, old, val, desc))
    if c.notes:
        print()
        print('  CLAMPED')
        for n in c.notes:
            print('    %s' % n)

    crc = F.crc_over(new, info['crc_at'])
    for j in range(16):
        new[info['crc_at'] + j] = (crc >> (15 - j)) & 1

    print()
    print('  HEADER AFTER')
    show(new, info)

    if not a.out:
        print()
        print('  nothing written; pass -o to save the modified card')
        return 0

    out = bytearray()
    for i in range(0, len(new), 8):
        v = 0
        for b in new[i:i + 8]:
            v = (v << 1) | b
        out.append(v)
    open(a.out, 'wb').write(bytes(out))
    check = P.parse_card(P.tobits(bytes(out)))
    print()
    print('    -> %s (%d bytes, %d changed), checksum %04X, re-read as %s'
          % (a.out, len(out), sum(1 for x, y in zip(data, out) if x != y), crc,
             'VALID' if check['crc_ok'] else 'INVALID'))
    return 0


if __name__ == '__main__':
    P.run(main)
