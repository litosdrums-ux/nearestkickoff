"""Generate static city and league pages from web/matches.json.

The map is one JavaScript page, so a search engine sees almost nothing: the site ranks
for nothing and has no distribution that compounds. These pages are the fix - real HTML
text, generated from fixture data we already hold, answering the thing people actually
type ("football in Florence this weekend").

They are regenerated on every build, so they never drift from the map.

    python3 ingest/build-pages.py        -> web/city/<slug>/, web/league/<slug>/
"""
import collections, datetime, html, json, math, pathlib, re, shutil, sys, unicodedata

HERE = pathlib.Path(__file__).resolve().parent
WEB = HERE.parent / 'web'
SITE = 'https://nearestkickoff.com'

MONTH = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
DAY = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


def slug(s):
    s = unicodedata.normalize('NFKD', s)
    for a, b in (('ø', 'o'), ('æ', 'ae'), ('ł', 'l'), ('ı', 'i'), ('ß', 'ss'),
                 ('ð', 'd'), ('þ', 'th'), ('đ', 'd')):
        s = s.replace(a, b).replace(a.upper(), b)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', s.lower())).strip('-')


def tickets_map():
    """Read the league -> competition slug table out of index.html rather than keeping a
    second copy here. Two copies drift, and the one that drifts is the one nobody looks
    at; a dead affiliate link on a page nobody checks would sit there for months."""
    src = (WEB / 'index.html').read_text(encoding='utf-8')
    aff = re.search(r"const AFF='([^']+)'", src)
    blk = re.search(r'const TICKETS=\{(.*?)\};', src, re.S)
    if not (aff and blk):
        sys.exit('could not read TICKETS/AFF out of index.html - check the markers')
    return aff.group(1), dict(re.findall(r"'([^']+)':'([^']+)'", blk.group(1)))


AFF, TICKETS = tickets_map()


def ticket_url(league):
    s = TICKETS.get(league)
    return f'{SITE and ""}https://www.sportsevents365.com/dock/competition/{s}?a_aid={AFF}&data1={s}' if s else None


def when(m):
    d = datetime.date.fromisoformat(m['date'])
    return f'{DAY[d.weekday()]} {d.day} {MONTH[d.month - 1]}'


def km(a, b, c, d):
    return 6371 * math.acos(min(1, math.sin(math.radians(a)) * math.sin(math.radians(c))
                            + math.cos(math.radians(a)) * math.cos(math.radians(c))
                            * math.cos(math.radians(d - b))))


def page(title, desc, canonical, body, crumb):
    return f'''<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(desc)}">
<link rel="canonical" href="{canonical}">
<link rel="stylesheet" href="/page.css">
</head><body><div class="wrap">
<header><span class="logo"></span><a href="/">Nearest Kickoff</a></header>
<p class="crumb">{crumb}</p>
{body}
<footer>
  <a href="/">Map</a><a href="/cities/">Cities</a><a href="/leagues/">Leagues</a>
  <a href="/credits.html">Credits</a><a href="/privacy.html">Privacy</a>
  <a href="/terms.html">Terms</a><a href="/disclosure.html">Affiliate disclosure</a>
</footer>
</div></body></html>
'''


def fixture_rows(ms, show_city=False):
    out = ['<table><tr><th>When</th><th>Match</th><th>League</th>'
           + ('<th>Where</th>' if show_city else '<th>Ground</th>') + '<th></th></tr>']
    for m in ms:
        t = ticket_url(m['league'])
        tix = (f'<a class="tix" href="{t}" rel="sponsored nofollow noopener" target="_blank">'
               'Tickets <span class="aff">affiliate</span></a>') if t else ''
        where = (f"{html.escape(m['city'])}" if show_city else html.escape(m['stadium'] or ''))
        out.append(
            f"<tr><td class='w'>{when(m)}<span class='t'>{m['time'] or 'time TBC'}</span></td>"
            f"<td><strong>{html.escape(m['home'])}</strong> v {html.escape(m['away'])}</td>"
            f"<td class='lg'>{html.escape(m['league'])}</td>"
            f"<td class='lg'>{where}</td><td>{tix}</td></tr>")
    out.append('</table>')
    return '\n'.join(out)


def main():
    matches = json.load(open(WEB / 'matches.json', encoding='utf-8'))
    today = datetime.date.today().isoformat()
    matches = sorted((m for m in matches if m['date'] >= today), key=lambda m: (m['date'], m['time'] or '99'))

    by_city, by_league = collections.defaultdict(list), collections.defaultdict(list)
    for m in matches:
        by_city[(m['city'], m['country'])].append(m)
        by_league[m['league']].append(m)

    # Two cities can share a name across countries (Valencia, Córdoba). Only the clashing
    # ones get the country in their slug, so the common case keeps the clean URL.
    names = collections.Counter(slug(c) for c, _ in by_city)
    city_slug = {k: (slug(k[0]) if names[slug(k[0])] == 1 else f'{slug(k[0])}-{slug(k[1])}')
                 for k in by_city}

    for d in ('city', 'league'):
        shutil.rmtree(WEB / d, ignore_errors=True)
    urls = []

    # ---- city pages ----
    centres = {k: (sum(m['lat'] for m in v) / len(v), sum(m['lon'] for m in v) / len(v))
               for k, v in by_city.items()}
    for (city, country), ms in by_city.items():
        sl = city_slug[(city, country)]
        lat, lon = centres[(city, country)]
        near = sorted(((km(lat, lon, *centres[k]), k) for k in by_city if k != (city, country)),
                      key=lambda x: x[0])[:8]
        near = [k for d, k in near if d < 120]
        clubs = sorted({m['home'] for m in ms})
        leagues = sorted({m['league'] for m in ms})
        n = len(ms)
        desc = (f'{n} upcoming football {"match" if n == 1 else "matches"} in {city}, '
                f'{country}. Dates, kickoff times and grounds, updated daily.')
        body = f'''<h1>Football in {html.escape(city)}</h1>
<p class="lede">{n} upcoming {"match" if n == 1 else "matches"} in {html.escape(city)},
{html.escape(country)} — first on {when(ms[0])}. Updated every night.</p>
<p><a class="cta" href="/?city={html.escape(city)}">See {html.escape(city)} on the map &rarr;</a></p>
{fixture_rows(ms)}
<h2>Who plays here</h2>
<p>{", ".join(html.escape(c) for c in clubs)} — in
{", ".join(f'<a href="/league/{slug(l)}/">{html.escape(l)}</a>' for l in leagues)}.</p>
'''
        if near:
            body += ('<h2>Nearby</h2>\n<p>' + ' · '.join(
                f'<a href="/city/{city_slug[k]}/">{html.escape(k[0])}</a>' for k in near) + '</p>\n')
        out = WEB / 'city' / sl
        out.mkdir(parents=True, exist_ok=True)
        (out / 'index.html').write_text(page(
            f'Football in {city} — fixtures, dates and tickets', desc,
            f'{SITE}/city/{sl}/', body,
            f'<a href="/">Map</a> › <a href="/cities/">Cities</a> › {html.escape(city)}'),
            encoding='utf-8')
        urls.append((f'/city/{sl}/', 'daily', '0.7'))

    # ---- league pages ----
    for league, ms in by_league.items():
        sl = slug(league)
        cities = sorted({(m['city'], m['country']) for m in ms})
        country = ms[0]['country']
        n = len(ms)
        desc = (f'{n} upcoming {league} fixtures with dates, kickoff times and grounds. '
                f'See them on a map of football across Europe.')
        body = f'''<h1>{html.escape(league)} fixtures</h1>
<p class="lede">{n} upcoming {html.escape(league)} {"match" if n == 1 else "matches"}
in {html.escape(country)} — first on {when(ms[0])}. Updated every night.</p>
<p><a class="cta" href="/">See them on the map &rarr;</a></p>
{fixture_rows(ms[:120], show_city=True)}
{'<p class="more">Showing the next 120 fixtures.</p>' if n > 120 else ''}
<h2>Where {html.escape(league)} is played</h2>
<p>{" · ".join(f'<a href="/city/{city_slug[k]}/">{html.escape(k[0])}</a>' for k in cities)}</p>
'''
        out = WEB / 'league' / sl
        out.mkdir(parents=True, exist_ok=True)
        (out / 'index.html').write_text(page(
            f'{league} fixtures — dates, times and grounds', desc,
            f'{SITE}/league/{sl}/', body,
            f'<a href="/">Map</a> › <a href="/leagues/">Leagues</a> › {html.escape(league)}'),
            encoding='utf-8')
        urls.append((f'/league/{sl}/', 'daily', '0.7'))

    # ---- indexes, so every page is reachable by a crawler in two clicks ----
    for name, title, items in (
        ('cities', 'Cities', sorted(((k[0], k[1], city_slug[k], len(v)) for k, v in by_city.items()),
                                    key=lambda x: (x[1], x[0]))),
        ('leagues', 'Leagues', sorted(((l, by_league[l][0]['country'], slug(l), len(by_league[l]))
                                       for l in by_league), key=lambda x: (x[1], x[0])))):
        groups = collections.defaultdict(list)
        for nm, ctry, sl, cnt in items:
            groups[ctry].append((nm, sl, cnt))
        body = [f'<h1>{title}</h1>',
                f'<p class="lede">Every place with upcoming fixtures, {len(items)} in all.</p>'
                if name == 'cities' else
                f'<p class="lede">All {len(items)} leagues currently on the map.</p>']
        for ctry in sorted(groups):
            body.append(f'<h2>{html.escape(ctry)}</h2>\n<p class="idx">' + ' · '.join(
                f'<a href="/{"city" if name == "cities" else "league"}/{sl}/">'
                f'{html.escape(nm)}</a> <span class="n">{cnt}</span>'
                for nm, sl, cnt in groups[ctry]) + '</p>')
        out = WEB / name
        out.mkdir(parents=True, exist_ok=True)
        (out / 'index.html').write_text(page(
            f'{title} — Nearest Kickoff', f'{title} with upcoming football fixtures across Europe.',
            f'{SITE}/{name}/', '\n'.join(body), f'<a href="/">Map</a> › {title}'), encoding='utf-8')
        urls.append((f'/{name}/', 'daily', '0.5'))

    # ---- sitemap ----
    head = [('/', 'daily', '1.0'), ('/credits.html', 'monthly', '0.3'),
            ('/privacy.html', 'yearly', '0.2'), ('/terms.html', 'yearly', '0.2'),
            ('/disclosure.html', 'yearly', '0.2')]
    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u, freq, pri in head + urls:
        xml.append(f'  <url><loc>{SITE}{u}</loc><changefreq>{freq}</changefreq>'
                   f'<priority>{pri}</priority></url>')
    xml.append('</urlset>')
    (WEB / 'sitemap.xml').write_text('\n'.join(xml), encoding='utf-8')

    print(f'{len(by_city)} city pages, {len(by_league)} league pages, '
          f'2 indexes, sitemap with {len(head) + len(urls)} urls')
    print(f'  fixtures covered: {len(matches)}')
    print(f'  pages with a ticket link: '
          f'{sum(1 for ms in by_city.values() if any(ticket_url(m["league"]) for m in ms))} cities')


if __name__ == '__main__':
    main()
