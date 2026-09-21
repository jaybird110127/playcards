# A Playcard to a WAV file, without an emulator

The Playcard format itself was decoded from the ROM and the cards rather than from Yamaha's
patents — see "The patents" in `../playcard-format.md`. These two programs do not decode it at
all: the firmware does that.

Two small programs. Together they take a card image and give back audio, with
nothing installed but a C compiler.

```bash
make
./playcard card.bin -o card.fmlog
./fmlog2wav card.fmlog card.wav --normalize
```

Neither needs to be told how long the card is or how loud it should be. A real
90-second card goes from image to `.wav` in under two seconds.

`playcard` runs the card on an emulated Yamaha CX5M — the real BIOS, the real
Play Card cartridge, the real SFG-01 FM module — and records every write the
firmware makes to the YM2151. `fmlog2wav` plays that recording back through an
emulated YM2151 and writes a `.wav`.

### Reading the cartridge's panel

`--screen FILE` writes the cartridge's own settings display as text, and `--screen-at S` takes it
S seconds after playback starts rather than when the card ends:

```bash
./playcard card.bin -o card.fmlog --screen panel.txt --screen-at 5
```

```
 0|     YAMAHA PLAY-CARD SYSTEM
 1|    Voice
 2|     melody    06:EPIANO1
 3|     obbligato 01:BRASS 1
 6|    Rhythm     03:swing
 7|    Sustain:off  ABC:off
```

That is the firmware's own account of what it thinks the card asked for, which makes it an
independent check on a header field. It works because the emulator keeps the VDP's 16 KB of video
memory; nothing is rendered, and the screen is read back out of the name table. Cells that are not
printable ASCII — the tempo and transpose sliders are drawn with graphics characters — come back
as blanks, with the raw codes appended after the text so nothing is lost.

Take the dump **after playback has started**. The panel is not refreshed until then, so a dump taken
earlier shows the cartridge's defaults rather than the card.

### What a capture from this is evidence of

What comes out is **the UPA-01 cartridge's** rendering of the card, on an SFG-01's YM2151 — not
"how a Playcard sounds". The PC-100 the cards were written for is a different instrument with
different accompaniment patterns, and this cartridge is a 1985 port with known bugs: fills come out
with a fixed feel rather than the rhythm's, chord notes drop, and a same-root chart entry silences
the accompaniment. For what the card asks for, as against what this machine does with it, read
`../playcard-format.md`.

Neither program understands the Playcard format. That is the point: the card is
decoded by Yamaha's own firmware, exactly as a keyboard would decode it, so the
result is what the machine does rather than what we think it does.

## Setting the cartridge's panel: volume, tempo, transpose

The cartridge has its own front panel, driven from the MSX keyboard while a card
plays. Nothing on it is on the card; it is the player's mixing desk. Set it from
the command line and the firmware applies it exactly as if you had typed:

```bash
./playcard card.bin -o card.fmlog --mix karaoke
./playcard card.bin -o card.fmlog --volume melody=40,rhythm=24
./playcard card.bin -o card.fmlog --tempo 132            # absolute, in bpm
./playcard card.bin -o card.fmlog --tempo -8             # the card's own, 8 slower
./playcard card.bin -o card.fmlog --transpose +2
```

| option | what it sets | range | the cartridge starts at |
|---|---|---|---|
| `--mix NAME` | all five at once: `lead`, `karaoke` or `cartridge` (below) | | this program's default is `lead` |
| `--volume P=N` | one part's level: `melody`, `obbligato`, `chord`, `bass`, `rhythm`, or `all` | 0 to 40 | 30 |
| `--tempo BPM` | the tempo, on the cartridge's grid of 4; a leading `+` or `-` moves the card's own instead | 40 to 200 | the card's |
| `--transpose S` | the whole arrangement, melody to bass; the drums are untouched | −5 to +6 | 0 |

The three mixes:

* **`lead`**, the default: 40, 34, 28, 26, 26 - the melody on top and the
  accompaniment balanced beneath it. Why, below.
* **`karaoke`**: `lead` with the melody gone, to sing or play along with.
  Volume 0 is not silence on this cartridge - the melody's carrier only drops
  to about 45 dB down, faint but there in a quiet passage - so the melody's
  notes are cut as well. The cartridge always plays the melody on FM channels
  0 and 1, doubled, and nothing else there (checked on 23 cards across every
  series); a key-on on those two becomes a key-off, so the capture has the same
  writes and fewer key-ons. The obbligato stays, as a second line.
* **`cartridge`**: the UPA-01's own 30 across the board, by touching nothing -
  the panel is left exactly as the firmware sets it. Use it whenever the
  question is what the machine does; every research script in this repository
  passes it.

`--volume` after `--mix` adjusts one part of it. The line the program prints
says what it imposed:

```
  panel: melody 40 obbligato 34 chord 28 bass 26 rhythm 26
```

### What the keys on the real panel do

For anyone at a real CX5M, which cannot say any of this aloud:

* **V** steps through the five volumes: melody, obbligato, chord, bass, rhythm,
  and round again. The arrows move the selected one. It wraps at both ends: one
  step up from 40 is 0.
* **T** selects the tempo, and the arrows move it 4 bpm at a time, wrapping
  from 200 to 40.
* **K** selects the transpose, one semitone a press, from −5 to +6, wrapping.
* **A** cycles the ABC setting, *off*, *on* and *variation*, and it is the one
  setting the panel shows as words. It changes **nothing** in the cartridge's
  own sound: forty seconds of a card captured in each of the three states are
  identical write for write. The value is read by the routine that sends the
  cartridge's settings out to the music keyboard, so what it controls is the
  keyboard's Auto Bass Chord - the left hand choosing the chords - which is not
  emulated here.

The levels, the tempo and the transpose are drawn as **sprites** sliding along
bars, which is why a text dump of the screen (`--screen`) shows the bars but
never the knobs.

### Why the lead mix exists

Measured each part alone, level while it sounds, at the cartridge's own 30
across the board: **the melody and obbligato sit about 9 dB under the bass and
drums, and 6 dB under the chords.** On Lady Madonna the melody is 9.3 dB under
the loudest accompaniment part; on 9 to 5, 11.8. Each volume step is 1.1 dB.

`lead` brings the melody to the front and the rhythm section back:

| card | melody | obbligato | chord | bass | rhythm |
|---|---:|---:|---:|---:|---:|
| Lady Madonna | **+6.6** | −0.3 | −0.7 | −0.2 | 0.0 |
| Edelweiss | **+9.2** | +4.2 | 0.0 | −4.7 | −5.1 |
| 9 to 5 | **+1.8** | +2.1 | 0.0 | −5.1 | −4.0 |

dB against the loudest accompaniment part. **No fixed mix suits every card**,
because each card picks its own voices and some pairings are lopsided - 9 to 5
sets a piano melody against a brass obbligato, and the piano only just gets
ahead. That is what `--volume` after `--mix` is for.

So `lead` is the default, for listening. A capture meant as evidence of what
the machine does should ask for `--mix cartridge`.

### How it works

The keys write the wanted value into a block at `0xCC26`: five volumes, then
tempo, then transpose. A routine that runs a few hundred times a second compares
each with the live copy at `0xCC09` and, where they differ, applies it through
the firmware's own path - the chip's levels, the tempo timer, the sprite on the
panel. Writing the wanted block is therefore as good as typing, and instant, and
it happens before the first note.

Two things needed care. **Starting a card overwrites the tempo** with the card's
own, at `0x4313`, so a tempo is imposed just after that store. And **the sync
applies a value only when wanted and live differ**, so asking for what the live
copy already holds - 120 bpm is the boot default - would change nothing and let
the card's tempo stand; each imposed setting is marked stale so the firmware
re-applies it.

### Typing at it directly

For anything else on the panel there is a key script, typed before playback
(`--keys`) or just after the start key (`--play-keys`):

```bash
./playcard card.bin -o card.fmlog --play-keys "wait:1,a,wait:0.3,screen:panel.txt"
```

Tokens are separated by commas: a key name taps it once (`v`, `right`, `f3`),
`right*5` taps it five times, `wait:0.5` lets the machine run, `screen:F` writes
the panel as text, and `ram:F` and `vram:F` write 16 KB snapshots for diffing.
Give it a second after the start key before typing; presses in the first moments
are lost.

## Speed

About **150× real time**: 24 emulated seconds of machine in 0.16 s of wall
clock. The Python twin, `../msx_player.py`, runs the same machine at 79% of real
time. Both are kept, and they are for different jobs — the Python one can stop
the machine and read a byte, and that is what actually finds bugs. This one is
for volume.

## The tempo is right here, and is not under an emulator

A card declaring 120 bpm renders at **119.7 bpm** from this program, and at half
that under openMSX. The difference is the YM2151's **timer A**, which clocks
the music: the cartridge programs it from the tempo, and the sequencer advances a
card tick every one, two or four overflows, whichever keeps the timer in range.
Deliver that interrupt and the firmware plays
at the speed it says; leave it out and only the VDP's 50 Hz drives the
sequencer, at half speed and unevenly. See "playback ticks" in
`../playcard-format.md`.

The 0.3% that remains is the chip's, not this program's: timer A counts in whole
steps of 64 clocks, so for 120 bpm the nearest the cartridge can ask for is
95.771 Hz, which is 119.7 bpm. Every tempo lands within that resolution of what
it asks for, from 39.9 at the bottom to 199.8 at the top.

**Until 2026-09-21 every capture here ran about four percent slow**, and the
spec used to quote 120.4 bpm on a figure taken before the fault crept in. The
playback loop runs the machine a quarter of a second at a time, and each call
restarted timer A's count from nothing, throwing away whatever part of a period
had already gone by: four overflows lost a second, which a trace of the SFG's
interrupt handler showed as a missed tick exactly every 250 ms. The next
overflow is now kept with the machine, the handler services 95.772 interrupts a
second against the 95.771 programmed, and every gap between them is exactly one
period. Anything measured from a capture's absolute timing before that date - a
bar length, a tempo, a bar grid - is 4% out.

**Five of the format's 32 tempos are not playable on this cartridge.** A card's
metronome mark reaches the panel as `floor(bpm / 4) - 10`, an index into 41
settings from 40 to 200 bpm in steps of 4 (ROM `0x4305` and the tables at
`0x4363` and `0x433A`), so a mark that is not a multiple of 4 is rounded down:

| the card says | this cartridge plays |
|---:|---:|
| 63 | 60 |
| 66 | 64 |
| 69 | 68 |
| 126 | 124 |
| 138 | 136 |

Measured, not inferred: Lesson 1a, Somewhere My Love, Ebb Tide and Night and Day
play at 59.9, 67.8, 124.0 and 135.5. This is the UPA-01's own behaviour, not the
format's.

## What is emulated, and what is not

Only what the cartridge touches: the Z80, the primary slot register and four 16K
pages, the keyboard matrix, the VDP's two ports as a sink with a working vblank
flag, the PSG discarded, and the YM2151 recorded. There is no video and no
sound hardware, because nothing reads either back.

The CR-01 card reader is not emulated at all. It is memory-mapped at `0x7FFF`,
and the two ROM routines that take a bit from it are answered straight from the
card image.

**Three things have to be right or a card reads perfectly and plays nothing:**

1. The SFG answers across its **whole slot**, the same 16K four times over, so
   the signature `"MCHFM0"` is readable at `0x0080` while its ROM is read at
   `0x4000` and its chip sits at `0x3FF0`.
2. The YM2151's status is read back from the **data** port `0x3FF1`, not the
   address port. Put it in the wrong place and the FM module's self-check never
   sees its timer flag, decides the chip is dead, and the cartridge comes up
   paused — silently, with everything else working.
3. `LD A,I` must set P/V from IFF2. The ROM uses the standard
   `LD A,I / PUSH AF / DI … POP AF / RET PO` idiom, so a CPU that treats it as a
   no-op restores interrupts to *off* for ever and the music stops after one
   note. This is why the Z80 core here is a borrowed one that passes ZEXALL
   rather than something hand-written.

## It stops when the card does

`playcard` plays until the card runs out, so there is no duration to guess.
`--seconds` is a **ceiling** (400 by default), not a length.

The end of a card is not the end of the FM traffic. Once the music stops the
firmware keeps writing about **285 registers a second, for ever**, housekeeping
an idle chip — so "the writes stopped" would never fire. What does stop, cleanly,
is the **key-ons**: on a card of known length the last one lands exactly where
the music ends. So the test is *no note struck for a while*, four seconds by
default, and `--quiet-for N` changes it.

```
F2: 43588 FM register writes, 3278 key-ons
    the card ended after 90.8 s (no note struck for 4.0 s)
```

That is a real card, and it is why the old fixed default was no good: 90 seconds
of music against a 20-second capture.

## Trimming and level

A capture starts with the machine booting and the card being read, and neither
makes a sound, so a card's audio typically begins about sixteen seconds in.
`fmlog2wav` **trims silence from both ends by default**, keeping 50 ms either
side, and says what it kept:

```
trimmed to 16.75 s .. 25.50 s of the capture
```

`--no-trim` keeps the lot. `--skip SECONDS` drops a fixed amount from the front
first, for when you want the second chorus rather than the first.

The chip's own output is quiet — a card's melody peaks around 9% of full scale,
because these voices were mixed to sit under a player's own hands. `--normalize`
brings the loudest peak to -0.5 dBFS and reports what it did:

```
normalised: peak was 0.093 of full scale, gain x10.20
```

`--gain G` applies a fixed multiplier instead, for when several cards need to
stay at the same relative level.

## Static by default

Both binaries link statically, so neither carries a compiler runtime around
with it. Left to itself the C++ one wants `libstdc++-6.dll` and
`libgcc_s_seh-1.dll` out of the toolchain — exactly the sort of thing that is
missing on the machine you copy it to. After `-static` the only dependencies
left are the operating system's own: `KERNEL32` and the Universal CRT stubs on
Windows.

```
playcard.exe    no non-system DLLs    188 KB
fmlog2wav.exe   no non-system DLLs    950 KB
```

`make STATIC=` links the ordinary way if you would rather.

## Playing a card with no FM hardware

The UPA-01 was sold for MSX machines with no FM module, and falls back to the
machine's own PSG. `--no-fm` leaves the FM slot empty so the cartridge takes
that path, and `--psg-log FILE` records what it plays there:

```bash
./playcard card.bin --no-fm --psg-log card.psg --seconds 130
```

Out come three voices instead of the FM arrangement: melody on channel A,
obbligato on B, and a bass on C. It is a different rendering of the same card,
and the only way to see that half of the cartridge.

Note that the end-of-card detection watches FM key-ons, so give `--seconds` a
real value in this mode.

## Free tempo

`--f5` starts the card with **F5** instead of F2, which is free tempo: the card
plays its introduction and then holds at the first melody note, waiting for the
player. Nothing here can play that note, so it holds for ever, and the program
says so rather than calling it the end of the card.

```
F5: 7380 FM register writes, 119 key-ons
    stopped after 14.2 s. In free tempo that is not the end of the card:
    it is holding for the player's first melody note, and nothing here can play it
```

## Two-sided cards

Give it both files, side A first. One F1 press pulls one card past the head, so
the two go in as two swipes against one strip:

```bash
./playcard side-a.bin side-b.bin -o card.fmlog
```

```
F1: card 1 read, 5520 of 5520 bits
F1: card 2 read, 6880 of 6880 bits
F2: 78550 FM register writes, 3284 key-ons
```

Neither half plays alone — a side A carries no section table and waits, a
side B has no header of its own — and the reader has to see the strip run
out between them or it reads straight on into the next card.

## Watching a byte of RAM

`--watch ADDR` reports every read and every write of an address, with the time,
the value and the CPU's PC; `--watch-out FILE` says where the report goes, and
up to eight addresses can be watched at once. It is the difference between
knowing what the firmware *stores* and knowing what it ever *looks at*.

```bash
./playcard card.bin --watch 0xD324 --watch 0xD349 --watch-out card.watch
```

```
40.281530 D349 W 60 pc=5FBF
40.281535 D324 R 60 pc=5E2F
```

The PC is where the Z80 sits while the operand is being fetched, which is the
address *after* the instruction that did it: `pc=5E2F` above is `LD B,(HL)` at
`0x5E2E`. Reads at `0369`, `036C`, `7D61`, `7D64` are the BIOS sizing RAM at
boot and reads at `5C88` are the cartridge's zero-fill, an `LDIR` that reads
back the byte it just wrote — none of those is anybody consuming a value.

This is what showed that the third part's level at `0xD349` is written and
never read; see "the third ducked part" in `../playcard-format.md`.

## Finding things: where the CPU is, and what is in RAM

`--pc-from S` counts where the CPU sits from second S onwards and prints the
twenty busiest addresses at the end. A wait loop shows as a few addresses
holding most of the samples; anything flatter is the machine going about its
business. Careful what you conclude from it: the busiest addresses on this
machine are `0x1478`-`0x147D`, and that is the SFG-01 scanning its music
keyboard, which it does whatever else is happening.

`--ram-out FILE` dumps `0xC000`-`0xFFFF` a moment after the start key, and
`--ram-at S` says how long a moment. Two runs that differ in one thing give two
dumps that differ in a handful of bytes, which is the quickest way to find the
byte that records a mode: F2 against F5 differs in **17 bytes**, and one of them
is `0xD222`.

## The ROMs

Not here, and not ours: they are Yamaha's. Put them in `../Roms/`, or pass
`--roms DIR`, or set `PLAYCARD_ROMS`.

| file | bytes | what it is |
|---|---|---|
| `cx5m_basic-bios1.rom` | 32768 | the CX5M's BIOS and BASIC |
| `SFG01.ROM` | 65536 | the SFG-01 FM module |
| `Play Card System (UPA-01) (1985) (Yamaha) (J).rom` | 16384 | the cartridge |

`playcard` names whichever is missing and stops, rather than crashing.

## Borrowed code, and its licences

Both permissive, both kept with their licence text:

* **`z80.c` / `z80.h`** — a Z80 core by Nicolas Allemand, MIT. `Z80_LICENSE`.
* **`ymfm/`** — the YM2151 core from Aaron Giles' ymfm, BSD 3-clause.
  `ymfm/YMFM_LICENSE`. Only the five files the OPM needs are here.

Everything else in this directory is part of this project.
