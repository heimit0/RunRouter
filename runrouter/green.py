"""Green-space and water discovery via the Overpass API (OSM data).

Used two ways by the route generator:
  * biasing loop waypoints toward parks/forests/water when the user asks for a
    "green" or "water" route, and
  * scoring how green/water-adjacent a finished route is.
"""

from __future__ import annotations

from typing import Any

import httpx

from . import config

_GREEN_TAGS = [
    ("leisure", "park"),
    ("landuse", "forest"),
    ("landuse", "grass"),
    ("leisure", "nature_reserve"),
    ("landuse", "meadow"),
    ("natural", "wood"),
    ("leisure", "garden"),
    ("landuse", "recreation_ground"),
]

_WATER_TAGS = [
    ("natural", "water"),
    ("waterway", "river"),
    ("waterway", "stream"),
    ("waterway", "canal"),
]

_ALL_TAGS = _WATER_TAGS + _GREEN_TAGS


def _build_query(around_m: float, lat: float, lon: float, limit: int) -> str:
    lines = []
    for key, val in _ALL_TAGS:
        lines.append(f'  way["{key}"="{val}"](around:{around_m},{lat},{lon});')
        lines.append(f'  relation["{key}"="{val}"](around:{around_m},{lat},{lon});')
    body = "\n".join(lines)
    return f"[out:json][timeout:25];\n(\n{body}\n);\nout center {limit};\n"


def _kind(tags: dict[str, str]) -> str | None:
    for key, val in _WATER_TAGS:
        if tags.get(key) == val:
            return "water"
    for key, val in _GREEN_TAGS:
        if tags.get(key) == val:
            return "green"
    return None


def _parse(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    areas: list[dict[str, Any]] = []
    for el in elements:
        if el.get("type") == "node":
            lat, lon = el.get("lat"), el.get("lon")
        else:
            center = el.get("center", {})
            lat, lon = center.get("lat"), center.get("lon")
        if lat is None or lon is None:
            continue
        tags = el.get("tags", {})
        kind = _kind(tags)
        if kind is None:
            continue
        name = (
            tags.get("name")
            or tags.get("name:de")
            or tags.get("name:en")
            or ""
        )
        areas.append(
            {
                "name": name,
                "lat": float(lat),
                "lon": float(lon),
                "kind": kind,
                "osm_type": el.get("type", ""),
                "osm_id": el.get("id", ""),
            }
        )
    return areas


async def _overpass(query: str) -> dict[str, Any]:
    last_error: str | None = None
    for url in config.OVERPASS_URLS:
        try:
            async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT) as client:
                resp = await client.post(
                    url,
                    data={"data": query},
                    headers={"User-Agent": "RunRouter/1.0"},
                )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            last_error = f"{url}: {exc}"
            continue
    raise RuntimeError(
        f"All Overpass mirrors failed. Last error: {last_error or 'unknown'}"
    )


async def nature_areas(
    lat: float,
    lon: float,
    radius_m: float,
    limit: int = 40,
) -> list[dict[str, Any]]:
    """Return green/water areas (centroids) within ``radius_m`` of a point."""
    query = _build_query(radius_m, lat, lon, limit)
    data = await _overpass(query)
    return _parse(data.get("elements", []))
