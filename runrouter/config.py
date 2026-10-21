"""Runtime configuration.

The routing backend is selectable via environment variables. By default the
public OSRM demo server is used (foot profile, no API key). Point
``OSRM_BASE_URL`` at a self-hosted OSRM instance to switch — see
``scripts/start-osrm.sh`` and ``docker-compose.osrm.yml``.
"""

from __future__ import annotations

import os


def _env(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


# --- Routing backend ---------------------------------------------------------
# Public demo by default. For a self-hosted instance set e.g.
#   OSRM_BASE_URL=http://localhost:5000
OSRM_BASE_URL = _env("OSRM_BASE_URL", "https://router.project-osrm.org").rstrip("/")
# foot = walking/running profile.
OSRM_PROFILE = _env("OSRM_PROFILE", "foot")

# --- Geocoding ---------------------------------------------------------------
NOMINATIM_URL = _env("NOMINATIM_URL", "https://nominatim.openstreetmap.org").rstrip("/")
NOMINATIM_USER_AGENT = _env("NOMINATIM_USER_AGENT", "RunRouter/1.0 (running route finder)")

# --- Overpass (green-space / water discovery) --------------------------------
OVERPASS_URLS = [
    u
    for u in (
        _env("OVERPASS_URL", ""),
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    )
    if u
]

HTTP_TIMEOUT = float(_env("HTTP_TIMEOUT", "30"))
