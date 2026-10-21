"""FastAPI endpoint tests (route generation mocked)."""

from fastapi.testclient import TestClient

from runrouter import main
from runrouter.generator import Route


def _fake_generate_routes(client, start, length_km, route_type="loop",
                          prefer="balanced", count=3):
    async def _inner():
        return [
            Route(
                id="abc123",
                name="Route 1",
                distance_m=5000.0,
                duration_s=1200.0,
                coordinates=[(52.52, 13.405), (52.53, 13.406)],
                route_type=route_type,
                green_score=0.3,
                score=95.0,
            )
        ]

    return _inner()


def test_health():
    with TestClient(main.app) as client:
        resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "routing_backend" in body


def test_routes_and_gpx(monkeypatch):
    monkeypatch.setattr(main, "generate_routes", _fake_generate_routes)
    with TestClient(main.app) as client:
        resp = client.post(
            "/api/routes",
            json={"lat": 52.52, "lon": 13.405, "length_km": 5.0},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["routes"]) == 1
        route = body["routes"][0]
        assert route["gpx_url"] == "/api/routes/abc123/gpx"
        assert route["distance_km"] == 5.0

        gpx_resp = client.get("/api/routes/abc123/gpx")
        assert gpx_resp.status_code == 200
        assert "<gpx" in gpx_resp.text
        assert "attachment" in gpx_resp.headers["content-disposition"]


def test_routes_validation():
    with TestClient(main.app) as client:
        resp = client.post(
            "/api/routes",
            json={"lat": 52.52, "lon": 13.405, "length_km": 999.0},
        )
        assert resp.status_code == 422


def test_frontend_served():
    with TestClient(main.app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    assert "RunRouter" in resp.text
