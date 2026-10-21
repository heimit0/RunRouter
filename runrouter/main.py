"""FastAPI application for RunRouter.

Endpoints:
  GET  /api/health              -> status + which routing backend is active
  GET  /api/geocode?q=...       -> Nominatim search
  POST /api/routes              -> generate ranked running routes
  GET  /api/routes/{id}/gpx     -> download a generated route as GPX

The frontend (static/) is served from the same origin.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, geocode, gpx
from .generator import generate_routes
from .routing import OSRMClient

# id -> (route_dict, gpx_text). Small in-memory cache so GPX downloads work.
_ROUTE_STORE: dict[str, tuple[dict[str, Any], str]] = {}
_MAX_STORE = 100


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="RunRouter",
    description="Real-world running route finder on OpenStreetMap.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class RouteRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    length_km: float = Field(5.0, ge=0.5, le=60)
    route_type: str = Field("loop", pattern="^(loop|out_and_back)$")
    prefer: str = Field("balanced", pattern="^(balanced|green|water)$")
    count: int = Field(3, ge=1, le=6)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "routing_backend": config.OSRM_BASE_URL,
        "profile": config.OSRM_PROFILE,
        "data_sources": ["OpenStreetMap", "OSRM", "Overpass", "Nominatim"],
    }


@app.get("/api/geocode")
async def geocode_ep(q: str = Query(..., min_length=2)) -> dict[str, Any]:
    try:
        results = await geocode.geocode(q)
    except Exception as exc:  # noqa: BLE001 - surface a clean error to the UI
        raise HTTPException(status_code=502, detail=f"Geocoding failed: {exc}")
    return {"results": results}


@app.post("/api/routes")
async def routes_ep(req: RouteRequest) -> dict[str, Any]:
    client = OSRMClient()
    try:
        routes = await generate_routes(
            client,
            (req.lat, req.lon),
            req.length_km,
            route_type=req.route_type,
            prefer=req.prefer,
            count=req.count,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Route generation failed: {exc}")

    if not routes:
        raise HTTPException(
            status_code=404,
            detail="No routes could be generated for this location and length.",
        )

    out: list[dict[str, Any]] = []
    for route in routes:
        gpx_text = gpx.to_gpx(
            route.name,
            route.coordinates,
            distance_m=route.distance_m,
            duration_s=route.duration_s,
        )
        _ROUTE_STORE[route.id] = (route.to_dict(), gpx_text)
        out.append(route.to_dict(gpx_url=f"/api/routes/{route.id}/gpx"))

    # Keep the store bounded.
    while len(_ROUTE_STORE) > _MAX_STORE:
        _ROUTE_STORE.pop(next(iter(_ROUTE_STORE)))

    return {
        "start": {"lat": req.lat, "lon": req.lon},
        "length_km": req.length_km,
        "route_type": req.route_type,
        "prefer": req.prefer,
        "routes": out,
    }


@app.get("/api/routes/{route_id}/gpx")
async def gpx_ep(route_id: str) -> Response:
    entry = _ROUTE_STORE.get(route_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Route not found (may have expired).")
    route_dict, gpx_text = entry
    name = route_dict.get("name", "route")
    return Response(
        gpx_text,
        media_type="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="{name}.gpx"'},
    )


_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")
app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")


def main() -> None:
    import uvicorn

    uvicorn.run("runrouter.main:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
