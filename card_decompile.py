#!/usr/bin/env python3
"""
Decompile a Yamaha Playcard image into an editable four-channel MIDI file.

    python card_decompile.py <card.bin> [-o out.mid]
    python card_decompile.py --all              # the whole corpus

The inverse is midi_compile.py, and the pair is meant to be used as a cycle:
decompile a card, edit the .mid, compile it back.  Everything the card carries
survives that trip, which is why this writes more than midi_export.py does.

WHAT THIS IS, AND WHAT midi_export.py IS

midi_export.py renders a card to be LISTENED to: three tracks, chords voiced as
triads, the obbligato's ducking baked into velocity.  It throws away everything
that is not a note, because nothing needs it back.

This writes the same music plus the machinery: bar marks, the duck opcodes, the
phrase marks and the accompaniment mute on a fourth channel, and the header in
a text meta event.  A card decompiled here and compiled back is the same card.

    channel 1   melody
    channel 2   obbligato
    channel 3   chord chart, one block per chart entry
    channel 4   control notes

The obbligato's velocity still drops to 75 where the card ducks it, because it
makes the file pleasant to listen to - but that is DECORATION.  The duck lives
in the control notes on channel 4, and the compiler reads it from there and
ignores velocity entirely.  One source of truth.

ONE BLOCK PER CHART ENTRY

A chord that the chart states twice is written as two adjacent blocks with a
re-strike between them, not as one long chord.  The chart really does carry two
entries, and a round trip that silently merged them would give back a different
card.  Nothing in the writer merges notes for the same reason.

TWO-SIDED CARDS

Handled the way midi_export.py handles them: a side-A card is joined with its
_side-b partner and written once under the name with the suffix dropped, since
side A holds the durations and side B the pitches.  A side-B file on its own is
declined - it is already covered by its side A.
"""

import argparse, os, sys

import playcard_decode as P
import playcard_resolve as R
import midi_export as M
import playcard_midi as X


def obbligato_events(track, ops):
    """Walk the obbligato and time everything that is not a note.

    Returns (chart, controls), both [(tick, ...)] on the obbligato's own
    timeline.  Chart entries and control opcodes are timed the same way because
    they arrive the same way: the table's positions are opcode indices in this
    stream, so the only way to place either in time is to walk the stream and
    accumulate the durations it pairs with.

    Bar marks and the three control opcodes both come back from the resolver as
    ('ctl', v); the marks are 0-7 and the opcodes are 0x11, 0x13 and 0x14."""
    durs = [v & 0x7F for k, v in track if k == 'byte']
    chart, controls = [], []
    t = i = 0
    live = None
    for kind, val in ops:
        if kind == 'byte':
            if i < len(durs):
                t += durs[i]
                i += 1
        elif kind == 'ctl':
            if val < 8:
                controls.append((t, X.MARK_BASE + val))
            elif val in X.CTL_NOTE:
                controls.append((t, X.CTL_NOTE[val]))
        elif kind == 'tbl':
            n, ty = val & 0x0F, (val >> 4) & 0x0F
            if val == 0xFF:
                key = 'mute'
            elif n not in P.OPM_INDEX:
                # An entry whose ROOT is one of the chip's unused note codes -
                # 47 of them across 22 cards, always code 3.  It means "the
                # root already sounding, with this quality ORed on": that is
                # what the PCS-30's converter does (ROM 0x28BA, run with
                # z80run.py), and the corpus agrees - every change one of these
                # makes adds a SEVENTH and not one moves the root.  They are
                # not mutes, whatever the cartridge does with them: 0xFF mutes
                # sit 6 to 12 ticks after a downbeat and none of these ever
                # falls on a bar line at all.
                #
                # The UPA-01 cartridge does not implement the convention.  Its
                # handler stores the value as-is, the accompaniment cannot
                # voice root code 3, and the whole thing falls silent - which
                # new-cards/make_mute_test.py measured on the real firmware.
                # These cards were pressed in 1982-83, the cartridge is 1985.
                #
                # So the chord is written out in full here.  That is what the
                # entry means, it plays the same on either machine, and a card
                # compiled back from it no longer depends on the reader knowing
                # the convention.
                if not isinstance(live, tuple):
                    continue                 # nothing sounding: it does nothing
                key = (live[0], live[1] | ty)
            elif ty in X.CHORD_TEMPLATE:
                key = ((P.OPM_INDEX[n] + 1) % 12, ty)
            else:
                continue
            # An entry that restates what is already sounding is dropped here,
            # once, so the chart and the mute notes agree about it.  The
            # handler only writes the value to the live chord byte, so the
            # second of two equal entries does nothing - and it costs a slot in
            # a table that holds 62.  See playcard_midi.collapse_chart.
            if key == live:
                continue
            live = key
            if key == 'mute':
                controls.append((t, X.MUTE_NOTE))
                chart.append((t, None, None))
            else:
                chart.append((t, key[0], key[1]))
    return chart, controls


def chord_blocks(chart, end_tick):
    """Chart -> one sounding block per entry, each held until the next entry.

    A mute ends the block before it and sounds nothing itself.  Entries that
    restate the chord already sounding have already been dropped by
    obbligato_events, so every entry here is a real change."""
    out = []
    for j, (t, root, ty) in enumerate(chart):
        if root is None:
            continue
        stop = chart[j + 1][0] if j + 1 < len(chart) else end_tick
        if stop <= t:
            stop = t + 1
        for pitch in X.chord_pitches(root, ty):
            out.append((t, stop - t, pitch, M.VELOCITY))
    return out


def decompile(card, out=None, quiet=False):
    h = M.load(card)
    joined = False

    if h['type'] == 2:
        if not quiet:
            print('%s: side B, decompiled with its side A' % os.path.basename(card))
        return None
    if h['type'] != 1:
        if not quiet:
            print('%s: unknown block type %s, skipped' % (os.path.basename(card), h['type']))
        return None
    if not h['sections']:
        mate = M.side_b_for(card)
        if mate is None:
            if not quiet:
                print('%s: no section and no side B found, skipped' % os.path.basename(card))
            return None
        hb = M.load(mate)
        if hb['type'] != 2 or not hb['sections']:
            if not quiet:
                print('%s: side B is not a continuation, skipped' % os.path.basename(card))
            return None
        h['sections'] = hb['sections']
        joined = True

    key = h['transpose'] if h['transpose'] >= 0 else h['transpose'] + 16
    shift = M.key_shift(key)
    t1, t2, s0, s1 = R.resolve(h)

    mel, tm, _, _ = M.build_part(t1, s0, shift)
    obb, to, _, _ = M.build_part(t2, s1, shift, duck=True)
    chart, controls = obbligato_events(t2, s1)
    end = max(tm, to)
    chords = chord_blocks(chart, end)

    if out is None:
        base = os.path.splitext(card)[0]
        if joined:
            base = base.replace('_side-a', '')
        out = base + '.mid'

    parts = [
        ('melody %s' % M.voice_name(M.MELODY_VOICE, h['field4']), X.MEL_CH,
         [(t, d, p, v) for t, d, p, mk, v in mel]),
        ('obbligato %s' % M.voice_name(M.OBBLIGATO_VOICE, h['field6']), X.OBB_CH,
         [(t, d, p, v) for t, d, p, mk, v in obb]),
        ('chords', X.CHORD_CH, chords),
        ('control', X.CTL_CH,
         [(t, 1, p, M.VELOCITY) for t, p in controls]),
    ]
    X.write_midi(out, parts, h['tempo'],
                 beats=3 if h['rhythm'] == 7 else 4,
                 texts=X.header_text(h))

    if not quiet:
        nmark = sum(1 for t, p in controls if p < X.CTL_NOTE[0x14])
        nctl = sum(1 for t, p in controls if p in X.NOTE_CTL)
        nmute = sum(1 for t, p in controls if p == X.MUTE_NOTE)
        print('%-52s %3d bpm  %-10s transpose=%+d'
              % (os.path.basename(card)[:52], h['tempo'],
                 P.RHYTHM[h['rhythm']], shift))
        if joined:
            print('     joined with %s' % os.path.basename(M.side_b_for(card)))
        print('     melody   : %4d notes over %5.1f bars' % (len(mel), tm / 96.0))
        print('     obbligato: %4d notes over %5.1f bars' % (len(obb), to / 96.0))
        print('     chords   : %4d chart entries (%d sounding, %d mutes)'
              % (len(chart), len(chart) - nmute, nmute))
        print('     control  : %4d notes (%d bar marks, %d duck, %d mute)'
              % (len(controls), nmark, nctl, nmute))
        print('     -> %s' % out)
    return out


def main():
    ap = argparse.ArgumentParser(
        description='Decompile a Playcard into an editable four-channel MIDI file.')
    ap.add_argument('card', nargs='?')
    ap.add_argument('-o', '--out')
    ap.add_argument('--all', action='store_true', help='decompile the whole corpus')
    ap.add_argument('--out-dir', default=os.path.join(P.HERE, 'rmidi'),
                    help='where --all writes (default: rmidi/)')
    a = ap.parse_args()
    if a.all:
        try:
            files = P.corpus()
        except P.Missing as e:
            sys.exit(str(e))
        os.makedirs(a.out_dir, exist_ok=True)
        ok = bad = 0
        for f in files:
            base = os.path.basename(os.path.splitext(f)[0]).replace('_side-a', '')
            try:
                if decompile(f, out=os.path.join(a.out_dir, base + '.mid'), quiet=True):
                    ok += 1
                else:
                    bad += 1
            except Exception as e:
                bad += 1
                print('%s: %s' % (os.path.basename(f), e))
        print('%d cards decompiled into %s, %d skipped' % (ok, a.out_dir, bad))
    elif a.card:
        decompile(a.card, a.out)
    else:
        ap.print_help()


if __name__ == '__main__':
    P.run(main)
