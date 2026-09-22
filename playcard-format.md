# The Yamaha Playcard format

Songs on a strip of magnetic tape glued to the bottom of a sheet-music card, read by the Yamaha
CR-01 reader through the UPA-01 MSX cartridge. This document describes the format as it is now
understood; a record of what turned out to be wrong along the way is at the end.

| | |
|---|---|
| **267 / 267** | cards decode, CRC-verified |
| **1.000** | melody and obbligato match the real firmware note for note |
| **264** | cards exported to MIDI, with chords (the 3 side-B files fold into their side A) |
| **264 / 264** | cards survive a MIDI round trip with melody and obbligato note for note |
| **261 / 261** | one-sided cards recompile from MIDI back inside the strip, every one smaller than the original |

Everything here was read out of the cartridge ROM and then checked two ways: against the CRC the
format carries, and against a capture of the genuine firmware playing a card under emulation.

**None of it came from Yamaha's patents.** The format was worked out from the ROM, the card images
and the instruments; the patents were read afterwards, and only to see whether they agreed. Where
this document cites one — and it cites a few — it is confirming a finding, never the source of it.
See "The patents" at the end.

---

## Which machine is being described

Four machines are involved, they do **not** behave identically, and a great deal of what follows is
one machine's reading of the card rather than the card itself. This document names the machine
wherever that distinction matters; where it says only *the card*, the claim is about the format.

| | what it is | what it contributes here |
|---|---|---|
| **PC-100** (1982) | the Yamaha keyboard these cards were written for | nearly every finding that is "known by ear". It has **no fill or drum controls at all**, so anything the arrangement does came off the card and not off a panel |
| **PCS-30** (1984) | a second Playcard-capable keyboard | a **second, independent implementation** — the only way to tell the format apart from one machine's reading of it. Its accompaniment patterns are also the ones this project's arranger uses |
| **UPA-01** (1985) | the *Play Card System* cartridge for MSX, read through the **CR-01** reader, in a **CX5M** with an **SFG-01** or **SFG-05** FM module | nearly all the ROM-level detail, every YM2151 register capture, and every emulator run. It is the machine whose code can be disassembled, stepped and watched |
| **PC-1000** (1983) | a later Yamaha keyboard with a Chord Lesson feature | context for one hypothesis about the chord chart, which the corpus then refused |

**Unqualified, "the cartridge", "the firmware" and "the ROM" mean the UPA-01**, because it is the
one whose code this project can read. Its ROM addresses are quoted throughout for the same reason.
That convenience is also the main hazard in this document.

### The cartridge is a witness, not the format

The UPA-01 is a **1985 port of a 1982 product, and not a faithful one**. Three of its behaviours
were written up here as facts about the format and later shown to be its own bugs:

* it **drops chord notes** where the other machines do not;
* it gives each drum fill a **fixed feel** instead of taking the feel from the rhythm, so a straight
  card can come out swung;
* it **falls silent** on a same-root chart entry, a convention it has no way to voice at all.

So a finding that rests on the cartridge alone carries different weight from one that also has the
PCS-30's ROM, the corpus, or a listener behind it, and the sections below say which they have. The
rule that came out of this the hard way: **where the cartridge is the only witness and the claim is
about how something SOUNDS rather than about what the bytes ARE, read it as "this is what the
cartridge does" until a second machine agrees.**

Two sections are wholly about one machine's internals and are marked as such: "How the UPA-01 voices
an accompaniment chord" below, and everything under "A second implementation: the Yamaha PCS-30".

---

## The container

### How the .bin files relate to the card

The extracted files are *almost* a raw card image. Each card block opens with 33 preamble bits and
then a 2-bit block type; whatever produced these files dropped the first 32 of those bits.

That matters because the preamble is fed to the CRC. Solving the CRC algebraically across all 267
files gives one shared starting state, `0x8005` — the value a run of zeros followed by a single `1`
bit produces. The cartridge confirms it directly: before storing card data it writes its own
four-byte preamble, `00 00 00 01`, which is exactly 31 zeros and a one.

The same calculation pins the other end. The CRC is followed by **zero padding to the next byte
boundary**, and then the file's **last three bytes** are a trailer outside the checksummed block —
always `F` · four nibbles · `F`. Nothing in the cartridge's read path touches it. It is a date; see
below.

### Card block layout

```
+-----------+------+--------+-------+-------+-----+-----------+----+------+-----+---------+
| preamble  | type | header | track | track | tag | section   | 00 | CRC  | pad | trailer |
| 33 bits   | 2    | 29+5N  |   1   |   2   | 2   | table + 2 | 2  | 16   | 0-8 | 24 bits |
| (stripped)| bits | bits   | durs  | durs  | bits| streams   |bits| bits |zeros| = date  |
|           |      |        |       |       |     |           |    |      |     |(outside |
|           |      |        |       |       |     |           |    |      |     |  CRC)   |
+-----------+------+--------+-------+-------+-----+-----------+----+------+-----+---------+
```

Block type `1` is a full card. Type `2` is a continuation carrying only a section — the `side-b`
files in the Japanese PC-1000 set are exactly this.

### Two-sided cards

Nothing in the header says "there is a side B". The signal is **structural**: a side-A card is a
type-1 card that carries *no section at all* — header and both duration tracks, then the two-bit
terminator, with no opcode streams. Every other type-1 card in the corpus has exactly one section;
the three side-A cards have zero. The durations are on side A and the pitches on side B.

The cartridge turns that into an explicit state. At ROM `0x6668`, a type-1 card that ends with tag
`0` and no section sets a flag at `0xE48B`; every other successful path clears it. At `0x6608` a
type-2 card is **rejected outright** (error `0x80`) unless that flag is set. So the reader is a
two-state machine: after side A it is armed for side B and will accept nothing else, which is the
state a keyboard's "swipe the other side" indicator reflects.

**The parser says which it just read, in `A`.** Running the cartridge's own parse over a card
image returns a code rather than a yes or no, and the two-sided codes are how a keyboard knows to
ask for the other side:

| `A` | meaning |
|---|---|
| `0x00` | a complete one-sided card |
| `0x01` | a **side A** — a type-1 card with no section; the reader is now armed |
| `0x02` | a **side B**, completing the card and clearing the flag |
| `0x80` | refused |

A side B decodes its section **on top of what its side A left in the buffer**, taking the buffer
pointer from `0xE47B`, so the two swipes are one operation and a side B cannot be read or checked
on its own. `card_limits.py` feeds cards in the order given into one reader for exactly that
reason, and refusing a lone side B is one of its checks.

Joining the two halves gives a complete card, and the one-to-one duration/pitch check passes on all
three pairs — 277, 144 and 273 melody events, 440, 288 and 441 obbligato, gap zero on every half.
`midi_export.py` does the join automatically: given a side-A file it finds the `_side-b` partner,
takes its section, and writes one `.mid` under the name with the side suffix dropped. Handed a
side-B file directly it declines, since that card is covered by its side A.

### Checksum

CRC-16, polynomial `0x8005`, initial value 0, MSB-first, no reflection and no final XOR, folded in
one bit at a time as the stream is read (ROM `0x61CC`). The stored value follows a 2-bit `00`
terminator, and running the CRC over data-plus-checksum yields zero.

### The trailer is a date

The last three bytes are the only part of a card the cartridge never reads, and they were the first
question asked about this format and the last one answered. They are a **date**, stored
least-significant field first:

```
   F    D    T    M    Y    F          as stored, nibble by nibble
        │    │    │    └── year, 2 = 1982 … 5 = 1985
        │    │    └────── month, 1 to 12 (hex 1 to C)
        │    └─────────── day, tens digit
        └──────────────── day, units digit
```

Reverse the six nibbles and it reads `F` · year · month · day · `F` in the ordinary order, so the
whole field is simply a little-endian date framed by two `F` nibbles. `F4152F` is 14 May 1982.

**All 267 cards decode to a real calendar date**, which is 267 independent chances to produce a
32nd of a month or a thirteenth month and take none of them. The dates run from **1982-05-14 to
1985-12-27**, matching a product whose cartridge ROM is dated 1985.

The clinching evidence is one the decoding cannot know about. Sorted by weekday, the 267 cards fall
overwhelmingly on working days:

| Mon | Tue | Wed | Thu | Fri | Sat | Sun |
|---:|---:|---:|---:|---:|---:|---:|
| 23 | 16 | 52 | 51 | **81** | 35 | **9** |

Nine Sundays out of 267, and they are not scattered — they are two particular Sundays, 6 June 1982
and 4 July 1982, on which a run evidently continued through the weekend.

### Which date, though?

**What the evidence supports is "a date", and no more than that.** It is emphatically not a card
identifier and not a set serial: cards sharing a date carry byte-identical trailers even when they
belong to *different sets*. 17-546 (Great Standards 2) and 17-548 (Latin 1) share `F4062F` and
`F6062F` exactly. Barry Manilow and Sing-Along Favorites share 2–3 June 1983. Both German sets carry
12 January 1983.

**Which step of production it records is unknown.** It could be the day the physical card was made,
but equally the day the data destined for the magnetic strip was created, compiled or signed off —
and nothing here distinguishes those. How the card data was authored in the first place is itself
unknown: by hand, or by someone composing in some internal format that a program converted. What
it was not is a performance captured off a PC-100 — that keyboard has no fill controls, and every
card carries per-bar fill marks. Some authoring system existed, and nothing about it is public. The
weekday skew argues only that a *working calendar* is involved, which is true of either. Calling
these "pressing dates" would be a guess dressed as a finding.

With that said, the groupings are real whatever the dates mean. Most sets carry one or two
consecutive days, which is what a six-card batch looks like. The two twelve-card keyboard bundles
divide cleanly:

| bundle | how its twelve cards divide |
|---|---|
| PCS-30 | **six on 1984-07-04, six on 1984-07-06** |
| PC-100 | five on 1982-05-28, five on 05-29, two on 06-01 |

The three Japanese PC-1000 sets are interleaved across 2–5 July 1982, with cards from all three
carrying the same days — one batch covering the whole series rather than one set at a time.

Two sets did not come from one batch. **17-552** (Popular Hits 2) splits 233 days: two cards from 28
June 1982 and four from 16 February 1983. **17-584** has five cards from 13–14 December 1985 and
*Misty* from the 27th.

Seasonal work shows up too: both Christmas sets, 17-557 and 17-561, carry **mid-June 1983**, half a
year before they would sell.

The sixteen bits are entirely accounted for by the date, so there is no room left in the field for a
facility, shift, region or retailer code. Those could only hide in the unused ranges of the year and
day-tens nibbles, and nothing in this corpus suggests they do.

---

## The header

Read MSB-first, immediately after the 2-bit block type. Field widths and lookup tables come from
the ROM routine at `0x6248`.

| Bits | Field | Decoding |
|---:|---|---|
| 5 | **Tempo** | Index into a 32-entry table of metronome marks: 40, 48, 52, 56, 60, 63, 66, 69, 72 … 176, 184, 192, 200 bpm |
| 4 | **Rhythm** | Value `v` → style `v+1`: rhumba, samba, swing, bossa-nova, rock, 16-beat, waltz, slow-rock, march, disco |
| 3 | **Accompaniment pattern** | Only bit 1 is used, yielding 0 or 3. Set = play the **alternate** pattern of the selected rhythm, from the first bar and **locked** there for the whole card |
| 4 | **Melody voice** | Mapped to 0–10, then through the table at ROM `0x5C3F` into the SFG-01's voice bank |
| 1 | **Sustain** | Expanded to 0 or 3 — one bit per part |
| 3 | **Obbligato voice** | Mapped to 1–8, then through the table at ROM `0x5C4B` |
| 4 | **Key** | A YM2151 note code; see below |
| 5 | *N* | Alphabet size, rejected if ≥ 26 |
| 5×*N* | Alphabet | *N* indices into the 32-symbol master table |

**The UPA-01 cannot play five of those 32 tempos.** It hands the card's metronome mark to its own
panel as `floor(bpm / 4) − 10` (ROM `0x4305`, through the table at `0x4363`), an index into the
panel's 41 settings from 40 to 200 bpm in steps of 4 (`0x433A`). A mark that is not a multiple of 4
is rounded down: **63 plays at 60, 66 at 64, 69 at 68, 126 at 124 and 138 at 136.** Measured on the
cartridge, not inferred: Lesson 1a, Somewhere My Love, Ebb Tide and Night and Day come out at 59.9,
67.8, 124.0 and 135.5 bpm. The card carries the exact mark; this machine is the one that loses it.

### The voice tables

Both fields index the SFG-01's 48-voice bank, whose names sit at `0x1B0D` in that ROM in 48-byte
records (7-character name plus FM parameters). The two cartridge tables are adjacent:

| melody (`0x5C3F`) | | | obbligato (`0x5C4B`) | | |
|---:|---|---|---:|---|---|
| 1 | **piccolo** | PICCOLO | 1 | **oboe** | OBOE |
| 2 | **organ** | PORGAN1 | 2 | **flute** | FLUTE |
| 3 | **violin** | STRING2 | 3 | **strings** | STRING1 |
| 4 | **trumpet** | TRUMPET | 4 | **brass** | BRASS 1 |
| 5 | **oboe** | OBOE | 5 | **clarinet** | CLARINE |
| 6 | **clarinet** | CLARINE | 6 | **piano** | EPIANO1 |
| 7 | **harpsichord** | HARPSIC | 7 | **harpsichord** | HARPSIC |
| 8 | **piano** | EPIANO1 | 8 | **guitar** | GUITAR |
| 9 | **vibraphone** | VIBRPHN | | | |
| 10 | **guitar** | GUITAR | | | |

The obbligato table is indexed 1–8 with no zero entry. Every value in both tables was confirmed by
loading a card that uses it and reading the voice name off the cartridge's own screen.

#### Two sets of names, and which one to use

The right-hand column of each pair is what the **SFG-01** shows on screen, and it is where these
were first read: eight characters, upper case, with a bank digit. The bold column is what the
**PC-100** prints on its own control panel — five instrument buttons and an A/B selector, and in
that order the ten melody voices read

> organ, trumpet, clarinet, piano, guitar — then piccolo, violin, oboe, harpsichord, vibraphone

**The panel names are the ones to use.** The PC-100 is a 1982 machine and the cartridge a 1985 one;
these cards were written for the keyboard, so its vocabulary is both older and the one a player
actually saw. Six of the ten differ, and two of those matter musically rather than cosmetically:
`STRING2` is a **violin**, not a string section, and `EPIANO1` is simply the **piano**.

The obbligato voices have no panel names, because that part is not user-selectable — it exists to
play cards. They follow the same convention: expand the abbreviation, drop the capitals, drop the
bank digit. That makes `STRING1` **strings** (the section, as against the melody's violin) and
`BRASS 1` **brass**.

**Both vocabularies are accepted everywhere a voice can be named** — on the command line, and in the
`Playcard:` line a decompiled MIDI carries. `--melody-voice clarinet` and `--melody-voice CLARINE`
select the same voice, and matching ignores case, spaces and punctuation. Only the panel names are
written out.

### The sustain bit

The 1-bit field is **sustain** — the same setting as the keyboard's own sustain button, and the
`Sustain:` field the cartridge shows on screen. Loading Swan Lake and reading the panel gives
`Sustain:on`; a card with the bit clear gives `Sustain:off`.

The routine at ROM `0x5CB5` unpacks the field one bit at a time into `0xD2FC` and `0xD321`, which
sit immediately after the melody and obbligato *voice* bytes — so the hardware wants **one sustain
bit per part**, and that is why the ROM turns the card's single bit into the value 3 rather than 1.

Twelve cards use it: Swan Lake, Rocky Mountain High, I Won't Last a Day Without You, PC-1000 Japan
2-00, 3-03, 3-06, 3-08 and 3-09, and the PCS-30 pressings of Aloha Oe, Memory, Nocturne and We're
All Alone. Aloha Oe has sustain on its PCS-30 pressing but not its PC-100 one — the same song
arranged twice, which is what a performance setting should look like.

### The accompaniment-pattern bit

The 3-bit field selects the **alternate accompaniment pattern** for whichever rhythm the card
chose, in force from the first bar. It reaches the firmware as `0xD352`, in the same live parameter
group as the rhythm bytes, with bit 7 used as a dirty flag.

This was settled by a controlled experiment rather than by inference. Flipping that one bit in a
real card and repairing the CRC gives an image whose header, tracks and opcode streams are
otherwise byte-identical; capturing the YM2151 while the **UPA-01** plays both then isolates exactly
what the bit does. The note counts below are that cartridge's output — what is being established
is that the bit selects a different pattern, not what any particular machine's pattern sounds like.
On Take the A Train, clearing it:

| channels | bit set | bit clear |
|---|---:|---:|
| melody (3 chans) | 9 / 9 / 44 notes | 9 / 9 / 44 — identical pitches, ≤12 ms jitter |
| **chord and bass** | **50 / 50 / 50** | **25 / 25 / 25** |
| drums (2 chans) | 132 / 158 | 132 / 158 — identical |

Setting it on a card that lacks it does the reverse: When the Saints goes from 24/24/29 to
53/53/53 on the same three channels, again with melody and drums untouched.

The alternate pattern comps twice as often — chord onsets every 0.885 s against 1.77 s — and the
plain pattern's onsets fall on exactly every *other* onset of the alternate one. It is also a
genuinely different pattern rather than the same one doubled: the pitch range widens (on When the
Saints, 38–55 to 38–60). The difference is present from the first chord and persists for the whole
capture; nothing switches back.

### The header bit is a lock

The bit does not merely *start* on the alternate pattern — it **holds** it there, and nothing on the
card can move it. `0xD352` is the live pattern state and only three places write it:

| ROM | what it does |
|---|---|
| `0x5CB2` | the header applies its field, `OR 0x80` — and the field expands to **3**, so bits 0 *and* 1 |
| `0x5F6F` | bar mark 7 does `OR 0xC1`, setting bit **0** |
| `0x6013` | the once-per-bar revert clears bit **0** again |

The revert is the whole story, because it is guarded:

```
6005  LD   A,(0xD352)
6008  RRCA            ; bit 0 -> carry
6009  RET  NC         ; bit 0 clear: nothing to revert
600A  RRCA            ; bit 1 -> carry
600B  RET  C          ; bit 1 SET: do not revert
600C  RLCA / RLCA     ; restore A
600F  OR   080h       ; mark dirty
6011  AND  0FEh       ; clear bit 0
6013  LD   (0xD352),A
```

Bit 0 is the one-bar alternate that mark 7 sets; bit 1 is the header's. **The revert returns early
when bit 1 is set**, so on a header-bit card bit 0 can never be cleared. Setting the header field
therefore does two things at once: it turns the alternate pattern on, and it disables the mechanism
that would ever turn it off.

No original card tests this, because none of the five header-bit cards contains a single mark 7. So
a card was written that does both — the header field set to 2, and mark 7 at bars 5, 7 and 9 — with
a byte-identical control differing only in that field and its CRC. Heard on the real firmware:

> the alternate pattern held for the entire duration … the accompaniment never switched back to the
> default pattern no matter what you did

which is what the ROM says must happen. The pattern-state writes confirm it directly: on the
header-set card every mark 7 stores `C3` and the revert at `0x6013` **never once fires**, while on
the control card each mark 7 stores `C1` and is followed exactly one bar later by `C0`.

The two mechanisms are therefore not symmetrical. Mark 7 borrows the alternate pattern for a bar;
the header bit takes it and keeps it.

Five cards set it: Cradle Song, Rocky Mountain High, All Shook Up, and Take the A Train on **both**
the PC-100 and PCS-30 pressings — the same song on two independent albums carrying the same value.

### The key field is a transposition

The field is **numerically a YM2151 note code** — which is why the chip's four unused values, 3, 7,
11 and 15, never appear in it, the same signature that identifies the pitch opcodes. What it carries
is a **transposition in semitones**: that code's position in the chromatic order, taken in the octave
nearest zero.

It does **not** name the key. The chip's note numbering begins at C♯, so code 0 sits at position 0
and transposes by nothing. Reading the field as a key name puts every value a semitone high, and
would have 158 of the 267 cards published in C♯.

It does not name the key at one remove either. The field is the *distance* the melody moves, and
**nothing on the card records where it started** — a card is written in whatever key was cheapest
to store, which is usually but not always C. So no key name can be read off this field alone, and
the tools print the only honest form, a conditional one:

```
  key        field 6  -> transpose +5 semitones (a card in C sounds in F)
```

Read that as arithmetic, not as a fact about the card in front of you. The PC-100 *9 to 5* has
field 6 and sounds in **C**, because it is written in G. See "The cards are not all written in C".

| field | shift | a card in C sounds in | | field | shift | a card in C sounds in |
|---:|---:|---|---|---:|---:|---|
| 0 | 0 | **C** | | 8 | −6 | F♯ |
| 1 | +1 | C♯ | | 9 | −5 | **G** |
| 2 | +2 | **D** | | 10 | −4 | G♯ |
| 4 | +3 | D♯ | | 12 | −3 | **A** |
| 5 | +4 | E | | 13 | −2 | **A♯** |
| 6 | +5 | **F** | | 14 | −1 | B |

The chord chart settles it, because chords are stored at **sounding pitch** and are not touched by
this field — so they are an independent witness to what key a card is actually in. Grouping every
card by its field value and counting the chord roots its chart uses:

| field | shift | cards | commonest chord roots |
|---:|---:|---:|---|
| 0 | 0 | 156 | **C** 32%, G 21%, F 14% — I, V, IV of C |
| 6 | +5 | 49 | **F** 32%, C 19%, B♭ 14% — I, V, IV of F |
| 9 | −5 | 45 | **G** 27%, D 20%, C 14% — I, V, IV of G |
| 2 | +2 | 1 | **D** 38%, A 31%, G 26% |
| 12 | −3 | 1 | **A** 41%, F 18%, D 18% |

Every one is C plus the shift, and never the note code's name. Read the table as *tendency*: it is
the average of a group, and it is what makes the shift itself unambiguous — but no row of it fixes
the key of any single card.

Seven values appear across the corpus: 0 (156 cards), 6 (49), 9 (45), 4 (5), 13 (4), 2 and 12 (1
each). The field transposes rather than declares, though: field-0 cards are mostly in C but 32 are
in G and 26 in A, so a card's key is a property of the music, not of this byte. What the field says
is only how far to move it.

---

## The duration tracks

Two tracks, melody and obbligato, entropy-coded. Each song ships its own alphabet — up to 25
symbols drawn from a fixed master table of 32 — ordered most-frequent-first.

**Nothing on a card is timestamped.** A track is a gapless run of lengths, so where a note falls is
the sum of everything before it and nothing else. There is no way to place an event a fraction of a
tick late, and no way to leave a hole that is not a rest of one of the ten available lengths.

That is a stronger constraint than it looks, because **the chord chart and the bar marks are
addressed by position in the obbligato's opcode stream** rather than by time — see "A chart entry
fires once, at the obbligato's position" below. A chord is not "at 41.5 seconds"; it is "at the
obbligato's 17th opcode", and it sounds whenever that opcode is reached. So the two are welded
together: move an obbligato event and every chord and mark hanging off it moves with it, by however
long that event lasts. It is why `midi_compile.py` reports a chord that had to move separately from
a note that had to move, and why the first rule of authoring a card is to quantise the music before
compiling it. A rounding of half a tick in the wrong place puts a chord change most of a bar away.

Codewords are an alternating-run prefix code: *k*+1 copies of a bit, then one opposite bit. The
value is `2k + (1−b₀)`, so the two commonest symbols cost 2 bits each, the next two cost 3, and so
on. Cheap to decode on a Z80 and self-synchronising.

```
value  codeword          cost
  0      10              2 bits
  1      01              2 bits
  2      110             3 bits
  3      001             3 bits
  4      1110            4 bits
  …
 24      1111111111111 0   14 bits
 25      0000000000000 1   14 bits
```

### The master symbol table

**24 ticks = one quarter note.**

| Ticks | Note | With lift bit |
|---:|---|---:|
| 6 | sixteenth | 0x86 |
| 8 | eighth triplet | 0x88 |
| 12 | eighth | 0x8C |
| 16 | quarter triplet | 0x90 |
| 18 | dotted eighth | 0x92 |
| 24 | quarter | 0x98 |
| 36 | dotted quarter | 0xA4 |
| 48 | half | 0xB0 |
| 72 | dotted half | 0xC8 |
| 96 | whole | 0xE0 |

Plus six control symbols: `0xFF` repeats the previous symbol, `0xE1` ends a track or closes a
repeat span, and `0xF0 0xF2 0xF4 0xF6` open one of four repeat spans.

The last six entries of the 32-symbol master table — `0x22 0x7D 0xE4 0x21 0xAE 0xE3` — are neither
durations nor controls, and no card uses them.

**Everything usable does not fit in one alphabet.** Ten lengths in a plain and a lift form is 20
symbols; with `0xFF`, `0xE1` and the four span markers that is **26**, against a size field that
rejects 26. A card that wanted all of it would be one symbol over, so something always gives. No
original comes close — the corpus runs from 8 to 23 symbols — but anything generating cards has to
choose rather than assume.

### Bit 7 is a LIFT flag, not a rest

Each duration exists in two forms, plain and with bit 7 set. The bit means **the finger comes off
at the end of this event**, so a following event on the same pitch is struck again rather than held
on. A run of equal pitches ties into one note only while the *preceding* event left the finger
down.

This is the single most error-prone detail in the format; see the superseded notes.

### The lift bit decides tie against re-strike — but do not treat it as free elsewhere

Bit 7 decides one thing when *reading* a card: whether an event that repeats the previous pitch ties
to it or strikes again. Nothing else in the decode depends on it, so it looks free everywhere else,
and spending that freedom saves bytes — every distinct symbol costs 5 bits in the header and pushes
every other codeword down a rank, so letting free events take whichever form of their length is
already in the alphabet can save a symbol outright.

**Do not.** The flag means what it says, and the playback path acts on it whether or not anything
repeats the pitch — so a card generated that way plays audibly *staccato*.

Measured on the **UPA-01**, with two cards that differ in nothing else: 28 notes, no pitch repeated
anywhere, same lengths, same header, same chart, same three-symbol alphabet, 47 bytes each. Every
melody duration plain in one and `| 0x80` in the other. Capturing the YM2151's key on/off register:

| | key down, as a fraction of the note's slot |
|---|---:|
| bit 7 clear | **99.6%** — held right up to the next note |
| bit 7 set | **83.2%** |

The accompaniment is untouched: chord and bass key-ons match to the millisecond across the two
captures, so the melody duration alone did it. `new-cards/make_lift_test.py` builds the pair, and
`--wav` renders the swipe audio to put the same question to a real keyboard — worth doing, since
the gap below is a number one machine chose.

**The release is 4 ticks early, or a sixth of the event, whichever is less.** A third card carrying
lifted events at four lengths measures the gap as 4.02, 4.03 and 3.96 ticks at 24, 48 and 96 — and
2.12 at 12, where four ticks would be a third of the note. So a lifted quarter sounds for 20 of its
24 ticks and a lifted eighth for 10 of its 12.

Yamaha's own cards say the same thing. Across the 264 originals the bit is set on:

| the event is followed by | count | bit 7 set |
|---|---:|---:|
| the same pitch again | 20438 | 57.7% |
| a different pitch, or nothing | 71009 | **2.8%** |
| — (the event is a rest) | 20757 | **0.0%** |

So the plain form is the default and the bit goes on exactly where a tie has to become a re-strike.
That is what makes the PC-100 Summertime alphabet carry two lift symbols of fifteen, where setting
the bit everywhere it was *allowed* gave eight of nineteen on the same music — a bigger card that
also played wrong.

---

## The pitch streams

Two streams pair one-to-one with the two duration tracks: melody with track 1, obbligato with
track 2. They are streams of **4-bit opcodes**, which is why the card data is nibble-aligned.

| Opcode | Meaning |
|---|---|
| 1–7 | A note letter: `1`=A `2`=B `3`=C `4`=D `5`=E `6`=F `7`=G |
| 0 | A rest. It emits YM2151 note code 3, one of the chip's four unused values, so it cannot sound by construction — yet it still occupies a duration slot |
| 8, 9, A | Pitch modifier on the following note (emits `0xE8` with 1, 2, 0) — see below |
| B, C, D | Emits `0xE1` with `0x11`, `0x13`, `0x14`: a passage division, and the obbligato duck off and on — see below |
| E | Return from a repeat span, or end the stream |
| F | Escape: read 4 more bits — under 8 is a **bar-level mark** controlling the drums and the accompaniment pattern (see below), 8 and up opens a repeat span |

The opcodes are the card's; the bytes each one **emits** are the UPA-01's translation of them, and
are quoted because that is where they were read. A different machine reaches the same music by its
own route — the PCS-30 does, from a table in an unrelated ROM.

### The bar-level marks: drums and the alternate pattern

The escape opcode's sub-values were assumed to be eight drum fill patterns. They are a mixed bag,
and **all eight are now identified**: value 0 mutes the drums, values 1 to 6 are fills, and value 7
switches the accompaniment to the alternate pattern for one bar. Values 0 to 3 and 7 came from
original cards whose behaviour is known by ear; 4, 5 and 6 were settled by building cards that
isolate them, and the six fills turn out to split by metre. Each is taken in turn
below.

These are **format-level** readings: what the mark asks the instrument for. The drum patterns and
fills it selects live in the instrument, and differ between machines — so what a mark *means* is
here, and what it *sounds like* is the PC-100's or the PCS-30's or the cartridge's business. Where a
capture is quoted below it is the UPA-01's.

**Value 0 silences the drums**, and it is re-asserted for each bar the drums stay out. On I Write
the Songs it appears at bars 1, 2, 3 and 4 and then stops — and the drums come in at bar 5. It
appears again at bar 19 beat 4.5 and at bars 20 and 21, and the drums return at bar 22. Every one
of those is bar-exact. At 848 occurrences it is the commonest mark, which suits a mute rather than
a fill.

**Values 1, 2 and 3 are drum fills.** I Write the Songs has a value 1 at bar 11 beat 1, where a
fill is heard; Night Fever has a value 2 at bar 4 beat 3, heard as a *partial* fill. A fill pattern
occupies a whole bar, so one triggered mid-bar plays only the part that would remain had it started
on the downbeat.

Mickey Mouse March is the clearest case of all, because it is almost nothing but one fill repeating.
It carries **45 marks of value 3 and only 4 of value 0**, and the value-3 marks sit on beat 1 of
every bar from 2 through 44 — a fill restated once a bar for the whole song, which is exactly what
is heard.

Its ending confirms the mute reading independently. The last fill is at bar 44; bar 45 has none, so
the fill drops out. At bar 45 beat 1⅓ a mark 0 and a chord `0xFF` land **together** — drums and
accompaniment both cut, having sounded once on the downbeat — and bar 46 restates the mark 0 to
hold the drums out. The card is 46 bars, so that is the final two, cut off for the remainder.

**Value 7 is not a fill — it plays the alternate accompaniment pattern for that one bar**, then
reverts.

Two cards whose behaviour is known by ear pin this exactly:

| card | marks of value 7 | heard |
|---|---|---|
| Someday My Prince Will Come | one, at bar 3.00 | alternate at bar 3, back to standard at bar 4 |
| When You Wish Upon a Star | two, at bars 1.00 and 2.00 | starts alternate, standard from bar 3 |

A UPA-01 capture of the first confirms it: bars 1, 2 and 5 play bass-chord-chord, while **bar 3
alone** plays bass-chord-bass-chord — a denser pattern, in the one bar the mark covers. What the
denser pattern *is* belongs to that cartridge; that the mark switches to it for exactly one bar is
the card's.

This is the second route to the alternate pattern, and the two are not interchangeable. The header
bit starts on it and **locks** it there; mark 7 switches for a single bar. **None of the five
header-bit cards contains a single mark 7** — which is exactly what the lock predicts, since on such
a card mark 7 can do nothing at all. The arrangers were not choosing between two equivalent
mechanisms; on those five cards the second one has no effect. See "the header bit is a lock" above,
where a purpose-built card confirms it.

**Values 4, 5 and 6 are further drum fills.** They were long left as "unidentified, and by
elimination probably further fills" because no card in the corpus isolates them. They were settled
in 2026 by writing cards that do nothing else — see `new-cards/`. Sixteen bars of 4/4, C major
throughout, one mark on beat 1 of every odd bar from 3 to 13, with marks 1, 2 and 3 on the same
card as the control:

Each occupies exactly one bar and the plain pattern resumes in the next. None duplicates another:
plain bars agree with each other at 0.94 pattern overlap, while every marked bar sits at most 0.42
against a plain bar and at most 0.51 against any other mark. Two rhythms, rock and march, agree.

So all eight sub-values are now accounted for: 0 mutes the drums, 1–6 are fills, and 7 switches the
accompaniment to the alternate pattern for one bar.

### The six fills split by metre, and only by metre

Sorting every fill in the corpus by its card's rhythm gives a three-way split, and each family uses
its own pair almost exclusively:

| family | rhythms | cards | fills | on that pair |
|---|---|---:|---:|---:|
| straight | rhumba, samba, bossa-nova, rock, 16-beat, march, disco | 156 | 537 | **94.0%** (1 and 2) |
| swing, slow-rock | swing, slow-rock | 68 | 261 | **98.1%** (3 and 4) |
| waltz | waltz | 37 | 67 | **97.0%** (5 and 6) |

Only the last of those three is a restriction. **Fills 5 and 6 are used by 21 of the 37 waltz cards
and by none of the other 224** — not one occurrence outside a waltz, anywhere in the corpus. The
first two rows are an authoring habit and nothing more; see below.

That one is a hard restriction, and the reason is metre. Playing all six on purpose-built cards in
4/4 and in 3/4 shows a fill is a **fixed pattern measured in beats**, identical whatever rhythm
calls it:

| mark | onsets, in beats from the bar line | in 4/4 | in 3/4 |
|---:|---|---|---|
| 5 | 0.09 0.67 2.59 2.67 | leaves beat 4 empty | **fits exactly** |
| 6 | 0.09 1.08 1.26 2.01 … 2.83 | leaves beat 4 empty | **fits exactly** |
| 1, 2 | run past beat 3 to ~3.84 | **fits exactly** | truncated at the bar line |

Marks 5 and 6 are **three-beat** patterns and 1 to 4 are **four-beat** ones. The 5 and 6 onset lists
are identical to within 0.02 beats whether the card is a waltz or a rock number; 1 and 2 are
identical for their first three beats and then simply stop when a 3/4 bar ends. So a 3/4 fill in a
4/4 bar leaves a hole on beat 4, and a 4/4 fill in a waltz is cut off mid-phrase — which is why no
arranger used either the wrong way round.

### Fill feel comes from the RHYTHM, and the UPA-01 gets it wrong

Three machines, and the cartridge is the odd one out.

**The PC-100 takes the feel from the rhythm.** The decisive case is *I Could Have Danced All
Night*, from its own set: a **disco** card — a straight rhythm — carrying **mark 3** at bar 4.00, in the obbligato
intro just before the melody enters at bar 4.62. On a PC-100 that fill sounds straight, as the tune
needs. Played through the UPA-01 it comes out swung and wrong. The same card also uses **fill 2** at
bar 12.25, so one straight-rhythm arrangement mixes fills from both supposed "families" without a
qualm.

**The PCS-30 does the same thing, and its ROM shows how.** The fill lookup is bank 1 with the fill
NUMBER as the bit index — no rhythm enters it — and what swings a rhythm is the grid: a bar is 16
steps straight and 12 swung. The same table data lands on sixteenths under rock and on triplets
under swing, for all four fills equally.

**The UPA-01 gives each fill a fixed feel instead**, whatever rhythm is selected: 1 and 2 straight,
3 and 4 swung. Heard on a march fill-test card and on the same card switched to swing, and matched
by a capture — the fill bars come out near enough identical between
`new-cards/playcard_new-15_fill-feel_rock.bin` and `..._16_..._swing.bin`, which differ in that one
field. **It is a bug**, and it belongs with the chord dropout in the list of things this 1985 port
gets wrong.

So "fills 1 and 2 are straight, 3 and 4 are swing" was never a property of the format or of the
fills. It is a fair description of nothing but the cartridge's mistake.

#### The corpus preference is real, and is now unexplained

| | cards | fills 1+2 | fills 3+4 | fills 5+6 |
|---|---:|---:|---:|---:|
| straight rhythms | 156 | **93.7%** | 6.3% | 0.0% |
| swing, slow-rock | 68 | **1.7%** | **98.3%** | 0.0% |
| waltz | 37 | 2.3% | 0.0% | **97.7%** |

**Fill 2 is used by 90 of the 156 straight cards and by none of the 68 swing cards.** Fill 1 by 106
straight cards and 3 swing ones. That is a real and very lopsided authoring habit, and the obvious
explanation — that choosing the fill was choosing the feel — is exactly what *I Could Have Danced
All Night* rules out.

**The PC-100 has no fill controls.** Nothing on that keyboard inserts a fill, so there a fill can
only come from the card. Whatever wrote these cards was therefore not somebody playing a PC-100 and
pressing things as the tune went by; it was an authoring system, and nothing about it is publicly
known — not its name, not its interface, not whether the fill was chosen by number or by ear.

That removes the one explanation that would have accounted for the sharpness of the split: a panel
whose "fill 1 / fill 2" buttons emitted different mark values depending on the rhythm selected. What
is left is the weaker guess that the fills are simply patterns whose character suits one feel better
than the other once swung — and otherwise the habit belongs to that unknown system, or to whoever
sat at it. Neither ROM speaks to it.

The metre split is untouched by any of this: 1 to 4 are four-beat patterns and 5 and 6 three-beat
ones, and **5 and 6 appear on 21 of 37 waltz cards and on none of the other 224**.

### The accompaniment mute is a chord, not a control opcode

Muting the accompaniment is **not** done with a control opcode. The chord chart carries the value
`0xFF`, which is not a chord but an instruction to stop sounding one; the next real chord starts it
again. There are 825 such entries across the corpus — 988 occurrences once repeats are expanded —
and every one of the 261 cards has at least one.

Two passages pin it exactly. On I Write the Songs, bar 11 beat 1.75 carries a mark 0 *and* a chord
`0xFF` together — the drums and the accompaniment both stop, which is what is heard, and both
resume at bar 12. Contrast bar 19 beat 4.5, which carries the mark 0 alone: there the drums drop
out and the accompaniment keeps playing. On Night Fever, bar 8 beat 1 is a real chord and beat 1.25
is `0xFF` — the accompaniment sounds just long enough for one chord and then stops, with the drums
continuing, and returns at bar 9.

That the two mutes are carried by different mechanisms — drums by a bar mark, accompaniment by a
chord-chart sentinel — is why they can be used independently. Both mechanisms are the card's, and
both are honoured by every machine here; `new-cards/playcard_new-11_mute-hold-test.bin` puts the
question to real hardware rather than to an emulator.

### The control opcodes duck the obbligato under the melody

The melody stream contains **no control opcodes at all** — not one, on any card. Every `0x11`,
`0x13` and `0x14` in the corpus is in stream 1, which is exactly right for what they turn out to
do: they are about the obbligato's own level.

| opcode | as stored | after repeats | meaning |
|---|---:|---:|---|
| `0x11` | 1978 | 3082 | bump a counter — the passage divisions for repeat practice; see below |
| `0x14` | 312 | 484 | **duck the obbligato**: the melody is entering |
| `0x13` | 251 | 295 | **restore the obbligato**: the melody has finished |

The cartridge's firmware settles it outright. All three are decoded by one chain at ROM `0x5F8B`
- so what follows is how the UPA-01 implements the ducking, and the corpus evidence in the two
sections after it is what makes the reading a fact about the card:

```
5F8B  FE 11      CP   0x11
      3A 60 D3   LD   A,(0xD360)     ; a counter, sent out by the parameter pump
      3C         INC  A
      32 60 D3   LD   (0xD360),A

5F99  FE 13      CP   0x13
      3E 80      LD   A,0x80
      32 56 D3   LD   (0xD356),A     ; a one-bit flag -> 0
      3E 80      LD   A,0x80
      32 24 D3   LD   (0xD324),A     ; obbligato level -> 0x80, full
      32 49 D3   LD   (0xD349),A     ; third part    -> 0x80, full

5FAD  FE 14      CP   0x14
      3E 81      LD   A,0x81
      32 56 D3   LD   (0xD356),A     ; the same flag -> 1
      3E 60      LD   A,0x60
      32 24 D3   LD   (0xD324),A     ; obbligato level -> 0x60, reduced
      32 49 D3   LD   (0xD349),A     ; third part    -> 0x60, reduced
```

`0xD2FF`, `0xD324` and `0xD349` are the same field in three per-part parameter blocks of stride
`0x25`, and the initialisation at `0x5D54` writes `0x80` to all three — so `0x80` is the default and
`0x60` is a reduction. The blocks are the ones whose `+0x20` byte carries the melody and obbligato
**sustain** (`0xD2FC` and `0xD321`), which identifies them: block 0 is the melody, block 1 the
obbligato. `0x14` and `0x13` never touch block 0. **The melody is not ducked; the obbligato is.**

### Confirmed against the chip

Capturing every YM2151 write while the firmware plays the PC-100 Edelweiss shows the level arriving
at the chip as Total Level on the obbligato's channel — register `0x7A`, the final carrier, the
operator that sets output volume:

| bar | opcode | reg `0x7A` |
|---:|---|---:|
| 5 | `0x13` | 34 — full |
| **9** | `0x14` | **36 — ducked** |
| **41** | `0x13` | **34 — restored** |
| **45** | `0x14` | **36 — ducked** |
| **77** | `0x13` | **34 — restored** |

Every transition lands within 45 ms of its opcode. The melody's two channels enter at 34 and never
move, and the accompaniment's channels are untouched throughout. The other three operators on the
obbligato's channel wobble by ±1 note to note; the carrier alone steps and holds, which is what a
level change looks like and a voice reload does not.

Those five bars are exactly the ones a player who knows the card predicted in advance, from the
sound of the real instrument, before any of this was measured.

### How deep the duck is depends on the machine

Two steps of Total Level is 1.5 dB, which is hard to hear, and on some cards the UPA-01 does not
duck at all. **On the UPA-01 the duck is a velocity, not a volume.** The only reader of `0xD324`
is `0x5E2F`, which sends it with each obbligato note to the SFG-01, and what a softer note does is
up to the voice. Love Theme re-headed to each obbligato voice in turn, at five panel volumes:

| obbligato voice | the duck on the UPA-01 |
|---|---|
| flute, piano, guitar | 2 TL steps, 1.5 dB |
| oboe, strings, brass, clarinet | 1 step, 0.75 dB |
| **harpsichord** | **none**, at any volume |

Love Theme itself has a harpsichord obbligato, and on this cartridge it does not drop back at all
when the guitar melody enters.

**The PCS-30 ducks by 6 dB, whatever the voice.** Its handler for the duck nibble sets bit 0 of
`0x80D7` (`0x2ACA`; the restore clears it at `0x2ABD`), `0x1E48` copies the flag into `0x80D1`,
and at every obbligato note `0x0F77` adds `0x10` to the level byte it sends to its sound chip,
register `0x8C` plus the channel. That chip is the YM2142, which is undocumented, but the PCS-30
drives it exactly as the **YM2163** is documented to be driven, and that datasheet survives:

| YM2163 registers | contents |
|---|---|
| `80H`–`87H` | pitch, octave and key-on, a register a channel |
| `88H`–`8BH` | envelope E2 E1, sustain, waveform W3–W1 |
| **`8CH`–`8FH`** | **volume VL2 VL1**: `00` 0 dB, `01` −6 dB, `10` −12 dB, `11` off; then F4–F1, which of four output pins the channel goes to |
| `90H`–`97H` | rhythm triggers and level |

The PCS-30 reaches its chip through one port, `0xE030` - a byte with bit 7 set is a register
address, and the next byte's low seven bits are its data, exactly as the datasheet describes - and
writes `0x84`, `0x88`, `0x8C` and `0x90`. It never writes a pitch divider to `0x80`: at `0x0D5D` it
turns a note into **octave × 16 + semitone**, sets `0x40` for key-on, and writes that to `0x84`. So
the YM2142 has a note table of its own where the YM2163 takes a raw divider - the one place the two
chips are known to differ - and its tuning cannot be read from anything here.

Every entry of the voice table at `0x2CFC` decodes cleanly as an (`88H`, `8CH`) pair, and the
tables at `0x1BA3` and `0x1BAD` say which card voice uses which entry:

| entry | card melody voice | card obbligato voice | waveform | envelope | level | output |
|---:|---|---|---|---:|---|---|
| 0 | organ | | Pf | 3 | 0 dB | OR3 |
| 1 | clarinet | clarinet | Cl | 1 | −6 dB | OR1 + OR2 |
| 2 | piano | piano | Pf | 0 | 0 dB | OR3 |
| 3 | guitar | guitar | St | 0 | 0 dB | OR2 + OR3 |
| 4 | harpsichord | harpsichord | Hc | 0 | 0 dB | OR4 |
| 6 | vibraphone | | Cl | 0, sustain on | 0 dB | OR3 |
| 7 | piccolo | flute | Cl | 1 | 0 dB | OR3 |
| 8 | oboe | oboe | St | 1 | −6 dB | OR4 |
| 9 | trumpet | brass | St | 1 | 0 dB | OR2 |
| 10 | violin | strings | St | 1 | 0 dB | OR1 |

The waveforms are the datasheet's five - St a stepped sawtooth, Cl a square, Pf, Or and Hc
narrower stepped pulses - and envelope 0 is the one that decays, 1 to 3 the three that hold.
Bit 3 of `88H`, blank on the YM2163, is set only for the vibraphone, the flute and the violin,
which suggests a vibrato; that is a guess. Oboe and trumpet share waveform and envelope and differ
only in their output pin, so much of what tells the voices apart is in the analogue filters on the
keyboard's board, which no document found describes.

Bit 4 of `8CH` is VL1, so **`0x10` is one volume step, exactly 6 dB**. The clarinet and the oboe
start at −6 dB and so duck to −12, and the flute - entry 7, which `0x0F86` singles out - always
plays a step down, duck or not.

So the card's two opcodes are the same on both machines, and what they do is not: a clear 6 dB on
the keyboard, and from nothing to 1.5 dB on the cartridge. `csrc/playcard` ducks the PCS-30's way
by default; see "The obbligato duck" in `csrc/README.md`.

### The same thing across the corpus

State the claim so it can be counted: `0x14` should fire where the melody is about to sound and was
not sounding before, and `0x13` where the melody gives up the tune. Measuring the fraction of the
two bars either side of each opcode that the melody actually sounds:

| opcode | n | melody sounding, 2 bars before | 2 bars after |
|---|---:|---:|---:|
| `0x11` | 3082 | 68.5% | 81.4% |
| `0x13` | 295 | 73.0% | **26.9%** |
| `0x14` | 484 | **22.7%** | **92.3%** |

**All 484** of the `0x14`s have the melody sounding in the two bars after them — a perfect record,
with no card excepted. At 70.5% of the `0x13`s the melody recedes. `0x11` is flat either way, as a
counter should be, and its spacing piles up on 4 bars (39.6% exactly, most of the rest within a
half bar of it) — a phrase or line mark rather than anything to do with the parts.

`0x11` being on **every** card ruled out the earlier reading of it as the alternate-pattern
selector; that is the header bit above. None of the three is a mute either — those are the mark 0
and the chord `0xFF`.

### They are assertions, not brackets

The obvious next guess — that `0x14` and `0x13` open and close a section, strictly alternating — is
**wrong**, and the corpus says so plainly: only 69.8% of cards alternate, and runs like `14 14 14`
are common. Both handlers are idempotent, and the format already has this idiom elsewhere: bar-mark
0 is re-asserted for every bar the drums stay out rather than toggling once.

`0x14` is asserted at **each melody entry**, including every re-entry after a rest. Measuring melody
*onsets* per bar — not sounding time, which a final held note disguises — over the two bars either
side:

| | onsets/bar before | onsets/bar after | direction |
|---|---:|---:|---|
| `0x14` | 0.80 | **4.59** | density falls at only 2.5% |
| `0x13` | 3.71 | **0.48** | density falls at **90.6%** |

And **96.2%** of the 478 `0x14`s are immediately preceded by a rest in the melody, 72% by a rest of
a bar or more. So `0x14` means *the melody starts here* and `0x13` means *the melody has run out of
material* — which is why `0x13` so often lands on the bar where the tune arrives at its last held
note and the obbligato takes over.

### 0x11 divides the card into practice passages

The counter at `0xD360` is bumped and queued outward, and the only code that reads it back is the
routine that sends it (`0x6068`, 1648 times on one card) — the
same shape as the flag at `0xD356`, and the same conclusion: its consumer is the keyboard. What the
keyboard does with it is a **repeat-practice feature**. Press the button, then one key to loop a
single passage or two keys to loop a range of them; on the PC-100 the selecting keys are the white
keys from F2 upward. `0x11` is what says where one passage ends and the next begins.

The corpus fits that reading closely, and in a way a bar counter does not:

| | |
|---:|---|
| **84.3%** | of the 3109 marks land **exactly on a melody note onset** |
| 41.3% | land on a bar line |
| **1 of 3109** | falls part-way through a melody note |
| 4 to 20 | marks per card, median 11, and **not one card has more than 20** |

The middle two lines carry the argument. A passage boundary *cannot* sit in the middle of a note —
there would be no way to start playing there — and the corpus obeys that to one event in 3109,
which is the kind of number that stops being a tendency and starts being a rule. Meanwhile only two
in five sit on a bar line, so whatever places them is following the tune and not the metre. And the
count per card is **bounded**: a phrase counter would grow with the length of the song, while a set
of passages a player selects by key is limited by how many keys there are to select with.

**I Could Have Danced All Night** (PC-100) shows the whole thing in eight bars. The obbligato opens
alone; the tune enters on a C4 pickup at bar 4.62, three and a half beats before the bar line:

```
tick     0  bar 1.00   0x11                      the obbligato lead-in: passage 1
tick   348  bar 4.62   0x11 + 0x14 (duck)        the melody enters: passage 2
tick   744  bar 8.75   0x11                      passage 3
```

The mark is at 348, not at 384 where the bar begins. A four-bar grid would put every one of them in
the wrong place on a card like this, and cards like this are ordinary — a tune that starts on an
upbeat is the normal case, not the exception.

This is attested by the instrument and strongly supported by the corpus, but it is **not provable
from this ROM**, because the cartridge only writes the counter and sends it on. It has the same
standing as the free-tempo reading of `0xD356`, and for the same reason.

`midi_compile.py` places these automatically when a MIDI file carries none, by walking a four-bar
grid and landing each mark on a melody onset within three beats, preferring one that begins a
phrase. That reproduces 1736 of the 3109 corpus marks exactly, against 862 for a plain bar grid, and
leaves none part-way through a note. It gets all of them on 36 cards — including all 18 of I
Could Have Danced All Night's. Where a teacher divides a song into passages is a musical judgement,
so half the corpus is about as far as a rule can reasonably go.

### Why a held flag: free tempo

The one-bit flag at `0xD356` — set by `0x14`, cleared by `0x13` — is read by exactly one
thing: the outgoing-parameter scan at `0x60CE`, which tests its top bit, clears it and hands the
value out. That top bit is a *dirty* mark, not data — both written values, `0x80` and `0x81`, have
it set — so the read is the message leaving, not the cartridge consulting it. Nothing in this ROM
acts on the flag itself. What it is for is nonetheless clear from its shape and from how
these instruments behave.

Some of these keyboards offer **free tempo**: playback holds until the player plays the correct
note, and then follows them, speeding up or slowing down to match how fast they are actually
playing, so a beginner settles into a slower tempo that gives them time to find each note. At the
end of a melody section the tempo returns to default — the card's metronome mark on instruments
that read it, the slider position on those that do not — whatever free tempo had drifted it to.

That is what wants a **held state** rather than an edge. A reset-now instruction needs no second
value; a follower that waits for the correct note needs to know continuously *whether there is a
note to wait for*. `0x14` says there is one coming, restated at every phrase entry so the follower
re-arms; `0x13` says the melody is done, so the follower stands down and the tempo goes back to the
card's. Measured against the corpus that is exactly where the two land.

So one pair of opcodes marks the melody section once and the instrument uses it twice: duck the
obbligato so the part being learned sits on top, and gate the tempo follower. This reading is
attested by playing the real hardware and fits the structure and the corpus; it is not provable from
this ROM, because the consumer is downstream of it.

**The UPA-01 plays without any FM hardware at all.** It was sold for MSX machines that had none: its
`INIT` hunts for the signature `"MCHFM0"`, and finding nothing it drives the machine's own PSG
instead. Running the cartridge with the FM slot left empty (`csrc/playcard --no-fm`) makes it do
exactly that, and what comes out is **three voices**:

| PSG channel | Summertime | Edelweiss | range | what it is |
|---|---:|---:|---|---|
| A | 114 notes | 68 | C4-G5 | the **melody** |
| B | 93 | 139 | C4-A5 | the **obbligato** |
| C | 189 | 53 | D2-G3 | a **bass** line |

The note counts settle it: Summertime's card carries 114 melody notes and 93 obbligato notes, and
channel A opens Edelweiss `E4 G4 D5 C5 G4 F4 E4 E4`, which is that tune's documented opening.

So there are three PARTS in this machine, not two, and there are three parameter blocks. Block 0 is
the melody, block 1 the obbligato — and block 2 lines up with the **bass**, which exists as a part
only when the PSG is doing the accompaniment. The duck writing to blocks 1 and 2 then reads as *duck
the obbligato and the bass under the melody*, which is musically what one would want, and on the FM
side only the obbligato answers because there the bass comes from the accompaniment generator rather
than from a part block.

**That is a hypothesis, not a result.** What is measured is the other half of it: on the PSG path
**nothing is ducked at all**. Across 108 seconds of Summertime the three volume registers are written
three times each, all of them during boot, twelve seconds before the first note. Whatever consumes
block 2's level, it is not the PSG's volume.

### F5 starts free tempo, and the cartridge holds the sequencer itself

`F2` starts a card at its own tempo. **`F5` starts the same card in free tempo**, and the difference
is visible without a keyboard attached: the card plays its introduction — accompaniment and
obbligato — and then stops dead at the first melody note, waiting for a player who is not there.
`csrc/playcard --f5` does it:

| | key-ons | stops after |
|---|---:|---:|
| Edelweiss, `F2` | 1375 | 138.0 s, the end of the card |
| Edelweiss, `F5` | **119** | **14.2 s** |

And it stops in exactly the right place. Under `F2` the `0x14` opcode — *melody starts here* —
fires at 30.997 s of machine time; under `F5` the last key-on is at 30.733 s and the hold begins at
**31.019 s**, twenty-two milliseconds later. Summertime stops at 9.0 s against 90.8, I Could Have
Danced All Night at 8.5 against 149.5, When the Saints at 5.0 against 49.0.

**The waiting is done here, not on the keyboard.** Three bytes and one comparison:

| | |
|---|---|
| `0xD222` | the play mode: **1** started with `F2`, **3** started with `F5`. Written at `0x5918` |
| `0xD225` | the melody note now due, with bit 7 set while one is pending |
| `0xD2AA` | the hold flag |

Each tick enters at `0x5B3F`, clears `0xD2AA`, and asks:

```
5B43  3a 22 d2   LD   A,(0xD222)    ; the play mode
5B46  fe 03      CP   3             ; free tempo?
5B48  20 3c      JR   NZ,0x5B86     ; no - dispatch the note as usual
...                                 ; yes, and a melody note is pending:
5B7D  32 aa d2   LD   (0xD2AA),A    ; hold, A = 1
5B85  c9         RET                ; and do not advance
```

and on the next tick the sequencer's own entry sees the flag and turns straight back:

```
59CC  3a aa d2   LD   A,(0xD2AA)
59D0  c2 3f 5b   JP   NZ,0x5B3F     ; still holding - do nothing else
```

Playing Edelweiss in free tempo, that loop ran **1071 times** and the pending note `0xD225` sat at
`0xC4` the whole while. Nothing releases it, because releasing it takes a note from the music
keyboard, which is the one part of this machine that is not emulated.

So the accompaniment holding for the player is the **cartridge's** doing. What still leaves this ROM
unanswered is the *following* — once the player has struck the note, what makes the tempo drift to
match them — and the flag at `0xD356`, which is only ever transmitted.

### The third block is written and never read

Watching every access to the three blocks while the firmware plays settles what the third one does
on this cartridge: **nothing**. The consumer is a parameter pump at `0x5D94`, and a level reaches it
through one instruction, `LD B,(HL)` at `0x5E2E`. Playing Edelweiss:

| block | base | level | pumped |
|---|---|---|---:|
| 0, the melody | `0xD2DC` | `0xD2FF` | 154 |
| 1, the obbligato | `0xD301` | `0xD324` | 245 |
| 2, unidentified | `0xD326` | `0xD349` | **0** |

The pump is called twice, and that is the whole of it:

```
6046  11 dc d2   LD DE,0D2DCh    ; block 0, the melody
6049  cd 94 5d   CALL 05D94h
604C  ...                        ; a flag of block 0's, checked
6057  11 01 d3   LD DE,0D301h    ; block 1, the obbligato
605A  cd 94 5d   CALL 05D94h
605D  ...                        ; the same flag of block 1's
606D  c9         RET             ; and that is all
```

**The address `0xD326` does not occur anywhere in the ROM.** The byte pair `26 D3` is absent from
all 16 KB, so there is no third call and no computed path to one; the routine at `0x606E`, which
walks the same blocks for a different field, likewise handles exactly two.

Block 2 is built like a real part all the same. The initialisation at `0x5D54` walks all three with
`ADD HL,0x25`, giving each `0x80`; other init writes give all three the same `+0x1C` and `+0x1E`
values; and both duck opcodes write block 2's level in step with the obbligato's. The firmware
maintains a third part and never speaks of it.

#### Across the corpus

Every card, played on `csrc/playcard` with a watch on both blocks:

| | |
|---|---:|
| cards played | **261**, and the 3 two-sided sets besides |
| key-ons | 611,818 |
| duck opcodes firing | 826, on 255 cards |
| reads of the obbligato's level by the pump | 57,827 |
| reads of **any** field of block 2 by live code | **0** |

The only reads of block 2 that happen at all are the BIOS sizing RAM at boot and the cartridge's own
zero-fill, an `LDIR` that reads back the byte it just wrote. Neither is anybody consuming a value.

So for this machine the answer is settled and negative: **the UPA-01 cannot duck a third part on any
card, because it never transmits one.** What the third part *is* remains a question about the
keyboard the cartridge was written to drive, and one this ROM cannot answer — see "Still open".

The 6 cards that never duck are worth naming, because they are not scattered: they are the
**six `b` lessons of Step by Step 1**, and every one of the matching `a` lessons ducks. A card with
no melody section to mark emits neither opcode.

### Pitch is a YM2151 key code

The byte each note opcode emits is the note field of the chip's KC register, whose block runs
`C# D D# · E F F# · G G# A · A# B C` — so C sits at the **top** of a block, not the bottom.

The *numbering* is format-level rather than the cartridge's alone: the same note codes appear in the
header's key field and in the chord chart, and the **PCS-30's** own converter maps them the same
way, 12 of 12, from a table in a completely different ROM. What is the cartridge's is the middle
column below — its lookup from the card's 4-bit opcode to that code.

| opcode | ROM byte | note |
|---:|---:|---|
| 0 | 3 | *unused code* |
| 1 | 10 | A |
| 2 | 13 | B |
| 3 | 14 | C |
| 4 | 1 | D |
| 5 | 4 | E |
| 6 | 5 | F |
| 7 | 8 | G |

### Octave: a running register

There is **no rule inferring octaves from context**. The cartridge keeps an octave register,
exactly like the key code it ends up writing, and the card's modifiers move it:

| modifier | emitted | effect |
|---:|---|---|
| 0 | `0xE8 00` | sharpen the following note only |
| 1 | `0xE8 01` | raise the octave register |
| 2 | `0xE8 02` | lower the octave register |

A note's MIDI pitch is `12 × (octave + 1) + chromatic_index(code) + 1`, plus the key shift. The
register starts at **4**.

Flats are spelled as sharps of the letter below — an A♭ is stored as `<sharp> G`.

---

## Repeat structure

The compressed stream marks repeats but does not say where they go. The cartridge decodes into a
byte buffer and then runs a **back-fill pass** which turns the markers into a call/return program.

**While decoding** (ROM `0x6535` for opcode streams, `0x6360` for duration tracks) each repeat
marker emits three bytes — the marker and a two-byte hole — and records the address just past that
record in `slot[n]` of a four-entry table at `0xE46B`. A later marker for the same span overwrites
the slot, so the slot ends up holding the position after the **last** marker for that span.

**When the track ends** (ROM `0x638B`, resolving at `0x6398`), for each span in turn:

```
DE = slot[n]; skip the span if the slot was never set.
Walk the buffer from the start of this track's region:
    byte  < 0xE1   ordinary data, one byte
    byte >= 0xF0   a marker: if it is span n, rewrite it as 0xF0 and fill its
                   hole with DE; otherwise skip its two bytes
    otherwise      a two-byte record (0xE1/0xE7/0xE8).  Skip it, then if we have
                   reached or passed DE, write E1 10 00 over the three bytes
                   ending at DE - that is, over the last marker - and stop.
```

So **every marker for a span except the last becomes a call to the span body, and the last becomes
the return that ends it**. Reading the result is then trivial: walk the bytes, `0xF0` with an
address is a call, `0xE1 0x10` is a return.

`playcard_resolve.py` reproduces this exactly. The objective check is that a duration track and its
pitch stream must expand to the same number of events, since they pair one-to-one: that holds for
**all 261** cards.

### The body is the tail, and a marked track needs two terminators

Reading that description is enough to decode a card and not enough to write one. Two things it
leaves implicit are exactly the two that a generator gets wrong, and both were found by building
cards that failed.

**The "span body" is the material *after* the last marker, not the material between markers.** The
call address is `slot[n]`, which is the position just past the last marker, so every earlier marker
jumps *forward* to the tail, plays it, and returns. The shape on the card is

```
seg1 [marker] seg2 [marker] seg3 [marker] BODY... <close> <end>
       |               |             |
       call ----------------------------> BODY, then return
```

so with *k* markers the body is played **k − 1** times, interleaved with the short segments that sit
between the markers, and is *not* played again at the end — the last marker has become the return
that finishes the track. Put the body before the markers instead and the calls replay nothing: the
span resolves to identity, valid but pointless. Across the corpus **517 of 522 duration tracks
resolve longer than they are stored**, typically about double, so replaying is what these markers
are for.

**A track carrying any marker needs two `0xE1`s at the end.** A marker leaves a pending flag (ROM
`0x636F`); the next `0xE1` is spent *closing* the span and only a second one ends the track. Emit
one and the parse runs straight on into the next track and the card is rejected. Real cards show it
plainly — Silent Night's melody duration track ends `... 30 0C 0C B0 18 END END`, and its opcode
stream likewise. The flag is a single flag rather than a count, so one closing `0xE1` suffices no
matter how many markers precede it.

The same two rules hold for opcode streams, with the end opcode `E` in place of `0xE1`. A stream
with a real span needs no other terminator: the span's own return ends it, which is why the
`E.terminated()` idiom — a lone marker plus a close — exists only for streams that have no repeat of
their own.

**A span pays for itself only from three markers.** Stored, it costs the body plus *k* markers;
played, it yields the body *k* − 1 times. The saving is `(k−2) × |body|` less the markers, so two
markers always lose and one is the degenerate case that `E.terminated()` uses to end a stream.

**The four structures compress independently.** A duration track and its opcode stream are resolved
by the same pass with the same four span slots, but nothing couples them: across the corpus **517 of
522 part-pairs place their markers at different events**, in different numbers. Silent Night's
melody uses spans 0 and 1 in both, with seven markers in the track against six in the stream. That
is what keeps the one-to-one pairing safe — each structure need only resolve losslessly back to its
own sequence, and the pairing then holds for free.

`make_random_card.py` generates cards that exercise this; roughly half carry a span that genuinely
replays, at about the same expansion ratio as the originals.

---

## The section table

Not static data. The routine at `0x659E` walks the table at `0xE3AE` on every decoded opcode,
comparing `0xE484` against each entry, and on a hit emits an inline `0xE7` record carrying the
entry's value — so the table is merged into the stream during decoding.

Entries are **three** bytes: a value, then a 10-bit position assembled by the rotate sequence at
`0x6477`. `0xE484` is set to 1 when a stream starts and incremented once per 4-bit read, so the
positions are **opcode indices within the current stream**, not musical time. Because they index
into a stream and reset per stream, the table cannot reorder anything — it annotates.

### The cartridge's table holds 62 entries, not 63

The parse loop at `0x6454` loads `D` with `0x3F` and stops when that counter runs out — but it stops
**without reading the end-of-table marker**, so a table of 63 leaves ten bits unread and everything
after it, both opcode streams included, is parsed from the wrong bit. The usable maximum is
therefore **62**.

This is the **cartridge's** limit and not the format's: the PCS-30 keeps the chart as byte pairs in
a span with no counter, and has no such ceiling (see below). A card has to satisfy whichever reader
is tightest, which is what makes 62 the number that matters.

The corpus says exactly that. The largest chart in it is **62 entries** — I Won't Last a Day Without
You — and nothing reaches 63. The format is used right up to the ceiling and never past it, which
is the same shape as the 433-byte length limit: a physical stop that the arrangers worked against.

The value-change records do not count against it. Those are the `code == 15` case, which sets the
current chord and continues without consuming a slot, so real cards reach **83 records** in a table
whose counter only ever sees the 62 positions.

#### Yamaha patented this shape, three years earlier

**US 4,587,878** (Nippon Gakki, priority 27 June 1981, granted 1986) describes an earlier machine of
the same family, and its chord data is built the way this chart is: a **chord name recorded once**,
followed by **several timing records** that point at it, each timing being an *address into the
melody note sequence in memory*. That is exactly the two kinds of record here — a `code == 15`
value that names the chord, and position records saying where it applies — and it is why only the
positions count against 62. Edelweiss is 34 timing records referring to 10 distinct chords.

The patent is not a description of this format. Its melody notes are a 6-bit code of two octave bits
and four note bits, where a Playcard keeps a running octave register and emits YM2151 note codes; it
has no obbligato, no bar marks and no accompaniment-pattern selection; and its timings index the
melody where a Playcard's index the obbligato. It is the ancestor, not the thing — but the chart's
design is Yamaha's own and was patented before the cards in this corpus were written.

This is a hard limit on anything that generates cards, and a sharper one than the length: expanding
a card's repeats multiplies its chart entries, so a song whose chart fits comfortably when
compressed can need well over 62 written out flat. Of the 264 cards, **101 exceed it** once their
repeats are resolved.

### The table is grouped by value, not sorted by position

An entry costs ten bits for its position, and a further ten every time the
value **changes** from the previous entry — the `code == 15` record that sets the current chord.
Nothing requires the positions to be in order: the routine at `0x659E` scans the whole table against
its opcode counter on every decoded opcode, so an entry is found wherever it sits.

So the cheap layout is to **group the entries by value**: all the positions of one chord together,
then all the positions of the next. The table then pays one value record per *distinct chord*
instead of one per change. The originals do exactly this, and the PCS-30's decoded chord tables show
it plainly — they come out grouped by value with the positions **descending** inside each group,
which no position-ordered reading would produce.

The saving is large on a chart that alternates. On It's Only a Paper Moon the original spends 622
bits on 52 entries; sorted by position the same chart costs 932 bits for only 46. That one change
took thirteen cards under the 433-byte limit.

### A chart entry fires once, at the obbligato's position

The table's positions are opcode indices, and the cartridge walks the table on every decoded opcode
of **both** streams (`0x659E`), which raises an obvious worry: an entry at position *P* would also be
emitted into the melody stream, firing at the melody's opcode *P* — a completely different musical
moment, since the two streams run at different opcode rates. **It does not happen.** Only the
obbligato's copy reaches the chord handler.

A card was written to make the two moments impossible to confuse: sixteenth notes in the melody, so
sixteen opcodes to the bar, against whole notes in the obbligato, so one. A chart entry at position
17 therefore falls in **bar 2 of the melody and bar 17 of the obbligato**. Breakpointing the `0xE7`
handler at `0x5FC6`, which writes the live chord byte to `0xD353`, and playing the card on the real
firmware:

| what | when |
|---|---|
| the entry at position 1 | at the start, as both readings predict |
| the entry at position 17 | **0.05 s before the obbligato's seventeenth note** |
| anything at the melody's opcode 17 | **nothing — a 43-second silence in the log** |

The melody was running throughout, striking a note every 0.17 s, so it passed its own opcode 17
within three seconds of starting. No chord record appears there, or anywhere else, until the
obbligato arrives at the same index.

This is read from the cartridge's own handler rather than from the audio, so the chord-dropout
bug described above cannot affect it, and it is a *local* comparison — a record against the
note beside it — which would survive a capture whose absolute timing was off, as every capture
from `csrc/playcard` was, by 4%, until the timer fault in "Playback ticks" was found.

The PCS-30 agrees structurally, which is the second reason to believe it: that machine keeps the
chord chart as its **own span**, with its own start and end pointers, and never merges it into
either opcode stream at all. The cartridge's inlining is a decoding strategy, not something the
format asks for. `new-cards/make_chart_test.py` builds the card.

### The values are the chord chart

Each value is a chord, packed as `(type << 4) | note`, where **note is a YM2151 note code** — the
same encoding the pitch stream uses:

| type | chord |
|---:|---|
| 0 | major |
| 1 | minor |
| 2 | seventh |
| 3 | minor seventh |

The structural evidence is the low nibble. Across 10220 table entries it lands on the chip's unused
codes 7 and 11 **exactly zero times**, and on 3 only 47 times — the same signature that identifies
the pitch opcodes. The high nibble takes only the values 0–3. Separately, 825 entries are `0xFF`,
which is not a chord but the **accompaniment mute** described above: it stops the accompaniment
sounding, and the next real chord starts it again.

**47 entries name a root the chip cannot play. They are not mutes: they mean "the root already
sounding, with this quality".** Across 22 of the 267 cards the low nibble is 3 — one of the
YM2151's four unused note codes, and the very code the pitch stream emits for a rest. The type
nibble is valid on every one, and only three values occur: `0x23` on 33 of them, `0x13` on 8, `0x33`
on 6. `0x03`, which would be a major, appears nowhere.

**The PCS-30 implements the convention explicitly.** Its converter looks the note code up in a table
that maps the chip's unused codes to `0xFF`, meaning *do not update the root*, and then ORs the type
nibble onto the chord already sounding (see the PCS-30 section below; run, not read). So `0x23` over
a sounding C gives C7, and over a sounding G7 gives G7 unchanged.

**The corpus agrees, four ways.** Resolving the repeats and walking the chord state in playback
order gives 83 of these entries:

| | |
|---|---|
| every change one of them makes | **adds a seventh** — C to C7, Gm to Gm7, Am to Am7, and so on |
| entries that move the root | **none** |
| entries whose result is the chord already sounding | 61 of 83 |
| entries followed by a *different* chord within a bar | 93% |

And they are placed nothing like a mute. A `0xFF` mute lands 6 to 12 ticks after a downbeat 35% of
the time — the documented "sound one chord and stop" idiom — while **not one of these 83 falls
on a bar line at all**, and 39.8% sit on beat 4 or later against 9.5% of mutes. The two occupy
disjoint positions in the bar.

The OR is doing real work, not just adding a bit. On Fly Me to the Moon an entry of type 2 arrives
over a sounding Am and yields **Am7**, which is that tune's chord; replacing the type rather than
ORing it would have given A7.

#### Two thirds of them change nothing, and that is the interesting part

The 83 split cleanly in two, and the halves behave differently. `same_root_entries.py` measures it:

| | changes the chord | changes nothing |
|---|---:|---:|
| how many | 22 | **61** |
| median gap to the next chord | 2.00 beats | **1.00 beat** |
| within a beat of the next chord | 13% | **54%** |
| commonest rhythm | rock | **bossa-nova**, 20 of 61 |

The 22 are harmony: add a seventh, and it stands for a couple of beats. The 61 are a **restatement
of the chord already sounding, placed a beat or less before the next one arrives** — and they pile
into bossa-nova, where pushing the chord ahead of the beat is the whole character of the style. On
Antonio's Song all fifteen sit on the last quaver of the bar, before a change on the next downbeat.

The best reading of the 61 is therefore a **re-strike**: sound the chord again, early, without
changing it. That is invisible in a model that only tracks harmony, which is why they look inert.

**They are not free.** Each occurrence spends one of the 62 chart positions, exactly as naming the
chord in full would. Someday My Prince Will Come sits at **61 of 62** and still spends two of them
on entries that change no harmony at all, which says whatever they do matters to somebody.

#### Does one of them reset something? Not on the PCS-30

If the inert entries are doing anything, the obvious candidate is **state**: restarting the
accompaniment pattern, re-striking the chord, resetting the bass phase. A model that tracks only
harmony would never show it. So the firmware was run instead of reasoned about.

Two machines were set up identically — an A sounding, the pattern at step 7 — and each was given one
chord value through the converter at `0x28BA` and the latch at `0x1E60`, then all 32K of RAM was
compared:

| given | chord byte after | RAM against "A7 in full" |
|---|---|---|
| A7 spelled in full | `29` = A7 | " |
| **same-root `0x23`** | `29` = A7 | **identical in every byte** |
| A spelled again | `09` = A | differs only in the chord byte |
| same-root `0x13` | `19` = Am | differs only in the chord byte |
| mute `0xFF` | `0F` = no chord | differs only in the chord byte |

With an A7 already sounding, so that `0x23` is a true no-op, restating A7 in full and sending
`0x23` again leave the machine **identical in every byte**.

The static reading agrees. The chord path writes exactly two bytes — the staging byte `0x8044` and
the live chord `0x8043` — and the accompaniment **step counter at `0x8038` has four writers in the
whole ROM**, at `0x01CB`, `0x0AA2`, `0x1369` and `0x1D45`, none of them reachable from a chart
entry. The pattern runs on its own 32-step cycle whatever the chart does; a chord value only
supplies the root each step's degree is added to.

**So on this machine there is nothing to reset, and neither form resets it.** Whatever the inert
entries are for, the answer is not here, and `new-cards/playcard_new-17_same-root-test.bin` states
the same chords both ways, at both phases of the two-bar pattern, for a machine whose ROM can't be
read.

#### Whose habit is it

| set | cards | using one |
|---|---:|---:|
| 17-5xx albums | 186 | **22** |
| PC-1000 (Japan) | 27 | 0 |
| PC-100 | 12 | 0 |
| PCS-30 | 12 | 0 |
| German | 12 | 0 |
| Step by Step | 12 | 0 |

Every card that uses one is in the international album series, 22 of 186, dated **1982-05-14 to
1985-01-24** with sixteen of the twenty-two in 1982. No keyboard's own set uses the convention, and
neither do the twelve teaching cards.

#### The chord-lesson reading, and why the distribution refuses it

The **PC-1000** (late 1983) has a *Chord Lesson*: the accompaniment holds until the player fingers
the chord, the same idea as free tempo applied to the left hand. A "keep the root, add this quality"
entry is shaped like an instruction to a pair of hands rather than like harmony, and on these
keyboards' single-finger chording the type nibble is literally *which extra key sits beside the
root* — minor takes the black key to the left, seventh the white key, and a minor seventh both. On
that reading `0x23` says **add one white key**, which is exactly a lesson-sized instruction, and the
73% that change nothing become "you should be holding this now" rather than dead weight.

It is a good fit in form, and the distribution refuses it anyway:

* **The machine with the feature never uses them.** All 27 PC-1000 cards in the corpus carry none.
* **Most of the cards predate it.** Sixteen are from 1982, the earliest 1982-05-14, more than a year
  before the PC-1000 existed.
* **The twelve Step by Step teaching cards carry none**, and if any set were cueing a learner's
  hands it would be those.
* **The convention can only add.** An OR cannot clear a bit, so it can never say *release* a note —
  and half of what a chord lesson has to tell you is when to let go.
* The 61 inert entries sit where a **push** sits, in the styles that push.

So: shaped like a cue, distributed like an arranging habit. Settling it needs a PC-1000 ROM, and no
dump is known to exist.

**Yamaha's own patent does not explain them either.** US 4,587,878, which covers the ancestor of
this chart (see "Yamaha patented this shape" above), has nothing to say about a root code naming no
note, no mechanism for changing a chord's type while keeping its root, and no lesson or waiting
mode at all. What it does confirm is the frame the question sits in: a chord-name record is a
**state assignment**, "the current chord is now this". A same-root entry is then a state *update*
rather than an assignment — which is what the PCS-30 implements, and still no reason for an
arranger to write one that updates nothing.

### The cartridge does not implement it, and falls silent

On the UPA-01 these entries stop the accompaniment dead. That is measured, not inferred: no original
card isolates one, so two cards were written that do nothing else, the second giving each value four
bars of silence to lapse in with `0xFF` as the control in the same capture:

```
bar    1   2  3  4  5    6   7  8  9 10   11  12 13 14 15   16  17 18 19 20   21  22 23 24
      C   FF  .  .  .   C   13  .  .  .   C   23  .  .  .   C   33  .  .  .   C   .  .  .
```

| block | value | C major bar before | its four bars | drums |
|---|---|---:|---:|---:|
| bars 2-5 | `0xFF`, the mute | 4 chord + 3 bass | **0** | 31-32 |
| bars 7-10 | `0x13` | 4 chord + 4 bass | **0** | 31-32 |
| bars 12-15 | `0x23` | 4 chord + 4 bass | **0** | 31-32 |
| bars 17-20 | `0x33` | 4 chord + 4 bass | **0** | 31-32 |

Nothing sounds in any of the sixteen bars, on any of the four values, while the drums run untouched.
Bars 21-23 are the control that makes it airtight: they carry one C major entry and then nothing at
all, and the accompaniment plays in every one of them — so the silence is caused by the entry and
not by the absence of one, which is the only other thing those bars have in common. The firmware's
chord-dropout bug cannot account for it either: that needs a mark 7 and this card carries none,
it leaves the bass playing and here the bass stops too, and it is not aligned to the chart while
this is. `new-cards/make_mute_test.py` builds both cards.

The handler at `0x5FC6` is three instructions — `LD A,C`, `OR 0x80`, `LD (0xD353),A` — so the
value reaches the accompaniment generator unaltered, with root code 3, which it cannot voice.

**So the cartridge is the machine that gets these wrong.** The 22 cards carrying them were made
between May 1982 and January 1985; the cartridge ROM is dated 1985 and the PCS-30 is 1984. A card
pressed for the PC-100 era is asking for a convention that the later cartridge does not know, and
where an arranger wrote "keep this chord and make it a seventh" the cartridge plays nothing at all.

`card_decompile.py` therefore writes the chord out in full rather than as a mute: that is what the
entry means, it plays the same on either machine, and a card compiled back from it no longer needs
the reader to know the convention.

Reading Someday My Prince Will Come's table straight out gives:

```
F | A7 | Bb | Bbm | C#7 | C7 | F | A7 | Bb | Am7 | D7 | Gm | D7 | Gm | Bbm7 | C7 | F
```

which is the song. Three independent confirmations: the user's ear (bar 1 F major, bar 3 A7, bar 4
unchanged — and the table has no entry at bar 4, exactly as it should not); the progression being
the tune's real changes; and a firmware capture whose bass root motion runs F, F, A, A, B♭ across
bars 1–5, matching the chart bar for bar.

**All four types are now confirmed directly** — see below. Note that the chords are stored at
**sounding pitch**: they are not transposed by the key field, though the melody is.

### How the UPA-01 voices an accompaniment chord

**This section is about the cartridge's own synthesis and not about the format.** Nothing here is on
the card: the card names a root and one of four types, and what follows is how *this* machine turns
that into sound on a YM2151. The PCS-30 reaches the same four chords by a different route entirely
— its own pitch-byte and seventh tables, described under "A second implementation" below — and
what the PC-100 does is not known. Read it as an answer to "why does a capture of the cartridge look
like it is playing minor chords", which is the question it was written for.

Reading chord quality off a capture looked impossible for a long time. The accompaniment's two chord
channels receive key codes a **minor third apart on every chord** — C and D♯ for a C chord, G and
A♯ for a G chord, D and F for a D chord — and those key codes do not change at all between major,
minor, seventh and minor seventh. A card built to hold each of the four types in turn on the same
root sends *identical* KC to the chip for all four.

The chord tones are not the key codes. They are the **operator frequency multipliers**, and the
trick is the harmonic series: `MUL` 4 : 5 : 6 is exactly a just major triad. Both chord channels run
**algorithm 4**, which is two independent two-operator stacks, so each channel has two carriers that
sound independently. The card-built experiment isolates what each type changes:

| register | major | minor | seventh | minor 7th |
|---|---:|---:|---:|---:|
| ch3 C2 `MUL` | **5** | 6 | **5** | 6 |
| ch4 C1 `MUL` | **5** | 4 | **5** | 4 |
| ch4 C2 `MUL` | 6 | 6 | 6 | 6 |
| ch4 C2 `TL` | 127 *silent* | 127 *silent* | **39** | **39** |

ch3 is tuned to the root and ch4 three semitones above it, and each carrier sounds root × MUL:

| type | ch3 C1 | ch3 C2 | ch4 C1 | ch4 C2 | sounds |
|---|---|---|---|---|---|
| major | ×4 → C | ×5 → **E** | ×5 → G | *silent* | **C E G** |
| minor | ×4 → C | ×6 → G | ×4 → **E♭** | *silent* | **C E♭ G** |
| seventh | ×4 → C | ×5 → E | ×5 → G | ×6 → **B♭** | **C E G B♭** |
| minor 7th | ×4 → C | ×6 → G | ×4 → E♭ | ×6 → B♭ | **C E♭ G B♭** |

So the major third is the fifth harmonic of the root channel, the fifth is the fifth harmonic of the
minor-third channel, and the seventh is the sixth harmonic of the minor-third channel — gated by
`TL`, muted for a plain triad and unmuted for a seventh. Two channels and two fixed pitches give all
four chord types.

The arithmetic lands where it should: +0.00, +3.86, +6.86 semitones for a major triad, and +0.00,
+3.00, +7.02 for a minor one. These are just intervals, so the third is 14 cents flat of equal
temperament and the fifth 2 cents sharp — the accompaniment is in just intonation over its root.

That is why the first reading of this was wrong. The key codes alone say "root plus minor third" for
every chord on every card, which looks like a minor triad and is nothing of the kind. **Chord
quality is readable from a capture of this cartridge after all** — from `MUL` and `TL`, never from
`KC`. The finding started from a listener naming the notes of a C major chord as C, E and G against
a capture that appeared to show C and E♭.

None of which says anything about what a PC-100 does with the same card. It says what to look at in
a capture of the UPA-01, which is what makes such a capture usable as evidence about the *card*.

---

## What is not on the card

Chords, bass and drums are **not** in the card data. They come from the firmware's rhythm and
accompaniment pattern generator. The card selects *which* pattern — the rhythm field picks one of
ten styles and the accompaniment-pattern bit picks the standard or alternate form of it — but the
pattern content itself lives in the firmware.

The card carries melody, obbligato, tempo, rhythm and pattern selection, voices, key, sustain,
drum fills and the obbligato's balance against the melody — the arrangement, not the accompaniment
itself.

Those tables have now been read out of **another** instrument. The UPA-01's own are still
unextracted, but the PCS-30 keyboard's are decoded in full — see below, where the same rhythm
numbering and the same chord-type encoding turn up in a machine that shares nothing else with the
cartridge.

---

## Tools in this folder

| File | Purpose |
|---|---|
| `playcard_decode.py` | Parses a card: header, alphabet, duration tracks, opcode streams, CRC |
| `playcard_resolve.py` | Reproduces the cartridge's back-fill, giving true playback order |
| `midi_export.py` | Melody, obbligato and chords to MIDI, statically; joins two-sided cards. `--all` converts everything |
| `fake_cr01.tcl` | Stand-in for the CR-01 reader, so openMSX can load a card |
| `play_card.py` | Plays a card on the emulated MSX with sound; `--wav` captures audio |
| `msx_screen.tcl` | Dumps the MSX screen as text — the accessible way to see the cartridge UI |
| `card_to_midi.py` | Captures the FM chip while the firmware plays. Superseded for melody and obbligato; still the only route to the accompaniment |
| `playcard_encode.py` | Builds a card image from scratch and verifies its own output. The way to turn a field into an experiment |
| `z80dis.py` | Small Z80 disassembler for the cartridge ROM — `python z80dis.py 5F8B 5FC2` |
| `card_dates.py` | Decodes the trailer: the date every card carries |
| `swipe_to_card.py` | Recovers a card image from a recording of a swipe; refuses to save unless the CRC checks |
| `card_to_swipe.py` | Renders a card image as swipe audio, for feeding a keyboard through a coil |
| `forge_crc.py` | Gives a deliberately corrupted card a checksum that passes, so a keyboard will accept it |
| `header_edit.py` | Shows or rewrites a card's header — tempo, rhythm, voices, transpose, sustain, pattern — and fixes the checksum |
| `Sample Playcards/` | Cards written as MIDI and compiled, and the guide to writing one. See its README |
| `new-cards/` | Cards written in 2026 to answer questions no original card can. See its README |
| `pcs30_demo.py` | The PCS-30 keyboard's three built-in demos, decoded — they are card data |
| `pcs30_arrange.py` | A card as a full five-part MIDI arrangement, with that keyboard's accompaniment; `--all` converts a whole folder. Reads the pattern tables from `pcs30-tables.json`, which is generated rather than shipped |
| `make_random_card.py` | Random but structurally valid cards for exercising a keyboard — every header field across its legal range, and a fresh structure per card |
| `make_test_midi.py` | A four-channel MIDI written from scratch, for testing the compiler on music that never was a card — and on pieces long enough to need two sides |
| `midi-roundtrip-design.md` | **Design, not code.** The plan for compiling a card from a MIDI file and decompiling one back |
| `z80run.py` | A small Z80 interpreter, the companion to `z80dis.py`: runs a ROM routine instead of reading it |
| `z80run_test.py` | Checks that interpreter against 17 hand-computed results before anything trusts it on a ROM |
| `pcs30_rhythm.py` | That keyboard's accompaniment pattern tables, rendered over any chord. From `pcs30-tables.json`, not from a ROM |
| `pcs30_drums.py` | Its drum patterns and the six fills, likewise. `--card` is different in kind: it *executes* the firmware's bar-mark handler, so that one mode needs the PCS-30 ROM itself |
| `pcs30_extract.py` | Reads a PCS-30 ROM **once** and writes `pcs30-tables.json`, checking the shape of both tables before it writes. `--check` reports on an existing file |
| `pcs30_tables.py` | Loads that file for everything else, and is where `pitch_byte` and `drum_mask` live. Run alone it says whether the tables are present and which ROM they came from |
| `playcard_expand.py` | **Superseded** by `playcard_resolve.py`. Kept only for reference |
| `playcard_midi.py` | The MIDI side of the round trip: the channel layout, the control-note map, quantisation and chord recognition |
| `card_decompile.py` | A card to an editable four-channel MIDI file — notes, chords, bar marks, the duck opcodes and the header |
| `midi_compile.py` | That MIDI back to a card image, reporting everything the format cannot carry. `--roundtrip` checks the whole corpus |
| `playcard_compress.py` | Finds the repeats worth factoring out of a generated card, and lays out the spans — the resolver is what checks the result |
| `card_limits.py` | Runs the cartridge's own parser over a card and says whether the firmware would accept it. `--sweep` finds the size ceiling from scratch |
| `csrc/` | **A card to a WAV file with no emulator installed.** `playcard` runs it on an emulated CX5M at about 150x real time and captures every YM2151 write; `fmlog2wav` renders that through ymfm. `--no-fm` makes the cartridge fall back to the PSG, which is the only way to see that half of it. See `csrc/README.md` |
| `same_root_entries.py` | Every unplayable-root chart entry in the corpus: which cards use them, what each does to the sounding chord, where in the bar it sits. Name a card and it prints that card's chart instead |
| `sweep_block2.py` | Runs the whole corpus through `csrc/playcard --watch` to ask whether anything ever reads the third part's level. Nothing does |
| `check_wrong_file.py` | Throws nine kinds of wrong file at every tool that takes one, and fails if any answers with anything but a sentence and exit 1 |
| `check_machine_named.py` | Checks that every source file describing behaviour names the machine it means, imports the naming block, or declares itself machine-neutral |
| `new-cards/dropout_trigger.py` | Builds eighteen one-chord cards and plays them, to find what triggers the UPA-01's chord dropout |
| `check_line_width.py` | Runs the tools down some fifty paths and flags any sentence too wide for an 80-column terminal |
| `key_against_firmware.py` | Plays every card with a non-zero key field on `csrc/playcard` and compares the firmware's melody note for note against the decoded one. The round trip cannot catch a transposition error — it uses the same function both ways — so this is the check that can |
| `key_field_check.py` | What the header's key field is doing, measured three ways: black notes in the melody as written against as played, how many melody notes are tones of the chord under them, and what key each card is actually written in. Name cards on the command line to see them one at a time |
| `README.md` | The repository's own front door: what each tool is for and how to run it, in plainer terms than this document |
| `msx_player.py` | The same emulated machine in Python, at 79% of real time. Slower than the C one and worth keeping: it can be stopped and asked what is in a byte, which is how the silent-playback bug was found |

### What is not in the repository

The card images and the ROMs are Yamaha's, so neither is published here. The tools expect them in
`Original Playcards/` and `Roms/` beside the code, and the environment variables `PLAYCARD_CARDS`
and `PLAYCARD_ROMS` point them elsewhere. Every corpus-wide tool resolves the folder through
`playcard_decode.corpus()` and every ROM reader through `playcard_decode.rom()`; both fail with a
message naming the missing folder rather than silently finding nothing.

**The PCS-30's accompaniment and drum patterns are Yamaha's too, and they are the one case where
the line runs through the middle of a tool.** The patterns are that instrument's musical content
rather than a fact about the card format, so they stay out — but the code that reads them is a
description of how a machine behaves, and there was no reason for it to stay out with them. It used
to: `pcs30_arrange.py`, `pcs30_rhythm.py` and `pcs30_drums.py` were all gitignored alongside the
data, which was the easy way to draw the line and the wrong one.

The patterns now live in **`pcs30-tables.json`**, which is generated and gitignored. Make it once
from a ROM you own:

```
python pcs30_extract.py          # Roms/PCS-30.rom -> pcs30-tables.json
```

and the three tools above read that file and never open a ROM again. Without it each one stops with
an explanation rather than a traceback. Two things still need the ROM itself, because they run its
code rather than reading a table: `pcs30_drums.py --card` and `pcs30_demo.py`.

The seventeen cards in `new-cards/` *are* published — they were written in 2026 from this
document, so they are ours. So is `Roms/README.md`, which is the one file in that folder: it names the four ROM
images the tools can want, says which tool needs which, and notes what a good dump of each looks
like. Most of the repository needs none of them.

### Driving openMSX without the GUI

**Historical.** Everything below was how this project worked until `csrc/playcard` existed. That
program now runs the same cartridge about 150 times faster, at the correct tempo, with nothing
installed, and since it keeps the VDP's video memory it reads the cartridge's panel too — which
was the last thing openMSX was needed for. Nothing here should be used for a new measurement.

openMSX runs Tcl at startup via `-script`, and Tcl can write files, so the emulator can be operated
entirely through text. Speeding a capture up does not work, but not for the reason once recorded
here: measured over a fixed emulated window, every setting of `speed` from 100 to 2000, `fastforward`
at up to 10000, and `throttle off` all yield **identical FM writes and identical wall-clock time**.
Nothing is lost at high speed; nothing is gained either, because the Tcl watchpoint callback is the
whole bottleneck — without one, openMSX runs at about 74x real time.

The documented external-control channel does not work on this Windows build: `-control stdio`
closes its stdout pipe immediately because openmsx.exe is a GUI-subsystem binary, and the TCP
socket accepts a connection then resets it. `-script` sidesteps both.

### The cartridge's sequencer ticks at 100 a second, whatever the MSX

The cartridge's `INIT` copies a five-byte `RST 30h` stub into **H.KEYI** (`0xFD9A`), so every VDP
interrupt enters the cartridge at `0x410D`. That gates on the VDP's own frame flag — `IN A,(099h)`
at `0x7DD1` — and jumps to `0x431F`, which is `LD HL,(0CC58h)` / `JP (HL)`: a state machine
dispatched through a RAM vector. **One pass is one tick of the sequencer.**

The rate that machine expects is **100 ticks a second**. On a card declaring 120 bpm a quarter note
measures 49.7 ticks, and bpm x ticks-per-quarter comes to 6000 — which is right only at 100 Hz.

No MSX VDP supplies it. A PAL machine interrupts at 50 Hz and the music comes out at **exactly half
tempo**; an NTSC one would give 0.6x. And the ROM never reads the BIOS frame-rate flag at `0x002B`,
so it does not scale itself to the machine either. A sequencer clocked off the VDP would therefore
play 20% faster in Japan than in Europe, which is not something Yamaha would ship — so the VDP
interrupt is almost certainly not the intended clock. The one source in a CX5M that can be
programmed to a fixed rate regardless of the video standard is the **YM2151's own timer**, which is
also the chip the cartridge already drives.

**And it is now demonstrated, not just measured.** An emulated CX5M that delivers timer A's
interrupt plays a 120 bpm card at **119.7 bpm**; the same machine driven only by a 50 Hz VDP plays it
at half that. So the timer is the clock, and half tempo under an emulator means the OPM's interrupt
is not reaching the firmware. `csrc/playcard.c` is the demonstration.

This paragraph used to say 120.4, on a figure taken before a fault crept into that program. From
then until 2026-09-21 **every capture it made ran about 4% slow**: its playback loop runs the machine
a quarter of a second at a time, and each call restarted timer A's count from nothing, throwing
away the part of a period already elapsed. A trace of the SFG's interrupt handler showed the missed
tick exactly every 250 ms. With the timer's phase kept across calls the handler services 95.772
interrupts a second against 95.771 programmed, and every tempo lands within the chip's own
resolution of what the cartridge asks for — 39.9 bpm for 40, 99.9 for 100, 199.8 for 200.

**The timer values, measured rather than deduced.** Running the machine in Python (`msx_player.py`) and
watching what the SFG programs, the FM module starts **both** OPM timers with their interrupts
enabled — register `0x14` = `0x3F` — and loads timer A with `CLKA` = 512, which at the chip's
3.579545 MHz clock is a period of 9.154 ms: **109.24 Hz**. That is where the SFG leaves it, and it is
within 10% of the 100 a second the tempo arithmetic implies.

**Then the cartridge sets the timer from the tempo**, once a card starts and again whenever the
panel's tempo moves. For 120 bpm it loads `CLKA` = 440, 95.771 Hz, and the sequencer takes one card
tick every two overflows: 47.9 ticks a second, 119.7 bpm. The divider changes with the tempo to keep
the timer in range — one overflow a tick at 140 bpm, four at 40 — and the residue of a few tenths of
a percent is the timer counting in whole steps of 64 clocks.

The practical consequence is for captures: under an emulator the sequencer gets only the VDP's
ticks, so **anything timed in seconds off a capture is at half speed**. Ratios measured within one
capture are unaffected.

### How the cartridge reaches the FM chip

It never writes the YM2151 itself — there is not one `0x3FF0` in its 16K, no `OUT` to an FM port,
and no IX or IY anywhere. Its `INIT` hunts every slot for the signature **`"MCHFM0"`** at `0x0080`,
and when it finds it, **deliberately leaves page 0 mapped to the SFG**: the jump at `0x40B3` steps
over the code that would restore the slot. From then on the SFG's BIOS entry points sit at `0x0090`,
`0x009C` and neighbours, its YM2151 at `0x3FF0`, and the cartridge simply calls them. That is also
why the whole FM module is mirrored across its slot — the signature has to be readable at `0x0080`
in page 0 while the ROM is read at `0x4000` in page 1.

**The chip's status is read back from the DATA port, `0x3FF1`**, which is where the SFG's own code
polls it (`0x2D57` and `0x2D5E`).

### A silent card usually means the FM module was not seen

The frame handler at `0x4813` is a **rate divider**: it calls one handler every frame, then runs a
second handler as many times as a table at `0xCC6B` says for that frame — `00 01 01 01 00 01 01
01 01 00 ...` — which is how a tick rate that is not a multiple of the frame rate gets made. All
of it is skipped when the gate at `0xCC6A` is non-zero.

That gate is loaded from `0xCC55`, and `0xCC55` is **the return value of command 0**, the FM voice
load, which begins by checking for `"MCHFM0"` at `0x0080` all over again. So a cartridge that cannot
see its FM module does not report anything: it reads the card perfectly, sets up, and then never
plays a note.

### The keyboard is scanned 256 times a second

The cartridge's main loop calls its own matrix scanner at `0x46E8` on every pass, and that loop runs
about **256 times a second** — far faster than the 50 Hz frame rate. A scripted key press of one
millisecond therefore lands somewhere between "never seen" and "seen twice", which is exactly what a
`press` in an emulator script does. It explains a familiar annoyance: the same script sometimes
needs the key pressed again by hand, and sometimes starts playback and stops it again immediately.

### The strip itself: F2F, and how to read or write it

The cartridge sees a bit stream, but the card carries flux reversals. The encoding is **F2F** — the
same self-clocking code as a credit-card magnetic stripe. Every bit cell opens with a reversal, and
a **1** has a second reversal in the middle of the cell:

```
   cell      cell      cell      cell
  |____     |__       |____     |__          flux
  |    |____|  |__ ___|    |____|  |__
   0         1         0         1

  long gap   two short gaps   long gap   two short gaps
```

A tape head produces dFlux/dt, so each reversal appears as a peak and the only measurement needed is
the time between them. On a reference recording of a genuine Silent Night swipe, sampled at 44.1 kHz,
the gaps fall into two clean groups — **136 µs and 272 µs, a ratio of 2.10** — with no third cluster.

Being self-clocking is what makes a hand swipe work at all. Across that one card the cell period
drifts from 11 samples to 15, about **25%**, as the hand slows; a decoder that tracks the period as
it goes reads it without trouble, and one that assumes a fixed bit rate does not.

**And measure the baseline, rather than assuming zero.** A tape head's output can sit well away from
zero for a while — a thump as the card is pushed in will do it. A trigger that compares the signal
against zero then stays latched on one side and drops every reversal underneath. One recording here
rides about **+15000 of full scale** for its first 2250 samples, which is **225 bit cells, 28 bytes
of card, header included**, lost in silence: the envelope looks healthy, the gaps that *are* found
fall into the same two clean clusters as ever, and the only symptom is that nothing parses. Taking a
moving average out of the signal first recovers it exactly, CRC and all. The window has to span
several bit cells — four is a good number — or it follows the data and cancels what it is
supposed to be measuring against.

The card is framed on the strip like this:

```
   <lead-in zeros>  1  <card image>  <run-out zeros>
        31 bits                          ~1400 bits
```

The lead-in is the run-up that lets the reader lock its clock, and the single **1** is the sync. That
sync is also exactly why the CRC seeds at `0x8005`: 31 zeros and a one leave the register in that
state, which is what the `.bin` files inherit by starting one bit later. The run-out is the blank
rest of the strip, and the cartridge needs it — a zero block type is the format's own end-of-data
marker.

### The strip is a fixed length, and that sets the maximum card

Every card is the same piece of tape at the same density, and in F2F a 1 and a 0 occupy the same
cell, so what is constant across the whole corpus is the **number of bit cells**. The run-out is
simply whatever the data does not use. The genuine swipe gives the capacity directly: 31 + 1 + 2128
+ 1433 = **3593 cells**.

The corpus corroborates it. The largest card is 433 bytes, which with its framing is **97.3%** of
3593 — and the size distribution piles up hard against that ceiling and stops dead:

| bytes | 429 | 430 | 431 | 432 | 433 | 434+ |
|---|---:|---:|---:|---:|---:|---:|
| cards | 4 | 10 | 13 | 4 | 10 | **0** |

**37 of the 267 cards sit within four bytes of the maximum.** That is not an arrangement decision;
it is the tape running out, with about 2.7% left as margin. So the format's maximum card size is a
physical fact about the strip rather than anything in the encoding, and a card's run-out length is
fully determined by how much music it carries — a 45-byte card ends with 3201 blank bits, a 433-byte
one with 97.

`swipe_to_card.py` recovers an image from a recording, and `card_to_swipe.py` renders one back to
audio for feeding a keyboard through a coil held against its head. Both were checked against the
genuine recording, which decodes **byte-for-byte identical** to the known image, and against every
card in the corpus: all 267 originals and all 17 new cards round-trip through audio unchanged, at
sample rates from 22.05 to 96 kHz, 8 to 32 bits, and bit rates from 1200 to 8000 per second.

### The firmware's own size limit: 4080 decoded bytes

The strip's 433 bytes are a physical fact about the tape. The cartridge has a limit of its own, and
it is a different quantity: not how big the card is, but **how big it decodes to**.

A card is read into a raw image at `0x8000` and then decoded into a second buffer at `0xD377`, and
it is that second buffer the firmware guards. Two hard-coded compares, one in each decoder:

```
6317  LD A,067h / SUB L / LD A,0E3h / SBC A,H / RET C     the duration tracks
64C8  LD A,067h / SUB L / LD A,0E3h / SBC A,H / RET C     the opcode streams
```

Both test the buffer pointer against **`0xE367`** — one on every duration symbol, the other on
every opcode. Past it the decoder returns with carry set, the section parse fails, and the card is
**refused with error `0x80`**. Nothing is overwritten and nothing crashes: the cartridge's own parse
state begins at `0xE377`, and the guard stops exactly **16 bytes** short of it.

```
0xD377   the decode buffer starts
0xE367   the guard          <- 4080 bytes of room
0xE377   the parse state the guard is protecting
```

So the ceiling is **4080 decoded bytes**, and `card_limits.py --sweep` finds it from scratch by
building longer and longer cards and running the cartridge's own parser over each: 1016 notes a part
is accepted and 1017 refused, which is 4082 decoded bytes against 4086.

**The strip runs out long before the firmware does.** The 264 originals decode to between 158 and
1361 bytes, so the largest real card uses **33%** of the ceiling. At the corpus's median expansion of
2.4x, 4080 decoded bytes is about a **1700-byte** card — four times what the strip physically holds.
A card can only reach the firmware's limit if it could never have been pressed in the first place.

### The CR-01 reader

openMSX does not emulate it, but the interface is simple enough to fake. It is **memory-mapped at
`0x7FFF`** in the cartridge's page — not an I/O port, which is why port scans never found it. Reads
return a status byte:

| bit | meaning |
|---:|---|
| 7 | reader active; 0 means the stream has ended |
| 6 | a data bit is ready |
| 5 | the data bit itself |

The cartridge polls at `0x6892` (testing only bit 7) and takes bits in the loop at `0x68B2`. After
the recorded data, feed **zero bits** — the blank rest of a real magnetic strip — before dropping
bit 7; a zero block type is the format's own end-of-data marker, and without it the reader spins
waiting for more.

Note that F2 is a play/stop **toggle**, and some cards start playing by themselves once read.

### Reading the cartridge's panel

The cartridge displays the card's settings — voices, rhythm, sustain, transpose — and reading them
off the screen is the cheapest way to confirm a header field, because it is the firmware's own
account of what it thinks it was handed.

```bash
csrc/playcard card.bin -o card.fmlog --screen panel.txt --screen-at 5
```

**This needs no emulator installed.** The cartridge does not use the MSX BIOS text routines at all
— not one `CALL` to `CHPUT`, `WRTVRM` or `LDIRVM` in its 16 KB — so there is nothing to intercept
at that level. What it has instead is a single table-driven port writer at `0x7DB6`: a byte count,
then that many bytes to port `0x99` or, with bit 7 of the count set, to port `0x98`. Keeping the
16 KB of video memory those writes land in is enough, and the screen then reads straight out of the
name table, which in SCREEN 0 holds one character code a cell. `csrc/playcard.c` does exactly that
and nothing more: no pixels are rendered.

The numeric fields — tempo, and the transpose control — are drawn as **slider bars** out of the
MSX's graphics characters rather than as numbers, so they come back as blanks in the text and as
codes `0x18`-`0x1B` in the raw dump the tool appends whenever any cell is not ASCII.

Two things make a panel dump worth trusting:

* Feed the **zero trailer** after the card data. `fake_cr01.tcl` does not, which is why its screen
  dump shows defaults: the reader was still spinning and the card had never finished loading.
* The panel is only refreshed **when playback starts**. Until then the header has been parsed into
  a staging record at `0xE377`, but nothing has applied it. Press F2 and sample the screen after.

### A firmware bug that looks like card behaviour

**The UPA-01 drops the accompaniment's non-bass chord notes during playback and does not bring them
back.** The bass continues; the two chord channels simply stop. It is not a property of the format:
it happens to **original cards** too, and it does *not* happen on real Playcard-capable keyboards,
which are not running this firmware.

**It is mark 7 that fires it, and nothing else.** Not the alternate pattern itself: a card whose
header bit LOCKS the alternate on plays sixteen bars of it over one held chord with the chord notes
intact throughout. Put a single mark 7 on that same card and they stop at that bar and never return.
Eighteen cards, one chord held for sixteen bars, differing only in the header bit and which mark
appears at bar 5:

| the card | chord notes |
|---|---|
| header clear, no mark | **hold all 16 bars** |
| header clear, **mark 7** at bar 5 | **stop at bar 5**, and never return |
| header **locks** the alternate on, no mark | **hold all 16 bars** |
| header **locks** the alternate on, **mark 7** at bar 5 | **stop at bar 5**, and never return |
| marks 0, 1, 2, 3, 4, 5 or 6 at bar 5 | **hold all 16 bars**, every one |

The bass is untouched in all of them. **Any chart record afterwards restores the chord notes** — a
new chord and a restatement of the same one work equally well, which is why a dense chart masks the
bug and a sparse one exposes it.

So the fault is in the **mark 7 handling path** rather than in the accompaniment generator: the one
route to the alternate pattern that goes through that handler is the one that breaks, and the route
that does not go near it never does. The header lock even makes mark 7 a no-op as far as the pattern
state is concerned — `0xD352` is already `C3` and the handler's `OR 0xC1` changes nothing — and the
chord notes still drop. Handling the mark is enough on its own.

**The code at fault has since been found.** Handling mark 7 flags a pattern change, and a pattern
change runs the routine at `0x4C63`, which rebuilds the pattern and then sends the chord part
**chord code 3, "no chord"** (`LD C,03h / LD D,04h / CALL 4E5D` at `0x4CB5`). The SFG-01 clears the
"sounding" bit of its chord byte `0xEC23`, and the chord is only sent again when the card's next
chart record arrives. The header lock escapes because its pattern change happens before the card's
first chord; a mark 7 changes the pattern twice mid-card, to the alternate and a bar later back,
with no chord behind either. `csrc/playcard` repairs it by default by re-sending the current chord
straight after the "no chord", as a restated chord would; `--as-is` leaves it in. See "The chord
dropout" in `csrc/README.md`.

`new-cards/dropout_trigger.py` builds every one of those cards and prints the table.

**This was recorded here for weeks as an openMSX bug, and that was wrong.** `csrc/playcard`, an
emulator written from scratch sharing no code with openMSX, reproduces it exactly; two independent
emulators agreeing on a behaviour taken from the same ROM means the ROM is where it lives. The two
observations that drove the misdiagnosis were both true — original cards do it, real keyboards do
not — and both point at the cartridge rather than the emulator.

It is still a trap for anyone reading accompaniment captures, because a chord that stops looks
exactly like an accompaniment mute or a pattern change; it cost three purpose-built cards and three
captures. **Read the pattern state at `0xD352` and the chord records at the `0xE7` handler instead**
— those are what the cartridge decided, as opposed to what it then managed to play.

### Changing one field and hearing the difference

Because the CRC is fully understood, a card image can be edited and re-checksummed, which turns any
header field into a controlled experiment: flip the field, repair the CRC, capture the **UPA-01**
playing both images, and diff. Every other byte of the card is unchanged, so whatever moves is
attributable to that field alone. What such a diff establishes directly is what the field does *to
that cartridge*; it is evidence about the format to the extent that the cartridge is reading the
field rather than inventing something, which is why the header findings above also quote the corpus
or a second machine wherever one is available.

The CRC to store is just the running register after the data — MSB-first, poly `0x8005`, seeded
`0x8005` for these files — since folding the register back in yields zero. Re-parsing the edited
image should show a valid CRC, the intended new field value, and byte-identical tracks and streams;
if any of those fail, the edit landed in the wrong place. This is how the accompaniment-pattern bit
was settled.

---

---

## A second implementation: the Yamaha PCS-30

The UPA-01 cartridge is not the only thing that reads these cards. The **PCS-30** (1984) is a
32-key Playcard keyboard with its own Z80 and a 32 KB ROM — a much smaller machine, with a
squarewave YM2142 rather than the SFG-01's YM2151, and no shared code with the cartridge at all.
It reads the same strips, so it is an independent witness to the format, and its ROM answers two
things the cartridge cannot.

Only the first 15 KB of the 32 KB image is populated; the rest is zero.

### Its built-in demos are decoded card data

The keyboard plays three demo tunes with no button: Mozart's Symphony No. 40, Dance of the Hours
and Chopin's Nocturne. They sit at ROM `0x3726`, `0x3873` and `0x39BC`, gated by bits 0, 1 and 3
of `0x8000`, each handed to a loader at `0x0820`. Each block is

```
12 words   six (start, end) offsets into the body; bit 15 of a pitch-stream
           offset selects the nibble within the byte
 3 bytes   copied to 0x802D - the performance settings
 1 word    body length
 body      alphabet | melody durations | obbligato durations
           chord table | melody pitches | obbligato pitches
```

They are **not** card images and not a private format. They are the exact RAM image a swiped card
decodes into, with the span index precomputed. The loader stores those twelve offsets into twelve
RAM slots (`0x805D`–`0x806B`, `0x80B5`/`B7`/`BB`/`BD`) and block-copies the body to `0x80DA`; the
card-reading path at `0x0383` fills *the same twelve slots* and *the same buffer*, one byte at a
time, from the reader at `0xE020`. The demo loader is a block copy where the card path is a parser,
and downstream nothing can tell them apart.

What survives from the card unchanged:

* **The pitch streams** — the same 4-bit opcodes, the same escape `0xF`, the same note letters and
  running octave register. The readers are at `0x25BC` for the low nibble and `0x2626` for the
  high, each testing its nibble against `0xF`.
* **The alphabet**, still ordered most-frequent-first. In all three demos it is exactly the set of
  values the duration tracks use, with strictly descending frequency.
* **The convention that bar marks and control opcodes live only in the obbligato.** Both melody
  streams carry none of either; all three obbligatos carry both. That rule was derived from the
  267-card corpus and here it holds on different hardware.

What does not survive is the **duration tracks**: on a card these are alternating-run prefix
codewords indexing the alphabet, and here they are the alphabet's *values*, one byte per read
(`0x2561`). The alphabet is kept anyway, though playback no longer needs it to decode.

The clinching check is that all three demos are cards in this corpus. Decoded, the Nocturne demo is
**32 of 32 notes identical in absolute pitch** to both `17-556_easy-classics-2_nocturne` and
`pcs-30_nocturne` — the keyboard's own bundled card. Symphony No. 40 matches its card's interval
contour at 100% from the first note, sounding a tone higher because the demo does not apply the
card's transposition. Dance of the Hours matches at 89%, so that one is a slightly different
arrangement.

### Its accompaniment pattern tables

Eight tables of 320 bytes sit at `0x2D26`, ending exactly where the demo data begins. Each is ten
rows of thirty-two, addressed at `0x14CD` as

```
byte = base + rhythm * 32 + step
```

The ten rows are **the Playcard's own rhythm numbering** — rhumba, samba, swing, bossa-nova, rock,
16-beat, waltz, slow-rock, march, disco. The metre proves it independently: exactly three rows fill
only 12 of each 16 steps, and they are **swing, waltz and slow-rock** — precisely the styles that
take the swing and waltz drum fills, and for the same reason. The PCS-30's front panel offers only
six rhythms; all ten are there, and a card can reach the rest.

A pattern byte is a **1-based semitone offset from the chord root**: 1 the root, 5 the major third,
8 the fifth, 13 the octave. `0xFF` is a rest and `0x00` a dead slot. The reader at `0x16CF` adds
the root and folds the result into range.

### The chord byte, and what a seventh does

The live chord sits in one byte at `0x8043`:

| bits | meaning |
|---|---|
| 0–3 | chord root, 0–11 |
| 4 | **minor** |
| 5 | **seventh** |

which is the chord chart's own `type` — major, minor, seventh, minor seventh — in one byte instead
of a nibble pair. Each bit acts differently, and neither is a transposition:

* **Minor** is a substitution. At `0x16E3`, when bit 4 is set and the pattern degree reduces to
  exactly 5, the note is decremented — a major third becoming a minor third, one degree, in place.
  That single instruction is also what fixes the 1-based reading of the table bytes.
* **Seventh switches tables.** The selector at `0x1620` tests bit 5 and picks a different 320-byte
  table for the whole pattern. So a seventh chord does not get the triad pattern with a note
  altered; it gets a pattern written for a seventh.

The eight tables divide two ways. Odd tables carry the **bass** and even ones the **chord** — their
value ranges do not overlap, the bass spanning the root to +16 semitones and the chord +4 to +29.
Within each voice, one table serves plain triads and another sevenths, and the whole set exists in
two variants.

Read over a G chord, the plain chord table gives **G B D** and the seventh table **G B D F**, the
minor seventh replacing the root.

### The seventh tables walk the PCS-30's bass

The seventh bass table does something the plain one does not: near the end of the bar it walks
upward toward the chord a fourth above. Over G7, comparing the last four steps of each row:

| rhythm | plain bass | seventh bass |
|---|---|---|
| swing | `B . . .` | `A . . . B` |
| slow-rock | `G . D B` | `G . A B` |
| march | `D . B -` | `A . B -` |
| disco | `D - G -` | **`A - A♯ - B`** |

G, A, B — a run at C, which is where a G7 wants to go. The disco row takes it chromatically.

**It does not look ahead.** The walk is baked into the pattern table and keyed only on the chord
sounding *now*, so it anticipates a chord that may never arrive — which is exactly how it behaves
on the instrument: sometimes it lands and sometimes it does not. It is also not on every rhythm.
This was described from the ear of someone who owns the keyboard, before the tables were read, and
the tables say precisely that.

`pcs30_demo.py` extracts and decodes the three demos; `pcs30_rhythm.py` renders the pattern tables
over any chord.

### And its drums

The percussion table is separate, at `0x2BBC`, and laid out by **bit-plane**:

```
byte = 0x2BBC + plane * 0x40 + bank * 0x20 + step      (ROM 0x1274)
```

Five planes of 64 bytes. The *bits* of each byte are the patterns - bit 7 the first, bit 0 the
eighth - so assembling bit *b* of all five planes gives a **5-bit strike mask** for that step
(`0x142F`). Bank 0 bits 7..0 are rhythms 0-9's first eight, bank 1 bits 7 and 6 the last two, and
**bank 1 bits 5..0 are the six drum fills** - the same six the corpus identified from the cards.

A step is a sixteenth and a pattern is 32 steps, so **every pattern is two bars**; bit 7 of the step
counter picks which (`0x0AB9`), which is how a pattern's second bar can differ from its first. The
same three styles that use 12 of 16 slots in the pitched tables do so here, and four of the six
fills are twelve-step for the same reason.

**The drum sounds are not in the ROM.** The mask is written straight to the sound chip at `0xE030`
(`0x077C`); the voices live in the YM2142 itself. The ROM says only which to strike, and when.

The five read off the patterns as:

| bit | voice | how it identifies itself |
|---:|---|---|
| 0 | kick | four-on-the-floor in disco, beat 1 alone in waltz |
| 1 | latin | plays the **son clave** in rhumba and bossa-nova; unused by seven styles |
| 2 | snare | backbeat on 2 and 4 in rock; beats 2 and 3 in waltz |
| 3 | cymbal, long | the open hi-hat - disco's off-beats |
| 4 | cymbal, short | the closed hi-hat - rock's straight eighths |

There is one cymbal on the chip, struck for a shorter or longer time, so bits 3 and 4 are two
lengths rather than two instruments. Every one of those readings was predicted from the instrument
before the table was decoded, including that the waltz is kick and cymbal on beat 1 with snare on
beats 2 and 3 - which is exactly what the bits say.

**The mark dispatch is known; which fill it names is not.** `z80run.py` is a small Z80
interpreter, and running the bar-mark handler at `0x2AEC` with each mark value gives what it sets:

| mark | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| sets bit of `0x80CF` | 3 | 2 | 1 | 0 | 5 | 4 | 6 | 7 |

Bits 0-5 are the fill selector (`0x13F9` masks with `0x3F`); bit 7 is the alternate accompaniment
pattern, as on the cartridge.

**That is a storage indirection and nothing more.** A table bit index is a slot, not a fill number,
so "mark 1 selects the pattern at bit 2" says nothing about which fill is heard. An earlier version
of this section concluded from that dispatch that the PCS-30's fills are marks 0-5 rather than 1-6;
that inference was invalid and the claim is withdrawn.

It is also impossible on its face. A card carries no notion of which instrument will read it, and a
card pressed in 1982 cannot anticipate a keyboard built in 1984, so the same mark must mean the same
thing everywhere — and the fills do sound alike across Playcard keyboards. Any reading that makes
one machine's mark numbering differ from another's is wrong somewhere.

The card-reading path was the obvious suspect and is not the answer: at `0x0486` the opcode nibble
goes into the buffer unmodified, and at `0x25D3` the escape sub-value comes back out unmodified. So
the value reaching the handler is the card's own.

Applying that remap leaves nothing unexplained. **Card mark 0 sets bit 6**, which falls outside the
fill mask and reaches `0x129F` — the routine that clears the pending drum strike at `0x8042`. That
is the drum mute, in the same place the cartridge puts it. Card marks 1 to 6 select the six fills
and card mark 7 sets bit 7, the alternate pattern. The two machines agree completely.

Running a real card through the ROM confirms it end to end. I Write the Songs carries mark 0 on
bars 1 to 4, a fill and a mute in bar 11, a fill in 12, and mark 0 again on 19, 20 and 21 — and
feeding those marks through the handler at `0x2AEC`, latching the result and executing the bit-6
test and its call to `0x129F`, the drum strike is cleared on exactly those bars and survives on
every other. That is the behaviour the card is documented to produce on the cartridge, reproduced
by a different machine's code. `pcs30_drums.py --card` does it.

An earlier version of this section reported mark 0 and mark 6 as swapped between the machines. That
was the missing remap, not a real difference, and the claim is withdrawn.

### What the PCS-30 does with the chord chart

The converter is at `0x28BA`. It takes the chart value in the form the card stores it — `value + 1`,
which is what the 6-bit field holds — masks off the low nibble and looks it up in a 16-byte table at
`0x28E3`, then ORs the type nibble on top. The result goes to a staging byte at `0x8044`, which
`0x1E60` copies to the live chord byte at `0x8043`.

That table is an **independent confirmation of the note-code mapping**, from a machine that shares
no code with the cartridge:

```
      0F 01 02 03 FF 04 05 06 FF 07 08 09 FF 0A 0B 00
```

Indexed by `value + 1`, all **12 of 12** real note codes land on the right chromatic root — code 14
is C and gives root 0, code 0 is C# and gives root 1, and so on to the top — and the chip's three
unused codes 3, 7 and 11 all land on `0xFF`.

`0xFF` in that table does not mean "mute". It means **do not update the root**, and the routine then
ORs the new type nibble onto whatever chord was already sounding. So the two machines part company:

| chart value | UPA-01 cartridge | PCS-30 |
|---|---|---|
| `0xFF` | accompaniment stops | root becomes `0x0F`, its own "no chord" value: accompaniment stops |
| `0x13` `0x23` `0x33` | accompaniment stops | **keeps the root, applies the type** |

Executed rather than read, with `z80run.py` calling `0x28BA`: over a sounding G7, `0x23` gives back
G7 unchanged, while `0x13` and `0x33` give Gm7. Over a C major, they give Cm, C7 and Cm7.

So **a card carrying one of these plays differently on the two machines**. On the cartridge all of
them silence the accompaniment; on the PCS-30 they alter the chord's quality without moving its
root, and because the type usually matches the chord already sounding (72% of the corpus's 47), most
of them are no-ops there. Which behaviour the arranger meant is not something either ROM can say.

**And the PCS-30 has no 62-entry ceiling.** It keeps the chart as (value, position) byte pairs in a
span with start and end pointers and no counter at all, so its limit is RAM rather than a table
size. The ceiling is the cartridge's, and a card has to satisfy the tightest reader — which is
exactly what the corpus does by stopping at 62.

### What this does and does not settle

It gives a complete, worked example of a Yamaha accompaniment generator built around this format,
using the same rhythm numbering and the same chord-type encoding as the cards. It does **not**
give the UPA-01's tables: that is a different machine with a different sound chip, and its patterns
are still unextracted. What the PCS-30 supplies is the shape to look for.

---

## How this was verified

Three independent checks, none sharing an assumption with the others.

1. **The checksum.** All 267 cards close with CRC = 0. A single misplaced bit anywhere in the parse
   would break it.
2. **Style versus title.** The rhythm field sorts songs into rhumba, samba, bossa-nova and waltz
   groups matching what the titles say they are. Summing decoded durations, 86% of waltzes come out
   as a whole number of 3/4 bars while every other style is majority-divisible by a 4/4 bar —
   and nothing in the duration decoding knows about the rhythm field.
3. **Against the firmware itself.** Feeding Jingle Bells to the real cartridge under emulation and
   capturing its YM2151 writes gives 194 melody notes and 234 obbligato notes. The static decoder
   reproduces **every one of them, in order, from the first** — similarity 1.000 on both parts.

Plus ground truth by ear on Silent Night, Edelweiss, This Masquerade, Bill Bailey, When You Wish
Upon a Star and others, and a transposition check across the whole corpus.

---

## The patents

Yamaha patented this machinery in pieces through the early 1980s, a separate application for each
idea rather than one description of the system. The list below is every patent known to bear on the
Playcard, what each actually contains, and what it does to the findings above.

**To say it once more: none of this was used to decode the format.** Everything in this document
came from the ROM and the cards, and the patents were read at the end. Two of them turn out to
describe mechanisms that had already been worked out the hard way, which is worth something as
independent confirmation and nothing at all as a shortcut.

| patent | priority | what it is | bearing |
|---|---|---|---|
| **4,406,203** | Dec 1980 | *Automatic performance device utilising data having various word lengths.* Okamoto and Mizuno's **"01 coding method"**: a per-song table of note lengths, codeword length set by how often each is used, the decoder counting runs of like bits to the change | **Confirms the duration track.** That is the alternating-run prefix code and most-frequent-first alphabet described above, arrived at from `0x631E` |
| **4,387,620** | Nov 1980 | *…with main routine data and subroutine data.* Repeated passages stored as subroutines with call marks and returns; a **subroutine detecting pass** scans the stored data and catalogues addresses *before* playback; nesting explicitly allowed | **Confirms the repeat spans.** That is the back-fill pass `playcard_resolve.py` reproduces, and the nesting the corpus shows |
| **4,587,878** | Jun 1981 | *Automatic performing apparatus and data recording medium therefor.* Chord data as a **name recorded once** plus several **timing records** pointing at it, each timing an address into the melody note sequence | **Confirms the chord chart's shape**, and why only positions count against the 62 |
| **5,144,875** | Nov 1981 | *Music sheet.* The card itself: the strip carries "a melody, an obbligato, a counter melody and a chord", and the printed rhythm notation names **cymbals 1 and 2, a snare drum and a bass drum** | Names the parts this format carries, and its four percussion voices are four of the five the PCS-30 strikes. No encoding at all |
| **4,402,244** | Jun 1980 | *…with tempo follow-up function.* A late key depression **halts the accompaniment until the key arrives**, an early one runs fast to catch up, and the guide melody sounds quieter | Corroborates free tempo as behaviour. A different product, so not proof of this one |
| **4,413,545** | Jul 1980 | *Music data reading type electronic musical instrument.* The idea of a strip on a music sheet | Nothing about the format |
| **4,466,324** | Dec 1980 | *…of electronic musical instrument.* Panel switches overriding recorded control data; melody as 6-bit pitch and 6-bit duration words, chords as 6-bit roots | A different encoding from this one |
| **4,454,797** | | *…* Practising between a chosen start and end measure; 8-bit words of a 2-bit tag plus payload | A different encoding again |
| **4,378,720** | Sep 1979 | *…having musical performance training system.* Key lighting; 8-bit words tagged `10` melody, `01` chord, `00` duration, `11` finish | The ancestor of the tagging idea, not this format |

### One claim in the family does not hold for these cards

4,406,203 says the pitch data of music not in C is **stored transposed to C**, with a key
instruction put back at playback. That is a real feature of the device it describes, and it is
tempting to carry over — it would explain the key field neatly. It is not what these cards do,
and what they do instead is more interesting.

**The melodies are written on the white keys, and the key field moves them.** Counting black notes
rather than guessing at scales, because a tune with a flat seventh reads as its own subdominant and
makes a best-fit test lie:

| | cards | black keys as written | as the machine plays it |
|---|---:|---:|---:|
| key field asks for no shift | 156 | 3.0% | 3.0% |
| key field asks for a shift | 105 | **4.9%** | **13.0%** |

A card that is never transposed is 3.0% black keys and stays there. A card that IS transposed is
just as easy on the hands as written — 4.9% — and four times as hard once it sounds. **Of the 94
cards moved by a fourth, 63 have a written melody under 5% black keys.** That is not a storage
convention normalising everything to C; it is somebody entering the tune in the key that is easiest
to play and then telling the card where it really belongs.

The chords are not moved with it, and do not need to be: they are stored at **sounding** pitch
already, so a card carries its melody in the convenient key and its chords in the real one.

#### The cards are not all written in C

The white keys are a **key signature**, not a key, and the difference matters because it is easy to
state this finding one step too strongly. The seven white notes are C major, but they are equally
A minor, G mixolydian, D dorian and four other modes; a melody that never touches a black note has
told you what it cost to store and nothing at all about its tonic.

Measuring the tonic needs a witness the key field does not touch, and there is exactly one: the
chord chart, stored at **sounding** pitch. Songs cadence to the tonic, so the chart's last chord
names the key the card sounds in — which agrees with the melody's own last note on **211 of 261**
cards. Subtract the shift and the written key falls out:

| the melody as written | cards | | the card is written in | cards |
|---|---:|---|---|---:|
| cheapest with no sharps or flats | 243 | | C | 203 |
| needs a signature with one or more | 18 | | A minor | 36 |
| | | | G, A, D, D minor, F, E | 22 |

**So "written in C" is right for 203 of the 261 and wrong for 58**, and where it is wrong it can be
wrong by a fourth. The rule is not C. The rule is *whatever is cheapest to write down*, which is
nearly always the white keys and is a different statement.

Two cards make the distinction concrete, and both are cards where reading C into the field gives an
answer a listener can hear is wrong:

| card | field | written in | sounds in | naming the field's shift from C would say |
|---|---:|---|---|---|
| PC-100 *9 to 5* | 6 (+5) | **G** | **C** | F |
| PCS-30 *Summertime* | 9 (−5) | **D minor** | **A minor** | G |

*9 to 5* is a blues melody with a flat seventh: written in G it uses F♮ 29 times against F♯ 6, so
it sits on the white keys while being in G and not in C. Shifted up a fourth it sounds in C, with
that flat seventh now B♭ — which is what makes its "as played" black-note count 29 of 165 without
its being in a black-key key at all. Its chart ends `Dm7 · G7 · F · C`, and its melody ends on C.

*Summertime* is written in D minor — D dorian, so again no accidental in the signature — and its
chart ends `E7 · Am · D · Am`, the dorian cadence, with the melody ending on A.

Neither card is unusual, and neither is broken. `key_field_check.py` measures all of it, and will
print any card you name.

**The shift is doing musical work, and it can be measured.** Asking what fraction of melody notes
are tones of the chord sounding under them:

| | cards | as written | as played |
|---|---:|---:|---:|
| key field asks for no shift | 156 | 74.0% | 74.0% |
| key field asks for a shift | 105 | **37.2%** | **70.3%** |

Applying the shift takes the transposed cards from nonsense to very nearly the corpus average, and
improves **101 of the 105**. Whatever the key field is for, it is not decoration.


#### Why not simply write it in the right key? For eighteen cards, it would not fit

The obvious objection to all this is that transposing the notes once, before they ever reached the
strip, would have cost nothing and saved the confusion. It would not have cost nothing.

**An accidental costs an opcode.** A sharp is a modifier of its own that precedes the note it
alters, and a flat is spelled as the sharp of the letter below — so every black note in the stored
stream is an extra opcode that a white note does not need. A melody written on the white keys is
therefore *smaller* than the same melody written where it sounds, and the strip is 433 bytes with
**37 of the 267 cards within four bytes of the end**.

Compiling each transposed card both ways measures it: written where it sounds, the 105 cost **642
bytes** more between them, a median of 6 each and up to 45. Compression recovers some of it — 92
extra accidentals on California Girls cost only 45 bytes — but the direction never reverses.

Add that cost to each card's real size and **eighteen of the 105 no longer fit the strip at all**:

| card | as pressed | written where it sounds |
|---|---:|---:|
| My Heart Belongs to Me | **433** | 468 |
| Summertime (PCS-30) | 431 | 449 |
| What Kind of Fool | 430 | 447 |
| Autumn in New York | 431 | 445 |
| Weekend in New England | 431 | 444 |
| Pennsylvania Polka | 429 | 444 |
| My Love | 425 | 441 |
| Symphony No. 40 | 423 | 440 |
| California Girls | 395 | 440 |

and nine more besides.

My Heart Belongs to Me is *exactly* at the maximum as it stands. Writing it in its own key would
need 468 bytes onto a 433-byte strip. So the practice is not laziness and not an accident of who was
at the keyboard: on a full card it is the only way the song fits, and a field that already existed
for transposing performances paid for it.

That does not explain every one — the median card had room to spare and would have fitted either
way. But whoever set the house style had a reason, and it was a good one.

#### The PC-100 9 to 5, which looks wrong and is not

This is the card that raised the question, and it is worth following the whole way, because the
first answer to it was still half wrong.

The complaint: the card **sounds in C** — anyone can hear that — while its key field is 6, a fourth
up, which everything printed as "F".

Its melody is written almost entirely on the white keys, **6 black notes out of 165**, and the
temptation is to call that C and conclude the machine plays it a fourth higher, in F. It does not.
The melody is written in **G**: it ends on G, and its 29 F♮ against 6 F♯ are a flat seventh, not a
key of C. Move G up a fourth and you land on **C**, which is what the listener hears, what the
melody's last sounded note is, and what the chord chart says — `Dm7 · G7 · F · C`, stored at
sounding pitch and never touched by the field. The card, the field, the chart and the ear all agree
the moment the melody's own key is measured rather than assumed.

The rest holds up. As it sounds, the melody is **29 black notes out of 165**, because C with a flat
seventh needs B♭ — which is exactly the storage argument above, a fourth's worth of accidentals
saved by writing it in G. Agreement between melody and chords goes from 50% as written to 65% as
played, the corpus norm. And the shift itself was confirmed against the firmware rather than
argued: `csrc/playcard` playing the real card gives a melody matching the shifted decode on **165
of 165 notes**, and the untransposed decode on none.

So there was never anything wrong with the card, and the apparent contradiction — a melody in one
key and a chart in another — was ours: **we had assumed the melody was in C.**

## Superseded findings

**The statistics about the key field were wrong for two days; the tools never were.** Worth
separating carefully, because the first account of this said the opposite.

`parse_header` stores the key field the way the ROM reads it at `0x62C4`: **signed**, so codes 9 to
15 come back as -7 to -1. `key_shift()` indexes a table by note code, so handing it a negative value
found nothing and returned **no transposition at all**.

Every tool that converts a card — `midi_export.py`, `card_decompile.py`, `pcs30_arrange.py`,
`playcard_midi.py`, `swipe_to_card.py` — converts the field first, on the line above the call:

```
key = h['transpose'] if h['transpose'] >= 0 else h['transpose'] + 16
```

**So every card was always decoded, exported and arranged in the right key.** Checked rather than
assumed: `midi_export.py` on Jingle Bells, whose field is -7, matches the firmware on **194 of its
194 melody notes**.

What was wrong was the *analysis* scripts written to study the field, which passed the parsed value
straight in and so counted 50 transposed cards as untransposed. Every figure derived from them was
wrong: 206 cards unshifted against the true 156, 55 shifted against 105, and the agreement and
black-note percentages with them. Those are corrected in "One claim in the family does not hold";
anything quoting the old numbers predates this.

`key_shift()` now takes the field either way round, so the mistake cannot be made again, and
`key_against_firmware.py` checks all 105 against the cartridge. The lesson is about measurement
rather than about the format: **a corpus round trip cannot catch a transposition error**, because it
decodes and recompiles with the same function and agrees with itself whatever that function does.
Only the firmware is not a party to our arithmetic.


**The firmware has bugs, and one long-standing "finding" was one.** The chord dropout was recorded
here for weeks as an openMSX defect and is in fact the UPA-01's own — established by an emulator
written from scratch, `csrc/playcard`, reproducing it independently.

**The fill feel was a second one**, and getting there took three passes and two wrong turns: first
"1 and 2 are straight, 3 and 4 swing" as a property of the format, then — on finding the PCS-30
disagreed — a flat denial that any such split existed, then a corpus statistic that seemed to put
the cartridge back in the right. What settled it was one card somebody had actually listened to on a
PC-100. **Two machines disagreeing is a question, not a verdict**, a corpus statistic is a weaker
witness than a played card, and where the answer is genuinely unknown the honest entry is in "Still
open" rather than a tidy story.

Recorded because the wrong turns are informative, and to stop them being re-derived.

**The "nearest note" octave rule was my invention and is wrong.** For a long time octaves were
computed by placing each note nearest the previous one. It approximates the truth about 88% of the
time, which is exactly enough to look plausible and never be right. The cartridge uses a plain
octave register.

**Modifier 2 was briefly concluded to have no effect on pitch.** That fit was made while the repeat
structure was still broken, and the structural error corrupted it. With correct structure, modifier
2 is octave down — the obvious reading, wrongly rejected.

**The duration bit 7 was read wrongly twice.** First as a rest, which silently swallowed notes;
then as "ignore entirely", which produced spurious duplicates. It is a lift flag, and it must be
tested on the *preceding* event, not the current one. Three separate user-reported passages were
needed to pin this down; no single one distinguishes the cases.

**`playcard_expand.py`'s call/definition model was structurally right but could not know targets.**
It desynchronised 237 of 261 cards. Superseded by `playcard_resolve.py`.

**The key field's values were named as if they were keys.** The field is numerically a YM2151 note
code, and the note-code name was printed as the card's key — so field 0 came out as "C♯". It is a
transposition, not a name: field 0 is no transposition at all and its cards sound in **C**. The
note-code name sits a semitone above the key throughout, and the reading would have had 158 of the
267 cards published in C♯, which no one has ever done. The chord charts, which are stored at
sounding pitch and untouched by this field, say C, F and G for fields 0, 6 and 9. A listener spotted
it; nothing in the arithmetic was wrong, only the label on it.

**The key field was a hand-built table of three values.** Unlisted values silently defaulted to no
transposition, leaving eleven cards in the wrong key. A lookup table with a silent default was the
wrong shape for the problem; the note-code rule has no gaps.

**"The playback engine is not in this cartridge" was based on a bad premise.** The decoded track
buffer's literal address appears once, which proves nothing — buffers are reached through pointer
variables. Relatedly, the absence of a note-frequency table was taken as proof that pitch was
resolved externally; the YM2151 takes key codes, not periods, so there is no such table to find.

**The unplayable-root chart entries were called a second spelling of the accompaniment mute.** They
do silence the UPA-01 — that part was measured on the real firmware and stands — but silence is
that machine misreading them. The PCS-30's converter shows the convention: the root is the one
already sounding and the type nibble is ORed on. The corpus agrees, and decisively: every change one
of them makes adds a seventh, none moves the root, and not one of the 83 falls on a bar line while
`0xFF` mutes cluster 6 to 12 ticks after a downbeat. Reading a behaviour off one machine and calling
it the format was the error; the cards are older than that machine.

**Obbligato voice 2 was guessed as piccolo.** It is the flute (`FLUTE` on the SFG-01).

**The escape opcode's sub-values were all read as drum fills.** Value 7 is the one-bar
alternate-accompaniment switch. The name "fill" came from the count being 8 and nothing more; it
was never checked against a card whose accompaniment behaviour was known.

**Opcode `0x11` was read as the alternate-pattern selector.** The reasoning was that it is the
first opcode on cards that begin on that pattern and recurs 6–10× per song, which looked like
bar-by-bar selection. But it occurs on *every* card, 1978 times across the corpus, while only five
cards start on the alternate pattern — and those five have unremarkable `0x11` counts. The
selection is a header bit. A frequency that "looks about right" is not evidence when the control
appears everywhere.

**The accompaniment-pattern bit was called "a starting state, not a lock".** The ROM says otherwise:
the header expands its field to 3, setting bit 1 of `0xD352`, and the once-per-bar revert returns
early whenever bit 1 is set — so bit 0 can never be cleared and the alternate pattern is held for
the whole card.

The reasoning that led to "not a lock" was that cards exist which begin on the alternate pattern and
later change to the standard one, so something besides the header bit must be able to move it.
**The observation is correct; the inference from it was not.** When You Wish Upon a Star does exactly
that — alternate for bars 1 and 2, standard from bar 3 — but its header field is **0**, and it gets
there with a mark 7 on each of those two bars. It never engages the lock at all. Two mechanisms
produce the same opening effect, and only one of them is permanent; observing the temporary one says
nothing about whether the other can be undone.

**Chord notes vanishing mid-card was read as a format behaviour.** It is an emulation bug on this
openMSX/CX5M/UPA-01 combination, it affects original cards too, and it does not occur on real
hardware. See the note above; three cards were built and captured chasing it.

**Capturing the FM chip looked like a complete solution.** It produces melody, obbligato, chords,
bass and drums — but the chords drop notes, spurious drum hits appear, and tempo is wrong because
the capture cannot run at true speed. It is an excellent oracle and a poor converter.

---

## Still open

- **Why fill 2 appears on 90 of the 156 straight cards and on none of the 68 swing ones.** The
  feel is not the reason: the PC-100 and the PCS-30 both take it from the rhythm. Nor is it a habit
  of the keyboard's panel — **the PC-100 has no fill controls at all**, so these marks came off an
  authoring system about which nothing is publicly known. The split is that system's habit, or its
  operators'; the one testable guess left is that the patterns simply suit one feel better once
  swung.

- **The UPA-01's own bass and drum patterns.** The card selects and gates them but does not contain
  them; they live in the firmware's pattern tables. Everything the card contributes is now decoded
  — rhythm style, standard or alternate pattern, per-bar fills, and the two mutes — so a capture
  can be attributed to a fully known selection, which is what the pattern tables have to reproduce.
  The **PCS-30's** equivalent tables are now fully decoded (see above), which gives the shape to
  look for: ten rows in the card's own rhythm order, one byte per step as a 1-based semitone offset
  from the chord root, and separate tables for sevenths. The cartridge's are not those tables, but
  they are the best lead there has been.
- **Which PCS-30 fill each mark names.** The dispatch is settled and the mute is settled, but a
  table bit index is a storage slot rather than a fill number, so which of the six stored patterns
  is heard for a given mark is still only inferred — from metre, which puts the two four-beat fills
  on marks 1 and 2 and the four twelve-slot ones on marks 3 to 6, exactly as the corpus families
  predict.
- **The flag at `0xD356`** in the strict sense. Free tempo itself is no longer a mystery: `F5`
  selects it, `0xD222` records it, and the cartridge holds its own sequencer at `0x5B46` until the
  player plays the note — all of that is measured. But the flag is a different thing from the mode
  byte, and it is only ever *transmitted*: the one read of it clears a dirty bit and hands it out.
  What the keyboard does with it, and what makes the tempo follow the player once they have started,
  are still downstream of this ROM.
- **What the third ducked part IS**, `0xD349`, moved in step with the obbligato's `0xD324` by both
  opcodes. What it does on this cartridge is now answered, and the answer is nothing at all: its
  level is written and never read, on every card in the corpus, because the parameter pump is called
  exactly twice and the address `0xD326` appears nowhere in the ROM. What is left is the identity. **The PCS-30 cannot settle this**, and the
  reason is worth recording so it is not tried again: the two machines duck by different mechanisms
  entirely. The cartridge writes a level byte into three per-part parameter blocks of stride `0x25`
  and queues them outward; the PCS-30 keeps a single duck flag (bit 0 of `0x80D7`, mirrored into
  `0x80D1`) and uses it at `0x0F91` to add `0x10` - one 6 dB volume step - to the level it writes
  to the obbligato's channel (see "How deep the duck is depends on the machine"). There is no
  three-block structure on that machine,
  so it has no third part to name. `0xD349` belongs to the cartridge's model of the keyboard it
  drives, and only a keyboard that responds to it can identify it.
- **What a "same root" chart entry is FOR.** The convention itself is decoded, and the two machines
  that can be read disagree about it: the PCS-30 implements it, the cartridge does not and falls
  silent. What is still open is why an arranger would spend one of 62 chart positions on an entry
  that changes no harmony, which **61 of the 83 do**. The best available answer is a re-strike — they
  sit a beat before the next chord and pile into bossa-nova, which is where a pushed chord belongs —
  but nothing measurable distinguishes that from a cue to a player's hands. The **PC-1000's Chord
  Lesson** is the obvious candidate for such a cue and the distribution refuses it: none of its 27
  cards uses one, sixteen of the twenty-two users predate the machine, and an OR can never say
  *release*. Settling it needs a PC-1000 ROM, and no dump is known. That `0x03`, a major, never
  appears is probably the same fact from another side: with nothing to add, there is nothing to say.
- **A handful of notes.** A few cards may still differ in detail; the corpus has been checked by
  ear but not exhaustively against the firmware.

---

Published as an artifact at
<https://claude.ai/code/artifact/e6063145-4b64-4c52-a515-7aac466956c4>.
This file and that page carry the same content — update both together.
