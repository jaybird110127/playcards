#!/usr/bin/env python3
"""
Repeat-span expansion for Yamaha Playcards.

The card streams are not stored in playback order.  A repeat span is stored
once as a *definition* and referenced from the places it should sound, so a
raw scan of a stream will not find any phrase that spans a reference.

Semantics, recovered from the marker layout and confirmed against a known
performance (see verify_silent_night below):

    LOOPn ... END      a definition.  The END closes the nearest preceding
                       LOOP marker; that marker's n names the span.
    LOOPn  (no END)    a call.  Splice span n in at this point.

Definitions are skipped where they sit in the stream - they only sound where
they are called.  The same marker vocabulary appears in the duration tracks
(0xF0/F2/F4/F6 open, 0xE1 closes), so both halves expand with one routine.

SUPERSEDED, in part.  Running a card through the real cartridge under openMSX
(see fake_cr01.tcl) shows the decoded buffer resolves every repeat marker into
a call with a 16-bit ABSOLUTE ADDRESS, with 0xE1 0x10 as the return.  The
call/definition model below is structurally right but has to guess targets,
which is exactly why it fails where a span is defined twice or stored out of
order.  Prefer the emulator dump when you need true playback order.

STATUS of this approximation.

It is exactly right on Silent Night's obbligato, which expands to the recorded
performance with note and duration counts balancing exactly.  It is WRONG on
I Write the Songs: that card's second ending is stored at ops 9-27, near the
front, with no END marker anywhere near it, and the three LOOP0 markers that
reference it have no END in the stream at all.  So the definition rule cannot
see it, and expansion leaves the ending stranded at the front while shrinking a
melody that should double.  No simple bracket language covers both cards; the
position table (merged inline by position during decode) is the remaining
candidate for what actually sequences playback.

Beware the count metric.  I Write the Songs balances to within one event after
expansion while being musically wrong, so agreement measures consistency, not
correctness.  Corpus-wide, expansion moves agreement from 22% to 30% of halves.

Known failure modes: span numbers defined more than once (Silent Night's melody
defines span 1 twice; the rule keeps only the last and loses the first body),
and out-of-order material carrying no END.  Six alternative bindings were
measured and none beat this one - first-definition-wins 29%,
nearest-following-definition 27%, definitions also sounding where stored 10%,
uncalled-only 30%.

Usage:
    python playcard_expand.py <file.bin>    # expanded melody / obbligato
    python playcard_expand.py --verify      # corpus-wide agreement check
"""

import sys, os
import playcard_decode as P

LETTER = '- A B C D E F G'.split()
PITCHVAL = [3, 10, 13, 14, 1, 4, 5, 8]        # P.OP07, opcode order


# ---------------------------------------------------------------- expansion

def _spans(items, is_loop, is_end):
    """Locate definitions.  Returns {n: (start, end)} and the set of
    indices that begin a definition, so the walker can skip them."""
    defs, defstart = {}, {}
    for i, x in enumerate(items):
        if not is_end(x):
            continue
        # the definition is the last loop marker before this END.
        # note: span 0 is falsy, so this must test against None explicitly
        j = i - 1
        while j >= 0 and is_loop(items[j]) is None:
            j -= 1
        if j < 0:
            continue                      # END with no opener: track terminator
        n = is_loop(items[j])
        if n is None:
            continue
        defs[n] = (j + 1, i)              # body sits between marker and END
        defstart[j] = i
    return defs, defstart


def expand(items, is_loop, is_end, depth=0, limit=20000):
    """Return items in playback order, with calls spliced and definitions
    skipped where they are stored."""
    defs, defstart = _spans(items, is_loop, is_end)
    out, i = [], 0
    while i < len(items):
        if len(out) > limit:
            break
        x = items[i]
        if i in defstart:                 # a definition: not sounded here
            i = defstart[i] + 1
            continue
        n = is_loop(x)
        if n is not None and n in defs and depth < 8:
            a, b = defs[n]
            out.extend(expand(items[a:b], is_loop, is_end, depth + 1, limit))
            i += 1
            continue
        if n is not None or is_end(x):    # unmatched marker: drop it
            i += 1
            continue
        out.append(x)
        i += 1
    return out


# ---- the two concrete flavours -------------------------------------------

def _op_loop(x):  return x[1] // 2 if x[0] == 'loop' else None
def _op_end(x):   return x[0] == 'loopend'

def expand_stream(ops):
    return expand(ops, _op_loop, _op_end)


def _dur_loop(x): return (x - 0xF0) // 2 if 0xF0 <= x <= 0xF6 else None
def _dur_end(x):  return x == 0xE1

def expand_track(tr):
    # the final 0xE1 terminates the track rather than closing a span
    if tr and tr[-1] == 0xE1:
        tr = tr[:-1]
    return expand(tr, _dur_loop, _dur_end)


# ---------------------------------------------------------------- readout

def notes(ops):
    """Expanded stream -> a readable note list.  Letters only: the octave
    and accidental modifiers are shown as they occur, not resolved, because
    the octave semantics of modifier 1 vs 2 is still open."""
    out = []
    for k, v in ops:
        if k == 'pitch':
            out.append(LETTER[PITCHVAL.index(v)])
        elif k == 'oct':
            out.append({0: '#', 1: '^', 2: 'v'}[v])
        elif k == 'mark':
            out.append('{fill%d}' % v)
        elif k == 'ctl':
            out.append('{c%02X}' % v)
    return out


def counts(h):
    """Event counts after expansion, for the melody and obbligato halves."""
    r = []
    for tr, sect in ((h.get('track1'), 0), (h.get('track2'), 1)):
        if tr is None or not h['sections']:
            return None
        d = [x for x in expand_track(tr)]
        s = expand_stream(h['sections'][0][1][sect])
        r.append((sum(1 for x in d if x < 0xE1),
                  sum(1 for k, v in s if k == 'pitch')))
    return r


# ---------------------------------------------------------------- checks

def verify_silent_night():
    """The one passage with an external performance to check against."""
    f = [x for x in P.corpus() if 'silent_night' in x]
    if not f:
        return
    h = P.parse_card(P.tobits(open(f[0], 'rb').read()))
    seq = ''.join(x for x in notes(expand_stream(h['sections'][0][1][1]))
                  if x in 'ABCDEFG')
    body = 'FFAABCDDEFEC'
    want = body + 'EGEDC' + body + 'BAGEC'
    at = seq.find(want)
    print('Silent Night obbligato, expanded')
    print('  expect  body + E G E D C + body + B A G E C')
    print('  found   %s' % ('YES at offset %d' % at if at >= 0 else 'NO'))
    if at < 0:
        i = seq.find(body)
        print('  body alone: %s' % ('at %d' % i if i >= 0 else 'absent'))
    return at >= 0


def verify_corpus():
    """Does expansion make the two halves of a card agree?

    Duration events and note opcodes should pair one-to-one.  Before
    expansion they matched on 37% of cards; that number is the control.
    """
    before = after = total = 0
    for p in P.corpus():
        try:
            h = P.parse_card(P.tobits(open(p, 'rb').read()))
        except P.Over:
            continue
        if h['type'] != 1 or not h['sections']:
            continue
        total += 1
        for i, tr in enumerate((h['track1'], h['track2'])):
            raw_d = sum(1 for x in tr if x < 0xE1)
            raw_s = sum(1 for k, v in h['sections'][0][1][i] if k == 'pitch')
            if raw_d == raw_s:
                before += 1
        c = counts(h)
        if c:
            for d, s in c:
                if d == s:
                    after += 1
    print('cards checked            : %d  (%d halves)' % (total, 2 * total))
    print('halves agreeing, raw     : %d  (%.0f%%)' % (before, 100 * before / (2 * total)))
    print('halves agreeing, expanded: %d  (%.0f%%)' % (after, 100 * after / (2 * total)))


def dump(path):
    h = P.parse_card(P.tobits(P.check_card(path)))
    print('=' * 72)
    print(os.path.basename(path))
    print('=' * 72)
    if h['type'] != 1 or not h['sections']:
        print('  continuation card')
        return
    print('  key field %d   melody voice %d   obbligato voice %d   %s'
          % (h['transpose'], h['field4'], h['field6'], P.RHYTHM[h['rhythm']]))
    for i, name in enumerate(('melody', 'obbligato')):
        raw = h['sections'][0][1][i]
        ex = expand_stream(raw)
        d = expand_track(h['track1'] if i == 0 else h['track2'])
        nd = sum(1 for x in d if x < 0xE1)
        ns = sum(1 for k, v in ex if k == 'pitch')
        print()
        print('  -- %s: %d ops raw -> %d expanded, %d notes vs %d durations %s'
              % (name, len(raw), len(ex), ns, nd, 'OK' if ns == nd else 'MISMATCH'))
        print('  ' + ' '.join(notes(ex)))


def _main():
        a = sys.argv[1:]
        if a and a[0] == '--verify':
            verify_silent_night()
            print()
            verify_corpus()
        elif a:
            for x in a:
                dump(x)
        else:
            print(__doc__)


if __name__ == '__main__':
    P.run(_main)
