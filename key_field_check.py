# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""What is the header's key field actually doing?

    python key_field_check.py
    python key_field_check.py 9to5 summertime      # and name some cards

A card stores its melody and obbligato in one key and its chord chart at
SOUNDING pitch, with a key field that transposes the two note streams and
leaves the chart alone.  Read off a card that looks like an error: melody and
chords in different keys.  It is not, and this measures why.

Three tests.

  BLACK NOTES, as stored against as they sound once the key field is applied.
  How awkward the melody was to play as it is written, which is also what it
  costs to store: a sharp is an opcode of its own.  Nothing here depends on any
  particular machine - the shift is arithmetic every reader of the card does.

  CHORD TONES.  What fraction of melody notes belong to the chord sounding
  under them - the test of whether the melody and the chart agree, which does
  not depend on naming any key at all.

  THE KEY THE CARD IS WRITTEN IN, which is not always C.  A best-fit scale
  cannot tell C major from A minor or G mixolydian, because they are the same
  seven notes, so this takes the tonic from the LAST CHORD of the chart - which
  is at sounding pitch, and so is the one witness the key field never touches -
  and subtracts the shift to get the written key.

The answer, over the corpus: melodies are entered wherever they cost the fewest
accidentals, which is nearly always the white keys, and the key field moves them
where they belong.  See "One claim in the family does not hold for these cards"
in playcard-format.md.
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playcard_decode as P
import playcard_resolve as R
import midi_export as M

# root, third, fifth, seventh for the four types the chart can name
TONES = {0: (0, 4, 7), 1: (0, 3, 7), 2: (0, 4, 7, 10), 3: (0, 3, 7, 10)}
MAJOR = (0, 2, 4, 5, 7, 9, 11)
BLACK = (1, 3, 6, 8, 10)
NAME = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')


def chords_of(h, t2, s1):
    """[(tick, root pitch class, type)] in playback order."""
    durs = [v & 0x7F for k, v in t2 if k == 'byte']
    out, t, i = [], 0, 0
    root = ty = None
    for kind, val in s1:
        if kind == 'byte':
            if i < len(durs):
                t += durs[i]
                i += 1
        elif kind == 'tbl':
            if val == 0xFF:
                root = ty = None
            else:
                note, hi = val & 0x0F, val >> 4
                if note == 3:
                    if root is not None:
                        ty = (ty or 0) | hi
                elif note in P.OPM_INDEX:
                    root, ty = (P.OPM_INDEX[note] + 1) % 12, hi
            out.append((t, root, ty))
    return out


def agreement(mel, chords):
    """What fraction of melody notes are tones of the chord then sounding."""
    if not chords:
        return None
    hit = seen = 0
    ci = 0
    for note in mel:
        start, pitch = note[0], note[2]
        while ci + 1 < len(chords) and chords[ci + 1][0] <= start:
            ci += 1
        t, root, ty = chords[ci]
        if root is None or t > start:
            continue
        seen += 1
        if (pitch - root) % 12 in TONES[ty]:
            hit += 1
    return (hit / float(seen)) if seen else None


def black(mel):
    """(black notes, notes) - what the melody costs to store and to play."""
    return (sum(1 for n in mel if n[2] % 12 in BLACK), len(mel))


def signature(mel):
    """(accidentals, tonic of the cheapest major signature) for these notes.

    Says how many sharps and flats the melody needs, not which key it is in:
    every mode of one signature scores identically, which is the whole
    difficulty and why the tonic has to come from the chart instead."""
    pcs = collections.Counter(n[2] % 12 for n in mel)
    best = None
    for t in range(12):
        scale = set((t + d) % 12 for d in MAJOR)
        miss = sum(n for pc, n in pcs.items() if pc not in scale)
        if best is None or miss < best[0]:
            best = (miss, t)
    return best


def cadence(s1):
    """(tonic, is it minor) from the chart's last chord, or None.

    Songs end on the tonic, and the chart is stored at sounding pitch, so its
    last chord names the key the card SOUNDS in without reference to the field.
    Right on 81% of the corpus, checked against the melody's own last note."""
    for kind, val in reversed(s1):
        if kind != 'tbl' or val == 0xFF:
            continue
        note, ty = val & 0x0F, val >> 4
        if note in P.OPM_INDEX and ty in TONES:
            return (P.OPM_INDEX[note] + 1) % 12, ty in (1, 3)
        return None
    return None


def keyname(tonic, minor):
    return NAME[tonic] + ('m' if minor else '')


def measure(f):
    """Everything the three tests need from one card, or None to skip it."""
    h = M.load(f)
    if h.get('type') != 1 or not h['sections']:
        return None
    sh = M.key_shift(h['transpose'])
    t1, t2, s0, s1 = R.resolve(h)
    written = M.build_part(t1, s0, 0)[0]
    played = M.build_part(t1, s0, sh)[0]
    if not written:
        return None
    ch = chords_of(h, t2, s1)
    end = cadence(s1)
    r = dict(name=os.path.basename(f)[9:-4], shift=sh,
             bw=black(written), bp=black(played),
             aw=agreement(written, ch), ap=agreement(played, ch),
             sig=signature(written), ends=played[-1][2] % 12,
             tonic=None, minor=False, writkey=None)
    if end:
        r['tonic'], r['minor'] = end
        r['writkey'] = (end[0] - sh) % 12
    return r


def pct(rows, get):
    """A percentage over the cards that have the measurement at all."""
    vals = [get(r) for r in rows if get(r) is not None]
    return (100.0 * sum(vals) / len(vals)) if vals else 0.0


def show(r):
    """One card, spelled out."""
    P.say('%s: key field asks for %+d semitones' % (r['name'], r['shift']),
          prefix='')
    if r['writkey'] is not None:
        P.say('written in %s, sounds in %s'
              % (keyname(r['writkey'], r['minor']),
                 keyname(r['tonic'], r['minor'])))
    P.say('black notes  %d of %d as written, %d as played'
          % (r['bw'][0], r['bw'][1], r['bp'][0]))
    P.say('accidentals  %d in the cheapest signature as written' % r['sig'][0])
    if r['aw'] is not None:
        P.say('chord tones  %.0f%% as written, %.0f%% as played'
              % (100 * r['aw'], 100 * r['ap']))
    print('')


def main():
    want = [a.lower() for a in sys.argv[1:]]
    rows = []
    for f in sorted(P.corpus()):
        r = measure(f)
        if r:
            rows.append(r)
            if any(w in f.lower() for w in want):
                show(r)
    if not rows:
        raise P.Missing('no cards to measure.')

    plain = [r for r in rows if not r['shift']]
    moved = [r for r in rows if r['shift']]
    groups = (('key field asks for no shift', plain),
              ('key field asks for a shift', moved))

    print('black notes in the melody\n')
    print('%-30s %6s %10s %9s' % ('', 'cards', 'as written', 'as played'))
    for label, rs in groups:
        if rs:
            print('%-30s %6d %9.1f%% %8.1f%%'
                  % (label, len(rs),
                     pct(rs, lambda r: 100.0 * r['bw'][0] / r['bw'][1]) / 100,
                     pct(rs, lambda r: 100.0 * r['bp'][0] / r['bp'][1]) / 100))

    print('\nmelody notes that are tones of the chord then sounding\n')
    print('%-30s %6s %10s %9s' % ('', 'cards', 'as written', 'as played'))
    for label, rs in groups:
        if rs:
            print('%-30s %6d %9.1f%% %8.1f%%'
                  % (label, len(rs), pct(rs, lambda r: r['aw']),
                     pct(rs, lambda r: r['ap'])))
    better = sum(1 for r in moved
                 if r['aw'] is not None and r['ap'] > r['aw'] + 0.02)
    worse = sum(1 for r in moved
                if r['aw'] is not None and r['ap'] < r['aw'] - 0.02)
    print('\nof the %d shifted cards the shift makes agreement better on %d,'
          % (len(moved), better))
    print('worse on %d, much the same on %d'
          % (worse, len(moved) - better - worse))

    named = [r for r in rows if r['writkey'] is not None]
    sure = sum(1 for r in named if r['ends'] == r['tonic'])
    print('\nwhat key is the card WRITTEN in?\n')
    P.say('Taking the tonic from the chart\'s last chord, which agrees with '
          'the melody\'s own last note on %d of %d cards (%.0f%%).'
          % (sure, len(named), 100.0 * sure / len(named)), prefix='')
    white = [r for r in rows if not r['sig'][1]]
    exact = sum(1 for r in white if not r['sig'][0])
    P.say('The melody as written is cheapest in the signature with no sharps '
          'or flats on %d of the %d cards (%.0f%%), and fits it without a '
          'single accidental on %d of those - it is on the white keys, which '
          'is what makes it cheap to store. But that is a key SIGNATURE, not '
          'a key: those same seven notes are C major, A minor, G mixolydian '
          'and D dorian alike, and the cards use all of them.'
          % (len(white), len(rows), 100.0 * len(white) / len(rows), exact),
          prefix='')
    c = collections.Counter(keyname(r['writkey'], r['minor']) for r in named)
    print('')
    for k, n in c.most_common():
        print('   written in %-4s %3d' % (k, n))
    inc = c.get('C', 0)
    P.say('So "the melodies are written in C" is right for %d of %d and wrong '
          'for %d. Nothing about the format assumes C: the field is a '
          'transposition, and what it transposes FROM is whatever was cheapest '
          'to write down.'
          % (inc, len(named), len(named) - inc), prefix='')


if __name__ == '__main__':
    P.run(main)
