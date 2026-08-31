#!/usr/bin/env python3
"""
Compile a four-channel MIDI file into a Yamaha Playcard image.

    python midi_compile.py song.mid -o song.bin
    python midi_compile.py song.mid --tempo 120 --rhythm swing
    python midi_compile.py song.mid --melody-voice clarinet --obbligato-voice strings
    python midi_compile.py --roundtrip          # decompile and recompile the corpus

The inverse of card_decompile.py.  Read playcard_midi.py for the channel layout
and the control-note map, midi-roundtrip-design.md for the plan, and
playcard-format.md for the format.

THE HEADER, FROM THE FILE OR FROM THE COMMAND LINE

A decompiled .mid carries its card's header in two meta text events, and a file
written by hand may carry neither.  **Everything either line can say has a
command-line option**, and the option wins where both are given:

    tempo=      --tempo         melody=       --melody-voice
    rhythm=     --rhythm        obbligato=    --obbligato-voice
    transpose=  --transpose     sustain=      --sustain
    pattern=    --pattern       (and --raw k=v for a raw field value)

Voices take either vocabulary - `clarinet` or the SFG-01's `CLARINE` - or a
field number.  Anything not given by either route keeps its default.

A CARD THAT WILL NOT FIT MAY FIT IN ANOTHER KEY

The key field transposes the melody and the obbligato at playback and leaves the
chord chart alone, so the value it carries makes no difference at all to how the
card SOUNDS.  It makes a great deal of difference to how big it is: every
accidental in the stored stream needs a sharp modifier of its own, so the same
music can differ by a fifth of the strip between its best key and its worst.
One corpus card runs 385 bytes at +3 and 480 at -3.

So when a card comes out over 433 bytes it is recompiled at each of the other
eleven keys and the smallest that fits is kept, before falling back to splitting
it over two sides.  The report says what happened, and a MIDI of nothing but
black keys shows why it is worth doing:

    452 bytes at the key asked for and 304 at -1 semitones, so the card was
    written in that key instead - it sounds the same, and the header says so

`--no-refit` turns it off and leaves the key exactly as asked.

CHANNELS, NOT TRACKS

Melody on channel 1, obbligato on 2, the chord chart on 3, control notes on 4.
Nothing here looks at track structure, so a file with one track per channel and
a file with everything on a single track compile to the same card.

WHAT A CARD CANNOT CARRY

The complaints are the point.  A MIDI file can ask for a great many things this
format has no way to store, and every one of them is reported rather than
quietly rounded away:

  * ten durations and nothing else - no 32nds, no 16th triplets, no dotted
    16ths.  Anything else is quantised, and every note that moved is named.
  * NO POSITIONS.  A part is a gapless run of durations, so where a note falls
    is the sum of everything before it and an onset off the grid cannot be
    stored as it stands.  That matters far more than it sounds: chords and bar
    marks are placed at the OBBLIGATO EVENT under them rather than at a time,
    so a nudged obbligato note can leave a chord with nothing to sit on, and
    it then slides to the next event - which may be most of a bar away.  Tell
    people to quantise before exporting; it is the one mistake that yields a
    card which compiles cleanly and puts the harmony in the wrong place.
  * one note at a time in the melody and in the obbligato.  Overlaps are
    reduced by keeping the higher note; both the dropped and the truncated are
    reported.
  * four chord types - major, minor, seventh, minor seventh.  A diminished,
    augmented, sus or 6th chord is approximated to the nearest of the four and
    said so.
  * no "same root, this quality" chart entry.  A card may name a chord on an
    unplayable root, meaning the root already sounding with the type ORed on;
    card_decompile.py resolves those to the chord they denote and the compiler
    writes that chord out in full.  Nothing is lost - the result plays the same
    on either machine, and unlike the original it does not need the reader to
    know the convention.  See playcard-format.md.
  * one tempo for the whole card, snapped to a 32-entry table.  Tempo changes
    cannot be represented at all.
  * 433 bytes, because that is where the magnetic strip runs out.
  * an alphabet of at most 25 duration symbols.
  * melody G3-C6 and obbligato G2-C6, the range these keyboards play.  A note
    outside it is folded by octaves until it fits, keeping its pitch class.

By default only the COUNT of each kind of change is printed; --verbose names
every one.

CHORDS ARE READ BY PITCH CLASS, SO VOICING IS FREE

C3 E3 G3, E3 G3 C4 and G2 E3 C4 are all C major; D3 F3 A3 C4 and D3 F3 C4 are
both D minor seventh; D3 F#3 C4 is D seventh.  A fifth left out costs almost
nothing, a third left out makes the chord ambiguous and is reported - D3 C4
alone really could be D7 or Dm7, and the tie is settled by the third in the
melody if there is one and by which is commoner in the corpus if there is not.

A NOTE ON WHOSE BEHAVIOUR IS BEING COMPILED

What goes on the card is a request: this rhythm, this fill here, duck there.
What the request SOUNDS like belongs to the instrument that reads it, and the
machines differ - see the naming block in playcard_decode.py.  The limits above
are the format's and apply everywhere; card_limits.py's accept/refuse verdict
is the UPA-01 cartridge's alone.

WHERE THE CONTROL OPCODES GO IF THE FILE HAS NONE

Bar marks are never invented: which fill sounds and where the drums drop out is
an arrangement decision, and mark 0 means silence rather than nothing.  But the
obbligato duck and the phrase mark follow the melody closely enough to place,
and with --auto-control (the default when the file carries none) they are:

    0x14   at every melody entry - an onset with at least half a bar of
           silence before it
    0x13   where the melody falls silent for two bars or more
    0x11   every four bars, landing on a melody note onset where there is one
           within three beats, preferring one that begins a phrase

Measured against all 264 corpus cards, replaying the duck rule over each card's
own obbligato reproduces the original ducked/not-ducked state on 97.0% of
obbligato notes, against 81.3% for a card that simply ducks throughout.
Restating 0x14 inside an already-ducked passage changes nothing, which is why
the entry threshold barely matters: these opcodes are assertions, not brackets.

0x11 marks the passages the keyboard's repeat-practice feature offers, so it
follows the tune rather than the bar line - 84.3% of the corpus's 3109 marks
land exactly on a melody onset against 41.3% on a bar line, and exactly one of
the 3109 falls part-way through a melody note.  Snapping to the melody more
than doubles the marks placed exactly where the card has them, 862 to 1736 of
3109, and never leaves one mid-note.  See place_phrases.
"""

import argparse, collections, os, sys

import playcard_compress as Z
import playcard_decode as P
import playcard_encode as E
import playcard_midi as X
import playcard_resolve as R

MAX_CARD = 433                 # the strip runs out; see playcard-format.md

# What the keyboards actually play, as SOUNDING pitch, measured off the corpus
# rather than assumed: 42083 melody notes span exactly G3 to C6 and 42115
# obbligato notes exactly G2 to C6, with nothing outside and no stragglers near
# either edge.  A note beyond an end is folded by octaves until it fits - both
# ranges are wider than an octave, so that always terminates - which keeps the
# pitch class, the least damaging thing to do to a note the instrument cannot
# reach.  It happens after the monophonic reduction, so which note survives a
# clash is still decided on the pitches as written.
MELODY_RANGE = (55, 84)        # G3 .. C6
OBBLIGATO_RANGE = (43, 84)     # G2 .. C6


def in_range(pitch, rng):
    lo, hi = rng
    while pitch < lo:
        pitch += 12
    while pitch > hi:
        pitch -= 12
    return pitch

# Used when the file carries no Playcard header meta event and no flag says
# otherwise.  Raw header values, not the ROM's remapped ones.
DEFAULT = {'tempo': 20, 'rhythm': 4, 'f3': 0, 'melody': 8, 'sustain': 0,
           'obbligato': 1, 'key': 0}


class Report:
    """The compiler's complaints, gathered by kind so one bad bar does not
    produce four hundred lines."""

    def __init__(self):
        self.items = collections.OrderedDict()

    def add(self, kind, detail=None):
        e = self.items.setdefault(kind, [])
        if detail is not None:
            e.append(detail)

    def lines(self, limit=4):
        out = []
        for kind, details in self.items.items():
            if details:
                shown = '; '.join(details[:limit])
                more = '' if len(details) <= limit else ' ... and %d more' % (len(details) - limit)
                out.append('%s (%d): %s%s' % (kind, len(details), shown, more))
            else:
                out.append(kind)
        return out

    def summary(self):
        """One line a kind, with how many - and no list of ticks."""
        out = []
        for kind, details in self.items.items():
            out.append('%d %s' % (len(details), kind) if details else kind)
        return out

    def count(self):
        return sum(max(1, len(d)) for d in self.items.values())

    def merge(self, other):
        """Fold another report in.  The card is built more than once - flat,
        with repeats, with repeats and run-length - and only the winner's
        complaints are the user's business.  A trial that was measured and
        thrown away must not leave a warning behind about a card that does not
        exist."""
        for kind, details in other.items.items():
            self.add(kind)
            self.items[kind].extend(details)


# ---------------------------------------------------------------- one part

def monophonic(notes, rep, which):
    """Reduce a channel to one note at a time, keeping the higher note.

    A card has one duration slot per pitch event and no way to say "and also".
    Something has to give, and a stated policy is better than a silent one."""
    segs = []
    active = None
    for tick, ch, pitch, vel, dur, order in sorted(notes, key=lambda n: (n[0], -n[2])):
        end = tick + dur
        if active is None or tick >= active[1]:
            if active:
                segs.append(active)
            active = (tick, end, pitch)
            continue
        if pitch > active[2]:
            if tick > active[0]:
                segs.append((active[0], tick, active[2]))
                rep.add('%s notes cut short by a higher note starting over them' % which,
                        'tick %d' % tick)
            else:
                rep.add('%s notes dropped, another sounds at the same moment' % which,
                        'tick %d, %s' % (tick, X.note_name(active[2])))
            active = (tick, end, pitch)
        else:
            rep.add('%s notes dropped, a higher note is already sounding' % which,
                    'tick %d, %s' % (tick, X.note_name(pitch)))
    if active:
        segs.append(active)
    return segs


def timeline(segs, rep, which):
    """Sounding spans -> a gapless run of (ticks, pitch or None), quantised.

    Boundaries are re-anchored to the original tick each step, so a note that
    has to move does not drag everything after it along."""
    spans = []
    t = 0
    for start, end, pitch in segs:
        if start > t:
            spans.append((t, start, None))
        spans.append((max(start, t), end, pitch))
        t = end
    if not spans:
        return []

    out = []
    at = 0
    for start, end, pitch in spans:
        want = end - at
        got = X.nearest_length(max(1, want))
        if got != want:
            rep.add('%s events quantised to a length the card can express' % which,
                    'tick %d, %d -> %d ticks' % (at, want, got))
        out.append((got, pitch))
        at += got
    return out


def cut_spans(spans, cuts):
    """Split spans at ticks something has to be placed on.

    A chord-chart entry and a control opcode are both positioned by OPCODE
    INDEX, so either can only land where the obbligato has an event boundary -
    and the canonical largest-first split does not necessarily put one where
    the music wants it.  Cutting a note into two events is free: the first
    leaves the finger down, so the pair ties back into one note and decompiles
    to exactly the note we started with.  It is also what the original cards
    do, which is why their chart entries land where they do.

    Every piece has to be a length the table can express, and taking cuts
    greedily from the left can strand the tail on a length it cannot - so the
    choice is made by a small dynamic program over the wanted points, which
    finds the most of them that can all be honoured at once.  Whatever it
    cannot honour is returned, so the caller can say which chords had to move."""
    out = []
    missed = []
    t = 0
    pts = sorted(set(cuts))
    for length, pitch in spans:
        start, end = t, t + length
        inner = [c for c in pts if start < c < end]
        t = end
        if not inner:
            out.append((length, pitch, True))
            continue
        p = [start] + inner + [end]
        n = len(p)
        best = [-1] * n
        prev = [None] * n
        best[0] = 0
        for j in range(1, n):
            for i in range(j):
                if best[i] < 0 or X.split_duration(p[j] - p[i]) is None:
                    continue
                cand = best[i] + (1 if j < n - 1 else 0)
                if cand > best[j]:
                    best[j] = cand
                    prev[j] = i
        if best[n - 1] < 0:
            out.append((length, pitch, True))       # cannot be cut at all
            missed.extend(inner)
            continue
        chain = []
        j = n - 1
        while j is not None:
            chain.append(j)
            j = prev[j]
        chain.reverse()
        missed.extend(c for c in inner if c not in [p[k] for k in chain])
        for a, b in zip(chain, chain[1:]):
            out.append((p[b] - p[a], pitch, b == n - 1))
    return out, missed


def encode_part(notes, shift, rep, which, pad_to=0, cuts=(), rng=None):
    """A channel's notes -> (durations, opcodes, slots).

    slots is [(tick, index into opcodes)] for every pitch event, which is what
    control opcodes and chord-chart entries are placed against."""
    spans = timeline(monophonic(notes, rep, which), rep, which)
    if pad_to and sum(L for L, p in spans) < pad_to:
        spans.append((X.nearest_length(pad_to - sum(L for L, p in spans)), None))
    spans, missed = cut_spans(spans, cuts)
    for c in missed:
        rep.add('chord and control events moved to the next opcode, having no '
                'event of their own to sit on - they do not move by a little, '
                'they move to wherever the next note is, so check these; '
                'quantising the file usually removes them',
                'tick %d' % c)

    # Flatten to events first, because whether an event's LIFT bit means
    # anything depends on the event AFTER it.
    #
    #   mid-note   the bit must be CLEAR, or the run re-strikes instead of tying
    #   note end   it must be SET only if the next event repeats this pitch;
    #              that is the one case the decoder consults it in
    #   rest       ignored entirely - the decoder forces the flag itself
    #
    # Most events are therefore free, and it is tempting to spend that freedom
    # on size: every extra symbol costs 5 bits in the header and pushes every
    # other codeword down a rank, so giving a free event whichever form of its
    # length is already commoner can save a symbol outright.
    #
    # DO NOT.  It sounds wrong.  If the lifted form happens to win, EVERY note
    # of the commonest length comes out lifted and the part plays staccato -
    # on real hardware the key is released at the end of the event whether or
    # not anything repeats the pitch, which is not something this file's model
    # of the flag can see.  Yamaha never did it: across the 264 originals the
    # bit is set on 57.7% of the notes a repeat follows and on 2.8% of the ones
    # it does not, and on 0 of 20757 rests.  So the bit goes on exactly where
    # it changes a tie into a re-strike, and nowhere else.
    events = []
    for length, pitch, ends_note in spans:
        parts = X.events_for_note(length)
        for L, last in parts:
            if pitch is None:
                events.append([L, None, 'free'])
            elif last and ends_note:
                events.append([L, pitch, 'end'])
            else:
                events.append([L, pitch, 'down'])
    for i, e in enumerate(events):
        if e[2] == 'end':
            nxt = events[i + 1] if i + 1 < len(events) else None
            e[2] = 'up' if (nxt is not None and nxt[1] == e[1]) else 'free'

    def symbol(L, kind):
        return (L | X.LIFT) if kind == 'up' else L

    durs, ops, slots = [], [], []
    octave = X.START_OCTAVE
    t = 0
    for L, pitch, kind in events:
        slots.append((t, len(ops)))
        if pitch is None:
            durs.append(symbol(L, kind))
            ops.append(('rest', None))
        else:
            if rng is not None:
                folded = in_range(pitch, rng)
                if folded != pitch:
                    rep.add("%s notes outside the keyboard's %s range, "
                            'moved by octaves to fit'
                            % (which, 'G3-C6' if rng == MELODY_RANGE else 'G2-C6'),
                            'tick %d, %s -> %s'
                            % (t, X.note_name(pitch), X.note_name(folded)))
                    pitch = folded
            card_pitch = pitch - shift
            letter, sharp, oct_want = X.note_position(card_pitch)
            while octave < oct_want:
                ops.append(('oct', 1))
                octave += 1
            while octave > oct_want:
                ops.append(('oct', 2))
                octave -= 1
            # The sharp modifier applies to ONE following note and is
            # cleared after it, so every event of a tied sharpened note
            # needs its own - without it the run reads C# C# C as C# C C
            # and stops being one note.
            if sharp:
                ops.append(('oct', 0))
            durs.append(symbol(L, kind))
            ops.append(('note', X.LETTER_CODE[letter]))
        t += L
    return durs, ops, slots, t


# ---------------------------------------------------------------- control opcodes

def place_phrases(mel_spans, bar, every=4):
    """0x11 positions from the melody alone.

    0x11 divides the card into the passages the keyboard's repeat-practice
    feature offers - press the button, then a key to loop one passage or two
    keys for a range.  That is why it is queued outward to the keyboard and
    never read back by the cartridge, and the corpus fits it closely:

      * 84.3% of all 3109 marks land EXACTLY on a melody note onset, against
        41.3% on a bar line
      * exactly ONE of the 3109 falls part-way through a melody note, which is
        what a passage boundary must obey - a passage cannot start mid-note
      * there are 4 to 20 per card, median 11, and not one card has more than
        20, which is what a set selected by keys looks like

    So the grid is walked in `every` bars and stays anchored - the count then
    tracks the length of the song rather than drifting - and each mark lands on
    a melody onset if one is near, preferring one that begins a phrase.  A
    melody very often enters before the bar line, so snapping is what matters:
    on I Could Have Danced All Night the tune comes in at bar 4.62 and the card
    puts a mark exactly there, where a bar grid would sit at 4.00 and be wrong.

    Nothing here can leave a mark inside a melody note."""
    window = bar * 3 // 4      # a phrase may begin up to three beats early
    ons = sorted(set(s for s, e, p in mel_spans))
    ent = set()
    prev = None
    for start, end, pitch in mel_spans:
        if prev is None or start - prev >= 12:
            ent.add(start)
        prev = end
    total = mel_spans[-1][1] if mel_spans else 0
    out = []
    t = 0
    while t <= total:
        near = [o for o in ons if abs(o - t) <= window]
        pick = [o for o in near if o in ent]
        if near:
            c = min(pick or near, key=lambda o: (abs(o - t), o))
        else:
            c = t
            for s, e, p in mel_spans:
                if s < c < e:
                    c = s              # never part-way through a note
                    break
        if not out or c > out[-1]:
            out.append(c)
        t += every * bar
    return out


def auto_control(mel_spans, bar, want_duck, want_phrase):
    """Place the duck and phrase opcodes from the melody alone.

    See the module docstring for how this was measured.  Bar marks are never
    invented: they are an arrangement decision, not a consequence of the tune."""
    ENTRY_GAP = 48             # half a 4/4 bar of silence starts a new entry
    EXIT_GAP = 192             # two bars of silence ends one
    out = []
    if want_duck:
        prev_end = None
        for start, end, pitch in mel_spans:
            if prev_end is None or start - prev_end >= ENTRY_GAP:
                out.append((start, X.CTL_NOTE[0x14]))
            prev_end = end
        for j, (start, end, pitch) in enumerate(mel_spans):
            nxt = mel_spans[j + 1][0] if j + 1 < len(mel_spans) else None
            if nxt is None or nxt - end >= EXIT_GAP:
                out.append((end, X.CTL_NOTE[0x13]))
    if want_phrase:
        for t in place_phrases(mel_spans, bar):
            out.append((t, X.CTL_NOTE[0x11]))
    out.sort()
    return out


def place(events, slots, ops):
    """Insert control opcodes into the obbligato stream at the right index.

    A control event at tick T belongs to the first pitch event at or after T,
    and goes in front of it - in front of that note's octave modifiers too, so
    the whole group stays together."""
    ins = collections.defaultdict(list)
    for tick, op in events:
        idx = len(ops)
        for st, oi in slots:
            if st >= tick:
                idx = oi
                break
        ins[idx].append(op)
    out = []
    moved = {}
    for i, o in enumerate(ops):
        for extra in ins.get(i, ()):
            out.append(extra)
        moved[i] = len(out)
        out.append(o)
    for extra in ins.get(len(ops), ()):
        out.append(extra)
    return out, [(t, moved.get(i, len(out))) for t, i in slots]


def nibble_positions(ops):
    """The position field counts 4-bit reads, 1-based, and an escape opcode
    costs two of them - which is what ROM 0xE484 counts and what the chord
    chart's positions index."""
    pos, n = [], 1
    for kind, val in ops:
        pos.append(n)
        n += 2 if kind in ('mark', 'loop') else 1
    return pos


# ---------------------------------------------------------------- the chart

def chord_blocks(notes):
    """Channel 3's notes -> [(tick, [pitches])], one block per onset."""
    by_tick = collections.OrderedDict()
    for tick, ch, pitch, vel, dur, order in notes:
        by_tick.setdefault(tick, []).append(pitch)
    return sorted(by_tick.items())


def chart_for_ops(chord_notes, mutes, mel_notes, obb_notes, slots, n_ops, rep):
    """Chord blocks and mutes -> [(obbligato opcode index, value)].

    Positions are opcode indices in the OBBLIGATO stream, because that is where
    a chart entry actually fires - the melody stream's copy never reaches the
    handler.  So a chord is placed against the obbligato's timeline and the
    melody is not consulted at all.

    This stops at the opcode.  Turning an opcode index into the position the
    card stores is chart_positions' job, and it is separate because compression
    moves every one of them."""
    sounding = collections.defaultdict(set)
    for tick, ch, pitch, vel, dur, order in list(mel_notes) + list(obb_notes):
        sounding[tick].add(pitch)

    entries = []
    for tick, pitches in chord_blocks(chord_notes):
        ctx = set()
        for t, ps in sounding.items():
            if tick <= t < tick + 96:
                ctx |= ps
        got = X.identify_chord(pitches, ctx)
        if not got:
            continue
        root, ty, note = got
        if note:
            rep.add('chords the card cannot spell exactly',
                    'tick %d: %s' % (tick, note))
        entries.append((tick, X.chord_value(root, ty)))
    for tick in mutes:
        entries.append((tick, 0xFF))
    entries.sort()
    entries = X.collapse_chart(entries)

    out = []
    for tick, value in entries:
        idx = None
        for st, oi in slots:
            if st >= tick:
                idx = oi
                break
        if idx is None or idx >= n_ops:
            # An entry past the last obbligato note - an end-of-card mute is
            # the usual one.  It still has to fire, so it goes at the end of
            # the stream rather than being thrown away.
            idx = n_ops - 1
        if out and out[-1][0] == idx:
            out[-1] = (idx, value)           # one opcode, one chord: the last wins
        else:
            out.append((idx, value))
    return out


def chart_positions(entries, index_map, npos, end_index, rep):
    """[(opcode index, value)] -> [(value, stored position)].

    `index_map` turns an index in the flat stream into an index in the stored
    one; with no compression it is the identity.  Two flat entries can land on
    one stored opcode - that is what happens to a chord inside a repeated body,
    and it is the whole point: the entry is stored once and fires on every
    pass."""
    out = []
    seen = {}
    at = {}
    for idx, value in entries:
        i = index_map(idx)
        if i is None or i >= end_index:
            # It still has to fire, and it has to go BEFORE the terminator: the
            # back-fill rewrites that repeat marker as the return, so anything
            # after it is never reached.
            i = end_index - 1
        p = npos[i]
        at[idx] = p
        if not 0 < p < 0x3C0:
            rep.add('chords too far into the stream for the chart to address '
                    '(the position field holds 959)', 'opcode %d' % idx)
            continue
        if p in seen:
            out[seen[p]] = (value, p)
        else:
            seen[p] = len(out)
            out.append((value, p))
    out.sort(key=lambda e: e[1])
    dropped = 0
    if len(out) > X.MAX_CHART:
        dropped = len(out) - X.MAX_CHART
        rep.add('the chord chart holds %d entries and this arrangement needs '
                '%d, so the last %d are dropped'
                % (X.MAX_CHART, len(out), dropped))
        out = out[:X.MAX_CHART]
    # The table costs ten bits a position plus ten more every time the value
    # CHANGES from one entry to the next, and nothing requires the positions to
    # be in order: the firmware scans the whole table against its opcode
    # counter, so an entry is found wherever it sits.  Grouping by value
    # therefore collapses the value records to one per distinct chord, and that
    # is what the originals do - the PCS-30's own decoded chord tables come out
    # grouped by value with the positions descending inside each group.  Sorted
    # by position instead, a chart that alternates between two chords pays a
    # value record for every single entry.  It was worth 40 bytes on a busy
    # card.
    out.sort(key=lambda e: (e[0], e[1]))

    # Which of the flat entries actually made it onto the card.  Chart records
    # that were dropped for want of room are a reported loss, not a sign that
    # the repeat structure is wrong, so the verifier is told to expect only
    # these - otherwise a card whose chart overflows would fail verification
    # and be rebuilt flat, which is both bigger and no more complete.
    kept = set(pos for value, pos in out)
    keep_flat = dict((idx, value) for idx, value in entries
                     if at.get(idx) in kept)
    return out, keep_flat, dropped


# ---------------------------------------------------------------- compression

def op_units(op):
    """An escape opcode costs two nibbles; everything else costs one."""
    return 2 if op[0] in ('mark', 'loop') else 1


# A duration track has all four spans to itself.  An opcode stream keeps span 0
# for E.terminated(), whose `E1 10` is also what lets the back-fill close a
# compressed span whose body happens to be nothing but notes.
TRACK_MARKERS = [0xF0, 0xF2, 0xF4, 0xF6]
STREAM_MARKERS = [('loop', 1), ('loop', 2), ('loop', 3)]


def run_length(durs):
    """Replace a duration symbol that repeats the one before it with 0xFF.

    0xFF is the master table's "repeat the previous symbol", and the alphabet
    is ordered most-frequent-first, so collapsing every repeat of every length
    onto ONE symbol tends to put that symbol at rank 0 and cost two bits a use.
    Every original card does this and on 239 of the 264 it is the commonest
    symbol they carry - it is run-length coding stacked on top of the entropy
    coding, and leaving it out was costing tens of bytes a card.

    Markers and terminators pass through untouched and do not count as the
    previous symbol: ROM 0x6348 only tracks the last real duration, so a 0xFF
    after a repeat marker still refers back across it."""
    out = []
    last = None
    for d in durs:
        if d == 0xE1 or 0xF0 <= d <= 0xF6:
            out.append(d)
            continue
        if d == last:
            out.append(0xFF)
        else:
            out.append(d)
            last = d
    return out


def symbol_bits(durs):
    """What each duration symbol costs, in bits, at its place in the alphabet.

    The alphabet is ordered most-frequent-first and the codeword is an
    alternating run, so values 0 and 1 cost two bits, 2 and 3 cost three, and
    so on.  A repeat built out of rare symbols is therefore worth much more
    than the same number of common ones, and counting symbols instead of bits
    picks the wrong body."""
    freq = collections.Counter(durs)
    rank = {}
    for i, (v, c) in enumerate(sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))):
        rank[v] = i
    cost = dict((v, 2 + (r // 2)) for v, r in rank.items())
    return lambda x: cost.get(x, 4)


def compress_track(durs):
    """Factor repeats out of a duration track.

    A track carrying any marker needs TWO closing 0xE1s - the first is spent
    closing the span and only the second ends the track - so one is appended
    here and put_track writes the other."""
    got = Z.compress(durs, TRACK_MARKERS, cost=symbol_bits(durs), marker_cost=4)
    if not got:
        return durs, None, None
    stored, origin, saving, chosen, locate = got
    return stored + [0xE1], locate, (saving, chosen)


def compress_stream(ops, accept_for=None):
    """Factor repeats out of an opcode stream."""
    got = Z.compress(ops, STREAM_MARKERS, cost=op_units, marker_cost=2,
                     accept_for=accept_for)
    if not got:
        return ops, None, None
    stored, origin, saving, chosen, locate = got
    return stored, locate, (saving, chosen)


def chart_agrees(entries):
    """Only factor out a body the chord chart agrees about.

    A chart entry inside a repeated body is decoded once and replayed on every
    pass, so the body may only be shared by occurrences carrying the same
    chords at the same offsets.  Occurrences are grouped by what their chart
    says and the largest group wins.

    This is built fresh for each span, because compression is iterative: the
    positions handed to `accept` index the sequence as it stands NOW, so the
    chart has to be expressed in those coordinates too.  `locate` is what
    translates, following an entry through any body it has already been folded
    into."""
    def accept_for(locate):
        here = {}
        for idx, value in entries:
            i = locate(idx)
            if i is not None:
                here[i] = value
        if not here:
            return None

        def accept(positions, length):
            groups = collections.defaultdict(list)
            for p in positions:
                pattern = tuple(sorted((f - p, v) for f, v in here.items()
                                       if p <= f < p + length))
                groups[pattern].append(p)
            return max(groups.values(), key=len)

        return accept

    return accept_for


def resolved_ops(ops, chart_by_index):
    """What playcard_resolve should give back for a flat stream and its chart.

    This is the oracle.  Compression is only kept when the card it produces
    resolves to exactly this, so a span that does not reproduce the music
    cannot survive - the same discipline the rest of the project runs on."""
    out = []
    for i, (kind, val) in enumerate(ops):
        if i in chart_by_index:
            out.append(('tbl', chart_by_index[i]))
        if kind == 'note':
            out.append(('byte', val))
        elif kind == 'rest':
            out.append(('byte', 3))
        elif kind == 'oct':
            out.append(('oct', val))
        elif kind in ('ctl', 'mark'):
            out.append(('ctl', val))
    return out


def verify(data, mel_durs, obb_durs, mel_ops, obb_ops, mel_chart, obb_chart):
    """Resolve a built card and check it plays the flat sequences exactly."""
    h = P.parse_card(P.tobits(data))
    if not h['crc_ok'] or h['type'] != 1 or not h['sections']:
        return False
    t1, t2, s0, s1 = R.resolve(h)
    if [v for k, v in t1 if k == 'byte'] != [d & 0xFF for d in mel_durs]:
        return False
    if [v for k, v in t2 if k == 'byte'] != [d & 0xFF for d in obb_durs]:
        return False
    # The cartridge walks the chart on every decoded opcode of BOTH streams, so
    # the melody's region carries 0xE7 records too - but only the obbligato's
    # copy reaches the chord handler, which is what the chart-position test card
    # settled.  So they are compared where they matter and ignored where they
    # do not.
    want0 = resolved_ops(mel_ops, mel_chart)
    want1 = resolved_ops(obb_ops, obb_chart)
    got0 = [e for e in s0 if e[0] in ('byte', 'oct', 'ctl')]
    got1 = [e for e in s1 if e[0] in ('byte', 'oct', 'ctl', 'tbl')]
    return got0 == want0 and got1 == want1


# ---------------------------------------------------------------- the alphabet

def build_alphabet(*tracks):
    """Most-frequent-first, which is what makes the prefix code cheap.

    Values 0 and 1 cost two bits, 2 and 3 cost three, and so on, so the order
    is not cosmetic."""
    freq = collections.Counter()
    for tr in tracks:
        freq.update(tr)
    freq[0xE1] += len(tracks)                # each track ends with one
    return [v for v, c in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))]


# ---------------------------------------------------------------- the compiler

# The header fields the raw meta line can set, and so --raw with it.
RAW_FIELDS = ('tempo', 'rhythm', 'f3', 'melody', 'sustain', 'obbligato', 'key')


say = P.say                  # sentences wrapped at the words, not the column


def voice_arg(val, table, hi, what):
    """A --melody-voice / --obbligato-voice argument as a field value.

    Either vocabulary is accepted, in any casing, and so is the field number
    itself for anyone working from the tables rather than from the panel.
    """
    if val is None:
        return None
    field = P.voice_field(table, val)
    if field is not None:
        return field
    s = str(val).strip()
    if s.isdigit() and 1 <= int(s) <= hi:
        return int(s)
    sys.exit(P.wrapped('unknown %s voice %r; one of: %s - or a field number '
                       '1-%d'
                       % (what, val, ', '.join(P.voice_choices(table)), hi)))


def compile_midi(path, overrides=None, auto='auto', compress=True,
                 sides='auto', refit='auto'):
    """Returns (card bytes, Report, facts dict).  Raises on anything fatal.

    `refit` is what to do when the card will not fit the strip.  The key field
    transposes the melody and the obbligato at playback and leaves the chord
    chart alone, so choosing a different one changes NOTHING about how the card
    sounds - it only changes how the notes are spelled, and an accidental costs
    an opcode of its own.  The same music can differ by a fifth of the strip
    between its best and worst key.  With `refit='auto'` an over-long card is
    recompiled at each of the other eleven and the smallest that fits is kept;
    'never' leaves the key alone.
    """
    rep = Report()
    P.check_midi(path)
    m = X.read_midi(path)
    notes, drift = X.rescale(m['notes'], m['tpq'])
    if drift['ticks']:
        rep.add('%d note positions do not land on the card\'s 24 ticks per '
                'quarter and were moved, the worst by %.2f of a tick - the '
                'file is written at %d, so quantise to a 16th or an 8th '
                'triplet. Small as that is, it is what displaces chords: '
                'those are placed at the obbligato event underneath them '
                'rather than at a time of their own'
                % (drift['ticks'], drift['worst_tick'], m['tpq']))
    if drift['lengths']:
        rep.add('%d note lengths do not land on the card\'s 24 ticks per '
                'quarter and were rounded, the worst by %.2f of a tick'
                % (drift['lengths'], drift['worst_length']))

    hdr = dict(DEFAULT)
    hdr.update(X.parse_header_text(m['texts']))
    if 'tempo' not in X.parse_header_text(m['texts']):
        bpm = int(round(m['bpm']))
        hdr['tempo'] = min(range(len(P.TEMPO)), key=lambda i: abs(P.TEMPO[i] - bpm))
        if P.TEMPO[hdr['tempo']] != bpm:
            rep.add('tempo %d bpm is not in the card\'s 32-entry table, '
                    'stored as %d' % (bpm, P.TEMPO[hdr['tempo']]))
        if m['beats'] == 3:
            hdr['rhythm'] = 6                # waltz
    for k, v in (overrides or {}).items():
        if v is not None:
            hdr[k] = v

    shift = P.key_shift(hdr['key'])
    bar = 72 if hdr['rhythm'] + 1 == 7 else 96

    chan = collections.defaultdict(list)
    for n in notes:
        chan[n[1]].append(n)
    for ch in chan:
        if ch not in (X.MEL_CH, X.OBB_CH, X.CHORD_CH, X.CTL_CH):
            rep.add('notes on channel %d, which the card has no part for, '
                    'ignored' % (ch + 1))

    # A control note that landed on a music channel.  The channel is the whole
    # contract - nothing here re-routes it, because a compiler that silently
    # moved notes between parts would be worse than one that misses a mark -
    # but say so plainly, because otherwise it surfaces as an unrelated
    # complaint about overlapping notes, or as a wrong note folded up into
    # the melody by three octaves and never mentioned at all.
    for ch, which in ((X.MEL_CH, 'melody'), (X.OBB_CH, 'obbligato')):
        for n in [n for n in chan[ch] if n[2] in X.CONTROL_NAMES]:
            rep.add('control notes on channel %d, where the card reads them as '
                    '%s and not as controls - move them to channel 4'
                    % (ch + 1, which),
                    'tick %d, %s = %s' % (n[0], X.note_name(n[2]),
                                          X.control_note_name(n[2])))

    mel_notes = chan[X.MEL_CH]
    obb_notes = chan[X.OBB_CH]
    if not mel_notes and not obb_notes:
        raise ValueError('no notes on channel 1 or channel 2 - nothing to compile')

    mel_durs, mel_ops, mel_slots, mel_end = encode_part(
        mel_notes, shift, rep, 'melody', rng=MELODY_RANGE)
    if not obb_notes:
        rep.add('channel 2 is empty, so the obbligato is a rest as long as the '
                'melody - the bar marks, the duck and the chord chart all live '
                'in that stream and need somewhere to sit')

    # --- control notes.  The file's own event order is kept for events sharing
    # a tick: it is the order the card had them in, and re-sorting by kind
    # would silently rewrite it.
    ctl = [(n[0], n[5], n[2]) for n in chan[X.CTL_CH]]
    ctl.sort()
    for tick, order, pitch in ctl:
        if pitch not in X.CONTROL_NAMES:
            rep.add('control notes on channel 4 that mean nothing, ignored',
                    'tick %d, note %d' % (tick, pitch))
    marks = [c for c in ctl if X.MARK_BASE <= c[2] < X.MARK_BASE + 8]
    ducks = [c for c in ctl if c[2] in X.NOTE_CTL and X.NOTE_CTL[c[2]] != 0x11]
    phrase = [c for c in ctl if c[2] in X.NOTE_CTL and X.NOTE_CTL[c[2]] == 0x11]
    mutes = [c[0] for c in ctl if c[2] == X.MUTE_NOTE]

    if auto != 'off':
        want_duck = auto == 'on' or not ducks
        want_phrase = auto == 'on' or not phrase
        if want_duck or want_phrase:
            mel_spans = monophonic(mel_notes, Report(), 'melody')
            added = auto_control(mel_spans, bar, want_duck, want_phrase)
            if want_duck:
                ducks = [(t, -1, p) for t, p in added if X.NOTE_CTL[p] != 0x11]
            if want_phrase:
                phrase = [(t, -1, p) for t, p in added if X.NOTE_CTL[p] == 0x11]
            rep.add('placed %d duck and %d phrase opcodes from the melody, '
                    'because the file carried none'
                    % (len(ducks) if want_duck else 0, len(phrase) if want_phrase else 0))

    stream_ops = []
    for tick, order, p in sorted(marks + ducks + phrase):
        if X.MARK_BASE <= p < X.MARK_BASE + 8:
            stream_ops.append((tick, ('mark', p - X.MARK_BASE)))
        else:
            stream_ops.append((tick, ('ctl', X.NOTE_CTL[p])))

    # Everything that is placed by opcode index needs an event boundary to
    # land on, so the obbligato is encoded knowing where they all are.
    cuts = set(t for t, op in stream_ops) | set(mutes)
    cuts |= set(t for t, ps in chord_blocks(chan[X.CHORD_CH]))
    # The card runs as long as its longest part, and a trailing rest is not
    # something MIDI records - but a chord held to the end of the card is, so
    # the file's full extent is the best statement of where the card stops.
    extent = max([n[0] + n[4] for n in notes] or [0])
    obb_durs, obb_ops, obb_slots, obb_end = encode_part(
        obb_notes, shift, rep, 'obbligato', pad_to=max(mel_end, extent),
        cuts=cuts, rng=OBBLIGATO_RANGE)
    obb_ops, obb_slots = place(stream_ops, obb_slots, obb_ops)

    # --- the chord chart, as opcode indices into the FLAT obbligato stream.
    # Turning those into stored positions waits until compression has decided
    # where everything ends up.
    entries = chart_for_ops(chan[X.CHORD_CH], mutes, mel_notes, obb_notes,
                            obb_slots, len(obb_ops), rep)

    def assemble(compress, rle=False):
        """Build the card once.  Returns everything the verifier needs, so a
        card that does not resolve back can be thrown away for a simpler one."""
        md, od, mo, oo = list(mel_durs), list(obb_durs), list(mel_ops), list(obb_ops)
        gain = []
        index_map = lambda i: i
        if compress:
            md, _, g = compress_track(md)
            if g:
                gain.append('melody durations x%d' % len(g[1]))
            od, _, g = compress_track(od)
            if g:
                gain.append('obbligato durations x%d' % len(g[1]))
            mo, _, g = compress_stream(mo)
            if g:
                gain.append('melody stream x%d' % len(g[1]))
            oo, locate, g = compress_stream(oo, accept_for=chart_agrees(entries))
            if g:
                gain.append('obbligato stream x%d' % len(g[1]))
                index_map = locate

        mo = E.terminated(mo)
        oo = E.terminated(oo)
        npos = nibble_positions(oo)
        # A trial's chart complaints belong to that trial: the flat form of a
        # chord-heavy card can overflow the table while the compressed form of
        # the SAME music fits it easily, because entries inside a repeated body
        # are stored once and fire on every pass.  Warning from here would
        # blame the card for a layout that was measured and discarded.
        sub = Report()
        chart, keep, dropped = chart_positions(entries, index_map, npos,
                                               len(oo) - 2, sub)

        if rle:
            # after compression, so the bodies are matched on real durations
            md, od = run_length(md), run_length(od)
        alphabet = build_alphabet(md, od)
        if len(alphabet) >= 26:
            raise ValueError('this arrangement needs %d duration symbols and '
                             'the alphabet field rejects 26 or more' % len(alphabet))
        card = E.Card(tempo=hdr['tempo'], rhythm=hdr['rhythm'], f3=hdr['f3'],
                      mel_voice=hdr['melody'], sustain=hdr['sustain'],
                      obb_voice=hdr['obbligato'], key=hdr['key'],
                      alphabet=alphabet, mel_durs=md, obb_durs=od,
                      mel_ops=mo, obb_ops=oo, chart=chart)
        return E.build(card), alphabet, chart, gain, keep, sub, dropped, card

    flat = assemble(False)
    data, alphabet, chart, gain, keep, sub, dropped, built = flat
    method = None
    if compress:
        # Try the smaller forms in turn and keep the best that verifies.  The
        # resolver is the oracle: anything that does not give the music back
        # exactly is thrown away, so a card can come out smaller but never
        # wrong.
        best = None
        for label, args in (('repeats', (True, False)),
                            ('repeats and run-length', (True, True))):
            try:
                got = assemble(*args)
            except Exception as e:
                rep.add('%s could not build a card: %s' % (label, e))
                continue
            if not verify(got[0], mel_durs, obb_durs, E.terminated(mel_ops),
                          E.terminated(obb_ops), {}, got[4]):
                rep.add('%s did not resolve back to the same music, so it was '
                        'discarded - this should not happen' % label)
                continue
            if best is None or len(got[0]) < len(best[1][0]):
                best = (label, got)
        if best and len(best[1][0]) < len(data):
            # how the card was built is information, not a complaint, so it
            # travels in `facts` and only surfaces with --verbose
            method, got = best
            data, alphabet, chart, gain, keep, sub, dropped, built = got

    rep.merge(sub)                      # now that a winner is chosen

    # Two sides, if the music wants them.  The split is the format's own and
    # not a choice of where to cut: side A is the header and both duration
    # tracks, side B is the chart and both opcode streams.  So it does not
    # halve a card - the originals run 190/360, 148/301 and 161/379 - and a
    # piece whose SECTION alone overflows the strip cannot be helped by it.
    # A card that will not fit may fit in another key.  The key field shifts
    # the melody and the obbligato at playback and leaves the chart alone, so
    # the card sounds exactly the same whichever value it carries - what
    # changes is the spelling, and every accidental costs an opcode of its own.
    # Try the other eleven and keep the smallest that fits, before resorting to
    # two sides, which is a real inconvenience where this is free.
    refit_note = won = None
    if refit == 'auto' and len(data) > MAX_CARD:
        tried = []
        for code in sorted(P.OPM_INDEX):
            if code == hdr['key']:
                continue
            try:
                alt, _, af = compile_midi(path, dict(overrides or {}, key=code),
                                          auto, compress, sides='never',
                                          refit='never')
            except Exception:
                continue
            if isinstance(alt, tuple):
                continue
            tried.append((len(alt), abs(P.key_shift(code)), code, alt, af))
        fits = sorted(t for t in tried if t[0] <= MAX_CARD)
        if fits:
            n, _, code, alt, af = fits[0]
            rep.add('%d bytes at the key asked for and %d at %+d semitones, so '
                    'the card was written in that key instead - it sounds the '
                    'same, and the header says so'
                    % (len(data), n, P.key_shift(code)))
            refit_note = (P.key_shift(hdr['key']), P.key_shift(code),
                          len(data), n)
            data, built, hdr, won = alt, af['built'], af['header'], af

    pair = None
    if sides == 'always' or (sides == 'auto' and len(data) > MAX_CARD):
        pair = E.build_sides(built)
        over = [n for n, d in zip('AB', pair) if len(d) > MAX_CARD]
        if over:
            rep.add('side %s is still over the %d bytes the strip holds, even '
                    'split in two' % (' and '.join(over), MAX_CARD))
    elif len(data) > MAX_CARD:
        rep.add('the card is %d bytes and the strip holds %d - pass '
                '--sides 2 to split it' % (len(data), MAX_CARD))

    facts = {'bytes': len(data), 'alphabet': len(alphabet), 'method': method,
             'sides': None if pair is None else (len(pair[0]), len(pair[1])),
             'melody': len(mel_durs), 'obbligato': len(obb_durs),
             'chart': len(chart), 'chart_dropped': dropped,
             'marks': len(marks),
             'controls': len(ducks) + len(phrase), 'mutes': len(mutes),
             'flat_bytes': len(flat[0]), 'flat_chart': len(flat[2]),
             'compressed': gain,
             'bpm': P.TEMPO[hdr['tempo']], 'rhythm': P.RHYTHM[hdr['rhythm'] + 1],
             'header': hdr, 'built': built, 'refit': refit_note}
    if refit_note:
        # everything the losing attempt measured belongs to a card that was
        # thrown away, so take those numbers from the one that was kept
        for k in ('alphabet', 'method', 'compressed', 'flat_bytes',
                  'flat_chart', 'chart', 'chart_dropped'):
            facts[k] = won[k]
    return (data if pair is None else pair), rep, facts


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(
        description='Compile a four-channel MIDI file into a Playcard image.')
    ap.add_argument('midi', nargs='?')
    ap.add_argument('-o', '--out')
    ap.add_argument('--tempo', type=int, help='bpm, snapped to the card table')
    ap.add_argument('--rhythm', help='rhumba samba swing bossa-nova rock '
                                     '16-beat waltz slow-rock march disco')
    ap.add_argument('--transpose', type=int, help='semitones, -6 to +5')
    ap.add_argument('--sustain', choices=('on', 'off'))
    ap.add_argument('--pattern', choices=('standard', 'alternate'))
    ap.add_argument('--melody-voice', dest='melody',
                    help='voice name or field 1-10 (piccolo organ violin '
                         'trumpet oboe clarinet harpsichord piano vibraphone '
                         'guitar)')
    ap.add_argument('--obbligato-voice', dest='obbligato',
                    help='voice name or field 1-8 (oboe flute strings brass '
                         'clarinet piano harpsichord guitar)')
    ap.add_argument('--raw', action='append', metavar='FIELD=N', default=[],
                    help='a header field by its raw value, for what the named '
                         'options cannot say: %s' % ', '.join(RAW_FIELDS))
    ap.add_argument('-v', '--verbose', action='store_true',
                    help='name every event that had to change, instead of just '
                         'counting them')
    ap.add_argument('--auto-control', choices=('auto', 'on', 'off'), default='auto',
                    help='place the duck and phrase opcodes from the melody '
                         '(default: only what the file lacks)')
    ap.add_argument('--no-refit', action='store_true',
                    help='do not try other keys when the card will not fit; '
                         'the key field is a playback transposition, so '
                         'changing it costs nothing musically and can save a '
                         'fifth of the strip')
    ap.add_argument('--sides', choices=('auto', '1', '2'), default='auto',
                    help='auto splits a card that will not fit the strip; '
                         '1 never splits; 2 always does')
    ap.add_argument('--roundtrip', action='store_true',
                    help='decompile and recompile every card, and report')
    a = ap.parse_args()

    if a.roundtrip:
        return roundtrip()
    if not a.midi:
        ap.print_help()
        return

    over = {}
    if a.tempo:
        over['tempo'] = min(range(len(P.TEMPO)), key=lambda i: abs(P.TEMPO[i] - a.tempo))
    if a.rhythm:
        name = a.rhythm.lower()
        if name not in X.NAME_RHYTHM:
            sys.exit('unknown rhythm %r; one of: %s'
                     % (a.rhythm, ' '.join(sorted(X.NAME_RHYTHM))))
        over['rhythm'] = X.NAME_RHYTHM[name] - 1
    if a.transpose is not None:
        for code in P.OPM_INDEX:
            if P.key_shift(code) == a.transpose:
                over['key'] = code
                break
        else:
            sys.exit('transpose must be between -6 and +5 semitones')
    if a.sustain:
        over['sustain'] = 1 if a.sustain == 'on' else 0
    if a.pattern:
        over['f3'] = 2 if a.pattern == 'alternate' else 0
    # The two voice fields are stored offset from the table index, exactly as
    # the raw meta line writes them: melody + 5, obbligato - 1.
    f = voice_arg(a.melody, P.MELODY_VOICE, 10, 'melody')
    if f is not None:
        over['melody'] = f + 5
    f = voice_arg(a.obbligato, P.OBBLIGATO_VOICE, 8, 'obbligato')
    if f is not None:
        over['obbligato'] = f - 1
    for item in a.raw:
        if '=' not in item:
            sys.exit('--raw wants FIELD=N, not %r' % item)
        k, v = item.split('=', 1)
        k = k.strip()
        if k not in RAW_FIELDS:
            sys.exit('unknown raw field %r; one of: %s' % (k, ', '.join(RAW_FIELDS)))
        try:
            over[k] = int(v, 0)
        except ValueError:
            sys.exit('--raw %s wants a number, not %r' % (k, v))

    out = a.out or os.path.splitext(a.midi)[0] + '.bin'
    want = {'auto': 'auto', '1': 'never', '2': 'always'}[a.sides]
    data, rep, facts = compile_midi(a.midi, over, a.auto_control, sides=want,
                                   refit='never' if a.no_refit else 'auto')

    if facts['sides'] is None:
        with open(out, 'wb') as f:
            f.write(data)
        print('%s -> %s' % (os.path.basename(a.midi), out))
        print('  %d bytes of %d   %d bpm  %s   alphabet %d of 25'
              % (facts['bytes'], MAX_CARD, facts['bpm'], facts['rhythm'],
                 facts['alphabet']))
    else:
        # The suffixes are the corpus's own, and midi_export.py and
        # card_decompile.py both find a side B by them - so a card written here
        # reads back with no help.
        stem, ext = os.path.splitext(out)
        if stem.endswith('_side-a'):
            stem = stem[:-len('_side-a')]
        names = []
        for tag, blob in zip(('a', 'b'), data):
            name = '%s_side-%s%s' % (stem, tag, ext)
            with open(name, 'wb') as f:
                f.write(blob)
            names.append(name)
        print('%s -> %s' % (os.path.basename(a.midi), ', '.join(
            os.path.basename(n) for n in names)))
        print('  two sides, %d + %d bytes, each of %d   %d bpm  %s   '
              'alphabet %d of 25'
              % (facts['sides'][0], facts['sides'][1], MAX_CARD, facts['bpm'],
                 facts['rhythm'], facts['alphabet']))
        say('swipe side A first: the reader will not accept side B until it '
            'has seen it')
    if a.verbose:
        if facts['method']:
            say('built with %s: %s   (%d bytes flat, %d saved)'
                % (facts['method'], ', '.join(facts['compressed']),
                   facts['flat_bytes'], facts['flat_bytes'] - facts['bytes']),
                hang='      ')
        say('melody %d events, obbligato %d, chart %d entries, %d bar marks, '
            '%d control opcodes, %d mutes'
            % (facts['melody'], facts['obbligato'], facts['chart'],
               facts['marks'], facts['controls'], facts['mutes']),
            hang='      ')
    for line in (rep.lines() if a.verbose else rep.summary()):
        say(line, prefix='  ! ', hang='    ')
    # Only worth suggesting when --verbose would actually say more.  A complaint
    # with no details of its own - "channel 2 is empty" - reads the same either
    # way, and there is nothing for it to name.
    if not a.verbose and any(rep.items.values()):
        say('(--verbose names every one)')


def roundtrip():
    """Decompile every card, compile it back, and compare what a player hears.

    Two cards are the same here when their melody and obbligato notes, their
    chord chart and their bar marks match.  The stored bytes are allowed to
    differ: a note split into events one way or another sounds identical, and
    which split a card used is not something a MIDI file records."""
    import card_decompile as D
    import tempfile
    try:
        files = P.corpus()
    except P.Missing as e:
        sys.exit(str(e))
    tmp = tempfile.mkdtemp(prefix='playcard-roundtrip-')
    same = diff = failed = 0
    oversize = flat_oversize = two_sided = 0
    saved = []
    firsts = []
    per = collections.Counter()
    fits = collections.Counter()
    for f in files:
        base = os.path.basename(os.path.splitext(f)[0]).replace('_side-a', '')
        mid = os.path.join(tmp, base + '.mid')
        try:
            if not D.decompile(f, out=mid, quiet=True):
                continue
            data, rep, facts = compile_midi(mid, auto='off')
            if facts['sides'] is None:
                back = os.path.join(tmp, base + '.bin')
                with open(back, 'wb') as fh:
                    fh.write(data)
            else:
                # Written as a pair and read back as one: card_decompile finds
                # the side B by name, exactly as it does for the originals.
                for tag, blob in zip(('a', 'b'), data):
                    with open(os.path.join(
                            tmp, '%s_side-%s.bin' % (base, tag)), 'wb') as fh:
                        fh.write(blob)
                back = os.path.join(tmp, base + '_side-a.bin')
            mid2 = os.path.join(tmp, base + '.2.mid')
            D.decompile(back, out=mid2, quiet=True)
            a = _digest(mid)
            b = _digest(mid2)
        except Exception as e:
            failed += 1
            if len(firsts) < 6:
                firsts.append('%s: %s' % (base[:44], e))
            continue
        if facts['sides'] is not None:
            two_sided += 1
            if max(facts['sides']) > MAX_CARD:
                oversize += 1
        elif facts['bytes'] > MAX_CARD:
            oversize += 1
        if facts['flat_bytes'] > MAX_CARD:
            flat_oversize += 1
        saved.append(facts['flat_bytes'] - facts['bytes'])
        for ch in a:
            if a[ch] == b[ch]:
                per[ch] += 1
        capped = facts['chart_dropped'] > 0
        fits['capped' if capped else 'fits'] += 1
        if a[X.CHORD_CH] == b[X.CHORD_CH]:
            fits[('capped' if capped else 'fits') + ' and matched'] += 1
        if a == b:
            same += 1
        else:
            diff += 1
            if len(firsts) < 6:
                firsts.append('%s: %s' % (base[:44], _first_difference(a, b)))
    n = same + diff + failed
    names = {X.MEL_CH: 'melody', X.OBB_CH: 'obbligato',
             X.CHORD_CH: 'chords', X.CTL_CH: 'control'}
    print('round trip over %d cards' % n)
    print('  %d identical in every part, %d differ, %d failed to compile'
          % (same, diff, failed))
    for ch in sorted(names):
        print('    %-10s %3d of %d  (%.1f%%)'
              % (names[ch], per[ch], n, 100.0 * per[ch] / max(1, n)))
    print('  chords, split by whether the chart fitted in %d entries:' % X.MAX_CHART)
    for k in ('fits', 'capped'):
        print('    %-7s %3d cards, %3d matched' % (k, fits[k], fits[k + ' and matched']))
    fit = n - oversize
    print('  size, against the %d-byte strip:' % MAX_CARD)
    if two_sided:
        print('    %d written over two sides, %d of which still do not fit'
              % (two_sided, oversize))
    print('    %d of %d fit once compressed, against %d flat'
          % (fit, n, n - flat_oversize))
    if saved:
        saved.sort()
        print('    compression saves a median %d bytes a card, up to %d'
              % (saved[len(saved) // 2], saved[-1]))
    for s in firsts:
        print('  ! %s' % s)


def _digest(mid):
    """What a player would hear, in a form two cards can be compared by.

    Events sharing a tick are sorted, so the order among them does not count as
    a difference.  That is not a weakened test: a bar mark, the duck, the
    phrase counter and the accompaniment mute each write a different piece of
    state, so which of them the stream lists first at a given moment changes
    nothing about what the instrument does.  Everything that IS audible - the
    tick, the pitch and the length - is compared exactly."""
    m = X.read_midi(mid)
    out = {}
    for ch in (X.MEL_CH, X.OBB_CH, X.CHORD_CH, X.CTL_CH):
        ev = [(n[0], n[2], n[4]) if ch != X.CTL_CH else (n[0], n[2])
              for n in m['notes'] if n[1] == ch]
        out[ch] = sorted(ev)
    return out


def _first_difference(a, b):
    names = {X.MEL_CH: 'melody', X.OBB_CH: 'obbligato',
             X.CHORD_CH: 'chords', X.CTL_CH: 'control'}
    for ch in sorted(a):
        if a[ch] == b[ch]:
            continue
        for i, (x, y) in enumerate(zip(a[ch], b[ch])):
            if x != y:
                return '%s event %d: %s became %s' % (names[ch], i, x, y)
        return ('%s has %d events, became %d'
                % (names[ch], len(a[ch]), len(b[ch])))
    return 'no difference found'


if __name__ == '__main__':
    P.run(main)
