#!/usr/bin/env bash
# Self-host an OSRM routing server with the "foot" profile (running/walking).
#
# Downloads a Geofabrik region extract, prepares it, and serves it on :5000.
# Then point RunRouter at it:
#     OSRM_BASE_URL=http://localhost:5000 uv run runrouter
#
# Usage:  scripts/start-osrm.sh [REGION]   (default: germany)
#   REGION is a Geofabrik extract name, e.g. berlin, brandenburg, germany,
#   bayern, nordrhein-westfalen, ...  see https://download.geofabrik.de/
set -euo pipefail

REGION="${1:-germany}"
WORKDIR="${OSRM_WORKDIR:-$HOME/.cache/osrm}"
PORT="${OSRM_PORT:-5000}"

PBF_URL="https://download.geofabrik.de/europe/${REGION}-latest.osm.pbf"
PBF="$WORKDIR/${REGION}-latest.osm.pbf"

mkdir -p "$WORKDIR"
cd "$WORKDIR"

echo "==> Downloading $PBF_URL"
if [ ! -f "$PBF" ]; then
  curl -L -o "$PBF" "$PBF_URL"
else
  echo "    (already present, skipping download)"
fi

echo "==> osrm-extract"
docker run --rm -v "$WORKDIR":/data osrm/osrm-backend \
  osrm-extract -p /opt/foot.lua "/data/${REGION}-latest.osm.pbf"

echo "==> osrm-partition"
docker run --rm -v "$WORKDIR":/data osrm/osrm-backend \
  osrm-partition "/data/${REGION}-latest.osrm"

echo "==> osrm-customize"
docker run --rm -v "$WORKDIR":/data osrm/osrm-backend \
  osrm-customize "/data/${REGION}-latest.osrm"

echo "==> Serving on http://localhost:${PORT}"
docker run --rm -p "${PORT}:5000" -v "$WORKDIR":/data osrm/osrm-backend \
  osrm-routed --algorithm mld "/data/${REGION}-latest.osrm"
