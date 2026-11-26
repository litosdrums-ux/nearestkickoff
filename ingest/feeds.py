"""Fetch live league calendar feeds and resolve venues -> web/fixtures-feeds.json.

Separate from calendars.py on purpose. calendars.py parses files a human downloaded -
season PDFs, one-off CSVs - and needs pdfplumber and those files on disk. This fetches
URLs that are always current, so it can run unattended in CI every night while the
file-based leagues stay frozen until someone re-downloads them.

Both outputs are merged by build.py and refresh.py. Keeping them in separate files means
a failure here cannot delete the file-based leagues, and vice versa.

Venues: these feeds carry no LOCATION, so grounds come from Wikidata via calendars.py.
A country with no Wikidata venues will resolve to town centres - run the "Refresh venue
data from Wikidata" action first when adding a country.

    python3 ingest/feeds.py            # fetch, resolve, write
    python3 ingest/feeds.py --dry-run  # fetch and report, write nothing
"""
import collections, datetime, json, pathlib, sys, tempfile, urllib.error, urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import calendars as cal                                    # noqa: E402

WEB = HERE.parent / 'web'
BASE = 'https://ics.fixtur.es/v2/league/'
UA = 'NearestKickoff/1.0 (https://nearestkickoff.com; contact@nearestkickoff.com)'

# slug, league name shown on the map, tier, country (must match europe.json), country QID
FEEDS = [
    ('ekstraklasa',                      'Ekstraklasa',     1, 'Poland',   'Q36'),
    ('croatia-hnl',                      'HNL',             1, 'Croatia',  'Q224'),
    ('hungarian-nemzeti-bajnoksag-nb-1', 'NB I',            1, 'Hungary',  'Q28'),
    ('liga-portugal-2',                  'Liga Portugal 2', 2, 'Portugal', 'Q45'),
    # Summer leagues: these run spring to autumn, so they fill the June-July hole the
    # winter leagues leave. Out of season they contribute nothing rather than failing -
    # their next season's fixtures appear in the feed when the league publishes them,
    # usually in December or January, and the nightly run picks them up on its own.
    ('irish-premier-division',           'Premier Division', 1, 'Ireland', 'Q27'),
    ('eliteserien',                      'Eliteserien',      1, 'Norway',  'Q20'),
    ('swedish-allsvenskan',              'Allsvenskan',      1, 'Sweden',  'Q34'),
]

# These feeds are multi-season archives going back years, so everything before today is
# dropped. The far limit guards against a feed that announces placeholder fixtures for
# seasons that have not been drawn.
HORIZON_DAYS = 420


def fetch(slug, dest):
    url = f'{BASE}{slug}.ics'
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    if b'BEGIN:VEVENT' not in data:
        # A feed can return a valid, well-formed, entirely empty calendar - voetbalkrant's
        # Ekstraklasa does exactly that. It looks like success and silently removes a league.
        raise SystemExit(f'{slug}: calendar has no events - refusing to continue')
    dest.write_bytes(data)
    return len(data)


def main(dry_run=False):
    today = datetime.date.today().isoformat()
    horizon = (datetime.date.today() + datetime.timedelta(days=HORIZON_DAYS)).isoformat()
    out, unresolved = [], collections.Counter()

    with tempfile.TemporaryDirectory() as tmp:
        for slug, league, tier, country, qid in FEEDS:
            path = pathlib.Path(tmp) / f'{slug}.ics'
            try:
                size = fetch(slug, path)
            except (urllib.error.URLError, TimeoutError) as e:
                # Wholesale rewrite: a feed we cannot reach must stop the run, or tonight's
                # file would simply be missing that league and the map would lose it.
                raise SystemExit(f'{slug}: download failed ({e}) - refusing to continue')

            meta = (slug, 'ics_feed', league, tier, country, qid)
            rows, kept = list(cal.ics_feed(path, meta)), 0
            for r in rows:
                if not (today <= r['date'] <= horizon):
                    continue
                v = cal.resolve(r['home'], r.get('ground'), qid, country)
                if not v:
                    unresolved[f'{country}: {r["home"]}'] += 1
                    continue
                out.append(dict(sid=cal.norm(r['home']), home=r['home'], away=r['away'],
                                date=r['date'], time=r['time'], note=r.get('note'),
                                league=league, tier=tier, country=country, **v))
                kept += 1
            timed = sum(1 for r in rows if r['time'])
            print(f'  {league:16} {len(rows):5} events, {kept:4} upcoming, '
                  f'{timed:5} with a kickoff time  ({size/1000:.0f} kB)')

    if unresolved:
        print('\n  clubs with no venue (dropped):')
        for k, n in unresolved.most_common(20):
            print(f'    {n:3}x {k}')

    prec = collections.Counter(m['precision'] for m in out)
    print(f'\n{len(out)} upcoming fixtures  (ground-level {prec["stadium"]}, '
          f'approximate {prec["city"]})')
    if prec['stadium'] == 0 and out:
        print('  ! every venue is a town centre - Wikidata has no stadiums for these '
              'countries yet. Run the "Refresh venue data from Wikidata" action.')
    if dry_run:
        print('dry run: nothing written')
        return 0
    (WEB / 'fixtures-feeds.json').write_text(json.dumps(out, ensure_ascii=False))
    print('-> web/fixtures-feeds.json')
    return 0


if __name__ == '__main__':
    sys.exit(main('--dry-run' in sys.argv))
