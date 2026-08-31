#!/usr/bin/env python3
"""
Reproduce the cartridge's own repeat resolution, exactly.

The compressed stream marks repeats but does not say where they go.  The
cartridge decodes into a byte buffer and then runs a back-fill pass, which is
what turns the markers into a call/return program.  This module does the same
thing, so no emulator is needed to get playback order right.

The cartridge's algorithm, from the ROM:

  While decoding (0x6535 for opcode streams, 0x6360 for duration tracks) each
  repeat marker emits THREE bytes - the marker itself and a two-byte hole - and
  records the address just past that record in slot[n] of a four-entry table at
  0xE46B.  A later marker for the same span overwrites the slot, so the slot
  ends up holding the position after the LAST marker for that span.

  When the track ends (0x638B) it resolves each span in turn (0x6398):

      DE = slot[n]; skip the span if the slot was never set.
      Walk the buffer from the start of this track's region:
          byte  < 0xE1   ordinary data, one byte
          byte >= 0xF0   a marker: if it is span n, rewrite it as 0xF0 and
                         fill its hole with DE; otherwise skip its two bytes
          otherwise      a two-byte record (0xE1/0xE7/0xE8).  Skip it, then if
                         we have reached or passed DE, write E1 10 00 over the
                         three bytes ending at DE - that is, over the last
                         marker - and stop resolving this span.

  So every marker for a span except the last becomes a call to the span body,
  and the last one becomes the return that ends it.

Reading the result is then trivial: walk the bytes, 0xF0 with an address is a
call, 0xE1 0x10 is a return.
"""

import playcard_decode as P

T65C8 = P.T65C8


class Buf:
    """The decoded byte buffer, built the way the cartridge builds it."""

    def __init__(self, base=0xD377):
        self.base = base
        self.b = bytearray()
        self.slots = [0, 0, 0, 0]

    @property
    def addr(self):
        return self.base + len(self.b)

    def byte(self, v):
        self.b.append(v & 0xFF)

    def pair(self, a, b):
        self.b.append(a & 0xFF)
        self.b.append(b & 0xFF)

    def marker(self, span):
        self.b.append(0xF0 | (span * 2))
        self.b.append(0)
        self.b.append(0)
        self.slots[span] = self.addr          # address just past the record


def backfill(buf, region_start):
    """The pass at ROM 0x6398, over one track's region."""
    data = buf.b
    base = buf.base
    for span in range(4):
        de = buf.slots[span]
        if not de:
            continue
        i = region_start - base
        end = len(data)
        while i < end:
            v = data[i]
            if v < 0xE1:
                i += 1
                continue
            if v >= 0xF0:
                if (v & 6) == span * 2:
                    data[i] = 0xF0
                    data[i+1] = de & 0xFF
                    data[i+2] = (de >> 8) & 0xFF
                i += 3
                continue
            # a two-byte record; after skipping it, have we reached the span?
            i += 2
            if base + i >= de:
                k = de - base
                data[k-3] = 0xE1
                data[k-2] = 0x10
                data[k-1] = 0x00
                break


def emit_track(buf, track):
    """Lay a duration track into the buffer."""
    start = buf.addr
    for x in track:
        if 0xF0 <= x <= 0xF6:
            buf.marker((x - 0xF0) // 2)
        elif x == 0xE1:
            buf.pair(0xE1, 0x10)
        else:
            buf.byte(x)
    backfill(buf, start)
    return start


def emit_stream(buf, ops, table):
    """Lay an opcode stream into the buffer, including the inline 0xE7 records
    the position table injects (they occupy space, so they shift addresses)."""
    start = buf.addr
    pos = {p: v for v, p in table}
    counter = 1
    for kind, val in ops:
        if counter in pos:
            buf.pair(0xE7, pos[counter])
        if kind == 'loop':
            counter += 2
            buf.marker(val // 2)
        elif kind == 'mark':
            counter += 2
            buf.pair(0xE1, val)
        elif kind == 'loopend':
            counter += 1
            buf.pair(0xE1, 0x10)
        elif kind == 'pitch':
            counter += 1
            buf.byte(val)
        elif kind == 'oct':
            counter += 1
            buf.pair(0xE8, val)
        elif kind == 'ctl':
            counter += 1
            buf.pair(0xE1, val)
    backfill(buf, start)
    return start


def walk(buf, start, limit=200000):
    """Run the resolved buffer: sequential, 0xF0 calls, 0xE1 0x10 returns."""
    data = buf.b
    base = buf.base
    out = []
    stack = []
    i = start - base
    steps = 0
    while 0 <= i < len(data) and steps < limit:
        steps += 1
        v = data[i]
        if v == 0xF0:
            tgt = data[i+1] | (data[i+2] << 8)
            if tgt and len(stack) < 32:
                stack.append(i + 3)
                i = tgt - base
                continue
            i += 3
        elif v >= 0xF0:
            i += 3                       # an unresolved marker: skip it
        elif v == 0xE1:
            sub = data[i+1]
            if sub == 0x10:
                if stack:
                    i = stack.pop()
                    continue
                break                    # return with nothing pending: done
            out.append(('ctl', sub))
            i += 2
        elif v == 0xE7:
            out.append(('tbl', data[i+1]))
            i += 2
        elif v == 0xE8:
            out.append(('oct', data[i+1]))
            i += 2
        else:
            out.append(('byte', v))
            i += 1
    return out


def resolve(h):
    """Return the four parts in true playback order.

    Gives (melody_durations, obbligato_durations, melody_events,
    obbligato_events), each a list of (kind, value)."""
    buf = Buf()
    s_t1 = emit_track(buf, h['track1'])
    s_t2 = emit_track(buf, h['track2'])
    table, streams = h['sections'][0]
    s_s0 = emit_stream(buf, streams[0], table)
    s_s1 = emit_stream(buf, streams[1], table)
    return (walk(buf, s_t1), walk(buf, s_t2),
            walk(buf, s_s0), walk(buf, s_s1))


def counts(h):
    """Duration and note counts per part, for checking they pair up."""
    t1, t2, s0, s1 = resolve(h)
    d1 = sum(1 for k, v in t1 if k == 'byte')
    d2 = sum(1 for k, v in t2 if k == 'byte')
    p0 = sum(1 for k, v in s0 if k == 'byte')
    p1 = sum(1 for k, v in s1 if k == 'byte')
    return d1, p0, d2, p1


def _main():
        import os, sys
        args = sys.argv[1:]
        try:
            files = args or P.corpus()
        except P.Missing as e:
            sys.exit(str(e))
        bad = tot = 0
        for f in files:
            try:
                h = P.parse_card(P.tobits(P.check_card(f)))
            except P.Over:
                continue
            if h['type'] != 1 or not h['sections']:
                continue
            tot += 1
            d1, p0, d2, p1 = counts(h)
            gap = abs(d1 - p0) + abs(d2 - p1)
            if gap:
                bad += 1
            if args or gap == 0 and tot <= 0:
                print('%-46s mel %3d/%3d  obb %3d/%3d  gap=%d'
                      % (os.path.basename(f)[9:55], d1, p0, d2, p1, gap))
        print('%d of %d cards still desynchronise' % (bad, tot))


if __name__ == '__main__':
    P.run(_main)
