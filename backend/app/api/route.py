"""
UrbanFlow — API: Safe Route Planner
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.routing.safe_router import SafeRouter
from app.simulation.simulation_engine import engine

logger = logging.getLogger("urbanflow.api.route")
router = APIRouter(prefix="/api/route", tags=["routing"])

# Router instance (initialized after graph is ready)
_router_instance: SafeRouter | None = None


def get_router() -> SafeRouter:
    global _router_instance
    if _router_instance is None or engine.graph is not None:
        _router_instance = SafeRouter(engine.graph)
    return _router_instance


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RouteRequest(BaseModel):
    start: List[float] = Field(..., min_length=2, max_length=2,
                                description="[latitude, longitude] of start point")
    end:   List[float] = Field(..., min_length=2, max_length=2,
                                description="[latitude, longitude] of end point")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/safe", summary="Compute flood-safe route")
async def compute_safe_route(req: RouteRequest) -> Dict[str, Any]:
    """
    Compute and compare a flood-safe route vs the naive shortest path.

    The safe route uses Dijkstra with edge weights penalised by current
    flood risk level (dry=1×, nuisance=2×, disruptive=10×, severe=1000×).

    The naive route uses plain travel-time weights.

    Returns both routes as coordinate lists plus comparison statistics.
    """
    if engine.graph is None:
        raise HTTPException(status_code=503, detail="Engine not ready")

    start_lat, start_lon = req.start[0], req.start[1]
    end_lat, end_lon = req.end[0], req.end[1]

    # Validate within bbox (roughly)
    from app.config import BOUNDING_BOX
    min_lon, min_lat, max_lon, max_lat = BOUNDING_BOX
    # Allow 10% margin outside bbox
    margin = 0.01
    for lat, lon in [(start_lat, start_lon), (end_lat, end_lon)]:
        if not (min_lat - margin <= lat <= max_lat + margin):
            raise HTTPException(
                status_code=400,
                detail=f"Latitude {lat} is outside study area {min_lat}–{max_lat}"
            )
        if not (min_lon - margin <= lon <= max_lon + margin):
            raise HTTPException(
                status_code=400,
                detail=f"Longitude {lon} is outside study area {min_lon}–{max_lon}"
            )

    safe_router = get_router()
    flood_state = engine.get_latest_state()

    try:
        result = safe_router.route(
            start_lat, start_lon,
            end_lat, end_lon,
            flood_state,
        )
    except Exception as e:
        logger.error(f"Route computation failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Route computation failed: {str(e)}"
        )

    return result.to_dict()
