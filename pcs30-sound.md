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
  says what should be sounding at every moment, and measured where a part sounds on its own.

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
vibraphone. Trumpet, oboe, piccolo and harpsichord exist for cards. The accompaniment's chord and
bass voices are chosen per rhythm from other tables (`0x2D12`, `0x2D1C`) and are not decoded yet.

Oboe and trumpet share waveform and envelope and differ only in their output pin, which is the
plainest sign that much of what tells these voices apart is in the analogue filters.

**Bit 3 of `88H` is a vibrato.** It is blank on the YM2163 and set only for the vibraphone, the
flute and the violin, and the recordings settle what it does: flute, strings and violin notes
wobble by 3 to 12 cents at **about 6 Hz**, while clarinet, brass and oboe notes hold dead steady
(0.0 to 0.1 cents).

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

## What is still unknown

* **The analogue filters' real shapes and the rhythm outputs' filtering.** A schematic would give
  them; failing that, the fits above.
* **The chip's master clock**, and so the envelope times in seconds. The 168 Hz tick is the best
  handle on it.
* **The accompaniment's chord and bass voices**, chosen per rhythm; the tables are found, not
  decoded.
* **The oboe's filter** (too few clean notes), and why the trumpet measures unlike the brass.
* **The snare's exact band**, measured only under the music.
* **How the cymbal's partials are made** from the 168 Hz clock.

## A synthesizer

Everything a first draft needs is above: four channels of stepped waveform times a straight-line
envelope, a two-bit volume, a 6 Hz vibrato on three voices, a low-pass filter per output pin, two
square-wave drums, a noise snare, a metallic cymbal with two decays, and the tempo table. Fed by
`pcs30_arrange.py`, it could play any card the PCS-30's way - and because the recordings exist, it
can be checked against the real keyboard card by card.

## Sources

* The YM2163 datasheet (Yamaha, No. LS1130), register map on page 5, formulas on page 6, waveforms
  and envelopes on page 7. Two scans are in denjhang's MIT-licensed `RE2-YM2163` repository on
  GitHub, which also holds the MARS 21 material; the cleaner one is `YM2163资料/YM2163.pdf`.
* "Undocumented Sound Chips" (sites.google.com/site/undocumentedsoundchips), on the YM2142 and
  YM2163.
* weltenschule.de's page on the VTech Rhythmic 8, a YM2163 keyboard, for the chip's character.
* The PCS-30 owner's manual, for its panel voices.
