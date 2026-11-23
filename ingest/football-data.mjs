// Pulls upcoming fixtures from Football-Data.org and writes ../web/matches.json
// Usage:  FOOTBALL_DATA_TOKEN=xxxx node football-data.mjs
// Free tier: 12 competitions, 10 requests/min. Check their terms before commercial use.
//
// Output schema (same fields the prototype uses):
//   { sid, home, away, ko (ISO UTC), league, tier, stadium, city, country, lat, lon }
//
// Stadium coordinates are NOT in the free fixtures payload. Join on team id/name against
// a venues table (OpenStreetMap leisure=stadium + sport=soccer, or Wikidata), see venues.json.

import fs from 'node:fs';

const TOKEN = process.env.FOOTBALL_DATA_TOKEN;
if (!TOKEN) { console.error('Set FOOTBALL_DATA_TOKEN'); process.exit(1); }

// code -> [league name, tier, country]
const COMPETITIONS = {
  PL:  ['Premier League', 1, 'England'],
  ELC: ['Championship', 2, 'England'],
  PD:  ['La Liga', 1, 'Spain'],
  SA:  ['Serie A', 1, 'Italy'],
  BL1: ['Bundesliga', 1, 'Germany'],
  FL1: ['Ligue 1', 1, 'France'],
  DED: ['Eredivisie', 1, 'Netherlands'],
  PPL: ['Primeira Liga', 1, 'Portugal'],
};

// venues.json: { "<football-data team id>": { stadium, city, lat, lon } }  (you build this once)
const venues = JSON.parse(fs.readFileSync(new URL('./venues.json', import.meta.url), 'utf8'));

const sleep = ms => new Promise(r => setTimeout(r, ms));
const from = new Date().toISOString().slice(0, 10);
const to = new Date(Date.now() + 14 * 864e5).toISOString().slice(0, 10);
const out = [];

for (const [code, [league, tier, country]] of Object.entries(COMPETITIONS)) {
  const url = `https://api.football-data.org/v4/competitions/${code}/matches?dateFrom=${from}&dateTo=${to}`;
  const res = await fetch(url, { headers: { 'X-Auth-Token': TOKEN } });
  if (!res.ok) { console.error(code, res.status, await res.text()); await sleep(7000); continue; }
  const { matches } = await res.json();
  for (const m of matches) {
    const v = venues[m.homeTeam.id];
    if (!v) { console.warn('no venue for', m.homeTeam.name); continue; }
    out.push({
      sid: String(m.homeTeam.id), home: m.homeTeam.shortName || m.homeTeam.name,
      away: m.awayTeam.shortName || m.awayTeam.name, ko: m.utcDate,
      league, tier, country, stadium: v.stadium, city: v.city, lat: v.lat, lon: v.lon,
    });
  }
  await sleep(7000); // stay under 10 req/min
}

fs.writeFileSync(new URL('../web/matches.json', import.meta.url), JSON.stringify(out));
console.log(`Wrote ${out.length} matches`);
