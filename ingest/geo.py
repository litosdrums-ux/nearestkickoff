"""Work out which town a coordinate is in.

Club-name matching gets the town for most venues, but it fails whenever the club is not
named after its town (Meadow Lane, Adams Park, The Hawthorns). The old fallback was to
use the stadium's own name as the town, which quietly produced 1,523 fixtures and 162
public pages titled things like "Football in Meadow Lane".

An earlier attempt at nearest-town matching was dropped because matching by name token
picked suburbs and, once, a place called "Zoo". This does not match by name: it snaps to
the nearest real settlement by distance, preferring Natural Earth's curated places -
which carry an importance rank and contain no zoos - and only falling back to the dense
gazetteer when nothing notable is close enough. That ordering is what keeps Prenton Park
in Liverpool rather than in a hamlet 400 m away.
"""
import functools, json, math, pathlib

HERE = pathlib.Path(__file__).resolve().parent
WEB = HERE.parent / 'web'
DATA = HERE.parent / 'data'

NOTABLE_KM = 15.0   # a Natural Earth place this close is the town, whatever its size
GAZETTEER_KM = 25.0  # otherwise the nearest real settlement, if there is one
LAST_RESORT_KM = 40.0


def _km(a, b, c, d):
    return 6371 * math.acos(min(1, math.sin(math.radians(a)) * math.sin(math.radians(c))
                            + math.cos(math.radians(a)) * math.cos(math.radians(c))
                            * math.cos(math.radians(d - b))))


@functools.lru_cache(maxsize=1)
def _sources():
    ne = [(f['properties']['n'], f['geometry']['coordinates'][1], f['geometry']['coordinates'][0])
          for f in json.load(open(WEB / 'places.json', encoding='utf-8'))['features']]
    gaz = [(r['n'], r['lat'], r['lon'])
           for r in json.load(open(DATA / 'cities-eu.json', encoding='utf-8'))]
    return ne, gaz


def snap_city(lat, lon):
    """Nearest real town to a coordinate, or None if nothing is plausibly close."""
    ne, gaz = _sources()
    n = min(((_km(lat, lon, p[1], p[2]), p[0]) for p in ne), key=lambda t: t[0])
    if n[0] <= NOTABLE_KM:
        return n[1]
    g = min(((_km(lat, lon, p[1], p[2]), p[0]) for p in gaz), key=lambda t: t[0])
    if g[0] <= GAZETTEER_KM:
        return g[1]
    return n[1] if n[0] <= LAST_RESORT_KM else None
