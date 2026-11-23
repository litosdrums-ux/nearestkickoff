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
UA = 'PitchRadar/0.1 (https://example.com; you@example.com)'

# country label -> Wikidata QID. Verify a QID by opening wikidata.org/wiki/<QID>.
COUNTRIES = {
    'England': 'Q145', 'Scotland': 'Q145', 'Wales': 'Q145',   # all under the UK item
    'Spain': 'Q29', 'Italy': 'Q38', 'Germany': 'Q183', 'France': 'Q142',
    'Netherlands': 'Q55', 'Portugal': 'Q45', 'Belgium': 'Q31', 'Austria': 'Q40',
    'Switzerland': 'Q39', 'Greece': 'Q41', 'Türkiye': 'Q43', 'Denmark': 'Q35',
}
# P31 instance of · P279 subclass of · P17 country · P115 home venue · P625 coordinates
# Q476028 association football club
QUERY = '''
SELECT ?club ?clubLabel ?clubAlt ?venue ?venueLabel ?coord WHERE {
  ?club wdt:P31/wdt:P279* wd:Q476028 ;
        wdt:P17 wd:%(country)s ;
        wdt:P115 ?venue .
  ?venue wdt:P625 ?coord .
  OPTIONAL { ?club skos:altLabel ?clubAlt FILTER(LANG(?clubAlt) IN ("en","%(lang)s")) }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,%(lang)s". }
}
'''
LANG = {'Q38':'it','Q29':'es','Q183':'de','Q142':'fr','Q55':'nl','Q45':'pt',
        'Q145':'en','Q31':'nl','Q40':'de','Q39':'de','Q41':'el','Q43':'tr','Q35':'da'}

def sparql(query):
    url = ENDPOINT + '?' + urllib.parse.urlencode({'query': query, 'format': 'json'})
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/sparql-results+json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)['results']['bindings']

def point(wkt):                      # 'Point(11.2824 43.7809)' -> (lat, lon)
    m = re.match(r'Point\(([-\d.]+) ([-\d.]+)\)', wkt)
    return (float(m.group(2)), float(m.group(1))) if m else None

def main():
    out, seen = [], set()
    for qid in sorted(set(COUNTRIES.values())):
        print(f'  querying {qid} ...', flush=True)
        try:
            rows = sparql(QUERY % {'country': qid, 'lang': LANG.get(qid, 'en')})
        except Exception as e:
            print(f'    FAILED {qid}: {e}'); continue
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
        print(f'    {len(rows)} rows')
        time.sleep(2)                 # be polite to a free public endpoint
    DATA.mkdir(exist_ok=True)
    (DATA/'wikidata-venues.json').write_text(json.dumps(out, ensure_ascii=False))
    print(f'\nwrote {len(out)} club-venue pairs -> data/wikidata-venues.json')
    if '--check' in sys.argv: check(out)

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
    main()
