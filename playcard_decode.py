#!/usr/bin/env python3
"""
Yamaha Playcard decoder.

Reverse-engineered from the cartridge ROM
"Play Card System (UPA-01) (1985) (Yamaha) (J).rom" (MSX, 16K at 0x4000).

Verified: all 267 original card images decode with a correct CRC-16.

The cards themselves are not in this repository - they are Yamaha's.  Keep them
in "Original Playcards", or set PLAYCARD_CARDS to wherever yours are.

WHICH MACHINE - the naming used across this whole repository

Four machines read these cards and they do NOT behave alike, so a comment that
says how something "plays" has to say whose playing it means:

    PC-100    1982.  The keyboard the cards were written FOR.  Most of what is
              known by ear.  It has no fill or drum controls at all.
    PCS-30    1984.  A second Playcard-capable keyboard, and the only
              independent implementation available - the one thing that can
              tell the format apart from one machine's reading of it.  Its
              accompaniment patterns are the ones pcs30_arrange.py uses.
    UPA-01    1985.  The Play Card System MSX cartridge, read through the
              CR-01 into a CX5M with an SFG-01.  Nearly every ROM address,
              register capture and emulator run here is this machine, because
              it is the one whose code can be disassembled and stepped.
    PC-1000   1983.  Context for one refuted hypothesis about the chord chart.

Unqualified, "the cartridge", "the firmware" and "the ROM" mean the UPA-01.
Anything else is named.

And the warning that goes with that: the UPA-01 is a 1985 port and not a
faithful one.  It drops chord notes, gives every fill a fixed feel instead of
the rhythm's, and falls silent on a same-root chart entry.  All three were
written up as facts about the FORMAT before a second machine disagreed.  So
where the cartridge is the only witness and the claim is about how something
SOUNDS rather than what the bytes ARE, read it as what the cartridge does.
See "Which machine is being described" in playcard-format.md.

Usage:
    python playcard_decode.py <file.bin>      # dump one card
    python playcard_decode.py --all           # summary table for every card
"""

import sys, glob, os, shutil, textwrap

# ---------------------------------------------------------------- where things live

# The repository holds no card images and no ROMs: both are Yamaha's, so they
# are kept out of it.  Card images live in "Original Playcards", ROMs in "Roms",
# and neither is published.  Point PLAYCARD_CARDS / PLAYCARD_ROMS elsewhere if
# yours are somewhere else.

HERE = os.path.dirname(os.path.abspath(__file__))

CARD_DIR = os.environ.get('PLAYCARD_CARDS') or os.path.join(HERE, 'Original Playcards')
ROM_DIR = os.environ.get('PLAYCARD_ROMS') or os.path.join(HERE, 'Roms')
NEW_CARD_DIR = os.path.join(HERE, 'new-cards')

CART_ROM = 'Play Card System (UPA-01) (1985) (Yamaha) (J).rom'


class Missing(Exception):
    """A card folder or ROM that is not present.  Its message is meant to be
    printed as-is: these files are deliberately absent from the repository."""


class WrongFile(Missing):
    """The file is there, it is just not the kind of file this tool wants.

    A subclass of Missing so that the handlers already catching that print it
    and stop, rather than showing a traceback: to a user, "I cannot find it"
    and "that is not one of those" are the same kind of answer.
    """


# What a file looks like from its first bytes.  Enough to tell somebody what
# they handed over, which is the whole job - not a general file(1).
def kind_of(path):
    """A short phrase naming what a file appears to be."""
    if os.path.isdir(path):
        return 'a folder'
    try:
        with open(path, 'rb') as f:
            head = f.read(4096)
        size = os.path.getsize(path)
    except (IOError, OSError) as e:
        return 'unreadable (%s)' % e.strerror
    if not size:
        return 'an empty file'

    magic = [(b'MThd', 'a MIDI file'), (b'%PDF', 'a PDF'),
             (b'\x7fELF', 'an ELF executable'), (b'MZ', 'a Windows executable'),
             (b'PK\x03\x04', 'a zip archive'), (b'\x1f\x8b', 'a gzip archive'),
             (b'\x89PNG', 'a PNG image'), (b'\xff\xd8\xff', 'a JPEG image'),
             (b'GIF8', 'a GIF image'), (b'OggS', 'an Ogg file'),
             (b'fLaC', 'a FLAC file'), (b'ID3', 'an MP3'),
             (b'{\\rtf', 'an RTF document'), (b'\xd0\xcf\x11\xe0', 'an Office document')]
    for sig, what in magic:
        if head.startswith(sig):
            return what
    if head.startswith(b'RIFF') and head[8:12] == b'WAVE':
        return 'a WAV recording'
    if head.startswith(b'RIFF'):
        return 'a RIFF file'

    low = head[:512].lower()
    if low.lstrip().startswith(b'<!doctype html') or low.lstrip().startswith(b'<html'):
        return 'an HTML document'
    if low.lstrip().startswith(b'<?xml') or low.lstrip().startswith(b'<'):
        return 'an XML or HTML document'

    # Text, including UTF-8: no control bytes beyond tab, newline and return.
    try:
        text = head.decode('utf-8')
        if not [c for c in text if ord(c) < 32 and c not in '\t\n\r']:
            s = head.lstrip()[:1]
            if s in (b'{', b'['):
                return 'a JSON file'
            if head.startswith(b'#!'):
                return 'a script'
            return 'a text file'
    except UnicodeDecodeError:
        pass

    # A Playcard is 40 to 433 bytes with no magic number at all, so the only
    # honest test is whether the decoder can make sense of it.
    if size <= 433:
        try:
            h = parse_card(tobits(head[:size]))
            if h.get('type') in (1, 2):
                return ('a Playcard image' if h.get('crc_ok')
                        else 'a Playcard image with a bad CRC')
        except Exception:
            pass
    return 'a %d-byte binary of some other kind' % size


def _refuse(path, wanted):
    name = os.path.basename(path)
    if not os.path.exists(path):
        return WrongFile(wrapped('there is no file at %s' % path, prefix=''))
    what = kind_of(path)
    msg = ('%s is %s, and this tool wants %s. Check the filename, or the tool.'
           % (name, what, wanted))
    # A binary of about the right size is more likely a damaged card than a
    # wrong file, and there is a tool for that.
    if (wanted == 'a Playcard image' and what.startswith('a ')
            and what.endswith('binary of some other kind')):
        msg += ('  If it really is a card and something has damaged it, '
                'forge_crc.py will say where the decoding stops.')
    return WrongFile(wrapped(msg, prefix=''))


def check_file(path, wanted='a file'):
    """Only that it is there and readable, for tools doing their own sniffing.

    forge_crc is the case: its whole job is cards too damaged to parse, so it
    must be handed the bytes of anything that exists.
    """
    if not os.path.isfile(path):
        raise _refuse(path, wanted)
    try:
        return open(path, 'rb').read()
    except (IOError, OSError) as e:
        raise WrongFile(wrapped('cannot read %s (%s)'
                                % (path, e.strerror or e), prefix=''))


def check_card(path):
    """The bytes of a card image, or WrongFile saying what was handed over.

    Structure only: a card whose CRC has been damaged on purpose is still a
    card, and forge_crc exists to repair exactly those.
    """
    if not os.path.isfile(path):
        raise _refuse(path, 'a Playcard image')
    data = open(path, 'rb').read()
    if len(data) > 433 or not data:
        raise _refuse(path, 'a Playcard image')
    try:
        h = parse_card(tobits(data))
    except Exception:
        raise _refuse(path, 'a Playcard image')
    if h.get('type') not in (1, 2):
        raise _refuse(path, 'a Playcard image')
    return data


def check_midi(path):
    """The bytes of a MIDI file, or WrongFile."""
    if not os.path.isfile(path):
        raise _refuse(path, 'a MIDI file')
    data = open(path, 'rb').read()
    if not data.startswith(b'MThd'):
        raise _refuse(path, 'a MIDI file')
    return data


def check_wav(path):
    """The bytes of a RIFF/WAVE recording, or WrongFile."""
    if not os.path.isfile(path):
        raise _refuse(path, 'a WAV recording')
    data = open(path, 'rb').read()
    if not (data.startswith(b'RIFF') and data[8:12] == b'WAVE'):
        raise _refuse(path, 'a WAV recording')
    return data


def wrapped(text, prefix='', hang=None):
    """A sentence broken where the words are rather than where the terminal
    runs out.

    Several of these tools have things to say that do not fit on one line, and
    a terminal breaking a message in the middle of a word is horrible to read.
    Tables and file paths are left alone - they are not prose, and wrapping them
    would be worse - so this is for sentences only.
    """
    width = min(shutil.get_terminal_size((80, 24)).columns - 1, 100)
    hang = prefix if hang is None else hang
    body = textwrap.wrap(text, max(20, width - len(prefix))) or ['']
    return '\n'.join((prefix if i == 0 else hang) + line
                     for i, line in enumerate(body))


def say(text, prefix='  ', hang=None):
    """`wrapped`, printed."""
    print(wrapped(text, prefix, hang))


def run(main):
    """Run a tool's main(), and answer the two things a user does by accident.

    A missing card folder or ROM, and a file that is not the kind this tool
    wants, both end as a sentence and exit 1 - a traceback tells the user
    nothing they can act on.  Ctrl-C is not an error at all.
    """
    try:
        sys.exit(main())
    except Missing as e:
        sys.exit(str(e))
    except KeyboardInterrupt:
        sys.exit(130)


def corpus(where=None):
    """Every original card image, sorted.  This is what the corpus-wide checks
    in these tools run over, and what the counts quoted in the documentation
    (267 cards, 261 with sections) refer to."""
    d = where or CARD_DIR
    if not os.path.isdir(d):
        raise Missing(
            'no card folder at %s\n'
            'The original Playcards are Yamaha copyright and are not in this '
            'repository.\nPut your own .bin images there, or set PLAYCARD_CARDS '
            'to the folder holding them.' % d)
    files = sorted(glob.glob(os.path.join(d, '*.bin')))
    if not files:
        raise Missing('no .bin card images in %s' % d)
    return files


def new_cards():
    """The cards written in 2026 to isolate one firmware behaviour each.
    These are in the repository - they are ours, not Yamaha's."""
    return sorted(glob.glob(os.path.join(NEW_CARD_DIR, '*.bin')))


def rom(name=CART_ROM):
    """The path to a ROM image, or a Missing explaining that it is not shipped."""
    p = name if os.path.isabs(name) else os.path.join(ROM_DIR, name)
    if not os.path.isfile(p):
        raise Missing(
            'no ROM at %s\n'
            'ROM images are Yamaha copyright and are not in this repository.\n'
            'Put yours in %s, or set PLAYCARD_ROMS to the folder holding them.'
            % (p, ROM_DIR))
    return p


# ---------------------------------------------------------------- ROM tables

# ROM 0x63EA - metronome marks, selected by the 5-bit tempo index
TEMPO = [40, 48, 52, 56, 60, 63, 66, 69, 72, 76, 80, 84, 88, 92, 96, 100,
         104, 108, 112, 116, 120, 126, 132, 138, 144, 152, 160, 168, 176,
         184, 192, 200]

# ROM 0x640A / 0x641A / 0x642A - small remap tables for the header fields
T640A = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 0, 0, 0, 0, 0, 0]
T641A = [0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
T642A = [1, 2, 3, 4, 5, 6, 7, 8]

# ROM 0x7A39 - rhythm style names shown in the cartridge UI
RHYTHM = ['(none)', 'rhumba', 'samba', 'swing', 'bossa-nova', 'rock',
          '16-beat', 'waltz', 'slow-rock', 'march', 'disco']

# ROM 0x6434 - the 32 symbols a card may put in its per-song alphabet.
# 24 ticks = one quarter note.  Bit 7 set = LIFT: the finger comes off at the
# end of that event, so a following event on the same pitch re-strikes rather
# than tying.  It is not a rest; see playcard-format.md.
ALPHA = [6, 8, 12, 16, 18, 24, 36, 48, 72, 96,
         0xFF, 0xE1, 0xF0, 0xF2, 0xF4, 0xF6,
         0x86, 0x88, 0x8C, 0x90, 0x92, 0x98, 0xA4, 0xB0, 0xC8, 0xE0,
         0x22, 0x7D, 0xE4, 0x21, 0xAE, 0xE3]

T65C8 = [3, 4, 5, 6, 1, 2, 0, 7]        # ROM 0x65C8 (index 7 runs into 0x65CF)
OP07  = [3, 10, 13, 14, 1, 4, 5, 8]     # ROM 0x6551 + 0x65CF, opcodes 0..7

# Voice fields index the SFG-01's bank through two adjacent cartridge tables.
#
# TWO SETS OF NAMES, AND WHY THE OLDER ONE WINS
#
# SFG_NAMES are the labels the SFG-01 module shows on screen, which is where
# these were first read.  They are the 1985 cartridge's vocabulary: eight
# characters, upper case, with a bank digit on the end.
#
# VOICE_NAMES are what the PC-100 calls the same voices on its own control
# panel - five instrument buttons and an A/B selector, in the order below.  The
# PC-100 came out in 1982 and is the machine these cards were written for, so
# where the two disagree it is the older and more authoritative witness, and
# the name a player actually saw.  Six of the ten melody voices differ:
#
#   PORGAN1 -> organ      EPIANO1 -> piano      HARPSIC -> harpsichord
#   CLARINE -> clarinet   STRING2 -> violin     VIBRPHN -> vibraphone
#
# The obbligato voices are not user-selectable on the keyboard and so have no
# panel names at all.  They follow the same convention: no abbreviations, no
# capitals, no bank digits - which makes STRING1 `strings` and BRASS 1 `brass`.
#
# Both sets are accepted wherever a voice can be named; see voice_field().
SFG_NAMES = {1: 'BRASS 1', 3: 'TRUMPET', 4: 'STRING1', 5: 'STRING2', 6: 'EPIANO1',
             9: 'GUITAR', 14: 'PORGAN1', 16: 'FLUTE', 17: 'PICCOLO', 18: 'OBOE',
             19: 'CLARINE', 21: 'VIBRPHN', 26: 'HARPSIC'}
VOICE_NAMES = {1: 'brass', 3: 'trumpet', 4: 'strings', 5: 'violin', 6: 'piano',
               9: 'guitar', 14: 'organ', 16: 'flute', 17: 'piccolo', 18: 'oboe',
               19: 'clarinet', 21: 'vibraphone', 26: 'harpsichord'}
MELODY_VOICE    = [0, 17, 14, 5, 3, 18, 19, 26, 6, 21, 9]   # ROM 0x5C3F
OBBLIGATO_VOICE = [0, 18, 16, 4, 1, 19, 6, 26, 9]           # ROM 0x5C4B

# The PC-100's panel order: five buttons, then the same five with A/B switched.
PANEL_ORDER = [14, 3, 19, 6, 9, 17, 5, 18, 26, 21]

# The key field is itself a YM2151 note code; the shift is its chromatic position.
OPM_INDEX = {0: 0, 1: 1, 2: 2, 4: 3, 5: 4, 6: 5, 8: 6, 9: 7, 10: 8, 12: 9, 13: 10, 14: 11}
NOTE_NAME = {0: 'C#', 1: 'D', 2: 'D#', 4: 'E', 5: 'F', 6: 'F#', 8: 'G',
             9: 'G#', 10: 'A', 12: 'A#', 13: 'B', 14: 'C'}


def voice(table, field):
    """The PC-100 panel name of the voice a field selects."""
    if 0 <= field < len(table):
        return VOICE_NAMES.get(table[field], 'voice %d' % table[field])
    return '?'


def _norm(s):
    """Fold a voice name for matching: case, spaces and punctuation go."""
    return ''.join(c for c in str(s).lower() if c.isalnum())


# Every spelling that names a voice: the panel name and the SFG-01's own label.
VOICE_ALIASES = {}
for _n, _s in VOICE_NAMES.items():
    VOICE_ALIASES[_norm(_s)] = _n
for _n, _s in SFG_NAMES.items():
    VOICE_ALIASES.setdefault(_norm(_s), _n)
del _n, _s


def voice_field(table, name):
    """The field value that selects a named voice, or None if it is not one.

    Either vocabulary works, in any casing: 'clarinet', 'CLARINE' and
    'Clarinet' all find the same voice, and so do 'brass' and 'BRASS 1'.
    """
    num = VOICE_ALIASES.get(_norm(name))
    if num is None:
        return None
    for i in range(1, len(table)):
        if table[i] == num:
            return i
    return None


def voice_choices(table):
    """The names this field can take, in field order, for help and errors."""
    return [VOICE_NAMES.get(v, 'voice %d' % v) for v in table[1:]]


def key_shift(key):
    """Semitones to transpose by, from the header's key field.

    Takes the field either way round.  `parse_header` stores it SIGNED, the way
    the ROM reads it at 0x62C4 - codes 9 to 15 come back as -7 to -1 - while the
    field is really a 4-bit YM2151 note code.  Handing the signed form straight
    to a table indexed by note code silently yields no transposition at all, and
    that is exactly the bug this fixes: it made the 50 corpus cards whose field
    has its top bit set look untransposed, when the firmware plays them a fourth
    or a fifth away.  Jingle Bells, field -7 and so code 9, is -5 semitones, and
    the firmware agrees on all 194 of its melody notes.
    """
    if key < 0:
        key += 16
    return ((OPM_INDEX[key] + 6) % 12) - 6 if key in OPM_INDEX else 0


# The key field is a TRANSPOSITION, not the name of a key.  Numerically it is a
# YM2151 note code, which is why the chip's four unused codes never appear in
# it - but the note code's NAME is a semitone above the key, and naming the
# field after it is wrong.  Field 0 is no transposition at all, so its cards
# sound in whatever they were written in - never in C#.
#
# The best a key name can be is CONDITIONAL, and every caller must say so.  A
# card is written in whatever key was cheapest to store - a sharp costs an
# opcode, so the notes go on the white keys - and the field carries the distance
# from there to where the song belongs, not the destination.  Nothing in the
# header records the starting point, so the sounding key cannot be read off a
# card without looking at the music: measure it from the chord chart, which is
# stored at SOUNDING pitch and which this field never touches.
#
# Written in C is the common case and not the rule - 203 of 261 cards, with 36
# in A minor and 22 elsewhere.  The PC-100 9 to 5 is written in G and sounds in
# C, and the PCS-30 Summertime is written in D minor and sounds in A minor;
# name either from the field alone and you are a fourth out.  key_field_check.py
# measures all of this.
KEY_OF = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def key_name(key):
    """The key a card WRITTEN IN C sounds in once this field is applied.

    Conditional, and worth printing as such - "a card in C sounds in F" - or
    it reads as a fact about this card, which it is not.  See above."""
    return KEY_OF[key_shift(key) % 12]

DURNAME = {6: '16th', 8: '8th-trip', 12: '8th', 16: 'qtr-trip', 18: 'dot-8th',
           24: 'quarter', 36: 'dot-qtr', 48: 'half', 72: 'dot-half', 96: 'whole'}

# The section table's values are chords: (type << 4) | YM2151 note code.  The
# low nibble never lands on the chip's unused codes 7 and 11, exactly like the
# pitch opcodes.  0xFF is a sentinel, not a chord.
CHORD_TYPE = {0: '', 1: 'm', 2: '7', 3: 'm7'}


def chord(v):
    if v == 0xFF:
        return '--'
    n, t = v & 0x0F, (v >> 4) & 0x0F
    if n in NOTE_NAME and t in CHORD_TYPE:
        return NOTE_NAME[n].replace('A#', 'Bb') + CHORD_TYPE[t]
    return '?%02X' % v


class Over(Exception):
    """Ran off the end of the bitstream, or hit an impossible symbol."""


class BR:
    """Bit reader, MSB first, with the running CRC-16 the ROM keeps.

    ROM 0x618A reads the bits; ROM 0x61CC folds each one into a CRC-16
    with polynomial 0x8005, init 0, no reflection and no final xor.
    """

    def __init__(self, bits, pos=0, crc=0):
        self.b, self.p, self.crc = bits, pos, crc

    def get(self, n):
        v = 0
        for _ in range(n):
            if self.p >= len(self.b):
                raise Over()
            bit = self.b[self.p]
            self.p += 1
            v = (v << 1) | bit
            msb = (self.crc >> 15) & 1
            self.crc = (self.crc << 1) & 0xFFFF
            if msb ^ bit:
                self.crc ^= 0x8005
        return v


def tobits(data):
    out = []
    for byte in data:
        for i in range(7, -1, -1):
            out.append((byte >> i) & 1)
    return out


# ---------------------------------------------------------------- the codecs

def sym_code(br):
    """ROM 0x631E - alternating-run prefix code.

    A codeword is (k+1) copies of a bit b0 then one opposite bit; its value
    is 2k + (1-b0).  So values 0..1 cost 2 bits, 2..3 cost 3 bits, and so on.
    The value indexes the per-song alphabet built by the header, which is
    ordered most-frequent-first, making this a cheap static Huffman code.
    """
    b0 = br.get(1)
    k = 0
    while True:
        b = br.get(1)
        if b != b0:
            return 2 * k + b
        k += 1
        if k > 20:
            raise Over()


def parse_header(br):
    """ROM 0x6248."""
    h = {}
    h['tempo']     = TEMPO[br.get(5)]
    h['rhythm']    = T640A[br.get(4)]
    h['f3']        = br.get(3)
    h['field4']    = T641A[br.get(4)]
    h['bit1']      = br.get(1)
    h['field6']    = T642A[br.get(3)]
    t = br.get(4)
    h['transpose'] = t if t < 9 else t - 16      # ROM 0x62C4: 9..15 -> -7..-1
    n = br.get(5)
    if n >= 26:
        raise Over()                              # ROM 0x62D9 rejects >= 26
    h['alphabet'] = [ALPHA[br.get(5)] for _ in range(n)]
    return h


def parse_track(br, alpha, limit=4000):
    """ROM 0x6303/0x6317 - one run-length coded duration track.

    0xE1 closes a repeat span when a loop marker is pending (the ROM's flag
    at 0xE484); with nothing pending it ends the track and 3 bits follow.
    """
    out, last, pending = [], 0, 0
    for _ in range(limit):
        v = sym_code(br)
        if v >= len(alpha):
            raise Over()
        a = alpha[v]
        if a == 0xFF:                 # ROM 0x6348: repeat previous symbol
            a = last
        if a == 0xE1:
            out.append(0xE1)
            if pending:
                pending = 0
                continue
            br.get(3)
            return out
        if a > 0xE1:
            pending = 1               # ROM 0x636F: loop marker
            out.append(a)
        else:
            last = a
            out.append(a)
    raise Over()


def opcode_stream(br, limit=4000):
    """ROM 0x64AD/0x64C8 - 4-bit opcode stream (why the files are nibble aligned)."""
    ops, pending = [], 0
    while len(ops) <= limit:
        op = br.get(4)
        if op == 15:                                  # ROM 0x6510, escape
            sub = br.get(4)
            if sub < 8:
                ops.append(('mark', T65C8[sub]))
            else:
                pending = 1
                ops.append(('loop', (sub & 3) * 2))
        elif op == 14:                                # ROM 0x6585
            if pending:
                pending = 0
                ops.append(('loopend', 0x10))
            else:
                return ops
        elif op <= 7:  ops.append(('pitch', OP07[op]))
        elif op == 8:  ops.append(('oct', 1))
        elif op == 9:  ops.append(('oct', 2))
        elif op == 10: ops.append(('oct', 0))
        elif op == 11: ops.append(('ctl', 0x11))
        elif op == 12: ops.append(('ctl', 0x13))
        elif op == 13: ops.append(('ctl', 0x14))
    raise Over()


def parse_section(br):
    """ROM 0x644E - position/marker table, then two opcode streams.

    ROM 0x64A0 calls the stream parser and then falls through into it again,
    so a section always carries exactly two streams.
    """
    table, dur = [], 15                    # ROM 0x6456: default 15
    while len(table) < 63:                 # ROM 0x6454: D = 0x3F
        code, val = br.get(4), br.get(6)
        if code == 15:                     # ROM 0x6473: set marker value
            dur = (val - 1) & 0xFF
            continue
        v = (code << 6) | val              # ROM 0x6477 reassembles B:C
        if v == 0:
            break                          # end of table, rest zero filled
        table.append((dur, v))
    return table, [opcode_stream(br), opcode_stream(br)]


def parse_card(bits):
    """Decode one card image.

    The .bin files start one bit before the 2-bit block-type field: the
    32 preamble bits ahead of that were dropped by whatever extracted them,
    which is why the CRC has to start from the state they leave behind
    (0x8005 - a run of zeros then a single 1 bit).
    """
    br = BR(bits, 0, crc=0x8005)
    br.get(1)                                   # last preamble bit
    h = {'type': br.get(2)}
    if h['type'] == 2:                          # ROM 0x6606, continuation card
        h['sections'] = [parse_section(br)]
        if br.get(2) != 0:                      # ROM 0x661A terminator
            raise Over()
    elif h['type'] == 1:                        # ROM 0x663D, full card
        h.update(parse_header(br))
        h['track1'] = parse_track(br, h['alphabet'])
        h['track2'] = parse_track(br, h['alphabet'])
        h['sections'] = []
        while True:
            tag = br.get(2)                     # ROM 0x6656
            if tag == 0:
                break
            if tag != 2:
                raise Over()
            h['sections'].append(parse_section(br))
    else:
        raise Over()
    br.get(16)                                  # stored CRC-16
    h['crc_ok'] = (br.crc == 0)
    h['endbit'] = br.p
    return h


# ---------------------------------------------------------------- presentation

def fmt_track(tr):
    parts = []
    for x in tr:
        if x == 0xE1:            parts.append('|end/loop|')
        elif 0xF0 <= x <= 0xF6:  parts.append('|loop%d|' % ((x - 0xF0) // 2))
        else:
            d = x & 0x7F
            parts.append(('r' if x & 0x80 else '') + DURNAME.get(d, str(d)))
    return ' '.join(parts)


def dump(path):
    data = check_card(path)
    h = parse_card(tobits(data))
    print('=' * 72)
    print(os.path.basename(path))
    print('=' * 72)
    print('  bytes %d   block type %d   CRC-16 %s' %
          (len(data), h['type'], 'VALID' if h['crc_ok'] else 'FAILED'))
    if h['type'] == 1:
        print('  tempo      %d bpm' % h['tempo'])
        print('  rhythm     %d (%s)' % (h['rhythm'], RHYTHM[h['rhythm']]))
        raw = h['transpose'] if h['transpose'] >= 0 else h['transpose'] + 16
        print('  key        field %-2d -> transpose %+d semitones (a card in C'
              ' sounds in %s)' % (raw, key_shift(raw), key_name(raw)))
        print('  melody     voice %-2d = %s' % (h['field4'], voice(MELODY_VOICE, h['field4'])))
        print('  obbligato  voice %-2d = %s' % (h['field6'], voice(OBBLIGATO_VOICE, h['field6'])))
        print('  accomp     %s pattern' % ('ALTERNATE' if h['f3'] else 'standard'))
        print('  sustain    %s' % ('ON' if h['bit1'] else 'off'))
        print('  alphabet   %s' % ' '.join('%02X' % a for a in h['alphabet']))
        total = sum(x & 0x7F for x in h['track1'] if x < 0xE1)
        print('  track1     %d events, %d ticks (%.1f bars of 4/4, %.1f of 3/4)'
              % (len(h['track1']), total, total / 96, total / 72))
        print()
        print('  -- track 1 (melody durations) --')
        print('  ' + fmt_track(h['track1']))
        print()
        print('  -- track 2 (obbligato durations) --')
        print('  ' + fmt_track(h['track2']))
    for i, (table, streams) in enumerate(h['sections']):
        print()
        print('  -- section %d: chord chart (%d entries) --' % (i, len(table)))
        print('  ' + ' '.join('%s@%d' % (chord(v), p) for v, p in table[:24]))
        for j, st in enumerate(streams):
            kinds = {}
            for k, v in st:
                kinds[k] = kinds.get(k, 0) + 1
            print('  -- section %d stream %d: %d ops %s --' % (i, j, len(st), kinds))
            print('  ' + ' '.join('%s%d' % (k[0], v) for k, v in st[:40]) + ' ...')


def summary():
    rows, bad = [], 0
    for p in corpus():
        try:
            h = parse_card(tobits(open(p, 'rb').read()))
        except Over:
            bad += 1
            continue
        if not h['crc_ok']:
            bad += 1
        if h['type'] == 1:
            raw = h['transpose'] if h['transpose'] >= 0 else h['transpose'] + 16
            rows.append((os.path.basename(p)[9:-4][:44], h['tempo'],
                         RHYTHM[h['rhythm']], key_shift(raw),
                         voice(MELODY_VOICE, h['field4']),
                         voice(OBBLIGATO_VOICE, h['field6'])))
    print('%-44s %5s  %-11s %-4s %-9s %-9s' %
          ('card', 'tempo', 'rhythm', 'key', 'melody', 'obbligato'))
    for r in rows:
        print('%-44s %5d  %-11s %+4d %-9s %-9s' % r)
    print()
    print('%d cards decoded, %d failures' % (len(rows), bad))


def _main():
    args = sys.argv[1:]
    if args and args[0] == '--all':
        summary()
    elif args:
        for a in args:
            dump(a)
    else:
        print(__doc__)


if __name__ == '__main__':
    run(_main)
