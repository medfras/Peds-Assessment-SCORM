---
name: Map Asset Optimization — May 2026
description: Static map asset changes made during map load performance audit (May 2026) — caching strategy, moved files, compression decisions
type: project
---

Completed map load optimization (2026-05-09):

**Why:** Map images were loading slowly on first user click (on-demand, no preload, large files, no cache headers).

**What changed:**
- Removed from public static: `puppy-park-map.jpeg`, `peds-medical-trail_2.jpeg`, `peds-trauma-trail_2.jpeg` (root), `orientation/station_v1.jpeg` — moved to `/private/tmp/ems-unused-public-map-assets/`
- Compressed `static/img/maps/orientation/station.jpeg`: 2.4 MB → 512 KB
- Added `<link rel="preload">` for `MAP0-park.jpeg?v=20260510` (first peds map)
- Added adjacent-map prefetch after visible map loads and browser is idle
- JS cache version bumped to `20260510-map-assets-v6`
- Total peds maps still ~11 MB (26 JPEGs, 335–578 KB each — WebP conversion deferred)

**Caching strategy added to app/main.py (around line 15143):**
- Versioned assets (`?v=...`): `Cache-Control: public, max-age=31536000, immutable`
- Unversioned `img/` and `audio/` assets: 1-day cache

**How to apply:** When touching static asset serving or adding new map images, preserve the versioned/unversioned cache split. WebP conversion (remaining ~30% size reduction opportunity) is deferred but not ruled out.
