// Town labels, so a zoomed-in country is a map rather than dots on an empty canvas.
//
// Natural Earth's populated places (public domain, same source as the country and
// province outlines). Its own importance ranking is what makes this work: every place
// carries scalerank and pop_max, so the map can show Rome before Rimini without anyone
// hand-picking which cities are "major".
//
//   node ingest/build-places.mjs      -> web/places.json
import fs from 'fs';

const WEB = new URL('../web/', import.meta.url);
const SRC = 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/'
          + 'geojson/ne_10m_populated_places_simple.geojson';

const WINDOW = [-32, 30, 46, 72];        // same frame as build-europe.mjs
// Drawn out of scope there, so their towns must go too or the labels reappear alone.
const OUTSIDE_SCOPE = new Set([
  'Algeria', 'Tunisia', 'Morocco', 'Libya', 'Egypt', 'W. Sahara', 'Western Sahara',
  'Israel', 'Palestine', 'Lebanon', 'Syria', 'Jordan', 'Iraq', 'Saudi Arabia', 'Kuwait',
]);

const res = await fetch(SRC);
if (!res.ok) throw new Error(`Natural Earth fetch failed: HTTP ${res.status}`);
const fc = await res.json();

const out = [];
for (const f of fc.features) {
  const p = f.properties;
  const [lon, lat] = f.geometry.coordinates;
  if (lon < WINDOW[0] || lon > WINDOW[2] || lat < WINDOW[1] || lat > WINDOW[3]) continue;
  if (OUTSIDE_SCOPE.has(p.adm0name)) continue;

  // scalerank runs 0 (world city) to 10 (small town). Sorting the layer by it lets
  // MapLibre's own collision detection do the work: when two labels overlap it keeps
  // the lower rank, so capitals survive and villages drop out, automatically, at every
  // zoom. No hand-tuned per-zoom thresholds to maintain.
  out.push({
    n: p.name,
    y: +lat.toFixed(3),
    x: +lon.toFixed(3),
    r: p.scalerank ?? 10,
    c: p.adm0cap === 1 ? 1 : 0,
  });
}
out.sort((a, b) => a.r - b.r || b.c - a.c);

const geo = {
  type: 'FeatureCollection',
  features: out.map(p => ({
    type: 'Feature',
    properties: { n: p.n, r: p.r, c: p.c },
    geometry: { type: 'Point', coordinates: [p.x, p.y] },
  })),
};
fs.writeFileSync(new URL('places.json', WEB), JSON.stringify(geo));
const kb = (fs.statSync(new URL('places.json', WEB)).size / 1024).toFixed(0);
const byRank = {};
for (const p of out) byRank[p.r] = (byRank[p.r] || 0) + 1;
console.log(`${out.length} places -> web/places.json (${kb} kB)`);
console.log('  by scalerank:', Object.entries(byRank).map(([k, v]) => `${k}:${v}`).join(' '));
console.log('  capitals:', out.filter(p => p.c).length);
