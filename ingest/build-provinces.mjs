// Build web/provinces.json (internal province/state borders) from Natural Earth 10m.
//   node ingest/build-provinces.mjs            # NE_ADMIN1 can point at the geojson
// Source: nvkelso/natural-earth-vector, ne_10m_admin_1_states_provinces - public domain,
// same family as the country outlines, so the two line up exactly at the coast.
import fs from 'fs';

const WEB = new URL('../web/', import.meta.url);
const SRC = process.env.NE_ADMIN1 || '/home/claude/ne_data/admin1.geojson';
const WINDOW = [-32, 30, 46, 72];   // w,s,e,n - drops French Guiana, Reunion, the Canaries
const TOL = 0.004;                  // Douglas-Peucker, ~350 m, as for the country outlines

// Every country we carry football for, plus the ones queued up, so the borders are
// already in place when those calendars land.
const COUNTRIES = new Set(['Italy','Germany','France','Spain','United Kingdom','Netherlands',
  'Belgium','Portugal','Turkey','Austria','Denmark','Greece','Czech Republic','Switzerland']);

// "Province" means wildly different things by country: 16 states in Germany, 5 regions in
// Denmark, but 110 provinces in Italy and 232 counties in the UK, which at country zoom
// read as texture rather than as places. Past this many, fall back to the coarser tier
// Natural Earth carries in `region` - Italy's 20 regioni, France's regions, Spain's
// autonomous communities. Only where every unit has one: a partly filled field would
// dissolve some borders and keep others, which is worse than either.
const MAX_UNITS = 40;

function dp(pts, tol) {
  const n = pts.length; if (n < 3) return pts;
  const keep = new Uint8Array(n); keep[0] = keep[n-1] = 1;
  const stack = [[0, n-1]];
  while (stack.length) {
    const [s,e] = stack.pop(); if (e-s < 2) continue;
    const [x1,y1] = pts[s], [x2,y2] = pts[e];
    const dx = x2-x1, dy = y2-y1, den = dx*dx + dy*dy;
    let max = -1, idx = -1;
    for (let i = s+1; i < e; i++) {
      const [x,y] = pts[i];
      let t = den ? ((x-x1)*dx + (y-y1)*dy)/den : 0; t = t<0?0:t>1?1:t;
      const d = (x-(x1+t*dx))**2 + (y-(y1+t*dy))**2;
      if (d > max) { max = d; idx = i; }
    }
    if (idx > 0 && Math.sqrt(max) > tol) { keep[idx] = 1; stack.push([s,idx],[idx,e]); }
  }
  return pts.filter((_,i) => keep[i]);
}

const key = p => `${p[0].toFixed(6)},${p[1].toFixed(6)}`;
const unkey = k => k.split(',').map(Number);

const fc = JSON.parse(fs.readFileSync(SRC, 'utf8'));

const tally = new Map();
for (const f of fc.features) {
  const a = f.properties.admin;
  if (!COUNTRIES.has(a)) continue;
  if (!tally.has(a)) tally.set(a, { n: 0, withRegion: 0, regions: new Set() });
  const t = tally.get(a); t.n++;
  if (f.properties.region) { t.withRegion++; t.regions.add(f.properties.region); }
}
const dissolve = new Map();
for (const [a, t] of tally)
  dissolve.set(a, t.n > MAX_UNITS && t.withRegion === t.n && t.regions.size > 1);

// The grouping each country's borders are drawn at. Two provinces in one group have no
// line between them, so dissolving is just a matter of what counts as "the same place".
const groupOf = f => dissolve.get(f.properties.admin)
  ? f.properties.region
  : (f.properties.adm1_code || f.properties.name);

const seg = new Map();   // undirected edge -> { countries:Set, groups:Set, n }
let rings = 0;

for (const f of fc.features) {
  const admin = f.properties.admin;
  if (!COUNTRIES.has(admin)) continue;
  const group = admin + '|' + groupOf(f);
  const g = f.geometry; if (!g) continue;
  const polys = g.type === 'Polygon' ? [g.coordinates] : g.coordinates;
  for (const poly of polys) {
    const b = poly[0].reduce((a,p) => [Math.min(a[0],p[0]),Math.min(a[1],p[1]),
                                       Math.max(a[2],p[0]),Math.max(a[3],p[1])], [1e9,1e9,-1e9,-1e9]);
    const cx = (b[0]+b[2])/2, cy = (b[1]+b[3])/2;
    if (cx < WINDOW[0] || cx > WINDOW[2] || cy < WINDOW[1] || cy > WINDOW[3]) continue;
    for (const ring of poly) {
      rings++;
      for (let i = 0; i + 1 < ring.length; i++) {
        const a = key(ring[i]), c = key(ring[i+1]);
        if (a === c) continue;
        const k = a < c ? a + '|' + c : c + '|' + a;
        let s = seg.get(k);
        if (!s) seg.set(k, s = { countries: new Set(), groups: new Set(), n: 0 });
        s.countries.add(admin); s.groups.add(group); s.n++;
      }
    }
  }
}

// An edge dividing two different groups is a border worth drawing. One walked twice by
// the same group is interior to it - this is what dissolves Italy's provinces into its
// regions. One walked once is the edge of the country, which the outline layer already
// draws, so drawing it again would only thicken it; and one whose two sides sit in
// different countries is a national border by another name.
const adj = new Map();
let kept = 0;
for (const [k, s] of seg) {
  if (s.n < 2 || s.countries.size !== 1 || s.groups.size !== 2) continue;
  kept++;
  const owner = [...s.countries][0];
  const [a, c] = k.split('|');
  for (const [x, y] of [[a,c],[c,a]]) {
    if (!adj.has(x)) adj.set(x, []);
    adj.get(x).push({ to: y, k, owner });
  }
}

// Stitch the surviving edges into the longest runs possible before simplifying: run
// Douglas-Peucker on two-point stubs and it has nothing to remove.
const used = new Set();
const lines = [];
function walk(start) {
  for (const e0 of adj.get(start) || []) {
    if (used.has(e0.k)) continue;
    used.add(e0.k);
    const pts = [start, e0.to];
    let cur = e0.to;
    for (;;) {
      const nb = (adj.get(cur) || []).filter(e => !used.has(e.k));
      if ((adj.get(cur) || []).length !== 2 || nb.length !== 1) break;
      used.add(nb[0].k); pts.push(nb[0].to); cur = nb[0].to;
    }
    lines.push({ pts, owner: e0.owner });
  }
}
for (const node of adj.keys()) if ((adj.get(node) || []).length !== 2) walk(node);
for (const node of adj.keys()) walk(node);   // whatever is left is a closed loop

// One feature per country, so the map can lift the country you are looking at out of
// its neighbours instead of drawing every border in Europe at the same weight.
// Natural Earth's admin-1 set says "Czech Republic" where its country shapes - and so
// the app - say "Czechia". The names have to agree or the emphasis never matches.
const APP_NAME = { 'Czech Republic': 'Czechia' };
const byCountry = new Map();
let nLines = 0, nPts = 0;
for (const l of lines) {
  const pts = dp(l.pts.map(unkey), TOL).map(p => [Math.round(p[0]*1e4)/1e4, Math.round(p[1]*1e4)/1e4]);
  if (pts.length < 2) continue;
  const owner = APP_NAME[l.owner] || l.owner;
  if (!byCountry.has(owner)) byCountry.set(owner, []);
  byCountry.get(owner).push(pts);
  nLines++; nPts += pts.length;
}
const geo = { type:'FeatureCollection', features: [...byCountry].map(([country, coords]) => (
  { type:'Feature', properties:{ country }, geometry:{ type:'MultiLineString', coordinates: coords } })) };
fs.writeFileSync(new URL('provinces.json', WEB), JSON.stringify(geo));
const mb = (fs.statSync(new URL('provinces.json', WEB)).size/1048576).toFixed(2);
for (const [a, t] of [...tally].sort())
  console.log(`   ${a.padEnd(16)} ${String(t.n).padStart(4)} units -> ` +
    (dissolve.get(a) ? `${t.regions.size} regions` : 'kept as-is') +
    (t.n > MAX_UNITS && !dissolve.get(a) ? `  (no region data: ${t.withRegion}/${t.n})` : ''));
console.log(`${rings} rings -> ${seg.size} edges, ${kept} internal`);
console.log(`${nLines} lines, ${nPts} points, ${byCountry.size} countries -> provinces.json ${mb} MB`);
for (const [c, v] of [...byCountry].sort((a,b)=>b[1].length-a[1].length))
  console.log(`   ${c.padEnd(16)} ${String(v.length).padStart(4)} lines`);
