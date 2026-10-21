"""Nominatim geocoding (forward + reverse).

Nominatim's usage policy asks for at most 1 request per second, so every
lookup is serialized through a module-level semaphore.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from . import config

_semaphore = asyncio.Semaphore(1)


async def geocode(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Geocode a free-text query into a list of candidate places."""
    async with _semaphore:
        async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT) as client:
            resp = await client.get(
                f"{config.NOMINATIM_URL}/search",
                params={
                    "q": query,
                    "format": "json",
                    "limit": limit,
                    "addressdetails": 1,
                    "accept-language": "de",
                },
                headers={"User-Agent": config.NOMINATIM_USER_AGENT},
            )
            resp.raise_for_status()
            data = resp.json()

    results = []
    for item in data:
        results.append(
            {
                "display_name": item.get("display_name", ""),
                "lat": float(item["lat"]),
                "lon": float(item["lon"]),
                "type": item.get("type", ""),
                "category": item.get("category", ""),
                "osm_type": item.get("osm_type", ""),
                "osm_id": item.get("osm_id", ""),
            }
        )
    return results


async def reverse(lat: float, lon: float) -> dict[str, Any]:
    """Reverse-geocode coordinates to a display name."""
    async with _semaphore:
        async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT) as client:
            resp = await client.get(
                f"{config.NOMINATIM_URL}/reverse",
                params={
                    "lat": lat,
                    "lon": lon,
                    "format": "json",
                    "addressdetails": 1,
                    "accept-language": "de",
                },
                headers={"User-Agent": config.NOMINATIM_USER_AGENT},
            )
            resp.raise_for_status()
            data = resp.json()
    return {"display_name": data.get("display_name", "")}
