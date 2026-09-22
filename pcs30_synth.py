#!/usr/bin/env python3
"""A Playcard played the way a Yamaha PCS-30 would sound.  WORK IN PROGRESS.

    python pcs30_synth.py card.bin [-o card.wav]
    python pcs30_synth.py card.bin --arranger upa      # the cartridge's patterns

A card with a side B is joined by the arranger; give the side A.

THIS IS A PROTOTYPE, and it does not yet sound like the keyboard.  It has been
through five rounds of listening against recordings of a real PCS-30, and the
last still had balance issues.  What is measured and what is set by ear is
marked where each value is set, and the state of it is in pcs30-sound.md,
"A synthesizer (work in progress)".

The notes come from pcs30_arrange.py --chip: the card's melody and obbligato,
and the PCS-30's own bass, chord and drum patterns, as the keyboard's four
chip channels play them.  This turns them into sound the way that keyboard's
YM2142 chip and the circuit behind it do, as far as they are known:

  * each part is one channel of the chip: a 32-step stepped waveform times a
    straight-line envelope, from the voice table the PCS-30 carries for the
    card's voice; the chord part's voice is chosen by rhythm, the bass is
    always entry 2;
  * every note is keyed, but its attack starts from the level the channel is
    already at, so a sustaining voice moves smoothly from note to note and a
    decaying one is struck afresh;
  * violin, flute and vibraphone have a 6 Hz vibrato that starts about 250 ms
    into every note;
  * each channel goes out on one or two of four output pins, each pin with its
    own measured low-pass filter - the reason the keyboard sounds muffled;
  * the five drums are the measured sounds, with their measured envelopes, and
    a snare struck with a cymbal silences the cymbal;
  * the tempo is the PCS-30's, from its table: a 120 bpm card plays at 127.4.

SET BY EAR, not measured: how loud each output pin is in the mix (PIN_DB),
each drum's level (DRUM_GAIN), and the envelope times, which are the YM2163
datasheet's.  Three can be changed from the environment while experimenting:

    PCS30_BASS_DB   the bass part, dB (default 0)
    PCS30_KICK_DB   the kick drum, dB on top of DRUM_GAIN (default 0)
    PCS30_OUT_LP    a one-pole roll-off after the mix, Hz (default 0, off: the
                    pins' measured filters already include the whole chain)
    PCS30_CHORD_DB  the chord part with --arranger upa, dB (default -5, because
                    one line has become three or four notes)

THE KEYBOARD'S SOUND WITH THE CARTRIDGE'S ARRANGEMENT

`--arranger upa` takes the notes from `upa_arrange.py` instead: the UPA-01's own
accompaniment patterns, with the corrections that tool makes - chords on the beat,
a fill in the rhythm's feel, bossa-nova's last chord on the clave, notes held -
played by this keyboard's voices, filters and drums. It is a machine that never
existed, and three differences from the real PCS-30 are deliberate:

  * **the card's own tempo.** The keyboard rounds every card to one of its 32
    tempos and so plays most of them 1.5 to 6% fast; a 120 bpm card really does
    play at 127.4 there. With the cartridge's arrangement that quirk is not
    wanted, so a 120 bpm card plays at 120.
  * **no four-note limit.** The real keyboard has four channels and one note
    each, and its chord part is a single line. The cartridge's is a whole chord,
    so the chord part is dealt into as many channels as it needs - see slots().
    PCS30_CHORD_DB takes that part down, by ear, since one line has become four.
  * **the organ stays where the card puts it.** `pcs30_arrange.py --chip` needs
    its octave taken back out and `upa_arrange.py` does not.

Everything else is the keyboard: the same waveforms, envelopes, voice table,
vibrato, output-pin filters, drums and the snare-over-cymbal rule.

Needs numpy and scipy, and the pattern tables: `pcs30_extract.py` from your own
PCS-30 ROM, and `upa_extract.py` from a cartridge ROM for `--arranger upa`.
"""

import argparse
import os
import subprocess
import sys
import tempfile
import wave

import numpy as np
from scipy.signal import butter, sosfilt, resample_poly

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import playcard_decode as P
import playcard_midi as M

RATE = 44100
OVER = 4                          # render at 4x and decimate: the chip's steps alias
FS = RATE * OVER
TUNING_CENTS = 3.7                # the whole instrument is this sharp (464 notes)

# ---------------------------------------------------------------- the chip
# The YM2163 datasheet's waveforms, 32 steps (figure 1); Hc as the recordings
# place its steps.
WAVES = {
    1: [-31 + 2 * i for i in range(32)],                             # St
    2: [-20] * 8 + [4] * 8 + [0] * 16,                               # Or
    3: [-25] * 16 + [24] * 16,                                       # Cl
    4: [-30] * 8 + [12] * 8 + [0] * 16,                              # Pf
    5: [-31, -5, -5, -5, 0, 0, 0, 5, 10, 31, 31] + [0] * 21,         # Hc
}

# The PCS-30's voice table, ROM 0x2CFC: (waveform, envelope, sustain,
# vibrato, level dB, output pins).  See pcs30-sound.md.
VOICES = {
    0: (4, 3, 0, 0, 0, (3,)),        # organ
    1: (3, 1, 0, 0, -6, (1, 2)),     # clarinet
    2: (4, 0, 0, 0, 0, (3,)),        # piano - and the bass
    3: (1, 0, 0, 0, 0, (2, 3)),      # guitar
    4: (5, 0, 0, 0, 0, (4,)),        # harpsichord
    6: (3, 0, 1, 1, 0, (3,)),        # vibraphone
    7: (3, 1, 0, 1, 0, (3,)),        # piccolo / flute
    8: (1, 1, 0, 0, -6, (4,)),       # oboe
    9: (1, 1, 0, 0, 0, (2,)),        # trumpet / brass
    10: (1, 1, 0, 1, 0, (1,)),       # violin / strings
}
MELODY_ENTRY = [7, 0, 10, 9, 8, 1, 4, 2, 6, 3]          # ROM 0x1BA3, card field 1-10
OBBLIGATO_ENTRY = [8, 7, 10, 9, 1, 2, 4, 3]             # ROM 0x1BAD, card field 1-8
CHORD_ENTRY = [3, 3, 3, 3, 2, 3, 3, 2, 2, 3]            # ROM 0x2D12, by rhythm
CHORD_ENTRY_ALT = [2, 2, 2, 2, 3, 2, 2, 3, 3, 2]        # ROM 0x2D1C, alternate pattern
BASS_ENTRY = 2

# Measured on the Santa Claus flute opening: it starts about 250 ms after every
# note change, reaches full depth by about 350 ms, and swings about 12 cents
# peak to peak.
VIBRATO_HZ, VIBRATO_CENTS, VIBRATO_DELAY, VIBRATO_RAMP = 6.0, 6.0, 0.25, 0.10

# The output pins' low-pass filters, as measured: (order, corner Hz).
PINS = {1: (2, 2300), 2: (2, 5200), 3: (3, 1600), 4: (2, 4000)}

# How loud each pin is in the mix, dB.  NOT measured - no schematic - and set by
# ear against recordings: the dark OR3 (piano, flute, organ) sits under the rest
# otherwise, and OR2's brass stands out.  A voice sent to two pins comes out of
# both, each through its own filter; splitting it between them left the guitar
# chord part far under the bass.
PIN_DB = {1: 0.0, 2: -4.0, 3: 4.0, 4: 0.0}

# Tuned against the recordings' long-term spectrum, not measured directly:
# how loud the bass part sits, and a gentle roll-off after the mix.
BASS_DB = float(os.environ.get('PCS30_BASS_DB', '0'))
# The keyboard's chord part is ONE note; the cartridge's is three or four, so
# playing them all at full level makes that part much louder than the machine
# ever was.  Set by ear, and only used with --arranger upa.
CHORD_DB = float(os.environ.get('PCS30_CHORD_DB', '-5'))
OUT_LOWPASS = float(os.environ.get('PCS30_OUT_LP', '0'))
KICK_DB = float(os.environ.get('PCS30_KICK_DB', '0'))
# Each drum's level.  Matched to the recordings' peak-to-music ratio and then
# brought down 6 dB by ear, the ratio having overshot.
DRUM_GAIN = {0: 4.0, 1: 3.7, 2: 2.4, 3: 1.1, 4: 1.1}

# The PCS-30 tempo table, ROM 0x1B83, by the card's tempo field; played bpm
# is 10070 / (entry + 1).
TEMPO_TABLE = [214, 197, 183, 171, 162, 154, 148, 142, 134, 128, 120, 115, 111, 105, 101, 98,
               94, 91, 88, 84, 78, 76, 73, 70, 67, 63, 60, 58, 54, 52, 51, 49]


def envelope(kind, sus, gate, total, start=0.0):
    """The datasheet's four envelopes (figure 2), straight lines, in samples.
    gate is the key-down length, total the length to render.

    start is where the channel's level already is when the key goes down.
    Every note is keyed, but the attack climbs from that level rather than from
    silence - so a sustaining voice (envelope 1, a 60 ms attack) that is still
    at full level moves to its next note without a swell, as the real keyboard
    does, while a decaying voice (envelope 0) is struck afresh.  That is the
    model that fits both the smooth brass and flute and the re-struck
    harpsichord in recordings of a real PCS-30."""
    t = np.arange(total) / FS
    g = gate / FS
    ms = 0.001
    rel = 1.2 if sus else None
    if kind == 0:                                    # decays by itself
        a = np.where(t < 60 * ms, 1 - 0.45 * t / (60 * ms), 0.55 * (1 - (t - 60 * ms) / 1.2))
        a = np.clip(a, 0, 1)
        if not sus:
            a = np.where(t < g, a, np.interp(g, t, a) * np.clip(1 - (t - g) / (60 * ms), 0, 1))
        return a
    if kind == 1:
        hold = np.clip(start + (1 - start) * t / (60 * ms), 0, 1)
    elif kind == 2:
        hold = np.where(t < 60 * ms, 1 - 0.5 * t / (60 * ms), 0.5)
    else:
        hold = np.ones_like(t)
    r = rel if rel else {1: 0.12, 2: 0.06, 3: 0.004}[kind]
    level = np.interp(g, t, hold) if total else 0
    return np.where(t < g, hold, level * np.clip(1 - (t - g) / r, 0, 1))


def tone(midi, entry, gate, total, sus_card, extra_db, start_level=0.0, start_phase=0.0):
    """One note on one chip channel.  Returns the samples, the output pins,
    and the channel's level and phase where the note stops, for the next."""
    wv, env, sus, vib, lvl, pins = VOICES[entry]
    f0 = 440 * 2 ** ((midi - 69 + TUNING_CENTS / 100) / 12)
    t = np.arange(total) / FS
    if vib:
        depth = VIBRATO_CENTS * np.clip((t - VIBRATO_DELAY) / VIBRATO_RAMP, 0, 1)
        f = f0 * 2 ** (depth * np.sin(2 * np.pi * VIBRATO_HZ * (t - VIBRATO_DELAY)) / 1200)
    else:
        f = np.full(total, f0)
    phase = start_phase + np.cumsum(f) / FS
    table = np.array(WAVES[wv], float) / 31
    sig = table[(np.floor(phase * 32) % 32).astype(int)]
    sig -= table.mean()
    e = envelope(env, sus or sus_card, gate, total, start_level)
    return sig * e * 10 ** ((lvl + extra_db) / 20), pins, float(e[-1]), float(phase[-1] % 1)


# ---------------------------------------------------------------- the drums
# The drums' amplitude envelopes, every 4 ms from the start of the hit, as
# measured on clean hits in a recording of a real PCS-30 (Feel Like Makin'
# Love's opening).  None decays smoothly: each falls to about half in the first
# 10 ms, runs down in a straight line and then stops dead.  The snare, which has
# no clean hit to measure, borrows the short cymbal's - both are noise voices on
# the same rhythm output.
KICK_ENV = [0.81, 1.00, 0.64, 0.51, 0.49, 0.42, 0.36, 0.32, 0.31, 0.32, 0.22, 0.19, 0.13,
            0.09, 0.09, 0.02, 0.02, 0.02, 0.01, 0]
LATIN_ENV = [1.00, 0.79, 0.58, 0.49, 0.47, 0.39, 0.38, 0.34, 0.29, 0.24, 0.22, 0.18, 0.14,
             0.11, 0.04, 0.03, 0.03, 0.03, 0.03, 0]
SHORT_ENV = [1.00, 0.53, 0.60, 0.42, 0.24, 0.22, 0.21, 0.22, 0.19, 0.15, 0.14, 0.09, 0.08,
             0.10, 0.08, 0.09, 0.08, 0.05, 0.02, 0.03, 0.04, 0.04, 0.04, 0.03, 0.03, 0.03,
             0.02, 0.01, 0]
LONG_ENV = [1.00, 0.56, 0.58, 0.39, 0.27, 0.27, 0.26, 0.28, 0.26, 0.24, 0.26, 0.23, 0.22,
            0.23, 0.22, 0.21, 0.21, 0.21, 0.20, 0.19, 0.19, 0.19, 0.17, 0.15, 0.12, 0.10,
            0.09, 0.06, 0.08, 0.07, 0.05, 0.04, 0.02, 0.01, 0]


def drum_env(points):
    n = int(len(points) * 0.004 * FS)
    return np.interp(np.arange(n) / FS, np.arange(len(points)) * 0.004, points)


def drum(bit, rng):
    """The measured drum sounds; see pcs30-sound.md."""
    if bit in (0, 1):                     # kick 112 Hz, latin 252 Hz: squares, steady pitch
        f0, points, corner = (112, KICK_ENV, 2500) if bit == 0 else (252, LATIN_ENV, 1100)
        gain = DRUM_GAIN[bit] * (10 ** (KICK_DB / 20) if bit == 0 else 1)
        env = drum_env(points)
        t = np.arange(len(env)) / FS
        sq = np.sign(np.sin(2 * np.pi * f0 * t))
        return sosfilt(butter(2, corner, fs=FS, output='sos'), sq) * env * gain
    if bit == 2:                          # snare: noise, 500 Hz - 3 kHz
        env = drum_env(SHORT_ENV)
        noise = rng.standard_normal(len(env))
        sig = sosfilt(butter(2, [500, 3000], btype='band', fs=FS, output='sos'), noise)
        return sig / (np.abs(sig).max() + 1e-9) * env * DRUM_GAIN[2]
    # the cymbal: fixed metallic partials, a long (bit 3) or short (bit 4) envelope
    env = drum_env(LONG_ENV if bit == 3 else SHORT_ENV)
    t = np.arange(len(env)) / FS
    sig = np.zeros(len(env))
    for f, db in ((673, -3), (2016, 0), (2519, -14), (3359, -14), (5373, -17)):
        sig += 10 ** (db / 20) * np.sign(np.sin(2 * np.pi * f * t + rng.uniform(0, 6.28)))
    sig = sosfilt(butter(2, 6000, fs=FS, output='sos'), sig)
    return sig / (np.abs(sig).max() + 1e-9) * env * DRUM_GAIN[bit]


# Both arrangers' GM drum notes.  75 is pcs30_arrange's claves and 63 is
# upa_arrange's conga; on this keyboard they are the same latin drum.
DRUM_BIT = {36: 0, 75: 1, 63: 1, 38: 2, 46: 3, 42: 4}


# ---------------------------------------------------------------- the card
def slots(ns):
    """Deal one part's notes into monophonic slots, so a chord can sound.

    A real PCS-30 channel plays one note at a time, and the render carries its
    level and its oscillator from note to note on that assumption.  The
    cartridge's chord part is three or four notes at once, and nothing written
    today has to be limited to the keyboard's four channels - so each note goes
    to the first slot whose last note has finished, and every slot is then one
    well-behaved chip channel.  A part that never overlaps itself, which is every
    part the PCS-30's own arranger writes, comes back as a single slot.
    """
    out = []
    for n in sorted(ns):
        for sl in out:
            if sl[-1][0] + sl[-1][4] <= n[0]:
                sl.append(n)
                break
        else:
            out.append([n])
    return out


def render(cards, out, duck_db=-6.0, arranger='pcs30'):
    h = P.parse_card(P.tobits(P.check_card(cards[0])))
    field = P.TEMPO.index(h['tempo'])
    # The keyboard plays every card at one of its own 32 tempos, a little fast.
    # With the cartridge's arrangement that quirk is not wanted: the card's own
    # metronome mark is what the music was written at, and neither machine's
    # rounding belongs in a render made today.
    played = h['tempo'] if arranger == 'upa' else 10070.0 / (TEMPO_TABLE[field] + 1)
    rhythm = h['rhythm'] - 1
    chord_entry = (CHORD_ENTRY_ALT if h.get('f3') else CHORD_ENTRY)[rhythm]
    entries = {0: MELODY_ENTRY[h['field4'] - 1], 1: OBBLIGATO_ENTRY[h['field6'] - 1],
               2: BASS_ENTRY, 3: chord_entry}
    extra = {0: 0.0, 1: -6.0 if entries[1] == 7 else 0.0, 2: BASS_DB,
             3: (-6.0 if chord_entry == 3 else 0.0) + (CHORD_DB if arranger == 'upa' else 0.0)}
    sus_card = bool(h.get('bit1'))            # the header's sustain bit
    # pcs30_arrange raises the organ an octave, because General MIDI synths
    # voice it low; the PCS-30 plays it where the card says.  (Its piccolo
    # octave is what the real keyboards do, and stays.)
    octave = {0: -12 if P.voice(P.MELODY_VOICE, h['field4']) == 'organ' else 0,
              1: 0, 2: 0, 3: 0}
    if arranger == 'upa':
        octave[0] = 0                 # upa_arrange leaves the organ where the card puts it

    with tempfile.TemporaryDirectory() as tmp:
        mid = os.path.join(tmp, 'card.mid')
        # --chip: the parts as the keyboard's own channels play them, not
        # rearranged for a General MIDI synth.
        tool = 'upa_arrange.py' if arranger == 'upa' else 'pcs30_arrange.py'
        args = [] if arranger == 'upa' else ['--chip']
        r = subprocess.run([sys.executable, os.path.join(HERE, tool)] + cards
                           + ['-o', mid] + args, capture_output=True, text=True)
        if not os.path.exists(mid):
            raise P.Missing('%s made no arrangement:\n%s'
                            % (tool, (r.stdout + r.stderr).strip()))
        song = M.read_midi(mid)
    sec = 60.0 / (song['tpq'] * played)             # the PCS-30's tempo, not the card's
    notes = song['notes']
    end = max(n[0] + n[4] for n in notes) * sec + 2.0
    buses = {k: np.zeros(int(end * FS)) for k in (1, 2, 3, 4)}
    drums = np.zeros(int(end * FS))
    rng = np.random.default_rng(1)

    # one chip channel a part: a new note cuts the one before
    by_ch = {}
    for n in notes:
        by_ch.setdefault(n[1], []).append(n)
    for ch, ns in by_ch.items():
        ns.sort()
        if ch == 9:
            # The snare and both cymbals share one rhythm output, and where the
            # pattern strikes the snare and a cymbal together, only the snare is
            # heard: a waltz's beats 2 and 3 carry both in the ROM, and a
            # recording of a real PCS-30 has the snare alone.
            strikes = {}
            for tick, _, pitch, vel, ticks, _ in ns:
                if pitch in DRUM_BIT:
                    strikes.setdefault(tick, set()).add(DRUM_BIT[pitch])
            for tick, bits in sorted(strikes.items()):
                if 2 in bits:
                    bits -= {3, 4}
                s = int(tick * sec * FS)
                for bit in sorted(bits):
                    d = drum(bit, rng)
                    e = min(len(drums), s + len(d))
                    drums[s:e] += d[:e - s]
            continue
        if ch not in entries:
            continue
        # Every note is keyed on the chip, but the channel's level and its
        # oscillator carry on into the next note when it follows at once; see
        # envelope().  A new note cuts the one before: one channel, one note.
        shift = octave[ch]
        for sl in slots(ns):
            level, phase_ = 0.0, 0.0
            for i, (tick, _, pitch, vel, ticks, _) in enumerate(sl):
                s0 = int(tick * sec * FS)
                gate = int(ticks * sec * FS)
                nxt = int(sl[i + 1][0] * sec * FS) if i + 1 < len(sl) else len(drums)
                total = max(1, min(nxt - s0, gate + int(1.3 * FS), len(drums) - s0))
                ducked = ch == 1 and vel < 90              # both arrangers duck by velocity
                sig, pins, end_level, end_phase = tone(
                    pitch + shift, entries[ch], min(gate, total), total, sus_card,
                    extra[ch] + (duck_db if ducked else 0.0), level, phase_)
                for p in pins:
                    buses[p][s0:s0 + total] += sig
                follows = total == nxt - s0                # still sounding when the next comes
                level, phase_ = (end_level, end_phase) if follows else (0.0, 0.0)
    mix = drums.copy()
    for p, (order, corner) in PINS.items():
        mix += sosfilt(butter(order, corner, fs=FS, output='sos'), buses[p]) * 10 ** (PIN_DB[p] / 20)
    if OUT_LOWPASS:
        mix = sosfilt(butter(1, OUT_LOWPASS, fs=FS, output='sos'), mix)
    out_audio = resample_poly(mix, 1, OVER)
    out_audio /= np.abs(out_audio).max() + 1e-9
    out_audio *= 0.89                               # -1 dBFS
    with wave.open(out, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((out_audio * 32767).astype('<i2').tobytes())
    P.say("%s: %.1f s at %.1f bpm (the card says %d); %s's arrangement; melody entry "
          '%d, obbligato %d, chord %d, bass %d -> %s'
          % (os.path.basename(cards[0]), len(out_audio) / RATE, played, h['tempo'],
             'the cartridge' if arranger == 'upa' else 'the PCS-30',
             entries[0], entries[1], chord_entry, BASS_ENTRY, out), prefix='')


def main():
    ap = argparse.ArgumentParser(description='A Playcard as a PCS-30 would sound (a prototype).')
    ap.add_argument('cards', nargs=1, help='the card')
    ap.add_argument('-o', '--out', help='the .wav to write (default: beside the card)')
    ap.add_argument('--arranger', choices=('pcs30', 'upa'), default='pcs30',
                    help="whose accompaniment to play: the PCS-30's own (default), or "
                         "the UPA-01 cartridge's, corrected by upa_arrange.py - this "
                         "keyboard's sound, the cartridge's patterns, and no four-note "
                         'limit')
    a = ap.parse_args()
    for c in a.cards:
        P.check_card(c)
    out = a.out or os.path.splitext(a.cards[0])[0] + (
        '.upa-pcs30.wav' if a.arranger == 'upa' else '.pcs30.wav')
    render(a.cards, out, arranger=a.arranger)


if __name__ == '__main__':
    P.run(main)
