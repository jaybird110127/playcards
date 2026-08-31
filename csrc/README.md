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

## Speed

About **150× real time**: 24 emulated seconds of machine in 0.16 s of wall
clock. The Python twin, `../msx_player.py`, runs the same machine at 79% of real
time. Both are kept, and they are for different jobs — the Python one can stop
the machine and read a byte, and that is what actually finds bugs. This one is
for volume.

## The tempo is right here, and is not under an emulator

A card declaring 120 bpm renders at **120.4 bpm** from this program, and at half
that under openMSX. The difference is the YM2151's **timer A**, which the SFG
programs at 109.24 Hz and which clocks the music. Deliver that interrupt and the
firmware plays at the speed it says; leave it out and only the VDP's 50 Hz drives
the sequencer, at half speed and unevenly. See "playback ticks" in
`../playcard-format.md`.

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
