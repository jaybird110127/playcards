# Making Playcards from MIDI — a design

The format this builds on was decoded from the cartridge ROM and the cards, not from Yamaha's
patents; those were read at the end only to check the result. See "The patents" in
`playcard-format.md`.

Two tools:

* **a decompiler**, `card_decompile.py` — a card image to a MIDI file that can be edited and played
* **a compiler**, `midi_compile.py` — that MIDI back to a valid card image

Read `playcard-format.md` for the format and `HANDOFF.md` for the state of the work. Everything
below assumes both.

**Status (2026-08-23): built, compressed, measured and finished.** All four parts round-trip on
**264 of 264** cards, all **264 fit the strip**, and every one-sided original comes out smaller than
Yamaha's. Two-sided output is built as well. What building it taught that this design did not know
is marked → **in practice** below; the order-of-work section is a record of how it went rather
than a plan, and the only item still open is the last one.

Where this document and `playcard-format.md` disagree, the format document wins: it is maintained
against the firmware, and this one is a design that was partly overtaken by building it.

---

## The shape of the MIDI

Four tracks, following `midi_export.py`'s existing layout so the two stay recognisable:

| track | channel | carries |
|---|---|---|
| 1 | 1 | melody |
| 2 | 2 | obbligato |
| 3 | 3 | chord chart |
| 4 | 4 | control notes — marks, mutes, ducking |

Plus one thing worth insisting on: **the header goes in a text meta event.** Tempo, rhythm, both
voices, key, sustain and the accompaniment-pattern bit, written by the decompiler and read by the
compiler, with command-line flags overriding. A decompile → edit → recompile cycle then needs no
remembered flags.

**And the two routes are equivalent**, which is the part worth keeping true: everything either meta
line can say, an option can say too, for anyone whose editor will not write text events.

| in the file | on the command line |
|---|---|
| `tempo=` | `--tempo` |
| `rhythm=` | `--rhythm` |
| `melody=` | `--melody-voice` |
| `obbligato=` | `--obbligato-voice` |
| `transpose=` | `--transpose` |
| `sustain=` | `--sustain` |
| `pattern=` | `--pattern` |
| any raw field | `--raw FIELD=N` |

Voices take either vocabulary or a field number: `--melody-voice clarinet`, `--melody-voice CLARINE`
and `--melody-voice 6` are the same instruction. The option wins where the file says otherwise, and
`--raw` reaches the values the named options cannot express — a melody field of 0, say, or an `f3`
that is neither 0 nor 2.

### Control notes

Notes rather than controller changes, so they can be played live on a keyboard while the rest of
the song runs. A layout that falls under one hand:

| note | meaning |
|---|---|
| C1 … G1, chromatic | bar marks 0–7: drums off, fills 1–6, one-bar alternate pattern |
| C2 | `0x14` — the melody begins here: duck the obbligato, arm free tempo |
| D2 | `0x13` — the melody has run out of material |
| E2 | `0x11` — phrase mark |
| G2 | accompaniment mute |

Two traps in that table:

* **Marks and control opcodes belong to the obbligato stream only.** Not one of the 2030 marks in
  the corpus is in the melody stream. The compiler injects them into stream 1 at the opcode index
  nearest the event's tick — never into stream 0.
* **The accompaniment mute is not a control opcode.** It is the value `0xFF` in the chord chart, so
  that note routes to the chart rather than to the stream. It looks like an inconsistency six months
  later; comment it where it is handled.

A deterministic ordering rule is needed for several control events on one tick.

→ **In practice** the compiler keeps the file's own event order for events sharing a tick, and the
round-trip comparison ignores that order entirely — a bar mark, the duck, the phrase counter and
the mute each write a different piece of state, so which the stream lists first changes nothing the
instrument does. That is the honest rule: preserve what you were given, and do not count a
difference where none is audible.

---

## What MIDI can ask for and a card cannot carry

The compiler's most valuable output may be its complaints. These are hard limits, not preferences:

| constraint | consequence |
|---|---|
| durations come from a table of ten — 6, 8, 12, 16, 18, 24, 36, 48, 72, 96 ticks at 24 per quarter | no 32nds, no 16th triplets, no dotted 16ths; quantise and report every note that moved |
| **no positions at all** — a part is a gapless run of those durations | an onset off the grid cannot be stored as it stands, and since chords and marks are addressed by obbligato event rather than by time, rounding one can displace a chord by most of a bar. The report has to separate "your notes moved a fraction" from "a chord went somewhere else" |
| one duration slot per pitch event, strictly monophonic | overlapping notes in melody or obbligato need a stated policy, not a silent choice |
| four chord types: major, minor, seventh, minor seventh | diminished, augmented, sus, 6ths and 9ths must be approximated or refused |
| one tempo per card, snapped to a 32-entry table | tempo changes cannot be represented at all |
| flats are spelled as sharps of the letter below | the enharmonic choice is forced |
| alphabet of at most 25 symbols | see below — this one bites |
| 433 bytes | the strip runs out; see *two-sided cards* |
| melody G3–C6, obbligato **G2**–C6 | the range these keyboards play, as sounding pitch; a note outside it is folded by octaves until it fits |
| **62 chord-chart entries** | see below — this one bites harder than the byte limit |

→ **In practice** the obbligato's low end is **G2, not C2**. Measured off the corpus rather than
assumed: 42083 melody notes span exactly G3 to C6 and 42115 obbligato notes exactly G2 to C6, with
nothing outside either and no stragglers near the edges. Folding by octaves keeps the pitch class,
which is the least damaging thing to do to a note the instrument cannot reach, and it happens after
the monophonic reduction so which note survives a clash is still decided on the pitches as written.

### The chart's 62-entry ceiling

This design did not know about it. The section table's parse loop stops on a counter of 63 *without
reading the end-of-table marker*, so 62 is the real maximum — and the largest chart in the corpus
is exactly 62. Written out flat, **101 of the 264 cards exceed it**, against 216 that exceed 433
bytes. It looked like the binding constraint, because entries past it are simply dropped and the
card comes out musically wrong rather than merely too long.

→ **In practice** it binds nothing. The same compression cures it, and **no corpus card overflows
the table** once compressed: an entry inside a repeated body is stored once and fires on every pass,
so a card can play far more chord changes than it stores. The one card that appeared to overflow
turned out to need exactly 62 and store 62; the warning came from a discarded trial layout. New
material is a different matter — `make_test_midi.py` with a chord a bar over 128 bars needs 105
entries, and there the cap is real.

Two entries stating the same chord in a row are a no-op — the handler only writes the value to the
live chord byte — so collapsing them is free, and the tools do it in both directions. It is
nowhere near enough on its own.

### The alphabet ceiling is real

Ten lengths, each in a plain and a lift form, is 20 symbols. Add `0xFF` (repeat previous), `0xE1`
(close/terminate) and the four span markers and it is **26**, against a field that rejects 26. A card
using everything is one symbol over, so a busy card has to give something up — and since span
markers are alphabet symbols, that choice is entangled with how hard the compressor works.

No original card gets near it: the corpus runs from 8 to **23** symbols. But a generated card that
quantises freely and compresses hard can, and the compiler needs a policy rather than an assertion
failure.

### Long notes, and why the round trip can be exact

There is no long-duration symbol. A held note is a run of same-pitch events with the **lift flag
clear** on all but the last — the flag means the finger comes off at the end of *that* event, so a
run ties only while the preceding event left it down.

That is what makes an exact round trip possible. Pick one canonical decomposition — greedy,
largest-first — and splitting a MIDI note into events and merging events back into a MIDI note become
inverse operations. Without a canonical rule the trip is merely equivalent, not identical.

→ **In practice** the canonical split is necessary but not sufficient, and the reason is worth
recording. Chart entries and control opcodes are placed by *opcode index*, so either can only land
where the obbligato has an event boundary — and the largest-first split does not necessarily put
one where the music needs it. Chords drifted to the next available note until the compiler learned
to **cut the obbligato at every tick something has to be placed on** (`cut_spans`). The cut is
musically free, because the first event leaves the finger down and the pair ties back into the same
note. Taking the cuts greedily from the left strands the tail on a length the table cannot express,
so the choice is made by a small dynamic program over the wanted points.

---

## The test that decides whether any of this works

**Decompile all 267 cards, recompile them, and compare.** That is the same kind of hard number the
rest of the project runs on, and it should be quoted the same way. Two tiers, because they are very
different problems:

1. **Semantic identity** — resolved events, marks and chord chart identical. This is the real target.
2. **Byte identity** — also requires reproducing the alphabet ordering and the exact repeat
   structure. A stretch goal, and only worth it if step 1 is solid.

Anything that fails should name the card and the first differing event, not just count.

→ **In practice** it is 264, not 267: the three `_side-b` files are absorbed into their side A
rather than tested separately, which is what a two-sided card *is*. `midi_compile.py --roundtrip`
runs it, and tier 1 is where it landed — **264 of 264** on every part. Tier 2 was never attempted;
tier 1 turned out to be enough for everything that has been asked of it, and the card the compiler
writes is usually smaller than the one it read.

---

## Compression: the hard part

A span with *k* markers produces this, and only this:

```
stored     S1 [m] S2 [m] S3 [m] BODY
playback   S1  BODY  S2  BODY  S3
```

The body is the material **after** the last marker; every earlier marker calls it and the last is the
return. So the compressible shape is a refrain interleaved with different segments — which is
verse-and-chorus, which is what these songs are. Two consequences fall straight out.

**A span needs k ≥ 3 to pay for itself.** Stored costs `|B|` plus *k* markers; playback yields
`(k−1)|B|`. The saving is `(k−2)|B| − marker cost`, so *k* = 2 always loses. Cheap pruning.

**Measure the saving in card bits, not in events.** Durations are prefix codewords whose length
depends on the symbol's position in a most-frequent-first alphabet, so what an event costs depends
on how common its symbol is — and compressing changes the frequencies that set the order.
Compress first, build the alphabet from the compressed frequencies, then iterate once if it matters.

### The four structures compress independently

A duration track and its opcode stream do **not** have to share a repeat structure. They are
resolved by the same back-fill with the same four span slots, but nothing couples them: across the
corpus **517 of 522 part-pairs place their markers at different events**, in different numbers.
Silent Night's melody uses spans 0 and 1 in both, but seven markers in the track against six in the
stream, at different positions.

That decoupling is the good news. As long as each structure resolves losslessly back to its own
sequence, the one-to-one pairing that the whole format depends on holds automatically. So this is
four separate compression problems, not one joint one.

Real cards nest, too: Silent Night's span-1 markers sit inside span 0's body, so calling span 0
executes span 1's structure as well.

→ **In practice** three things decided the design.

**The tail is laid out consecutively as `[m1] BODY1 [m2] BODY2 ... [mN] BODYN`**, because a call to
span *i*'s body starts just past span *i*'s last marker and runs until the next RETURN — and the
next return is span *i+1*'s last marker, which the back-fill rewrites into one. **That layout does
not stop the spans nesting, and an early version of this note said it did.** The bodies sit one
after another in the tail; what nests is which *material* a body covers, and a later span's body may
lie inside an earlier one. Reading it the other way is what kept the first compressor from ever
producing the shape the originals use — see step 4 below, where fixing it was the whole difference.

**The last body needs a terminator after it**, which is why `E.terminated()` still goes on even when
a stream is compressed.

And **counting symbols picks the wrong body** in a duration track: codewords run from 2 bits to 14
depending on where the symbol sits in the alphabet, so a repeat built of rare symbols is worth far
more than the same number of common ones. Costing in bits rather than symbols moved seven more
cards under the limit on its own.

### A starting algorithm

1. Build the event sequence for one structure.
2. Enumerate maximal repeats. Sequences are only a few hundred events, so a suffix array — or even
   O(n²) — is fine.
3. For each candidate body *B*, test the alternation: occurrences non-overlapping, in order, and the
   sequence decomposing as `S1 B S2 B … Sk`. Score by `(k−2)|B|` in bits.
4. Take the best, emit it, then recurse into the body with the next span. Four available.
5. **Resolve the result and compare against the original sequence.** Reject any span that does not
   reproduce it exactly. Same discipline as everywhere else here — the resolver is the oracle.

And do not forget the terminator rule: a structure carrying any marker needs *two* closing records,
one to close the span and one to end it. That single omission is what made an early version of
`make_random_card.py` emit spans that silently failed to resolve.

---

## Settled: where a chord chart entry fires

**One entry, one chord change, at the obbligato's opcode index.** The melody stream's copy never
reaches the handler.

This was worth checking because the cartridge walks the chart on every decoded opcode of *both*
streams, so an entry at position *P* looks like it should also fire at the melody's opcode *P*, at a
different musical time. A card built to separate the two — sixteenths in the melody against whole
notes in the obbligato, putting position 17 in bar 2 of one and bar 17 of the other — shows the
record arriving 0.05 s before the obbligato's seventeenth note and nowhere near the melody's, with
43 seconds of silence in between. See "a chart entry fires once" in `playcard-format.md`.

**So a compiler places chords by obbligato opcode index, and does not need to reason about the
melody at all.** Take the tick of each chord in the MIDI, find the obbligato opcode running at that
tick, and emit the entry there.

## Order of work

1. **The decompiler.** ✅ Done. Nearly free, as predicted — `playcard_resolve.py` already
   gives playback order and `midi_export.py` already had most of the writer.
2. **The compiler without compression.** ✅ Done. Melody and obbligato match on 264 of 264
   cards; chords and control events match on all 163 whose chart fits without compression.
3. **Compression.** ✅ Done, in `playcard_compress.py`. Up to four spans per duration track and
   three per opcode stream — span 0 stays reserved for `E.terminated()`, whose `E1 10` is what
   lets the back-fill close a span whose body is nothing but notes. *At this step* it took 208 of
   264 cards under the 433-byte strip against 48 flat, and 259 of 264 charts under the 62-entry
   table against 163 — but the result was still a median **+8 bytes** against the original card,
   with only 98 of 261 coming out smaller. Steps 4 and 5 are what fixed that; the numbers here are
   where it stood, not where it ended.
4. **Nesting.** ✅ Done, and it was the whole difference. **897 of 897** multi-span structures in
   the corpus nest one span inside another, and the first compressor never did — it searched the
   flat sequence and blocked each chosen body's region, which forbids exactly the shape the
   originals use. Searching the sequence the *previous* round produced fixes it: a later span's
   body may then lie inside an earlier one, and the tail layout `[m1] BODY1 [m2] BODY2` already
   supported it. The round trip went from 260 of 264 to **264 of 264**, cards fitting the strip
   from 209 to **249**, and the result from a median +8 bytes against the original to **-6**.
5. **Fitting the strip.** ✅ Done. **261 of 261** one-sided cards now fit, every one smaller than
   the original, median **-33 bytes**. The insight that did it was a format one rather than
   compressor tuning: the chord chart is grouped by VALUE rather than sorted by position, so it pays
   one set-value record per distinct chord instead of one per change.

   The LIFT bit looked like a second such saving and **was withdrawn**. Nothing in the decode reads
   it except to choose tie against re-strike, so it appears free everywhere else and giving free
   events whichever form was commoner saved a symbol on many cards — but it plays *staccato*, since
   the keyboard lifts the key at the end of every event carrying the bit. Setting it only where a
   tie must become a re-strike costs a median 5 bytes a card against that version and is what the
   originals do. Round trip unaffected at 264 of 264.
6. **Two-sided output.** ✅ Done. `playcard_encode.build_sides()` writes the pair and
   `midi_compile.py --sides auto|1|2` chooses; `auto` splits only what will not fit, which takes the
   round trip to **264 of 264 fitting the strip**. The split is the format's own and not a choice of
   where to cut — side A is the header and both duration tracks, side B is the chart and both
   opcode streams — so it does not halve a card, and a piece whose SECTION alone overflows cannot
   be helped by it. Verified against the firmware: both sides of a generated pair return the same
   codes as Yamaha's own, `0x01` then `0x02`, and a lone side B is refused with `0x80`.

   `make_test_midi.py` is what tested it, and writing music that never was a card found two things
   the corpus cannot show. **Side B is always the binding half** — opcode streams do not compress
   the way duration tracks do, so a piece grows out of side B while side A still has room, and
   since the split point is the format's own there is nothing to rebalance. And **new material
   really can overflow the 62-entry chart**: a chord change every bar over 128 bars needs 105
   entries. No original comes near that, so the cap had never been reached by anything but a
   discarded trial layout.
7. **Byte-identical round trip**, if it earns its keep. Still untested and still optional.
8. **A looser span-acceptance rule**, which would buy a few chart entries. Not needed — no card in
   the corpus overflows the table — but it is where the remaining gap against Yamaha sits, and it is
   worth writing down.

   `chart_agrees` only folds occurrences of a body whose chart entries match **exactly**; anything
   else is excluded from the span. Yamaha's are looser. On the easy-playcard *Moon River*, their
   card recycles **25 of its 60** entries through repeated bodies where mine recycles 18 of 62 —
   and the price they pay is visible in the same card: **2 of its 5 restatements are created by the
   fold**, a body firing again where that chord is already sounding, which is inaudible.

   So the rule could be relaxed to accept a mismatch whose extra firing merely restates the live
   chord. The catch is that "the live chord at that point" depends on the folding being decided,
   which makes it circular; it needs the accept test to run against a provisional playback order
   rather than the flat one.

### The escape hatch

For anything still over the limit the format has its own answer: **two-sided cards**, durations on
side A and pitches on side B. That is how the originals handled pieces that would not fit, and it
is built — `midi_compile.py --sides auto|1|2`, described in step 6. The flag is `--sides` and not
the `--two-sided` this design first imagined, because `auto` — split only what will not fit — is
the useful default and a boolean could not say it.

---

## Things found by building it

**A chart entry on an unplayable root is NOT a mute.** This section said it was, and that was
wrong — the correction is kept here rather than deleted, because the wrong reading is the one a
capture on the cartridge supports and anyone re-deriving it from the UPA-01 will reach it again.

47 entries across 22 cards carry a low nibble of 3, one of the YM2151's unused note codes and the
same one the pitch stream uses for a rest, so the entry cannot sound *as a root*. A purpose-built
card measured what the cartridge does with them: it stops the chord channels and the bass exactly as
`0xFF` does. But that is the UPA-01 **failing to implement a convention**, not the meaning. They
mean **"the root already sounding, with this quality ORed on"**.

The PCS-30 implements it explicitly: its converter at `0x28BA` maps the chip's unused codes to
`0xFF` = *do not update the root*, then ORs the type nibble onto the chord already playing, so
`0x23` over a sounding C gives C7. The corpus agrees four ways — every change one of them makes
adds a **seventh**, none moves the root, 61 of 83 produce the chord already sounding, and **not one
of the 83 falls on a bar line** while `0xFF` mutes cluster 6 to 12 ticks after a downbeat. The 22
cards were pressed 1982-85, against a 1984 keyboard and a 1985 cartridge, so the machine they were
written for is the one that cannot be checked here.

So the tools do **not** map them to `0xFF`. `card_decompile.py` writes the resulting chord out in
full and a recompiled card states it as an ordinary entry, which plays the same on either machine.
See `new-cards/make_mute_test.py` and playcard-format.md.

**Placing the duck and phrase opcodes automatically works.** The design left this alone, and it
turns out the melody predicts them closely. Placing `0x14` at every melody onset with at least half
a bar of silence before it, `0x13` where the melody falls silent for two bars or more, and `0x11`
every four bars from the start reproduces the original ducked/not-ducked state on **97.0%** of all
obbligato notes in the corpus, against 81.3% for a card that simply ducks throughout. The median
card scores 0.98, and 243 of 264 score above 0.90.

The entry threshold barely matters — 48, 72 and 96 ticks score identically — and that is the
"assertions, not brackets" property turning up as a measurement: restating `0x14` inside an
already-ducked passage changes nothing at all.

**`0x11` follows the tune, not the bar line.** It divides the card into the passages the keyboard's
repeat-practice feature offers, so it lands where a passage can actually be started from: 84.3% of
the corpus's 3109 marks sit exactly on a melody note onset, against 41.3% on a bar line, and exactly
one falls part-way through a melody note. A tune that enters on an upbeat therefore gets its mark on
the upbeat and not on the downbeat before it. Walking a four-bar grid but landing each mark on a
melody onset within three beats reproduces **1736** of the 3109 exactly against **862** for a plain
bar grid, and never leaves one mid-note. See `place_phrases` and playcard-format.md.

Bar marks are **not** placed automatically and should not be. Which fill sounds and where the drums
drop out is an arrangement decision rather than a consequence of the tune, and mark 0 means silence
rather than nothing.

---

## A curiosity worth remembering

The PCS-30's own built-in demos use durations of 3, 4 and 9 ticks, which are **not in the card
master table**. The internal representation is slightly richer than anything a strip can carry, so a
MIDI file could legitimately want a 32nd note and there would be no way to express it on a card.
Quantisation is not laziness here; it is the format.
