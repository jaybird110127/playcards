# Handoff — Yamaha Playcard project

Read `playcard-format.md` for the format itself. This file is about the *state of the work*: what
is done, what is not, what will bite you, and how to verify anything you change.

**Naming, throughout both files:** unqualified, "the cartridge", "the firmware" and "the ROM" mean
the **UPA-01**, the 1985 MSX Play Card System cartridge, because it is the one whose code can be
read. The other machines — the **PC-100** the cards were written for, the **PCS-30** that is the
second implementation, the **PC-1000** — are always named. See "Which machine is being described"
in `playcard-format.md`, and remember that the cartridge is a witness rather than the format.

## Where things stand

**A card can now be played and heard without an emulator installed.** `csrc/playcard` runs the card
on an emulated CX5M — the real BIOS, the real cartridge, the real SFG-01 — and records every write
the firmware makes to the YM2151; `csrc/fmlog2wav` renders that through ymfm's YM2151 into a `.wav`.
A 90-second card goes from image to audio in under two seconds, at about 150x real time. Neither
program understands the Playcard format: the card is decoded by Yamaha's own firmware, so the result
is what the machine does rather than what we think it does. `msx_player.py` is the same machine in
Python at 79% of real time — slower, but it can stop and be asked what is in a byte, which is what
actually finds bugs. Both are kept, and `csrc/README.md` is the entry point.

That changed the project's centre of gravity. Questions that used to need openMSX, a Tcl harness and
a careful reading of a capture are now a command. Two long-standing "findings" turned out to be
firmware bugs once a second, independent emulator existed to disagree with the first — see
"Superseded findings" in `playcard-format.md`, and treat *this cartridge is a buggy 1985 port* as a
live possibility whenever the UPA-01 is the only witness.

The card format is decoded. All 267 cards pass their CRC, and the static decoder reproduces the
melody and obbligato **note for note against the real firmware** — 194 and 234 notes on Jingle
Bells, similarity 1.000, every note in order from the first.

Both formerly unknown header fields are now identified: the 1-bit field is **sustain** and the
3-bit field selects the **alternate accompaniment pattern**. The section table's values are decoded
too — they are the **chord chart**, `(type << 4) | note code`. All confirmed against the firmware
or the user's ear, not inferred. See `playcard-format.md`.

**264 cards export to MIDI**, each with three tracks: melody, obbligato and chords, with the
obbligato's notes dropped to velocity 75 wherever the card ducks it under the melody — 80.6% of all
obbligato notes in the corpus, across 249 cards. The only files
that do not produce a `.mid` are the three `_side-b` continuations, and those are not skipped so
much as absorbed — a two-sided card is written once, from its side A, under the name with the side
suffix dropped. Side A holds the durations and side B the pitches.

The drum and accompaniment **mutes** are decoded too, and they use different mechanisms: drums are
silenced by bar-mark value 0, the accompaniment by chord-chart value `0xFF`. That is why a card can
mute one without the other.

The **three control opcodes are solved**. `0x14` ducks the obbligato when the melody enters and
`0x13` restores it when the melody finishes — confirmed in the ROM at `0x5F8B`, in a YM2151 capture
(the obbligato carrier's Total Level stepping 34 → 36 → 34 within 45 ms of each opcode), and across
the corpus, where all 484 `0x14`s have the melody sounding in the two bars after them. `0x11` bumps
a counter at `0xD360` and marks the **passage divisions** used by the keyboard's repeat-practice
feature — 84.3% of its 3109 occurrences land exactly on a melody note onset against 41.3% on a
bar line, exactly one of the 3109 falls part-way through a melody note, and there are 4 to 20 per
card and never more. Like `0xD356` it is queued outward and read back only by the routine that sends
it, so the reading rests on the instrument plus the corpus rather than on the ROM.

They are **assertions, not brackets** — `0x14` is restated at every melody re-entry, the same idiom
as bar-mark 0 for the drums, and only 69.8% of cards alternate. The pair also sets a held flag at
`0xD356` (1 on `0x14`, 0 on `0x13`) which the cartridge reads only to send onward: it belongs to
**free tempo**, the mode where playback waits for the player's note and follows their speed.

**Free tempo is the cartridge's own, and `F5` starts it.** `csrc/playcard --f5` presses F5 rather
than F2, and the card plays its introduction and stops dead at the first melody note — Edelweiss
119 key-ons against 1375, the hold beginning 22 ms after the `0x14` that marks the melody's entry.
`0xD222` is the play mode, **1** for F2 and **3** for F5, written at `0x5918`; `0xD225` carries the
note now due with bit 7 set; `0xD2AA` is the hold flag. The test is `CP 3` at `0x5B46`, and the
sequencer's own entry at `0x59CC` turns straight back while the hold flag is set — 1071 times on
one card. It never releases, because releasing it needs a note from the music keyboard, which is the
one part of this machine not emulated.

What is still downstream of this ROM is the *following*: once the player has struck the note, what
makes the tempo drift to match them, and what the keyboard does with `0xD356`.

The **strip encoding is decoded and both directions work**. Cards are written in F2F, the same
self-clocking code as a magnetic stripe: a long gap between flux reversals is a 0, two short gaps
are a 1, framed as `<31 zeros> 1 <card image> <~1400 zeros>`. The reference recording of a genuine
Silent Night swipe decodes **byte-for-byte identical** to the known image, and all 267 originals
plus all 17 new cards round-trip through audio unchanged. Self-clocking matters: that one swipe
drifts 25% in speed from one end of the card to the other, so track the cell period, never assume a
fixed bit rate.

The **24-bit trailer is solved**: it is a date, stored least-significant field first as `F` ·
day-units · day-tens · month · year · `F`, with year 2 = 1982. Reverse the six nibbles and it reads
as an ordinary date. All 267 decode to real calendar days, 1982-05-14 to 1985-12-27, and only 9 of
267 fall on a Sunday. It is per *date*, not per card and not per set — cards from different sets
sharing a date carry identical trailers. **Which** date is not established: it may be when the card
was physically made, or when its data was authored or compiled. Do not call it a pressing date.

**Not done:** the UPA-01's bass and drum *patterns* themselves. The card selects and gates them but
does not contain them — the firmware generates them from rhythm pattern tables, probably in the
SFG-01 ROM or the cartridge. That is the one substantial piece of work left on the cartridge.

**The two machines disagree about the unplayable-root entries `0x13`, `0x23` and `0x33`.** They are
**not a second spelling of the mute** — see the fuller account below, and `playcard-format.md`. The
PCS-30's chord converter at `0x28BA` translates the chart value through a table at `0x28E3` indexed
by `value + 1` — which independently confirms the note-code mapping, 12 of 12 — and the chip's
unused codes 3, 7 and 11 map to `0xFF` there, meaning **do not update the root**. So on the PCS-30
such an entry keeps the chord's root and merely ORs the new type on, while `0xFF` proper sets the
root to `0x0F`, that machine's own "no chord". Run with `z80run.py`: over a sounding G7, `0x23`
gives back G7 unchanged. On the cartridge they silence the accompaniment instead, measured on real
firmware — that machine has no such convention and cannot voice root code 3.

**Two thirds of them change no harmony at all, and that is the open part.** Of the 83 in playback
order, **61 leave the sounding chord exactly as it was**; the other 22 add a seventh. The two halves
behave differently: the inert ones sit a median **one beat** before the next chord and are 20/61
bossa-nova, which is a **re-strike**, a chord pushed ahead of the beat. Each one still costs a chart
position out of 62 — Someday My Prince Will Come is at 61 of 62 and spends two of them this way —
so they are not idle bytes. `same_root_entries.py` measures all of this, and a card at a time.

**Nor do they reset anything, at least on the PCS-30.** The next guess after the chord-lesson one
was state: that restating a chord might restart the accompaniment pattern or the bass phase where
leaving it alone would not. Run rather than reasoned about — the converter at `0x28BA` and the latch
at `0x1E60`, from an identical machine, then all 32K of RAM compared — **a fully spelled A7 and the
same-root `0x23` leave the machine identical in every byte**, and so do a restated A7 and a `0x23`
over it. The chord path writes two bytes and nothing else, and the step counter at `0x8038` has four
writers in the whole ROM, none of them in that path. `new-cards/playcard_new-17_same-root-test.bin`
puts the question to a real keyboard: the same chords stated both ways, at both phases of the
two-bar pattern.

**The patents were read at the END, and nothing here came out of them.** Say so when publishing:
the format was decoded from the ROM, the card images and the instruments, and the patent family was
read afterwards to see whether it agreed. `playcard-format.md` has the full list of nine with what
each contains. The three that matter confirm findings already made — **4,406,203** the duration
code (Yamaha's own name for it is the "01 coding method"), **4,387,620** the repeat subroutines and
the detecting pass before playback, **4,587,878** the chord chart's name-once-plus-timings shape —
and **5,144,875** names the parts a strip carries, obbligato included. One claim of the family is
**false for these cards**: 4,406,203's "everything stored transposed to C". What the corpus does
instead is better: **melodies are written on the white keys and the key field moves them.** A card
that never transposes is 3.0% black notes as written and as played; the 105 that do transpose are
4.9% as written and **13.0%** as played, and 63 of the 94 moved by a fourth are under 5% as written.
Melody-against-chord agreement on those 105 goes from **37.2% to 70.3%** when the shift is applied,
better on 101 of them, so the field is doing real work.

**The key field is signed on the way out of the parser, and the analysis scripts forgot it.**
`parse_header` stores it as the ROM reads it (`0x62C4`: codes 9-15 come back as -7 to -1) while
`key_shift()` wants the note code, so a negative field silently meant "no transposition".

**The tools were never affected.** `midi_export.py`, `card_decompile.py`, `pcs30_arrange.py`,
`playcard_midi.py` and `swipe_to_card.py` all convert on the line above the call and always did —
`midi_export.py` on Jingle Bells, field -7, matches the firmware on 194 of 194 notes. What was wrong
was the scripts written to *study* the field, and every statistic they produced. `key_shift()` now
accepts either form — **hand it whichever you have** — and `key_against_firmware.py` checks all 105
transposed cards against the cartridge.

The lesson is about measurement rather than the format: a corpus round trip cannot catch a
transposition error, because it uses the same function in both directions and agrees with itself
whatever that function does. `csrc/playcard` can, because the cartridge is not a party to our
arithmetic. **When a measurement about pitch surprises you, check it against the firmware before
believing it, and before writing it down.**

**And there is a reason for it, not just a habit.** An accidental costs an opcode of its own —
a sharp modifier precedes the note, and a flat is the sharp of the letter below — so a melody on
the white keys is smaller than the same melody where it sounds. Compiled both ways the 105 cost 642
bytes more written in their own keys, and adding that to each card's real size, **eighteen of them
no longer fit the 433-byte strip**. My Heart Belongs to Me is exactly 433 as pressed and would need
468. So on a full card, writing in C and transposing at playback is the only way the song fits.

Do not measure this with a best-fit-major-scale test — a tune with a flat seventh reads as its own
subdominant and the answer comes out wrong. Count black notes, or count chord tones.

**The patents have been read, and neither settles it.** US 4,587,878 (Nippon Gakki, priority 1981)
covers the ancestor of this chord chart and confirms its shape from outside the ROM: a chord name
recorded once, then several timing records pointing at it, the timings being addresses into the
melody note sequence. That is exactly the `code == 15` value record plus position records here, and
it is why only positions count against the 62. It is *not* this format — 6-bit melody notes of two
octave bits and four note bits, no obbligato, no bar marks, timings indexing the melody rather than
the obbligato — and it says nothing about unplayable root codes, nothing about changing a type
while keeping a root, and nothing about a lesson mode. **Do not read it again hoping otherwise.**

US 4,402,244 (priority 1980) is the other one worth knowing about: it describes tempo follow-up in
Yamaha's own words — a late key depression **halts the accompaniment until the key arrives**, an
early one runs the sequencer fast to catch up, and the guide melody sounds at reduced volume. That
is the behaviour the card's owner describes for free tempo, from the right era, though the device in
it is a different product and it is corroboration rather than proof.

**The PC-1000's Chord Lesson was weighed as an explanation and does not fit.** The idea was good:
that machine holds the accompaniment until the player fingers the chord, and "keep the root, add
this quality" is shaped like an instruction to a pair of hands — on single-finger chording the type
nibble is exactly which extra key sits beside the root. But **none of the 27 PC-1000 cards uses
one**, sixteen of the twenty-two that do predate the machine's late-1983 release, the twelve Step by
Step teaching cards use none, and an OR cannot clear a bit so the convention can never say *release
a note*. All 22 users are in the 17-5xx album series. Shaped like a cue, distributed like a habit;
**do not re-derive this without a PC-1000 ROM**, and none is known to exist.

**A card carrying one plays differently on the two machines.** The tools follow the PCS-30, because
that is what the entry *means*: `card_decompile.py` writes the resulting chord out in full, and a
recompiled card states it as an ordinary chart entry. It therefore plays the same on either machine,
which the original does not. The PCS-30 also has **no 62-entry ceiling** — it stores the chart as
byte pairs in a span with no counter, so that limit is the cartridge's alone.

**But the PCS-30 keyboard's equivalent tables are decoded in full** (2026-08-20), out of
`Roms/PCS-30.rom`, statically — that machine has no working emulator anywhere. Eight tables of 320
bytes at `0x2D26`, ten rows of thirty-two, addressed `base + rhythm*32 + step`. The ten rows are the
**card's own rhythm numbering**, proved independently by metre: exactly swing, waltz and slow-rock
fill 12 of 16 steps. A byte is a **1-based semitone offset from the chord root**. The live chord is
one byte at `0x8043` — root in bits 0-3, **minor** bit 4, **seventh** bit 5, which is the chord
chart's own type encoding. Minor flattens a degree in place (`0x16E3`); **seventh switches to a
different table** (`0x1620`), and those tables walk the bass up toward the chord a fourth above with
no lookahead. `pcs30_rhythm.py` renders any of it. This is not the cartridge's data, but it is the
shape to look for.

**Its drums are decoded too.** Separate table at `0x2BBC`, laid out by *bit-plane*:
`0x2BBC + plane*0x40 + bank*0x20 + step` (`0x1274`), five planes, and the *bits* of each byte are
the patterns. Bit *b* of all five planes assembles a 5-bit strike mask (`0x142F`) written straight
to the YM2142 at `0xE030` (`0x077C`) — **the drum sounds are in the chip, not the ROM**. Voices:
bit 0 kick, bit 1 latin (son clave in rhumba/bossa), bit 2 snare, bit 3 cymbal long, bit 4 cymbal
short — one cymbal struck short or long, not two. Every pattern is two bars. `pcs30_drums.py`.

**Its mark dispatch** (by running the ROM with `z80run.py`): mark n sets bit (3,2,1,0,5,4,6,7)[n]
of `0x80CF`; bits 0-5 are the fill selector, bit 7 the alternate pattern. **A bit index is a storage
slot, not a fill number** — do not infer from it which fill sounds, which is exactly the mistake made
and retracted on 2026-08-20. A card cannot know which keyboard reads it, so no reading that makes
two machines number the same mark differently can be right. The card reader does not alter the
values (`0x0486`, `0x25D3`). With the remap applied the two machines agree completely: **card mark 0
sets bit 6, which reaches `0x129F` and clears the pending drum strike — the drum mute**, card marks
1 to 6 are the six fills, card mark 7 is the alternate pattern. Confirmed end to end by running
I Write the Songs through the ROM (`pcs30_drums.py --card`): drums muted on bars 1-4, 11, 19, 20 and
21 and playing everywhere else, which is exactly what that card is documented to do on the
cartridge.

**The PCS-30's three built-in demos are decoded card data**, not card images: the exact RAM image a
swipe produces, at `0x80DA`, with the twelve span pointers precomputed. Its Nocturne demo is 32 of
32 notes identical to `pcs-30_nocturne.bin`. `pcs30_demo.py` extracts them.

**Also settled, and newer than most of the above:** a chord chart entry fires **once, at the
obbligato's opcode index** — the melody stream's copy never reaches the handler, proved on the real
firmware with `new-cards/make_chart_test.py`. And the repeat spans are understood well enough to
*write* as well as read: the body is the tail after the last marker, and a track carrying any marker
needs two terminators. Both are in `playcard-format.md`.

**The MIDI round trip is built, compressed and measured** (2026-08-22). `card_decompile.py` writes a
card as a four-channel MIDI file — melody, obbligato, chord chart, and control notes for the bar
marks, the duck opcodes and the accompaniment mute — with the header in a text meta event.
`midi_compile.py` takes that back to a card image, finding repeat spans as it goes. Decompiling all
264 cards, recompiling and comparing what a player hears:

| part | matches |
|---|---|
| melody | **264 / 264** |
| obbligato | **264 / 264** |
| chords | **264 / 264** |
| control events | **264 / 264** |
| **every part at once** | **264 / 264** |

**Nothing fails.** Every card decompiles to MIDI and compiles back to a card that plays exactly the
same music.

On size, against the 433-byte strip:

| | |
|---|---|
| **cards that fit** | **264 of 264** |
| one-sided originals | **261 of 261** fit on one side, and **every one** comes out smaller |
| against the original card | median **-33 bytes**, best -89, worst -2 |
| compression saves | a median 169 bytes a card, up to 618 |

**Every card Yamaha fitted on one side now fits on one side, and every one is smaller than the
original.** The three two-sided originals come out smaller too, and one of them no longer needs two
sides at all:

| | Yamaha | here |
|---|---|---|
| `pc-1000-japan_1-09` | 190 + 360 | 180 + 328 |
| `pc-1000-japan_2-08` | 161 + 379 | 133 + 368 |
| `pc-1000-japan_2-01` | 148 + 301 | **367 on one side** |

The playable ranges are **melody G3-C6 and obbligato G2-C6**, measured off the corpus rather than
assumed — 42083 and 42115 notes span exactly those, with nothing outside and no stragglers near
either edge. `midi_compile.py` folds a note beyond an end by octaves until it fits, which keeps its
pitch class. (`midi-roundtrip-design.md` originally guessed C2 for the obbligato; the corpus says
G2.)

Two format insights got it there, rather than compressor tuning — and a third that looked like a
third was **withdrawn**, because it was audible:

* **Nesting.** 897 of 897 multi-span structures in the corpus nest one span inside another. Searching
  the sequence the *previous* round produced, rather than the flat one, allows it.
* **The chord chart is grouped by VALUE, not sorted by position.** The table pays ten bits a
  position plus ten every time the value changes, and the firmware scans the whole table, so order
  is free. Grouping collapses the value records to one per distinct chord. Worth 40 bytes on a busy
  card, and it took thirteen cards under the limit on its own.
* **Withdrawn: the lift bit decides tie against re-strike, and nothing in the decode reads it
  elsewhere — but it is NOT free there.** Spending the apparent freedom to save alphabet symbols makes the card play
  *staccato*, and this is **measured, not inferred**: two cards differing in that bit alone hold the
  key for 99.6% and 83.2% of each note's slot, with the accompaniment identical to the millisecond.
  The release is 4 ticks early, or a sixth of the event, whichever is less. Yamaha agrees — bit 7 is
  set on 57.7% of the notes a repeat follows, 2.8% of the ones it does not, and 0 of 20757 rests.
  `midi_compile.py` sets it only where a tie has to become a re-strike; the alphabet costs a symbol
  here and there and it is worth it. `new-cards/make_lift_test.py` builds the cards.
* **Renderers have to apply that release; the round trip must not.** `midi_export.py` and
  `pcs30_arrange.py` pass `articulate=True` to `build_part` and shorten 16.7% of the corpus's notes,
  which is what stops a rendering sounding legato throughout. `card_decompile.py` passes nothing:
  its MIDI has to compile back, and a shortened note would build a different card.

Two format findings came out of building it, both now in `playcard-format.md`. **The section table
holds 62 entries, not 63**: the loop at `0x6454` stops on its counter without reading the
end-of-table marker, so a 63-entry table misparses everything after it — and the largest chart in
the corpus is exactly 62. And **47 entries across 22 cards name a chord root on note code 3**, one
of the YM2151's unused values, which cannot sound.

That second one is now **decoded, and it reversed an earlier reading of mine.** They are **not
mutes**: they mean "the root already sounding, with this quality ORed on". The PCS-30's converter
implements exactly that (`0x28BA`, run with `z80run.py`), and the corpus agrees four ways — every
change one of them makes adds a **seventh**, none moves the root, 61 of 83 produce the chord already
sounding, and **not one of the 83 falls on a bar line** while `0xFF` mutes cluster 6 to 12 ticks
after a downbeat. They are placed nothing like mutes.

The UPA-01 *does* silence the accompaniment on all of them — that was measured on the real firmware
with `new-cards/make_mute_test.py`, and it stands. But silence is that machine misreading them: the
handler at `0x5FC6` stores the value unaltered and the generator cannot voice root code 3. The 22
cards carrying these were pressed 1982-85, against a 1984 keyboard and a 1985 cartridge, so **the
machine they were written for is the one that cannot be checked here.**

`card_decompile.py` now writes the chord out in full rather than as a mute — that is what the entry
means, it plays the same on either machine, and a recompiled card no longer needs the reader to know
the convention.

**Tooling added since the format work finished:** `make_test_midi.py` (a MIDI that never was a
card, for testing the compiler on new material and on pieces needing two sides),
`make_random_card.py` (valid cards with a fresh structure each, for exercising a keyboard), `pcs30_arrange.py` (a card to a five-part MIDI
arrangement with the PCS-30's accompaniment), `z80run.py` with `z80run_test.py` (run a ROM routine
instead of reading it), and `midi-roundtrip-design.md` (the plan for compiling cards from MIDI,
now fully implemented).

## Who you are working with

The user is blind and uses a screen reader. **openMSX's GUI is unusable for them.** Everything must
be driveable and readable as text — that is why `msx_screen.tcl` exists (it dumps the MSX screen as
plain text) and why the tools print rather than display.

They know these cards intimately from real hardware and are the authority on what a card *should*
sound like. Their ear has caught every remaining bug in this project, and each specific passage
they reported led straight to a real defect. When something sounds wrong, ask for a concrete
passage — notes and where — rather than guessing.

## The layout

Two folders hold Yamaha's material and are **not in the repository**, because the cards and the
firmware are not ours to publish. Everything else is.

| Folder | What goes in it | Published |
|---|---|---|
| `Original Playcards/` | the 267 genuine card images | no |
| `Roms/` | UPA-01 cartridge, SFG-01/05, PCS-30 keyboard | no |
| `new-cards/` | the seventeen cards written in 2026, and their maker scripts | **yes** |
| `Sample Playcards/` | cards written as MIDI and compiled, kept as worked examples, and the guide to writing one | **yes** |
| `midi/` | what `midi_export.py --all` writes | no |
| `pcs30-midi/` | what `pcs30_arrange.py --all` writes | no |
| `examples/` | sample arrangements to listen to | no |
| `random-cards/` | what `make_random_card.py` writes | no |

Nothing hard-codes those paths any more. `playcard_decode.py` resolves them, and the environment
variables `PLAYCARD_CARDS` and `PLAYCARD_ROMS` override either one, so a checkout with the cards
somewhere else still works:

```bash
PLAYCARD_CARDS=/mnt/cards python playcard_resolve.py
```

Every corpus-wide tool goes through `P.corpus()`, and every ROM reader through `P.rom()`. Both
raise `P.Missing`, whose message says which folder is absent and why it is not shipped — so a fresh
clone fails with an explanation rather than by quietly finding zero cards. That last failure mode is
what the reorganisation originally caused: `playcard_resolve.py` printed `0 of 0 cards still
desynchronise`, which looks like a pass.

## The files

| File | What it is |
|---|---|
| `playcard_decode.py` | Parses a card: header, alphabet, duration tracks, opcode streams, CRC. `--all` for a table of every card |
| `playcard_resolve.py` | Reproduces the cartridge's repeat back-fill, giving true playback order. Run bare to check all cards still synchronise |
| `midi_export.py` | The deliverable: melody + obbligato + chords to MIDI, joining two-sided cards. `--all` regenerates everything |
| `playcard_expand.py` | **Superseded.** The old guess-the-targets expander. Kept for reference only — do not build on it |
| `card_to_midi.py` | Captures the FM chip while the firmware plays. Superseded for melody/obbligato, but still the only route to the accompaniment |
| `play_card.py` | Plays a card on the emulated MSX with sound; `--wav` captures audio |
| `fake_cr01.tcl` | Stand-in for the CR-01 card reader |
| `msx_screen.tcl` | Dumps the MSX screen as text |
| `z80dis.py` | Small Z80 disassembler for the cartridge ROM. `python z80dis.py 5F8B 5FC2` |
| `playcard_encode.py` | Builds a card image from scratch, verifying its own output. The inverse of `playcard_decode.py` |
| `card_dates.py` | Decodes the trailer to the date each card carries |
| `swipe_to_card.py` | Audio of a swipe -> card image. Validates the CRC and will not save a bad read without `--force` |
| `card_to_swipe.py` | Card image -> swipe audio, with `--rate`, `--bits`, `--bitrate`, `--speed`, `--lead`, `--tail` |
| `forge_crc.py` | Repairs the CRC of a deliberately corrupted card so it is accepted. Refuses only if the file is not a card at all, and says which structure failed and why |
| `header_edit.py` | Reads or rewrites the header and repairs the checksum. Values in musical terms, clamped to what the format can express; `--raw` for deliberately invalid ones |
| `Sample Playcards/` | Cards written as MIDI and compiled, with a README that is the user-facing guide to the compiler: the four channels, the control-note map, and every limit MIDI can breach - lengths, polyphony, the four chord types, one tempo, the ranges, the 62-entry chart, 433 bytes. The `.mid` and the `.bin` are both un-ignored so a reader gets a worked example |
| `new-cards/` | Cards written in 2026 to isolate one behaviour each, and a README. `make_same_root_test.py` writes card 17, which states the same chords two ways to ask whether one form resets state the other does not. `make_mute_test.py --wav` also renders swipe audio for a real keyboard; `make_lift_test.py` builds the three that measured what the lift bit does |
| `pcs30_demo.py` | The PCS-30's three built-in demos. They are decoded card data, not card images |
| `pcs30_arrange.py` | A card to a five-part MIDI arrangement using the PCS-30's accompaniment: melody, obbligato, bass, guitar, drums on channel 10. `--all` does a whole folder, `--in-dir`/`--out-dir` say which. Needs `pcs30-tables.json`. Bass anchors at C2 per the owner's ear. Two departures from the keyboard, both documented in its own docstring: a restruck pitch ends and starts again rather than merging into one note, and kick-plus-snare on one step is separated outside fills — the snare gives way on a downbeat, the kick gives way on disco's backbeat, and elsewhere both stay |
| `midi-roundtrip-design.md` | The design for the round trip, and a record of how building it went. All of it is built; where it disagrees with `playcard-format.md`, the format document wins |
| `playcard_midi.py` | Shared by the two round-trip tools: channel layout, control-note map, quantisation, chord recognition |
| `card_decompile.py` | A card to an editable four-channel MIDI file. `--all` does the corpus, into gitignored `rmidi/` |
| `midi_compile.py` | That MIDI back to a card, reporting everything the format cannot carry. `--sides auto\|1\|2` writes a two-sided card, `auto` splitting only what will not fit; `--roundtrip` measures the corpus; `--verbose` names every changed event rather than counting them. **A card that will not fit is recompiled in another key before it is split over two sides**: the key field changes nothing about how a card sounds and a great deal about how big it is, because every accidental costs a sharp modifier — 385 bytes against 480 for the same music on one corpus card, and 304 against 452 on a MIDI of nothing but black keys. `--no-refit` turns it off. **Every header field the meta text can carry has an option too** — `--tempo --rhythm --melody-voice --obbligato-voice --transpose --sustain --pattern`, plus `--raw FIELD=N` for values the named ones cannot express — so a file written by an editor that will not make text events still compiles to the card you meant |
| `playcard_compress.py` | Finds the repeats worth factoring out and lays out the spans. Used only by `midi_compile.py`; the resolver is what checks it |
| `make_random_card.py` | Random but structurally valid cards, to put a keyboard through its paces. About half carry a repeat span that really replays. Every header field over its whole legal range; each card draws its own *shape* first. `--seed` reproduces one. Output to gitignored `random-cards/` |
| `new-cards/make_swing_fill_test.py` | Builds cards 15 and 16, one field apart (rock and swing), for asking whether a fill's feel is its own or the rhythm's. `diff_fill_feel.py` beside it plays both through `csrc/playcard` and prints them against the PCS-30's tables |
| `make_test_midi.py` | A four-channel MIDI written from scratch, for testing `midi_compile.py` on material that did not come off a card. `--form short` folds onto one side, `--form long` needs two, `--sections` sets how long, `--seed` changes the material. **The long form overflows the 62-entry chord chart at the same point it goes two-sided** — 8 sections already needs 64 — because it writes a chord a bar and has little for the compressor to fold. That is one of the two limits it exists to reach, but it means the default long card is not the music that went in; `--chord-bars 2` thins the chords and 11 sections then fits both halves whole. The corpus round trip cannot test quantising real note starts, an alphabet with no precedent, repeats nobody planted, or either of the two limits — this can |
| `msx_player.py` | An emulated CX5M in Python, no emulator installed: boots the BIOS, initialises both cartridges and the SFG, reads a card through the cartridge's own UI (F1), starts the player (F2) and captures every YM2151 write to an `.fmlog`. Needs `cx5m_basic-bios1.rom` and `SFG01.ROM` in `Roms/`. Its docstring holds the three things that have to be right before a note will sound |
| `csrc/` | The C twin, and now the only way to see the cartridge's PSG-only mode (`--no-fm`, `--psg-log`): `playcard` runs a card on an emulated CX5M at ~150x real time and captures the FM, `fmlog2wav` renders that capture to a `.wav` through ymfm's YM2151. `--watch ADDR --watch-out F` reports every read and write of up to eight RAM addresses with the PC that did it, which is how a question like “does anything ever look at this byte” gets answered. `--screen F --screen-at S` writes the cartridge's own settings panel as text, read out of the emulated VRAM — the last thing openMSX was needed for. `--mix`, `--volume`, `--tempo` and `--transpose` set the cartridge's panel as a player would, through the firmware's own sync routine; `--keys`/`--play-keys` type anything else at it. **The tempo is correct here** and half speed under openMSX, because this one delivers the YM2151's timer-A interrupt. Borrows a Z80 core (MIT) and ymfm (BSD-3); see its README |
| `card_limits.py` | Runs the cartridge's own parser over a card and says whether the firmware would take it, reporting its return code (`0` one-sided, `1` a side A, `2` a side B, `0x80` refused). Cards given together go into ONE reader in order, which is how a two-sided pair has to be checked. `--sweep` finds the size ceiling from scratch |
| `same_root_entries.py` | Walks every card in playback order and reports the unplayable-root chart entries: which cards use them, what each does to the sounding chord, where in the bar it sits and how long it stands. Name a card and it prints that card's whole chart with the entries marked. This is the evidence for that section of `playcard-format.md` |
| `check_wrong_file.py` | Throws nine kinds of wrong file — MIDI, WAV, PDF, HTML, an executable, random bytes, an empty file, a folder, a path that does not exist — at every tool that takes one, and fails if any of them does other than name the file, name what it looks like, name what was wanted, and exit 1. Run it after touching how anything opens a file |
| `check_machine_named.py` | Every source file that describes behaviour must say WHOSE - name a machine, import `playcard_decode` for its naming block, or declare itself MACHINE-NEUTRAL. Blunt on purpose: it cannot judge a paragraph, only catch a new file that never joined the convention. **0 that do not say whose** |
| `new-cards/dropout_trigger.py` | What sets off the UPA-01's chord dropout, measured rather than argued: eighteen one-chord cards over the header pattern bit and all eight bar marks, played on `csrc/playcard`, counting chord key-ons a bar. **Mark 7 and nothing else** |
| `check_line_width.py` | Runs the tools down some fifty paths and flags any SENTENCE too wide for an 80-column terminal. Prose only: it counts distinct words, so drum grids and duration dumps are left alone. A static scan is not enough and was not — forge_crc's failure report is assembled from an exception's fields |
| `key_against_firmware.py` | Plays every card with a non-zero key field on `csrc/playcard` and compares the firmware's melody, note for note, against what this repository decodes. Written after two days of statistics built on a mis-read key field: the tools were right all along, the measuring scripts were not, and only the cartridge could say so. **105 of 105 exact** |
| `key_field_check.py` | What the header's key field is doing, measured three ways: black notes in the melody as written against as played, how many melody notes are tones of the chord under them, and what key each card is actually written in - taken from the chart's last chord, the one witness the field never touches. Name cards on the command line to see them one at a time. Written to settle whether a card whose melody and chart look like different keys is broken. It is not |
| `sweep_block2.py` | Runs the whole corpus through `csrc/playcard --watch` and counts who reads the three per-part level bytes. Written to answer one question — is the third ducked part ever consumed — and the answer is no, on every card. Keep it: it is the evidence for that section of `playcard-format.md`, and the pattern generalises to any “does the firmware ever look at this byte” question |
| `z80run.py` | Small Z80 interpreter. Runs a ROM routine with a made-up state instead of reading a disassembly and hoping. Unimplemented opcodes raise rather than being skipped; `z80run_test.py` checks it against 17 hand-computed results |
| `pcs30_rhythm.py` | The PCS-30's accompaniment pattern tables over any chord. `--chord G7 --rhythm march`. Reads `pcs30-tables.json`, not the ROM |
| `pcs30_drums.py` | Its drum patterns and the six fills, from `pcs30-tables.json`. `--card X.bin` is different in kind: it *executes* the firmware's bar-mark handler and reports the drum state bar by bar, so that mode needs the ROM itself |
| `pcs30_extract.py` | Reads a PCS-30 ROM once and writes `pcs30-tables.json`: the eight pattern tables at `0x2D26` and the five drum bit-planes at `0x2BBC`. Checks the shape of both before writing, so a wrong image is caught here rather than three tools later. `--check` reports on an existing file |
| `upa_extract.py` | Reads a UPA-01 cartridge ROM once and writes `upa-tables.json`: the ten drum patterns at `0x523B`, the six drum fills at `0x5251` and the ten accompaniment patterns at `0x5261`, with each block's flags and ticks a step. Checks the whole structure first - the pointers, that the blocks tile their region exactly, and that every drum byte's low bits are the constant 2 - so a wrong image is caught here. `--check` reports on an existing file, `--show` prints the patterns as strikes and chord tones |
| `upa_rhythm.py` | Those patterns over any chord: `--chord G7 --rhythm march`, `--alternate` for the other pattern of each rhythm, `--fills` for the six drum fills, `--raw` for the bytes. Reads `upa-tables.json`, not the ROM. This is where the owner's export voicing lives - the chord in the octave band ending at C5, the bass root C2 up to F#2 and then G1 up to B1 - so a MIDI exporter should import it rather than invent its own |
| `upa_arrange.py` | A card as a five-part MIDI arrangement using the CARTRIDGE's accompaniment: melody, obbligato, bass, chord, drums on channel 10. `--all` does a folder. Needs `upa-tables.json`, and `pcs30-tables.json` too unless `--drums upa`. Shares `pcs30_arrange.py`'s card walk, held-note voice, MIDI writer and drum tables, and `upa_rhythm.py`'s voicing. Departures from the cartridge, all listed in its docstring: chords on the beat (it plays them a step late), bossa-nova's last chord onto the clave, the exported voicing, the next bass note forced to a new root, a fill's feel from the rhythm, chords ringing to the next beat, and the PCS-30's drum patterns by default. `--as-is` turns all of it off |
| `pcs30_tables.py` | Loads that file for everything else, and is where `pitch_byte` and `drum_mask` live. Run alone it says whether the tables are present and which ROM they came from |

## Corrupting a card on purpose

`forge_crc.py` exists to find out what a keyboard does with a card it accepts but cannot make sense
of. It recomputes the checksum so the cartridge will take the card, and it deliberately does **not**
police the contents — a rhythm value that maps to no style, a key field on one of the YM2151's
unused note codes, a voice index off the end of its table are all passed through and merely listed.

It refuses exactly one thing: a file that is not a card. The reason is mechanical rather than
cautious — the checksum has no fixed address. It sits after the last section, and where that falls
depends on the length of the header, both duration tracks, the chord chart and both opcode streams.
If any of those cannot be walked, there is nowhere to put a checksum. When that happens the tool
names the structure it was standing on, the bit it stopped at, and why the walk could not continue.

**Corrupt fixed-width fields, not variable-length ones.** The header is all fixed-width, so editing
tempo, rhythm, voices, key or the pattern bit shifts nothing and the card still walks — which is
exactly what `header_edit.py` does, and why it is safe. Verified across the corpus: every full card
can have all seven header fields rewritten at once and re-reads with a valid checksum and its
duration tracks, chord chart, opcode streams and alphabet byte-identical. Stamping on
the duration tracks or the opcode streams changes their *lengths*, which moves every structure after
them — the section tag then lands in the wrong place and the file stops being a card at all. That is
a real result, not a limitation of the tool: those structures are self-delimiting, so damage to them
is not local.

One false-positive guard is worth knowing about. Random data can survive the first few fields by
luck, so the walk also requires the file to end **within 32 bits of the checksum** — 0 to 8 pad bits
and the 24-bit trailer, which is what all 267 originals do. 400 bytes of random data parses as a
28-byte card and is caught by that check alone.

One was made earlier — a real card with tempo 200, rhythm 13, melody voice 0, the key on unused code
7 and the pattern bit set, so the cartridge accepts it and can make nothing of it. It is **not kept
here**, because it was a Yamaha card with five fields changed rather than a card of our own, and no
Yamaha card data is in this repository. Rebuild it from any card you have:

```bash
python header_edit.py card.bin -o nonsense.bin --raw tempo=31 --raw rhythm=13 --raw melody=0 --raw key=7 --raw pattern=7
```

`header_edit.py` repairs the checksum as it writes, so `forge_crc.py` is only needed for damage
outside the header.

## How to verify a change

Three checks, cheap to expensive. Run at least the first two after touching anything.

**1. Structural (instant, no emulator).**

```bash
python playcard_resolve.py
```

Must print `0 of 261 cards still desynchronise`. A duration track and its pitch stream pair
one-to-one, so any count mismatch means the repeat expansion is wrong. This one number caught the
biggest bug in the project.

**2. Ground truth by ear (instant).** Known-correct openings:

| card | part | should be |
|---|---|---|
| Silent Night | melody | G4 A4 G4 E4 G4 A4 G4 E4 D5 D5 B4 C5 C5 G4 |
| Edelweiss | melody | E4 G4 D5 C5 G4 F4 E4 E4 E4 F4 G4 A4 G4 |
| This Masquerade | melody | A3 B3 C4 D4 E4 |
| Bill Bailey | obbligato | C4 D F A A♭ A B♭ C5 B4 B♭ A G |
| Someday My Prince Will Come | chords | F for two bars, A7 at bar 3, still A7 at bar 4 |
| Someday My Prince Will Come | accompaniment | standard, alternate for bar 3 only, standard from bar 4 |
| When You Wish Upon a Star | accompaniment | alternate for bars 1–2, standard from bar 3 |
| When You Wish Upon a Star | melody | C4 C5 B♭4 A4 F♯4 G4 D5 |
| When You Wish Upon a Star | obbligato | A4 B♭4 C5, C♯5 F5, E5 |
| I Write the Songs | drums | out for bars 1–4, in at bar 5; out bar 19 beat 4½ to bar 21, back at 22 |
| I Write the Songs | both mutes | bar 11 beat 1¾ drums *and* accompaniment stop, both back at bar 12 |
| Night Fever | accompaniment | bar 8 beat 1 one chord, muted at beat 1¼, back at bar 9, drums throughout |
| Mickey Mouse March | drums | fill value 3 on beat 1 of bars 2–44; drums out at bar 1 and 2 beat 4⅓ |
| Mickey Mouse March | ending | last fill bar 44; bar 45 beat 1⅓ both cut; 46 bars total |
| Edelweiss (PC-100) | obbligato level | full to bar 9, ducked 9–40, full 41–44, ducked 45–76, full from 77 |

**2b. Read the ROM (instant).** When a field's meaning is in doubt, scan for `CP <value>` — the two
bytes `FE nn` — and disassemble around the hits with `z80dis.py`. The three control opcodes were
solved this way in a single scan, after corpus statistics had gone nowhere for two sessions.

**2c. The MIDI round trip (about a minute).**

```bash
python midi_compile.py --roundtrip
```

**All four parts must print `264 of 264`** — melody, obbligato, chords and control events — and
`capped` must be `0 cards`. It should also report `264 of 264` fitting the strip, two of them
written over two sides. This is the check that the format is understood well enough to *write* and
not only to read, and it fails loudly: it names the card and the first differing event.

It is also the check most likely to catch a change made for another reason. Both the renderer's
articulation and the compiler's lift-bit rule were arrived at through it.

**3. Against the firmware (seconds).**

```bash
python key_against_firmware.py
csrc/playcard card.bin -o card.fmlog --watch 0xD353 --watch-out card.marks
```

Capture the real cartridge playing a card and diff. `key_against_firmware.py` does it over the 105
transposed cards and must print `exact 105`; for one card, `csrc/playcard` writes every YM2151
register write, and notes reconstruct from key-on (`0x08`) and key code (`0x28+ch`). `--watch`
reports every access to a RAM address with the PC that made it, which is how you see what the
firmware DECIDED rather than what it then played.

This used to mean openMSX, a Tcl harness and several minutes a card; that is now the historical
route, and only the cartridge's on-screen panel still needs it.

## The firmware's size ceiling is 4080 DECODED bytes

Worth knowing before generating anything large. The 433-byte strip limit is physical; the cartridge
has a separate one, on **how big the card decodes to** rather than how big it is.

A card is read into a raw image at `0x8000`, then decoded into a second buffer at `0xD377`. Two
hard-coded compares guard that second buffer — `0x6317` on every duration symbol and `0x64C8` on
every opcode, both `SBC`-ing the pointer against **`0xE367`** and doing `RET C`. Past it the section
parse fails and the card is **refused with error `0x80`**. Nothing is overwritten and nothing
crashes: the parse state starts at `0xE377` and the guard stops 16 bytes short of it.

`card_limits.py --sweep` finds the number without being told it: 1016 notes a part accepted, 1017
refused, so **4080 bytes**. The 264 originals decode to 158-1361, so the largest uses a third of it.
At the corpus's median 2.4x expansion that ceiling is about a 1700-byte card, four times what the
strip holds — so **the strip always runs out first**, and a card can only hit the firmware limit
if it could never have been pressed anyway.

Both were confirmed by running the real decode path under `z80run.py`, which now implements ADC,
SBC and the ED-prefixed 16-bit loads it needed to get there.

## Traps

These cost real time. Do not rediscover them.

**The size guard is at `0x6317`/`0x64C8`, NOT the bounds check at `0x622A`.** `0x622A` compares a
pointer against the limit at `0xE479` and sits right on the failure path, so it looks like the size
guard. It is not: patching it out does not move the threshold by a single byte. It is a "have I read
past the end of the card image" test. The real ceiling is the `0xE367` compare described above.

**openMSX is the historical route, and as of 2026-08-30 nothing needs it.** Everything up to
mid-2026 was measured through it and the traps below are its, but `csrc/playcard` now covers the
lot: ~150x faster, at the right tempo, with nothing installed. `--watch ADDR` sees the same events
a Tcl breakpoint did, which is what let `capture_fills.py` lose its whole Tcl harness; and
`--screen FILE` reads the cartridge's settings panel, which was the last thing openMSX still had.

That last one is worth knowing how it works, because the obvious approach fails. **The cartridge
does not use the MSX BIOS text routines** - not one CALL to CHPUT, WRTVRM, LDIRVM or SETWRT in its
16 KB - so there is nothing to intercept at the BIOS level. It drives the VDP ports directly, from
one table-driven writer at `0x7DB6`. Keeping the 16 KB of VRAM is what makes the screen readable,
and the emulator now does; the name table holds character codes and reads back as text.

The traps below are kept because they explain old numbers, and in case anyone runs openMSX again.

**For a question about what the firmware DOES, reach for `z80run.py` before either.** Watching the
card decoder under the emulator does not work: watchpoints on the decode buffer drown in the MSX
BIOS's own stack traffic and the cartridge's `PUSH`/`POP`, and the card feed never surfaces. Running
the real decode path statically out of the ROM answered the size-ceiling question in about a second.
The emulator earns its keep for *audio* questions, where the answer is what you hear.

**A capture under openMSX runs at HALF the card's tempo, and the machine's frame rate is not
the reason.** Measured on card 12, which declares 120 bpm: a quarter note comes out at **0.9998 s**
against the 0.5000 s it asks for. The cartridge's sequencer advances once per pass of `0x431F`,
those passes arrive at **49.75 a second** (openMSX's `yamaha_cx5m` is PAL), and a quarter note takes
**49.7 of them** — so bpm x ticks-per-quarter is 6000 and the firmware's timebase is **100 ticks a
second**. No MSX VDP gives that: 50 Hz is exactly half, and 60 Hz would be 0.6x, so **running a
60 Hz machine would not fix it**. The ROM never reads the BIOS 50/60 Hz flag at `0x002B`, so it does
not adapt either — which is itself the argument that the VDP interrupt was never the intended
clock. The likeliest real one is the YM2151's own timer, the only source in the machine that can be
programmed to a fixed rate; that part is not verified.

What this does and does not spoil: anything measured as a RATIO within a capture is unaffected, and
the lift-bit release was measured that way — 99.6% against 83.2% of a note's own slot. Anything
quoted in seconds from a capture is at half speed.

**The melody is voiced across TWO YM2151 channels, alternating.** Compared against either alone it
looks half missing. Merge them by timestamp.

**A swipe recording that decodes to clean-looking gaps and parses to nothing has BASELINE WANDER.**
A Schmitt trigger measures against zero; a head that sits +15000 above zero for a moment — a
thump as the card goes in — never reaches the negative threshold, so the trigger latches and every
reversal underneath is dropped. Nothing about it looks wrong: the envelope is steady, the gaps that
are found are cleanly bimodal, two independent decoders agree bit for bit, and the date trailer at
the end decodes to a real date. The tell is arithmetic — the distance from the sync to the end of
the image was not a whole number of bytes. `swipe_to_card.flux()` subtracts a moving average before
triggering, which cost one recording 28 bytes of its header before it was found.

**Capture speed: the 2026-08-17 conclusion was wrong, and the useful half of it is that speed does
not lose anything.** That test set `speed` 100 / 400 / 1000 / 2000, `fastforward` at 2000 and 10000,
and `throttle off` over a fixed 45-second emulated window, and found the same FM writes
(12290-12296), the same key-ons, and the same 45 s of wall clock every time. The identical FM output
is solid and still holds: **no speed setting loses writes**, and the older claim that `set speed
1000` silently stops FM writes appearing did not reproduce and should not be trusted.

The wall-clock half does not hold. **Pressing F9 in the openMSX window does speed emulation up**,
and one run of `capture_fills.py` on 2026-08-22 shows the size of it: 150 emulated seconds in 23 s
of wall clock, against 45 emulated seconds in 60 s for a run left alone — 6.5x real time against
0.75x. The fast run was driven by hand: the card owner pressed F9 once the card had audibly loaded
and quit openMSX when the music ended, so the several seconds of MSX boot and card feeding ran at
normal speed and the music itself ran faster still than 6.5x suggests. So a capture is not pinned to
real time, and "nothing makes it faster" should not be relied on.

**None of that touches a measurement that is made in emulated time.** The 6.5x run gave a bar length
of 4.805 s in all four of its blocks, identical to the 0.75x run's 4.806 s. Derive the grid from the
card's own events — chord records, bar marks — and the rate the emulator happens to be running at
drops out. The trap below about not touching a running capture is about *absolute* timing, and it
still stands.

**`set speed` inside a Tcl proc sets a local variable, not the setting.** Use `$::speed`. A bare
`set speed 1000` at global scope does work.

**difflib's autojunk fires on sequences over 200 elements** and tanks similarity ratios on long
note lists. Always pass `autojunk=False`, or you will "discover" a regression that is not there.

**openMSX's external control channel does not work on this Windows build.** `-control stdio` closes
its stdout pipe (GUI-subsystem binary); the TCP socket accepts then resets. Use `-script`.

**F2 is a play/stop toggle**, and some cards start playing on their own once read. Pressing F2
blindly stops those.

**Feed zero bits after the card data** when faking the reader — the blank tail of a real strip. A
zero block type is the format's end-of-data marker; without it the reader spins forever.

**The chord channels' key codes are a minor third apart on EVERY chord**, whatever its quality — C
and D♯ for a C chord, G and A♯ for a G chord. Read as pitches this says "minor triad" on every card
ever pressed, which is wrong and cost real time. The chord tones are the operator **`MUL` ratios**,
not the key codes: both channels run algorithm 4, so each has two carriers, and an operator sounds
root × MUL, with 4 : 5 : 6 being a just major triad. ch3 is the root and ch4 sits three semitones
up; the major third is ch3's fifth harmonic, the fifth is ch4's, and the seventh is ch4's sixth
harmonic gated by `TL` (127 for a plain triad). To read quality from a capture, look at `MUL` on
`0x53`/`0x5B` (ch3) and `0x54`/`0x5C` (ch4), and `TL` at `0x7C`.

**The accompaniment mute is not a control opcode.** It is the value `0xFF` in the chord chart — a
"stop sounding" entry rather than a chord. Looking for it among the control opcodes wastes time; it
is decoded by `chord_chart()` in `midi_export.py`, not by anything that handles `0xE1` records.

**A tool handed the wrong kind of file says so, and never tracebacks.** Point one of these at a MIDI when it wants a card, or at a PDF, an executable, a folder or nothing at all, and it names the file, names what it appears to be, names what the tool wanted, and exits 1. `playcard_decode` holds the machinery: `kind_of()` sniffs a file, `check_card()`, `check_midi()` and `check_wav()` demand one kind and raise `WrongFile` (a subclass of `Missing`, so handlers that already catch that keep working), `check_file()` asks only that it be readable, and `run(main)` is the entry-point wrapper that turns any of it into a sentence — and Ctrl-C into a quiet exit 130. **Every tool's `__main__` goes through `P.run`.** Two deliberate exceptions: `forge_crc.py` takes anything readable, because repairing images too damaged to parse is its whole job, and it does its own reporting; and `csrc/playcard` checks size alone (a card is 433 bytes at most), since C has no exceptions to catch. `check_wrong_file.py` throws nine kinds of wrong file at every tool that takes one and expects a clean refusal from each.

**Long messages go through `playcard_decode.say()`.** A terminal breaks an over-long line wherever it runs out, which lands in the middle of a word and reads horribly. `say()` wraps at the words instead, to the real terminal width, with a hanging indent; `wrapped()` returns the string for a `sys.exit`. Use them for **sentences only** — tables and file paths are better left to overflow than folded.

**Heredocs mangle backslashes** in this shell. Write Python helper scripts with the Write tool
rather than `cat <<EOF` when they contain Windows paths, regex escapes, or `\n` inside a string
that is being written into another file. This one keeps recurring because the damage is silent and
looks like something else: a `printf("...\n")` emitted into a C file becomes a real newline and the
compiler reports an unterminated string on a line that looks perfectly fine.

**A patch script that asserts its anchors is atomic, and that is a feature.** Several of the doc
edits here are done by a small Python script that asserts each `old` string is present before
writing anything. When an anchor goes stale the script fails having written nothing, which is much
easier to recover from than a half-applied edit. Do not "fix" it by dropping the asserts.

**The cartridge's panel does not refresh until playback starts.** The header is parsed into a
staging record at `0xE377` and only applied on play, so a screen dump taken right after loading
shows defaults and looks like the card failed. Press F2 first, then read the screen.

**The chord notes dropping out is a BUG IN THE UPA-01, not an emulator artifact.** This was
recorded here for weeks as an openMSX defect. It is not. `csrc/playcard`, an emulator written from
scratch that shares no code with openMSX, reproduces it exactly — and two independent emulators
agreeing on a behaviour drawn from the same ROM means the behaviour is the ROM's.

**The trigger is mark 7, and only mark 7.** The first reading of it — "the alternate pattern running
more than one bar on the same chord" — was wrong in both halves, and the card owner caught it:
the alternate pattern can run sixteen bars over one held chord with the chord notes intact, provided
it got there through the HEADER LOCK; a single mark 7 drops them at that bar in either header state,
and they never come back on their own. Marks 0 to 6 never do it. Any chart record afterwards
restores them, a restatement of the same chord as readily as a new one.

That puts the fault in the **mark 7 handler**, not the accompaniment generator — and note that with
the header bit set, mark 7 cannot even change `0xD352` (it is already `C3`, and `OR 0xC1` is a
no-op), yet the chord notes still drop. Handling the mark is enough by itself.
`new-cards/dropout_trigger.py` builds the eighteen cards and prints the table.

What made the wrong diagnosis so persuasive: original cards do it too, and **real Playcard keyboards
do not**, both checked by the card's owner. Both facts are still true. They point at the cartridge
rather than at the emulator, because a PC-100 is not running this firmware. A chord that stops looks
exactly like an accompaniment mute or a pattern switch, and it cost three built cards and three
captures.

For reading captures the advice is unchanged, and now for a better reason: read `0xD352` for the
pattern state and the `0xE7` handler for chord records rather than the chord channels' key-ons.
Those are what the card asked for; the key-ons are what the firmware managed to do with it.

**openMSX's sound buffer was set to 65 and dragged the whole emulator below real time.** The
`samples` setting is the sound mixer buffer; the default is 2048 and the minimum is 64. It was
persisted at **65**, and openMSX paces emulation against its mixer, so the machine ran at
**1.21 wall seconds per emulated second** — about 17% slow, with constant buffer underruns on top.
That is both "the sound is choppy" and a good part of "capture timing cannot be trusted". Measured
across buffer sizes, with throttle on:

| `samples` | wall / emulated |
|---:|---|
| 65 | 1.207 — slow |
| 256 | 1.023 |
| 512 | 1.002 |
| 1024 | 1.001 |
| 2048 (default) | 1.003 |

Fixed on 2026-08-17: `samples` back to 2048, and `master_volume` and every sound device's volume
raised from the default 75 to 100. openMSX now holds real time at 1.000. **Frame skipping was not
the problem** — there is roughly 74× headroom with throttle off, and `minframeskip` from 0 to 5
changes nothing.

**openMSX is simply quiet, and it is already at maximum.** Measured off its own `soundlog`, playing
a card: the volume settings do work and raising them from 75 to 100 gained exactly +5.0 dB
(peak 0.191 → 0.339, RMS 0.0069 → 0.0123, both ×1.78 as the arithmetic predicts). But that RMS is
**−38 dB of full scale**, roughly 20 dB below ordinary listening level, and 100 is the top of the
range. There is nothing left to turn up inside the emulator; more level has to come from the OS
mixer or from normalising a captured `.wav`.

**And most of the apparent level is a boot transient, not the music.** Recording from the moment
openMSX starts and looking at the envelope in half-second buckets, the whole recording peaks at
**0.3806 — at t = 5.5 s, during the MSX boot, before the card is even fed.** The music that follows
never exceeds **0.0914**. So normalising a capture does almost nothing: the gain is set by a pop.

Muting the PSG and the key click removes them at source, and the music is untouched:

| | boot transient | music peak | music RMS | headroom |
|---|---:|---:|---:|---:|
| everything sounding | 0.3806 | 0.0914 | 0.0168 | 8.4 dB |
| PSG + keyclick muted | **0.0000** | 0.0913 | 0.0168 | **20.8 dB** |

Same peak, same RMS, 12.4 dB of headroom recovered. Playcard music is entirely on the SFG-01's
YM2151, so nothing musical is lost. **This is now the configured state**: SFG-01 and master at 100,
PSG, key click and cassette player at 0. Undo with `set PSG_volume 75` etc. if the MSX's own sound
is ever wanted.

Do not measure loudness with a bare peak on these recordings — it will find the boot pop every time.
Bucket the envelope, or measure only from the point playback starts.

Settings live in `%USERPROFILE%\Documents\openMSX\share\settings.xml`, and **`save_settings_on_exit`
is true** — so any setting a `-script` changes is persisted when that run exits. Back the file up
before benchmarking, or a throwaway experiment becomes the new default.

**A capture is a live emulator, and anything done to its window lands in the data.** The tempo
control changes the music's speed in *emulated* time, so it is indistinguishable afterwards from a
firmware behaviour. This has already cost one wrong conclusion: an Edelweiss capture appeared to
show the tempo drifting through the intro and locking exactly where the melody entered, which was
in fact the tempo being nudged during the run to make it finish sooner. Two runs of the same card
disagreeing is the tell. **Do not touch the emulator while a capture is running**, and treat any
timing measured across a whole capture as unverified unless the run is known to have been left
alone.

Timing is the only thing at risk. Correlating an event with a register write survives it, because
that is a local comparison — if the tempo moves, the opcode and the register write move together.
The obbligato duck lands within 45 ms of its opcode however the run was driven.

**`fake_cr01.tcl` does not feed the zero trailer**, unlike `play_card.py` and `card_to_midi.py`.
The reader never finishes, so its screen dump is always defaults. Use it for buffer dumps, not for
anything that depends on the card having loaded.

## What to pick up next

**Nothing on the compiler is outstanding.** Both items that stood here are closed:

* **Two-sided output** is built. `playcard_encode.build_sides()` writes the pair, `midi_compile.py
  --sides auto|1|2` chooses, and the firmware accepts a generated pair with the same return codes as
  Yamaha's own — `0x01` for a side A then `0x02` for its side B, with a lone side B refused `0x80`.
* **The card whose chart "overflowed" never did.** It needed exactly 62 entries and stored 62. The
  overflow warning came from a *discarded* trial layout — the flat form of that card really does need
  84 — and all three attempts shared one report; and the round trip counted `>= 62` as capped when
  62 is legal. Both were reporting bugs, and no corpus card overflows the table. New material can:
  `make_test_midi.py` with a chord a bar over 128 bars needs 105.

What is left is not the compiler. The remaining gap against Yamaha is a looser span-acceptance rule,
written up as item 8 of `midi-roundtrip-design.md` and not worth building until something needs it;
everything else is the accompaniment patterns below.

One question that was an input to that design is now **settled**: a chord chart entry fires **once,
at the obbligato's opcode index**. The melody stream's copy never reaches the handler, despite the
cartridge walking the table for both streams. Proved on the real firmware with
`new-cards/make_chart_test.py` — sixteenths in the melody against whole notes in the obbligato put
position 17 in bar 2 of one and bar 17 of the other, and the record arrives at the obbligato's, with
43 seconds of nothing at the melody's. So a compiler places chords by obbligato index and can ignore
the melody entirely.

The other open items are the UPA-01's own accompaniment patterns and which of the six stored PCS-30
patterns each mark names. **The third ducked part at `0xD349` is answered as far as this cartridge
goes: it is written and never read.** `csrc/playcard --watch` reports every access to an address with
the PC that made it, and across all 261 cards plus the three two-sided sets, the level field of
block 2 was read by live code **zero times**, against 57,827 reads of the obbligato's. The reason is
four lines of ROM: the pump is `CALL 0x5D94`, it is called at `0x6046` for the melody and at `0x6057`
for the obbligato, and then the routine returns — and the address `0xD326` occurs nowhere in the
16 KB. Block 2 is initialised like a real part and ducked like a real part, and nothing sends it
anywhere.

What survives is the identity question, and the PSG reading still looks best: with no FM hardware
(`--no-fm`) the cartridge plays melody, obbligato and a bass, so there are three parts to have
blocks. But nothing is ducked on that path either — the PSG volume registers are written only
during boot — so block 2 belongs to the cartridge's model of a keyboard, and only a keyboard that
answers to it can say what it is.

## Yamaha's music, and where the line is

The rule this repository follows: **the code and the addresses are ours to
publish, the musical content is not.** Card images, ROM images and the
instrument's own accompaniment stay out; everything that reads them is in.

That used to mean three scripts were gitignored along with the data, which was
the easy way to draw the line and the wrong one — the arrangement code is a
description of how the machine behaves, and nothing in it is Yamaha's. The
patterns now live in `pcs30-tables.json`, which is generated and gitignored:

```
python pcs30_extract.py          # a PCS-30 ROM you own -> pcs30-tables.json
```

`pcs30_arrange.py`, `pcs30_rhythm.py`, `pcs30_drums.py` and
`new-cards/diff_fill_feel.py` read that file and never open a ROM. Without it
each stops with the same short explanation and exit code 1, never a traceback.
The two exceptions genuinely need the ROM, because they run its code rather than
reading a table: `pcs30_drums.py --card` and `pcs30_demo.py`.

If you add a tool that reads Yamaha's patterns, take them from `pcs30_tables`
rather than from a ROM, and the boundary keeps itself.

**`Roms/README.md` is the map**: the four images, which tool needs which, what a
good dump looks like, and what happens when one is absent. It is the only file
in that folder that goes into the repository, which needs `Roms/*` rather than
`Roms/` in `.gitignore` — git does not look inside an ignored directory, so a
README under one can never be un-ignored.

## The voices have two sets of names

The tools print and write the **PC-100's** panel names, and accept the SFG-01's as aliases. The
cartridge is a 1985 product; the keyboard the cards were written for is a 1982 one, and its panel is
what a player read. Six of the ten melody voices differ:

| SFG-01 | PC-100 | | SFG-01 | PC-100 |
|---|---|---|---|---|
| `PORGAN1` | organ | | `STRING2` | violin |
| `CLARINE` | clarinet | | `HARPSIC` | harpsichord |
| `EPIANO1` | piano | | `VIBRPHN` | vibraphone |

The obbligato voices are not user-selectable and have no panel names, so they take the same
convention: `STRING1` is **strings** and `BRASS 1` is **brass**.

`playcard_decode.VOICE_NAMES` is the one place these live, `SFG_NAMES` keeps the old set, and
`voice_field()` resolves either, ignoring case, spaces and punctuation. **Anything that names a
voice should go through those** rather than carrying its own table — `midi_export` used to keep a
second copy and no longer does. A `.mid` decompiled before the rename says `melody=CLARINE` and
still compiles.

## Two reporting bugs the first outside user found

Worth keeping, because both were **the report being wrong, not the compiler** - the card it wrote
was correct in each case, which is exactly what makes this kind of bug survive a 264-card round
trip. A MIDI submitted by someone who had never seen the format before flushed out both.

**The lossy-timing warning fired on note LENGTHS and blamed note POSITIONS.** The file was written
at 960 ticks a quarter with every onset exactly on the grid, and 38 notes one tick short of their
full length - the gap a sequencer leaves so a note-off does not collide with the next note-on. That
is 1/2880 of a bar and rounds straight back to what the writer meant, but it produced *"the file's
timing does not divide into the card's 24 ticks per quarter, so note positions were rounded"*, which
is alarming and false. `X.rescale` now returns a drift dict counting positions and lengths
separately, and **ignores a discrepancy of one SOURCE tick or less**, which is the smallest unit the
file could express and therefore always noise. The scary case still reports, and now names the
file's resolution so the reader knows what to change.

**A control note on a music channel was reported as an unrelated complaint about overlapping
notes.** Two of the file's control notes - a mark 5 and a duck - had landed on channel 1. They came
out as *"melody notes dropped, a higher note is already sounding: tick 4248, 29"*, which names
neither the problem nor even the note. Worse is the case where such a note does NOT overlap: it is
below the melody's G3 and gets **folded up three octaves into the tune** as a wrong note, mentioned
only as "moved by octaves". `midi_compile` now checks channels 1 and 2 for control-note pitches and
says so first, and every pitch in every report is spelled `F1` rather than `29` (`X.note_name`).

**It does not re-route them, and should not.** The channel is the contract; a compiler that silently
moved notes between parts on a pitch guess would be worse than one that misses a mark. Say what
happened and let the author fix the file.

## The cartridge's panel, and a tempo fault that ran every capture 4% slow

**The panel is a small block of RAM.** V, T and K on the MSX keyboard write the *wanted* value at
`0xCC26`: five volumes (melody, obbligato, chord, bass, rhythm; 0-40, booting at 30), tempo (an index
into 41 settings, 40-200 bpm in 4s, ROM `0x433A`) and transpose (0-11, 5 is none). A routine that runs
a few hundred times a second copies each into the live copy at `0xCC09` when they differ and applies
it. So poking `0xCC26` is exactly as good as typing — which is what `csrc/playcard`'s options do. Two
catches, both handled there: starting a card overwrites the tempo at `0x4313`, so tempo goes in just
after that store; and the sync only acts when wanted and live DIFFER, so asking for the boot default
does nothing unless the live copy is marked stale. **A** cycles ABC off/on/variation at `0xCC08`,
which changes nothing in the cartridge's own output — it is sent to the music keyboard. The volume,
tempo and transpose knobs are sprites, which is why `--screen` never showed them.

**At the cartridge's own levels the melody is quiet**: measured alone and while sounding, melody and
obbligato sit about 9 dB under the bass and drums and 6 dB under the chords, and each volume step is
1.1 dB. `--mix lead` brings it forward, and is `csrc/playcard`'s **default** since 2026-09-21. It
began as a fixed 40/34/28/26/26 and now **sets melody and obbligato by voice**: the voices differ by
up to 8.6 LU at one setting (oboe melody loudest, piano quietest), so a fixed mix left a violin 9 LU
over a brass obbligato. `csrc/voice_levels.py` measured every voice (BS.1770 loudness, part alone,
eight re-headed cards); the firmware holds the card's voices at `0xD2FB` and `0xD320` (`0x80` plus
the field) by the time the tempo lands at `0x4316`, and lead aims the melody 4 LU and the obbligato
1 LU over the accompaniment. On 55 unseen voice pairs melody-over-obbligato came out +3.3 mean, sd
1.1, against a target of 3. `--mix karaoke` is lead with the melody muted: volume 0 is not silence (the carrier TL
only goes to `0x4F`, about 45 dB down), so key-ons on channels 0 and 1 - always the melody, doubled,
on all 23 cards checked - are turned into key-offs. `--mix cartridge` imposes nothing at all.
**`--as-is`** is that plus every firmware bug left in (today: the chord dropout, below), and
**every research harness passes it** (`key_against_firmware.py`, `sweep_block2.py`,
`new-cards/capture_fills.py`, `diff_fill_feel.py`, `dropout_trigger.py`), so their captures stay
the machine untouched. Anything new that studies the firmware should do the same.

**The chord dropout is found, and repaired by default in `csrc/playcard`.** Every pattern change
runs `0x4C63` (service 5 of `0x4850`), which ends `LD C,03h / LD D,04h / CALL 4E5D` at `0x4CB5`:
it sends the chord part chord code 3, "no chord". The SFG-01 clears bit 7 ("sounding") of its chord
byte `0xEC23` at `0x14FE`, and nothing re-sends the chord until a chart record flags `0xD353`. At
card start the first chord follows the pattern events, so the header lock is harmless; mark 7
switches pattern twice mid-card with no chord behind. The repair: on reaching `0x4CB5` with
`0xEC23` bit 7 set, set bit 7 of `0xD353`, so the firmware's own pump re-sends the chord - what a
restated chord on the card does. `dropout_trigger.py --repaired` holds all sixteen bars on all
eighteen cards; across the corpus 60 cards trigger it, 33 gain chord notes (1,164), none loses a
note and no other part's count changes. `--keep-chord-dropout` or `--as-is` leave the bug in. The
chase used the new `--trace ADDR` (registers and stack at an address): event pump `0x606E` -> event
dispatcher `0x59D8` -> pattern handler `0x5A9B` -> `0x4850` service 5 -> `0x4CB5`.

**The PCS-30's sound now has its own document, `pcs30-sound.md` (2026-09-22):** chip, waveforms,
envelopes, the decoded voice table, measured output-pin filters, vibrato, tuning, drums, and the
tempo table at `0x1B83` (played bpm = 10070/(entry+1), a 167.8 Hz tick; 120 bpm cards play at
127.4). Measured from the card owner's PCS-30 recordings (not in the repository) by lining each up
with `pcs30_arrange.py`'s arrangement of its card; the analysis scripts were not kept, so the
document's "How the recordings were measured" holds the method instead - align on an onset curve
searching offset *and* speed ratio (the keyboard plays fast), find each note again locally by pitch
purity because the global fit drifts by up to a note, and measure only notes that are alone. Its
four traps are worth reading before any of it is redone; the fourth is that melody-against-obbligato
balance cannot be measured this way at all, which was learned twice.

**`pcs30_synth.py`, a PCS-30 synthesizer - WORK IN PROGRESS (2026-09-22).** It renders a card
from `pcs30_arrange.py --chip` (new: the parts as the chip's four channels play them - the whole
bass table on the bass channel with its own note-offs, no dropped kick/snare doubles). Five rounds
of listening by the card owner fixed: bass rerouting (Silent Night's C2 E3 E3 G2), the organ's
GM octave (undone in the synth; piccolo's kept), retrigger swells (model: every note keyed, attack
starts from the current level), drum envelopes (measured: fall to half in 10 ms, linear, hard stop),
snare silences a simultaneous cymbal (waltz beats 2-3), vibrato delay (~250 ms, ~12 cents p-p),
and a double-counted roll-off (the pin filters already include the chain). Still set by ear:
`PIN_DB` (OR3 +4, OR2 -4), two-pin voices at full level on both, `DRUM_GAIN`. Open: violin
brightness, bass on guitar-chord cards, Mickey's guitar melody level, snare. The chord voice is
decoded (`0x2D12`/`0x2D1C` by rhythm, guitar a step down); the bass is always entry 2. All of it
is in `pcs30-sound.md`. The user's recordings are in `tmp/PCS-30 Recordings/` (not committed);
renders go to `tmp/pcs30-synth/`. **Set aside on 2026-09-22** with those items open; all of them are
balance, all by ear, so resuming means listening to a render beside a recording of the same card.

**A machine that never existed: the keyboard's sound with the cartridge's arrangement
(2026-09-22).** `pcs30_synth.py --arranger upa` takes its notes from `upa_arrange.py` instead of
`pcs30_arrange.py --chip`, so a card is played by the PCS-30's voices, filters, drums and
snare-over-cymbal rule, from the UPA-01's own accompaniment patterns with that tool's corrections.
Three departures from the real keyboard are deliberate and marked in the docstring: **the card's own
tempo** rather than the keyboard's 32-entry table, because a 120 bpm card really does play at 127.4
there and that quirk is not wanted here; **no four-note limit** - the keyboard has four channels
playing one note each and its chord part is a single line, while the cartridge's is a whole chord, so
`slots()` deals a part into as many channels as it needs and `PCS30_CHORD_DB` (ear-set, -5 dB) takes
that part down now one line has become four; and **the organ stays where the card puts it**, since
only the PCS-30 arranger's `--chip` output needs its octave taken back out. `DRUM_BIT` now accepts
both arrangers' GM notes, the conga and the claves being the same latin drum on this keyboard.
Renders for listening go to `tmp/upa-pcs30/`.

**The obbligato duck (2026-09-22).** On the UPA-01 the duck is velocity: `0xD324` (`0x60` ducked,
`0x80` full) rides with each obbligato note from `0x5E2F`, and the SFG voice decides the effect -
1-2 TL steps for most voices, **zero for the harpsichord** (Love Theme: no audible duck at all). The
PCS-30 adds `0x10` at every obbligato note (`0x0F77`, flag from `0x2ACA`/`0x2ABD` via `0x1E48`) to
its YM2142 register `0x8C+ch`. The YM2142 is undocumented but register-compatible with the
**YM2163**, whose datasheet exists (denjhang/RE2-YM2163 on GitHub, MIT; also a Drive copy): `8CH`
bits 5-4 are volume 0/-6/-12 dB/off, bits 3-0 route to four output pins (analogue filters); `88H`
is envelope/sustain/waveform, and the PCS-30 voice table at `0x2CFC` decodes cleanly as (`88H`,
`8CH`) pairs. So the PCS-30 duck is exactly **6 dB for every voice**. No YM2163/YM2142 emulator
exists (MAME has neither). `csrc/playcard` now ducks like the PCS-30 by default: it resets `0xD324`
to `0x80` at `0x5FBF` (after the `0x14` handler) and adds 8 TL to channel 2's carriers until
`0x5FAA` (after `0x13`). `--duck DB`, `--duck cartridge`, and `--as-is` keeps the cartridge's.

**Every capture from `csrc/playcard` before 2026-09-21 ran about 4% slow.** The playback loop runs the
machine in quarter-second slices, and `run()` kept timer A's next overflow in a local variable, so
each slice started the timer period afresh and lost a tick — exactly one every 250 ms, found by
tracing the SFG's interrupt handler at `0x2D4C`. The phase now lives in the machine, the handler
services 95.772 interrupts a second against 95.771 programmed, and tempos land within the timer's
own resolution. It explains the old "folds best at 95" in `diff_fill_feel.py`, the stray half-bars in
`dropout_trigger.py`'s first table, and the spec's 120.4 bpm, which is really 119.7.

**The UPA-01 plays five card tempos slow**: it turns the card's metronome mark into a panel index as
`floor(bpm/4) - 10`, so 63, 66, 69, 126 and 138 play at 60, 64, 68, 124 and 136. Measured.

## The three things most likely to be wrong again

The duration byte's **bit 7** has been misread twice and is the subtlest part of the format. It is
a *lift* flag — the finger comes off at the end of that event — and it must be tested on the
**preceding** event when deciding whether a repeated pitch ties or re-strikes. Read as a rest it
swallows notes; ignored it duplicates them; read on the current event it merges repeats.

The **octave register** is a plain running register, not any kind of context inference. An earlier
"nearest note" heuristic matched 88% of the time, which was enough to look right and never be.

The **key field** is a note code numerically, but it is a **transposition, not a key name**, and it
has now been got wrong twice in two different ways. Printing the note-code name for it gives "C#"
for field 0, a semitone high, which was wrong in four tools and the spec until 2026-08-17. Then the
correction overshot: field 0 does not mean "sounds in C" either, because **the card does not record
what key it was written in**, and it is not always C — 203 of 261, with 36 in A minor and 22
elsewhere. `playcard_decode.key_name()` answers a conditional question, *what would a card written
in C sound like*, and every caller prints it as one: `(a card in C sounds in F)`. Never print a bare
"sounds in X". Any lookup with a silent default will also quietly leave cards in the wrong key.

To measure the key a card is actually in, use the **chord chart**: it is stored at sounding pitch
and the field never touches it, so its last chord names the sounding key — right against the
melody's own last note on 211 of 261. `key_field_check.py` does this, for the corpus or for any card
you name. Do not try to get the key from the notes: C major, A minor, G mixolydian and D dorian are
the same seven notes, so a scale fit cannot tell them apart, and this is precisely how *9 to 5*
(written in G, sounds in C) was written up as C for a week.

## The accompaniment patterns

**Found, 2026-09-22: the cartridge's own pattern tables are in the cartridge ROM**, not the SFG-01,
and their shape is measured rather than guessed. The way in was a new emulator option, `--rom-reads`
(see `csrc/README.md`): it logs every ROM address the firmware reads as *data* rather than executes,
with the instruction that read it, so a table announces itself as a run of neighbouring addresses
read by one instruction. Ten throw-away cards - one a rhythm, each holding a single chord and
playing almost nothing of its own - then said which block belongs to which selection.

**Three pointer tables**, back to back, each a little-endian word an entry, with null entries where
nothing is selected:

| table | at | entries | indexed by |
|---|---|---|---|
| **drums** | `0x523B` | 10 and a null | the card's **raw rhythm** value, 0-9 |
| **drum fills** | `0x5251` | 6, entries 1-6 | the **fill** number from the escape opcode, 1-6 |
| **accompaniment** | `0x5261` | 10, entries 1-10 | the raw rhythm **+ 1** |

The blocks they name run back to back from `0x5279` to `0x589C`, 1572 bytes in all, and the code
resumes immediately after. Measured on the cards: rhythm 4 (rock) reads the drum block for 4 and the
accompaniment block for 5, rhythm 8 (march) 8 and 9, and Röslein, which has fill marks, reads fills
1 and 2. **`upa_extract.py` lifts all three tables out of a ROM you own into a gitignored
`upa-tables.json`**, checking the structure below before it writes; `--show` prints the patterns.

**A block is two bars of 4/4 - 192 ticks - however it is cut up.** Two header bytes come first,
flags and **ticks a step**, and then the steps, one byte each:

* 66 bytes: 3 ticks a step, 64 steps, a step being a 1/32 note;
* 50 bytes: 4 ticks a step, 48 steps, the swung grid of triplet 1/16s.

**Flags bit 7 clear means three-beat**, and the engine gets 3/4 out of a pattern stored in 4/4 by
*skipping a beat*: at `0x5111`, with the bit clear, a tick accumulator standing at `0x48` (72, the
end of the first 3/4 bar) or `0xA8` (168) has `0x18` (24 ticks) added and the step index moved on to
match, so the stored fourth beat of each bar is never played. The blocks with the bit clear are the
**waltz's** two and fills **5 and 6**, which is exactly the pair that only waltz cards use, and it
explains the hole they leave on beat 4 of a 4/4 bar.

**Nothing in either kind of block is a pitch, and nothing is a note length.** A byte is a set of
fields that hold their value, and **an event happens where a field changes** - that one rule runs
the whole engine (`0x50F1` compares the field with the last one, kept at `0xD204`).

### The accompaniment byte

Two patterns live in one byte: **the standard in the low nibble, the alternate in the high one**, and
`0xD206` says which the engine reads - 1 for the low, 2 for the high (`0x50D7`-`0x50E5`, `RRCA` four
times for the high one, then `AND 7`). **Bit 1 of the card's 3-bit header field** is what sets it:
cards with `f3` of 2, 3, 6 or 7 get `0xD206` = 2 and `0xD352` = `0x83`, and 0, 1, 4 and 5 do not.
That is the "two accompaniment patterns a rhythm" the machine advertises - one table, two nibbles.

Inside a nibble:

* **bits 0-2 are the bass**, as a number into an **eight-entry table of the chord's own notes** at
  `0xD207` - part of the engine's 17-byte state block at `0xD1FD`, refilled from the card's chord at
  `0x5165`. Measured on a C major card, the entries come back as YM2151 key codes:

  | index | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
  |---|---|---|---|---|---|---|---|
  | note | silence | root | third | fifth | sixth | seventh | octave |
  | C major | - | C3 | E3 | G3 | A3 | A#3 | C4 |

  A pattern carries chord-tone numbers, which is why one table serves every chord, and the bass
  sounds where the number changes.
* **bit 3 strikes the chord part**, on its rising edge, one step later than the byte it is in.

Both halves are confirmed against sound. Rock's standard nibble reads root, root, off, root, fifth,
fifth, off, fifth over the bar and the capture plays C on beat 1, C on 2½, G on 3, G on 4½. Rhumba's
standard chord bit rises at steps 4, 6, 12, 20 and 28 and the chords sound at 5, 7, 13, 21 and 29;
with the header bit set, the same block's high nibble predicts strikes at 5, 9, 17, 21 and 29 and
its bass walks root, third, fifth - and that is exactly what the alternate card plays.

**The chord part's pitches never come from the pattern.** Channels 3 and 4 always key the same two
notes - a root and a **flattened third**, C and E flat on a C chord - and the real chord tones come
from the FM **multipliers**, which is why a capture shows 96 writes to `0x40`-`0x5F` against 24 key
codes on those channels. Read a capture's key codes for the chord and you will read nonsense.

### The drum byte

A drum byte is a **five-bit mask in bits 7 to 3**, and a drum sounds where its bit rises. Bits 2, 1
and 0 are the constant `0x02` in every byte of every drum block in the ROM, which `upa_extract.py`
checks; what they are for is unknown.

The drums are **two FM channels, each carrying two sounds** - algorithm 4 on both, so operators 1-2
are one voice and 3-4 another - and the key-on's slot mask picks them, `3`, `C` or `F` for both at
once. Five mask bits reach four sounds, because two of them share one:

| bit | drum | where it plays | reaches |
|---:|---|---|---|
| 7 | **cymbal** | eighths in rock, sixteenths in 16-beat, every rhythm but the march and waltz | ch 6, operators 1-2 |
| 6 | **second cymbal** | rhumba, samba, bossa-nova, slow-rock only | ch 6, operators 3-4 |
| 5 | **kick** | beats 1 and 3 in rock, all four in march and disco | ch 7, operators 1-2 |
| 4 | **latin drum** | rhumba and samba only | ch 7, operators 3-4 |
| 3 | **snare** | the backbeat: beats 2 and 4 in every straight rhythm, the swung backbeat in swing and slow-rock | ch 7, operators 3-4 |

The names come from where each bit plays, and the last two columns are why **the cartridge sounds as
though it has three drums when its patterns are written for five**: the snare and the latin drum are
the *same* FM voice here, so a samba's congas come out as snares. That is the owner's ear -
"a kick, a cymbal, and a weird one which stands in for the snare and just about everything else" -
accounted for in the ROM. The five are the same five the PCS-30 has (kick, conga, snare, open and
closed hi-hat), so the patterns were written for a machine with a fuller drum set.

**The drums are played by the SFG-01, not the cartridge.** Every FM write in a capture comes from one
routine at `0x01EC` in page 0. At playback the cartridge **resamples** the drum block into a 96-slot
buffer at `0xD0D0`, one slot every two ticks, by the loop at `0x4C42`: it writes each first byte of a
pair twice and the second once, so a pair of 3-tick steps becomes 4 ticks and 2. Straight patterns
put their strikes on even steps and are untouched by that; a pattern that uses the odd steps comes
out **shuffled**, which is where a fill's fixed feel comes from. Fills are copied the same way, over
the same buffer - so a fill replaces the drums and nothing else - and they use only three of the five
bits: cymbal, kick and snare.

### Turning them into notes: the export voicing

What the tables give is a chord-tone number and a bare strike, so an export has to decide the rest,
and what the cartridge does is no help: its chord part's key codes spell a root and a flattened third
whatever the chord is, and its bass puts **every** root in one octave band whose top note is C, so a
chord on B sounds eleven semitones below one on C. The owner's own voicing, which `upa_rhythm.py`
carries and any MIDI or other export should use:

* **the chord** is root, third and fifth, plus the flattened seventh on a seventh chord, each note
  placed in the one octave band that **ends at C5** - anything that would go above C5 drops an
  octave. C major seventh comes out **E4 G4 A#4 C5**, and E major seventh **D4 E4 G#4 B4**.
* **the bass root** is **C2** for a C chord and rises to F#2, and then G and above **drop an
  octave**: G1, G#1, A1, A#1, B1. The bass never climbs out of its register, which is what the
  cartridge's own band fails to do.
* **the bass's other tones** sit above that root at the intervals the cartridge itself uses, measured
  off the engine's table on C, G and E in all four chord types: **third** (minor on a minor or minor
  seventh chord, major otherwise), **fifth** 7, **sixth** 9, **flattened seventh** 10 - flat whatever
  the chord type - and **octave** 12. So chord-tone 3 on a C chord is G2, and on a G chord D2.

These are conventions and the document says so where they appear; everything above them is measured.

**Both bars are always two bars.** A block is 192 ticks and some rhythms genuinely differ between
its halves - rhumba's second cymbal and latin drum both do - so nothing that prints or exports a
pattern may fold it to one bar.

### The arranger, and where it departs from the cartridge

`upa_arrange.py` writes the five-part MIDI: the card's melody and obbligato, and the cartridge's
bass, chord and drums. It borrows `pcs30_arrange.py`'s card walk (`marks_and_chords`, `chord_at`),
its held-note `Voice`, its MIDI writer and now its drum tables as well, so the two arrangers stay in
step. Every departure below is the owner's decision, all are in the tool's docstring, and `--as-is`
turns the lot off and plays what the cartridge plays.

* **Chords land on the beat.** The cartridge sends its chord part **one step late** - measured on
  every rhythm - which is what makes slow-rock's busy alternate sound off the beat on the real
  thing. Drop that step and every chord in all ten rhythms, both patterns, falls on a clean
  sixteenth or (on the swung rhythms) a triplet eighth: 0 exceptions in the whole table, which is how
  we know the lateness is the machine and not the data. The bass is never late.
* **Bossa-nova's last chord is moved a sixteenth earlier**, which is the one place the DATA is
  wrong. That pattern is the bossa clave - 3+3+4+3+3 sixteenths, beats 1, 2 1/2, 4, 6, 7 1/2 over its
  two bars - and its last stroke is written at 7 3/4. Two things say so rather than one: every other
  stroke is exactly on the clave, and every other chord in the block is held a quarter note while
  that one is held a quarter less a sixteenth, exactly as a stroke starting two steps late would be.
  It is the only asymmetry of its kind in the twenty patterns. The owner heard it before it was
  found, twice - it survived the first pass because a sixteenth-offbeat chord is still on the grid,
  and a grid check cannot tell a syncopation from a mistake.
* **The chord is voiced for a synthesizer**, per the section above.
* **A chord change forces the next bass note to the new root**, whatever the pattern holds there,
  the flag waiting through rests - the PCS-30's own rule, its ROM `0x173E`.
* **A fill's feel follows the rhythm.** The cartridge plays each fill in the feel it is stored in -
  1 and 2 straight, 3 and 4 swung, 5 and 6 for the waltz - and the PC-100 and PCS-30 play any fill
  in the rhythm's. The authoring system chose to match: over the corpus, fills 1 and 2 appear on the
  straight rhythms, 3 and 4 on swing and slow-rock (154 and 101 marks on swing alone), and 5 and 6
  **only** on waltz cards. So the disagreement bites about fifty marks, the biggest group being fill
  3 on disco and rock cards. The default swaps in the fill of the same rank in the matching group;
  fills 1 and 3 are the same figure in the two feels, so that one is exact, while the other pairs
  are different figures and the figure changes with the feel.
* **Notes hold, but not for ever.** A bass note runs to the next bass note. A chord rings **to the
  next beat**, which keeps the texture from smearing, and a chord caught by the chart's
  accompaniment mute is held out to the bar line instead. A chord change stops what is held - the
  cartridge instead rewrites its multipliers, so one note changes pitch, which MIDI cannot do
  without a new strike.
* **The drums are the PCS-30's by default.** Both machines have the same five drums, so the patterns
  mix, and `--drums` says how. `mixed`, the default, is what sounds best to the owner: the
  **PCS-30's patterns for the ten rhythms**, the **cartridge's own fills 1 to 4**, and the
  **PCS-30's for the waltz pair 5 and 6**. `--drums upa` is all the cartridge's and needs no PCS-30
  ROM; `--drums pcs30` is all the keyboard's. When the PCS-30's own fills are used they are indexed
  the way that keyboard indexes them - `BIT_OF_RAW[RAW_OF_MARK[mark]]`, which is a permutation of
  the cartridge's numbering, so mark 5 is its fill bit 0.

**The five drums stay apart on the GM kit** - closed and open hi-hat, bass drum, open high conga and
acoustic snare - even though the cartridge itself plays the snare and the latin drum with one voice.
Checked over the whole corpus: 264 files, no unreadable one, no overlapping note on any channel, and
every bass and chord note-on on a sixteenth or a triplet eighth.

**Still open**, and the next thing to do:

* **what bits 2-0 of a drum byte are**, always `0x02` and never anything else.
* **how the chord part's multipliers spell a chord** - the capture has them, and reading them is how
  a renderer would know what the chord part actually sounds. Channels 3 and 4 only ever key a root
  and a flattened third.
* **the chord part's voicing and octave**, and whether the third channel of the three the
  accompaniment holds (`ch5` is the bass, `ch3` and `ch4` the chord) ever does anything else.
* the rest of the engine's 17-byte state block at `0xD1FD`, and how many parts run it: `0xD206` is
  written three times at playback start, which suggests more than one.
* the **resampling**'s exact effect on the 4-tick blocks, where the copy peeks the next byte.

How it was measured, so it can be redone: `playcard --rom-reads` finds the tables, `--fm-pc` says
which code wrote each FM register (all of it the SFG's `0x01EC`, which is how the drums were traced
to the slot masks), `--watch 0xD1FF` gives the engine's own step grid to file each key-on under - far
better than a guessed tempo - and `--ram-out` catches the resampled buffer. The probe cards are ten
lines of `playcard_encode.py`: one rhythm, one chord held throughout, nothing else (see "Write a card
that does one thing" below).

## If you pick up the accompaniment

Older notes toward the same work, all still good:

- **The card's inputs to the pattern generator are now fully known**: the rhythm field picks one of
  ten styles, and the header's 3-bit field picks the standard or alternate pattern of that style.
  Nothing else on the card selects a pattern, so any capture can be attributed to a known
  selection — which is exactly what the pattern tables have to reproduce.
- The accompaniment occupies **three FM channels** (chord and bass), cleanly separated from the
  melody's and obbligato's three and the two single-pitch percussion channels. On Take the A Train:
  ch0/ch1/ch2 melody and obbligato, ch3/ch4/ch5 chord and bass, ch6/ch7 drums.
- **Write a card that does one thing.** `playcard_encode.py` builds a valid image from a `Card`
  object and verifies it before returning — CRC, and durations pairing one-to-one with pitches. A
  card that isolates one behaviour answers what no original card can, because no original card does
  only one thing; this is how marks 4, 5 and 6 were settled after corpus statistics had gone
  nowhere for two sessions. One trap it caught immediately: **a melody stream with no repeat marker
  never returns**, so playback walks straight on into the obbligato stream. No original card does
  that. `E.terminated()` is the fix and explains why.
- **Or edit a card and re-checksum it.** The CRC is understood well enough to change one field and
  repair the image, which turns any header field into a controlled experiment — capture both
  versions and diff. This is how the pattern bit was settled. Verify the edit by re-parsing: valid
  CRC, intended new value, byte-identical tracks and streams.
- `0xD352` is **settled**. Bit 0 is the one-bar alternate that mark 7 sets (`0x5F6F`, `OR 0xC1`),
  bit 1 is the header's, and the once-per-bar revert (`0x6013`) clears bit 0 *only when bit 1 is
  clear* — so the header bit is a **lock**, not a starting state. Confirmed by ear on a
  purpose-built card and its byte-identical control: with the header bit set, every mark 7 stores
  `C3` and the revert never fires once. The old note here about cards that "start alternate and
  change to standard partway" needs care: **such cards do exist** — When You Wish Upon a Star is
  alternate for bars 1-2 and standard from bar 3 — but they do it with mark 7 and a header field of
  0, never touching the lock. What was wrong was inferring from them that something can clear the
  header's bits.
- The three control opcodes are **done** and were never about the accompaniment: `0x14`/`0x13` duck
  and restore the obbligato around the melody, `0x11` is a phrase counter. What is still open from
  them is the one-bit flag at `0xD356` that `0x14` sets and `0x13` clears — written and queued
  outward, and read only by the routine that sends it, so its own effect happens in the keyboard.
  Free tempo itself is no longer open: `F5` selects it and the cartridge holds its own sequencer at
  `0x5B46`, which is measured. The flag is a separate thing from that mode byte.
- The escape opcode's sub-values are now **fully accounted for**. Value 0 silences the drums
  (restated once per bar while they stay out), values 1 to 6 are fills, and value 7 switches to the
  alternate pattern for one bar then reverts. 4, 5 and 6 were settled by writing cards that isolate
  them — see `new-cards/`.
- The six fills split **by metre, and only by metre**: 1 to 4 are four-beat patterns, 5 and 6 are
  three-beat ones, so the waltz pair leaves a hole on beat 4 of a 4/4 bar and the others are cut off
  mid-phrase in 3/4. **5 and 6 appear on 21 of 37 waltz cards and on none of the other 224.**
  That part is measured and stands.

  **Fill feel comes from the RHYTHM, and the UPA-01 gets it wrong.** On the PC-100 and the PCS-30 a
  straight rhythm plays all four fills straight and a swing rhythm swings all four; on the PCS-30
  the mechanism is visible in its ROM (bank 1 indexed by fill number alone, on a grid of 16 steps a
  bar straight and 12 swung). The UPA-01 instead gives each fill a fixed feel — 1 and 2 straight,
  3 and 4 swung — whatever the rhythm. **That is a bug**, alongside the chord dropout. The case that
  settles it is *I Could Have Danced All Night*, from the PC-100's own set: a **disco** card with **mark 3** in
  its obbligato intro, which sounds straight on a PC-100 and swung on the cartridge, and which also
  uses fill 2 elsewhere in the same straight arrangement.

  What remains open is the authoring habit: **fill 2 appears on 90 of 156 straight cards and on none
  of the 68 swing ones.** "Choosing the fill was choosing the feel" would have explained it, and
  that card rules it out. A panel emitting different mark values per rhythm would have explained it
  too — except that **the PC-100 has no fill controls at all**, so nobody was pressing anything: a
  fill reaches that keyboard only from the card. These cards came off an **authoring system about
  which nothing is publicly known**, and the habit is its, or its operators'. Do not write about
  that system as though it were a keyboard.
- **The chords are known.** The section table's values decode to `(type << 4) | YM2151 note code`,
  types 0–3 being major, minor, seventh, minor seventh. So a capture can now be checked against the
  chord the card asked for, bar by bar — which is what makes the pattern tables tractable.
- Capturing the FM chip *does* produce chords, bass and drums — imperfectly (chords drop notes,
  spurious drum hits) but enough to work out what the patterns are. **Capture timing from
  `csrc/playcard` can now be trusted** to within the YM2151 timer's own resolution, a few tenths of
  a percent: characterised on 2026-09-21 across the whole tempo range. Before that date every
  capture it made ran 4% slow — its playback loop restarted timer A's count every quarter second
  and lost a tick each time — and openMSX captures were worse, since its own tempo control rewrites
  emulated time (see the trap above). So distrust any *old* number taken from elapsed time; for new
  work the header's bpm, through the cartridge's grid of 4 (`floor(bpm/4)*4`), is what plays. The bass channel
  gives reliable chord roots. **Chord quality is readable after all, but never from the key codes**
  — see the trap below.
- A good first experiment: hand-build a minimal card that selects one rhythm and holds one chord,
  feed it through `fake_cr01.tcl`, and capture what the firmware plays. The user suggested exactly
  this and it is the cleanest way in.
