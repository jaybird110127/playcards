# Rendering a Playcard through genny

`upa_genny.py` turns `upa_arrange.py`'s arrangement into a `.wav` by handing it to **genny**. This
document is the **method and the measurements** behind the numbers in that file: what was measured,
with what, what the traps were, and which figures are measured rather than chosen. The tool's own
docstring says what it does; this says why the numbers are what they are.

## genny, and getting it

genny is **not part of this project and not ours**. It is a CLI by **Oriol Gomez** that renders JSON
specs of layered notes, drums, sound effects and effect chains to a WAV - offline, deterministic, no
external audio dependencies - and it is written to be driven by an agent, which is exactly how it is
used here. Version 0.2.0 at the time of writing; Python 3.10 or newer.

> <https://github.com/ogomez92/genny>

```bash
git clone https://github.com/ogomez92/genny
cd genny
python install.py --tool        # installs the `genny` command with uv, editable from the clone
```

`python install.py` on its own installs only genny's Claude Code skill; `--link` symlinks it instead
of copying, `--uninstall` removes it, `--dest DIR` puts it somewhere else. From inside the clone
`uv run genny ...` works without installing anything. Once `genny` is on PATH, `upa_genny.py` finds
it with `shutil.which` and says so plainly if it cannot.

The repository carried **no licence file** when this was written, so nothing here assumes any right
to redistribute it: this project references genny and calls it, exactly as it calls `openmsx` or
`gcc`, and ships none of it. Its terms are its author's to state.

Its own `AGENTS.md` is the reference for the spec format and the catalog, and `genny list --json` is
the authority on what exists.

## Using it

```bash
python upa_genny.py card.bin -o card.wav
python upa_genny.py --all                      # a whole folder, into upa-genny/
python upa_genny.py --all --in-dir . --out-dir wav
python upa_genny.py card.bin --spec-only       # write the genny JSON and stop
```

A card with a side B is joined by the arranger, so give it the side A; under `--all` a side B is
skipped, because it is rendered with its side A. The folder is gitignored, as `upa-midi/` and
`pcs30-midi/` are.

Knobs, in the order they are likely to be wanted:

| option | what it does |
|---|---|
| `--gain NAME=VALUE` | move one part: `melody`, `obbligato`, `bass`, `chord`, `kick`, `snare`, `hihat`, `openhat`, `conga`. Repeatable |
| `--duck DB` | how far a ducked obbligato note drops (default -6; `0` for no duck) |
| `--voices fm` | every voice becomes genny's raw two-operator FM synth instead of its own instruments |
| `--drums upa` / `pcs30` | passed to `upa_arrange.py`: whose drum patterns. `upa` needs no PCS-30 ROM |
| `--as-is` | passed to `upa_arrange.py`: what the cartridge plays, corrections off |
| `--spec-only` | write the JSON and stop, for hand-editing or rendering elsewhere |

It also needs what the arranger needs: `upa-tables.json` from `upa_extract.py`, and
`pcs30-tables.json` from `pcs30_extract.py` unless `--drums upa`.

**None of it is the cartridge's sound.** The genuine article is `csrc/playcard` into `csrc/fmlog2wav`
- a real YM2151 playing the real card. genny's FM is two operators where the SFG-01's is four, so
this cannot imitate those voices and does not try. What it is for is the arrangement **as
`upa_arrange.py` corrects it**, which no cartridge will ever play, rendered without a General MIDI
synth anywhere.

## Why an arrangement fits genny at all

genny's model is a list of layers, each a sequence of steps. An arrangement fits it **exactly**, and
that was checked rather than assumed: across the corpus **no part ever overlaps itself**, and every
group of notes struck together shares one length. So each part converts to a sequential step list
with nothing approximated. The drums go in as one `pattern` layer a kit piece with explicit hit
positions. Seventy seconds of music renders in about five seconds.

## How things are measured

Everything below was measured one of three ways, and which one matters:

* **`genny info`, whole file.** Its `loudness` is K-weighted (the broadcast measure) and `ear` is an
  ear-weighted level of the loudest 0.2 s.
* **Each layer alone.** The spec is split into one spec a layer with `normalize: null`, rendered, and
  measured. This is how the parts are placed against each other.
* **Third-octave bands, in a window.** Rendered stems, a 16k FFT in half-overlapping frames, summed
  into third-octave bands, over a chosen four-second window. **This is the only measure that answers
  "is the obbligato buried", because burial is masking and masking is a band-by-band question.**

The scripts are in the scratch copy: `duck_analysis.py` (level per voice, ducked and open, and every
melody-against-obbligato pair), `masking2.py` (one card, one obbligato, every melody voice in turn),
`busy.py` (what buries the obbligato when the accompaniment is busy), `auditions.py` (candidate
voices, measured and cut to a short excerpt), and a stem renderer.

## The traps, in the order they cost time

1. **genny's `vel` is a BRIGHTNESS control, not a level control.** The card's duck is a velocity -
   `0x60` against `0x80` - and carrying that into genny moved the level by **0.4 to 1.4 dB** across
   the eight obbligato voices. The harpsichord was the 0.4, which is why Love Theme sounded as though
   it did not duck at all. The duck is now a real gain on its own layer.
2. **And a duck must not darken.** The first fix kept the card's lower velocity *as well as* the new
   gain, so a ducked note came out quieter **and** darker - and a dark quiet note disappears. The
   machine's duck is a volume step, not a filter; the ducked layer is now written at full velocity.
3. **Do not place a bass part by the ear-weighted number.** Ear weighting discounts 60-80 Hz by
   design, so the `upright_bass` reads **10 dB quieter than it sounds** (`ear` -23.5 against
   `loudness` -13.7). Chasing that number buries everything else.
4. **The melody is not what buries the obbligato.** Broadband, every melody voice is within a decibel
   of the others, which says nothing. In the bands a clarinet obbligato actually occupies it is
   **+18.3 dB above a trumpet melody** on Joy to the World and +11.5 above a vibraphone on Love Me
   Tender. The masker is the **accompaniment**, and on a busy card it is the accompaniment *summed*:
   no single part was above the clarinet on Joy to the World while the three together were, by
   6.8 dB.
5. **A pattern's business varies enormously and changes everything.** The standard rock chord part
   strikes **1.9** times a bar; disco **4.7**; slow-rock's ALTERNATE **8.1**; the march's alternate
   more still. A level that is right for rock is wrong for all of them.
6. **genny's `range` is advice, not a limit.** The `violin` is listed G3-C7 and 7 of 12 sampled
   strings-obbligato cards go below that, to MIDI 43. Measured on four notes below G3, the violin
   loses **0.4 dB** against its own mid register and sits level with what `strings` or `cello` would
   do there; only its colour changes (centroid 276 Hz against the ensemble's 326). The worry was
   unfounded.
7. **Compare like with like.** The first attempt at the masking question used two different cards and
   concluded the violin masks *more* than the trumpet - the opposite of what the owner heard. Swapping
   only the melody instrument on one card put them within half a decibel of each other.

## What is measured, and what is chosen by ear

**Measured.** The per-voice trims (`VOICE_TRIM`): each voice rendered alone at the gain and velocity
its part gets, compared with the mean of its role. The spread was 2.7 dB across the melody voices and
2.3 dB across the obbligato ones, with the **harpsichord and the guitar the quiet ones in both** -
half of why a harpsichord obbligato disappears. The masking lift (`MASK_LIFT`) likewise: how far the
obbligato must come up to stay audible under each melody voice, aiming for a 5 dB margin and only
ever lifting. The density rule (`DENSITY_REF`, `DENSITY_EXP`, `DENSITY_FLOOR`): the chord
part's gain comes down with how often it strikes, two strikes a bar being the reference because that
is the rock pattern whose balance was settled by ear. The exponent that would hold the part's energy
exactly constant is 0.5 - doubling the strike rate adds 3 dB - and that was **too much**: the
march's alternate pattern strikes 7.2 times a bar and lost 5.6 dB, which was heard as the
accompaniment being too soft. It is 0.35 with a floor of -4.4 dB, which is a compromise rather than
a measurement. The duck depth of 6 dB is this project's own figure for the PCS-30.

**Chosen by ear, by the owner, over six rounds.** Which voices: the nylon `guitar` for the chord
part and `upright_bass` for the bass, neither of which has a voice on the card at all; the acoustic
`piano` for the card's "piano", which is Yamaha's `EPIANO1` and so `epiano` is the faithful choice -
the acoustic one simply sounded better; `violin` for `strings`, as closer to a real keyboard; a
breathy `flute` for the piccolo, genny having none. And the part gains: the drums down twice, the
chord part up, the obbligato up.

The chord voice took an audition of all ten of genny's plucked voices over Love Me Tender's busy
second verse, each cut to the same sixteen seconds, and it settled on **`electric_guitar`** - the one
voice in that family described as sustaining while held, which suits a chord written to ring to the
bar line rather than decay away from it. The spread between best and worst was only 2.5 dB in the
bands the ducked clarinet occupies, and the two that measured best - `pizzicato` at -1.5 and
`muted_guitar` at -1.7, both dry and woody - were **not** the ones that sounded right; the chosen one
measures -3.9, no better than the `steel_guitar` and the nylon `guitar` it followed. A reminder that
the measurement ranks maskers, not music: on this question it was nearly useless and the ear did all
the work.

The kick likewise: `punch` is its "click and pitch-drop amount" and starts at **1.0**, which on a
disco card kicking four to the bar is a pitch sweep on every beat and was heard as the kick sounding
"a bit weird". `decay 0.5, punch 0.4, tune 45` by ear, against five alternatives including `kick808`
and `taiko`. The lesson is the one in trap 6: a drum that sounds wrong may be a parameter rather
than the wrong drum.

## Still open

* **Why a trumpet melody buries a clarinet obbligato where a violin only crowds it.** They measure
  within half a decibel of each other in the clarinet's own bands, so it is not level and not
  spectrum. The likeliest remaining explanation is temporal - genny's violin has vibrato and a slower
  attack, so it modulates and the clarinet peeks through, while the trumpet holds steady and masks
  continuously - and the way to test it is to measure the *modulation* of the masker in those bands
  rather than its level.
* Whether the accompaniment should come down further on busy cards: with the density rule and the
  nylon guitar the margins improved by 3.5 dB on Joy to the World and 4.5 on Love Me Tender, and both
  are still slightly negative.
