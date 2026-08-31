#!/usr/bin/env python3
"""
Convert a Yamaha Playcard to a MIDI file, by capturing what the real
cartridge firmware actually plays.

    python card_to_midi.py <card.bin> [-o out.mid] [options]

Rather than re-implementing the rhythm and accompaniment patterns, this runs
the genuine UPA-01 cartridge under openMSX, feeds it the card through a stand-in
for the CR-01 reader, and records every write to the SFG's YM2151.  Melody,
obbligato, chords, bass and drums all come out, because all of them are played
by that chip.

The YM2151 sits behind two addresses in the SFG's page: 0x3FF0 latches a
register number and 0x3FF1 supplies the data.  The registers that matter:

    0x08        key on/off - low 3 bits pick the channel, bits 3..6 the slots
    0x28+ch     KC, the key code: octave in bits 4..6, note in bits 0..3
    0x30+ch     KF, the fine tuning fraction (used only to detect pitch bends)

Note codes run C# D D# . E F F# . G G# A . A# B C, so the four codes 3, 7, 11
and 15 are unused - which is exactly what the cards emit for a "no note" event.

Each YM2151 channel becomes its own MIDI track, so the parts can be soloed.
Because this captures the performance rather than the score, the piccolo
melody's octave shift and any firmware quirks are already baked in.

Options:
    -o, --out P     output .mid              (default: card name with .mid)
    --seconds N     how long to record       (default 90)
    --press-play    press F2 after loading (cards that do not self-start)
    --trailer N     zero bits fed after the card data (default 4000)
    --machine M     MSX machine              (default yamaha_cx5m)
    --openmsx P     path to openmsx.exe
    --cart P        path to the UPA-01 ROM
    --drums         route single-pitch percussion channels to MIDI channel 10
    --keep-log      keep the raw register capture next to the .mid
"""

import argparse, os, shutil, struct, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import playcard_decode as P

def find_openmsx():
    """openmsx on PATH, or OPENMSX_PATH, or a few usual places.

    There is no default install path worth hard-coding, and there used to be
    one here that only existed on the machine this was written on.  --openmsx
    overrides whatever this finds."""
    env = os.environ.get('OPENMSX_PATH')
    if env and os.path.isfile(env):
        return env
    for name in ('openmsx.exe', 'openmsx'):
        found = shutil.which(name)
        if found:
            return found
    for guess in (r'C:/Program Files/openMSX/openmsx.exe',
                  r'C:/Program Files (x86)/openMSX/openmsx.exe',
                  '/usr/bin/openmsx', '/usr/local/bin/openmsx',
                  '/Applications/openMSX.app/Contents/MacOS/openmsx'):
        if os.path.isfile(guess):
            return guess
    return 'openmsx.exe'          # so the error message names something


DEF_OPENMSX = find_openmsx()
# The cartridge ROM is Yamaha's and is not in this repository; it lives in
# Roms/, or wherever PLAYCARD_ROMS points.  Resolved at run time so that
# --help works without it.
DEF_CART = os.path.join(P.ROM_DIR, P.CART_ROM)

# YM2151 note field -> semitone within the block.  The block runs C# .. C.
OPM_ORDER = {0: 0, 1: 1, 2: 2, 4: 3, 5: 4, 6: 5, 8: 6, 9: 7, 10: 8, 12: 9, 13: 10, 14: 11}

TCL = r'''
set ::card    {%(card)s}
set ::logfile {%(log)s}
set ::trailer  %(trailer)s
set ::pressplay %(pressplay)s
set ::runfor   %(seconds)s

set ::log [open $::logfile w]
proc emit {m} { puts $::log $m }

set fh [open $::card rb]
fconfigure $fh -translation binary
set ::carddata [read $fh]
close $fh
binary scan $::carddata B* ::bits
set ::nbits [string length $::bits]
set ::total [expr {$::nbits + $::trailer}]
set ::bitpos 0

proc cr01_poll {} { if {$::bitpos < $::total} { reg A 0x80 } else { reg A 0x00 }; reg PC 0x6895 }
proc cr01_bit {} {
    if {$::bitpos >= $::total} { reg A 0x00 } else {
        if {$::bitpos < $::nbits} { set b [string index $::bits $::bitpos] } else { set b "0" }
        incr ::bitpos
        reg A [expr {0xC0 | ($b eq "1" ? 0x20 : 0x00)}]
    }
    reg PC 0x68B5
}
proc press {r m} { keymatrixdown $r $m; after time 1 [list keymatrixup $r $m] }

# --- capture YM2151 traffic -------------------------------------------------
set ::opmreg -1
proc fmw {} {
    set a $::wp_last_address
    set v $::wp_last_value
    if {($a & 0x0FFF) == 0x0FF0} {
        set ::opmreg $v
    } elseif {($a & 0x0FFF) == 0x0FF1} {
        set r $::opmreg
        # key on/off, key code, key fraction
        if {$r == 8 || ($r >= 0x28 && $r <= 0x2F) || ($r >= 0x30 && $r <= 0x37)} {
            emit [format "%%.5f %%02X %%02X" [machine_info time] $r $v]
        }
    }
}

proc go {} {
    debug set_bp 0x6892 {} {cr01_poll}
    debug set_bp 0x68B2 {} {cr01_bit}
    press 6 0x20
    after time 6 armed
}
proc armed {} {
    emit "# card bits: $::bitpos of $::total"
    foreach spec {{0x3FF0 0x3FF1} {0x7FF0 0x7FF1} {0xBFF0 0xBFF1} {0xFFF0 0xFFF1}} {
        catch {debug watchpoint create -type write_mem -address $spec -command {fmw}}
    }
    emit "# START [machine_info time]"
    if {$::pressplay} { press 6 0x40 }
    after time $::runfor finish
}
proc finish {} {
    emit "# END [machine_info time]"
    close $::log
    exit
}
after time 6 go
'''


# ------------------------------------------------------------------ MIDI out

def varlen(n):
    out = bytearray([n & 0x7F])
    n >>= 7
    while n:
        out.insert(0, (n & 0x7F) | 0x80)
        n >>= 7
    return bytes(out)


def write_midi(path, tracks, ticks_per_beat=480, us_per_beat=500000):
    """tracks: list of lists of (abs_tick, status, d1, d2)."""
    chunks = []
    head = struct.pack('>4sIHHH', b'MThd', 6, 1, len(tracks) + 1, ticks_per_beat)

    tempo = bytearray()
    tempo += varlen(0) + b'\xFF\x51\x03' + us_per_beat.to_bytes(3, 'big')
    tempo += varlen(0) + b'\xFF\x2F\x00'
    chunks.append(struct.pack('>4sI', b'MTrk', len(tempo)) + bytes(tempo))

    for ev in tracks:
        body = bytearray()
        last = 0
        for tick, status, d1, d2 in sorted(ev, key=lambda e: e[0]):
            body += varlen(max(0, tick - last))
            body += bytes([status, d1, d2]) if d2 is not None else bytes([status, d1])
            last = tick
        body += varlen(0) + b'\xFF\x2F\x00'
        chunks.append(struct.pack('>4sI', b'MTrk', len(body)) + bytes(body))

    with open(path, 'wb') as f:
        f.write(head)
        for c in chunks:
            f.write(c)


def parse_capture(path, base_octave_offset=0):
    """Turn the register log into per-channel note events."""
    kc = [0] * 8
    on = [None] * 8            # start time of the currently sounding note
    notes = [[] for _ in range(8)]   # (start, end, midinote)
    t0 = None
    for line in open(path):
        if line.startswith('#'):
            continue
        parts = line.split()
        if len(parts) != 3:
            continue
        t = float(parts[0])
        r = int(parts[1], 16)
        v = int(parts[2], 16)
        if t0 is None:
            t0 = t
        t -= t0
        if 0x28 <= r <= 0x2F:
            kc[r - 0x28] = v
        elif r == 0x08:
            ch = v & 7
            slots = (v >> 3) & 0x0F
            if slots:
                if on[ch] is not None:
                    notes[ch].append((on[ch][0], t, on[ch][1]))
                octave = (kc[ch] >> 4) & 7
                note = kc[ch] & 0x0F
                if note in OPM_ORDER:
                    midi = 12 * (octave + 1 + base_octave_offset) + OPM_ORDER[note] + 1
                    if 0 <= midi <= 127:
                        on[ch] = (t, midi)
                    else:
                        on[ch] = None
                else:
                    on[ch] = None      # 3, 7, 11, 15 - the "no note" codes
            else:
                if on[ch] is not None:
                    notes[ch].append((on[ch][0], t, on[ch][1]))
                    on[ch] = None
    end = max((n[1] for chn in notes for n in chn), default=0)
    for ch in range(8):
        if on[ch] is not None:
            notes[ch].append((on[ch][0], end, on[ch][1]))
    return notes


def main():
    ap = argparse.ArgumentParser(description='Convert a Playcard to MIDI via the real firmware.')
    ap.add_argument('card')
    ap.add_argument('-o', '--out', default=None)
    ap.add_argument('--seconds', type=int, default=90)
    ap.add_argument('--press-play', action='store_true', dest='pressplay')
    ap.add_argument('--trailer', type=int, default=4000)
    ap.add_argument('--machine', default='yamaha_cx5m')
    ap.add_argument('--openmsx', default=DEF_OPENMSX)
    ap.add_argument('--cart', default=DEF_CART)
    ap.add_argument('--drums', action='store_true',
                    help='route single-pitch percussion channels to MIDI channel 10')
    ap.add_argument('--keep-log', action='store_true', dest='keeplog')
    a = ap.parse_args()

    card = os.path.abspath(a.card)
    P.check_card(card)          # before openMSX is started for nothing
    if not os.path.isfile(a.openmsx):
        sys.exit('openmsx.exe not found at %s (use --openmsx)' % a.openmsx)
    if not os.path.isfile(a.cart):
        sys.exit('UPA-01 cartridge ROM not found at %s (use --cart)' % a.cart)
    out = a.out or os.path.splitext(card)[0] + '.mid'

    tmp = tempfile.mkdtemp(prefix='cardmidi_')
    log = os.path.join(tmp, 'fm.log')
    tcl = os.path.join(tmp, 'cap.tcl')
    with open(tcl, 'w') as f:
        f.write(TCL % {'card': card.replace(os.sep, '/'),
                       'log': log.replace(os.sep, '/'),
                       'trailer': a.trailer,
                       'pressplay': 1 if a.pressplay else 0,
                       'seconds': a.seconds})

    print('card    : %s' % os.path.basename(card))
    print('capture : %d emulated seconds%s' % (a.seconds,
          ' (pressing F2)' if a.pressplay else ' (card should self-start)'))
    print('running openMSX...')
    t0 = time.time()
    proc = subprocess.Popen([a.openmsx, '-machine', a.machine, '-cart', a.cart,
                             '-script', tcl],
                            cwd=os.path.dirname(a.openmsx) or None,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    proc.wait()
    print('capture finished in %.0fs wall clock' % (time.time() - t0))

    if not os.path.exists(log):
        sys.exit('no capture produced - openMSX may have failed to start')
    notes = parse_capture(log)
    total = sum(len(n) for n in notes)
    if not total:
        print('no notes captured.')
        print('if the card needs starting by hand, re-run with --press-play')
        sys.exit(1)

    # A channel that only ever sounds one pitch, many times over, is a drum
    # voice rather than a melodic one.
    perc = [ch for ch in range(8)
            if notes[ch] and len({n[2] for n in notes[ch]}) == 1 and len(notes[ch]) >= 20]

    tracks = []
    used = 0
    for ch in range(8):
        if not notes[ch]:
            continue
        used += 1
        mch = 9 if (a.drums and ch in perc) else (ch if ch < 9 else ch + 1)
        ev = []
        for start, end, midi in notes[ch]:
            ev.append((int(start * 960), 0x90 | mch, midi, 100))
            ev.append((int(max(end, start + 0.02) * 960), 0x80 | mch, midi, 0))
        tracks.append(ev)

    write_midi(out, tracks)
    print('%d notes on %d channels -> %s' % (total, used, out))
    for ch in range(8):
        if notes[ch]:
            lo = min(n[2] for n in notes[ch])
            hi = max(n[2] for n in notes[ch])
            tag = '  <- percussion' if ch in perc else ''
            print('   ch%d: %4d notes, MIDI %d..%d%s' % (ch, len(notes[ch]), lo, hi, tag))
    if perc and not a.drums:
        print('   (pass --drums to route those to MIDI channel 10)')

    if a.keeplog:
        import shutil
        dest = os.path.splitext(out)[0] + '.fmlog'
        shutil.copyfile(log, dest)
        print('register capture kept: %s' % dest)
    else:
        try:
            os.remove(log)
        except OSError:
            pass
    try:
        os.remove(tcl)
        os.rmdir(tmp)
    except OSError:
        pass


if __name__ == '__main__':
    P.run(main)
