#!/usr/bin/env python3
"""
Repeat compression for generated Playcards.

A card has four independently compressible structures - two duration tracks and
two opcode streams - and one repeat mechanism, described in playcard-format.md
and reproduced exactly by playcard_resolve.py.  This module finds a repeat
worth factoring out and rewrites a sequence into the stored form that produces
it.  Nothing here decides whether the result is correct: the resolver does that,
and midi_compile.py falls back to the flat form if it disagrees.

MACHINE-NEUTRAL.  Repeat structure is a property of the format, not of any one
instrument: a compressed card resolves to the same event sequence as the flat
one, so nothing here can change what any machine plays.  "Playback" below means
the resolver's expansion, not an instrument's.

THE SHAPE THE FORMAT ALLOWS

With k markers the stored form is

    stored     S1 [m] S2 [m] ... Sk [m] BODY
    playback   S1 BODY S2 BODY ... S(k-1) BODY Sk

because the call address is the position just past the LAST marker.  Every
marker but the last becomes a call to the tail; the last becomes the return
that ends the structure.  So the body is stored once and played k-1 times.

Turn that around: to factor out j non-overlapping occurrences of a body B, emit
the j+1 segments that sit between them, each followed by a marker, and then one
copy of B.  Any set of non-overlapping occurrences works, because the segments
are simply whatever is left between them.

    saving = (j-1) * |B| - (j+1) * marker

so j = 1 always loses and j = 2 pays only if the body is bigger than three
markers.  Sizes are in whatever unit the caller counts in - nibbles for an
opcode stream, symbols for a duration track.

THE CHORD CHART IS WHY THE OBBLIGATO STREAM IS DIFFERENT

Chart positions are indices into the STORED stream, and the chart is merged in
during decoding, before the repeat pass runs.  So an entry inside a body is
decoded once and then replayed on every pass - which is exactly how an original
card covers a hundred chord changes with the 62 entries its table holds.

It also means a body may only be factored out if the chart says the same thing
in every occurrence.  `accept` is the hook for that: it is handed the candidate
occurrences and returns the subset that may be used together.  Without it a
compressed card would quietly play the wrong chords over the repeats.
"""

_MOD = (1 << 61) - 1
_BASE = 1315423911


def _hashes(ids, n):
    """Prefix hashes, so any window's hash is O(1)."""
    h = [0] * (n + 1)
    for i in range(n):
        h[i + 1] = (h[i] * _BASE + ids[i] + 1) % _MOD
    return h


def _powers(n):
    p = [1] * (n + 1)
    for i in range(n):
        p[i + 1] = (p[i] * _BASE) % _MOD
    return p


def find_span(seq, cost=None, marker_cost=1, accept=None, min_units=1,
              forbid=()):
    """Find the repeat worth factoring out of `seq`.

    cost(item) -> units, defaulting to 1 for everything.  accept(occurrences,
    length) -> the subset that may be used together, defaulting to all of them.

    `forbid` is the set of markers already placed by earlier spans.  A body may
    not contain one, because bodies are stored in the order they were chosen
    and a span's markers all have to precede its own body: an earlier span's
    marker swept into a later span's body would end up AFTER that span's body
    and move the address the back-fill calls.  A marker of a LATER span inside
    an earlier body is the nesting case and is exactly what we want.

    Returns (length, occurrences, saving) with at least two occurrences, or
    None if nothing pays."""
    n = len(seq)
    if n < 8:
        return None
    cost = cost or (lambda x: 1)
    if forbid:
        bad = [0] * (n + 1)
        for i in range(n):
            bad[i + 1] = bad[i] + (1 if seq[i] in forbid else 0)

        def free(i, L):
            return bad[i + L] == bad[i]
    else:
        def free(i, L):
            return True

    index = {}
    ids = []
    for x in seq:
        if x not in index:
            index[x] = len(index)
        ids.append(index[x])
    h = _hashes(ids, n)
    pw = _powers(n)
    csum = [0] * (n + 1)
    for i, x in enumerate(seq):
        csum[i + 1] = csum[i] + cost(x)

    def window(i, L):
        return (h[i + L] - h[i] * pw[L]) % _MOD

    best = None
    # A body longer than half the sequence cannot occur twice.  Every length is
    # tried; the sweep is O(n^2) in dictionary operations, which for the few
    # hundred events a card carries is well under a second.  Most windows hash
    # uniquely and drop out at once, so the work that looks quadratic is not.
    for L in range(n // 2, 1, -1):
        groups = {}
        for i in range(n - L + 1):
            if free(i, L):
                groups.setdefault(window(i, L), []).append(i)
        for positions in groups.values():
            if len(positions) < 2:
                continue
            # guard against a hash collision before trusting the group
            first = seq[positions[0]:positions[0] + L]
            positions = [p for p in positions if seq[p:p + L] == first]
            if len(positions) < 2:
                continue
            if accept is not None:
                positions = accept(positions, L)
                if not positions or len(positions) < 2:
                    continue
            occ = []
            last = -1
            for p in positions:
                if p >= last:
                    occ.append(p)
                    last = p + L
            if len(occ) < 2:
                continue
            blen = csum[occ[0] + L] - csum[occ[0]]
            saving = (len(occ) - 1) * blen - (len(occ) + 1) * marker_cost
            if saving >= min_units and (best is None or saving > best[2]):
                best = (L, occ, saving)
    return best


def apply_span(seq, length, occ, marker):
    """Rewrite `seq` into its stored form.

    Returns (stored, origin) where origin[i] is the index in `seq` that
    stored[i] came from, or None for a marker.  Body items carry the index they
    had in the FIRST occurrence, which is the copy actually stored."""
    stored, origin = [], []
    at = 0
    for p in occ:
        for k in range(at, p):
            stored.append(seq[k])
            origin.append(k)
        stored.append(marker)
        origin.append(None)
        at = p + length
    for k in range(at, len(seq)):
        stored.append(seq[k])
        origin.append(k)
    stored.append(marker)
    origin.append(None)
    for k in range(occ[0], occ[0] + length):
        stored.append(seq[k])
        origin.append(k)
    return stored, origin


def body_range(length, occ):
    """The half-open range of `seq` indices that the stored body copies."""
    return occ[0], occ[0] + length


def apply_spans(seq, chosen):
    """Lay out several spans at once.

    `chosen` is [(length, occurrences, marker)], the bodies in the order they
    are to be stored.  The tail must read

        [m1] BODY1 [m2] BODY2 ... [mN] BODYN

    because a call to span i's body starts just past span i's last marker and
    runs until the next RETURN - and the next return is span i+1's last marker,
    which the back-fill rewrites into one.  So each body is bracketed by its own
    marker and the following span's, and the last body is closed by the
    terminator that E.terminated() adds.

    Occurrences of every span become markers in place, which is what turns them
    into calls.  Returns (stored, origin) with origin[i] the index in `seq` that
    stored[i] came from, or None for a marker; a body item carries the index it
    had in its FIRST occurrence, the copy actually stored."""
    starts = {}
    for length, occ, marker in chosen:
        for p in occ:
            starts[p] = (length, marker)

    stored, origin = [], []
    i = 0
    while i < len(seq):
        if i in starts:
            length, marker = starts[i]
            stored.append(marker)
            origin.append(None)
            i += length
        else:
            stored.append(seq[i])
            origin.append(i)
            i += 1
    for length, occ, marker in chosen:
        stored.append(marker)
        origin.append(None)
        for k in range(occ[0], occ[0] + length):
            stored.append(seq[k])
            origin.append(k)
    return stored, origin


def apply_one(stored, origin, length, occ, marker):
    """Factor one span out of the sequence as it currently stands.

    Occurrences become markers in place and one copy of the body is appended,
    preceded by its own marker.  Applied repeatedly this builds the tail

        [m1] BODY1 [m2] BODY2 ...

    and, because each round searches the sequence the previous round produced,
    a later span's occurrences may sit INSIDE an earlier span's body.  That is
    nesting, and it is what every multi-span structure in the corpus does:
    calling the outer span then makes calls to the inner one."""
    starts = set(occ)
    out, out_origin = [], []
    i = 0
    while i < len(stored):
        if i in starts:
            out.append(marker)
            out_origin.append(None)
            i += length
        else:
            out.append(stored[i])
            out_origin.append(origin[i])
            i += 1
    out.append(marker)
    out_origin.append(None)
    for k in range(occ[0], occ[0] + length):
        out.append(stored[k])
        out_origin.append(origin[k])
    return out, out_origin


def compress(seq, markers, cost=None, marker_cost=1, accept_for=None,
             max_spans=4):
    """Factor out up to `max_spans` repeats, best first, nesting as it goes.

    Each round runs over the sequence the last round produced, so a body found
    now may lie inside a body factored earlier.  `accept_for(origin)` is handed
    the current stored-to-original mapping and returns the `accept` hook for
    this round, or None.

    Returns (stored, origin, saving, chosen) or None.  `origin[i]` is the index
    in the original `seq` that stored[i] came from, or None for a marker; every
    original index appears at most once, in the one copy that survives."""
    if not isinstance(markers, list):
        markers = [markers]
    stored = list(seq)
    origin = list(range(len(seq)))
    rep = {}                       # an index that was factored out -> the copy kept
    chosen = []
    total = 0
    placed = set()

    def locate(f):
        """Where an original index ended up, following it through every span
        that folded its occurrence into a body stored once."""
        seen = set()
        while f in rep and f not in seen:
            seen.add(f)
            f = rep[f]
        return where.get(f)

    where = dict((f, i) for i, f in enumerate(origin) if f is not None)

    for marker in markers[:max_spans]:
        accept = accept_for(locate) if accept_for else None
        got = find_span(stored, cost=cost, marker_cost=marker_cost,
                        accept=accept, forbid=placed)
        if not got:
            break
        length, occ, saving = got
        for j in range(length):
            src = origin[occ[0] + j]
            if src is None:
                continue
            for q in occ[1:]:
                dst = origin[q + j]
                if dst is not None:
                    rep[dst] = src
        stored, origin = apply_one(stored, origin, length, occ, marker)
        where = dict((f, i) for i, f in enumerate(origin) if f is not None)
        chosen.append((length, len(occ), marker))
        total += saving
        placed.add(marker)
    if not chosen:
        return None
    return stored, origin, total, chosen, locate
