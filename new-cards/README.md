# New Playcards

Seventeen Playcards **written in 2026**, from the format spec in `../playcard-format.md`, using the
encoder in `../playcard_encode.py`. As far as anyone involved knows they are the first new Yamaha
Playcards made since the format went out of use in the 1980s, and they are working cards: the
genuine UPA-01 firmware reads them, accepts their CRC and plays them.

None of what follows came from Yamaha's patents. The format was decoded from the ROM and the cards,
and the patents were read at the end only to check the result — see "The patents" in
`../playcard-format.md`.

They are also dummies. Each exists to ask **one** question that no original card could answer,
because no original card isolates the thing being asked about. A real arrangement does six things at
once; these do one thing and nothing else, sixteen bars of it, with a control on the same card.

**Which machine is being asked matters, and differs by card.** Most were put to the **UPA-01**
cartridge under emulation, because that is the machine that can be watched a byte at a time. Some
carry a `--wav` option that renders swipe audio for a **real keyboard**, which is the only way to
check a finding the cartridge might be getting wrong. Answers about *sound* rather than about
*bytes* are that machine's answers until a second one agrees — the UPA-01 is a 1985 port with at
least three known bugs, one of which cost three of the cards below. See "Which machine is being
described" in `../playcard-format.md`.

## The cards

| card | bytes | built by | the question it asks |
|---|---:|---|---|
| `playcard_new-01_fill-test_rock.bin` | 50 | `make_fill_test.py` | what are bar marks 4, 5 and 6? — rock, 4/4 |
| `playcard_new-02_fill-test_march.bin` | 50 | `make_fill_test.py` | the same card in march, as an independent check |
| `playcard_new-03_fill-test_waltz.bin` | 50 | `make_fill_test.py` | the same card in 3/4, which showed why the fills come in pairs |
| `playcard_new-04_chord-test_rock.bin` | 52 | `make_chord_test.py` | four bars each of chord type 0, 1, 2, 3 on one root: how is a chord voiced? |
| `playcard_new-05_pattern-test_header-set.bin` | 47 | `make_pattern_test.py` | header pattern bit set **and** mark 7 — the first card ever to combine them |
| `playcard_new-06_pattern-test_header-clear.bin` | 47 | `make_pattern_test.py` | its control, differing in that one field and the CRC |
| `playcard_new-07_pattern-test_single-mark7.bin` | 45 | by hand | one mark 7 and nothing else |
| `playcard_new-08_pattern-test_rechord.bin` | 50 | by hand | re-asserts the chord after a mark 7; built while chasing what turned out to be a cartridge bug, kept because re-asserting is the workaround |
| `playcard_new-09_chart-position-test.bin` | 279 | `make_chart_test.py` | sixteenths against whole notes, so one chart entry falls in bar 2 of the melody and bar 17 of the obbligato: where does a chord fire? |
| `playcard_new-10_unplayable-root-test.bin` | 70 | `make_mute_test.py` | the known mute and a chord on an unplayable root, alternating on one root: are they the same instruction? |
| `playcard_new-11_mute-hold-test.bin` | 99 | `make_mute_test.py` | all four values, each given four bars to lapse in: does the mute hold? |
| `playcard_new-12_lift-test_plain.bin` | 47 | `make_lift_test.py` | 28 notes, no pitch repeated, lift bit clear |
| `playcard_new-13_lift-test_lifted.bin` | 47 | `make_lift_test.py` | the same 28 notes with the lift bit set: is the bit free where nothing repeats? |
| `playcard_new-14_lift-test_lengths.bin` | 45 | `make_lift_test.py` | lifted events at four lengths: is the release a fixed gap or a fraction? |
| `playcard_new-15_fill-feel_rock.bin` | 50 | `make_swing_fill_test.py` | the six fills under a straight rhythm |
| `playcard_new-16_fill-feel_swing.bin` | 50 | `make_swing_fill_test.py` | the same six under swing: does a fill have a feel of its own? |
| `playcard_new-17_same-root-test.bin` | 118 | `make_same_root_test.py` | the same chords stated two ways at both phases of the pattern: does a same-root entry reset anything? |

All seventeen are in the repository, and the eight maker scripts rebuild fifteen of them byte for
byte — 07 and 08 were built by hand from `../playcard_encode.py`. See "Rebuilding them" at the end.

The sections below take the cards in order, each giving a card's design and what it answered.

Two scripts here build no cards of their own. `dropout_trigger.py` builds eighteen throwaway ones
to isolate the cartridge bug described under cards 05 to 08, and `capture_fills.py` plays a card on
the real firmware and writes an `.fmlog` of every YM2151 write, alongside a `.marks` report of every
write to the three bytes that say what the firmware DECIDED — the bar mark, the pattern state and
the live chord. Both run on `../csrc/playcard`; the openMSX harness they used to need is gone.
**The captures behind the findings below are not kept in the repository** — they are large, and
regenerating one is a single command:

```bash
python capture_fills.py playcard_new-01_fill-test_rock.bin
```

## Cards 01, 02 and 03: what bar marks 4, 5 and 6 are

### What the three cards contain

Sixteen bars of 4/4 at 100 bpm, C major held throughout, with one bar mark on beat 1 of every odd
bar from 3 to 13:

```
bar   1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16
mark        1     2     3     4     5     6
```

Marks 1, 2 and 3 were already known to be drum fills. They are on the card as the **control**: they
put three known fills in the same rhythm, on the same card, in the same capture as the three
unknowns, so 4, 5 and 6 are compared against something rather than against a memory of another
card.

Every mark has a plain bar either side, so a fill has a clean bar to play into and the pattern is
re-established before the next one arrives.

The melody sounds one C and then rests; the obbligato rests throughout and carries the marks, which
is where the firmware expects them — all 2030 marks in the original corpus are in the obbligato
stream and not one is in the melody stream. So after the first note, the only things sounding are
the accompaniment and the drums.

### What they showed

**Marks 4, 5 and 6 are further drum fills.** The spec had them down as "unidentified; by elimination
most likely further fills" — this is the first direct evidence, and it is now confirmed.

Building the bar grid from the mark events themselves rather than from the clock — they sit on beat
1 of known bars by construction — the six marks fit that grid to within ±4 ms. On that grid each
mark occupies exactly one bar and the plain pattern resumes in the next, which is what a fill
does.

None is a duplicate of another. Measuring pattern overlap between bars, the plain bars agree with
each other at **0.94**, while every marked bar sits at most **0.42** against a plain bar and at most
**0.51** against any other mark. Marks 4, 5 and 6 are as distinct from 1, 2 and 3 as those are from
each other. Both 4/4 cards agree.

#### Then the waltz card explained *why there are six*

Listening to the two 4/4 captures produced a prediction: the six fills are three pairs, one pair per
feel — 1 and 2 for straight rhythms, 3 and 4 for swing and slow-rock, 5 and 6 for waltzes. Sorting
every fill in the original corpus by its card's rhythm bears that out, and **fills 5 and 6 appear on
21 of the 37 waltz cards and on none of the other 224**.

The third card, the same test in 3/4, gives the mechanism. A fill is a **fixed pattern measured in
beats**, identical whatever rhythm calls it — mark 5 sounds at 0.09, 0.67, 2.59 and 2.67 beats after
the bar line in the rock card and at exactly the same four positions in the waltz card. What differs
is only how much of the bar is left:

| mark | length | in 4/4 | in 3/4 |
|---|---|---|---|
| 5, 6 | three beats | leaves beat 4 empty | **fits exactly** |
| 1–4 | four beats | **fits exactly** | truncated at the bar line |

So the waltz pair is a hard restriction — a 3/4 fill in a 4/4 bar leaves a hole, a 4/4 fill in a
waltz is cut off mid-phrase. The swing pair is not: 14 straight-style cards use 3 or 4, and 13 of
them also use 1 or 2, so they are cards reaching for a wider palette rather than a different one.

This also corrects the first reading above. Mark 5 was described as "sparser than a plain bar, a
break rather than a busier fill", and mark 6 as "back-loaded". Neither is true — that was a
three-beat pattern rattling around in a four-beat bar.

## Card 04: how the UPA-01 voices a chord

The fill cards raised a puzzle. Breakpointing the firmware's `0xE7` handler shows it receiving `8E`
— chord value `0x0E`, C major, exactly what the card encodes — and yet the accompaniment's two
chord channels get key codes C and D♯, a **minor** third. A listener hearing the same card called
the chord as C, E and G. Both could not be right.

The listener was right. Card 04 holds one root and steps through all four chord types, four bars
each, so that whatever differs between the blocks is the type and nothing else. What it establishes
is how **this cartridge** builds the four chords out of a YM2151 — the PCS-30 does it another way
entirely, and the PC-100's method is unknown. The card's own content is the same four values on
every machine; only the synthesis below is the UPA-01's. What differs is not
the key codes — those are **identical for all four types** — but the operator frequency multipliers.

Both chord channels run **algorithm 4**, two independent two-operator stacks, so each has two
carriers sounding independently. An operator sounds root × `MUL`, and `MUL` 4 : 5 : 6 is a just
major triad. ch3 is tuned to the root, ch4 three semitones above it:

| type | ch3 C1 | ch3 C2 | ch4 C1 | ch4 C2 | sounds |
|---|---|---|---|---|---|
| major | ×4 → C | ×5 → **E** | ×5 → G | *silent* | **C E G** |
| minor | ×4 → C | ×6 → G | ×4 → **E♭** | *silent* | **C E♭ G** |
| seventh | ×4 → C | ×5 → E | ×5 → G | ×6 → **B♭** | **C E G B♭** |
| minor 7th | ×4 → C | ×6 → G | ×4 → E♭ | ×6 → B♭ | **C E♭ G B♭** |

The seventh is gated by `TL` — 127, fully attenuated, for a plain triad. The root/minor-third key
code skeleton holds on original cards too: on Edelweiss the pairs are C2/D♯3, G2/A♯2, F2/G♯2, D3/F3,
E3/G3 and A2/C2, every one exactly three semitones apart, matching that chord's root.

Two things follow. **Chord quality is readable from a capture after all** — from `MUL` and `TL`,
never from `KC`, which says "minor triad" on every chord ever pressed. And chord types 1 and 3,
minor and minor seventh, which the spec had only inferred from progressions making harmonic sense,
are now confirmed directly.

**Absolute timing in a capture means nothing.** The two cards report different bar lengths despite
carrying the same tempo, and the emulator's own tempo control rewrites emulated time in a way that
is invisible afterwards. Everything above is built on the mark events, which are timestamped by the
same clock as the register writes, so the comparison holds regardless.

## Cards 05 to 08: the header pattern bit is a lock

There are two routes to the alternate accompaniment pattern — the header's 3-bit field, and bar mark
7 — and **no original card uses both**, since none of the five header-bit cards contains a single
mark 7. So what happens when they meet had never been heard by anyone.

Four cards went into this. Card 05 sets the header field to 2, the value all five originals carry,
and places mark 7 at bars 5, 7 and 9. Card 06 is byte-identical except for that field and the CRC
that covers it — four bytes in the whole image. Heard on the real firmware:

> the alternate pattern held for the entire duration … the accompaniment never switched back to the
> default pattern no matter what you did

The ROM says exactly that must happen, and the captured pattern-state writes show the mechanism:

| card | header write | at each mark 7 | revert at `0x6013` |
|---|---|---|---|
| 06, bit clear | `80` | `C1` — sets bit 0 | `C0` one bar later, three times |
| 05, bit set | `83` — bits 0 **and** 1 | `C3` — no change | **never fires** |

The once-per-bar revert reads bit 0, then reads bit 1 and *returns* if it is set. Bit 1 is the
header's, so setting the header field both turns the alternate pattern on and disables the only
thing that could turn it off. Mark 7 borrows the pattern for a bar; the header bit takes it and
keeps it.

Cards 07 and 08 came out of chasing the chord dropout below, and are kept because they are the
smallest statements of it: 07 is one mark 7 and nothing else, and 08 re-asserts the chord after the
mark, which is the workaround. Both were built by hand.

### The firmware bug that wasted three cards, and was misdiagnosed for weeks

While measuring the above, the accompaniment's non-bass chord notes were seen to stop partway
through and never resume, on both cards. It was written up here, and in `HANDOFF.md`, as a bug in
**openMSX**.

**It is a bug in the UPA-01 itself.** `../csrc/playcard`, an emulator written from scratch that
shares no line of code with openMSX, reproduces it exactly. Two independent emulators agreeing on a
behaviour drawn from the same ROM means the behaviour belongs to the ROM.

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

`new-cards/dropout_trigger.py` builds every one of those cards and prints the table.

The two observations that drove the wrong diagnosis were both correct: original cards do it too, and
real Playcard keyboards do not. They point at the *cartridge*, not at the emulator — a PC-100 is
not running this firmware. Assuming "the emulator" rather than "this machine's firmware" is what
cost three built cards and three captures.

The reading advice is unchanged, and now rests on something better: **trust the pattern state at
`0xD352` and the chord records at the `0xE7` handler, not the chord channels' key-ons.** Those are
what the card asked for; the key-ons are what the firmware managed to do with it.

## Card 09: where a chord chart entry actually fires

The chart's positions are opcode indices, and the cartridge walks the table on every decoded opcode
of **both** streams — so an entry at position *P* looked like it should also fire at the melody's
opcode *P*, at a completely different musical moment. Every original card places its chords by
obbligato index and tolerates whatever the melody's copy does; no card in the corpus separates the
two enough to tell.

This one does. Sixteenth notes in the melody give sixteen opcodes to the bar; whole notes in the
obbligato give one. An entry at position 17 therefore lands in **bar 2 of the melody and bar 17 of
the obbligato**. Breakpointing the `0xE7` handler at `0x5FC6` and playing it on the real firmware:

| what | when |
|---|---|
| the entry at position 1 | at the start, as either reading predicts |
| the entry at position 17 | **0.05 s before the obbligato's seventeenth note** |
| anything at the melody's opcode 17 | **nothing — 43 seconds of silence** |

**One entry, one chord change, at the obbligato's position.** The melody's copy never reaches the
handler. Read from the cartridge's own handler rather than the audio, so the chord-dropout bug
cannot touch it, and it is a local comparison, so the emulator's unreliable absolute timing cannot
either.

One trap this card taught, worth repeating: the first version gave its durations no **lift** flag,
so every run of equal pitches tied into one held note and the melody sounded twice a bar instead of
sixteen times. Opcode positions were unaffected, but the log was unreadable. If a purpose-built card
is meant to be *counted*, set the lift bit.

## Cards 10 and 11: the accompaniment mute, and the roots no chip can play

Two cards on one question, the second written because the first answered less than it looked like
it had.

### Card 10: two spellings of the accompaniment mute

47 chart entries across 22 original cards name a chord root on **note code 3** — one of the
YM2151's four unused values, and the same code the pitch stream emits for a rest, so the chord it
names cannot sound. The type nibble is valid on every one, so they are deliberate rather than
damage. No original card isolates one, so what the firmware made of them was unknown.

The card puts the unknown next to the known answer, in the same bar position, on the same root:

```
bar   1   2    3   4    5   6    7   8    9  10 11 12
     C   FF   C   33   C   FF   C   33   C   .  .  .
```

Bar 4 is bar 2 with one byte changed, and the whole five-bar figure runs twice so it can be heard
twice. There are no bar marks at all, so the drums run throughout and give an audible bar grid even
while the accompaniment is out; the melody strikes one C5 on each downbeat as a count. Neither
touches the accompaniment.

On the real firmware, counting key-ons per bar on the accompaniment's three channels:

| bars | chart entry | chord (ch3, ch4) | bass (ch5) | drums |
|---|---|---:|---:|---:|
| 1, 3, 5, 7, 9 | C major | 2 + 2 | 4-5 | 32 |
| 2, 6 | `0xFF`, the known mute | **0** | **0** | 31 |
| 4, 8 | `0x33`, the unplayable root | **0** | **0** | 31 |

**They are the same instruction.** The accompaniment stops dead in all four marked bars and comes
back on the next real chord, four times over, with the drums untouched.

The firmware's chord-dropout bug is ruled out three ways: it needs a mark 7 and this card carries
none, while this recovers four times; it leaves the bass playing, and here the bass stops too; and
it is not synchronised to anything on the card, while this is exactly aligned to the chart. Worth
stating, because that bug stops the chord voices, which is precisely what this card measures.

### Card 11: all three values, and does the mute hold?

Card 10 answered less than it looked like it did. It tested only `0x33`, and it never left a mute in
force for more than one bar before the next chord restarted the accompaniment — so it could not
tell a mute that holds from one that lapses on its own. Card 11 fixes both, with `0xFF` given the
identical treatment as the control:

```
bar    1   2  3  4  5    6   7  8  9 10   11  12 13 14 15   16  17 18 19 20   21  22 23 24
      C   FF  .  .  .   C   13  .  .  .   C   23  .  .  .   C   33  .  .  .   C   .  .  .
```

Each block is one bar of C major, then the value, then three bars carrying no chart entry at all.

| block | value | C major bar before | its four muted bars | drums |
|---|---|---:|---:|---:|
| bars 2-5 | `0xFF`, the known mute | 4 chord + 3 bass | **0** | 31-32 |
| bars 7-10 | `0x13` | 4 chord + 4 bass | **0** | 31-32 |
| bars 12-15 | `0x23` | 4 chord + 4 bass | **0** | 31-32 |
| bars 17-20 | `0x33` | 4 chord + 4 bass | **0** | 31-32 |

**Nothing sounds in any of the sixteen muted bars**, on any of the four values. The mute **holds**,
and the three unplayable values are indistinguishable from `0xFF`.

Bars 21-23 are what make it airtight. They carry one C major entry and then nothing at all, and the
accompaniment plays 4 chord and 4 bass key-ons in every one of them — so the silence in the muted
bars is caused by the mute, not by the absence of a chart entry, which is the only other thing those
bars have in common.

Each block's bar boundaries were taken from the two chart records that bracket it, so the reading
holds whatever rate the emulator was running at. That mattered: this capture ran at about 6.5x real
time and still gave a bar of 4.805 s in all four blocks, against 4.806 s in card 10's run at 0.75x.

**What this does NOT show is that these are mutes.** It shows what the *cartridge* does with them,
and the cartridge turns out to be the machine in the wrong. The PCS-30's converter reads an
unplayable root as "keep the root already sounding and OR this quality on", and the corpus backs
that: every change one of them makes adds a seventh, none moves the root, and not one of the 83 in
the corpus falls on a bar line, while `0xFF` mutes cluster 6 to 12 ticks after a downbeat. The
cartridge stores the value unaltered, its generator cannot voice root code 3, and the accompaniment
falls silent — which is exactly what these two cards measured. The cards carrying such entries were
pressed 1982-85; this cartridge is 1985. See playcard-format.md.

## Cards 12, 13 and 14: what the LIFT bit does when nothing repeats

Bit 7 of a duration symbol is a lift flag. Reading a card back it matters in exactly one situation
— an event repeating the previous pitch ties or strikes again depending on it — and nothing else in
the decode looks at it. That makes it appear *free* everywhere else, and free bits are worth bytes:
each distinct symbol costs 5 bits in the header and pushes every other codeword down a rank, so
letting a free event take whichever form of its length is already in the alphabet can save a symbol
outright. `midi_compile.py` did exactly that, and the cards it produced played wrong.

Cards 12 and 13 carry the same 28 notes, the same lengths, the same header, the same chart and the
same three-symbol alphabet, at 47 bytes each. **Not one note repeats the pitch before it**, so by
the reading above the bit is free on every single event and the two should be indistinguishable.

```
card 12    D4 E F G A B C5  x4, every duration 24          bit 7 clear
card 13    D4 E F G A B C5  x4, every duration 24 | 0x80   bit 7 set
```

They are not indistinguishable.

| | key down, as a fraction of each note's slot |
|---|---:|
| card 12, bit 7 clear | **99.6%** — held right up to the next note |
| card 13, bit 7 set | **83.2%** |

The control is in the same capture: the chord channels and the bass are identical to the
millisecond across the two cards, so the melody's duration symbols alone did it. The flag acts on
the playback path whether or not anything repeats the pitch, which is something reading a card back
can never reveal.

**Card 14** asks how the release is measured, since 4 ticks of 24 and a sixth of the event are the
same number. Sixteen lifted events at four lengths separate them:

| event | held | released early | fixed 4 ticks | a sixth |
|---:|---:|---:|---:|---:|
| 12 | 9.88 ticks | **2.12** | 8 ✗ | 10 ✓ |
| 24 | 19.98 | **4.02** | 20 ✓ | 20 ✓ |
| 48 | 43.97 | **4.03** | 44 ✓ | 40 ✗ |
| 96 | 92.04 | **3.96** | 92 ✓ | 80 ✗ |

Neither rule alone fits. **The release is 4 ticks early, or a sixth of the event, whichever is
less** — a lifted quarter sounds for 20 of its 24 ticks, a lifted eighth for 10 of its 12.

These are register captures rather than recordings, so the emulator's unreliability as a witness
for *audio* does not apply: the numbers are the firmware's own writes to the chip's key on/off
register. What they cannot rule out is a different keyboard behaving differently — this is the
UPA-01 ROM, and the corpus was pressed for the PC-100.

## Cards 15 and 16: do fills have a feel of their own?

Two cards a single field apart — `playcard_new-15_fill-feel_rock.bin` is rhythm 5, straight;
`playcard_new-16_fill-feel_swing.bin` is rhythm 3, swing. Sixteen bars of 4/4 at
100 bpm, C major throughout, one mark on beat 1 of every odd bar from 3 to 13, so
the same six fills play under two rhythms with nothing else changed.

What they show is that **the two machines disagree**, and the corpus decides
which is faithful.

The PCS-30's fill lookup is bank 1 with the fill NUMBER as the bit index: *there
is no rhythm in that lookup at all.* What makes a rhythm swing there is the grid,
16 steps to the bar straight and 12 swung, so the same table data lands on
sixteenths under rock and on triplets under swing — for all four fills equally:

```
rock    fill 1: 0.00 1.00 2.00 2.25 2.50 2.75
swing   fill 1: 0.00 1.33 2.67 3.00 3.33 3.67
rock    fill 3: 0.00 0.25 0.50 0.75 1.00 1.25 1.50 2.25 2.50 2.75
swing   fill 3: 0.00 0.33 0.67 1.00 1.33 1.67 2.00 3.00 3.33 3.67
```

The UPA-01 does not do that. On it each fill keeps its own feel whatever the
rhythm, which the card's owner hears plainly on these two cards.

**The PC-100 sides with the PCS-30, so the cartridge is simply wrong.**
*I Could Have Danced All Night*, from its own set, is a **disco** card carrying **mark 3** at bar
4.00, in the obbligato intro before the melody enters at bar 4.62: straight on a
PC-100, swung and wrong through the UPA-01. The same card uses fill 2 at bar
12.25, mixing both supposed families in one straight arrangement.

A corpus argument briefly pointed the other way — fill 2 appears on 90 of the
156 straight cards and on **none** of the 68 swing ones, which would follow if
picking the fill picked the feel. That card rules the explanation out, and the
lopsided habit is now unexplained, and cannot be a habit of the keyboard's
panel: **the PC-100 has no fill controls**, so a fill reaches it only from the
card. These cards came off an authoring system about which nothing is publicly
known. Worth remembering as a caution: a strong statistic lost to a single card
somebody had actually listened to.

What the cards did *not* settle is what the UPA-01 does with them. `diff_fill_feel.py`
plays both and prints the drum onsets, and the cartridge plainly treats the two
rhythms differently — the steady bars carry different patterns, and 501 onsets
against 425. But putting a fill's onsets on a bar grid needs a bar grid, and that
script does not yet get one: the card asks 100 bpm and the capture folds best at
95, with the phase wandering between runs. Its UPA-01 numbers are raw and no
verdict is drawn from them. A firmer anchor than one melody note — the
accompaniment's own downbeat — would fix it.

## Card 17: does a same-root entry reset anything?

Some original cards carry chart entries on note code 3, which no chip can play. They mean *keep the
root already sounding and OR this quality onto it*, and **two thirds of them change no harmony at
all** — they restate the chord that is already there. So the question is whether they do something
else: restart the accompaniment pattern, re-strike the chord, reset the bass phase. Nothing that
tracks only harmony could see it.

`playcard_new-17_same-root-test.bin` is ten four-bar blocks on one root, A. Each sets a chord on its
first bar and states a chord again two bars later, or one bar later, in one of the two forms:

| bars | | |
|---|---|---|
| 1-4 | A, nothing else | control |
| 5-8 | A, then **A7 spelled in full** at bar 7 | odd bar, real change |
| 9-12 | A, then **`0x23` same-root** at bar 11 | odd bar, real change |
| 13-16 | A, then **A spelled again** at bar 15 | odd bar, restating no change |
| 17-20 | A7, then **A7 spelled again** at bar 19 | odd bar, no change |
| 21-24 | A7, then **`0x23`** at bar 23 | odd bar, no change |
| 25-28 | A, then **A7 in full** at bar 26 | EVEN bar, real change |
| 29-32 | A, then **`0x23`** at bar 30 | EVEN bar, real change |
| 33-36 | A7, then **`0x23`** at bar 34 | EVEN bar, no change |
| 37-40 | A, nothing else | control |

The patterns are 32 steps — two bars — so the odd and even blocks put the second entry at opposite
phases. A melody note marks the first bar of each block, so they can be counted by ear.

**The PCS-30 has already answered, and the answer is no.** Running its chord path from an identical
machine, a fully spelled A7 and a same-root `0x23` leave all 32K of RAM identical byte for byte, and
so do a restated A7 and a `0x23` over it. That path writes two bytes and nothing else, and the
accompaniment step counter has four writers in the whole ROM, none of them in it. This card is for
the machines whose ROMs are not available — a PC-1000 above all.

**Do not expect it to play on the UPA-01.** That cartridge has no same-root convention and falls
silent on those entries, so blocks 3, 6, 8 and 9 stop dead. That is measured, and it is not what
this card is asking about.

## The card that is not here: a nonsense header

There was an eighteenth experiment, and it is not in this folder. A real Playcard with its header
fields set to values no genuine card carries, so that the cartridge would accept it and then be
unable to make sense of it — not an experiment in the format so much as one in the hardware, the
question being what a keyboard does with such a card. It was numbered 09 at the time, and that
number has since been reused.

**It cannot be published**, because it was a real Yamaha card with five fields changed rather than
a card of our own, and this repository carries no Yamaha card data. Rebuild it from any card you
own — tempo index 31 (200 bpm), rhythm 13 which maps to no style at all, melody voice 0 which is
off the end of the voice table, the key field on 7 which is one of the YM2151's unused note codes,
and all three bits of the accompaniment-pattern field set:

```bash
python ../header_edit.py card.bin -o nonsense.bin \
    --raw tempo=31 --raw rhythm=13 --raw melody=0 --raw key=7 --raw pattern=7
```

`--raw` clamps only to each field's width, so it writes values the musical options refuse, and
`header_edit.py` repairs the checksum itself — `../forge_crc.py` is for damage it cannot repair
that way, such as a card whose body has been altered.

The finding survives the card. **A header is safe to corrupt this way because every one of its
fields is fixed width** — rewriting them shifts nothing, so the card still walks and only its
values are absurd. The duration tracks and opcode streams are not fixed width: damaging those
changes their lengths, which moves every structure after them, and the file stops being a card at
all.

## Rebuilding them

Each maker script rewrites its own cards in place, byte for byte identical to the ones committed
here:

```bash
python make_fill_test.py            # cards 01, 02, 03
python make_chord_test.py           # card  04
python make_pattern_test.py         # cards 05, 06
python make_chart_test.py           # card  09
python make_mute_test.py            # cards 10, 11
python make_lift_test.py            # cards 12, 13, 14
python make_swing_fill_test.py      # cards 15, 16
python make_same_root_test.py       # card  17
```

That is all eight, covering fifteen cards; 07 and 08 have no script. Checked rather than asserted:
running all eight leaves every one of the seventeen images byte for byte as committed.

`make_mute_test.py --wav` also renders the swipe audio, for feeding a real keyboard through a coil
held against its head. That card in particular wants real hardware: what it measures is whether the
accompaniment stops, and the UPA-01 has a bug that stops the chord voices on its own.
`make_lift_test.py` offers `--wav` for the same reason.

`../playcard_encode.py` builds a card from a `Card` object and verifies its own output before
returning it — valid CRC, and durations pairing one-to-one with pitches. It caught a real defect in
the first version of these cards: a melody stream with no repeat marker never returns, so playback
walks straight on into the obbligato stream. No original card does that, which is why it had never
come up. `E.terminated()` is the fix and explains itself.
