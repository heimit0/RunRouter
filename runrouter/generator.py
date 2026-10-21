"""Route generation: turn a start point + preferences into ranked running loops.

How a loop is made
------------------
A loop of road length ``L`` is approximated as a polygon of via-points placed
on a circle of radius ``r`` around the start (or, for green/water preferences,
around a point shifted toward nearby nature areas). OSRM routes through those
points and back to the start.

The mapping from radius to road length is not smooth — in real cities the road
network quantizes achievable loop lengths (placing a waypoint 200 m vs 400 m
out can land on the same ring road and produce the *same* loop). We therefore:

  1. probe the area once to estimate its "winding factor" (road length per unit
     of straight-line loop perimeter), then
  2. target each route's radius with that factor, measuring and refining
     deterministically (fixed angles, no jitter) so refinement stays monotonic.

Routes are ranked by how close they land to the target length (plus a small
bonus for green/water preference), so the user always gets the nearest
achievable loops with their real distances shown.
"""

from __future__ import annotations

import asyncio
import math
import random
import uuid
from dataclasses import dataclass
from typing import Any, Sequence

from . import green
from .routing import OSRMClient, RoutingError

EARTH_R = 6_371_000.0
_TOLERANCE = 0.12


@dataclass
class Route:
    id: str
    name: str
    distance_m: float
    duration_s: float
    coordinates: list[tuple[float, float]]  # [(lat, lon), ...]
    route_type: str
    green_score: float
    score: float

    def to_dict(self, gpx_url: str | None = None) -> dict[str, Any]:
        lats = [c[0] for c in self.coordinates]
        lons = [c[1] for c in self.coordinates]
        bbox = (
            [round(min(lats), 6), round(min(lons), 6),
             round(max(lats), 6), round(max(lons), 6)]
            if self.coordinates
            else []
        )
        data: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "distance_km": round(self.distance_m / 1000, 2),
            "distance_m": round(self.distance_m, 1),
            "duration_min": round(self.duration_s / 60, 1),
            "duration_s": round(self.duration_s, 1),
            "route_type": self.route_type,
            "green_score": round(self.green_score, 2),
            "coordinates": self.coordinates,
            "bbox": bbox,
        }
        if gpx_url:
            data["gpx_url"] = gpx_url
        return data


def _offset(lat: float, lon: float, bearing_deg: float, dist_m: float) -> tuple[float, float]:
    """Destination point given a start, bearing and distance (geodesic)."""
    delta = dist_m / EARTH_R
    theta = math.radians(bearing_deg)
    phi1 = math.radians(lat)
    lam1 = math.radians(lon)
    phi2 = math.asin(
        math.sin(phi1) * math.cos(delta)
        + math.cos(phi1) * math.sin(delta) * math.cos(theta)
    )
    lam2 = lam1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * math.sin(phi2),
    )
    return math.degrees(phi2), math.degrees(lam2)


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    )
    return 2 * EARTH_R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _perimeter_factor(k: int) -> float:
    """Straight-line perimeter of a regular k-gon with circumradius 1."""
    return 2 * k * math.sin(math.pi / k)


def _shape(
    center: tuple[float, float],
    radius_m: float,
    theta0: float,
    k: int,
) -> list[tuple[float, float]]:
    """Deterministic k points on a circle of ``radius_m`` around ``center``."""
    clat, clon = center
    return [
        _offset(clat, clon, theta0 + 360.0 * i / k, radius_m) for i in range(k)
    ]


def _bias_center(
    start: tuple[float, float],
    areas: Sequence[dict[str, Any]],
    prefer: str,
    target_m: float,
) -> tuple[float, float] | None:
    """Point to shift the loop toward for green/water preferences, or None."""
    if prefer not in ("green", "water"):
        return None
    want = "water" if prefer == "water" else "green"
    candidates = [a for a in areas if a["kind"] == want]
    if not candidates and prefer == "water":
        candidates = [a for a in areas if a["kind"] == "green"]
    if not candidates:
        return None

    nearby = [
        a
        for a in candidates
        if _haversine(start[0], start[1], a["lat"], a["lon"]) <= target_m * 0.7
    ]
    if not nearby:
        return None

    clat = sum(a["lat"] for a in nearby) / len(nearby)
    clon = sum(a["lon"] for a in nearby) / len(nearby)
    return (
        start[0] + (clat - start[0]) * 0.4,
        start[1] + (clon - start[1]) * 0.4,
    )


async def _probe_winding(client: OSRMClient, start: tuple[float, float], target_m: float) -> float:
    """Estimate how many metres of road one metre of loop perimeter produces."""
    radius = target_m / 8.0
    via = _shape(start, radius, 0.0, 4)
    data = await client.route([start] + via + [start])
    dist = float(data["routes"][0]["distance"])
    straight = _perimeter_factor(4) * radius
    return dist / max(straight, 1.0)


async def _make_loop(
    client: OSRMClient,
    start: tuple[float, float],
    center: tuple[float, float],
    target_m: float,
    theta0: float,
    k: int,
    winding: float,
    max_attempts: int = 3,
) -> tuple[float, list[tuple[float, float]], float] | None:
    radius = target_m / (_perimeter_factor(k) * max(winding, 1.0))
    radius = max(30.0, min(radius, target_m * 0.5))

    best: tuple[float, list[tuple[float, float]], float] | None = None
    for _ in range(max_attempts):
        via = _shape(center, radius, theta0, k)
        coords = [start] + via + [start]
        try:
            data = await client.route(coords)
        except RoutingError:
            radius *= 0.8
            continue

        route = data["routes"][0]
        geom = route.get("geometry", {}).get("coordinates", [])
        if len(geom) < 2:
            radius *= 0.8
            continue

        coords_ll = [(lat, lon) for lon, lat in geom]
        dist = float(route.get("distance", 0.0))
        dur = float(route.get("duration", 0.0))

        candidate = (dist, coords_ll, dur)
        if best is None or abs(dist - target_m) < abs(best[0] - target_m):
            best = candidate

        if dist > 0 and abs(dist - target_m) / target_m < _TOLERANCE:
            return candidate

        radius *= (target_m / max(dist, 1.0)) ** 0.9
        radius = max(20.0, min(radius, target_m * 0.6))

    return best


async def _make_out_and_back(
    client: OSRMClient,
    start: tuple[float, float],
    center: tuple[float, float] | None,
    target_m: float,
    theta0: float,
    max_attempts: int = 3,
) -> tuple[float, list[tuple[float, float]], float] | None:
    lat, lon = start
    out = target_m / 4.0

    best: tuple[float, list[tuple[float, float]], float] | None = None
    for _ in range(max_attempts):
        dest = center if center else _offset(lat, lon, theta0, out)
        try:
            data = await client.route([start, dest])
        except RoutingError:
            out *= 0.8
            continue

        route = data["routes"][0]
        geom = route.get("geometry", {}).get("coordinates", [])
        if len(geom) < 2:
            out *= 0.8
            continue

        one_way = [(la, lo) for lo, la in geom]
        full = one_way + list(reversed(one_way))
        total = float(route["distance"]) * 2
        dur = float(route["duration"]) * 2

        candidate = (total, full, dur)
        if best is None or abs(total - target_m) < abs(best[0] - target_m):
            best = candidate

        if abs(total - target_m) / target_m < _TOLERANCE:
            return candidate

        out *= (target_m / max(total, 1.0)) ** 0.9

    return best


def _green_score(
    coords: list[tuple[float, float]],
    areas: Sequence[dict[str, Any]],
    sample: int = 40,
) -> float:
    """Fraction of sampled route points within 180 m of a nature area."""
    if not areas or not coords:
        return 0.0
    step = max(1, len(coords) // sample)
    near = 0
    total = 0
    for i in range(0, len(coords), step):
        lat, lon = coords[i]
        total += 1
        for area in areas:
            if _haversine(lat, lon, area["lat"], area["lon"]) < 180:
                near += 1
                break
    return near / total


def _score(dist_m: float, target_m: float, green_score: float, prefer: str) -> float:
    fit = abs(dist_m - target_m) / target_m
    score = 100.0 * (1.0 - min(fit, 1.0))
    if prefer in ("green", "water"):
        score += 15.0 * green_score
    return score


async def _safe_nature(lat: float, lon: float, radius_m: float) -> list[dict[str, Any]]:
    try:
        return await asyncio.wait_for(
            green.nature_areas(lat, lon, radius_m), timeout=12.0
        )
    except Exception:
        return []


async def generate_routes(
    client: OSRMClient,
    start: tuple[float, float],
    length_km: float,
    route_type: str = "loop",
    prefer: str = "balanced",
    count: int = 3,
    concurrency: int = 3,
) -> list[Route]:
    """Generate ``count`` running routes of roughly ``length_km`` from ``start``."""
    target_m = length_km * 1000.0
    rng = random.Random()

    # Green-space discovery and winding probe run concurrently (both are slow
    # external calls and are independent of each other).
    nature_task = asyncio.create_task(
        _safe_nature(start[0], start[1], min(target_m * 0.9, 15_000.0))
    )
    winding_task = asyncio.create_task(_probe_winding(client, start, target_m))

    areas = await nature_task
    try:
        winding = await winding_task
    except Exception:
        winding = 6.0  # sane urban default if the probe fails

    center = _bias_center(start, areas, prefer, target_m)
    loop_center = center or start

    semaphore = asyncio.Semaphore(concurrency)
    angles = [
        i * (360.0 / count) + rng.uniform(0.0, 60.0) for i in range(count)
    ]

    async def one(index: int, theta: float) -> tuple[float, list[tuple[float, float]], float] | None:
        async with semaphore:
            if route_type == "out_and_back":
                return await _make_out_and_back(client, start, center, target_m, theta)
            k = 3 + (index % 3)  # triangle/square/pentagon for variety
            return await _make_loop(client, start, loop_center, target_m, theta, k, winding)

    results = await asyncio.gather(
        *[one(i, theta) for i, theta in enumerate(angles)]
    )

    routes: list[Route] = []
    for index, result in enumerate(results):
        if result is None:
            continue
        dist, coords, dur = result
        gs = _green_score(coords, areas)
        score = _score(dist, target_m, gs, prefer)
        routes.append(
            Route(
                id=str(uuid.uuid4()),
                name=f"Route {index + 1}",
                distance_m=dist,
                duration_s=dur,
                coordinates=coords,
                route_type=route_type,
                green_score=gs,
                score=score,
            )
        )

    routes.sort(key=lambda r: r.score, reverse=True)
    return routes
