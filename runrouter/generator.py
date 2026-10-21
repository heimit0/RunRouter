"""Route generation: turn a start point + preferences into ranked running loops.

The core idea: a loop of road length ``L`` is roughly a polygon of via-points
placed on a circle of radius ``r ≈ L/8`` around the start. OSRM routes through
those points and back to the start; we measure the resulting distance and
iteratively rescale ``r`` until the loop is within tolerance of the target.

Preferences:
  * ``route_type``: "loop" (round course) or "out_and_back" (there and back).
  * ``prefer``:     "balanced", "green" (bias toward parks/forest), "water"
                    (bias toward rivers/lakes). Bias steers waypoints toward
                    nearby nature-area centroids (from Overpass).
  * ``count``:      how many distinct routes to return (fanned out in different
                    directions).
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


def _loop_via_points(
    start: tuple[float, float],
    radius_m: float,
    theta0: float,
    k: int,
    bias: Sequence[dict[str, Any]],
    bias_prob: float,
    rng: random.Random,
) -> list[tuple[float, float]]:
    lat, lon = start
    points: list[tuple[float, float]] = []
    bias_index = 0
    for i in range(k):
        if bias and rng.random() < bias_prob:
            area = bias[bias_index % len(bias)]
            bias_index += 1
            points.append((area["lat"], area["lon"]))
            continue
        angle = theta0 + 360.0 * i / k + rng.uniform(-8, 8)
        radius = radius_m * rng.uniform(0.85, 1.15)
        points.append(_offset(lat, lon, angle, radius))
    return points


def _bias_areas(
    areas: Sequence[dict[str, Any]],
    start: tuple[float, float],
    prefer: str,
    target_m: float,
) -> list[dict[str, Any]]:
    if prefer not in ("green", "water"):
        return []
    want = "water" if prefer == "water" else "green"
    candidates = [a for a in areas if a["kind"] == want]
    if not candidates and prefer == "water":
        candidates = [a for a in areas if a["kind"] == "green"]
    max_dist = target_m * 0.7
    return [
        a
        for a in candidates
        if _haversine(start[0], start[1], a["lat"], a["lon"]) <= max_dist
    ]


async def _make_loop(
    client: OSRMClient,
    start: tuple[float, float],
    target_m: float,
    bias: Sequence[dict[str, Any]],
    bias_prob: float,
    theta0: float,
    rng: random.Random,
    k: int,
    max_attempts: int = 3,
) -> tuple[float, list[tuple[float, float]], float] | None:
    radius = target_m / 8.0
    best: tuple[float, list[tuple[float, float]], float] | None = None
    for _ in range(max_attempts):
        via = _loop_via_points(start, radius, theta0, k, bias, bias_prob, rng)
        coords = [start] + via + [start]
        try:
            data = await client.route(coords)
        except RoutingError:
            radius *= 0.7
            continue

        route = data["routes"][0]
        geom = route.get("geometry", {}).get("coordinates", [])
        if len(geom) < 2:
            radius *= 0.7
            continue

        coords_ll = [(lat, lon) for lon, lat in geom]
        dist = float(route.get("distance", 0.0))
        dur = float(route.get("duration", 0.0))
        waypoints = data.get("waypoints", [])
        max_snap = max((w.get("distance", 0.0) for w in waypoints), default=0.0)

        candidate = (dist, coords_ll, dur)
        if best is None or abs(dist - target_m) < abs(best[0] - target_m):
            best = candidate

        if dist > 0 and abs(dist - target_m) / target_m < 0.12 and max_snap < 500:
            return candidate

        radius *= (target_m / max(dist, 1.0)) ** 0.6

    return best


async def _make_out_and_back(
    client: OSRMClient,
    start: tuple[float, float],
    target_m: float,
    bias: Sequence[dict[str, Any]],
    bias_prob: float,
    theta0: float,
    rng: random.Random,
) -> tuple[float, list[tuple[float, float]], float] | None:
    lat, lon = start
    half = target_m / 2.0
    dest = _offset(lat, lon, theta0, half)
    if bias and rng.random() < bias_prob:
        area = rng.choice(bias)
        dest = (area["lat"], area["lon"])

    data = await client.route([start, dest])
    route = data["routes"][0]
    geom = route.get("geometry", {}).get("coordinates", [])
    if len(geom) < 2:
        return None

    out = [(la, lo) for lo, la in geom]
    full = out + list(reversed(out))
    return route["distance"] * 2, full, route["duration"] * 2


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


async def generate_routes(
    client: OSRMClient,
    start: tuple[float, float],
    length_km: float,
    route_type: str = "loop",
    prefer: str = "balanced",
    count: int = 3,
    concurrency: int = 2,
) -> list[Route]:
    """Generate ``count`` running routes of roughly ``length_km`` from ``start``."""
    target_m = length_km * 1000.0
    rng = random.Random()

    try:
        areas = await green.nature_areas(
            start[0], start[1], min(target_m * 0.9, 15_000.0)
        )
    except Exception:
        areas = []

    bias = _bias_areas(areas, start, prefer, target_m)
    bias_prob = 0.6 if bias else 0.0

    semaphore = asyncio.Semaphore(concurrency)
    angles = [
        i * (360.0 / count) + rng.uniform(0.0, 60.0) for i in range(count)
    ]

    async def one(index: int, theta: float) -> tuple[float, list[tuple[float, float]], float] | None:
        async with semaphore:
            if route_type == "out_and_back":
                return await _make_out_and_back(
                    client, start, target_m, bias, bias_prob, theta, rng
                )
            k = 3 + (index % 3)  # vary loop shape: triangle/square/pentagon
            return await _make_loop(
                client, start, target_m, bias, bias_prob, theta, rng, k
            )

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
