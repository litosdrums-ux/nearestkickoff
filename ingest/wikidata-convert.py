#!/usr/bin/env python3
"""Turn a Wikidata Query Service JSON download into data/wikidata-venues.json.

The WDQS web UI's "Download > JSON" gives a flat list of label/value rows, which is
a different shape from the SPARQL API's results.bindings. This accepts either.

    python3 ingest/wikidata-convert.py <downloaded.json>
"""
import json, re, sys, pathlib
DATA = pathlib.Path(__file__).resolve().parent.parent/'data'
QID = {'United Kingdom':'Q145','Spain':'Q29','Italy':'Q38','Germany':'Q183','France':'Q142',
       'Netherlands':'Q55','Portugal':'Q45','Belgium':'Q31','Austria':'Q40','Switzerland':'Q39',
       'Greece':'Q41','Turkey':'Q43','Türkiye':'Q43','Denmark':'Q35',
       'Czech Republic':'Q213','Czechia':'Q213'}

# Wikidata lists academies, women's and reserve sides as separate clubs sharing a name.
# They are not what a fixture means by "Arsenal", and they manufacture false ambiguity.
NOT_FIRST_TEAM = re.compile(
    r"\b(women|ladies|femen\w*|femmin\w*|frauen|academy|youth|reserves?|"
    r"development|under[- ]?\d+|u1\d|u2\d|a2|jong|national football team)\b", re.I)
# accented and localised variants the \b-word list above misses
NOT_FIRST_ALT = re.compile(r"f[ée]minin|frauen|femminile|\bYLA\b", re.I)
# a basketball or volleyball club can share a football club's name; its arena is not a ground
INDOOR = re.compile(r"indoor|sport\s*hall|\bgym\b|arena di|palazzetto", re.I)
# Wikidata returns the bare QID when an item has no label in the languages asked for
BARE_QID = re.compile(r"^Q\d+$")
# A reserve side is written "Espanyol B" - a trailing B only. Matching a bare "b"
# anywhere also swallows "Treviso F.B.C.", which is a first team.
B_TEAM = re.compile(r"\sB$", re.I)

def val(r, k):
    v = r.get(k)
    return v.get('value') if isinstance(v, dict) else v

def main(*paths):
    rows, out, skipped = [], [], 0
    for path in paths:
        raw = json.load(open(path, encoding='utf-8'))
        rows += raw['results']['bindings'] if isinstance(raw, dict) else raw
    for r in rows:
        coord, club = val(r, 'coord'), val(r, 'clubLabel')
        m = re.match(r'Point\(([-\d.]+) ([-\d.]+)\)', coord or '')
        country = val(r, 'countryLabel')
        stadium = val(r, 'venueLabel') or ''
        # an unlabelled venue comes back as its bare QID, which is not a stadium name
        if re.fullmatch(r'Q\d+', stadium.strip()):
            skipped += 1; continue
        if (not (m and club and country in QID)
                or NOT_FIRST_TEAM.search(club) or NOT_FIRST_ALT.search(club)
                or B_TEAM.search(club.strip()) or BARE_QID.match(club.strip())
                or INDOOR.search(stadium)):
            skipped += 1; continue
        out.append({'qid': (val(r, 'club') or '').rsplit('/', 1)[-1] or None,
                    'club': club, 'alt': None, 'stadium': stadium,
                    'city': None, 'lat': round(float(m.group(2)), 5),
                    'lon': round(float(m.group(1)), 5), 'countryQid': QID[country]})
    seen, uniq = set(), []
    for v in out:
        k = (v['club'], round(v['lat'], 4), round(v['lon'], 4))
        if k in seen: continue
        seen.add(k); uniq.append(v)
    out = uniq
    (DATA/'wikidata-venues.json').write_text(json.dumps(out, ensure_ascii=False))
    print(f'{len(out)} venues written to data/wikidata-venues.json ({skipped} rows skipped)')

if __name__ == '__main__':
    main(*sys.argv[1:])
