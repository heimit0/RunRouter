# RunRouter

A real-world running route finder built on OpenStreetMap. Pick a start point,
choose a target distance, and get back several distinct loop (or out-and-back)
routes you can run today — exportable as GPX for your watch or phone.

## How it works

RunRouter combines three free, keyless OSM services:

| Layer       | Service                    | Role                                   |
|-------------|----------------------------|----------------------------------------|
| Geocoding   | [Nominatim](https://nominatim.openstreetmap.org) | turn an address into coordinates |
| Routing     | [OSRM](https://project-osrm.org) (foot profile) | find actual runnable paths    |
| Green data  | [Overpass](https://overpass-api.de)   | discover parks, forests and water |

Route generation: a loop of road length `L` is approximated as a polygon of
waypoints placed on a circle around the start. OSRM routes through those points
and back. Because the road→length mapping is not smooth (real road networks
quantize achievable loop lengths), RunRouter first probes the area once to
estimate its local "winding factor", then targets each route's radius with that
factor and refines deterministically. For "green"/"water" preferences, waypoints
are biased toward nearby nature-area centroids (from Overpass) and each finished
route is scored by how green it is. Routes are ranked by distance fit (+ green
bonus) and returned fanned out in different directions.

## Quick start

```bash
cd RunRouter
uv sync
uv run python -m runrouter.main   # serves on http://127.0.0.1:8010
```

Requires Python 3.11–3.13 (pinned via `.python-version`).

> The app is started via `python -m` (not the `runrouter` console script) because
> on macOS, `uv` marks `.venv` files with the `UF_HIDDEN` flag and Python's
> `site.py` skips hidden `.pth` files — which breaks *editable* installs, so the
> console script's `import runrouter` fails. `python -m` resolves the package
> from the working directory and is unaffected.

Open http://127.0.0.1:8010, click a start point on the map (or search an
address), set the length and preferences, then hit **Routen generieren**.

> The default routing backend is the public OSRM demo server
> (`router.project-osrm.org`, foot profile) — free, no key, but demo-grade and
> rate-limited. For reliable use, self-host OSRM (below) and point RunRouter at
> it.
>
> The requested length is a *target*, not a guarantee: real road networks
> quantize achievable loop lengths, so RunRouter returns the nearest loops and
> always shows their actual distance. The "green"/"water" preference depends on
> the Overpass API; if Overpass is down, routes are still generated (just
> without green biasing/scoring).

## Routing backend (public vs. self-hosted)

RunRouter picks its backend from environment variables:

```bash
OSRM_BASE_URL=https://router.project-osrm.org   # default (public demo)
OSRM_PROFILE=foot                                # running/walking

# self-hosted:
OSRM_BASE_URL=http://localhost:5000 uv run python -m runrouter.main
```

To self-host OSRM with the foot profile, either use Docker Compose
(`docker-compose.osrm.yml`) or the helper script
(`scripts/start-osrm.sh <region>`). Both download a Geofabrik region extract
and run extract → partition → customize → routed. You will want to edit the
region to match your area (the example uses Brandenburg, Germany).

## API

| Method | Path                    | Description                                   |
|--------|-------------------------|-----------------------------------------------|
| GET    | `/api/health`           | status + active routing backend               |
| GET    | `/api/geocode?q=…`      | Nominatim address search                      |
| POST   | `/api/routes`           | generate ranked routes                        |
| GET    | `/api/routes/{id}/gpx`  | download a route as GPX                       |

`POST /api/routes` body:

```json
{
  "lat": 52.5200,
  "lon": 13.4050,
  "length_km": 8,
  "route_type": "loop",        // loop | out_and_back
  "prefer": "green",           // balanced | green | water
  "count": 3
}
```

## Development

```bash
uv run pytest                 # backend unit tests (mocked, deterministic)

# browser e2e (uses system Chrome, no download):
npm install                   # installs @playwright/test
npm run e2e                   # deterministic mock tests
npm run e2e:real              # real test against live OSRM (needs network)
```

The web server host/port are configurable via `RUNROUTER_HOST` /
`RUNROUTER_PORT` (default `127.0.0.1:8010`).

## Project layout

```
runrouter/          Python package (FastAPI app + route generator)
  config.py         env-driven routing-backend switch
  geocode.py        Nominatim
  routing.py        OSRM client (retries/backoff)
  green.py          Overpass nature-area discovery
  generator.py      loop generation + ranking
  gpx.py            GPX 1.1 serialization
  main.py           FastAPI app + endpoints
static/             Leaflet frontend (no build step)
scripts/            self-hosted OSRM helper
tests/              pytest unit tests
e2e/                Playwright browser tests
```

## Data sources

© OpenStreetMap contributors — data licensed under the
[ODbL](https://www.openstreetmap.org/copyright). Respect the public Nominatim,
Overpass and OSRM-demo usage policies (low request volume, identify your app).
