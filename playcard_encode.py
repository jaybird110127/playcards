#!/usr/bin/env python3
"""
Build a Yamaha Playcard image from scratch.

    import playcard_encode as E
    data = E.build(E.Card(tempo=15, rhythm=4, ...))
    open('mycard.bin','wb').write(data)

This is the inverse of playcard_decode.py, and every field means what that
module says it means.  It exists so that header fields and opcode values can be
turned into controlled experiments: write a card that does exactly one thing,
feed it to the real firmware, and hear what comes out.

THE THINGS THAT ARE EASY TO GET WRONG, all measured against the 267 real cards:

  * The file starts ONE BIT before the 2-bit block type, and that bit is 0 on
    261 of the 267 cards.  The CRC is seeded 0x8005, which is the state the 32
    stripped preamble bits leave behind.

  * The CRC to store is just the running register after the data, because
    folding a register back into itself yields zero.  build() checks this by
    re-parsing its own output.

  * After the CRC come 24 trailer bits OUTSIDE the checksum, and then zero
    padding to the next byte boundary.  That rule reproduces the observed
    distance from CRC to EOF on every one of the 267 cards (24 to 31 bits,
    exactly tracking endbit % 8).

  * Bar marks belong in the OBBLIGATO stream.  All 2030 marks in the corpus are
    in stream 1 and not one is in stream 0, so a card that puts them in the
    melody stream is not a card the firmware has ever been asked to play.

  * The mark value is not the nibble you write.  The escape sub-value goes
    through the table at ROM 0x65C8, so writing "mark 3" means emitting sub 0.
    mark() does that mapping for you.

  * Chord-chart values are stored as value+1 in a 6-bit field, which is why the
    accompaniment mute (0xFF) is written as 0 - it is the wrap-around.
"""

import playcard_decode as P

# --- alphabet indices, for readability at the call site ----------------------
SYM = {v: i for i, v in enumerate(P.ALPHA)}          # 96 -> 9, 0xE1 -> 11, ...

# escape sub-value that produces each bar-mark value (inverse of ROM 0x65C8)
MARK_SUB = {v: i for i, v in enumerate(P.T65C8)}     # mark 3 -> sub 0, mark 0 -> sub 6

# opcode that produces each YM2151 note code (inverse of ROM 0x6551)
NOTE_OP = {v: i for i, v in enumerate(P.OP07)}       # C (14) -> 3, rest (3) -> 0

REST = 0                                              # opcode 0: the unused note code
END = 14                                              # opcode E: end of stream

# The 24-bit trailer is a date - see card_dates.py - stored least significant
# field first as F <day units> <day tens> <month> <year> F, year 2 = 1982.  The
# year is a single nibble, so the field cannot express anything after 1995 and a
# card written today cannot state its real date.
#
# So these cards carry day 00, month 0, year 1980: structurally well formed, and
# a date that has never existed.  Nothing will ever mistake one of them for a
# card Yamaha pressed.
TRAILER_SYNTHETIC = 0xF0000F


class BW:
    """Bit writer, MSB first, keeping the same running CRC-16 the ROM keeps."""

    def __init__(self, crc=0x8005):
        self.bits = []
        self.crc = crc

    def put(self, value, n):
        for i in range(n - 1, -1, -1):
            bit = (value >> i) & 1
            self.bits.append(bit)
            msb = (self.crc >> 15) & 1
            self.crc = (self.crc << 1) & 0xFFFF
            if msb ^ bit:
                self.crc ^= 0x8005

    def put_raw(self, value, n):
        """Bits outside the checksummed block - the trailer and the padding."""
        for i in range(n - 1, -1, -1):
            self.bits.append((value >> i) & 1)

    def tobytes(self):
        if len(self.bits) % 8:
            raise AssertionError('bit stream is not byte aligned - pad it first')
        out = bytearray()
        for i in range(0, len(self.bits), 8):
            byte = 0
            for b in self.bits[i:i + 8]:
                byte = (byte << 1) | b
            out.append(byte)
        return bytes(out)


def put_sym(bw, v):
    """The alternating-run prefix code of ROM 0x631E.

    Value v is k+1 copies of b0 followed by one opposite bit, where
    k = v >> 1 and the closing bit is v & 1."""
    k, b = v >> 1, v & 1
    b0 = 1 - b
    for _ in range(k + 1):
        bw.put(b0, 1)
    bw.put(b, 1)


def put_track(bw, alphabet, durations):
    """One duration track: its symbols, then the 0xE1 terminator and 3 bits."""
    idx = {a: i for i, a in enumerate(alphabet)}
    for d in durations:
        put_sym(bw, idx[d])
    put_sym(bw, idx[0xE1])
    bw.put(0, 3)


def put_chart(bw, entries):
    """The section table: (chord value, opcode position) pairs.

    A 4-bit code of 15 is not a position but an instruction to set the current
    chord value, carried as value+1 in the 6 bits that follow - so the mute
    0xFF is written as 0.  Positions are opcode indices within the stream and
    are emitted with the value that was last set."""
    # ROM 0x6454 loads D = 0x3F, so the parse takes at most 63 entries - and it
    # stops on the count without reading the end-of-table marker, which leaves
    # ten bits unread and parses both opcode streams from the wrong bit.  The
    # usable maximum is 62, which is exactly the largest chart in the corpus.
    # Over it the card still builds and its CRC still fails, which is a
    # confusing way to find out.  Value-change records are not counted: they
    # do not decrement the ROM's counter, and real cards reach 83 records.
    if len(entries) > 62:
        raise ValueError('the section table holds 62 entries, not %d (ROM 0x6454)'
                         % len(entries))
    current = None
    for value, pos in entries:
        if value != current:
            bw.put(15, 4)
            bw.put((value + 1) & 0x3F, 6)
            current = value
        if not 0 < pos < 0x3C0 or (pos >> 6) == 15:
            raise ValueError('position %d is not encodable' % pos)
        bw.put(pos >> 6, 4)
        bw.put(pos & 0x3F, 6)
    bw.put(0, 10)                                    # end of table


def put_stream(bw, ops):
    """One 4-bit opcode stream, closed with the end opcode.

    ops entries are ('note', code) | ('rest', None) | ('mark', value)
                  | ('oct', 0|1|2) | ('ctl', 0x11|0x13|0x14)
                  | ('loop', span) | ('loopend', None)"""
    for kind, val in ops:
        if kind == 'note':
            bw.put(NOTE_OP[val], 4)
        elif kind == 'rest':
            bw.put(REST, 4)
        elif kind == 'mark':
            bw.put(15, 4)
            bw.put(MARK_SUB[val], 4)
        elif kind == 'oct':
            bw.put({1: 8, 2: 9, 0: 10}[val], 4)
        elif kind == 'ctl':
            bw.put({0x11: 11, 0x13: 12, 0x14: 13}[val], 4)
        elif kind == 'loop':
            bw.put(15, 4)
            bw.put(8 | (val & 3), 4)                 # sub >= 8 opens a span
        elif kind == 'loopend':
            bw.put(END, 4)                           # an E while a span is open
        else:
            raise ValueError('unknown op %r' % (kind,))
    bw.put(END, 4)


def terminated(ops):
    """Append the two opcodes that make a stream stop where it should.

    A stream carries no explicit end marker in the decoded buffer: the ROM's
    back-fill pass produces one, by rewriting the LAST repeat marker of a span
    as the return `E1 10`.  A stream with no repeat marker therefore never
    returns, and walking it runs straight on into the next stream - which is
    why no card in the corpus has a loopless MELODY stream, while the thirteen
    with a loopless obbligato get away with it only because that stream is the
    last region in the buffer.

    A span with exactly one marker is the whole trick.  Every marker but the
    last becomes a call to the span body; with only one there is no call, and
    the single marker becomes the return.  The `loopend` after it is what makes
    the back-fill notice: the rewrite fires at the first two-byte record at or
    past the marker, so something has to follow it.  Nothing repeats, and the
    stream ends exactly where the notes do."""
    return list(ops) + [('loop', 0), ('loopend', None)]


class Card:
    """One card to be built.  Field names match playcard_decode's output.

    tempo, rhythm, f3, mel_voice, sustain, obb_voice and key are the RAW header
    values - the ones written to the card, before the ROM's remap tables.  Use
    playcard_decode's tables to read back what they mean."""

    def __init__(self, tempo, rhythm, mel_voice, obb_voice, key=0,
                 f3=0, sustain=0, alphabet=(96, 0xE1),
                 mel_durs=(), obb_durs=(), mel_ops=(), obb_ops=(),
                 chart=(), trailer=TRAILER_SYNTHETIC):
        self.tempo, self.rhythm, self.f3 = tempo, rhythm, f3
        self.mel_voice, self.sustain, self.obb_voice = mel_voice, sustain, obb_voice
        self.key = key
        self.alphabet = list(alphabet)
        self.mel_durs, self.obb_durs = list(mel_durs), list(obb_durs)
        self.mel_ops, self.obb_ops = list(mel_ops), list(obb_ops)
        self.chart = list(chart)
        self.trailer = trailer


def _header_and_tracks(bw, card):
    """The header and both duration tracks - everything a side A carries."""
    bw.put(card.tempo, 5)
    bw.put(card.rhythm, 4)
    bw.put(card.f3, 3)
    bw.put(card.mel_voice, 4)
    bw.put(card.sustain, 1)
    bw.put(card.obb_voice, 3)
    bw.put(card.key, 4)
    bw.put(len(card.alphabet), 5)
    for a in card.alphabet:
        bw.put(SYM[a], 5)

    put_track(bw, card.alphabet, card.mel_durs)
    put_track(bw, card.alphabet, card.obb_durs)


def _section(bw, card):
    """The chart and both opcode streams - everything a side B carries."""
    put_chart(bw, card.chart)
    put_stream(bw, card.mel_ops)
    put_stream(bw, card.obb_ops)


def _close(bw, card):
    """The CRC, the pad and the date trailer, in that order."""
    crc = bw.crc
    bw.put(crc, 16)                                  # folding it in yields zero
    if bw.crc != 0:
        raise AssertionError('CRC did not close to zero')

    # Outside the checksum: zero-pad to the byte boundary FIRST, then lay the
    # 24-bit trailer down byte-aligned as the file's last three bytes.  Doing it
    # the other way round writes the trailer at whatever bit offset the CRC
    # happened to end on, and it comes back out shifted.
    pad = (-(len(bw.bits) + 24)) % 8
    if pad:
        bw.put_raw(0, pad)
    bw.put_raw(card.trailer, 24)
    return bw.tobytes()


def _check_pairs(h):
    import playcard_resolve as R
    d1, p0, d2, p1 = R.counts(h)
    if d1 != p0 or d2 != p1:
        raise AssertionError(
            'durations and pitches do not pair one-to-one: '
            'melody %d/%d, obbligato %d/%d' % (d1, p0, d2, p1))


def build(card, verify=True):
    """Card -> the bytes of a .bin image, on one side.

    With verify (the default) the result is parsed straight back and checked:
    valid CRC, and a duration track and its pitch stream expanding to the same
    number of events.  A card that fails either is not worth feeding to the
    firmware."""
    if len(card.alphabet) >= 26:
        raise ValueError('alphabet must be under 26 symbols (ROM 0x62D9)')

    bw = BW()
    bw.put(0, 1)                                     # the last preamble bit
    bw.put(1, 2)                                     # block type 1: a full card
    _header_and_tracks(bw, card)
    bw.put(2, 2)                                     # tag 2: a section follows
    _section(bw, card)
    bw.put(0, 2)                                     # tag 0: no more sections
    data = _close(bw, card)

    if verify:
        h = P.parse_card(P.tobits(data))
        if not h['crc_ok']:
            raise AssertionError('built card does not verify its own CRC')
        if h['type'] != 1:
            raise AssertionError('built card is not block type 1')
        _check_pairs(h)
    return data


def build_sides(card, verify=True):
    """Card -> (side A bytes, side B bytes), the same music over two swipes.

    The split is the format's, not a choice: **side A is a type-1 card with no
    section at all** - header and both duration tracks, then the terminator -
    and **side B is a type-2 block carrying nothing but the section**.  Nothing
    in either header says a second side exists; the cartridge infers it from the
    structure.  A type-1 card that ends with no section sets a flag at 0xE48B
    (ROM 0x6668), and a type-2 block is refused outright with error 0x80 unless
    that flag is set (ROM 0x6608), so the reader is a two-state machine and the
    sides have to be swiped in order.

    Both sides carry the same date trailer, which is what the three original
    pairs do.

    Side B is much the bigger half - durations compress far better than opcode
    streams - so the originals run 190/360, 148/301 and 161/379.  The split
    point is the format's, so a card whose SECTION alone will not fit the strip
    cannot be rescued by splitting it somewhere else."""
    if len(card.alphabet) >= 26:
        raise ValueError('alphabet must be under 26 symbols (ROM 0x62D9)')

    a = BW()
    a.put(0, 1)
    a.put(1, 2)                                      # type 1, but sectionless
    _header_and_tracks(a, card)
    a.put(0, 2)                                      # tag 0: no section here
    side_a = _close(a, card)

    b = BW()
    b.put(0, 1)
    b.put(2, 2)                                      # type 2: a continuation
    _section(b, card)
    b.put(0, 2)                                      # ROM 0x661A terminator
    side_b = _close(b, card)

    if verify:
        ha = P.parse_card(P.tobits(side_a))
        hb = P.parse_card(P.tobits(side_b))
        if not ha['crc_ok'] or not hb['crc_ok']:
            raise AssertionError('a built side does not verify its own CRC')
        if ha['type'] != 1 or ha['sections']:
            raise AssertionError('side A must be a type-1 card with no section')
        if hb['type'] != 2 or len(hb['sections']) != 1:
            raise AssertionError('side B must be a type-2 block with one section')
        ha['sections'] = hb['sections']              # the join the reader does
        _check_pairs(ha)
    return side_a, side_b
