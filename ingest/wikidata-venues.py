#!/usr/bin/env python3
"""Pull club -> home venue coordinates from Wikidata (CC0) into data/wikidata-venues.json.

Wikidata is CC0, so unlike OpenStreetMap's ODbL there is no share-alike obligation
on a database built from it. That is why this is the first venue source to try.

    python3 ingest/wikidata-venues.py            # fetch all configured countries
    python3 ingest/wikidata-venues.py --check    # fetch, then report coverage vs our clubs

Blocked in the Claude sandbox (query.wikidata.org is not on the egress allowlist),
so this is written to run on your machine. Nothing here needs an API key.
"""
import json, sys, time, urllib.parse, urllib.request, re, unicodedata, pathlib, collections

HERE = pathlib.Path(__file__).resolve().parent
DATA, WEB = HERE.parent/'data', HERE.parent/'web'
ENDPOINT = 'https://query.wikidata.org/sparql'
# Wikidata blocks requests without a descriptive agent. Put a real contact in here.
UA = 'NearestKickoff/1.0 (https://nearestkickoff.com; contact@nearestkickoff.com)'

# Every country UEFA plays in, by ISO 3166-1 alpha-2 code.
#
# QIDs are deliberately NOT hardcoded. A wrong QID does not error - it silently returns
# another country's clubs, and you find out when a pin lands in the wrong nation. So the
# script asks Wikidata for the QID behind each ISO code (property P297) and uses what it
# is told. ISO codes are stable and easy to check by eye; QIDs are neither.
#
# England, Scotland, Wales and Northern Ireland are all GB: Wikidata files their clubs
# under the United Kingdom, not under the home nations.
ISO = [
    'AL','AD','AM','AT','AZ','BY','BE','BA','BG','HR','CY','CZ','DK','EE','FO','FI',
    'FR','GE','DE','GI','GR','HU','IS','IE','IL','IT','KZ','LV','LI','LT','LU','MT',
    'MD','MC','ME','NL','MK','NO','PL','PT','RO','RS','SK','SI','ES','SE','CH','TR',
    'UA','GB','SM','RU',
]
# Label language per country, so a club's local name is collected alongside its English
# one. Anything not listed falls back to English, which is never wrong, only thinner.
ISO_LANG = {
    'AT':'de','BE':'nl','BG':'bg','CH':'de','CZ':'cs','DE':'de','DK':'da','EE':'et',
    'ES':'es','FI':'fi','FR':'fr','GR':'el','HR':'hr','HU':'hu','IS':'is','IT':'it',
    'LT':'lt','LV':'lv','MD':'ro','MK':'mk','NL':'nl','NO':'no','PL':'pl','PT':'pt',
    'RO':'ro','RS':'sr','RU':'ru','SE':'sv','SI':'sl','SK':'sk','TR':'tr','UA':'uk',
    'AL':'sq','BA':'bs','ME':'sr','CY':'el','IL':'he','GE':'ka','AM':'hy','AZ':'az',
    'BY':'be','KZ':'kk','FO':'fo','MT':'mt','LU':'fr','MC':'fr','LI':'de','SM':'it',
}

# Resolve ISO alpha-2 (P297) to the country item, rather than trusting a written-down QID.
QID_QUERY = """
SELECT ?iso ?country WHERE {
  VALUES ?iso { %s }
  ?country wdt:P297 ?iso .
}
"""

# P31 instance of - P279 subclass of - P17 country - P115 home venue - P625 coordinates
# Q476028 association football club
QUERY = """
SELECT ?club ?clubLabel ?clubAlt ?venue ?venueLabel ?coord WHERE {
  ?club wdt:P31/wdt:P279* wd:Q476028 ;
        wdt:P17 wd:%(country)s ;
        wdt:P115 ?venue .
  ?venue wdt:P625 ?coord .
  OPTIONAL { ?club skos:altLabel ?clubAlt FILTER(LANG(?clubAlt) IN ("en","%(lang)s")) }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,%(lang)s". }
}
"""

def sparql(query):
    url = ENDPOINT + '?' + urllib.parse.urlencode({'query': query, 'format': 'json'})
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/sparql-results+json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)['results']['bindings']

def point(wkt):                      # 'Point(11.2824 43.7809)' -> (lat, lon)
    m = re.match(r'Point\(([-\d.]+) ([-\d.]+)\)', wkt)
    return (float(m.group(2)), float(m.group(1))) if m else None

def resolve_qids(isos):
    """Ask Wikidata which item each ISO code belongs to, instead of trusting a list of
    QIDs written down by hand. A mistyped QID returns another country's clubs silently."""
    values = ' '.join(f'"{c}"' for c in isos)
    out = {}
    for b in sparql(QID_QUERY % values):
        out[b['iso']['value']] = b['country']['value'].rsplit('/', 1)[-1]
    missing = [c for c in isos if c not in out]
    if missing:
        print(f'  no Wikidata item for ISO {missing} - skipping those')
    return out


def main():
    isos = ISO if '--all' in sys.argv else sorted(set(ISO))
    print(f'resolving {len(isos)} ISO codes to Wikidata items ...', flush=True)
    try:
        qids = resolve_qids(isos)
    except Exception as e:
        print(f'could not reach query.wikidata.org: {e}')
        print('Nothing was changed. This script needs unrestricted internet access - '
              'run it from the "Refresh venue data from Wikidata" GitHub Action.')
        return 1

    prev = []
    if (DATA/'wikidata-venues.json').exists():
        prev = json.load(open(DATA/'wikidata-venues.json', encoding='utf-8'))
    before = collections.Counter(v['countryQid'] for v in prev)

    out, seen, failed = [], set(), []
    for iso, qid in sorted(qids.items()):
        print(f'  {iso} ({qid}) ...', end='', flush=True)
        try:
            rows = sparql(QUERY % {'country': qid, 'lang': ISO_LANG.get(iso, 'en')})
        except Exception as e:
            print(f' FAILED: {e}'); failed.append((iso, qid)); continue
        n = 0
        for b in rows:
            cid = b['club']['value'].rsplit('/', 1)[-1]
            c = point(b['coord']['value'])
            if not c: continue
            key = (cid, b['venue']['value'])
            if key in seen: continue
            seen.add(key)
            out.append({'qid': cid, 'club': b['clubLabel']['value'],
                        'alt': b.get('clubAlt', {}).get('value'),
                        'stadium': b['venueLabel']['value'],
                        'lat': round(c[0], 5), 'lon': round(c[1], 5), 'countryQid': qid})
            n += 1
        print(f' {n} club-venue pairs')
        time.sleep(2)                 # be polite to a free public endpoint

    # Safety gate. A timeout or a throttled endpoint returns FEWER rows, not an error,
    # so a plain overwrite can quietly demote venues we already had to city-centre pins.
    # Refuse the write if any country we already covered came back materially thinner.
    after = collections.Counter(v['countryQid'] for v in out)
    lost = {q: (before[q], after[q]) for q in before if after[q] < before[q] * 0.9}
    if lost and '--force' not in sys.argv:
        print('\nREFUSING TO WRITE - these countries came back smaller than what we hold:')
        for q, (b, a) in sorted(lost.items()):
            print(f'  {q}: {b} -> {a}')
        print('Nothing was changed. Re-run later, or pass --force if this is expected.')
        return 1

    DATA.mkdir(exist_ok=True)
    (DATA/'wikidata-venues.json').write_text(json.dumps(out, ensure_ascii=False))
    print(f'\nwrote {len(out)} club-venue pairs across {len(after)} countries '
          f'-> data/wikidata-venues.json  (was {len(prev)})')
    if failed:
        print(f'failed, worth re-running: {[i for i, _ in failed]}')
    if '--check' in sys.argv: check(out)
    return 0


DROP = {'fc','afc','cf','sc','ac','as','ssc','us','ud','rc','cd','sd','club','de','calcio',
        'bk','sv','vfl','vfb','fsv','bsc','cp','sl','rcd','ca','ogc','losc','bc','cfc','the'}
def norm(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii','ignore').decode().lower()
    s = s.replace('.', '')          # "Arsenal F.C." -> "arsenal fc", so FC drops like any other
    return ' '.join(w for w in re.sub(r'[^a-z0-9 ]',' ',s).split() if w not in DROP)

def check(wd):
    """The number that decides how hard league expansion is: what share of the clubs
    we already carry does Wikidata resolve to a ground-level coordinate?"""
    idx = {}
    for v in wd:
        for name in (v['club'], v.get('alt')):
            if name: idx.setdefault(norm(name), v)
    ours = json.load(open(WEB/'venues.json', encoding='utf-8'))
    hit = [v for v in ours if norm(v['club']) in idx]
    print(f'\ncoverage: {len(hit)}/{len(ours)} of our clubs matched ({100*len(hit)//max(len(ours),1)}%)')
    by = collections.Counter(v['country'] for v in ours if norm(v['club']) not in idx)
    if by: print('unmatched by country:', dict(by))
    # agreement check on clubs where we already hold a ground-level coordinate
    import math
    gaps = []
    for v in hit:
        if v['precision'] != 'stadium': continue
        w = idx[norm(v['club'])]
        d = math.hypot((w['lon']-v['lon'])*math.cos(math.radians(v['lat']))*111.32, (w['lat']-v['lat'])*110.57)
        gaps.append((d, v['club']))
    if gaps:
        gaps.sort(reverse=True)
        bad = [g for g in gaps if g[0] > 2]
        print(f'agreement on {len(gaps)} known grounds: {len(gaps)-len(bad)} within 2 km')
        for d, c in gaps[:5]: print(f'   {d:7.2f} km  {c}')

if __name__ == '__main__':
    sys.exit(main())
