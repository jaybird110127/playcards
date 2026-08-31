#!/usr/bin/env python3
"""Who uses the same-root chord chart entries, and what do they actually do?

    python same_root_entries.py                 # the whole corpus
    python same_root_entries.py fly_me          # one card, chord by chord

Some chart entries name note code 3, which the YM2151 cannot play. They are not
mutes: they mean "the root already sounding, with this quality ORed on", and the
PCS-30 implements exactly that. See "A chart entry on an unplayable root is NOT
a mute" in playcard-format.md.

This walks every card in playback order, tracks the sounding chord, and reports
each one: which cards use them, what the chord was before and after, where in
the bar they sit, and how long they stand before the next chord arrives.

The question it was written to answer was whether they could be cues for the
PC-1000's Chord Lesson - a feature that holds the accompaniment until the player
fingers the chord - since "keep the root and add this quality" is shaped like an
instruction to a pair of hands rather than like harmony. The distribution says
no; the reasoning is in playcard-format.md, and the numbers are here.
"""

import collections
import datetime
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playcard_decode as P
import playcard_resolve as R

QUAL = {0: '', 1: 'm', 2: '7', 3: 'm7'}
BEAT = 24
SAME_ROOT = 3                              # the note code that means "no root"


def family(name):
    """Which set a card belongs to, for asking whose habit this is."""
    n = name[9:-4] if name.startswith('playcard_') else name
    if n.startswith('pc-1000-japan'):
        return 'pc-1000 (Japan)'
    if n.startswith('pc-100_'):
        return 'pc-100'
    if n.startswith('pcs-30_'):
        return 'pcs-30'
    if '_german-' in n:
        return 'german'
    if 'step-by-step' in n:
        return 'step-by-step'
    m = re.match(r'(17-\d+)_', n)
    return '17-5xx albums' if m else n


def date_of(data):
    nib = [int(c, 16) for c in data[-3:].hex().upper()]
    try:
        return datetime.date(1980 + nib[4], nib[3], nib[2] * 10 + nib[1])
    except ValueError:
        return None


def walk(path):
    """(header, [(tick, chart value)] in playback order, ticks to the bar)."""
    h = P.parse_card(P.tobits(P.check_card(path)))
    if h.get('type') != 1 or not h['sections']:
        return None, None, None
    t1, t2, s0, s1 = R.resolve(h)
    durs = [v & 0x7F for k, v in t2 if k == 'byte']
    out, t, i = [], 0, 0
    for kind, val in s1:
        if kind == 'byte':
            if i < len(durs):
                t += durs[i]
                i += 1
        elif kind == 'tbl':
            out.append((t, val))
    return h, out, (72 if h['rhythm'] == 7 else 96)


def entries(path):
    """Every same-root entry on one card, with what it did."""
    h, chords, bar = walk(path)
    if h is None:
        return None, []
    root = ty = None
    out = []
    for k, (t, v) in enumerate(chords):
        if v == 0xFF:                      # the accompaniment mute
            root = ty = None
            continue
        note, hi = v & 0x0F, v >> 4
        if note == SAME_ROOT:
            before = (root, ty)
            if root is not None:
                ty = (ty or 0) | hi
            gap = None
            for t2, v2 in chords[k + 1:]:  # the next entry that is not one of these
                if v2 == 0xFF or (v2 & 0x0F) != SAME_ROOT:
                    gap = t2 - t
                    break
            out.append(dict(tick=t, bar=bar, val=v, before=before,
                            after=(root, ty), gap=gap))
        elif note in P.OPM_INDEX:
            root, ty = note, hi
    return h, out


def name_of(pair):
    """The chord's name.  `root` is the chip's note code, not a scale degree."""
    root, ty = pair
    return P.NOTE_NAME[root] + QUAL[ty] if root is not None else '-'


def detail(path):
    """One card's chart in playback order, with the same-root entries marked."""
    h, chords, bar = walk(path)
    if h is None:
        print('%s carries no chart' % os.path.basename(path))
        return
    print('%s  (%s)' % (os.path.basename(path)[9:-4], P.RHYTHM[h['rhythm']]))
    print('%-9s %-6s %-9s %-9s' % ('bar.beat', 'raw', 'means', 'sounding'))
    root = ty = None
    for t, v in chords:
        flag = ''
        if v == 0xFF:
            means, root, ty = 'mute', None, None
        elif (v & 0x0F) == SAME_ROOT:
            before = (root, ty)
            if root is not None:
                ty = (ty or 0) | (v >> 4)
            means = 'OR %s' % (QUAL[v >> 4] or 'major')
            flag = '  <== same-root%s' % ('   (no change)' if before == (root, ty) else '')
        elif (v & 0x0F) in P.OPM_INDEX:
            root, ty = v & 0x0F, v >> 4
            means = 'chord'
        else:
            means = '?'
        print('%-9s 0x%02X   %-9s %-9s%s'
              % ('%d.%s' % (t // bar + 1, round(t % bar / float(BEAT) + 1, 2)),
                 v, means, name_of((root, ty)), flag))
    print('')


def main():
    try:
        files = sorted(P.corpus())
    except P.Missing as e:
        sys.exit(str(e))

    if len(sys.argv) > 1:
        if os.path.isfile(sys.argv[1]):          # a path, e.g. a card in new-cards/
            detail(sys.argv[1])
            return
        if os.path.exists(sys.argv[1]):          # there, but not a file
            P.check_card(sys.argv[1])
        hit = [f for f in files if sys.argv[1] in os.path.basename(f)]
        if not hit:
            sys.exit('no card matching %r' % sys.argv[1])
        for f in hit:
            detail(f)
        return

    rows, by_family, users = [], collections.Counter(), collections.Counter()
    for f in files:
        h, mine = entries(f)
        if h is None:
            continue
        fam = family(os.path.basename(f))
        by_family[fam] += 1
        if mine:
            users[fam] += 1
            rows.append((os.path.basename(f)[9:-4], date_of(open(f, 'rb').read()),
                         P.RHYTHM[h['rhythm']], mine))

    hits = [r for _, _, _, m in rows for r in m]
    print('%d same-root entries on %d cards, in playback order\n' % (len(hits), len(rows)))

    print('=== which cards')
    print('%-52s %-11s %-11s %5s %5s' % ('card', 'date', 'rhythm', 'used', 'inert'))
    for n, d, r, m in sorted(rows, key=lambda x: (x[1] or datetime.date(1900, 1, 1))):
        inert = sum(1 for e in m if e['before'] == e['after'])
        print('%-52s %-11s %-11s %5d %5d' % (n[:52], d or '?', r, len(m), inert))

    print('\n=== whose habit is it')
    print('%-16s %6s %6s' % ('set', 'cards', 'using'))
    for fam in sorted(by_family):
        print('%-16s %6d %6d' % (fam, by_family[fam], users[fam]))

    print('\n=== what the entry does to the chord')
    moves = collections.Counter()
    for e in hits:
        b, a = e['before'], e['after']
        if b[0] is None:
            moves['no chord sounding'] += 1
        elif b == a:
            moves['%s, unchanged' % (QUAL.get(b[1]) or 'major')] += 1
        else:
            moves['%s -> %s' % (QUAL.get(b[1]) or 'major', QUAL.get(a[1]))] += 1
    for k, v in moves.most_common():
        print('  %-24s %d' % (k, v))
    inert = sum(1 for e in hits if e['before'] == e['after'])
    print('  %-24s %d of %d (%.0f%%)' % ('changing nothing', inert, len(hits),
                                         100.0 * inert / len(hits)))

    print('\n=== where in the bar, and how long it stands')
    for label, want in (('changes the chord', False), ('changes nothing', True)):
        g = sorted(e['gap'] for e in hits
                   if (e['before'] == e['after']) == want and e['gap'] is not None)
        if not g:
            continue
        print('  %-18s n=%-3d median %.2f beats to the next chord, %d%% within a beat'
              % (label, len(g), g[len(g) // 2] / float(BEAT),
                 100 * sum(1 for x in g if x <= BEAT) // len(g)))
    pos = collections.Counter(round(e['tick'] % e['bar'] / float(BEAT) + 1, 2) for e in hits)
    print('  beat: %s' % ', '.join('%s x%d' % (k, pos[k]) for k in sorted(pos)))
    print('  on a bar line: %d' % pos.get(1.0, 0))


if __name__ == '__main__':
    P.run(main)
