# Sample Playcards

Cards written from scratch as MIDI files and compiled with `midi_compile.py`, kept here as worked
examples. Each one is a `.mid` you can open in any sequencer and the `.bin` it compiles to.

| file | what it is |
|---|---|
| `roslein.mid` / `roslein.bin` | Schubert: Heidenröslein, D. 257, arranged for Yamaha Playcard by Jayson Smith. 32 bars, 120 bpm, rock, piano melody over a clarinet obbligato, transposed +5. 222 bytes of the 433 the strip holds |
| `Szla_Dzieweczka.mid` / `Szla_Dzieweczka.bin` | *Szla Dzieweczka Do Laseczka*, a Polish folksong, arranged for Yamaha Playcard by [Daniel Kisielewski](https://github.com/dannyboy1996). Demonstrates strategic drum and accompaniment mutes, fills, and use of the alternate accompaniment pattern. Also demonstrates handling of a MIDI without a text record. To properly compile, pass `--obbligato clarinet` as a command line argument. |

More examples may be added in the future. The rest of this file is how to make your own. **Every command below is run from the repository
root**, one folder up from here.

---

## The short version

A Playcard is a four-part arrangement. You write those four parts as four MIDI channels, add a line
of text saying what the keyboard's front panel should be set to, and compile:

```bash
python midi_compile.py mysong.mid -o mysong.bin
```

```
mysong.mid -> mysong.bin
  222 bytes of 433   120 bpm  rock   alphabet 16 of 25
```

That is a card. To check a real keyboard will take it:

```bash
python card_limits.py mysong.bin
```

```
mysong.bin                                       222 bytes on the strip
   decodes to 509 bytes of the 4080 the firmware allows (12%)
   the UPA-01 ACCEPTS it: a complete one-sided card
```

**One rule before you start: quantise.** A card has no timestamps, so a note that is not exactly
on the beat cannot be stored as it stands, and the chords and bar marks — which are addressed by
position rather than by time — can land somewhere else entirely. See "Quantise first" below. It is
the one mistake that produces a card that compiles cleanly, sounds nearly right, and has its
harmony in the wrong place.

**The fastest way to learn the conventions is to read one.** Take any card and decompile it — the
result is an ordinary MIDI file with everything in place, and you can copy its shape:

```bash
python card_decompile.py somecard.bin -o somecard.mid
```

---

## The four channels

Channels, not tracks. The compiler throws track structure away, so four tracks of one channel each
and one track carrying all four channels compile to exactly the same card. Use whichever your
editor makes pleasant.

| channel | part | notes |
|---|---|---|
| **1** | melody | monophonic, G3–C6 |
| **2** | obbligato | monophonic, G2–C6 — the countermelody, and the part everything else hangs off |
| **3** | chord chart | play the chords as chords; the compiler works out their names |
| **4** | control notes | bar marks, ducking, the mute — see below |

Notes on any other channel are ignored, and you are told so.

**Write everything at the pitch you want to hear.** The card's key field is a storage trick, not
something you compose around: the compiler transposes for you, and if a card will not fit the strip
it will try the other eleven keys to make it fit, and say so. Channel 3's chords are at sounding
pitch too.

### Channel 2 deserves a word

The obbligato is not decoration. **The chord chart and every control opcode are addressed by
position in the obbligato's note stream**, so a chord change can only land where the obbligato has
a note boundary. The compiler cuts the obbligato at every point something needs to be placed — the
cut is inaudible, since the two halves tie back into one note — but it cannot cut what is not there.

If channel 2 is empty you get a warning, and you should believe it: the part becomes one long rest,
and the marks and chords have nowhere to sit but the beginning.

---

## Control notes, on channel 4

These are notes rather than controller messages so you can play them in live on a keyboard while
the rest of the song runs. They sit under one hand at the bottom of the keyboard. **Only the onset
matters** — length and velocity are ignored, so one tick is plenty.

Every one of them is a **request to the instrument**, not a sound. The card says "fill 3 here"; what
fill 3 actually plays lives in whichever keyboard reads the card, and the machines differ — the
PC-100, the PCS-30 and the UPA-01 cartridge all have their own patterns, and the cartridge is known
to get the *feel* of a fill wrong. So the marks below say what you are asking for, and the answer
depends on where you play it.

| note | MIDI # | what it does |
|---|---|---|
| **C1** | 24 | mark 0 — **drums off** for this bar |
| **C♯1** | 25 | mark 1 — drum fill 1 |
| **D1** | 26 | mark 2 — drum fill 2 |
| **D♯1** | 27 | mark 3 — drum fill 3 |
| **E1** | 28 | mark 4 — drum fill 4 |
| **F1** | 29 | mark 5 — drum fill 5 *(three-beat: for waltzes)* |
| **F♯1** | 30 | mark 6 — drum fill 6 *(three-beat: for waltzes)* |
| **G1** | 31 | mark 7 — the **alternate** accompaniment pattern, for one bar |
| **C2** | 36 | the melody starts here: duck the obbligato under it |
| **D2** | 38 | the melody has run out of material: bring the obbligato back up |
| **E2** | 40 | passage division — a phrase mark for the keyboard's practice feature |
| **G2** | 43 | accompaniment mute: bass and chords stop until the next chord |

### Things about them that will catch you out

**Marks are one bar long and do not latch.** Mark 0 silences the drums for *that bar only*, so to
keep them out for eight bars you put a C1 in each of the eight. Mark 7 is the same: one bar of the
alternate pattern, then back. This is how the original cards do it, and it is why a corpus card can
have a hundred bar marks in it.

**Fills 5 and 6 are three-beat patterns.** Use them in a waltz. Used in 4/4 they leave a hole on
beat four; fills 1–4 used in 3/4 get cut off mid-phrase.

**The drum mute and the accompaniment mute are different mechanisms.** Mark 0 (C1) stops the drums.
G2 stops the bass and chords. That is why a card can silence one and keep the other — and why they
are un-done differently. Drums come back when you stop putting C1 in the bar; the accompaniment
comes back at the next chord on channel 3.

**Several control notes on the same tick are fine.** Channel 4 never goes through the
one-note-at-a-time reduction the melody and obbligato do, so a bar mark, a duck and a mute can all
sit on the same beat and nothing is dropped or complained about. Stack them freely.

**But they only work on channel 4.** This is the easiest mistake to make and the hardest to see: a
control note that lands on channel 1 or 2 is *music*, and the card has no way to know you meant
otherwise. F1 on the melody channel is not a fill — it is an F below the melody's range, which gets
folded up three octaves into the tune, or dropped if a real note is sounding over it. The compiler
now says so in as many words:

```
! 2 control notes on channel 1, where the card reads them as melody and not
  as controls - move them to channel 4 (2): tick 4248, F1 = mark 5;
  tick 4896, C2 = duck (0x14)
```

If your editor puts everything on one track, check the channel assignment of each control note
rather than trusting where it sits in the piano roll.

**C2 and D2 are assertions, not brackets.** The original cards restate C2 at every re-entry of the
melody rather than strictly alternating C2 … D2 … C2. Either way works.

**If you leave channel 4 empty, the compiler fills in C2, D2 and E2 for you**, working them out from
where the melody enters and rests. It tells you it did. `--auto-control off` stops it; `on` makes it
do so even where your file has some of its own.

---

## The header

Everything the keyboard's front panel would be set to travels in a text meta event at the top of
the file. Put this on the tempo track:

```
Playcard: tempo=120 rhythm=rock melody=piano obbligato=clarinet transpose=+5 sustain=off pattern=standard
```

| field | values |
|---|---|
| `tempo=` | bpm; snapped to the card's 32-entry table (40, 48, 52, 56, 60, 63, 66, … 184, 192, 200) |
| `rhythm=` | rhumba, samba, swing, bossa-nova, rock, 16-beat, waltz, slow-rock, march, disco |
| `melody=` | organ, trumpet, clarinet, piano, guitar, piccolo, violin, oboe, harpsichord, vibraphone |
| `obbligato=` | oboe, flute, strings, brass, clarinet, piano, harpsichord, guitar |
| `transpose=` | −6 to +5 semitones |
| `sustain=` | on, off |
| `pattern=` | standard, alternate — `alternate` locks the alternate accompaniment on for the whole card |

**If your editor will not write text events, every one of those has a command-line option instead**,
and the option wins where both are present:

```bash
python midi_compile.py mysong.mid -o mysong.bin \
    --tempo 120 --rhythm rock --melody-voice piano \
    --obbligato-voice clarinet --transpose +5 --sustain off
```

The voice names are the PC-100's front panel. The SFG-01 cartridge's names — `EPIANO1`, `CLARINE`,
`STRING1` and so on — are accepted as aliases everywhere, as are the raw field numbers.

A decompiled card also carries a second line, `Playcard-raw:`, holding the header's actual bit
fields. The compiler prefers it when both are there, so a decompile-edit-recompile cycle cannot
drift through a name lookup. Delete it if you want to edit the friendly line.

---

## What MIDI can say and a Playcard cannot

This is the part worth reading before you write 200 bars. None of it is a preference; these are the
format's own limits, and the compiler reports every one it had to work around rather than silently
doing something to your music.

### Quantise first. Notes have to sit exactly on the beat

**This is the single most likely thing to go wrong, and the hardest to see afterwards.** Get it
right and most of the rest of this section stops mattering.

A Playcard carries no timestamps. Each part is a **gapless run of durations**, so a note's position
is nothing but the sum of everything before it, and there is no way at all to say "this note is a
fraction late". Anything that does not land on the grid has to be rounded to something that does.

The melody survives that; a note a fraction early or late still sounds like the note. **What does
not survive is everything addressed by position** — and on a Playcard that is the chords and the bar
marks. They are placed at the obbligato event running underneath them, so if an obbligato note has
been nudged, the chord that belonged with it can find nothing to sit on and slide forward to the
next event. It does not slide by a fraction. It slides to wherever the next note is, which can be
most of a bar:

```
! 2 chord and control events moved to the next opcode, having no event of
  their own to sit on - they do not move by a little, they move to wherever
  the next note is, so check these; quantising the file usually removes them
```

That warning is the one to take seriously. A chord change two beats from where you put it is
obvious on playback and invisible in the file, and the melody around it is untouched, so nothing
looks wrong.

**Quantise in your sequencer before exporting** — to a 16th, or an 8th triplet if the piece has
triplets in it. Not by hand, and not by eye: the offsets that cause this are far too small to see
in a piano roll. One real case had 47 onsets exactly **half a card tick** late — a 48th of a beat,
inaudible, invisible — and it moved two chords and cost 29 note lengths. Quantising the same music
to a 16th fixed every one of them, and the card came out **39 bytes smaller** into the bargain,
because a note on the grid needs a length the format already has.

| the same music | card | what the compiler had to do |
|---|---:|---|
| as exported, 47 onsets half a tick late | 377 bytes | 47 positions moved, 29 lengths quantised, **2 chords displaced** |
| quantised to the nearest 16th | **338 bytes** | nothing |

**Quantise to note values, not to the card's tick.** Rounding each onset to the nearest whole card
tick is *not* enough and can make things worse: a tick is a 24th of a quarter note, and the format
has only ten lengths, so an onset can sit on an exact tick and still be unreachable by any sum of
them. Snapping to the nearest tick rather than the nearest 16th, on the same file above, moved
**four** chords instead of two.

Set your sequencer to 24, 48, 96 or 480 ticks per quarter while you are at it. Those all divide
evenly into the card's 24 per quarter, so nothing has to be rounded at all, and you are told when
something did:

```
! 2 note positions do not land on the card's 24 ticks per quarter and were
  moved, the worst by 0.25 of a tick - the file is written at 480, so
  quantise to a 16th or an 8th triplet. Small as that is, it is what
  displaces chords: those are placed at the obbligato event underneath them
  rather than at a time of their own
```

Note *lengths* are reported separately from note *positions*, and for a good reason: many
sequencers write every note a tick or two short so its note-off does not collide with the next
note-on. That is not your music being altered and it is not counted — a discrepancy of one tick of
the source file's own resolution is ignored entirely.

### Note lengths: ten, and no others

| ticks (24 = a quarter) | 6 | 8 | 12 | 16 | 18 | 24 | 36 | 48 | 72 | 96 |
|---|---|---|---|---|---|---|---|---|---|---|
| | 16th | 8th trip | 8th | qtr trip | dot 8th | quarter | dot qtr | half | dot half | whole |

**No 32nds, no 16th triplets, no dotted 16ths, no double dots.** Anything else is rounded to the
nearest of the ten and counted in the report.

Notes *longer* than a whole note are fine — they are stored as a run of tied events, and the
compiler handles that for you. Rests are just gaps.

### One note at a time on channels 1 and 2

Both parts are strictly monophonic. Where two notes overlap the compiler keeps the higher one and
tells you what it dropped or cut short. Decide it yourself if you care which survives.

### Four chord types

Major, minor, seventh, minor seventh. That is the whole vocabulary.

Play the chord as actual notes on channel 3, in any voicing or inversion — the compiler identifies
it by pitch class, and a missing fifth costs nothing. But **diminished, augmented, sus, 6ths, 9ths
and everything else must be approximated**, and you will be told exactly what happened:

```
! 1 chords the card cannot spell exactly
```

and with `-v`, exactly which note went where:

```
! chords the card cannot spell exactly (1): tick 0: F# does not fit Cm; it is
  dropped
```

Three more things about channel 3:

* **A chord change is an onset.** Notes starting on the same tick are one chord. How long you hold
  it makes no difference — the next onset replaces it.
* **Restating the same chord does nothing** and is dropped, so you can re-strike every bar for
  playability without spending anything.
* **The chart holds 62 entries.** Repeats are found and compressed, so a chord inside a repeated
  section is stored once and played every time round — no original card ever overflows. But a
  through-composed 128-bar piece with a chord a bar needs 105 entries and will not fit. If you get
  the warning, either repeat more or change less often.

### One tempo, and no changes

A card has a single tempo, snapped to the 32-entry table. **Tempo changes cannot be represented at
all**, and this one is quiet: a `set tempo` event partway through your file is not an error and you
are not warned, the **last** one in the file simply becomes the card's tempo. The same goes for a
time-signature change. Set both once, at the top.

Two small conveniences that follow from that. If you leave `tempo=` out of the text event, the
compiler takes the tempo from the MIDI itself and tells you when it had to snap it — *"tempo 137 bpm
is not in the card's 32-entry table, stored as 138"*. And in that case a **3/4 time signature also
picks the waltz rhythm** for you. Put `tempo=` in the text and it does neither: what you wrote is
what you get.

### Ranges

Melody **G3–C6**, obbligato **G2–C6**, in sounding pitch — the range these keyboards physically
play. A note outside it is folded by octaves until it fits, keeping its pitch class, and counted.

### Everything else MIDI has

Ignored, silently, because there is nowhere to put it: velocity, program changes, pitch bend, the
sustain pedal and every other controller, aftertouch, and any channel past 4. Velocity in
particular looks like it should matter — a decompiled card writes ducked obbligato notes at velocity
75 so they sound right in a player — but it is decoration, and nothing reads it back.

### 433 bytes

The strip. If you go over, the compiler first recompiles in each of the other eleven keys and keeps
the smallest that fits — an accidental costs a whole extra opcode, so the same music can vary by a
fifth of the strip between its best key and its worst. Failing that, `--sides auto` splits it across
a two-sided card. `--no-refit` turns the key search off.

---

## Reading the report

Everything the compiler had to change is listed. Here is a file that gets nearly everything wrong:

```
bad.mid -> bad.bin
  37 bytes of 433   138 bpm  rock   alphabet 6 of 25
  ! 1 melody notes dropped, a higher note is already sounding
  ! 4 melody events quantised to a length the card can express
  ! 1 melody notes outside the keyboard's G3-C6 range, moved by octaves to fit
  ! 1 control notes on channel 4 that mean nothing, ignored
  ! placed 2 duck and 1 phrase opcodes from the melody, because the file
    carried none
  ! 1 chords the card cannot spell exactly
  (--verbose names every one)
```

Add `-v` and each line expands into the individual events, with ticks, so you can go back and fix
them. **A report with warnings still wrote a valid card** — these say what was changed, not what
failed.

---

## Hearing it

Three ways, in order of how much you need installed.

**Play it through the real firmware**, if you have the ROM images (see
[Roms/README.md](../Roms/README.md)):

```bash
cd csrc && make && cd ..
csrc/playcard "Sample Playcards/roslein.bin" -o roslein.fmlog
csrc/fmlog2wav roslein.fmlog roslein.wav --normalize
```

That is the actual Yamaha code decoding your card, so it is the answer to *what the card says* —
nothing in those two programs understands the format. What you hear, though, is the **UPA-01
cartridge's** rendering on an SFG-01: a 1985 port with its own accompaniment patterns and its own
bugs, not what a PC-100 would make of the same card. Use it to check your arrangement, not to judge
how a fill or a chord voicing will sound on other hardware.

**Export it back to MIDI** and listen in your sequencer — melody, obbligato and chords, no
accompaniment:

```bash
python midi_export.py "Sample Playcards/roslein.bin" -o roslein-check.mid
```

**Play it into a real keyboard.** `card_to_swipe.py` turns the image into the audio a card reader
would have heard; feed that to a coil held against the tape head:

```bash
python card_to_swipe.py "Sample Playcards/roslein.bin" -o roslein-swipe.wav
```

---

## A checklist

- [ ] Melody on channel 1, obbligato on channel 2, chords on channel 3, control notes on channel 4
- [ ] Both note channels monophonic
- [ ] **Everything quantised to a 16th or an 8th triplet, in the sequencer, before exporting**
- [ ] Written at sounding pitch
- [ ] Chords are major, minor, 7th or minor 7th
- [ ] Channel 2 has notes in it wherever a chord or a mark needs to land
- [ ] Bar marks repeated in every bar you want them to apply to
- [ ] One tempo for the whole piece
- [ ] A `Playcard:` text event, or the equivalent options on the command line
- [ ] `card_limits.py` says the UPA-01 accepts it

---

## Where to read more

* [../README.md](../README.md) — the tools, one by one
* [../playcard-format.md](../playcard-format.md) — the format itself, in full
* [../midi-roundtrip-design.md](../midi-roundtrip-design.md) — why the round trip is shaped this way
* [../new-cards/README.md](../new-cards/README.md) — cards written to answer one question each, with
  the scripts that build them: a different way in, if you would rather write Python than MIDI
