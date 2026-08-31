#!/usr/bin/env python3
"""
Turn a Playcard image back into the audio a card reader would have heard.

    python card_to_swipe.py card.bin                       # card.wav at defaults
    python card_to_swipe.py card.bin -o out.wav --rate 48000 --bits 24
    python card_to_swipe.py card.bin --bitrate 2600        # a slower swipe

Played into a coil held against the tape head of a Playcard-capable keyboard,
this stands in for pulling the card through the reader.  The output is the
waveform the head itself produces: a square that flips polarity at every flux
reversal, which is what a saturated recording of a real swipe looks like.

The encoding is F2F, the same self-clocking code as a magnetic stripe - every
bit cell opens with a reversal, and a 1 has a second one in the middle.  The
image is framed the way a real card is:

    <lead-in zeros>  1  <card data>  <run-out zeros>

The lead-in gives the reader's clock something to lock onto, the single 1 is the
sync the cartridge looks for, and the run-out is the blank rest of the strip
that tells it the card has ended.

Every card is the same piece of tape at the same density, so the run-out is not
a fixed number - it is whatever the data leaves over.  By default the output
fills a strip of 3593 bit cells, the capacity measured from a genuine swipe, so
a 45-byte card ends with 3201 blank bits and a 433-byte one with only 97, and
the audio comes out the same length either way.  `--tail` overrides it and
`--strip-bits` adjusts the assumed capacity.

Because the code is self-clocking, the bit rate is a free choice - a real swipe
is done by hand and drifts about 25% from one end of a card to the other.  The
default matches the reference recording; slower is often more reliable through
a coil, and `--bitrate` will take anything the receiving keyboard tolerates.

Round-trips exactly: swipe_to_card.py recovers a byte-identical image from this
tool's output at every rate, depth and speed listed in --help.
"""

import argparse
import os
import struct
import sys
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playcard_decode as P

# The reference swipe of a genuine card measured a cell of 11 to 15 samples at
# 44100 Hz as the hand slowed, so about 2900 to 4000 bits per second.  12
# samples - 3675 bit/s - sits in the middle of that.
DEFAULT_BITRATE = 3675.0
DEFAULT_LEAD = 31            # zero bits before the sync, as a real card carries

# Every card is the same piece of tape at the same density, so what is fixed is
# the number of bit CELLS - in F2F a 1 and a 0 occupy the same cell - and the
# run-out is simply whatever the data does not use.  A small card therefore ends
# with a long blank tail and a nearly full one with almost none.
#
# The genuine Silent Night swipe decodes to 3593 cells: 31 lead-in, the sync, a
# 266-byte image, and 1433 of run-out.  The corpus corroborates that as the real
# capacity - the largest card is 433 bytes, which with its framing is 97.3% of
# 3593, and 37 of the 267 cards sit within four bytes of that ceiling with the
# distribution stopping dead there.  Yamaha filled the strip to about 97% and no
# further.
DEFAULT_STRIP_BITS = 3593
MIN_TAIL = 64                # never emit less than this, whatever the sum says


def tobits(data):
    out = []
    for byte in data:
        for i in range(7, -1, -1):
            out.append((byte >> i) & 1)
    return out


def auto_tail(card_bits, lead=DEFAULT_LEAD, strip=DEFAULT_STRIP_BITS):
    """Run-out that fills the rest of the strip, since the tape is a fixed length."""
    return max(MIN_TAIL, strip - lead - 1 - card_bits)


def frame(card_bits, lead=DEFAULT_LEAD, tail=None, strip=DEFAULT_STRIP_BITS):
    """Wrap the image the way the strip carries it."""
    card_bits = list(card_bits)
    if tail is None:
        tail = auto_tail(len(card_bits), lead, strip)
    return [0] * lead + [1] + card_bits + [0] * tail


def f2f_transitions(bits, cell):
    """Bit stream -> flux reversal times in seconds.

    Every cell starts with a reversal; a 1 adds one at the half cell."""
    out = []
    t = 0.0
    for b in bits:
        out.append(t)
        if b:
            out.append(t + cell / 2.0)
        t += cell
    return out, t


def render(transitions, total, rate, amplitude, invert):
    """Reversal times -> a square wave that flips at each one."""
    n = int(round(total * rate)) + 1
    buf = [0.0] * n
    level = -amplitude if invert else amplitude
    idx = 0
    for t in transitions:
        end = min(n, int(round(t * rate)))
        while idx < end:
            buf[idx] = level
            idx += 1
        level = -level
    while idx < n:
        buf[idx] = level
        idx += 1
    return buf


def write_wav(path, buf, rate, bits):
    if bits == 8:
        sw = 1
        data = bytes(max(0, min(255, int(round(v * 127)) + 128)) for v in buf)
    elif bits == 16:
        sw = 2
        data = struct.pack('<%dh' % len(buf),
                           *(max(-32768, min(32767, int(round(v * 32767)))) for v in buf))
    elif bits in (24, 32):
        sw = 4
        lim = 2147483647
        data = struct.pack('<%di' % len(buf),
                           *(max(-lim, min(lim, int(round(v * lim)))) for v in buf))
    else:
        raise ValueError('bit depth must be 8, 16, 24 or 32')
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(sw)
        w.setframerate(rate)
        w.writeframes(data)
    return sw


def main():
    ap = argparse.ArgumentParser(
        description='Render a Playcard image as the audio of a swipe.')
    ap.add_argument('card')
    ap.add_argument('-o', '--out', help='output .wav (default: the card name)')
    ap.add_argument('--rate', type=int, default=44100, help='sample rate (default 44100)')
    ap.add_argument('--bits', type=int, default=16, choices=(8, 16, 24, 32),
                    help='bit depth (default 16)')
    ap.add_argument('--bitrate', type=float, default=DEFAULT_BITRATE,
                    help='bits per second, i.e. how fast the card is "swiped" '
                         '(default %g)' % DEFAULT_BITRATE)
    ap.add_argument('--speed', type=float, default=1.0,
                    help='multiplier on --bitrate, so --speed 0.5 is half as fast')
    ap.add_argument('--lead', type=int, default=DEFAULT_LEAD,
                    help='zero bits before the sync (default %d, as on a real card)' % DEFAULT_LEAD)
    ap.add_argument('--tail', type=int, default=None,
                    help='zero bits of blank strip after the data (default: fill the strip, '
                         'so a small card gets a long run-out and a full one almost none)')
    ap.add_argument('--strip-bits', type=int, default=DEFAULT_STRIP_BITS, dest='strip',
                    help='bit cells a physical strip holds, used to size the run-out '
                         '(default %d, measured from a genuine swipe)' % DEFAULT_STRIP_BITS)
    ap.add_argument('--amplitude', type=float, default=0.8,
                    help='output level, 0 to 1 (default 0.8)')
    ap.add_argument('--invert', action='store_true', help='flip the starting polarity')
    a = ap.parse_args()

    data = P.check_card(a.card)
    out = a.out or os.path.splitext(a.card)[0] + '.wav'

    bitrate = a.bitrate * a.speed
    if bitrate <= 0:
        sys.exit('bit rate must be positive')
    cell = 1.0 / bitrate
    if cell * a.rate < 4:
        sys.exit(P.wrapped(
            '%.0f bits/s needs a cell of %.1f samples at %d Hz - too few to '
            'render cleanly; raise --rate or lower --bitrate'
            % (bitrate, cell * a.rate, a.rate)))

    card_bits = tobits(data)
    tail = a.tail if a.tail is not None else auto_tail(len(card_bits), a.lead, a.strip)
    used = a.lead + 1 + len(card_bits)
    if a.tail is None and a.strip - used < MIN_TAIL:
        P.say('note: this card needs %d of the %d cells on a strip, so the '
              'run-out is the %d-bit minimum rather than a fill'
              % (used, a.strip, MIN_TAIL))
    bits = frame(card_bits, a.lead, tail, a.strip)
    tr, total = f2f_transitions(bits, cell)
    buf = render(tr, total, a.rate, a.amplitude, a.invert)
    sw = write_wav(out, buf, a.rate, a.bits)

    print('%s -> %s' % (os.path.basename(a.card), os.path.basename(out)))
    try:
        h = P.parse_card(P.tobits(data))
        print('  card       %d bytes, CRC %s'
              % (len(data), 'VALID' if h['crc_ok'] else 'FAILED - rendering it anyway'))
        if h['type'] == 1:
            print('  %d bpm %s, melody %s, obbligato %s'
                  % (h['tempo'], P.RHYTHM[h['rhythm']],
                     P.voice(P.MELODY_VOICE, h['field4']),
                     P.voice(P.OBBLIGATO_VOICE, h['field6'])))
    except P.Over:
        print('  card       %d bytes, does not parse - rendering it anyway' % len(data))
    how = 'filling the strip' if a.tail is None else 'run-out set by hand'
    print('  framing    %d lead-in + 1 sync + %d card + %d run-out = %d bits (%s)'
          % (a.lead, len(data) * 8, tail, len(bits), how))
    print('  strip      %d of %d cells used, %.1f%% full'
          % (used, a.strip, 100.0 * used / a.strip))
    print('  encoding   F2F, %.0f bits/s, cell %.2f samples, %d flux reversals'
          % (bitrate, cell * a.rate, len(tr)))
    print('  audio      %.3f s, %d Hz, %d-bit mono, %d samples, peak %.0f%%'
          % (total, a.rate, a.bits, len(buf), a.amplitude * 100))
    print('  -> %s (%d bytes)' % (out, os.path.getsize(out)))


if __name__ == '__main__':
    P.run(main)
