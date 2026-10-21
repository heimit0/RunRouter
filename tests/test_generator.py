"""Route generator tests (OSRM + Overpass mocked, deterministic)."""

import asyncio
import math

from runrouter import generator


class FakeClient:
    """Returns a fixed closed-loop geometry with a configurable distance."""

    def __init__(self, distance_m: float = 5000.0):
        self.distance_m = distance_m
        self.calls = []

    async def route(self, coords, steps=False):
        self.calls.append(coords)
        lat0, lon0 = coords[0]
        geom = []
        n = 100
        for i in range(n):
            a = 2 * math.pi * i / n
            geom.append(
                [lon0 + 0.01 * math.cos(a), lat0 + 0.01 * math.sin(a)]
            )
        return {
            "code": "Ok",
            "routes": [
                {
                    "distance": self.distance_m,
                    "duration": self.distance_m / 2.5,
                    "geometry": {"coordinates": geom},
                }
            ],
            "waypoints": [{"distance": 0.0}] * len(coords),
        }


async def _no_nature(lat, lon, radius_m, limit=40):
    return []


def _run(coro):
    return asyncio.run(coro)


def test_generate_returns_requested_count(monkeypatch):
    monkeypatch.setattr(generator.green, "nature_areas", _no_nature)
    routes = _run(
        generator.generate_routes(FakeClient(), (52.52, 13.405), 5.0, count=3)
    )
    assert len(routes) == 3
    for route in routes:
        assert route.distance_m > 0
        assert route.coordinates
        assert route.green_score == 0.0


def test_loop_is_closed(monkeypatch):
    monkeypatch.setattr(generator.green, "nature_areas", _no_nature)
    routes = _run(
        generator.generate_routes(FakeClient(), (52.52, 13.405), 5.0, count=1)
    )
    coords = routes[0].coordinates
    start = coords[0]
    end = coords[-1]
    assert abs(start[0] - end[0]) < 0.001
    assert abs(start[1] - end[1]) < 0.001


def test_routes_are_sorted_by_score(monkeypatch):
    monkeypatch.setattr(generator.green, "nature_areas", _no_nature)
    routes = _run(
        generator.generate_routes(FakeClient(), (52.52, 13.405), 5.0, count=3)
    )
    scores = [r.score for r in routes]
    assert scores == sorted(scores, reverse=True)


def test_offset_moves_point():
    lat, lon = generator._offset(52.52, 13.405, 0, 1000)
    assert lat > 52.52  # north bearing increases latitude
    assert abs(lon - 13.405) < 0.5
