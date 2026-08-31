#!/usr/bin/env python3
"""Generate random but structurally valid Playcards, to put a keyboard through
its paces.

    python make_random_card.py                    # one card into random-cards/
    python make_random_card.py -n 20              # twenty of them
    python make_random_card.py --seed 1234        # reproduce one exactly

The music is nonsense on purpose.  What these cards are for is *coverage*: every
header field takes a value from its whole legal range, both streams carry notes,
rests, octave moves and accidentals, the obbligato carries bar marks and control
opcodes, and the chord chart changes under it - so a keyboard reading one has to
exercise most of what the format can ask for.

Nonsense, but PLAYABLE nonsense.  The pitches stay where these keyboards expect
them - melody G3 to C6, obbligato C2 to C6, as SOUNDING pitch, so the key
field's transposition is taken into account.  The octave register is tracked the
way the cartridge tracks it and the modifiers emitted are the ones that keep the
next note in range, rather than random moves that let it wander off.  The chord
chart needs no such care: it stores a pitch CLASS and no octave, so it can only
ever produce C3..A4 whatever the card asks for.

The check that matters happens after resolution, not during generation: a repeat
replays its body with the octave register carried over, so a card can be laid
out inside the range and still stray once its spans expand.  Every card is
resolved and its real sounding range measured before it is kept.

Each card also gets its own **shape**, not just its own values.  A generator
that always put a fill at bar 16 and a mute at bar 27 would test one structure
267 times; instead every card draws a profile first - how long it is, how often
marks appear, whether it uses repeat spans at all, how restless the melody is,
how often the harmony moves - and only then fills that shape in.  Two cards from
different seeds differ in their layout, not merely their notes.

Validity is not assumed.  `playcard_encode.build()` re-parses each image and
checks the CRC and that every duration track pairs one-to-one with its pitch
stream; anything that fails is discarded and redrawn, so what lands on disk is
a card the UPA-01 will accept - which is the machine its parser can be run
against, and the nearest thing to a guarantee this project can give.

About half these cards carry a repeat span that GENUINELY REPLAYS, at about the
same expansion ratio as the originals.  Two rules make that work, and both are
easy to get wrong - see "the body is the tail" in ../playcard-format.md:

  * the span body is the material AFTER the last marker, so the markers go early
    and the tail is what gets replayed, k markers giving k-1 replays;
  * a track carrying any marker needs TWO terminators, because a marker leaves a
    pending flag and the first 0xE1 is spent closing the span rather than ending
    the track.  Emit one and the parse runs on into the next track.

The cards are ours - generated here, not Yamaha's - but they are still card
images, so `random-cards/` is gitignored like the rest.
"""

import argparse
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playcard_decode as P
import playcard_encode as E
import playcard_resolve as R
import midi_export as M

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'random-cards')

MAX_BYTES = 433              # the longest card in the corpus; the strip runs out
MAX_ALPHABET = 25            # the size field is rejected at 26

# Durations from the master table, and the same values with the LIFT bit set.
PLAIN = [6, 8, 12, 16, 18, 24, 36, 48, 72, 96]
NOTE_CODES = [10, 13, 14, 1, 4, 5, 8]         # A B C D E F G, as YM2151 codes
KEYS = [0, 1, 2, 4, 5, 6, 8, 9, 10, 12, 13, 14]   # the chip's used note codes
CHORD_TYPES = [0, 1, 2, 3]                    # major, minor, seventh, minor 7th

# The range these keyboards expect, as SOUNDING pitch - after the key field's
# transposition, which is what the instrument actually plays.  The chord chart
# needs no such limit: it carries a pitch CLASS and no octave, so it can only
# ever produce C3..A4 whatever the card asks for.
MEL_LO, MEL_HI = 55, 84                       # G3 .. C6
OBB_LO, OBB_HI = 36, 84                       # C2 .. C6
START_OCTAVE = 4                              # the register's initial value


def note_midi(octave, code, sharp, shift):
    """The sounding pitch of one note, by midi_export's own formula."""
    return 12 * (octave + 1) + P.OPM_INDEX[code] + 1 + sharp + shift


def octave_window(code, sharp, shift, lo, hi):
    """Octave-register values that keep this note inside the range."""
    k = P.OPM_INDEX[code] + 1 + sharp + shift
    omin = -(-(lo - k) // 12) - 1             # ceil division
    omax = (hi - k) // 12 - 1
    return omin, omax


def profile(rng):
    """The card's shape, drawn before any of its contents."""
    rhythm = rng.randrange(10)                # raw 0..9 -> style 1..10
    waltz = (rhythm + 1) == 7
    return dict(
        rhythm=rhythm,
        bar_ticks=72 if waltz else 96,
        bars=rng.randint(6, 32),
        tempo=rng.randrange(32),
        mel_voice=rng.randint(6, 15),         # raw -> field 1..10
        obb_voice=rng.randrange(8),           # raw -> field 1..8
        key=rng.choice(KEYS),
        sustain=rng.randrange(2),
        f3=rng.choice([0, 0, 0, 2]),          # the alternate-pattern lock is rare
        # how busy each part is
        mel_rest=rng.uniform(0.05, 0.45),
        obb_rest=rng.uniform(0.05, 0.55),
        mel_short=rng.uniform(0.2, 0.9),      # bias toward short notes
        obb_short=rng.uniform(0.2, 0.9),
        lift=rng.uniform(0.1, 0.8),
        octave_move=rng.uniform(0.02, 0.25),
        sharpen=rng.uniform(0.0, 0.2),
        # what the obbligato asks the accompaniment to do
        mark_bars=rng.uniform(0.0, 0.6),      # fraction of bars carrying a mark
        mark_pool=rng.sample(range(8), rng.randint(1, 8)),
        ctl=rng.uniform(0.0, 0.3),
        chord_bars=rng.uniform(0.15, 1.0),    # fraction of bars changing chord
        mute=rng.uniform(0.0, 0.25),
        repeats=rng.random() < 0.5,
    )


def settle(pr):
    """A part that will carry a repeat moves its octave register sparingly.

    A span replays the body with the register carried over, so whatever the body
    does to it happens again on every pass and the part drifts out of the
    keyboard's range.  Real cards avoid this by moving the octave rarely inside
    a repeated stretch; keeping the move rate low here does the same, and stops
    the range check from throwing away nearly every card that has a span."""
    if pr['repeats']:
        pr['octave_move'] *= 0.2
    return pr


def fill_bar(rng, ticks, short_bias, lift):
    """Durations that add up to exactly one bar."""
    out = []
    left = ticks
    while left > 0:
        choices = [d for d in PLAIN if d <= left]
        if not choices:
            break
        # short_bias pulls the choice toward the front of the list
        i = int(len(choices) * min(0.999, rng.random() ** (1.0 / (1.0 - short_bias * 0.9))))
        d = choices[min(i, len(choices) - 1)]
        out.append(d | (0x80 if rng.random() < lift else 0))
        left -= d
    return out


def make_part(rng, pr, obbligato):
    """One part: its durations, its opcodes, and where its bar lines fall.

    The octave register is tracked as the cartridge tracks it, and every note is
    placed inside the keyboard's range: the modifiers emitted are the ones that
    get there, rather than random moves that let the register wander off."""
    rest_p = pr['obb_rest'] if obbligato else pr['mel_rest']
    short = pr['obb_short'] if obbligato else pr['mel_short']
    lo, hi = (OBB_LO, OBB_HI) if obbligato else (MEL_LO, MEL_HI)
    shift = P.key_shift(pr['key'])
    durs, ops, bar_at, ev_at = [], [], [], []
    octave = START_OCTAVE

    for bar in range(pr['bars']):
        bar_at.append(len(ops))
        if obbligato and rng.random() < pr['mark_bars']:
            ops.append(('mark', rng.choice(pr['mark_pool'])))
        if obbligato and rng.random() < pr['ctl']:
            ops.append(('ctl', rng.choice([0x11, 0x13, 0x14])))
        for d in fill_bar(rng, pr['bar_ticks'], short, pr['lift']):
            ev_at.append(len(ops))       # where this event's opcodes begin
            durs.append(d)
            if rng.random() < rest_p:
                ops.append(('rest', None))
                continue
            code = rng.choice(NOTE_CODES)
            sharp = 1 if rng.random() < pr['sharpen'] else 0
            omin, omax = octave_window(code, sharp, shift, lo, hi)
            if omin > omax:                          # this note cannot fit at all
                ops.append(('rest', None))
                continue
            want = octave
            if rng.random() < pr['octave_move']:
                want += rng.choice([1, -1])
            want = max(omin, min(omax, want))
            while octave < want:
                ops.append(('oct', 1))               # raise the register
                octave += 1
            while octave > want:
                ops.append(('oct', 2))               # lower it
                octave -= 1
            if sharp:
                ops.append(('oct', 0))               # sharpen the next note only
            ops.append(('note', code))
    return durs, ops, bar_at, ev_at


# Duration-track symbol that opens each repeat span, and the span it opens.
SPAN_SYM = {0: 0xF0, 1: 0xF2, 2: 0xF4, 3: 0xF6}


def add_repeat(rng, durs, ops, ev_at, span):
    """Put a genuinely repeating span into one part.

    The shape is the one the real cards use, and it is not the obvious one: the
    markers go EARLY and the material they replay is the **tail after the last
    marker**, not the stretch between them.  Every marker but the last becomes a
    call to just past the last, and the last becomes the return that ends the
    track - so with k markers the body is played k-1 times, interleaved with the
    short segments that sit between the markers, and is not played again at the
    end.

        seg1 [call] seg2 [call] seg3 [return] BODY...

    Put the body before the markers instead and the calls replay nothing, which
    is what made an earlier version of this generator emit spans that resolved
    to identity.  The body's own closing record is what lets a call return, and
    the encoder's terminator supplies it - so a part built this way must NOT
    also be wrapped in terminated(), which would add a second span.
    """
    n_ev = len(ev_at)
    k = rng.choice([3, 3, 4])
    if n_ev < k * 2 + 6:
        return False
    # markers in the first part of the track, leaving a body worth replaying
    limit = max(k, int(n_ev * rng.uniform(0.25, 0.5)))
    pts = sorted(rng.sample(range(1, limit), k))
    for ev in sorted(pts, reverse=True):
        ops.insert(ev_at[ev], ('loop', span))
        durs.insert(ev, SPAN_SYM[span])
    # A marker leaves a pending flag (playcard_decode.parse_track, ROM 0x636F)
    # and the next 0xE1 is spent CLOSING the span rather than ending the track.
    # So a track carrying any marker needs two terminators: this one to close,
    # and the encoder's own to end.  Real cards show it - Silent Night's melody
    # track ends `... 18 END END`.  Emit only one and the parse runs straight on
    # into the next track.
    durs.append(0xE1)
    ops.append(('loopend', None))
    return True


def nibble_positions(ops):
    """Opcode index of each op, counting 4-bit reads - an escape costs two."""
    pos, n = [], 1
    for kind, val in ops:
        pos.append(n)
        n += 2 if kind in ('mark', 'loop') else 1
    return pos


def make_chart(rng, pr, ops, bar_at):
    """Chords hung on the obbligato's bar lines, with the odd mute."""
    pos = nibble_positions(ops)
    chart, last = [], None
    for bar, idx in enumerate(bar_at):
        if bar and rng.random() > pr['chord_bars']:
            continue
        if bar and rng.random() < pr['mute']:
            value = 0xFF                                  # accompaniment mute
        else:
            value = (rng.choice(CHORD_TYPES) << 4) | rng.choice(KEYS)
        if value == last:
            continue
        chart.append((value, pos[idx] if idx < len(pos) else 1))
        last = value
    if not chart:
        chart = [((rng.choice(CHORD_TYPES) << 4) | rng.choice(KEYS), 1)]
    return chart


def build_alphabet(mel_durs, obb_durs, extra):
    """Symbols in use, most-frequent-first, as the real cards order them."""
    counts = {}
    for d in list(mel_durs) + list(obb_durs):
        counts[d] = counts.get(d, 0) + 1
    for sym in extra:
        counts.setdefault(sym, 0)
    counts.setdefault(0xE1, 10 ** 6)                      # the terminator is common
    order = sorted(counts, key=lambda s: (-counts[s], s))
    return order


def one_card(seed):
    """Draw a card, or None if this seed produces one that will not fit."""
    rng = random.Random(seed)
    pr = settle(profile(rng))

    mel_durs, mel_ops, _, mel_ev = make_part(rng, pr, obbligato=False)
    obb_durs, obb_ops, obb_bars, obb_ev = make_part(rng, pr, obbligato=True)

    # A part with a real span terminates through that span's return; one without
    # needs terminated() to supply a return of its own.
    spans, looped = [], {'mel': False, 'obb': False}
    if pr['repeats']:
        for span, key, d, o, e in ((1, 'mel', mel_durs, mel_ops, mel_ev),
                                   (2, 'obb', obb_durs, obb_ops, obb_ev)):
            if rng.random() < 0.75 and add_repeat(rng, d, o, e, span):
                spans.append(SPAN_SYM[span])
                looped[key] = True

    chart = make_chart(rng, pr, obb_ops, obb_bars)

    alphabet = build_alphabet(mel_durs, obb_durs, [0xE1] + spans)
    if len(alphabet) > MAX_ALPHABET:
        return None, pr

    card = E.Card(
        tempo=pr['tempo'], rhythm=pr['rhythm'], f3=pr['f3'],
        mel_voice=pr['mel_voice'], sustain=pr['sustain'],
        obb_voice=pr['obb_voice'], key=pr['key'],
        alphabet=alphabet,
        mel_durs=mel_durs, obb_durs=obb_durs,
        mel_ops=mel_ops if looped['mel'] else E.terminated(mel_ops),
        obb_ops=obb_ops if looped['obb'] else E.terminated(obb_ops),
        chart=chart)
    try:
        data = E.build(card)                              # re-parses and checks
    except Exception:
        return None, pr
    if len(data) > MAX_BYTES:
        return None, pr
    if not in_range(data):
        return None, pr
    return data, pr


def part_range(data):
    """The sounding range each part actually reaches, in playback order.

    Measured after resolution rather than during generation, because a repeat
    replays material with the octave register carried over - so a card can be
    laid out inside the range and still stray once the spans expand."""
    h = P.parse_card(P.tobits(data))
    key = h['transpose'] if h['transpose'] >= 0 else h['transpose'] + 16
    shift = P.key_shift(key)
    t1, t2, s0, s1 = R.resolve(h)
    out = []
    for stream in (s0, s1):
        notes = [m + shift for m in M.pitch_events(stream) if m is not None]
        out.append((min(notes), max(notes)) if notes else None)
    return out


def in_range(data):
    mel, obb = part_range(data)
    if mel and not (MEL_LO <= mel[0] and mel[1] <= MEL_HI):
        return False
    if obb and not (OBB_LO <= obb[0] and obb[1] <= OBB_HI):
        return False
    return True


def describe(path, pr):
    h = P.parse_card(P.tobits(open(path, 'rb').read()))
    import playcard_resolve as R
    t1, t2, s0, s1 = R.resolve(h)
    # h['transpose'] is ALREADY signed, so it has to go back to the raw note
    # code before key_shift sees it - that function returns 0 for anything not
    # in the table, which would silently report every negative key as C.
    raw_key = h['transpose'] if h['transpose'] >= 0 else h['transpose'] + 16
    marks = sorted({v for k, v in s1 if k == 'ctl' and v < 8})
    ctl = sorted({v for k, v in s1 if k == 'ctl' and v >= 8})
    chart = h['sections'][0][0]
    mutes = sum(1 for v, _ in chart if v == 0xFF)
    print('  %-34s %3d bytes  CRC %s' % (os.path.basename(path), os.path.getsize(path),
                                         'VALID' if h['crc_ok'] else 'FAILED'))
    print('     %3d bpm  %-11s %-9s key %+d  sustain %-3s  %s'
          % (h['tempo'], P.RHYTHM[h['rhythm']],
             '%d bars' % pr['bars'], P.key_shift(raw_key),
             'on' if h['bit1'] else 'off',
             'ALTERNATE pattern' if h['f3'] else 'standard pattern'))
    print('     melody %-8s obbligato %-8s  %d/%d events'
          % (P.voice(P.MELODY_VOICE, h['field4']),
             P.voice(P.OBBLIGATO_VOICE, h['field6']),
             len(h['track1']), len(h['track2'])))
    spans = sorted({v for st in h['sections'][0][1] for k, v in st
                    if k == 'loop' and v != 0})
    print('     repeat spans %-9s' % (spans or 'none'), end='')
    mr, orr = part_range(open(path, 'rb').read())
    nm = lambda m: '%s%d' % (['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#',
                             'A', 'A#', 'B'][m % 12], m // 12 - 1)
    print('     range  melody %-11s obbligato %-11s'
          % ('%s..%s' % (nm(mr[0]), nm(mr[1])) if mr else 'silent',
             '%s..%s' % (nm(orr[0]), nm(orr[1])) if orr else 'silent'))
    print('     marks %-22s control %-14s chords %d (%d mute%s)'
          % (marks or 'none', ['%02X' % c for c in ctl] or 'none',
             len(chart), mutes, '' if mutes == 1 else 's'))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('-n', '--count', type=int, default=1)
    ap.add_argument('--seed', type=int, help='reproduce one specific card')
    ap.add_argument('-o', '--out-dir', default=OUT_DIR)
    a = ap.parse_args()

    os.makedirs(a.out_dir, exist_ok=True)
    made, tries = 0, 0
    seed = a.seed if a.seed is not None else random.randrange(1 << 30)
    print('Generating %d random Playcard%s into %s'
          % (a.count, '' if a.count == 1 else 's', a.out_dir))
    print()
    while made < a.count and tries < a.count * 200:
        tries += 1
        data, pr = one_card(seed)
        if data is None:
            seed = random.randrange(1 << 30) if a.seed is None else seed + 1
            continue
        path = os.path.join(a.out_dir, 'playcard_random_%08x.bin' % seed)
        with open(path, 'wb') as f:
            f.write(data)
        describe(path, pr)
        made += 1
        seed = random.randrange(1 << 30) if a.seed is None else seed + 1
    print()
    print('%d card%s written, %d draws discarded as too large or invalid'
          % (made, '' if made == 1 else 's', tries - made))


if __name__ == '__main__':
    P.run(main)
