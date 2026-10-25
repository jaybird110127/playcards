#!/usr/bin/env python3
"""A Playcard as a .wav, by handing the cartridge's arrangement to genny.

    python upa_genny.py card.bin [-o card.wav]
    python upa_genny.py card.bin --voices fm        # the raw 2-operator FM synth
    python upa_genny.py card.bin --spec-only        # write the JSON, render nothing
    python upa_genny.py --all                       # a whole folder, into upa-genny/

`upa_arrange.py` writes what the UPA-01 plays, corrected; this turns that into
audio without a General MIDI synth anywhere.

It needs **genny**, which is not part of this project: a CLI by **Oriol Gomez**
that renders JSON specs of layered notes, drums and effects to a WAV, with no
external audio dependencies. <https://github.com/ogomez92/genny>. Clone it and
install the command with

    python install.py --tool        # from the genny clone; uses uv

after which `genny` is on PATH and this tool finds it. See `genny-render.md` for
the rest, including what was measured to arrive at the levels here.

WHY THIS WORKS AT ALL

genny's model is a list of layers, each a sequence of steps, and an arrangement
fits it exactly. Checked across the corpus: **no part ever overlaps itself**, and
every group of notes struck together has one length - so each part converts to a
sequential step list with nothing lost and nothing approximated. The drums go in
as one `pattern` layer a kit piece with explicit hit positions. A seventy-second
card renders in about five seconds.

THE VOICES

The card names ten melody voices and eight obbligato ones, and genny's catalog
happens to carry nearly all of them by name, which is a better match than a GM
program number through whatever synth is installed:

    organ violin trumpet oboe clarinet harpsichord piano vibraphone guitar
    flute strings brass

Only the **piccolo** is missing; it becomes a breathy `flute`, which is what a
piccolo is, and the arrangement has already put it an octave up.

The card's "piano" is Yamaha's `EPIANO1`, an electric piano, and genny's `epiano`
is the faithful choice - but the **acoustic** `piano` was better to listen to and
is what is used. The same goes for the accompaniment, which has no voice on the
card at all: a `steel_guitar` and an `upright_bass`, chosen by ear.

    --voices native   (default)  the catalog's own voices, plus `fm_bass` and
                                 `clav` for the accompaniment and a real kit
    --voices fm                  the raw `synth` instrument with `wave: fm` -
                                 one modulator on one carrier, a ratio and an
                                 index per voice, in the spirit of each

WHAT THIS IS NOT

genny's FM is **two operators**; the SFG-01's is four, so this cannot imitate the
cartridge's own voices and does not try. For the genuine article, render the
firmware's own capture instead - `csrc/playcard` then `csrc/fmlog2wav` - which is
a real YM2151 playing the real card. What this is for is the arrangement as
`upa_arrange.py` corrects it, which no cartridge will ever play.

Every level here is set by ear and is listed in one place below, and
`--gain NAME=VALUE` moves any part without editing the file:

    python upa_genny.py card.bin --gain chord=0.85 --gain kick=0.55
"""

import argparse
import glob
import json
import math
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playcard_decode as P
import playcard_midi as M
import midi_export as ME
import pcs30_arrange as A               # for the velocities the arranger uses

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, 'upa-genny')      # where --all writes


def fm(ratio, index, attack, decay, sustain, release, cutoff):
    """One genny `synth` voice, as two-operator FM."""
    return ('synth', {'wave': 'fm', 'ratio': ratio, 'index': index,
                      'attack': attack, 'decay': decay, 'sustain': sustain,
                      'release': release, 'cutoff': cutoff})


# The card's voice names -> a genny instrument and its parameters.
NATIVE = {
    'piccolo': ('flute', {'breath': 0.3}),        # genny has no piccolo
    'organ': ('organ', {}),
    'violin': ('violin', {}),
    'trumpet': ('trumpet', {}),
    'oboe': ('oboe', {}),
    'clarinet': ('clarinet', {}),
    'harpsichord': ('harpsichord', {}),
    'piano': ('piano', {}),                       # see the note below
    'vibraphone': ('vibraphone', {}),
    'guitar': ('guitar', {}),
    'flute': ('flute', {}),
    'strings': ('violin', {}),                    # by ear: closer to a real
                                                  # keyboard than the ensemble
    'brass': ('brass', {}),
}
FM = {
    'piccolo': fm(3.0, 1.2, 0.03, 0.10, 0.80, 0.12, 3400),
    'organ': fm(2.0, 1.6, 0.005, 0.05, 1.00, 0.06, 2600),
    'violin': fm(3.0, 2.2, 0.09, 0.20, 0.85, 0.25, 3000),
    'trumpet': fm(1.0, 3.2, 0.05, 0.15, 0.85, 0.15, 3200),
    'oboe': fm(3.0, 2.6, 0.04, 0.12, 0.80, 0.14, 3000),
    'clarinet': fm(3.0, 1.4, 0.04, 0.12, 0.85, 0.14, 2400),
    'harpsichord': fm(2.0, 3.0, 0.002, 0.50, 0.00, 0.18, 3400),
    'piano': fm(1.0, 2.4, 0.002, 1.10, 0.00, 0.30, 2800),
    'vibraphone': fm(4.0, 1.0, 0.004, 1.60, 0.00, 0.50, 2600),
    'guitar': fm(2.0, 2.0, 0.004, 0.70, 0.00, 0.25, 2600),
    'flute': fm(2.0, 0.6, 0.06, 0.12, 0.90, 0.12, 2200),
    'strings': fm(2.0, 1.8, 0.12, 0.25, 0.90, 0.35, 2600),
    'brass': fm(1.0, 2.8, 0.06, 0.18, 0.85, 0.18, 3000),
}
# The accompaniment's two parts have no voice on the card - the cartridge gives
# them FM patches of its own - so these are chosen by ear.  Neither is what the
# MIDI arranger names (it asks a GM synth for an acoustic bass and a guitar).
# A `clav` was tried for the chord part and did not hold: a clavinet is a short
# struck string by design, and the arrangement wants a chord that rings to the
# bar line.
BASS = {'native': ('upright_bass', {}),       # E1-G3; the bass part is 31-48
        'fm': fm(1.0, 2.0, 0.004, 0.80, 0.20, 0.20, 1400)}
# `electric_guitar`, picked by ear from an audition of all ten of genny's
# plucked voices over Love Me Tender's busy second verse - a clean single-coil
# tone that SUSTAINS, which suits a chord written to ring to the bar line.  The
# two voices that measured furthest out of a clarinet obbligato's way, the dry
# `pizzicato` and `muted_guitar`, were not the ones that sounded right, and this
# one measures no better than the steel guitar it replaces.
CHORD = {'native': ('electric_guitar', {}),   # E2-E6; the chord band is 61-72
         'fm': fm(2.0, 2.2, 0.004, 0.50, 0.10, 0.20, 2600)}

# upa_arrange's GM drum notes -> genny's kit
DRUM = {36: 'kick', 38: 'snare', 42: 'hihat', 46: 'openhat', 63: 'conga'}

# ---------------------------------------------------------------- the levels
#
# All by ear, and all lower on the drums than genny's own mix guidance (kick 1.0,
# snare 0.6-0.85, hats 0.25-0.4): these patterns put something on nearly every
# step, so at those levels the kit walks over the music.  The chord part sits
# above genny's suggested 0.35-0.5 for the same reason in reverse - it is the
# accompaniment's only harmony and was lost under the drums.
PART_GAIN = {'melody': 0.85, 'obbligato': 0.70, 'bass': 0.60, 'chord': 0.80}
# 2.5 dB below the levels that were first settled by ear, on a second listen
DRUM_GAIN = {'kick': 0.29, 'snare': 0.22, 'hihat': 0.11,
             'openhat': 0.13, 'conga': 0.19}

# genny's kick at its defaults has a pitch drop on every beat - `punch` is "click
# and pitch-drop amount" and starts at 1.0 - which on a disco card, kicking four
# to the bar, is a sweep you cannot stop hearing.  Softened, tuned down and given
# a longer body, all by ear against five alternatives including `kick808` and
# `taiko`.
DRUM_PARAMS = {'kick': {'decay': 0.5, 'punch': 0.4, 'tune': 45}}

# How much a ducked obbligato note comes down.  genny's `vel` is mostly a
# BRIGHTNESS control: measured over all eight obbligato voices, the card's own
# duck - a velocity of 0x60 against 0x80 - moved the level by 0.4 to 1.4 dB, and
# the harpsichord was the 0.4.  That is why Love Theme did not seem to duck.  So
# the ducked notes go in their own layer with a real gain instead, 6 dB, which is
# the figure the rest of this project uses (see "How deep the duck is depends on
# the machine" in playcard-format.md).
#
# And they are written at FULL velocity, so the gain is the only thing that
# changes.  Carrying the card's lower velocity across as well made a ducked note
# quieter AND darker, and a dark quiet note disappears under a melody: the duck
# on this machine is a volume step, not a filter.  `--duck DB` tries another
# depth; 0 turns it off.
DUCK_DB = -6.0

# Per-voice trims, dB, from the measurement above: each voice rendered alone at
# the gain and velocity its part gets, measured K-weighted, and compared with the
# mean of its role.  The spread was 2.7 dB across the melody voices and 2.3 dB
# across the obbligato ones, with the harpsichord and the guitar the quiet ones
# in both - which is the other half of why a harpsichord obbligato disappears.
VOICE_TRIM = {'piccolo': -0.6, 'organ': -0.6, 'violin': -0.4, 'trumpet': -0.5,
              'oboe': -0.7, 'clarinet': -0.4, 'harpsichord': 1.8, 'piano': 0.5,
              'vibraphone': -0.8, 'guitar': 1.6, 'flute': -0.6, 'strings': -0.7,
              'brass': -0.4}

# How far the obbligato has to come UP to stay audible under each melody voice,
# dB.  This is masking rather than level, and it had to be measured as such:
# broadband loudness says every melody voice is within a decibel of the others,
# while in the third-octave bands a clarinet obbligato actually occupies, the
# spread is SEVEN decibels - 8 dB under a violin or a clarinet melody, 1 dB under
# a harpsichord.  Measured on Can't Help Falling In Love by swapping the melody
# instrument and leaving everything else alone (scratchpad masking2.py), aiming
# for a 5 dB margin, and only ever lifting: the pairs that were already clear
# are left where they are.
MASK_LIFT = {'violin': 3.0, 'clarinet': 3.0, 'piccolo': 3.0, 'organ': 2.5,
             'trumpet': 2.5}
PART_OF_CHANNEL = {0: 'melody', 1: 'obbligato', 2: 'bass', 3: 'chord'}

# Where they sit.  Measured two ways, which disagreed and both mattered: each
# layer of a real card rendered alone, and one phrase per voice at the gain and
# velocity its part gets (the second is in the scratchpad's duck_analysis.py).
# The second found what the first could not: the whole accompaniment together -
# chords, bass and kit - came out **8 to 11 dB above the obbligato**, which is
# the owner's "the accompaniment overshadows the obbligato", measured.  So the
# obbligato is up 3 dB and the accompaniment down 3 from the levels before,
# keeping the guitar-against-drums balance that was settled by ear.
#
# Do NOT place the bass by the ear-weighted figure `genny info` also prints: the
# weighting discounts 60-80 Hz by design, so the upright bass reads 10 dB quieter
# than it sounds and chasing that number buries everything else.
#
# `--gain NAME=VALUE` moves any part without editing this file.

# A busy accompaniment pattern buries the obbligato, and the patterns differ
# enormously: the standard rock chord part strikes twice a bar while slow-rock's
# ALTERNATE strikes twelve times.  Measured on Love Me Tender, whose second verse
# is that alternate, the chord part alone sat 9.5 dB OVER the ducked clarinet in
# its own bands; on Joy to the World, a disco card, no single part was over it but
# the accompaniment together was, by 6.8 dB.
#
# So the chord part is scaled by how often it strikes, which keeps that part's
# ENERGY roughly constant rather than its per-note level: doubling the strike
# rate adds 3 dB, so the gain comes down by the square root of the ratio.  Two
# strikes a bar is the reference, because that is the standard rock pattern whose
# balance was settled by ear, and the floor stops it disappearing altogether.
# The exponent is 0.35 rather than the 0.5 that would hold the part's energy
# exactly constant: full compensation took the chord part too far down on the
# busiest patterns - the march's alternate strikes 7.2 times a bar and was losing
# 5.6 dB - and the owner heard that as the accompaniment being too soft on some
# cards.  Two strikes a bar is still the reference, so the sparse patterns are
# untouched by it.
DENSITY_REF = 2.0                       # chord strikes a bar
DENSITY_EXP = 0.35
DENSITY_FLOOR = 0.6                     # never scale below this (-4.4 dB)
REVERB = {'type': 'reverb', 'mix': 0.12, 'size': 0.4}
COMPRESSOR = {'type': 'compressor', 'threshold': -16, 'ratio': 2.5}
NORMALIZE = -2.0


class Missing(Exception):
    """genny is not installed, with instructions."""


def genny():
    path = shutil.which('genny')
    if not path:
        raise Missing(
            'no `genny` on PATH.\n'
            'This needs genny, a CLI by Oriol Gomez that renders JSON note specs\n'
            'to a WAV:  https://github.com/ogomez92/genny\n'
            'Clone it and run `python install.py --tool` there, or write the spec\n'
            'alone with --spec-only and render it yourself.')
    return path


# upa_arrange raises two voices an octave for General MIDI synths.  The
# PICCOLO's is real - the Yamahas play their piccolo up there - but the ORGAN's
# is an accommodation, because most GM synths voice a percussive organ low, and
# genny's `organ` does not need it.  So that one is taken back out.
UNDO_OCTAVE = {'organ': -12}


def steps_for(notes, tpq, keep=None):
    """One part's notes as genny step objects, with rests between them.

    Notes struck together become one chord step.  That this is lossless is a
    measured fact about the arrangement rather than an assumption: no part
    overlaps itself, and a group struck together always shares one length.
    """
    groups = {}
    for tick, _, pitch, vel, ticks, _ in sorted(notes):
        if keep is not None and not keep(vel):
            continue
        groups.setdefault((tick, ticks), []).append((pitch, vel))
    out, at = [], 0
    for (tick, ticks), group in sorted(groups.items()):
        if tick > at:
            out.append({'note': '-', 'dur': round((tick - at) / float(tpq), 6)})
        step = {'dur': round(ticks / float(tpq), 6),
                'vel': round(max(v for _, v in group) / 127.0, 3)}
        pitches = sorted(p for p, _ in group)
        if len(pitches) == 1:
            step['note'] = pitches[0]
        else:
            step['notes'] = pitches
        out.append(step)
        at = tick + ticks
    return out


def gains(override=None):
    """The mix, with any `name=value` overrides applied."""
    out = dict(PART_GAIN)
    out.update(DRUM_GAIN)
    for item in override or ():
        name, _, value = item.partition('=')
        if name not in out:
            raise Missing('no part called "%s"; there is %s'
                          % (name, ', '.join(sorted(out))))
        out[name] = float(value)
    return out


def spec_for(card, out_wav, voices='native', arrange_args=(), quiet=False,
             override=None, duck_db=DUCK_DB):
    """-> (the genny spec, a one-line description of the voices)."""
    gain = gains(override)
    h = P.parse_card(P.tobits(P.check_card(card)))
    mid = os.path.splitext(out_wav)[0] + '.mid'
    r = subprocess.run([sys.executable, os.path.join(HERE, 'upa_arrange.py'), card,
                        '-o', mid] + list(arrange_args),
                       cwd=HERE, capture_output=True, text=True)
    if not os.path.exists(mid):
        raise Missing('upa_arrange.py made no arrangement:\n'
                      + (r.stdout + r.stderr).strip())
    song = M.read_midi(mid)
    os.remove(mid)
    tpq = song['tpq']
    by_ch = {}
    for n in song['notes']:
        by_ch.setdefault(n[1], []).append(n)

    table = FM if voices == 'fm' else NATIVE
    mel = P.voice(P.MELODY_VOICE, h['field4'])
    obb = P.voice(P.OBBLIGATO_VOICE, h['field6'])
    inst = {0: table.get(mel, table['piano']), 1: table.get(obb, table['flute']),
            2: BASS[voices], 3: CHORD[voices]}

    # how busy the chord part is, in strikes a bar
    bar_beats = 3 if h['rhythm'] == A.WALTZ else 4
    strikes = len({n[0] for n in by_ch.get(3, [])})
    end = max((n[0] + n[4] for n in song['notes']), default=0)
    bars = max(1.0, end / float(tpq * bar_beats))
    density = strikes / bars
    busy = max(DENSITY_FLOOR, (DENSITY_REF / density) ** DENSITY_EXP)         if density > DENSITY_REF else 1.0
    busy_db = 20 * math.log10(busy)

    voice_of = {0: mel, 1: obb, 2: None, 3: None}
    layers = []
    for ch in (0, 1, 2, 3):
        if not by_ch.get(ch):
            continue
        name, params = inst[ch]
        part = PART_OF_CHANNEL[ch]
        trim = VOICE_TRIM.get(voice_of[ch], 0.0)
        if ch == 1:
            trim += MASK_LIFT.get(mel, 0.0)     # clear of THIS melody voice
        g = gain[part] * 10 ** (trim / 20.0)
        if ch == 3:
            g *= busy                       # see DENSITY_REF

        def make(steps, this_gain):
            layer = {'type': 'seq', 'inst': name, 'steps': steps,
                     'gain': round(this_gain, 4)}
            if params:
                layer['params'] = params
            if voice_of[ch] in UNDO_OCTAVE:
                layer['transpose'] = UNDO_OCTAVE[voice_of[ch]]
            return layer

        if ch == 1:
            # The obbligato goes in two layers, open and ducked, so the duck is
            # a real level change rather than genny's velocity alone.
            full = A.OBBLIGATO_VEL              # anything under it is ducked
            open_steps = steps_for(by_ch[ch], tpq, keep=lambda v: v >= full)
            duck_steps = steps_for(by_ch[ch], tpq, keep=lambda v: v < full)
            for step in duck_steps:             # full velocity: see DUCK_DB
                if 'vel' in step:
                    step['vel'] = round(full / 127.0, 3)
            if any('note' in x or 'notes' in x for x in open_steps):
                layers.append(make(open_steps, g))
            if any('note' in x or 'notes' in x for x in duck_steps):
                layers.append(make(duck_steps, g * 10 ** (duck_db / 20.0)))
        else:
            layers.append(make(steps_for(by_ch[ch], tpq), g))
    hits = {}
    for tick, _, pitch, vel, ticks, _ in sorted(by_ch.get(9, [])):
        kind = DRUM.get(pitch)
        if kind:
            hits.setdefault(kind, []).append(round(tick / float(tpq), 6))
    for kind in sorted(hits):
        layer = {'type': 'pattern', 'kind': kind, 'hits': hits[kind],
                 'gain': gain[kind]}
        if kind in DRUM_PARAMS:
            layer['params'] = dict(DRUM_PARAMS[kind])
        layers.append(layer)

    spec = {'out': out_wav, 'bpm': h['tempo'], 'layers': layers,
            'fx': [REVERB, COMPRESSOR], 'normalize': NORMALIZE,
            'max_loudness': None,       # this is music, not a UI sound
            'tail': 2.0}
    how = ('%s voices; melody %s -> %s, obbligato %s -> %s; the chord part '
           'strikes %.1f times a bar%s'
           % (voices, mel, inst[0][0], obb, inst[1][0], density,
              ', so %+.1f dB' % busy_db if busy < 1 else ''))
    return spec, how


def render(card, out=None, voices='native', arrange_args=(), spec_only=False,
           quiet=False, override=None, duck_db=DUCK_DB):
    if out is None:
        base = os.path.splitext(os.path.basename(card))[0].replace('_side-a', '')
        out = base + '.genny.wav'
    spec, how = spec_for(card, out, voices, arrange_args, quiet, override,
                         duck_db)
    path = os.path.splitext(out)[0] + '.genny.json'
    with open(path, 'w') as f:
        json.dump(spec, f, indent=1)
        f.write('\n')
    events = sum(len(l.get('steps', l.get('hits', []))) for l in spec['layers'])
    if not quiet:
        P.say('%s: %s, %d layers, %d events' % (os.path.basename(card), how,
                                                len(spec['layers']), events),
              prefix='')
    if spec_only:
        if not quiet:
            P.say('  -> %s' % path, prefix='')
        return path
    r = subprocess.run([genny(), 'render', path, '--quiet'],
                       capture_output=True, text=True)
    if r.returncode or not os.path.exists(out):
        raise Missing('genny could not render it:\n' + (r.stdout + r.stderr).strip())
    os.remove(path)
    if not quiet:
        P.say('  -> %s' % out, prefix='')
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('card', nargs='?')
    ap.add_argument('-o', '--out', help='the .wav to write')
    ap.add_argument('--all', action='store_true',
                    help='render every card in a folder instead of one')
    ap.add_argument('--in-dir',
                    help='with --all, the folder to read cards from '
                         '(default: the card corpus; use . for the current one)')
    ap.add_argument('--out-dir', default=OUT_DIR,
                    help='with --all, where the .wav files go (default: upa-genny/)')
    ap.add_argument('--voices', choices=('native', 'fm'), default='native',
                    help="genny's own voices (default), or its raw two-operator "
                         'FM synth')
    ap.add_argument('--spec-only', action='store_true',
                    help='write the genny JSON and stop')
    ap.add_argument('--duck', type=float, default=DUCK_DB, metavar='DB',
                    help='how far a ducked obbligato note comes down, dB '
                         '(default %.0f; 0 for no duck)' % DUCK_DB)
    ap.add_argument('--gain', action='append', metavar='NAME=VALUE', default=[],
                    help='move one part in the mix: melody, obbligato, bass, '
                         'chord, kick, snare, hihat, openhat, conga '
                         '(repeatable, e.g. --gain chord=0.85 --gain kick=0.55)')
    ap.add_argument('--drums', choices=('mixed', 'upa', 'pcs30'),
                    help="passed to upa_arrange.py: whose drum patterns")
    ap.add_argument('--as-is', action='store_true',
                    help='passed to upa_arrange.py: what the cartridge plays')
    a = ap.parse_args()
    extra = []
    if a.drums:
        extra += ['--drums', a.drums]
    if a.as_is:
        extra += ['--as-is']
    if a.all:
        where = a.in_dir or P.CARD_DIR
        cards = sorted(glob.glob(os.path.join(where, '*.bin')))
        if not cards:
            print('upa_genny: no cards in %s' % where)
            return 1
        if not os.path.isdir(a.out_dir):
            os.makedirs(a.out_dir)
        done = failed = 0
        for c in cards:
            base = os.path.splitext(os.path.basename(c))[0].replace('_side-a', '')
            out = os.path.join(a.out_dir, base + '.wav')
            try:
                h = P.parse_card(P.tobits(P.check_card(c)))
                if h['type'] == 2:
                    continue                    # a side B is rendered with its A
                render(c, out, a.voices, extra, a.spec_only, quiet=True,
                       override=a.gain, duck_db=a.duck)
                done += 1
            except (Missing, SystemExit) as e:
                failed += 1
                print('  %s: %s' % (os.path.basename(c), e))
        print('%d cards rendered into %s%s'
              % (done, a.out_dir, ', %d failed' % failed if failed else ''))
        return 0

    if not a.card:
        ap.error('give a card, or --all')
    try:
        render(a.card, a.out, a.voices, extra, a.spec_only, override=a.gain,
               duck_db=a.duck)
    except Missing as e:
        print(e)
        return 1
    return 0


if __name__ == '__main__':
    P.run(main)
