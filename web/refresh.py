#!/usr/bin/env python3
"""Nightly refresh: rebuild matches.json from openfootball, reusing resolved venues.

Venues change about once a season; fixtures and kickoff times change constantly.
So this re-fetches only the schedules and joins them to the venue table that the
full ingest already resolved. No API key, no venue work, ~8 small downloads.

    python3 refresh.py venues.json prev-matches.json out-matches.json [side.json ...]

Leagues with no machine-readable feed (Serie C, uploaded as a calendar file) live in
fixtures-static.json and are merged in here. Without that merge each night's rebuild
would silently delete them.

Exits non-zero without writing if a safety gate trips, so a bad upstream day
leaves the live site on its last good data rather than publishing a hole.
"""
import json, re, sys, unicodedata, datetime, urllib.request, collections, pathlib

BASE = 'https://raw.githubusercontent.com/openfootball/football.json/master'
SEASON = '2026-27'
LEAGUES = {
    'en.1': ('Premier League', 1, 'England'),  'en.2': ('Championship', 2, 'England'),
    'es.1': ('La Liga', 1, 'Spain'),           'it.1': ('Serie A', 1, 'Italy'),
    'de.1': ('Bundesliga', 1, 'Germany'),      'fr.1': ('Ligue 1', 1, 'France'),
    'nl.1': ('Eredivisie', 1, 'Netherlands'),  'pt.1': ('Primeira Liga', 1, 'Portugal'),
}
DROP = {'fc','afc','cf','sc','ac','as','ssc','us','ud','rc','cd','sd','sbv','club','de','del',
        'futbol','calcio','bk','sv','tsv','vfl','vfb','fsv','bsc','vv','cp','sl','rcd','ca','aj',
        'ogc','losc','psg','bc','cfc','sco','ve','the','1899','1900','1904','1907','1909','1913',
        '1963','65','07','04','05','09'}

def norm(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii','ignore').decode().lower().replace('.', '')
    return ' '.join(w for w in re.sub(r'[^a-z0-9 ]', ' ', s).split() if w not in DROP)

def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'PitchRadar-refresh/1.0'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def main(venues_path, prev_path, out_path, *side_paths):
    venues = json.load(open(venues_path, encoding='utf-8'))
    by_club = {norm(v['club']): v for v in venues}
    today = datetime.date.today().isoformat()

    out, missing, failed = [], collections.Counter(), []
    for code, (league, tier, country) in LEAGUES.items():
        try:
            data = fetch(f'{BASE}/{SEASON}/{code}.json')
        except Exception as e:
            failed.append(code); print(f'  {code}: FETCH FAILED {e}'); continue
        kept = 0
        for m in data.get('matches', []):
            if m.get('date', '') < today:
                continue
            v = by_club.get(norm(m['team1']))
            if not v:
                missing[m['team1']] += 1; continue
            out.append({'sid': norm(m['team1']), 'home': m['team1'], 'away': m['team2'],
                        'date': m['date'], 'time': m.get('time'), 'league': league, 'tier': tier,
                        'stadium': v['stadium'], 'city': v['city'], 'country': v['country'],
                        'lat': v['lat'], 'lon': v['lon'], 'precision': v['precision']})
            kept += 1
        print(f'  {code}: {kept} upcoming')

    # ---- merge the leagues that do not come from openfootball ----
    # fixtures-static.json: parsed from downloaded files, changes rarely.
    # fixtures-feeds.json:  fetched from live .ics URLs by ingest/feeds.py, nightly.
    # Each is merged independently so one missing file cannot take the other down.
    for side_path in side_paths:
        name = pathlib.Path(side_path).name
        try:
            side = [m for m in json.load(open(side_path, encoding='utf-8'))
                    if m.get('date', '') >= today]
            out += side
            print(f'  {name}: {len(side)} upcoming fixtures merged')
            if not side:
                failed.append(name)      # an empty side file means a league vanished
        except FileNotFoundError:
            print(f'  {name}: not found, skipping')
        except Exception as e:
            failed.append(name); print(f'  {name}: FAILED {e}')

    # ---- safety gates: refuse to publish a dataset that looks broken ----
    prev = []
    try:
        prev = json.load(open(prev_path, encoding='utf-8'))
    except Exception:
        pass
    problems = []
    if failed:
        problems.append(f'{len(failed)} league(s) failed to download: {", ".join(failed)}')
    if not out:
        problems.append('no fixtures produced at all')
    if prev and len(out) < len(prev) * 0.8:
        problems.append(f'fixture count fell from {len(prev)} to {len(out)}, more than 20%')
    if missing:
        problems.append(f'{sum(missing.values())} fixtures dropped for {len(missing)} unknown clubs: '
                        + ', '.join(list(missing)[:5]))

    timed = sum(1 for m in out if m['time'])
    print(f'\n{len(out)} upcoming fixtures, {timed} with a kickoff time '
          f'({100*timed//max(len(out),1)}%)')
    if prev:
        p_timed = sum(1 for m in prev if m.get('time'))
        print(f'previous: {len(prev)} fixtures, {p_timed} timed  '
              f'-> {len(out)-len(prev):+d} fixtures, {timed-p_timed:+d} timed')

    if problems:
        print('\nGATE FAILED, nothing written:')
        for p in problems: print('  -', p)
        return 1
    json.dump(out, open(out_path, 'w'), ensure_ascii=False)
    print(f'\nwrote {out_path}')
    return 0

if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:]))   # any number of side files
