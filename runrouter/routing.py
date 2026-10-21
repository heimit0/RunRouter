"""OSRM routing client.

Talks to the OSRM route service. Works against the public demo server or a
self-hosted instance (selected via config.OSRM_BASE_URL).
"""

from __future__ import annotations

import asyncio
from typing import Any, Sequence

import httpx

from . import config


class RoutingError(Exception):
    """Raised when OSRM cannot produce a route."""


class OSRMClient:
    def __init__(
        self,
        base_url: str | None = None,
        profile: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.base_url = (base_url or config.OSRM_BASE_URL).rstrip("/")
        self.profile = profile or config.OSRM_PROFILE
        self.timeout = timeout or config.HTTP_TIMEOUT

    async def route(
        self,
        coords: Sequence[tuple[float, float]],
        steps: bool = False,
        retries: int = 3,
    ) -> dict[str, Any]:
        """Route through a list of ``(lat, lon)`` points.

        Returns the parsed OSRM JSON (``code``, ``routes``, ``waypoints``).
        Retries transient errors (429/5xx) with backoff — the public demo
        server rate-limits aggressively.
        """
        # OSRM expects "lon,lat" order, semicolon-separated.
        path = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in coords)
        url = f"{self.base_url}/route/v1/{self.profile}/{path}"
        params = {
            "overview": "full",
            "geometries": "geojson",
            "steps": "true" if steps else "false",
            "alternatives": "false",
        }

        last_error: str | None = None
        for attempt in range(retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.get(
                        url,
                        params=params,
                        headers={"User-Agent": "RunRouter/1.0"},
                    )
                if resp.status_code in (429, 502, 503, 504):
                    last_error = f"HTTP {resp.status_code} from {self.base_url}"
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                resp.raise_for_status()
                data = resp.json()
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = str(exc)
                await asyncio.sleep(1.5 * (attempt + 1))
                continue

            if data.get("code") != "Ok":
                raise RoutingError(data.get("message") or data.get("code"))
            if not data.get("routes"):
                raise RoutingError("No route found")
            return data

        raise RoutingError(
            f"OSRM request failed after {retries} attempts: {last_error}"
        )

    @property
    def backend_description(self) -> str:
        return f"{self.profile} @ {self.base_url}"
