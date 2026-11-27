#!/usr/bin/env bash
# Assemble dist/ - the folder the host actually serves.
#
# Deliberately a copy step rather than serving web/ directly: web/ also holds build
# inputs and intermediates (fixtures-static.json, venues.json, stadiums.json) that the
# site never fetches and that have no business being public.
set -euo pipefail
cd "$(dirname "$0")"

rm -rf dist && mkdir -p dist/fonts

cp web/index.html web/credits.html web/privacy.html web/terms.html \
   web/disclosure.html web/page.css dist/
cp web/matches.json web/europe.json web/provinces.json web/cities.json web/places.json dist/
cp web/maplibre-gl.js web/maplibre-gl.css dist/
cp web/fonts/* dist/fonts/
cp web/_headers web/robots.txt web/sitemap.xml dist/

# The generated content layer: city/, league/ and the two indexes. Copied wholesale
# because build-pages.py rebuilds them from scratch on every run.
cp -r web/city web/league web/cities web/leagues dist/

echo "dist/ assembled: $(find dist -type f | wc -l) files, $(du -sh dist | cut -f1)"
