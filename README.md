# PitchRadar

Interactive map of football matches near you across Europe.

## Status
Working prototype on **real 2026/27 fixtures** — 5,873 upcoming matches across 28 leagues in
15 countries, down to the 4th tier.

| Country | Leagues |
|---|---|
| England | Premier League, Championship, League One, League Two |
| Italy | Serie A, Serie B, Serie C (Gironi A/B/C), Serie D (Girone E) |
| Germany | Bundesliga, 2. Bundesliga, 3. Liga |
| France | Ligue 1, Ligue 2 |
| Netherlands | Eredivisie, Eerste Divisie |
| Spain | La Liga, Segunda División |
| Portugal / Belgium / Scotland | Primeira Liga, Belgian Pro League, Scottish Premiership |
| Turkey / Greece / Czechia / Switzerland / Austria / Denmark | Süper Lig, Super League, Chance Liga, Swiss Super League, Austrian Bundesliga, Superliga |

Eight come from a feed and are rebuilt nightly; the other twenty come from published
calendar files and are merged from `web/fixtures-static.json` (see below).

## No API needed
Season schedules are published months in advance, so this is a **batch job, not a live service**.
Nothing is fetched at request time and there is no API key in the app.

| What | Source | Licence |
|---|---|---|
| Schedules | `openfootball/football.json` | public domain |
| Stadium coordinates | Wikidata | CC0, 143 venues, ground-level |
| Hand-verified venues | `ingest/verified-venues.json` | 9 venues, source named per venue |
| City coordinates | `lutangar/cities.json` | fallback for the other 64 venues |
| Town gazetteer (search box) | `lutangar/cities.json` | 68,493 towns in 38 countries |
| Country outlines | Natural Earth 10m via `world-atlas` | public domain |
| Province/state borders | Natural Earth 10m admin-1 (`nvkelso/natural-earth-vector`) | public domain |

Re-run nightly; that is frequent enough for schedules and covers postponements.

## The "where are you" search box

`ingest/build-cities.py` turns the gazetteer into `web/cities.json`: every town in the 38
countries we draw, 1.65 MB of it (0.66 MB over the wire gzipped). That is too much to put in
the critical path, so **nothing is fetched until someone clicks into the box** - the app opens,
draws and is usable without it, and the fetch is warmed on first focus rather than first
keystroke so the list is already there by the time a word is typed.

Two things keep it small: coordinates are rounded to 3 decimal places (about 110 m, far finer
than a town centre is meaningful when it is only ever the origin for "how far is this match"),
and names are joined with newlines instead of stored as an array, which drops 68,000 pairs of
quotes and commas - 350 KB.

Searching folds accents, so `zurich` finds Zürich, `koln` finds Köln and `brondby` finds
Brøndby. That needs more than NFKD: ø, æ, ł, ı, ß, ð, þ and đ are standalone letters that
decomposition leaves untouched, so they are mapped by hand in `deburr()`.

**Known limitation: the gazetteer carries no population.** Ranking puts prefix matches ahead of
substring matches and then leans on whether a town hosts football in our own fixture data as a
stand-in for prominence. That is right most of the time - `mil` gives Milan, `manch` gives
Manchester, `munic` gives Munich - but it is a proxy, and it shows: `barce` offers Barcelos
(Primeira Liga) above Barcelona, which hosts nothing in our data. A population field would fix
the ordering properly; the upstream source does not have one, so it would mean a second
gazetteer.

## Adding Wikidata venues

Wikidata is the preferred venue source: CC0 (no share-alike, unlike OpenStreetMap's ODbL),
ground-level, and far wider than the stadium csv. It is optional - without the file the build
runs on the csv plus seed exactly as before, so this is an upgrade, never a dependency.

    # 1. put a real contact in the UA line of ingest/wikidata-venues.py first:
    #    Wikidata rejects requests without a descriptive User-Agent
    python3 ingest/wikidata-venues.py --check    # -> data/wikidata-venues.json

`--check` answers the question worth answering before any expansion work: what share of the
clubs we already carry does Wikidata resolve, and do its coordinates agree with the grounds we
already know? Disagreement over ~2 km on a known ground means the match is wrong, not the data.

    # 2. rebuild - build.py picks the file up automatically
    python3 ingest/build.py
    python3 ingest/verify.py

### Why there is a hand-verified venue file

Wikidata lists a club's historic home grounds alongside its current one, and our extract has
no way to tell them apart, so the resolver refuses any club with more than one rather than
guess. `ingest/verified-venues.json` is those clubs, each resolved by checking a named public
source, with that source recorded in the entry. **Paris FC is why this is done by hand:** it
moved to the Stade Jean-Bouin in 2025, so *both* of its Wikidata rows are stale and picking
either would have produced a confident wrong pin.

The same file replaced `jokecamp/FootballData`'s stadium csv, whose licence we were never able
to establish. Nothing in the build reads that csv now.

`build.py` prints a source breakdown (`wikidata` / `verified` / `seed` / `city-fallback`) so you can see
coverage move. Two safety rules in the join, both tested with decoys in `/tmp/wd-fixture.json`:

- **Country-gated.** A name only matches inside the club's own country, because club names
  repeat across Europe and a cross-border match places a pin in the wrong nation silently.
- **Ambiguity is rejected, not guessed.** Two Wikidata entries for one club in one country
  means no match, falling through to the csv rather than picking one.

Set `WIKIDATA_FILE` to test against a fixture without touching the real file.

    node ingest/build-europe.mjs     # country outlines   -> web/europe.json
    node ingest/build-provinces.mjs  # province borders   -> web/provinces.json
    python3 ingest/calendars.py <every calendar file>   # -> web/fixtures-static.json
    python3 ingest/build.py          # fixtures + venues -> web/matches.json, web/venues.json
    python3 ingest/verify.py         # fails the build if a venue is not on land

### Venue precision is tracked, not faked
Each venue carries `precision`. 456 of 509 points are the actual ground; the other 53 are city
centres, drawn as **hollow pins**, labelled approximate, and linking to a maps *search* rather
than a confident wrong route. Filling these in is the main data chore — add a row to
`ingest/venue-aliases.json` or, better, a real coordinate to the stadium table.

A reserve side is treated as its own club and never inherits its parent's stadium: left to the
club lookup, "Jong AZ" lands at the AFAS Stadion in Alkmaar instead of the training complex at
Wijdewormer, and would be labelled exact. Either the calendar names a ground we recognise, or
the pin is drawn at town level.

### Kickoff times
3,532 of 5,873 fixtures (60%) have a kickoff time. The rest show **TBD** rather than a guessed
one, because TV selections land ~5 weeks out. German lists go further and publish a *weekend*
rather than a day until then, so those carry a `note` ("4–6 Dec") and sort to the end of their
first day rather than to midnight. This is the one field that genuinely churns, and the reason
the ingest re-runs rather than being a one-off import.

## Calendar files (the file-based leagues)
`build.py` merges `web/fixtures-static.json` into `web/matches.json`, which is the only data
file the app fetches. Run `calendars.py` first, then `build.py`; running `build.py` alone will
warn rather than quietly drop the calendar leagues off the map.

`python3 ingest/calendars.py <file> [file ...]` rebuilds `web/fixtures-static.json` **wholesale**,
so pass every calendar file each time, not just the new one. Each publisher has its own format;
`SOURCES` maps a filename fragment to a parser, and the longest matching fragment wins so a new
league whose name contains an existing one cannot quietly inherit the wrong country.

| Parser | Publishes | Gives |
|---|---|---|
| `fixturedl_csv` | fixturedownload.com | every field, whole season — the best case |
| `datasport_pdf` | datasport.it | ground and kickoff time per row |
| `voetbalkrant_ics` | voetbalkrant.com `.ics` | every field; one parser serves ten leagues |
| `anstoss_pdf` | anstosszeiten.de | ground always, time once the DFB fixes it |
| `spfl_pdf` / `dfl_pdf` / `legapro_csv` | federations | partial; see the docstrings |

### Two integrity gates
`drop_foreign_clubs` catches a file carrying fixtures from a league it does not claim to be
(Datasport's Serie D Girone E PDF ends with two pages of Serie C). `check_grounds` catches a
file naming the wrong *venue*: a club's real ground is the one it names most often across its
own home fixtures, so a ground belonging to a **different** club is wrong, while a sponsor
rename belongs to nobody else and is left alone. One or two bad rows are dropped individually;
past 15% the field itself is the problem and the whole file's venues are ignored.

| Feed | Venues naming another club's ground |
|---|---|
| Switzerland | **47 of 73 (64%)** — venue field ignored entirely, resolved by club |
| Turkey | 1 (Galatasaray at Başakşehir's ground) |
| Czechia | 1 (SK Artis Brno at Brno's ground) |
| the other seven | none |

Without this, two thirds of the Swiss league would be pinned in the wrong town and **labelled
exact** — worse than admitting we only know the city.

The script **refuses to write anything** if a single fixture ends up without a venue, rather
than publishing a partial league. Run `ingest/verify.py` afterwards: it land-checks both venue
tables, `web/venues.json` and the venues carried inline in `web/fixtures-static.json`.

### And three from the calendars
11. **A fixturedownload export named `-UTC` is not local time.** An English 3pm Saturday reads
   `14:00` through August and `15:00` from November — that gap is BST, not a schedule change.
   Taken literally, every fixture outside GMT lands an hour early. `fixturedl_csv` converts when
   the filename says UTC.
12. **A two-column PDF has to be read by coordinate, not by line.** In the 3. Liga list the
   kickoff sits in a gutter ~2pt above the club names, so any row-banding merges `19:00` into
   `SV Waldhof Mannheim`; and once the time reads `--:--` it drifts above, beside or below the
   names, so the *date* line delimits a match. Validate against arithmetic the file can't fake:
   380 matches, 38 matchdays of 10, 20 clubs with 19 home games each.
13. **Wikidata states some grounds twice,** a few hundred metres apart. Rounding coordinates and
   demanding one distinct point turns that into no answer at all; cluster instead.

## Map behaviour
- **Europe** (zoom < 4.9) — one bubble per country with a match count; click to zoom in.
  Bubbles ignore the distance slider, so zooming out always shows all of Europe.
- **Country** (zoom >= 4.9, or any country selected) — stadium pins sized by zoom.
  City names fade in past zoom 6.3 with overlap declutter. Zoom back out to return to the picker.
- The distance slider means "near me", so it applies only in the Europe view.
- **Collapse the panel** with the tab on the seam between panel and map, to explore the map
  on its own. The grid column is what animates, so the map really gains the width rather
  than having the panel float over it; on narrow screens the panel sits below, so it is the
  row that collapses instead.

### Province borders
`build-provinces.mjs` keeps only *internal* borders. It walks every province ring as a
set of undirected edges: an edge walked twice is shared by two provinces and is a real
internal border; an edge walked once is the edge of the country, which the outline layer
already draws, and an edge whose two owners sit in different countries is a national
border by another name. The survivors are stitched back into the longest runs possible
*before* simplifying — run Douglas-Peucker on two-point stubs and it has nothing to
remove. 45,716 internal edges become 1,616 lines, 390 KB.

Output is one feature per country, so the map can draw the country you picked at full
strength and let its neighbours sit back at 40%.

**"Province" means wildly different things by country**, so the level is chosen per
country rather than fixed. Germany has 16 states and Denmark 5 regions, but Italy has 110
provinces and the UK 232 counties — at country zoom those read as texture, not as places.
Past `MAX_UNITS` (40) the build falls back to the coarser tier Natural Earth carries in
`region`, and only where *every* unit has one: a partly filled field would dissolve some
borders and keep others, which is worse than either level. Dissolving is just a matter of
what counts as "the same place" — an edge between two provinces of one region stops being
a border and disappears.

| Country | Units | Drawn at |
|---|---|---|
| United Kingdom | 232 counties | 16 regions |
| Italy | 110 provinces | 20 regioni |
| France | 101 départements | 18 régions |
| Spain | 52 provinces | 19 autonomous communities |
| Turkey | 81 provinces | **81 provinces** — Natural Earth has no `region` for Turkey |
| everything else | 5–26 | as-is |

Turkey is the one case the rule wants to fix and can't; the build logs it rather than
leaving it to be noticed on the map. Grouping its 81 provinces needs a hand-written table,
which is worth doing only if it actually looks wrong once the Süper Lig feed is in.

### Traps worth remembering
1. **Never put a CSS `transform` or `transition: transform` on a MapLibre marker element.**
   MapLibre positions markers by writing `transform` inline; a transition makes every pin lag
   behind the map while panning. Wrap the marker in a plain `div` and style the child.
2. **MapLibre also writes an inline `opacity` on marker elements**, beating any stylesheet rule.
   Fade the child, not the marker element.
3. **Zoom-to-country must use mainland bounds.** Madeira and Shetland otherwise zoom a whole
   country out to nothing; `build-europe.mjs` ignores polygons under 2% of the largest.
4. **A decorative marker still eats clicks.** City labels have no click handler and their
   text sets `pointer-events:none`, but the marker element MapLibre wraps them in does not —
   and it is anchored at the venue, directly over the pin. Below `LABEL_ZOOM` the label is
   invisible, so the pin simply looked dead. Opt the *marker* out, not just its contents.
   This, not pin size, was why pins felt unclickable.
5. **Draw size and hit size are different numbers.** A 9px dot is honest about how precisely
   the venue is known; it is also far too small to hit. `--pz` sizes the dot, `--hit` sizes a
   transparent circle behind it (32px), so the target grew without the map getting heavier.
6. **`line-dasharray` is measured in multiples of `line-width`.** At 0.6px wide the dashes go
   sub-pixel and the line vanishes. Set the width first, then the pattern.
7. **A `zoom` expression must be the outermost `interpolate`.** MapLibre rejects
   `['*', zoomRamp, caseExpr]`; put the data-driven part inside each stop instead.
8. **Country names have to match the shapes.** `europe.json` says "Czechia"; call the country
   "Czech Republic" anywhere else and it silently cannot be selected, never highlights, and its
   venues skip the land check.
9. **A venue outside the map window has no land under it.** The Europe window stops at 30°N,
   which cuts the Canaries, so Tenerife and Las Palmas were drawn in open ocean.
   `build-europe.mjs` now keeps any polygon containing a venue we actually hold.
10. **MapLibre caches its container size.** Resize the container and the canvas keeps the old
   width, so the space just gained renders blank. Call `map.resize()` across the whole
   transition, not only at the end, or the map snaps into place at the finish.

## Adding a country

Venue coordinates come from Wikidata, and the query covers **every UEFA country** rather than
only the ones currently on the map - so a new league in a new country usually resolves to real
grounds the moment its calendar is added, with no venue work at all.

Refresh it from the **"Refresh venue data from Wikidata"** action on GitHub (run by hand; it
hits a free public endpoint about fifty times, so it is not on a schedule). It cannot run from
a sandboxed environment, because `query.wikidata.org` is not reachable from one.

Two things make that safe to re-run:

- **QIDs are never hardcoded.** The script asks Wikidata which item each ISO 3166-1 country
  code belongs to. A mistyped QID does not error - it silently returns a different country's
  clubs, and you find out when a pin appears in the wrong nation.
- **It refuses to shrink the data.** A throttled or timed-out endpoint returns fewer rows
  rather than an error, which would quietly demote known grounds to city-centre pins. If any
  country comes back more than 10% smaller than what is already held, nothing is written.

## Adding a league

Two things are needed: a published calendar, and a line in `SOURCES` in
`ingest/calendars.py` mapping a filename fragment to a parser, tier, country and country
QID. The longest matching fragment wins, so a new league whose name contains an existing
one cannot quietly inherit the wrong country.

Venues need no work: `data/wikidata-venues.json` covers **52 European countries**, so a
club in a country we have never drawn still resolves to its ground. If a country is ever
missing, run the **Refresh venue data from Wikidata** action (Actions tab, Run workflow)
— `ingest/wikidata-venues.py` resolves ISO codes to Wikidata items through P297 at run
time rather than trusting hand-copied QIDs, because a mistyped QID does not error, it
silently returns another country's stadiums.

That action is manual on purpose. Venues change about once a season and the public SPARQL
endpoint is a free shared service; there is nothing to gain from hitting it nightly.

That action rebuilds and verifies before it commits, so refreshed venues reach the live
map on its own.

Adding a *league* is different: run the full ingest — `calendars.py`, `build.py`,
`verify.py`, `build-site.sh` — and commit. The nightly job only refreshes the
feed-based leagues, so a new calendar-file league will not appear until you do.

## Publishing

The site is static: `web/` is the whole thing, and any static host will serve it as is.

**Attribution is an obligation, not decoration.** The town gazetteer is CC BY 4.0, so GeoNames
and the licence must be credited wherever the data is published. That credit is in the map's
attribution control and in full on `credits.html`. Natural Earth, openfootball and Wikidata are
public domain or CC0 and need no credit; they are named anyway so the map can say where every
number on it came from.

**The font is self-hosted on purpose.** Loading it from Google Fonts sends every visitor's IP
address to Google, which is a third-party disclosure that would need consent under GDPR and is
a render-blocking round trip besides. `fonts/SpaceGrotesk.woff2` is 49 kB and ships with its
OFL licence. With it in place **the page makes no third-party requests at all**, which is what
lets `privacy.html` say plainly that opening the map tells nobody else that you did.

Standing pages: `credits.html`, `privacy.html`, `terms.html`, `disclosure.html`, sharing
`page.css`. They carry `[your email]`-style placeholders that must be filled in before launch,
each marked with a yellow box on the page itself.

`disclosure.html` currently states that the site earns nothing, which is true. The affiliate
version is written and commented out in the same file. **Publish it the same day the first
affiliate link goes live, and update `privacy.html` at the same time** — affiliate links set
third-party cookies, and the privacy policy currently says the site sets none.

### Still open before ticket links

Section 166 of the Criminal Justice and Public Order Act 1994 makes it an offence for an
unauthorised person to sell, or offer or expose for sale, a ticket for a designated football
match; designation covers virtually all professional football in England and Wales, and the
Violent Crime Reduction Act 2006 extended it to sales over the internet. An affiliate link is
arguably an offer for sale, in the course of a business. This needs a legal opinion before any
ticket link points at an English or Welsh fixture. Scotland is outside s.166.

## Roadmap
1. **Lower leagues (the moat)** — continue down: National League, Regionalliga, Serie C Girone
   D, the rest of Serie D. No API covers these; federation sites, club
   pages and a "submit a match" form. Per-source licence review needed.
2. **Real basemap** — swap the style for tiles (MapTiler, Stadia, self-hosted Protomaps).
3. **Backend** — Postgres + PostGIS, nightly ingest, `ST_DWithin` for radius queries.
4. **Ticket affiliate links** as the first revenue path.
5. Next.js + SSR for SEO ("football near Florence this weekend"), saved teams, calendar export.

`ingest/football-data.mjs` is kept as an alternative source if you ever want live scores —
it reads `FOOTBALL_DATA_TOKEN` from the environment. No key is stored in this repo.
