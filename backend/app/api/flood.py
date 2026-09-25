"""
UrbanFlow — API: Flood State
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.simulation.simulation_engine import engine

logger = logging.getLogger("urbanflow.api.flood")
router = APIRouter(prefix="/api/flood", tags=["flood"])


@router.get("/state", summary="Get flood state at simulation time t")
async def get_flood_state(
    t: float = Query(default=-1, description="Simulation time in minutes (0–180). -1 = latest"),
) -> Dict[str, Any]:
    """
    Returns the complete flood prediction state at simulation time t.

    Each node includes:
    - predicted_depth_cm (flood depth on road surface)
    - risk_level (dry / nuisance / disruptive / severe)
    - eta_minutes (estimated time until flooding onset, 0 = already flooded)
    - confidence (0–1, decreases with forecast horizon)
    - rainfall_mm_hr (current rainfall intensity)
    - clogging_idx (0–1 drain clogging factor)
    """
    if engine.graph is None:
        raise HTTPException(status_code=503, detail="Engine not ready")

    if t < 0:
        state = engine.get_latest_state()
    else:
        state = engine.get_state(t)

    if state is None:
        raise HTTPException(status_code=404, detail="No simulation state available yet")

    return state.to_dict()


@router.get("/summary", summary="Lightweight summary (no per-node data)")
async def get_flood_summary() -> Dict[str, Any]:
    """
    Returns the summary-only view of the latest flood state.
    Useful for polling overview stats without the full node payload.
    """
    state = engine.get_latest_state()
    if state is None:
        return {"status": "no_simulation"}

    return {
        "t_minutes":         state.t_minutes,
        "run_id":            state.run_id,
        "scenario_name":     state.scenario_name,
        "storm_center":      {"lat": state.storm_center[0], "lon": state.storm_center[1]},
        "mean_depth_cm":     round(state.mean_depth_cm, 1),
        "max_depth_cm":      round(state.max_depth_cm, 1),
        "severe_count":      state.severe_count,
        "disruptive_count":  state.disruptive_count,
        "nuisance_count":    state.nuisance_count,
        "dry_count":         state.dry_count,
        "drainage_util_pct": round(state.drainage_util_pct, 1),
    }


@router.get("/incident-feed", summary="Latest severe/disruptive nodes for incident feed")
async def get_incident_feed(
    limit: int = Query(default=20, ge=1, le=100),
) -> List[Dict[str, Any]]:
    """
    Returns the most recent severe and disruptive flood nodes,
    sorted by depth (most severe first). Used by the Incident Feed panel.
    """
    state = engine.get_latest_state()
    if state is None:
        return []

    critical = [
        fn.to_dict() for fn in state.nodes
        if fn.risk_level in ("severe", "disruptive")
    ]
    critical.sort(key=lambda n: -n["predicted_depth_cm"])
    return critical[:limit]
