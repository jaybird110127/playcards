#!/usr/bin/env python3
"""
Measure how loud each UPA-01 voice is, and check the lead mix built from it.

    python voice_levels.py            # the table: every melody and obbligato voice
    python voice_levels.py --verify   # lead's balance on cards the table never saw

The UPA-01's voices are not equally loud at one panel setting: the oboe melody
is 8.6 dB louder than the piano.  So "--mix lead" in playcard.c sets the melody
and obbligato volumes from the card's own voices, using the table this prints
(MELODY_LUFS and OBBLIGATO_LUFS there).

THE TABLE.  Eight cards are re-headed to each voice in turn with header_edit.py
and played with only that part up - everything else at volume 0, which is
about 45 dB down and negligible - at panel volume 30.  The level is BS.1770
integrated loudness: K-weighted and gated, so rests do not count.  The mean of
the eight goes in the table; a voice varies by 1-2 LU from card to card, the
piano by up to 4.  Loudness is linear in the panel volume for every voice,
1.13 LU a step, from 20 to 40.

THE CHECK.  One card for each melody/obbligato voice pair in the corpus, none
of them the eight: each part played alone at the volumes lead chose, and the
differences set against lead's targets (melody 3 LU over the obbligato, 4 over
the accompaniment).

Takes several minutes either way.  Needs playcard and fmlog2wav built here,
the ROMs (../Roms/README.md), and numpy and scipy.
"""

import glob
import math
import os
import re
import subprocess
import sys
import tempfile
import wave

import numpy as np
from scipy.signal import lfilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import playcard_decode as P

EXE = os.path.join(HERE, 'playcard.exe' if os.name == 'nt' else 'playcard')
WAV = os.path.join(HERE, 'fmlog2wav.exe' if os.name == 'nt' else 'fmlog2wav')
CARDS_DIR = os.path.join(ROOT, 'Original Playcards')
TMP = tempfile.mkdtemp(prefix='voice_levels_')
PARTS = ('melody', 'obbligato', 'chord', 'bass', 'rhythm')

# The eight the table is measured on: varied tempos, rhythms and ranges.
CARDS = [
    'playcard_17-541_beatles_lady_madonna.bin',
    'playcard_17-545_great-standards-1_night_and_day.bin',
    'playcard_17-548_latin-1_la_paloma.bin',
    'playcard_17-554_popular-hits-4_endless_love.bin',
    'playcard_17-557_christmas-1_o_come_all_ye_faithful.bin',
    'playcard_17-566_broadway-1-my-fair-lady_get_me_to_the_church.bin',
    'playcard_17-578_polka-1_there_is_a_tavern_in_the_town.bin',
    'playcard_no-269_german-1_ein_jager_aus_kurpfalz.bin',
]


def kweight(fs):
    """BS.1770's two filters - a high shelf, then a high pass - at any rate."""
    G, Q, fc = 3.999843853973347, 0.7071752369554196, 1681.974450955533
    K = math.tan(math.pi * fc / fs)
    Vh = 10 ** (G / 20)
    Vb = Vh ** 0.4996667741545416
    a0 = 1 + K / Q + K * K
    shelf = ([(Vh + Vb * K / Q + K * K) / a0, 2 * (K * K - Vh) / a0,
              (Vh - Vb * K / Q + K * K) / a0],
             [1, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0])
    Q, fc = 0.5003270373238773, 38.13547087602444
    K = math.tan(math.pi * fc / fs)
    a0 = 1 + K / Q + K * K
    highpass = ([1, -2, 1], [1, 2 * (K * K - 1) / a0, (1 - K / Q + K * K) / a0])
    return shelf, highpass


def loudness(path):
    """Integrated loudness in LUFS, or None if the file is silent."""
    w = wave.open(path)
    fs, ch = w.getframerate(), w.getnchannels()
    x = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2').astype(float) / 32768
    x = x.reshape(-1, ch)
    for b, a in kweight(fs):
        x = lfilter(b, a, x, axis=0)
    blk, hop = int(0.4 * fs), int(0.1 * fs)
    ms = np.array([np.sum(np.mean(x[i:i + blk] ** 2, axis=0))
                   for i in range(0, len(x) - blk, hop)])
    if not len(ms):
        return None
    lk = -0.691 + 10 * np.log10(ms + 1e-20)
    gated = ms[lk > -70]
    if not len(gated):
        return None
    rel = -0.691 + 10 * np.log10(np.mean(gated)) - 10
    gated = ms[(lk > -70) & (lk > rel)]
    return -0.691 + 10 * np.log10(np.mean(gated))


def play(card, args, tag):
    """Run a card with these playcard options; its loudness and stdout."""
    log, wav = os.path.join(TMP, tag + '.fmlog'), os.path.join(TMP, tag + '.wav')
    r = subprocess.run([EXE, card, '-o', log, '--seconds', '60'] + args,
                       cwd=ROOT, capture_output=True, text=True, check=True)
    subprocess.run([WAV, log, wav], capture_output=True, check=True)
    return loudness(wav), r.stdout


def table():
    for part, n, opt in (('melody', 10, '--melody-voice'),
                         ('obbligato', 8, '--obbligato-voice')):
        for field in range(1, n + 1):
            levels = []
            for c in CARDS:
                img = os.path.join(TMP, 'card.bin')
                subprocess.run([sys.executable, os.path.join(ROOT, 'header_edit.py'),
                                os.path.join(CARDS_DIR, c), '-o', img, opt, str(field)],
                               capture_output=True, check=True)
                lv, _ = play(img, ['--mix', 'cartridge', '--volume',
                                   'all=0,%s=30' % part], 'part')
                if lv is not None:
                    levels.append(lv)
            names = P.MELODY_VOICE if part == 'melody' else P.OBBLIGATO_VOICE
            print('%-9s %2d %-12s %6.1f LUFS   spread %.1f' % (
                part, field, P.voice(names, field), np.mean(levels),
                max(levels) - min(levels)), flush=True)
    print('accompaniment, chord 28 bass 26 rhythm 26:')
    acc = [play(os.path.join(CARDS_DIR, c), ['--mix', 'cartridge', '--volume',
                'melody=0,obbligato=0,chord=28,bass=26,rhythm=26'], 'acc')[0] for c in CARDS]
    print('          %6.1f LUFS   spread %.1f' % (np.mean(acc), max(acc) - min(acc)))


def verify():
    pairs = {}
    for path in sorted(glob.glob(os.path.join(CARDS_DIR, '*.bin'))):
        if os.path.basename(path) in CARDS:
            continue
        try:
            h = P.parse_card(P.tobits(P.check_card(path)))
        except Exception:
            continue
        if h.get('type') == 1:
            pairs.setdefault((h['field4'], h['field6']), path)
    rows = []
    for path in pairs.values():
        lv = {}
        for name, keep in (('m', ('melody',)), ('o', ('obbligato',)),
                           ('a', ('chord', 'bass', 'rhythm'))):
            quiet = ','.join(p + '=0' for p in PARTS if p not in keep)
            lv[name], out = play(path, ['--volume', quiet], name)
            if name == 'm':
                mix = re.search(r'mix for (.*?): (\d+ \d+)', out)
        if None in lv.values() or lv['o'] < -65:
            print('%-46s skipped: a part is silent' % os.path.basename(path)[9:55])
            continue
        d = (lv['m'] - lv['o'], lv['m'] - lv['a'], lv['o'] - lv['a'])
        rows.append(d)
        print('%-46s %-42s mel-obb %+5.1f  mel-acc %+5.1f  obb-acc %+5.1f' % (
            (os.path.basename(path)[9:55], mix.group(1) if mix else '?') + d), flush=True)
    r = np.array(rows)
    print('\n%d voice pairs' % len(r))
    for i, what in enumerate(('melody - obbligato, target +3',
                              'melody - accompaniment, target +4',
                              'obbligato - accompaniment, target +1')):
        print('  %-38s mean %+5.2f  sd %4.2f  range %+5.1f to %+5.1f' % (
            what, r[:, i].mean(), r[:, i].std(), r[:, i].min(), r[:, i].max()))


if __name__ == '__main__':
    for exe in (EXE, WAV):
        if not os.path.isfile(exe):
            sys.exit('%s is not built; run make here first' % os.path.basename(exe))
    verify() if '--verify' in sys.argv else table()
