# ROM images

The format was decoded from these ROMs and from the cards, not from Yamaha's patents; the patent
family was read at the end only to check the result. See "The patents" in
`../playcard-format.md`.

**This folder is empty in the repository, and it is meant to be.** The ROMs are
Yamaha's copyright; nothing here ships them. Put your own dumps in this folder
and the tools will find them, or set `PLAYCARD_ROMS` to wherever you keep them.

Most of this repository needs **no ROM at all**. Decoding a card, compiling a
MIDI back into one, checking CRCs, reading dates, the compression, the round
trip — all of that is code, and the few small firmware tables it depends on
(tempo marks, the symbol alphabet, the opcode maps) are transcribed into
`playcard_decode.py` as the facts they are. What needs a ROM is anything that
*runs* the firmware or reads the instrument's own music out of it.

## The four that matter

| file | bytes | what it is |
|---|---:|---|
| `Play Card System (UPA-01) (1985) (Yamaha) (J).rom` | 16,384 | The Play Card cartridge. The firmware that reads and plays a card |
| `cx5m_basic-bios1.rom` | 32,768 | The Yamaha CX5M's BIOS and BASIC, to boot the machine the cartridge runs on |
| `SFG01.ROM` | 65,536 | The SFG-01 FM module: its own ROM, and the YM2151 the music comes out of |
| `PCS-30.rom` | 32,768 | The PCS-30 keyboard. A different machine, and the source of the accompaniment and drum patterns |

The names are matched exactly, so keep them as they are or pass the right name
on the command line.

Any other dumps in this folder are ignored. A CX5M II or a CX5M/U will not do
for the emulator: the slot layout it sets up is that of the original CX5M, and a
differently sized BIOS is a different machine.

### What the dumps look like

Worth knowing, because a good dump can look wrong:

* **`SFG01.ROM` is 64K for a 16K ROM.** The module answers across its whole
  slot, the same 16K four times over — which is not incidental, it is why the
  signature `MCHFM0` is readable at `0x0080` while the ROM itself is read at
  `0x4000`. In this dump the four copies differ at exactly two bytes, `0x3FF3`
  and `0x3FF4`, which are inside the YM2151's own window at `0x3FF0`-`0x3FF7`:
  the dumper caught live chip values rather than ROM. It makes no difference,
  because both emulators intercept that window anyway. Expect your dump to
  differ there too, and possibly by different values.

* **`PCS-30.rom` is 32K with a blank second half.** Everything used lives in the
  first 16K, well before the tables at `0x2BBC` and `0x2D26`.

* **The cartridge is a plain 16K** starting `AB` with its init vector at
  `0x404B`, as an MSX cartridge should.

If you want to check a dump against the ones this work was done with:

```
Play Card System (UPA-01) (1985) (Yamaha) (J).rom   sha256 1f9ef29d7ffd8a84...
cx5m_basic-bios1.rom                                sha256 efb1547eb341b365...
SFG01.ROM                                           sha256 c14dcfd8541daa81...
PCS-30.rom                                          sha256 f6f349900ee19f01...
```

These are a record of what was used, not a requirement. A different dump of the
same ROM should work; a *different* ROM will not, and the tools that care say so
rather than misbehaving quietly.

## Which tool needs which

### Nothing at all

`playcard_decode.py`, `playcard_encode.py`, `playcard_resolve.py`,
`playcard_compress.py`, `playcard_expand.py`, `playcard_midi.py`,
`card_decompile.py`, `midi_compile.py`, `midi_export.py`, `card_dates.py`,
`card_to_swipe.py`, `swipe_to_card.py`, `forge_crc.py`, `header_edit.py`,
`make_random_card.py`, `make_test_midi.py`, `z80run.py`, `z80run_test.py`,
and everything in `new-cards/` that writes a card.

### The cartridge, on its own

| tool | why |
|---|---|
| `card_limits.py` | Runs the cartridge's own parser over a card to see whether the firmware would take it. There is no doing that without the firmware |
| `z80dis.py` | Disassembles it. `--rom` picks a different image |

### The cartridge, the BIOS and the SFG-01 — a whole machine

| tool | why |
|---|---|
| `csrc/playcard` | Boots an emulated CX5M, reads the card through the cartridge's own UI and captures every YM2151 write. `--roms DIR` says where they are |
| `msx_player.py` | The same machine in Python. `--roms` reports which it can find before it starts |
| `new-cards/diff_fill_feel.py` | Drives `csrc/playcard`, so it needs the same three |

`csrc/fmlog2wav` needs none of them: it renders a capture through its own
YM2151 model.

### The PCS-30

| tool | why |
|---|---|
| `pcs30_extract.py` | Lifts the accompaniment and drum tables out of the ROM into `pcs30-tables.json`. **Run this once** and the three tools below never touch a ROM again |
| `pcs30_demo.py` | Decodes the three demo tunes stored in the ROM |
| `pcs30_drums.py --card` | *Executes* the firmware's bar-mark handler rather than reading a table, so this one mode needs the ROM even though the rest of the script does not |

`pcs30_arrange.py`, `pcs30_rhythm.py` and `pcs30_drums.py` in its other modes
read `pcs30-tables.json` and nothing else:

```bash
python pcs30_extract.py          # once, against your own PCS-30 ROM
```

That file is generated and gitignored for the same reason this folder is: the
patterns are the instrument's musical content. `PCS30_TABLES` moves it.

### openMSX, which is a different thing again

`play_card.py`, `card_to_midi.py` and `new-cards/capture_fills.py` drive a real
openMSX. They pass this folder's cartridge image to it with `--cart`, but the
MSX system ROMs they run it on are **openMSX's own**, configured there rather
than here. Since `csrc/playcard` arrived these are mostly of historical
interest: it does the same job about 150 times faster, and with the right tempo.

## When one is missing

Every tool that needs a ROM says which one, where it looked, and what to do,
then exits 1. None of them shows a traceback:

```
no ROM at X:\playcards\Roms\PCS-30.rom
ROM images are Yamaha copyright and are not in this repository.
Put yours in X:\playcards\Roms, or set PLAYCARD_ROMS to the folder holding them.
```

`msx_player.py --roms` and `pcs30_extract.py --check` will tell you what you
have before you try to use it.
