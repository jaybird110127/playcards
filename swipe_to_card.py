#!/usr/bin/env python3
"""
Recover a Playcard image from a recording of the card being swiped.

    python swipe_to_card.py "Silent Night.wav"            # decode and report
    python swipe_to_card.py swipe.wav -o card.bin         # save it
    python swipe_to_card.py swipe.wav -o card.bin --force # save even if the CRC fails

The strip is written in F2F, the same self-clocking code as a credit card
magnetic stripe: every bit cell begins with a flux reversal, and a 1 has a
second reversal in the middle of the cell.  A tape head produces dFlux/dt, so
each reversal shows up as a peak and all the decoder has to measure is the time
between them - a long gap is a 0, a pair of short gaps is a 1.

That makes the code self-clocking, which matters because a swipe is done by
hand: in the reference recording the cell period drifts from 11 samples to 15
between one end of the card and the other, about 25%.  The decoder tracks the
period as it goes rather than assuming a fixed bit rate, so it does not care how
fast or how evenly the card was pulled through.

The card is framed on the strip as:

    <many 0 bits>  1  <card data>  <many 0 bits>

The leading zeros are the run-up that lets the reader lock onto the clock, and
the single 1 is the marker the cartridge syncs on - it is also what seeds the
CRC to 0x8005, since 31 zeros and a one leave the register in exactly that
state.  The trailing zeros are the blank rest of the strip; the cartridge needs
them to know the card has ended.

The recording's own baseline is measured and subtracted before any of that.
A tape head's output can sit well away from zero for a while - a thump as the
card is pushed in will do it - and a Schmitt trigger measuring against zero then
stays latched and drops every reversal underneath, which loses a stretch of the
card with no symptom except that nothing parses.  See `flux()`.

By default nothing is written unless the recovered image passes its CRC, so a
bad swipe cannot quietly become a bad .bin.
"""

import argparse
import os
import struct
import sys
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playcard_decode as P


# ---------------------------------------------------------------- the signal

def read_wav(path):
    """-> (samples as a list of ints, sample rate).  Mono; a stereo file is mixed."""
    P.check_wav(path)                    # say what it is before wave.open trips
    with wave.open(path, 'rb') as w:
        ch, sw, rate, n = (w.getnchannels(), w.getsampwidth(),
                           w.getframerate(), w.getnframes())
        raw = w.readframes(n)
    if sw == 1:
        vals = [(b - 128) << 8 for b in raw]
    elif sw == 2:
        vals = list(struct.unpack('<%dh' % (len(raw) // 2), raw))
    elif sw == 4:
        vals = [v >> 16 for v in struct.unpack('<%di' % (len(raw) // 4), raw)]
    else:
        raise ValueError('unsupported sample width: %d bytes' % sw)
    if ch > 1:
        vals = [sum(vals[i:i + ch]) // ch for i in range(0, len(vals) - ch + 1, ch)]
    return vals, rate


def level(x, w):
    """The signal's own baseline: a moving average over `w` samples."""
    n = len(x)
    if w < 3 or n == 0:
        return [0.0] * n
    half = w // 2
    out = [0.0] * n
    run = float(sum(x[:min(w, n)]))
    cnt = min(w, n)
    for i in range(n):
        lo, hi = i - half, i + half
        if lo > 0:
            run -= x[lo - 1]
            cnt -= 1
        if hi < n:
            run += x[hi]
            cnt += 1
        out[i] = run / cnt
    return out


def transitions(x, frac=0.2):
    """Sample indices of the flux reversals.

    Uses a Schmitt trigger at +/- a fraction of the signal's own peak, so it
    works whether the recording is clean or driven into clipping (the reference
    swipe is fully saturated), and ignores the small wander around zero between
    reversals."""
    peak = max(abs(v) for v in x) if x else 0
    if not peak:
        return []
    hi, lo = peak * frac, -peak * frac
    st = None
    out = []
    for i, v in enumerate(x):
        if st != 1 and v > hi:
            st = 1
            out.append(i)
        elif st != -1 and v < lo:
            st = -1
            out.append(i)
    return out


def flux(x, rate):
    """Flux reversals, with the recording's baseline taken out first.

    A Schmitt trigger measures the signal against zero, and a recording whose
    baseline WANDERS breaks that assumption without looking broken.  The card
    that prompted this carries a mechanical thump as the swipe begins: for its
    first 2250 samples the whole waveform rides about +15000 above zero, so it
    never reaches the negative threshold, the trigger stays latched, and 225 bit
    cells - 28 bytes of card, header included - vanish without a single warning.
    The envelope looks healthy, the gaps that ARE found look clean, and the only
    symptom is that nothing parses.

    So the baseline is measured and subtracted before triggering.  The window
    has to span several bit cells, or it follows the data and cancels it; four
    cells is comfortably clear of the fastest thing in the signal (a half cell)
    and still short enough to track a thump.  The cell is not known until the
    reversals have been found, so this makes a first pass at the raw signal to
    estimate it, then a second at the levelled one.  On a clean recording the
    two passes agree and the levelling changes nothing.
    """
    first = transitions(x)
    if len(first) < 32:
        return first
    gaps = sorted(first[i + 1] - first[i] for i in range(len(first) - 1))
    cell = gaps[len(gaps) * 3 // 4]
    w = int(4 * cell) | 1                      # odd, so the window is centred
    base = level(x, w)
    second = transitions([v - b for v, b in zip(x, base)])
    return second if len(second) >= len(first) else first


def decode_f2f(tr):
    """Flux reversals -> bits, tracking the cell period as it drifts.

    A gap longer than about three quarters of the current cell is a whole cell
    and therefore a 0; anything shorter is the first half of a 1 and its partner
    is consumed with it."""
    gaps = [tr[i + 1] - tr[i] for i in range(len(tr) - 1)]
    if len(gaps) < 16:
        return [], 0.0
    ordered = sorted(gaps)
    cell = float(ordered[len(ordered) * 3 // 4])      # a long gap, robustly

    # skip any run-up junk: start at the first gap that begins eight plausible ones
    start = 0
    for i in range(len(gaps) - 8):
        w = gaps[i:i + 8]
        if all(0.35 * cell < g < 1.4 * cell for g in w):
            start = i
            break

    bits = []
    i = start
    while i < len(gaps):
        g = gaps[i]
        if g > 2.0 * cell:            # a dropout: the head lost the strip
            i += 1
            continue
        if g > 0.72 * cell:
            bits.append(0)
            cell = 0.85 * cell + 0.15 * g
            i += 1
        else:
            if i + 1 >= len(gaps):
                break
            g2 = gaps[i + 1]
            if g2 > 0.72 * cell:      # an unpaired half cell - the swipe glitched
                i += 1
                continue
            bits.append(1)
            cell = 0.85 * cell + 0.15 * (g + g2)
            i += 2
    return bits, cell


def find_card(bits, lead=16):
    """Index of the first card bit: just past the sync 1 that ends the run-up.

    The sync is the first 1 preceded by a long run of 0s, which is what
    distinguishes it from a 1 inside the data."""
    zeros = 0
    for i, b in enumerate(bits):
        if b == 0:
            zeros += 1
        else:
            if zeros >= lead:
                return i + 1
            zeros = 0
    return None


def pack(bits):
    out = bytearray()
    for i in range(0, len(bits) - 7, 8):
        v = 0
        for b in bits[i:i + 8]:
            v = (v << 1) | b
        out.append(v)
    return bytes(out)


def recover(path, verbose=True):
    """-> (image bytes, parsed header or None, diagnostics dict)"""
    x, rate = read_wav(path)
    tr = flux(x, rate)
    bits, cell = decode_f2f(tr)
    diag = dict(rate=rate, samples=len(x), seconds=len(x) / float(rate),
                reversals=len(tr), bits=len(bits), cell=cell,
                bitrate=rate / cell if cell else 0)

    best = None
    for direction, bb in (('forward', bits), ('reversed', bits[::-1])):
        s = find_card(bb)
        if s is None:
            continue
        tail = bb[s:]
        # The card ends at its last 1 bit.  The trailer's final nibble is always
        # F, so that bit is the last bit of the image - which is a sounder way
        # to find the end than measuring from the CRC, because the zero padding
        # between the CRC and the trailer is not always minimal: some cards
        # carry a whole extra zero byte there.
        last = max((i for i, b in enumerate(tail) if b), default=-1)
        if last < 0:
            continue
        nbytes = (last + 8) // 8
        for nb in (nbytes, nbytes + 1):
            data = pack(tail[:nb * 8])
            if len(data) < nb:
                continue
            try:
                h = P.parse_card(P.tobits(data))
            except P.Over:
                continue
            if h['crc_ok']:
                return data, h, dict(diag, direction=direction, leading_zeros=s - 1)
            if best is None:
                best = (data, h, dict(diag, direction=direction, leading_zeros=s - 1))
    if best:
        return best
    s = find_card(bits) or 0
    return pack(bits[s:]), None, dict(diag, direction='forward', leading_zeros=max(s - 1, 0))


# ---------------------------------------------------------------- reporting

def describe(img, h):
    print('  bytes      %d' % len(img))
    print('  block type %d' % h['type'])
    print('  CRC-16     %s' % ('VALID' if h['crc_ok'] else 'FAILED'))
    if h['type'] != 1:
        return
    raw = h['transpose'] if h['transpose'] >= 0 else h['transpose'] + 16
    print('  tempo      %d bpm' % h['tempo'])
    print('  rhythm     %s' % P.RHYTHM[h['rhythm']])
    print('  key        field %d -> transpose %+d semitones (a card in C'
          ' sounds in %s)' % (raw, P.key_shift(raw), P.key_name(raw)))
    print('  melody     %s' % P.voice(P.MELODY_VOICE, h['field4']))
    print('  obbligato  %s' % P.voice(P.OBBLIGATO_VOICE, h['field6']))
    print('  accomp     %s pattern' % ('ALTERNATE (locked)' if h['f3'] else 'standard'))
    print('  sustain    %s' % ('ON' if h['bit1'] else 'off'))
    total = sum(v & 0x7F for v in h['track1'] if v < 0xE1)
    print('  length     %d melody events, %.1f bars of 4/4' % (len(h['track1']), total / 96.0))
    if h['sections']:
        table = h['sections'][0][0]
        chords = ' '.join(P.chord(v) for v, p in table[:14])
        print('  chords     %s%s' % (chords, ' ...' if len(table) > 14 else ''))
    if len(img) >= 3:
        hx = img[-3:].hex().upper()
        nb = [int(c, 16) for c in hx]
        if hx[0] == 'F' and hx[5] == 'F':
            try:
                import datetime
                d = datetime.date(1980 + nb[4], nb[3], nb[2] * 10 + nb[1])
                print('  date       %s (%s)   trailer %s' % (d.isoformat(), d.strftime('%A'), hx))
            except ValueError:
                print('  date       trailer %s does not decode to a real date' % hx)


def main():
    ap = argparse.ArgumentParser(
        description='Recover a Playcard image from a recording of a swipe.')
    ap.add_argument('wav')
    ap.add_argument('-o', '--out', help='write the image here')
    ap.add_argument('--force', action='store_true',
                    help='write even if the CRC fails (the swipe was bad)')
    a = ap.parse_args()

    img, h, d = recover(a.wav)
    print('%s' % os.path.basename(a.wav))
    print('  %.3f s at %d Hz, %d flux reversals, read %s'
          % (d['seconds'], d['rate'], d['reversals'], d['direction']))
    print('  cell %.1f samples -> %.0f bits/s, %d bits, %d bits of run-up'
          % (d['cell'], d['bitrate'], d['bits'], d['leading_zeros']))
    print()
    if h is None:
        print('  could not parse the recovered data at all - the swipe is unusable')
        if not a.force:
            return 1
    else:
        describe(img, h)

    if a.out:
        if h is not None and h['crc_ok']:
            open(a.out, 'wb').write(img)
            print('\n  -> %s' % a.out)
        elif a.force:
            open(a.out, 'wb').write(img)
            print('\n  -> %s  (WRITTEN ANYWAY, --force: this image is not trustworthy)' % a.out)
        else:
            print('\n  not written: the CRC does not check out, so this swipe did not read')
            print('  cleanly.  Swipe again, or pass --force to keep it regardless.')
            return 1
    return 0


if __name__ == '__main__':
    P.run(main)
