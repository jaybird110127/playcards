#!/usr/bin/env python3
"""When was each card pressed?

    python card_dates.py

The 24-bit trailer - the file's last three bytes, outside the CRC and never
read by the cartridge - is a date, stored least-significant field first:

    F <day units> <day tens> <month> <year> F      as stored
    F <year> <month> <day tens> <day units> F      nibbles reversed

Year 2 is 1982.  All 267 original cards decode to a real calendar date between
1982-05-14 and 1985-12-27, and only 9 of them fall on a Sunday - a working
calendar, which is what makes it a production date rather than anything about
the music.

It is per DATE, not per card and not per set: cards from different sets sharing
a date carry byte-identical trailers.

WHICH date is not established.  It may be when the physical card was made, or
when the data for its magnetic strip was created or compiled - nothing in the
corpus separates those, and how the card data was authored in the first place
is itself unknown.  Do not call it a pressing date.
"""
import glob, os, re, collections, datetime, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playcard_decode as P


def album(name):
    n = name[9:-4]
    m = re.match(r'(17-\d+)_', n)
    if m:
        return m.group(1)
    if n.startswith('no-'):
        return n.split('_')[1]
    if n.startswith('pc-1000-japan_'):
        return 'pc-1000-japan-' + n.split('_')[1].split('-')[0]
    if n.startswith('pc-100_'):
        return 'pc-100'
    if n.startswith('pcs-30_'):
        return 'pcs-30'
    return n


rows = []
try:
    files = P.corpus()
except P.Missing as e:
    sys.exit(str(e))

for f in files:
    d = open(f, 'rb').read()
    hx = d[-3:].hex().upper()
    nib = [int(c, 16) for c in hx]
    # stored:  F n1 n2 n3 n4 F   ->  read backwards: year, month, dayTens, dayUnits
    year, month, dt, du = nib[4], nib[3], nib[2], nib[1]
    rows.append(dict(name=os.path.basename(f)[9:-4], album=album(os.path.basename(f)),
                     hx=hx, y=year, m=month, day=dt * 10 + du))

bad = []
dates = []
for r in rows:
    try:
        dt = datetime.date(1980 + r['y'], r['m'], r['day'])
        r['date'] = dt
        dates.append(dt)
    except ValueError:
        r['date'] = None
        bad.append(r)

print('%d cards' % len(rows))
print('cards whose trailer does NOT decode to a real calendar date: %d' % len(bad))
for r in bad[:10]:
    print('   %-44s %s -> %04d-%02d-%02d' % (r['name'][:44], r['hx'], 1980 + r['y'], r['m'], r['day']))
print()
print('date range: %s to %s' % (min(dates), max(dates)))
print()
wd = collections.Counter(d.strftime('%A') for d in dates)
print('day of week over all 267 cards:')
for day in ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'):
    print('   %-10s %3d' % (day, wd.get(day, 0)))
print()
byyear = collections.Counter(d.year for d in dates)
print('by year: %s' % ', '.join('%d:%d' % (y, byyear[y]) for y in sorted(byyear)))
print()
print('%-22s %s' % ('set', 'date(s) its cards were made'))
print('-' * 62)
byalbum = collections.defaultdict(set)
for r in rows:
    if r['date']:
        byalbum[r['album']].add(r['date'])
for a in sorted(byalbum, key=lambda a: min(byalbum[a])):
    ds = sorted(byalbum[a])
    print('%-22s %s' % (a, ', '.join(d.isoformat() for d in ds)))
