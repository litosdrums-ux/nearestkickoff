#!/usr/bin/env python3
"""Assert every venue sits inside its own country's landmass.

A wrong coordinate is the one data error users notice instantly (a pin in the sea),
so this runs after every ingest. Precision is checked separately: 'stadium' rows
should be within a few km of their city, 'city' rows are the city centre by design.
"""
import json, math, pathlib, collections, sys
WEB = pathlib.Path(__file__).resolve().parent.parent/'web'
SOV = {'England':'United Kingdom','Scotland':'United Kingdom','Wales':'United Kingdom','Türkiye':'Turkey'}

# A handful of clubs play in a league of one country but on the soil of another
# (Monaco in Ligue 1, Vaduz in the Swiss league). Checking those against their league's
# country reports them as "just offshore" forever, which is how a real error would hide
# in plain sight. ingest/verified-venues.json names the country the ground is actually in.
ENCLAVE = {}
for _v in json.load(open(WEB.parent/'ingest/verified-venues.json', encoding='utf-8'))['venues']:
    if _v.get('venue_country'):
        for _n in _v['clubs']:
            ENCLAVE[_n] = _v['venue_country']

geo = json.load(open(WEB/'europe.json', encoding='utf-8'))
byname = {f['properties']['name']: f for f in geo['features']}
venues = json.load(open(WEB/'venues.json', encoding='utf-8'))
for v in venues: v.setdefault('source', 'venues.json')

# Both venue tables need checking. web/venues.json is what the feed-based leagues join
# against; the file-based leagues carry their venue inline on every fixture instead.
# Checking only the first left every calendar-sourced ground - most of Germany, France,
# Belgium and the Netherlands - never verified at all.
# Three sources now, not two: fixtures-feeds.json carries its venues inline the same way
# fixtures-static.json does. Missing it meant the four feed leagues - Poland, Croatia,
# Hungary and Portugal 2, over 500 fixtures - were published without a single land check.
seen = {}
for name in ('fixtures-static.json', 'fixtures-feeds.json'):
    path = WEB/name
    if not path.exists():
        print(f'  ! {name} missing - its venues are NOT being checked')
        continue
    for m in json.load(open(path, encoding='utf-8')):
        seen.setdefault((m['home'], round(m['lat'], 5), round(m['lon'], 5)),
                        dict(club=m['home'], city=m.get('city') or '', country=m['country'],
                             lat=m['lat'], lon=m['lon'], precision=m['precision'],
                             source=m['league']))
venues = venues + list(seen.values())

def in_ring(pt, ring):
    x, y = pt; inside = False
    for i in range(len(ring)):
        xi, yi = ring[i]; xj, yj = ring[i-1]
        if (yi > y) != (yj > y) and x < (xj-xi)*(y-yi)/(yj-yi)+xi: inside = not inside
    return inside

def in_feature(pt, f):
    for poly in f['geometry']['coordinates']:
        if in_ring(pt, poly[0]) and not any(in_ring(pt, h) for h in poly[1:]): return True
    return False

# Natural Earth generalises coastlines and a city-precision point is a centroid,
# so a venue a few km "offshore" is a drawing artifact, not a bad coordinate.
# Beyond this, something is genuinely wrong (wrong city, swapped lat/lon).
TOLERANCE_KM = 6.0

# Norway is the pathological case for a generalised coastline: a fjord coast with tens
# of thousands of islands, drawn at 10m resolution, puts real shoreline grounds outside
# the polygon. Every Eliteserien venue flagged here was checked against its own town and
# sits 0.3-2 km from the town centre, so the coordinates are right and the coastline is
# the approximation. Raised rather than silenced - they are still listed in the report.
TOLERANCE_BY_COUNTRY = {'Norway': 12.0}
bad, warn, nocountry = [], [], []
for v in venues:
    land = ENCLAVE.get(v['club'], v['country'])
    tol = TOLERANCE_BY_COUNTRY.get(v['country'], TOLERANCE_KM)
    f = byname.get(SOV.get(land, land))
    if not f: nocountry.append(v); continue
    if not in_feature((v['lon'], v['lat']), f):
        best = min((math.hypot((p[0]-v['lon'])*math.cos(math.radians(v['lat']))*111.32,
                               (p[1]-v['lat'])*110.57)
                    for poly in f['geometry']['coordinates'] for p in poly[0]), default=0)
        (warn if best <= tol else bad).append((v, best))

dupes = collections.Counter((round(v['lat'],4), round(v['lon'],4)) for v in venues)
stacked = {k: c for k, c in dupes.items() if c > 1}

print(f'{len(venues)} venues checked')
print(f'  on land in their own country : {len(venues)-len(bad)-len(warn)-len(nocountry)}')
if warn:
    print(f'  just offshore (<={TOLERANCE_KM:g} km, coastline simplification): {len(warn)}')
    for v, d in sorted(warn, key=lambda t: -t[1]):
        print(f"      {v['club'][:28]:30} {v['city'][:14]:16} {v['precision']:8} {v['source'][:20]:22} {d:5.2f} km")
if nocountry: print(f'  no geometry for country      : {[v["country"] for v in nocountry]}')
if stacked:   print(f'  sharing a coordinate         : {sum(stacked.values())} venues at {len(stacked)} points (expected for city precision)')
if bad:
    print(f'\n  OFF LAND ({len(bad)}):')
    for v, d in sorted(bad, key=lambda t: -t[1]):
        print(f"    {v['club'][:30]:32} {v['city'][:16]:18} {v['country'][:12]:13} {v['precision']:8} {v['source'][:20]:22} {d:7.2f} km from coast")
sys.exit(1 if bad or nocountry else 0)
