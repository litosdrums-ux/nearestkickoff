#!/usr/bin/env python3
"""Build web/matches.json + web/venues.json from open, public-domain sources.

No API key and no live service: season schedules are published months ahead, so
this is a batch job you re-run (nightly is plenty) rather than a request-time call.

Sources
  schedules  openfootball/football.json      public domain
  verified   ingest/verified-venues.json     hand-checked, source named per venue
  cities     lutangar/cities.json            city-precision fallback
  seed       web/stadiums.json               hand-checked venues
"""
import json, csv, re, sys, os, unicodedata, datetime, pathlib, collections

HERE = pathlib.Path(__file__).resolve().parent
DATA, WEB = HERE.parent/'data', HERE.parent/'web'

LEAGUES = {  # file: (display name, tier, country, ISO2)
 'en.1':('Premier League',1,'England','GB'),   'en.2':('Championship',2,'England','GB'),
 'es.1':('La Liga',1,'Spain','ES'),            'it.1':('Serie A',1,'Italy','IT'),
 'de.1':('Bundesliga',1,'Germany','DE'),       'fr.1':('Ligue 1',1,'France','FR'),
 'nl.1':('Eredivisie',1,'Netherlands','NL'),   'pt.1':('Primeira Liga',1,'Portugal','PT'),
}
DROP = {'fc','afc','cf','sc','ac','as','ssc','us','ud','rc','cd','sd','club','de','del','futbol',
        'calcio','bk','sv','tsv','vfl','vfb','fsv','bsc','vv','cp','sl','rcd','ca','aj','ogc',
        'losc','psg','bc','cfc','sco','ve','the','1899','1900','1904','1907','1909','1913','1963','65','07','04','05','09'}

# Characters NFKD does not decompose, so stripping accents deletes them outright:
# "Kasımpaşa" would reduce to "kasmpasa" and "Brøndby" to "brndby", and neither
# would ever match. Map them to their Latin equivalents first.
TRANSLIT = str.maketrans({'\u0131':'i','\u0130':'i','\u00f8':'o','\u00d8':'o','\u00e6':'ae','\u00c6':'ae',
                          '\u0153':'oe','\u0152':'oe','\u00df':'ss','\u0142':'l','\u0141':'l','\u0111':'d',
                          '\u0110':'d','\u00f0':'d','\u00fe':'th','\u00e5':'a','\u00c5':'a'})

def norm(s):
    s = unicodedata.normalize('NFKD', s.translate(TRANSLIT)).encode('ascii','ignore').decode().lower()
    s = s.replace('.', '')          # "Arsenal F.C." -> "arsenal fc", so FC drops like any other
    s = re.sub(r"[^a-z0-9 ]", ' ', s)
    return ' '.join(w for w in s.split() if w and w not in DROP)

# ---------- venue sources ----------
# Hand-verified venues come first: each one was checked against a named public source
# and carries that source in the file. They exist because Wikidata lists historic home
# grounds next to current ones, and because data/stadiums-src.csv - the old fallback -
# had a licence we could never establish. Nothing reads that csv any more.
VERIFIED = {}
for v in json.load(open(HERE/'verified-venues.json', encoding='utf-8'))['venues']:
    rec = dict(stadium=v['stadium'], city=v['city'], lat=v['lat'], lon=v['lon'],
               country=v['country'], precision='stadium', source='verified')
    if v.get('venue_country'):
        rec['venue_country'] = v['venue_country']
    for name in v['clubs']:
        VERIFIED[norm(name)] = rec

stad = {}                                   # normalised club -> venue (stadium precision)
for s in json.load(open(WEB/'stadiums.json', encoding='utf-8')):
    k = norm(s['club'])
    if k and k not in stad:
        stad[k] = dict(stadium=s['stadium'], city=s['city'], lat=s['lat'], lon=s['lon'],
                       country=s['country'], precision='stadium')

# Wikidata is the preferred venue source: CC0, ground-level, and it covers far more
# clubs than the stadium csv. Optional - if the file is absent the build still runs on
# the csv + seed, so fetching it is an upgrade, never a dependency.
#   python3 ingest/wikidata-venues.py     ->  data/wikidata-venues.json
ISO_QID = {'GB': 'Q145', 'ES': 'Q29', 'IT': 'Q38', 'DE': 'Q183', 'FR': 'Q142',
           'NL': 'Q55', 'PT': 'Q45', 'BE': 'Q31', 'AT': 'Q40', 'CH': 'Q39',
           'GR': 'Q41', 'TR': 'Q43', 'DK': 'Q35'}
WD_PATH = pathlib.Path(os.environ.get('WIKIDATA_FILE', DATA/'wikidata-venues.json'))
tight = lambda s: re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', s)
                         .encode('ascii', 'ignore').decode().lower())
wiki, wiki_tight = collections.defaultdict(list), collections.defaultdict(list)
if WD_PATH.exists():
    for v in json.load(open(WD_PATH, encoding='utf-8')):
        for name in (v['club'], v.get('alt')):
            if name:
                wiki[norm(name)].append(v)
                wiki_tight[tight(name)].append(v)
    print(f'wikidata: {WD_PATH.name}, {sum(len(x) for x in wiki.values())} name keys')
else:
    print(f'wikidata: {WD_PATH} not present, using csv + seed only')

WD_ALIAS = {k: v for k, v in json.load(open(HERE/'wikidata-club-aliases.json', encoding='utf-8')).items()
            if not k.startswith('_')}

aliases = {k: v for k, v in json.load(open(HERE/'venue-aliases.json', encoding='utf-8')).items()
           if not k.startswith('_')}

cities = collections.defaultdict(list)
for c in json.load(open(DATA/'cities-eu.json', encoding='utf-8')):
    cities[(c['c'], norm(c['n']))].append(c)

def city_for(team, iso):
    """Wikidata gives us a ground, not a town. The city is still what a reader wants
    to see in the list, so resolve it separately from the coordinate."""
    k = norm(team)
    if k in stad and stad[k].get('city'):
        return stad[k]['city']
    if team in aliases:
        return aliases[team]
    for (ci, cn), rows in cities.items():
        if ci == iso and cn and cn in k.split():
            return rows[0]['n']
    return None

def from_wikidata(team, iso, country):
    """Match on club name, but only inside the right country: club names repeat across
    Europe, and a cross-border match would put a pin in the wrong nation silently."""
    want = ISO_QID.get(iso)
    # Look Wikidata up under its own name for the club, but record the venue under the
    # name our fixtures use - otherwise nothing downstream can join back to it.
    lookup = WD_ALIAS.get(team, team)
    k = norm(lookup)
    ok = lambda v: not want or v.get('countryQid') == want
    # An exact full-name match beats a normalised one: "AFC Bournemouth" and
    # "Bournemouth F.C." are different clubs that normalise identically.
    hits = [v for v in wiki_tight.get(tight(lookup), []) if ok(v)]
    if not hits:
        hits = [v for v in wiki.get(k, []) if ok(v)]
    if not hits and k:
        # "PSV" against Wikidata's "PSV Eindhoven": one name's tokens contain the other's
        tk = set(k.split())
        hits = [v for ck, vs in wiki.items() if ck and
                (set(ck.split()) <= tk or tk <= set(ck.split()))
                for v in vs if ok(v)]
    if not hits:
        return None
    # Several rows for one club are usually the same ground stated twice. Only a
    # genuinely different location is ambiguous - a club that moved, say - and that
    # is the case worth refusing, because we cannot tell which ground is current.
    # A club often lists a former ground beside its current one. When one location is
    # stated more often than the others, take it; a genuine tie we refuse, because
    # picking at random is how a pin ends up at a demolished stadium.
    spots = collections.Counter((round(v['lat'], 3), round(v['lon'], 3)) for v in hits)
    (best, n), = spots.most_common(1)
    if len(spots) > 1 and n == sorted(spots.values())[-2]:
        return None
    v = next(v for v in hits if (round(v['lat'], 3), round(v['lon'], 3)) == best)
    return dict(club=team, stadium=v['stadium'],
                city=v.get('city') or city_for(team, iso) or v['stadium'],
                lat=v['lat'], lon=v['lon'], country=country,
                precision='stadium', source='wikidata')

def resolve(team, iso, country):
    v = VERIFIED.get(norm(team))
    if v:
        return dict(v, club=team)
    v = from_wikidata(team, iso, country)
    if v:
        return v
    k = norm(team)
    if k in stad:
        return dict(stad[k], club=team, source='seed')
    # token-subset match (e.g. "Manchester United FC" vs "Man United")
    tk = set(k.split())
    best = [v for ck, v in stad.items() if tk and (set(ck.split()) <= tk or tk <= set(ck.split()))]
    if len(best) == 1:
        return dict(best[0], club=team, source='seed')
    # fall back to the club's city
    city = aliases.get(team)
    if not city:                       # city often sits inside the club name
        for (ci, cn), rows in cities.items():
            if ci == iso and cn and cn in k.split():
                city = rows[0]['n']; break
    if city:
        rows = cities.get((iso, norm(city)))
        if rows:
            r = rows[0]
            return dict(club=team, stadium=city, city=city, lat=r['lat'], lon=r['lon'],
                        country=country, precision='city', source='city-fallback')
    return None

# ---------- build ----------
TODAY = datetime.date.today().isoformat()
venues, matches, unresolved = {}, [], collections.defaultdict(list)
for code, (league, tier, country, iso) in LEAGUES.items():
    p = DATA/f'{code}.json'
    if not p.exists():
        print(f'  ! missing {p.name}, skipped'); continue
    d = json.load(open(p, encoding='utf-8'))
    for m in d['matches']:
        home = m['team1']
        if home not in venues:
            v = resolve(home, iso, country)
            if not v:
                unresolved[code].append(home); continue
            venues[home] = v
        if m['date'] < TODAY: continue          # past fixtures: nothing to show on a "what's on" map
        v = venues[home]
        matches.append(dict(sid=norm(home) or home, home=home, away=m['team2'],
                            date=m['date'], time=m.get('time'), league=league, tier=tier,
                            stadium=v['stadium'], city=v['city'], country=v['country'],
                            lat=v['lat'], lon=v['lon'], precision=v['precision']))

json.dump(sorted(venues.values(), key=lambda v: (v['country'], v['club'])),
          open(WEB/'venues.json','w'), ensure_ascii=False)
# The calendar-file leagues are ingested separately (ingest/calendars.py, which writes
# web/fixtures-static.json) because they come from published PDFs/ICS rather than an API.
# They are merged here so matches.json - the only file the app fetches - is rebuilt by one
# command rather than by remembering to concatenate two files by hand.
static_path = WEB/'fixtures-static.json'
static = json.load(open(static_path, encoding='utf-8')) if static_path.exists() else []
static = [m for m in static if m['date'] >= TODAY]
if not static:
    print('  ! fixtures-static.json is empty - run ingest/calendars.py first, or the '
          'calendar leagues will be missing from the map')
matches += static
json.dump(matches, open(WEB/'matches.json','w'), ensure_ascii=False)

# ---------- report ----------
prec = collections.Counter(v['precision'] for v in venues.values())
src = collections.Counter(v.get('source', '?') for v in venues.values())
print('venue sources:', dict(src))
print(f"venues {len(venues)}  (stadium-precision {prec['stadium']}, city-precision {prec['city']})")
print(f"matches {len(matches)}")
today = datetime.date.today().isoformat()
soon = [m for m in matches if today <= m['date'] <= (datetime.date.today()+datetime.timedelta(days=14)).isoformat()]
print(f"next 14 days: {len(soon)}  ({sum(1 for m in soon if not m['time'])} without a kickoff time)")
if unresolved:
    print('\nUNRESOLVED home teams (no fixtures emitted for these):')
    for c, ts in unresolved.items(): print(f'  {c}: {", ".join(sorted(set(ts)))}')
