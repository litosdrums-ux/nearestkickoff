"""Build web/cities.json, the search index behind the "where are you" box.

    python3 ingest/build-cities.py

The whole gazetteer is 68k towns, which is 1.6 MB of JSON, so the app fetches this
lazily - nothing is downloaded until someone actually clicks into the search box.
Names are joined with newlines rather than stored as an array of strings: it drops
68,000 pairs of quotes and commas, which is 350 KB.
"""
import json, collections, pathlib, gzip

ROOT = pathlib.Path(__file__).resolve().parent.parent
COUNTRY = {
    'AL':'Albania','AT':'Austria','BA':'Bosnia and Herzegovina','BE':'Belgium',
    'BG':'Bulgaria','CH':'Switzerland','CY':'Cyprus','CZ':'Czechia','DE':'Germany',
    'DK':'Denmark','EE':'Estonia','ES':'Spain','FI':'Finland','FR':'France',
    'GB':'United Kingdom','GR':'Greece','HR':'Croatia','HU':'Hungary','IE':'Ireland',
    'IS':'Iceland','IT':'Italy','LI':'Liechtenstein','LT':'Lithuania','LU':'Luxembourg',
    'LV':'Latvia','ME':'Montenegro','MK':'North Macedonia','NL':'Netherlands',
    'NO':'Norway','PL':'Poland','PT':'Portugal','RO':'Romania','RS':'Serbia',
    'SE':'Sweden','SI':'Slovenia','SK':'Slovakia','TR':'Turkey','UA':'Ukraine',
}

rows = json.load(open(ROOT/'data/cities-eu.json', encoding='utf-8'))
by, seen = collections.defaultdict(lambda: {'n': [], 'y': [], 'x': []}), set()
for r in sorted(rows, key=lambda r: (r['c'], r['n'])):
    key = (r['c'], r['n'])
    if key in seen or '\n' in r['n']:       # the newline is the record separator
        continue
    seen.add(key)
    d = by[r['c']]
    d['n'].append(r['n'])
    # 3 decimal places is about 110 m - far finer than a town centre is meaningful,
    # and it is only ever used as the origin for "how far is this match from me"
    d['y'].append(round(r['lat'] * 1e3))
    d['x'].append(round(r['lon'] * 1e3))

missing = sorted(set(by) - set(COUNTRY))
if missing:
    raise SystemExit(f'no country name for {missing} - add it to COUNTRY')

out = {'c': COUNTRY,
       'p': {k: {'n': '\n'.join(v['n']), 'y': v['y'], 'x': v['x']} for k, v in by.items()}}
blob = json.dumps(out, ensure_ascii=False, separators=(',', ':'))
(ROOT/'web/cities.json').write_text(blob, encoding='utf-8')
print(f'{len(seen)} towns in {len(by)} countries -> web/cities.json '
      f'{len(blob.encode())/1e6:.2f} MB ({len(gzip.compress(blob.encode(),9))/1e6:.2f} MB gzipped)')
