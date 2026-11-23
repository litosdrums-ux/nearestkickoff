// Build web/europe.json (country outlines) from Natural Earth 10m via world-atlas.
//   node ingest/build-europe.mjs
// Needs: npm i world-atlas topojson-client   (WORLD_ATLAS can point at the json)
import fs from 'fs';
import { feature } from 'topojson-client';

const WEB = new URL('../web/', import.meta.url);
const read = f => { try { return JSON.parse(fs.readFileSync(new URL(f, WEB), 'utf8')); } catch { return null; } };
// any venue we hold, so small islands that actually host football survive the islet filter
// every venue we hold, from both tables, so a ground outside the window still pulls in
// the land under it - without this the Canaries are missing and Tenerife and Las Palmas
// are drawn in open ocean, which is the one error users spot instantly
const venues = [...(read('venues.json') || []), ...(read('stadiums.json') || []),
                ...(read('fixtures-static.json') || [])];

const WINDOW = [-32, 30, 46, 72];   // w,s,e,n — 30N keeps Madeira, -32 keeps the Azores
const TOL = 0.004;                  // Douglas-Peucker, ~350 m
const atlas = process.env.WORLD_ATLAS || 'node_modules/world-atlas/countries-10m.json';
const topo = JSON.parse(fs.readFileSync(atlas, 'utf8'));
const fc = feature(topo, topo.objects.countries);

const bboxOf = r => r.reduce((a, p) => [Math.min(a[0],p[0]),Math.min(a[1],p[1]),Math.max(a[2],p[0]),Math.max(a[3],p[1])], [1e9,1e9,-1e9,-1e9]);
const areaOf = b => (b[2]-b[0]) * (b[3]-b[1]) * Math.cos((b[1]+b[3])/2 * Math.PI/180);

function dp(pts, tol) {
  const n = pts.length; if (n < 5) return pts;
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
  const out = pts.filter((_,i) => keep[i]);
  return out.length >= 4 ? out : pts;
}
const round = p => [Math.round(p[0]*1e4)/1e4, Math.round(p[1]*1e4)/1e4];
const nearVenue = b => venues.some(v => v.lon > b[0]-.4 && v.lon < b[2]+.4 && v.lat > b[1]-.4 && v.lat < b[3]+.4);

const features = [];
for (const f of fc.features) {
  const g = f.geometry; if (!g) continue;
  const polys = g.type === 'Polygon' ? [g.coordinates] : g.coordinates;
  const kept = [];
  for (const poly of polys) {
    const b = bboxOf(poly[0]);
    const cx = (b[0]+b[2])/2, cy = (b[1]+b[3])/2;
    if ((cx < WINDOW[0] || cx > WINDOW[2] || cy < WINDOW[1] || cy > WINDOW[3])
        && !nearVenue(b)) continue;
    if (b[2]-b[0] < 0.08 && b[3]-b[1] < 0.08 && !nearVenue(b)) continue;
    const rings = poly.map(r => dp(r, TOL).map(round)).filter(r => r.length >= 4);
    if (rings.length) kept.push({ rings, area: areaOf(b), bbox: bboxOf(rings[0]) });
  }
  if (!kept.length) continue;
  // "bounds" drives the zoom-to-country camera, so use the mainland: a far-flung
  // island (Madeira, the Canaries, Shetland) must not zoom the whole country out
  const biggest = Math.max(...kept.map(k => k.area));
  const main = kept.filter(k => k.area >= biggest * 0.02);
  const mb = main.reduce((a,k) => [Math.min(a[0],k.bbox[0]),Math.min(a[1],k.bbox[1]),Math.max(a[2],k.bbox[2]),Math.max(a[3],k.bbox[3])], [1e9,1e9,-1e9,-1e9]);
  features.push({ type:'Feature', id: features.length+1,
    properties: { name: f.properties.name, bounds: mb.map(v => Math.round(v*1e3)/1e3) },
    geometry: { type:'MultiPolygon', coordinates: kept.map(k => k.rings) } });
}

fs.writeFileSync(new URL('europe.json', WEB), JSON.stringify({ type:'FeatureCollection', features }));
console.log(`${features.length} countries -> europe.json ${(fs.statSync(new URL('europe.json', WEB)).size/1048576).toFixed(2)} MB`);
