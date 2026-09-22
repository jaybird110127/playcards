# How the PCS-30 makes its sound

This is not about the Playcard format. It is about one keyboard, the Yamaha **PCS-30** (1984), and
how it turns what a card asks for into sound: its sound chip, its voices, the analogue filters
behind them, its drums and its tempo. It is here because the PCS-30 is the second machine whose
firmware this project can read, and because a synthesizer that sounds like it - playing cards with
the PCS-30's own accompaniment patterns, which `pcs30_arrange.py` already reproduces - is now within
reach. For the format itself, read `playcard-format.md`.

Nothing here comes from a PCS-30 service manual or schematic; none has been found anywhere, and
neither has one for the Portasounds that share its chip. It comes from three places:

* the **PCS-30's own ROM**, read the same way the rest of this project reads the UPA-01's;
* the datasheet of the **YM2163**, a close relative of the PCS-30's chip (below);
* **recordings of a real PCS-30** playing about sixty original cards, made by the card owner. They
  are not in this repository. Each was lined up against the PCS-30 arrangement of its card, which
  says what should be sounding at every moment, and measured where a part sounds on its own -
  "How the recordings were measured", below, has the method and its traps.

How sure each finding is gets said where it is made.

## The sound chip

The PCS-30's sound chip is the **YM2142**, which is undocumented. The PCS-30 drives it exactly as
the **YM2163** "DSG" (Digital Sound Generator) is documented to be driven, and that datasheet
survives. Both are listed with the same features: four melody channels with five preset
waveforms, four rhythm voices, a 7-bit DAC, a 14-bit timer, four melody outputs and two rhythm
outputs. The YM2142 is also in the PSS-150, PSS-160 and PSS-450 Portasounds.

The CPU reaches the chip through one port, `0xE030`: a byte with bit 7 set is a register address,
and the next byte's low seven bits are its data, as the datasheet describes. The PCS-30 writes four
groups of registers, one register a channel:

| register | bits (YM2163 datasheet) | what the PCS-30 writes |
|---|---|---|
| `84H`-`87H` | key-on, octave, pitch | a note number, below |
| `88H`-`8BH` | E2 E1 (envelope, bits 6-5), SUS (bit 4), -, W3-W1 (waveform, bits 2-0) | each voice's settings |
| `8CH`-`8FH` | VL2 VL1 (volume, bits 5-4), F4-F1 (output pins OR4-OR1, bits 3-0) | each voice's level and routing |
| `90H` | HHD, HHO, SDN, HC, BD (bits 4-0) | the drum strike, one bit a drum |

**Pitch is where the two chips differ.** The YM2163 takes a 10-bit frequency divider in `80H` and
`84H`. The PCS-30 never writes `80H`: at `0x0D5D` it turns a note into **octave × 16 + semitone**
(four octaves, the semitone counted from 0 or 1 to 12) and writes that, with `0x40` for key-on, to
`84H`. So the YM2142 has a note table of its own.

**Volume** is two bits: `00` 0 dB, `01` −6 dB, `10` −12 dB, `11` off. **The four output pins** are
what the datasheet calls "filter select": a channel can be sent to any of them, and a keyboard puts
a different analogue filter behind each. (A Japanese hobbyist's YM2163 MIDI module, MARS 21, uses
the same four pins as extra volume steps instead - binary-weighted resistors into one amplifier -
which shows the pins themselves are plain outputs and the character is added outside the chip.)

The PCS-30 has four melodic parts, which is exactly the chip's four channels: **melody,
obbligato, bass, and a single-line chord part**. The drums are separate.

**Neither chip has an emulator anywhere** - MAME has no YM2142 and no YM2163 - so nothing can be
checked against a known-good implementation. Everything below is the datasheet, the ROM, or a
measurement.

## Waveforms

The datasheet draws five waveforms, 32 steps a cycle, each step held (a staircase):

| code | name | shape |
|---:|---|---|
| 1 | **St** (strings) | a rising sawtooth, −31 to +31 in steps of 2 |
| 2 | **Or** (organ) | −20 for 8 steps, +4 for 8, then 0 for 16 |
| 3 | **Cl** (clarinet) | a square: −25 for 16 steps, +24 for 16 |
| 4 | **Pf** (piano) | −30 for 8 steps, +12 for 8, then 0 for 16 |
| 5 | **Hc** (harpsichord) | a narrow staircase pulse, then 0 |

Two are confirmed against the recordings to within the measurement: **St** exactly (three solo
guitar notes, 1.1 dB), and **Pf**, whose 4th, 8th and 12th harmonics are missing from the piano -
50 to 77 dB down - as that 8/8/16 shape requires. For **Hc** the recordings choose where the
drawing's steps fall: −31 at step 0, −5 at 1-3, 0 at 4-6, +5 at 7, +10 at 8, +31 at 9-10, and 0
from 11, which fits seven clean harpsichord notes within 0.9 dB. **Or** is used by no PCS-30 voice.

## Envelopes

Four, each with sustain off or on, drawn in the datasheet as straight lines:

| envelope | sustain off | sustain on |
|---:|---|---|
| **0** | instant attack, a fall toward ½ over about 60 ms, then a slow decay over about 1.2 s; stops at key-off | the same decay carries on past key-off |
| **1** | a 60 ms attack, holds, a 120 ms release | the same, with a 1.2 s release |
| **2** | instant attack, a 60 ms fall to ½, holds, a 60 ms release | the same, with a 1.2 s release |
| **3** | on and off at once, like an organ | a 1.2 s release |

Envelope 0 is the one that decays by itself; 1 to 3 hold while the key is down. The times are the
datasheet's, and presumably scale with the chip's clock; they have not yet been measured on the
PCS-30.

**Every note is keyed, but the attack starts from where the level already is.** That is the one
model that fits two things heard in the recordings: a sustaining voice - the flute opening Here
Comes Santa Claus, brass - moves from note to note with no dip at all (the level holds within
0.2 dB across note changes), while the harpsichord opening Love Theme is struck afresh on every
note, even notes that follow with no lift. A voice already at full level has nothing to climb; a
decaying one jumps back up.

## The voices

The voice table at ROM `0x2CFC` holds a (`88H`, `8CH`) pair for each voice, and two tables map the
card's voice fields onto it: `0x1BA3` for the melody, `0x1BAD` for the obbligato.

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

The PCS-30's own panel offers only six of these - violin, organ, clarinet, piano, guitar and
vibraphone. Trumpet, oboe, piccolo and harpsichord exist for cards.

**The accompaniment's voices.** The chord part takes its entry from a table by rhythm, `0x2D12`,
or `0x2D1C` when the alternate pattern is on (`0x0EB7`): the **guitar** (entry 3) for rhumba,
samba, swing, bossa-nova, 16-beat, waltz and disco, the **piano** (entry 2) for rock, slow-rock
and march, and the other way round on the alternate pattern. A guitar chord part is played a
volume step down (`0x0EC8`). **The bass is always entry 2**, the piano's settings - the Pf
waveform, the decaying envelope, the dark OR3 (`0x0F0C`); `0x0F2D` also drops it a step on
slow-rock in one mode, not yet pinned down.

**The bass channel plays the whole bass table**, including the notes above the chord's root octave
that `pcs30_arrange.py` moves to the guitar for a General MIDI synth: in Silent Night's C major the
bass channel goes C2, E3, E3, G2, E3, E3 while the chord part plays C4 on beats 2 and 3.
`pcs30_arrange.py --chip` writes the parts that way.

Oboe and trumpet share waveform and envelope and differ only in their output pin, which is the
plainest sign that much of what tells these voices apart is in the analogue filters.

**Bit 3 of `88H` is a vibrato.** It is blank on the YM2163 and set only for the vibraphone, the
flute and the violin, and the recordings settle what it does: flute, strings and violin notes
wobble at **about 6 Hz**, while clarinet, brass and oboe notes hold dead steady (0.0 to 0.1
cents). **It is delayed:** on the Santa Claus flute, pitch tracked every 3 ms, there is no wobble
for about the first 250 ms of every note - legato notes included - and then it grows to its full
swing of **about 12 cents peak to peak** within about 100 ms.

## The analogue filters: why the PCS-30 sounds muffled

The PCS-30 sounds muffled, not bright as a square-wave synthesizer should, and the recordings say
exactly why: each output pin has a **low-pass filter**, and they differ. Measured by comparing each
voice's harmonics with its datasheet waveform's:

| pin | measured on | low-pass | fit |
|---|---|---|---|
| **OR3** | flute (a clean solo obbligato), piano | steep: about 3-pole at 1.6 kHz, or 2-pole at 1.3-1.8 kHz | 2.2 dB |
| **OR1** | violin | 2-pole, about 2.3 kHz | 0.7 dB |
| **OR2 + OR3** | guitar | 2-pole, about 2.1 kHz | 1.1 dB |
| **OR4** | harpsichord | 2-pole, about 3-4.9 kHz | 0.9-2.2 dB |
| **OR1 + OR2** | clarinet | 2-pole, about 4.3 kHz | 0.1 dB |
| **OR2** | brass | 2-pole, about 5.2 kHz | 0.6 dB |

**OR3 is by far the darkest**, and it carries the organ, piano, piccolo, flute and vibraphone. The
clarinet, sent to OR1 and OR2, lands between those two pins' corners, as a mix of them should. The
oboe and trumpet measurements disagree with the rest and are not used; the oboe had too few clean
notes, and the trumpet disagrees with the brass, which is the same entry.

These are simple fits to what came out of the keyboard's audio output, recording chain included.
Real filters will have their own shapes; these say where the corners are.

## Tuning

Equal temperament, the whole instrument **about 3.7 cents sharp** - close to A = 441 Hz - with
every pitch class within ±3 cents of that, the scatter a whole-number note table would give.
Measured on 464 notes.

## The drums

Five drums, struck through `90H`. The two tonal ones come out on the rhythm output RH1, the three
noisy ones on RH2. The PCS-30 writes no drum levels (`94H`-`97H`), so each decays on the chip's own
envelope.

| bit | drum | sound | falls 20 dB in |
|---:|---|---|---|
| 0 | **kick** (BD) | a **square wave at 112 Hz**, odd harmonics only | about 40 ms |
| 1 | **latin** (HC, "high conga") | a **square wave at 252 Hz**, filtered harder than the kick; it plays the son clave in rhumba and bossa-nova | about 50 ms |
| 2 | **snare** (SDN, "snare drum noise") | **noise**, mostly 500 Hz to 3 kHz, with no fundamental - confirmed by ear | |
| 3 | **long cymbal** (HHO, "hi-hat open") | metallic: fixed partials at 673, 2016, 2519, 3359 and 5373 Hz | about 100 ms |
| 4 | **short cymbal** (HHD, "hi-hat closed") | the same partials as the long one | about 42 ms |

**None of them fades smoothly.** Measured every 4 ms on clean hits (Feel Like Makin' Love's
opening), each falls to about half in the first 10 ms, runs down in a straight line and then
stops dead: the kick and latin drum are gone by about 60 ms, the short cymbal by about 70 ms, and
the long cymbal holds a shelf at about a quarter of its peak until it stops at about 130 ms. The
kick's pitch holds steady at 110-113 Hz throughout - no drop.

**A snare struck with a cymbal silences the cymbal.** The waltz pattern in the ROM strikes snare
and short cymbal together on beats 2 and 3, yet the waltz in Silent Night has only a snare there:
measured against a known cymbal hit, whose metallic partials stand about 14 dB above the noise,
and a known snare, 7 to 10 dB below, those beats read 2 to 7 dB below - snare. The three share
the RH2 output, which would account for it.

The kick and latin drum repeat almost sample for sample from hit to hit (correlation 0.98 or
better), so they are fixed waveforms, not noise. The two cymbals are **one sound with two decay
lengths**, and every one of their partials is a whole multiple of **168 Hz** (4, 12, 15, 20 and 32
times) - the kind of spectrum mixed square waves from one divided clock give, and the same 168 Hz
the tempo runs on (below). The cymbals are about 20 dB quieter than the kick; the snare is quieter
still. Measured on Mickey Mouse March's and Feel Like Makin' Love's openings (drums alone), Bette
Davis Eyes (short cymbals in a gap), and a fill in Silent Night (the snare, over the music).

## Tempo

The header's tempo field indexes a 32-byte table at ROM **`0x1B83`**, and the entry goes to
`0x803A`. The entries fall from 214 to 49: they are periods, not tempos. Across thirty measured
tempos,

> **played bpm = 10070 ÷ (entry + 1)**

to within 0.11%: a beat lasts entry + 1 ticks of a **167.8 Hz** clock - the same 168 Hz as the
cymbals, so tempo and drums are almost certainly counted from one divided-down clock. The PCS-30's
tempo slider does not change this: it only affects card playback if it is moved while a card
plays.

So the PCS-30 plays every card a little fast - most by 1.5 to 4% - and two much faster, because
their table entries are out of line with the rest:

| card | PCS-30 | card | PCS-30 | card | PCS-30 | card | PCS-30 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 40 | **46.8** | 69 | 70.4 | 96 | 98.7 | 126 | 130.7 |
| 48 | 50.8 | 72 | 74.6 | 100 | 101.7 | 132 | 136.0 |
| 52 | 54.7 | 76 | 78.0 | 104 | 106.0 | 138 | 141.8 |
| 56 | 58.5 | 80 | 83.2 | 108 | 109.4 | 144 | 148.0 |
| 60 | 61.8 | 84 | 86.8 | 112 | 113.1 | 152 | 157.3 |
| 63 | 64.9 | 88 | 89.9 | 116 | 118.4 | 160 | 165.0 |
| 66 | 67.6 | 92 | 95.0 | **120** | **127.4** | 168 | 170.6 |
| | | | | | | 176 | 183.0 |
| | | | | | | 184 | 189.9 |
| | | | | | | 192 | 193.6 |
| | | | | | | 200 | 201.3 |

A **120 bpm card plays at 127.4**, 6% fast - Lady Madonna, Swan Lake and Leaving on a Jet Plane
among them - and a 40 bpm card would play at 46.8. The PCS-30 does not use the chip's timer for
this: registers `98H`-`9FH` are never written.

## The obbligato duck

A card's duck opcode (`0x14`, "the melody is entering") sets bit 0 of `0x80D7` at `0x2ACA`, and
the restore (`0x13`) clears it at `0x2ABD`; `0x1E48` copies the flag into `0x80D1`. At every
obbligato note `0x0F77` adds `0x10` to the level byte it writes to `8CH` - one volume step, **6
dB**, whatever the voice. The clarinet and oboe start at −6 dB and so duck to −12, and the flute
(entry 7, which `0x0F86` singles out) always plays a step down, duck or not.

This is the PCS-30's biggest difference from the UPA-01 cartridge, whose duck is a per-note
velocity worth 0 to 1.5 dB depending on the voice - nothing at all for the harpsichord.
`csrc/playcard` ducks the PCS-30's way by default; see "How deep the duck is depends on the
machine" in `playcard-format.md` and "The obbligato duck" in `csrc/README.md`.

## How the recordings were measured

Every measurement above comes from about sixty recordings of a real PCS-30 playing original cards,
against the arrangement `pcs30_arrange.py` makes of the same card, which says what should be
sounding at every instant. The scripts that did it were scratch work and were not kept, so here is
the method and, more usefully, the four ways it goes wrong.

**Lining a recording up with its card.** Take an onset curve of each - rising energy per 10 ms
frame for the recording, note starts for the arrangement - and search offset and *speed ratio*
together for the best correlation. The ratio matters: the keyboard plays the card 1.5 to 6% fast
(above), and the recordings were made on real hardware, so a search that assumes the card's own
tempo finds nothing. Search roughly 0.9 to 1.15, coarse first and then fine around the winner.
Where the card behind a recording is not certain, score every candidate and take the best.

**Then find each note again locally.** The global fit drifts by up to a whole note over a few
minutes, which is far too much to measure a harmonic in. So for each note, search ±0.35 s around
where the fit predicts it and keep the window in which that note's own fundamental band holds the
largest share of the energy - its *pitch purity*. Below about 20% the note has not been found;
throw it away rather than measure the wrong thing.

**Measure only notes that are alone.** Longer than 0.3 s, no other part sounding a harmonic within
4% of the fundamental, no drum within 0.1 s of the attack, and the measurement window taken from
30 ms after the attack to no more than 80% of the note. That leaves few notes - a handful per card -
which is why some findings rest on three notes and say so.

**The four traps, each of which cost an evening:**

* **A scoring bias picks the wrong alignment.** The first version scored notes the arrangement puts
  out of the instrument's range as if they sounded, and happily aligned a recording a bar off.
* **A coarse grid straddles the peak.** One pass at a tolerance loose enough to find the region is
  not accurate enough to measure in, and one tight enough to measure in never finds it. Two passes.
* **A cached render is worse than no measurement.** Deleting the renders from the shell did not
  reach the path Python's `tempfile` had chosen, so a whole round of comparisons was made against
  the previous synth. Re-render every time.
* **Melody against obbligato cannot be measured this way at all.** An obbligato note that is clean
  by the rules above, under a melody, is too rare - a few per corpus. This was tried twice and both
  times produced numbers with a spread wider than the thing being measured. The balance between the
  parts, and so `PIN_DB`, has to be set by ear. Do not try it a third time.

## What is still unknown

* **The analogue filters' real shapes and the rhythm outputs' filtering.** A schematic would give
  them; failing that, the fits above.
* **The chip's master clock**, and so the envelope times in seconds. The 168 Hz tick is the best
  handle on it.
* **How the four output pins are mixed.** The synth's balance is set by ear.
* **What `0x0F2D`'s bass step down on slow-rock depends on.**
* **The oboe's filter** (too few clean notes), and why the trumpet measures unlike the brass.
* **The snare's exact band**, measured only under the music.
* **How the cymbal's partials are made** from the 168 Hz clock.

## A synthesizer (work in progress)

`pcs30_synth.py` plays a card the PCS-30's way, from `pcs30_arrange.py --chip`, and **it is not
finished**: after five rounds of listening against recordings of a real PCS-30 it is closer, but
still has balance issues. It builds on everything above - the waveforms, envelopes and voice
table, the keying model, the delayed vibrato, a filter per output pin, the measured drums, the
snare-over-cymbal rule and the tempo table.

What the listening settled, and is in it:

* **the bass channel plays the whole bass table** (the missing E3s in Silent Night);
* **the organ plays where the card says** - `pcs30_arrange.py` raises it an octave for General
  MIDI synths, and the synth takes that back out (the piccolo's octave, which the real keyboards
  play, stays);
* **no swell on held notes**, from the keying model;
* **the vibrato's delay and depth**, as measured;
* **the drums' envelopes**, as measured, and the snare-over-cymbal rule;
* **no extra roll-off after the mix**: the pin filters were measured from recordings and already
  include everything after the chip. Adding one darkened the violin.

What is set by ear and still under test - each value is marked where it is set:

* **how loud each output pin is in the mix** (`PIN_DB`: OR3 +4 dB, OR2 −4 dB). Nothing says;
  the recordings could not settle it, because an obbligato under the melody is rarely clean
  enough to measure. The two observations behind it: the flute under Silent Night's violin and
  the piano under Röslein's clarinet were both too quiet, and both are on OR3; and brass
  measured about 5 dB loud.
* **a voice on two pins is at full level on both.** Splitting it instead left the guitar chord
  part far under the bass.
* **each drum's level** (`DRUM_GAIN`). Matched first to the ratio of drum peak to music level in
  the recordings, which overshot, then brought down 6 dB by ear, with the snare raised again.

Open when this was written:

* whether the **violin** is now as bright as the real one;
* whether the **bass** still stands out on cards with a guitar chord part (Silent Night, Lady
  Madonna, Here Comes Santa Claus) - Röslein and Mickey Mouse March, with a piano chord part,
  sounded right;
* whether **Mickey Mouse March's guitar melody**, now louder, is too prominent;
* the **snare's** level and colour, measured only under the music;
* the **envelope times**, still the datasheet's.

**Set aside on 2026-09-22**, at that point. Everything the five rounds settled is in the code and
above; what is left is all balance and all by ear, so picking it up again means listening to a
render beside a recording of the same card and moving `PIN_DB`, `DRUM_GAIN` and the envelope times.
The recordings are the card owner's and are not in this repository; renders went to
`tmp/pcs30-synth/`. Two things would change the game rather than the balance: a PCS-30 schematic,
which would give the output filters and the mix outright, and the chip's master clock, which would
turn the datasheet's envelope times into seconds.

## Sources

* The YM2163 datasheet (Yamaha, No. LS1130), register map on page 5, formulas on page 6, waveforms
  and envelopes on page 7. Two scans are in denjhang's MIT-licensed `RE2-YM2163` repository on
  GitHub, which also holds the MARS 21 material; the cleaner one is `YM2163资料/YM2163.pdf`.
* "Undocumented Sound Chips" (sites.google.com/site/undocumentedsoundchips), on the YM2142 and
  YM2163.
* weltenschule.de's page on the VTech Rhythmic 8, a YM2163 keyboard, for the chip's character.
* The PCS-30 owner's manual, for its panel voices.
