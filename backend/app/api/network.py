"""
UrbanFlow — API: Network Graph Export
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from app.simulation.simulation_engine import engine

logger = logging.getLogger("urbanflow.api.network")
router = APIRouter(prefix="/api/network", tags=["network"])


@router.get("/graph", summary="Full network as GeoJSON FeatureCollection")
async def get_network_graph(
    include_flood: bool = Query(
        default=True,
        description="Whether to augment node/edge properties with current flood state"
    ),
) -> Dict[str, Any]:
    """
    Returns the full road/drainage network as a GeoJSON FeatureCollection.

    Each feature carries:
    - For nodes (type=node): lat/lon, elevation, road_class, risk_level, depth, ETA
    - For edges (type=edge): road_class, length_m, risk_level, avg_depth

    This is used by the frontend MapLibre GL JS layers for initial map render.
    The WebSocket stream /ws/flood-stream then pushes incremental updates.
    """
    if engine.graph is None:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    current_state = engine.get_latest_state() if include_flood else None
    geojson = engine.get_network_geojson(current_state)
    return geojson


@router.get("/bbox", summary="Study area bounding box")
async def get_bbox() -> Dict[str, Any]:
    from app.config import BOUNDING_BOX, BBOX_CENTER, CITY_NAME
    return {
        "city": CITY_NAME,
        "bbox": {
            "min_lon": BOUNDING_BOX[0],
            "min_lat": BOUNDING_BOX[1],
            "max_lon": BOUNDING_BOX[2],
            "max_lat": BOUNDING_BOX[3],
        },
        "center": {"lat": BBOX_CENTER[0], "lon": BBOX_CENTER[1]},
    }
