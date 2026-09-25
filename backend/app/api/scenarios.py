"""
UrbanFlow — API: Scenario Management
"""
from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.simulation.simulation_engine import engine
from app.simulation.storm import list_scenarios, SCENARIOS

logger = logging.getLogger("urbanflow.api.scenarios")
router = APIRouter(prefix="/api/scenario", tags=["scenario"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class CustomStormConfig(BaseModel):
    center_lat:      float = Field(13.075, description="Storm center latitude")
    center_lon:      float = Field(80.215, description="Storm center longitude")
    intensity_mm_hr: float = Field(60.0, ge=0, le=300, description="Peak intensity mm/hr")
    radius_km:       float = Field(3.0, ge=0.5, le=20, description="Gaussian radius km")
    vel_lat_ms:      float = Field(0.3, description="Northward velocity m/s")
    vel_lon_ms:      float = Field(1.5, description="Eastward velocity m/s")
    decay_rate:      float = Field(0.003, ge=0, description="Temporal decay 1/min")
    start_time_min:  float = Field(0.0)
    end_time_min:    float = Field(180.0)


class RunScenarioRequest(BaseModel):
    scenario:     str            = Field("cloudburst_extreme", description="Scenario name or 'custom'")
    custom_storm: Optional[CustomStormConfig] = Field(None, description="Custom storm config (if scenario='custom')")


class RunScenarioResponse(BaseModel):
    run_id:       str
    scenario:     str
    started_at:   str
    node_count:   int
    edge_count:   int
    message:      str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/list", summary="List available scenarios")
async def list_available_scenarios() -> List[Dict[str, Any]]:
    """Return metadata about all built-in storm scenarios."""
    return list_scenarios()


@router.post("/run", response_model=RunScenarioResponse, summary="Start a simulation run")
async def run_scenario(req: RunScenarioRequest) -> RunScenarioResponse:
    """
    Start a new simulation run with the specified storm scenario.

    Resets the simulation state and begins the clock loop. The flood
    state will start updating immediately and be available via:
    - GET /api/flood-state
    - WS  /ws/flood-stream
    """
    if engine.graph is None:
        raise HTTPException(
            status_code=503,
            detail="Simulation engine not initialized. Bootstrap may still be running."
        )

    valid_scenarios = list(SCENARIOS.keys()) + ["custom"]
    if req.scenario not in valid_scenarios:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown scenario '{req.scenario}'. Valid: {valid_scenarios}"
        )

    if req.scenario == "custom" and req.custom_storm is None:
        raise HTTPException(
            status_code=400,
            detail="custom_storm config is required when scenario='custom'"
        )

    custom_dict = req.custom_storm.model_dump() if req.custom_storm else None
    run_id = await engine.start_scenario(req.scenario, custom_dict)

    return RunScenarioResponse(
        run_id=run_id,
        scenario=req.scenario,
        started_at=datetime.datetime.utcnow().isoformat() + "Z",
        node_count=engine.graph.number_of_nodes() if engine.graph else 0,
        edge_count=engine.graph.number_of_edges() if engine.graph else 0,
        message=f"Scenario '{req.scenario}' started. Flood state streaming every {5} sim-minutes.",
    )


@router.post("/pause", summary="Pause simulation clock")
async def pause_simulation():
    engine.pause()
    return {"status": "paused", "sim_clock_minutes": engine.sim_clock}


@router.post("/resume", summary="Resume simulation clock")
async def resume_simulation():
    engine.resume()
    return {"status": "running", "sim_clock_minutes": engine.sim_clock}


@router.get("/status", summary="Get current simulation status")
async def get_status():
    return {
        "is_running":      engine.is_running,
        "is_paused":       engine.is_paused,
        "sim_clock_min":   engine.sim_clock,
        "run_id":          engine.run_id,
        "scenario":        engine.active_scenario,
        "node_count":      engine.graph.number_of_nodes() if engine.graph else 0,
        "edge_count":      engine.graph.number_of_edges() if engine.graph else 0,
        "intensity_timeseries": engine.get_forecast_timeseries(),
    }
