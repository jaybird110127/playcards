# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""Does every source file that describes a machine's behaviour say WHOSE?

    python check_machine_named.py
    python check_machine_named.py -v        # list every phrase it found

Four machines read these cards and they do not behave alike - see the naming
block in playcard_decode.py.  The hazard this guards against is a comment that
says how something "plays" or "sounds" without saying which machine, because a
reader then takes it for a fact about the FORMAT.  Three such readings have
already turned out to be the UPA-01's own bugs.

The rule it applies: a file whose comments describe behaviour must either name
a machine itself, import playcard_decode (which carries the naming block), or
say MACHINE-NEUTRAL outright - which a few honestly are, a Z80 interpreter and
a repeat compressor among them.

That is deliberately loose: it cannot tell a well-attributed paragraph from a
badly attributed one, and it is not meant to.  What it catches is a NEW file
that grew a behavioural comment and never joined the convention.

Run it after adding a tool, or after moving prose between files.
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKIP = ('z80.c', 'z80.h', 'ymfm')

# a comment that describes something happening, as against something being
BEHAVIOUR = re.compile(
    r'\b(plays?|playing|sounds?|sounding|silen\w+|ducks?|mutes?|voices\b|'
    r'accompaniment|drums?|fills?|audible|renders?|key.?ons?)\b', re.I)

# saying whose behaviour it is
NAMED = re.compile(r'UPA-01|PC-100|PCS-30|PC-1000|CX5M|SFG-0[15]|CR-01', re.I)

# the file that carries the naming block for everything that imports it
CANON = 'playcard_decode'

# a file with no machine in it at all can say so, once, in as many words
NEUTRAL = 'MACHINE-NEUTRAL'


def sources():
    for root, dirs, files in os.walk(HERE):
        dirs[:] = [d for d in dirs
                   if d not in ('__pycache__', 'ymfm', '.claude', 'tmp')]
        for f in sorted(files):
            if f.endswith(('.py', '.c')) and f not in SKIP:
                yield os.path.join(root, f)


def comments(text, is_c):
    """Every comment and docstring, roughly - enough to grep prose in."""
    out = []
    if is_c:
        out += re.findall(r'/\*.*?\*/', text, re.S)
        out += re.findall(r'//[^\n]*', text)
    else:
        q = chr(34) * 3
        out += re.findall(q + r'(?:.|\n)*?' + q, text)
        out += re.findall(r'#[^\n]*', text)
    return out


def main():
    verbose = '-v' in sys.argv
    bad = []
    checked = 0
    for path in sources():
        rel = os.path.relpath(path, HERE).replace('\\', '/')
        if rel == 'check_machine_named.py':
            continue
        text = io.open(path, encoding='utf-8', errors='replace').read()
        prose = '\n'.join(comments(text, path.endswith('.c')))
        hits = BEHAVIOUR.findall(prose)
        if len(hits) < 3:
            continue
        checked += 1
        if NAMED.search(prose) or NEUTRAL in prose or CANON in text:
            if verbose:
                print('%-34s ok   (%d behaviour words)' % (rel, len(hits)))
            continue
        bad.append((rel, len(hits), sorted(set(h.lower() for h in hits))[:6]))

    for rel, n, words in bad:
        print('%-34s %d behaviour words, no machine named and no %s import'
              % (rel, n, CANON))
        print('%-34s   %s' % ('', ', '.join(words)))
    print('%d source files describe behaviour; %d do not say whose'
          % (checked, len(bad)))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
