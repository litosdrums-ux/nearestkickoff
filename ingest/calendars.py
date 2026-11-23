#!/usr/bin/env python3
"""Turn published league calendars into web/fixtures-static.json.

Leagues with no machine-readable feed publish a file instead, and every league
publishes a different one. Each format gets a parser here; everything downstream
(venue resolution, the refusal gate, the output shape) is shared.

    python3 ingest/calendars.py <file> [file ...]

Formats, by what they give us:
  legapro_csv    both legs per row, no ground, NO kickoff times
  datasport_pdf  one match per row WITH ground and kickoff time   <- best
  spfl_pdf       date heading, then time/home/away, ground on the next line
  dfl_pdf        matchday rows, mostly a 2-3 day RANGE and no time
  fixturedl_csv  fixturedownload.com export: all five fields, whole season   <- best
  voetbalkrant_ics  .ics feed: all five fields; one parser serves many leagues
  anstoss_pdf    two-column web print: ground always, time once the DFB fixes it

A file is a snapshot of its publication date; a later reschedule is invisible
until a fresh one arrives.
"""
import csv, json, re, sys, subprocess, unicodedata, datetime, pathlib, collections, html

HERE = pathlib.Path(__file__).resolve().parent
DATA, WEB = HERE.parent/'data', HERE.parent/'web'

# filename fragment (or any of several) -> parser, league, tier, country,
# Wikidata country QID. The longest matching fragment wins, so a new league whose
# name contains an existing one cannot quietly inherit the wrong country.
SOURCES = [
    ('calendario_ca',  'legapro_csv',   None,                    3, 'Italy',    'Q38'),
    ('calendario_cb',  'legapro_csv',   None,                    3, 'Italy',    'Q38'),
    ('calendario_cc',  'legapro_csv',   None,                    3, 'Italy',    'Q38'),
    ('girone-b',       'datasport_pdf', 'Serie C, Girone B',     3, 'Italy',    'Q38'),
    # Datasport publishes these at
    # https://www.datasport.it/pdf/calendari/calendario-serie-<x>2026-2027.pdf
    ('serie-b2026',    'datasport_pdf', 'Serie B',               2, 'Italy',    'Q38'),
    ('serie-d-girone-d','datasport_pdf','Serie D, Girone D',     4, 'Italy',    'Q38'),
    ('serie-d-girone-e','datasport_pdf','Serie D, Girone E',     4, 'Italy',    'Q38'),
    ('spfl',           'spfl_pdf',      'Scottish Premiership',  1, 'Scotland', 'Q145'),
    ('bundesliga-2',   'dfl_pdf',       '2. Bundesliga',         2, 'Germany',  'Q183'),
    # anstosszeiten.de carries the whole 3. Liga season on one page, at
    # https://anstosszeiten.de/3-liga/spielplan/ - print it to PDF
    (('3._liga', '3-liga', '3. liga'),
                       'anstoss_pdf',   '3. Liga',               3, 'Germany',  'Q183'),
    # fixturedownload.com - a real file, every field, whole season
    ('league-one',     'fixturedl_csv', 'League One',            3, 'England',  'Q145'),
    ('league-two',     'fixturedl_csv', 'League Two',            4, 'England',  'Q145'),
    # voetbalkrant .ics feeds. The link downloads as competition_<id>_nl.ics, but a
    # browser that names the file after the link text saves it under the league name,
    # so both spellings are listed for the ones we have actually seen. A feed saved
    # under an unlisted name fails loudly as UNKNOWN rather than being mislabelled -
    # add the spelling here rather than guessing it in advance.
    # The feed is a rolling window - about a month back plus everything the league has
    # published forward - so re-download periodically; a feed pulled in March carries
    # fixtures it does not carry today.
    (('competition_1_', 'jupiler-pro-league'),
              'voetbalkrant_ics', 'Belgian Pro League',  1, 'Belgium',        'Q31'),
    (('competition_20_', 'super-lig'),
              'voetbalkrant_ics', 'Super Lig',           1, 'Turkey',      'Q43'),
    (('competition_24_', 't-mobile-bundesliga'),
              'voetbalkrant_ics', 'Austrian Bundesliga', 1, 'Austria',     'Q40'),
    (('competition_25_', 'eerste-divisie'),
              'voetbalkrant_ics', 'Eerste Divisie',      2, 'Netherlands',    'Q55'),
    (('competition_79_', 'superliga'),
              'voetbalkrant_ics', 'Superliga',           1, 'Denmark',     'Q35'),
    (('competition_148_', 'ligue-2'),
              'voetbalkrant_ics', 'Ligue 2',             2, 'France',         'Q142'),
    (('competition_154_', 'super-league'),
              'voetbalkrant_ics', 'Super League',        1, 'Greece',      'Q41'),
    (('competition_155_', 'first-league'),
              # 'Czechia', not 'Czech Republic': the country name has to match the one
              # in europe.json, or the country cannot be selected and never highlights
              'voetbalkrant_ics', 'Chance Liga',  1, 'Czechia',        'Q213'),
    (('competition_160_', 'segunda-division'),
              'voetbalkrant_ics', 'Segunda Division',    2, 'Spain',       'Q29'),
    (('competition_213_', 'super-league-switzerland'),
              'voetbalkrant_ics', 'Swiss Super League',  1, 'Switzerland', 'Q39'),
    # IDs 10 (Championship), 23 (Scottish Premiership) and 75 (Serie B) exist too, but
    # we already carry those from fuller sources - adding them would duplicate.
]

def source_for(name):
    """The source whose filename fragment matches longest, so 'super-league' cannot
    claim a file that is really 'super-league-zwitserland'."""
    best = None
    for src in SOURCES:
        frags = src[0] if isinstance(src[0], tuple) else (src[0],)
        for f in frags:
            if f in name and (best is None or len(f) > best[0]):
                best = (len(f), src)
    return best[1] if best else None
GIRONE = {'CA': 'Serie C, Girone A', 'CB': 'Serie C, Girone B', 'CC': 'Serie C, Girone C'}

# Clubs Wikidata has no usable home venue for: town only, drawn as approximate.
CITY_FALLBACK = {
    'ALTAMURA': 'Altamura', 'AUDACE CERIGNOLA': 'Cerignola', 'SCAFATESE': 'Scafati',
    'INTER U23': 'Sesto San Giovanni', 'RENATE': 'Renate', 'DOLOMITI BELLUNESI': 'Belluno',
    'DESENZANO': 'Desenzano del Garda', 'OSPITALETTO FRANCIACORTA': 'Ospitaletto',
    'FOLGORE CARATESE': 'Carate Brianza', 'OSTIAMARE': 'Lido di Ostia',
    'PIANESE': 'Piancastagnaio', 'ATALANTA U23': 'Caravaggio',
    # Serie B
    'CARRARESE': 'Carrara',
    # Serie D Girone E - several play in a frazione, so the town is the comune
    'RONDINELLA MARZOCCO': 'Florence', 'GRASSINA': 'Bagno a Ripoli',
    'GHIVIBORGO VDS': 'Coreglia Antelminelli', 'SASSO MARCONI': 'Sasso Marconi',
    'FLAMINIA CIVITACASTELLANA': 'Civita Castellana',
    # Reserve sides: their grounds are training complexes Wikidata has no venue for,
    # and the .ics feed leaves LOCATION empty for the later rounds, so these are the
    # towns the pin falls back to.
    'JONG AJAX': 'Duivendrecht', 'JONG PSV': 'Eindhoven',
    'JONG AZ': 'Wijdewormer', 'JONG FC UTRECHT': 'Utrecht',
    # Amedspor's ground is not in Wikidata; the only Diyarbakir entry is a different,
    # defunct club at a different stadium, so the town is as precise as we can honestly be
    'AMED SK': 'Diyarbakır',
}
# club name does not carry its town
TOWN = {
    'CASERTANA': 'Caserta', 'SALERNITANA': 'Salerno', 'CAVESE': "Cava de' Tirreni",
    'SAVOIA': 'Torre Annunziata', 'AUDACE CERIGNOLA': 'Cerignola',
    'GIUGLIANO': 'Giugliano in Campania', 'GIANA ERMINIO': 'Gorgonzola',
    'PERGOLETTESE': 'Crema', 'JUVENTUS NEXT GEN': 'Alessandria',
    'ALCIONE MILANO': 'Sesto San Giovanni', 'ALBINOLEFFE': 'Bergamo',
    'PICERNO': 'Potenza', 'REGGIANA': "Reggio nell'Emilia",
    'SAMBENEDETTESE': 'San Benedetto del Tronto', 'SPEZIA': 'La Spezia', 'TORRES': 'Sassari',
    # Scotland
    'CELTIC': 'Glasgow', 'RANGERS': 'Glasgow', 'HIBERNIAN': 'Edinburgh',
    'HEART OF MIDLOTHIAN': 'Edinburgh', 'ST. MIRREN': 'Paisley',
    'ST JOHNSTONE': 'Perth', 'ST. JOHNSTONE': 'Perth',
    # Germany
    'HERTHA BSC': 'Berlin', 'FC ST. PAULI': 'Hamburg', '1. FC NURNBERG': 'Nuremberg',
    '1. FC NÜRNBERG': 'Nuremberg', 'KARLSRUHER SC': 'Karlsruhe',
}
# Wikidata's label shares no word with the name the calendar uses
WD_NAME = {'ARZIGNANO VALCHIAMPO': 'Union ArzignanoChiampo',
           'AGF': 'Aarhus Gymnastikforening', 'AGF AARHUS': 'Aarhus Gymnastikforening',
           # voetbalkrant writes club names in Dutch, Wikidata in English
           'AEK ATHENE': 'AEK Athens F.C.', 'OFI KRETA': 'OFI Crete F.C.',
           'IRAKLIS': "G.S. Iraklis Thessalonikis (men's association football)",
           'SPARTA PRAAG': 'AC Sparta Prague', 'SLAVIA PRAAG': 'SK Slavia Prague',
           'JABLONEC 97': 'FK Jablonec', 'GRASSHOPPERS': 'Grasshopper Club Zurich',
           'SANKT GALLEN': 'FC St. Gallen', 'FC KOPENHAGEN': 'F.C. Copenhagen',
           'AARHUS GF': 'Aarhus Gymnastikforening', 'REAL MALLORCA': 'RCD Mallorca'}

# A club whose ground is in a different country from the league it plays in, so the
# country-gated city lookup would never find its town.
# Grounds checked by hand against a named public source - see ingest/verified-venues.json,
# which carries the source for each one. Checked before any other venue source.
VERIFIED = {}
for _v in json.load(open(HERE/'verified-venues.json', encoding='utf-8'))['venues']:
    _rec = dict(stadium=_v['stadium'], city=_v['city'], lat=_v['lat'], lon=_v['lon'],
                precision='stadium')
    if _v.get('venue_country'):
        _rec['venue_country'] = _v['venue_country']
    for _n in _v['clubs']:
        VERIFIED[_n.upper()] = _rec

TOWN_ABROAD = {}
# Calendars print the sponsor's name for a ground; Wikidata keeps the plain one.
GROUND_NAME = {'ST. MIRREN': 'St. Mirren Park'}

# A feed that names a reserve side after its parent club: left alone, "Utrecht" in the
# Eerste Divisie is drawn at FC Utrecht's Galgenwaard and reads as the Eredivisie club.
CLUB_RENAME = {('Eerste Divisie', 'Utrecht'): 'Jong FC Utrecht'}

DROP = {'fc','afc','cf','sc','ac','as','ssc','us','ud','rc','cd','sd','club','de','calcio','bk',
        'sv','tsv','vfl','vfb','fsv','bsc','vv','cp','sl','rcd','ca','bc','cfc','the','ssd',
        'asd','usd','pol','spvgg','dsc','sg','1','04','05','09','96','98','1846','1848','1909','1913'}
VENUE_WORDS = {'stadio','stadium','comunale','nuovo','nuova','arena','campo','impianto',
               'sportivo','centro','park','stadion'}

# Characters NFKD does not decompose, so stripping accents deletes them outright:
# "Kasımpaşa" would reduce to "kasmpasa" and "Brøndby" to "brndby", and neither
# would ever match. Map them to their Latin equivalents first.
TRANSLIT = str.maketrans({'\u0131':'i','\u0130':'i','\u00f8':'o','\u00d8':'o','\u00e6':'ae','\u00c6':'ae',
                          '\u0153':'oe','\u0152':'oe','\u00df':'ss','\u0142':'l','\u0141':'l','\u0111':'d',
                          '\u0110':'d','\u00f0':'d','\u00fe':'th','\u00e5':'a','\u00c5':'a'})

def norm(s):
    s = unicodedata.normalize('NFKD', s.translate(TRANSLIT)).encode('ascii','ignore').decode().lower().replace('.', '')
    return ' '.join(w for w in re.sub(r'[^a-z0-9 ]', ' ', s).split() if w not in DROP)

def vnorm(s):
    return ' '.join(w for w in norm(s).split() if w not in VENUE_WORDS)

def same_ground(a, b):
    """Subset, not equality, because a calendar writes "Stade Maurice Dufrasne
    (Sclessin)" where Wikidata writes "Stade Maurice Dufrasne". But a single
    surviving word must match outright: strip the venue words from "AFAS Stadion"
    and "AFAS Trainingscomplex" and the first is a subset of the second, which
    would pin AZ's reserves at the first team's ground."""
    x, y = set(vnorm(a).split()), set(vnorm(b).split())
    if not (x and y):
        return False
    if x == y:
        return True
    return min(len(x), len(y)) >= 2 and (x <= y or y <= x)

def one_place(cands, metres=400):
    """Wikidata often states the same ground twice with coordinates a stone's throw
    apart - SG Sonnenhof Großaspach's two rows sit 130m apart, which rounding to 3dp
    turns into two different places and so into no answer at all. Returns a single
    candidate when they all describe one spot."""
    if not cands:
        return None
    import math
    la, lo = cands[0]['lat'], cands[0]['lon']
    for v in cands[1:]:
        dy = (v['lat'] - la) * 111_320
        dx = (v['lon'] - lo) * 111_320 * math.cos(math.radians(la))
        if math.hypot(dx, dy) > metres:
            return None
    return cands[0]

# A reserve side is its own club playing its own ground, so it must never fall through
# to the parent's stadium: "Jong AZ" would land at the AFAS Stadion in Alkmaar instead
# of the training complex at Wijdewormer, and be labelled exact. Either the calendar
# names a ground we recognise, or the pin is drawn at town level.
RESERVE = re.compile(r'(^|\s)jong(\s|$)|\sii$|\su\d\d$|next gen|amateure?s?$')

ALL_WD = json.load(open(DATA/'wikidata-venues.json', encoding='utf-8'))
CITIES = collections.defaultdict(dict)
for c in json.load(open(DATA/'cities-eu.json', encoding='utf-8')):
    CITIES[c['c']].setdefault(norm(c['n']), c)
ISO_OF = {'Q38':'IT','Q145':'GB','Q183':'DE','Q29':'ES','Q142':'FR','Q55':'NL','Q45':'PT',
          'Q31':'BE','Q40':'AT','Q39':'CH','Q41':'GR','Q43':'TR','Q35':'DK','Q213':'CZ'}

def city_for(team, iso):
    if team.upper() in TOWN: return TOWN[team.upper()]
    if team.upper() in CITY_FALLBACK: return CITY_FALLBACK[team.upper()]
    for w in norm(team).split():
        if w in CITIES[iso]: return CITIES[iso][w]['n']
    return None

def resolve(team, ground, qid, country):
    """A calendar that names the ground beats Wikidata's home-venue link, which lags."""
    v = VERIFIED.get(team.upper())
    if v:                       # hand-checked against a named source; beats everything
        return dict(v)          # caller supplies league/country
    iso = ISO_OF.get(qid, 'IT')
    wd = [v for v in ALL_WD if v['countryQid'] == qid]
    ground = GROUND_NAME.get(team.upper(), ground)
    matched = False
    if ground:
        g = [v for v in wd if same_ground(v['stadium'], ground)]
        matched = bool(g)
        hit = one_place(g)
        if hit:
            return dict(stadium=hit['stadium'], city=city_for(team, iso) or hit['stadium'],
                        lat=hit['lat'], lon=hit['lon'], precision='stadium')
    if RESERVE.search(norm(team)):
        cand = []
    else:
        cand = None
    idx = collections.defaultdict(list)
    for v in wd: idx[norm(v['club'])].append(v)
    if cand is None:
        k = norm(WD_NAME.get(team.upper(), team))
        cand = idx.get(k, [])
        if not cand:
            tk = set(k.split())
            cand = [v for ck, vs in idx.items() if ck and
                    (set(ck.split()) <= tk or tk <= set(ck.split())) for v in vs]
    v = one_place(cand)
    # Only let a named ground veto the club's stored venue when that ground is one we
    # recognise. An unrecognised name is usually a sponsor title ("The Marbill Coaches
    # Stadium" for St. Mirren Park), which is no evidence the club moved.
    if v and not (matched and not same_ground(v['stadium'], ground)):
        return dict(stadium=v['stadium'], city=city_for(team, iso) or v['stadium'],
                    lat=v['lat'], lon=v['lon'], precision='stadium')
    abroad = TOWN_ABROAD.get(team.upper())
    town = abroad[0] if abroad else (CITY_FALLBACK.get(team.upper()) or city_for(team, iso))
    c = CITIES[abroad[1] if abroad else iso].get(norm(town)) if town else None
    if c:
        return dict(stadium=ground or town, city=town, lat=c['lat'], lon=c['lon'],
                    precision='city')
    return None

# ---------------- parsers: each yields home, away, date, time, ground, dateNote ----------
def legapro_csv(path, meta):
    for r in csv.DictReader(open(path, encoding='utf-8-sig')):
        league = GIRONE.get(r['Serie'].strip(), meta[2])
        h, a = r['SquadraCasa'].strip(), r['SquadraFuori'].strip()
        for home, away, d in ((h, a, r['DataAndata']), (a, h, r['DataRitorno'])):
            iso = datetime.datetime.strptime(d.strip(), '%d.%m.%Y').date().isoformat()
            yield dict(home=home, away=away, date=iso, time=None, ground=None,
                       note=None, league=league)

IT_MONTH = {'gen':1,'feb':2,'mar':3,'apr':4,'mag':5,'giu':6,
            'lug':7,'ago':8,'set':9,'ott':10,'nov':11,'dic':12}
DATASPORT = re.compile(r'^(.+?)\s{2,}(?:\d+-\d+|-)\s{2,}(.+?)\s{2,}(.+?)\s{2,}'
                       r'(\d{1,2})\s+([A-Za-z]{3})\s+h\.(\d{2}:\d{2})$')

def text_of(path):
    return subprocess.run(['pdftotext', '-layout', str(path), '-'],
                          capture_output=True, text=True, check=True).stdout

def datasport_pdf(path, meta, season=2026):
    for line in text_of(path).split('\n'):
        m = DATASPORT.match(line.strip())
        if not m: continue
        home, away, ground, day, mon, ko = m.groups()
        mi = IT_MONTH.get(mon.lower())
        if not mi: continue
        y = season if mi >= 7 else season + 1
        yield dict(home=home.strip(), away=away.strip(), ground=ground.strip(),
                   date=datetime.date(y, mi, int(day)).isoformat(), time=ko,
                   note=None, league=meta[2])

SPFL_DATE = re.compile(r'^\s*(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day\s+'
                       r'(\d{1,2})\s+([A-Z][a-z]+)\s+(\d{4})\s*$')
SPFL_ROW = re.compile(r'^\s*(\d{2}:\d{2})\s+(.+?)\s+v\s+(.+?)\s*$')

def spfl_pdf(path, meta):
    lines = text_of(path).split('\n')
    cur = None
    for i, l in enumerate(lines):
        d = SPFL_DATE.match(l)
        if d:
            day, mon, yr = d.groups()
            cur = datetime.datetime.strptime(f'{day} {mon} {yr}', '%d %B %Y').date()
            continue
        m = SPFL_ROW.match(l)
        if not (m and cur): continue
        ground = ''
        for nxt in lines[i+1:i+4]:
            t = nxt.strip()
            if t and not SPFL_ROW.match(nxt) and not SPFL_DATE.match(nxt):
                # page breaks drop a footer where the ground should be
                if 'http' in t.lower() or re.fullmatch(r'[\d/\s]+', t):
                    continue
                ground = t; break
        yield dict(home=m.group(2).strip(), away=m.group(3).strip(), ground=ground or None,
                   date=cur.isoformat(), time=m.group(1), note=None, league=meta[2])

DFL_ROW = re.compile(r'^\s*([\d./\-]+\.\d{4})\s+(?:(\d{2}:\d{2})\s+)?(\S+)\s+(\d+)\s+'
                     r'(.+?)\s{2,}(.+?)\s*$')
MONTHS_EN = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

def dfl_date(s):
    """German fixture lists publish a weekend, not a day, until broadcasters pick slots.
    Returns (first day, label) - the label is None only when the date is exact."""
    year = int(s[-4:])
    body = s[:-5].rstrip('.')
    nums = re.findall(r'\d{1,2}', body)
    if re.fullmatch(r'\d{1,2}\.\d{1,2}', body):                     # 07.08
        d, mth = int(nums[0]), int(nums[1])
        return datetime.date(year, mth, d), None
    if re.fullmatch(r'\d{1,2}\.\d{1,2}\.-\d{1,2}\.\d{1,2}', body):  # 30.10.-01.11
        d1, m1, d2, m2 = map(int, nums)
        a, b = datetime.date(year, m1, d1), datetime.date(year, m2, d2)
    else:                                                            # 04.-06.09 | 08./09.08
        mth = int(nums[-1])
        a = datetime.date(year, mth, int(nums[0]))
        b = datetime.date(year, mth, int(nums[-2]))
    label = (f'{a.day}' if a.month == b.month else f'{a.day} {MONTHS_EN[a.month-1]}') + \
            f'–{b.day} {MONTHS_EN[b.month-1]}'
    return a, label

def dfl_pdf(path, meta):
    for line in text_of(path).split('\n'):
        m = DFL_ROW.match(line)
        if not m: continue
        date, ko, md, _seq, home, away = m.groups()
        if not md.isdigit(): continue
        try:
            day, label = dfl_date(date)
        except Exception:
            continue
        yield dict(home=home.strip(), away=away.strip(), ground=None,
                   date=day.isoformat(), time=ko, note=label, league=meta[2])

ANS_SPLIT, ANS_YTOL, ANS_XGAP = 310.0, 1.5, 20.0
ANS_MD    = re.compile(r'^(\d{1,2})\.\s*Spieltag\s*·')   # its year often wraps away
ANS_TIME  = re.compile(r'^(?:(\d{1,2}):(\d{2})|--:--)$')
ANS_WHEN  = re.compile(r'^\D*?,\s*([\d.\-/]*\d{1,2}\.\d[\d.\-/]*)\s*·\s*(.+)$')
ANS_NOISE = re.compile(r'^(Uhr|Termin offen|ANZEIGE|Details\s*→?|[\d\s]+|\d+/\d+|·|→)$')
ANS_JUNK  = re.compile(r'anstosszeiten|Spielplan|Spieltage|^\d{1,2}/\d{1,2}/\d{2},'
                       r'|Bundesliga:|Startseite')

def anstoss_lines(path):
    """Geometry, not line order, is what makes this file readable.

    Every match sits wholly inside one of two columns, so the page is split at a fixed
    x before anything else. Inside a column the kickoff time sits in a narrow gutter to
    the LEFT of the club names and only ~2pt higher, so banding rows by height alone
    merges "19:00" into "SV Waldhof Mannheim"; lines are therefore cut on horizontal
    gaps as well. Yields (page, column, top, x, text)."""
    import pdfplumber, logging
    logging.getLogger('pdfminer').setLevel(logging.ERROR)
    out = []
    with pdfplumber.open(path) as pdf:
        for pno, page in enumerate(pdf.pages):
            words = page.extract_words()
            for col in (0, 1):
                ws = sorted((w for w in words if (w['x0'] < ANS_SPLIT) == (col == 0)),
                            key=lambda w: (w['top'], w['x0']))
                lines = []
                for w in ws:
                    if lines and abs(w['top'] - lines[-1][0]['top']) <= ANS_YTOL:
                        lines[-1].append(w)
                    else:
                        lines.append([w])
                for ln in lines:
                    ln.sort(key=lambda w: w['x0'])   # gathered in (top, x0) order
                    seg = [ln[0]]
                    for w in ln[1:]:
                        if w['x0'] - seg[-1]['x1'] > ANS_XGAP:
                            out.append((pno, col, seg[0]['top'], seg[0]['x0'],
                                        ' '.join(x['text'] for x in seg)))
                            seg = [w]
                        else:
                            seg.append(w)
                    out.append((pno, col, seg[0]['top'], seg[0]['x0'],
                                ' '.join(x['text'] for x in seg)))
    return out

def anstoss_pdf(path, meta, season=2026):
    """Until the DFB fixes a kickoff the time reads "--:--" and drifts above, beside or
    below the two club names, so the date line - which every match has, and always last
    - delimits a match rather than the time."""
    recs = anstoss_lines(path)
    heads = sorted((pg, y, ANS_MD.match(t).group(1))
                   for pg, c, y, x, t in recs if ANS_MD.match(t))
    def matchday(page, y):
        cur = None
        for hp, hy, n in heads:
            if (hp, hy) <= (page, y): cur = n
            else: break
        return cur
    unread = 0
    for col in (0, 1):
        stream = sorted((r for r in recs if r[1] == col), key=lambda r: (r[0], r[2], r[3]))
        buf, cur = [], None
        for page, _c, y, _x, t in stream:
            t = t.strip()
            if not t or ANS_NOISE.match(t) or ANS_JUNK.search(t) or ANS_MD.match(t):
                continue
            # The blurb at the top of page one spills into both columns and would read
            # as club names. Only one column ever sees the matchday headings, so place
            # each record against the headings instead of watching for them go past.
            day_no = matchday(page, y)
            if day_no is None:
                continue
            if day_no != cur:
                buf, cur = [], day_no
            m = ANS_WHEN.match(t)
            if not m:
                buf.append(t); continue
            teams = [x for x in buf if not ANS_TIME.match(x)]
            times = [x for x in buf if ANS_TIME.match(x)]
            buf = []
            if len(teams) != 2 or len(times) > 1:
                unread += 1; continue
            body = m.group(1).rstrip('.')
            mon = int(re.findall(r'\d{1,2}', body)[-1])
            try:
                day, label = dfl_date(f'{body}.{season if mon >= 7 else season + 1}')
            except Exception:
                unread += 1; continue
            kt = ANS_TIME.match(times[0]) if times else None
            yield dict(home=teams[0], away=teams[1], ground=m.group(2).strip(),
                       date=day.isoformat(),
                       time=f'{int(kt.group(1)):02d}:{kt.group(2)}'
                            if kt and kt.group(1) else None,
                       note=label, league=meta[2])
    if unread:
        print(f'  WARNING: {unread} match blocks in {pathlib.Path(path).name} unreadable')

TZ = {'Belgium': 'Europe/Brussels', 'Netherlands': 'Europe/Amsterdam',
      'Turkey': 'Europe/Istanbul', 'Greece': 'Europe/Athens', 'Denmark': 'Europe/Copenhagen',
      'Czechia': 'Europe/Prague', 'Spain': 'Europe/Madrid',
      'France': 'Europe/Paris', 'Austria': 'Europe/Vienna', 'Switzerland': 'Europe/Zurich',
      'England': 'Europe/London', 'Scotland': 'Europe/London', 'Germany': 'Europe/Berlin',
      'Italy': 'Europe/Rome'}

def fixturedl_csv(path, meta):
    """fixturedownload.com: Round Number, Date, Location, Home Team, Away Team, Result.

    The site offers the same season in several timezones and names the file after the
    one chosen. A -UTC export is NOT local time: an English 3pm Saturday reads 14:00
    through August and 15:00 from November, so taking it literally would put every
    fixture outside GMT an hour early."""
    from zoneinfo import ZoneInfo
    utc = 'utc' in pathlib.Path(path).name.lower()
    zone = ZoneInfo(TZ.get(meta[4], 'Europe/London'))
    for r in csv.DictReader(open(path, encoding='utf-8-sig')):
        raw = (r.get('Date') or '').strip()
        if not raw: continue
        try:
            dt = datetime.datetime.strptime(raw, '%d/%m/%Y %H:%M')
        except ValueError:
            try: dt = datetime.datetime.strptime(raw, '%d/%m/%Y %H:%M:%S')
            except ValueError: continue
        if utc:
            dt = dt.replace(tzinfo=datetime.timezone.utc).astimezone(zone)
        yield dict(home=(r.get('Home Team') or '').strip(),
                   away=(r.get('Away Team') or '').strip(),
                   ground=(r.get('Location') or '').strip() or None,
                   date=dt.date().isoformat(), time=dt.strftime('%H:%M'),
                   note=None, league=meta[2])

ICS_SCORE = re.compile(r':\s*\d+\s*-\s*\d+\s*$')

def ics_text(v):
    """ICS escapes commas and semicolons with a backslash; unescape before splitting,
    or a venue comes back as "Jan Breydelstadion\\"."""
    v = (v.replace('\\n', '\n').replace('\\N', '\n')
            .replace('\\,', ',').replace('\\;', ';').replace('\\\\', '\\'))
    # Some of these feeds serve UTF-8 that was decoded as Latin-1 somewhere upstream,
    # so Brondby arrives as "BrÃ¸ndby". Round-tripping repairs it; text that was
    # never mangled either fails to encode or fails to decode, and is handed back as is.
    try:
        v = v.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    # and HTML entities, which some rows escape twice: "Ismetpa&amp;#351;a"
    prev = None
    while prev != v:
        prev, v = v, html.unescape(v)
    return v

def voetbalkrant_ics(path, meta):
    """An .ics feed. SUMMARY is "Home - Away" with ": 3-0" appended once played, so the
    score is stripped first. DTSTART ending in Z is UTC and converted to league time."""
    from zoneinfo import ZoneInfo
    zone = ZoneInfo(TZ.get(meta[4], 'Europe/Brussels'))
    raw = open(path, encoding='utf-8', errors='replace').read().replace('\r\n', '\n')
    raw = re.sub(r'\n[ \t]', '', raw)          # unfold continuation lines
    for block in raw.split('BEGIN:VEVENT')[1:]:
        block = block.split('END:VEVENT')[0]
        f = {}
        for line in block.split('\n'):
            if ':' not in line: continue
            k, v = line.split(':', 1)
            f[k.split(';')[0].strip().upper()] = v.strip()
        start, summary = f.get('DTSTART', ''), f.get('SUMMARY', '')
        if not (start and summary): continue
        summary = ICS_SCORE.sub('', ics_text(summary)).strip()
        parts = summary.split(' - ')
        if len(parts) != 2:                      # a club name containing " - " is ambiguous
            continue
        try:
            if start.endswith('Z'):
                dt = datetime.datetime.strptime(start, '%Y%m%dT%H%M%SZ') \
                        .replace(tzinfo=datetime.timezone.utc).astimezone(zone)
            elif 'T' in start:
                dt = datetime.datetime.strptime(start[:15], '%Y%m%dT%H%M%S')
            else:
                dt = datetime.datetime.strptime(start[:8], '%Y%m%d')
        except ValueError:
            continue
        has_time = 'T' in start
        yield dict(home=parts[0].strip(), away=parts[1].strip(),
                   ground=ics_text(f.get('LOCATION') or '').split(',')[0].strip() or None,
                   date=dt.date().isoformat(),
                   time=dt.strftime('%H:%M') if has_time else None,
                   note=None, league=meta[2])

PARSERS = {'legapro_csv': legapro_csv, 'datasport_pdf': datasport_pdf,
           'spfl_pdf': spfl_pdf, 'dfl_pdf': dfl_pdf, 'anstoss_pdf': anstoss_pdf,
           'fixturedl_csv': fixturedl_csv, 'voetbalkrant_ics': voetbalkrant_ics}

def drop_foreign_clubs(rows, floor=0.4):
    """A club in a league plays every round, so its appearances land in a tight band.
    A club appearing a handful of times is contamination - Datasport's Serie D Girone E
    file carries two pages of Serie C Girone C fixtures under a Serie D heading, and
    without this they enter silently under the wrong league."""
    if len(rows) < 40:
        return rows, {}
    seen = collections.Counter()
    for r in rows:
        seen[r['home']] += 1; seen[r['away']] += 1
    # Not the median: in the Serie D Girone E file 20 intruding clubs outnumber the 18
    # real ones, so the median IS the contamination. A club that plays every round sits
    # at the top of the distribution, so compare against that instead.
    counts = sorted(seen.values())
    full_season = counts[int(len(counts) * 0.9)]
    strays = {c for c, n in seen.items() if n < full_season * floor}
    if not strays:
        return rows, {}
    kept = [r for r in rows if r['home'] not in strays and r['away'] not in strays]
    dropped = collections.Counter()
    for r in rows:
        if r['home'] in strays or r['away'] in strays:
            dropped[r['home'] if r['home'] in strays else r['away']] += 1
    return kept, dropped

def check_grounds(rows):
    """Some feeds name the wrong ground, and a wrong ground that Wikidata recognises
    beats the club lookup and gets labelled exact - a confident pin in the wrong town.

    A club's real ground is the one it names most often across its own home fixtures.
    Measured against that, a suspect ground is one belonging to a DIFFERENT club; a
    sponsor rename ("SAS Arena" for "MCH Arena") belongs to nobody else and is left
    alone, because resolve() already copes with a name Wikidata does not know.

    Past a threshold the field itself is the problem rather than a few rows of it:
    voetbalkrant's Swiss list puts 47 of 73 fixtures at another club's stadium, often
    the away side's, so there the venue is dropped wholesale and every Swiss fixture
    resolved from the club instead."""
    named = [r for r in rows if r.get('ground')]
    if len(named) < 20:
        return rows, None
    byhome = collections.defaultdict(collections.Counter)
    for r in named:
        byhome[r['home']][r['ground']] += 1
    modal = {c: g.most_common(1)[0][0] for c, g in byhome.items()}
    owners = collections.defaultdict(set)
    for c, g in modal.items():
        owners[g].add(c)
    # a ground two clubs share (Cercle and Club Brugge at Jan Breydel) is owned by both
    foreign = [r for r in named if r['ground'] != modal.get(r['home'])
               and owners.get(r['ground']) and r['home'] not in owners[r['ground']]]
    if not foreign:
        return rows, None
    share = len(foreign) / len(named)
    if share > .15:
        for r in rows:
            r['ground'] = None
        return rows, (f'{len(foreign)} of {len(named)} venues belong to another club '
                      f'({share:.0%}) - venue field ignored, resolving by club')
    eg = foreign[0]
    owner = sorted(owners[eg['ground']])[0]
    for r in foreign:
        r['ground'] = None
    return rows, (f"{len(foreign)} fixture(s) named another club's ground, resolved by "
                  f"club instead (e.g. {eg['home']} at {owner}'s)")

def main(paths):
    # Writing is wholesale, so an empty argument list would silently truncate the file
    # to []. That is never what anyone meant; it only ever means the shell glob missed.
    if not paths:
        print('no calendar files given - pass every one, since this rebuilds wholesale')
        return 1
    out, unresolved = [], collections.Counter()
    today = datetime.date.today().isoformat()
    for p in paths:
        name = pathlib.Path(p).name.lower()
        meta = source_for(name)
        if not meta:
            print(f'  {pathlib.Path(p).name}: UNKNOWN source, add it to SOURCES')
            return 1
        kind, _, _, tier, country, qid = meta[1], *meta[1:]
        rows = list(PARSERS[meta[1]](p, meta))
        rows, strays = drop_foreign_clubs(rows)
        if strays:
            print(f'  {pathlib.Path(p).name[:46]}: dropped {sum(strays.values())} rows for '
                  f'clubs not in this competition: {", ".join(list(strays)[:4])}')
        rows, note = check_grounds(rows)
        if note:
            print(f'  {pathlib.Path(p).name[:46]}: {note}')
        kept = 0
        for r in rows:
            if r['date'] < today: continue
            for side in ('home', 'away'):
                r[side] = CLUB_RENAME.get((r['league'], r[side]), r[side])
            v = resolve(r['home'], r.get('ground'), qid, country)
            if not v:
                unresolved[f"{r['home']} ({country})"] += 1; continue
            out.append(dict(sid=norm(r['home']), home=r['home'], away=r['away'],
                            date=r['date'], time=r['time'], note=r['note'],
                            league=r['league'], tier=tier, country=country, **v))
            kept += 1
        timed = sum(1 for r in rows if r['time'])
        ranged = sum(1 for r in rows if r['note'])
        print(f"  {pathlib.Path(p).name[:46]:48} {len(rows):4} rows, {kept:4} upcoming"
              f"{f', {timed} timed' if timed else ', no kickoff times'}"
              f"{f', {ranged} date not fixed' if ranged else ''}")
    if unresolved:
        print(f"\n  REFUSED: {sum(unresolved.values())} fixtures have no venue, nothing written")
        for c, n in unresolved.most_common(): print(f"    {c}: {n}")
        return 1
    # Sources overlap (a league can appear in both an .ics feed and a federation PDF),
    # so drop a fixture we already hold rather than showing it twice on the map.
    seen, deduped, dupes = set(), [], 0
    for m in out:
        key = (m['date'], norm(m['home']), norm(m['away']))
        if key in seen:
            dupes += 1; continue
        seen.add(key); deduped.append(m)
    if dupes:
        print(f'  {dupes} duplicate fixtures dropped (same day, same two clubs)')
    out = deduped
    (WEB/'fixtures-static.json').write_text(json.dumps(out, ensure_ascii=False))
    prec = collections.Counter(m['precision'] for m in out)
    print(f"\n{len(out)} upcoming fixtures -> web/fixtures-static.json")
    print(f"  ground-level {prec['stadium']}, approximate {prec['city']}")
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
