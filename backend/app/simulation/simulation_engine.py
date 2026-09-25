"""
UrbanFlow — Simulation Engine
================================
Orchestrates the simulation clock, ticking all sub-models and
publishing flood state updates to Redis for WebSocket distribution.

Clock model:
  - Real wall-clock ticks every SIM_TICK_REAL_SECONDS seconds
  - Each tick advances simulation by SIM_TICK_SIM_MINUTES minutes
  - Full 180-minute window = 36 ticks at 5-min steps

State management:
  - In-memory ring buffer of the last 36 FloodState snapshots (full window)
  - Redis pub/sub: publishes JSON to 'flood:state' on every tick
  - PostgreSQL: persists snapshots every 15 sim-minutes for historical replay
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

import redis.asyncio as aioredis

from app.config import (
    FLOOD_PUBSUB_CHANNEL,
    NOWCAST_STEPS,
    REDIS_URL,
    SIM_TICK_REAL_SECONDS,
    SIM_TICK_SIM_MINUTES,
    SIM_TOTAL_MINUTES,
)
from app.simulation.drainage import DrainageModel
from app.simulation.flood_predictor import FloodPredictor, FloodState
from app.simulation.nowcast import NowcastEngine, NowcastForecast
from app.simulation.runoff import RunoffCalculator
from app.simulation.storm import StormCell, get_scenario

logger = logging.getLogger("urbanflow.engine")


class SimulationEngine:
    """Singleton simulation engine. Initialized once at app startup."""

    def __init__(self):
        self.graph = None
        self.drainage: Optional[DrainageModel] = None
        self.runoff_calc: Optional[RunoffCalculator] = None
        self.nowcast_engine: Optional[NowcastEngine] = None
        self.predictor: Optional[FloodPredictor] = None

        self.active_scenario: Optional[str] = None
        self.active_storm: Optional[StormCell] = None
        self.run_id: Optional[str] = None
        self.run_started_at: Optional[float] = None

        self.sim_clock: float = 0.0          # current simulation time (minutes)
        self.is_running: bool = False
        self.is_paused: bool = False

        # In-memory state store: t_minutes → FloodState
        self._state_store: Dict[float, FloodState] = {}
        self._latest_state: Optional[FloodState] = None

        # Node locations list (for nowcast)
        self._node_locations: List[tuple] = []   # (node_id, lat, lon)

        # Forecast (pre-computed at scenario start)
        self._forecast: Optional[NowcastForecast] = None

        # Redis
        self._redis: Optional[aioredis.Redis] = None
        self._tick_task: Optional[asyncio.Task] = None

        # Observers (for in-process WebSocket broadcast)
        self._observers: List[asyncio.Queue] = []

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(
        self,
        graph,
        voronoi_areas: Dict[str, float],
    ):
        """
        Call once after the bootstrap has loaded the road network and elevation.
        Sets up drainage, runoff, and predictor instances.
        """
        self.graph = graph
        self._node_locations = [
            (nid, data["lat"], data["lon"])
            for nid, data in graph.nodes(data=True)
        ]
        self.drainage = DrainageModel(graph)
        self.runoff_calc = RunoffCalculator(graph, voronoi_areas)
        self.nowcast_engine = NowcastEngine(timestep_minutes=15)
        self.predictor = FloodPredictor(self.drainage)
        logger.info(
            f"SimulationEngine initialized with {graph.number_of_nodes()} nodes, "
            f"{graph.number_of_edges()} edges"
        )

    # ------------------------------------------------------------------
    # Scenario management
    # ------------------------------------------------------------------

    async def start_scenario(
        self,
        scenario_name: str,
        custom_storm: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Start a new simulation scenario.

        Args:
            scenario_name:  Name from SCENARIOS dict (or 'custom')
            custom_storm:   Optional dict to override storm parameters

        Returns:
            run_id (UUID string)
        """
        if self._tick_task and not self._tick_task.done():
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass

        if scenario_name == "custom" and custom_storm:
            from app.simulation.storm import StormCell
            self.active_storm = StormCell(**custom_storm)
        else:
            self.active_storm = get_scenario(scenario_name)

        self.active_scenario = scenario_name
        self.run_id = str(uuid.uuid4())
        self.run_started_at = time.time()
        self.sim_clock = 0.0
        self.is_running = True
        self.is_paused = False
        self._state_store.clear()
        self._latest_state = None

        # Reset drainage model state
        self.drainage.reset()

        # Pre-compute full 0–180 min nowcast
        self._forecast = self.nowcast_engine.generate(
            storm=self.active_storm,
            node_locations=self._node_locations,
            t_start_minutes=0.0,
            t_end_minutes=float(SIM_TOTAL_MINUTES),
        )
        logger.info(
            f"Scenario '{scenario_name}' started | run_id={self.run_id}"
        )

        # Initialize Redis
        if self._redis is None:
            try:
                self._redis = aioredis.from_url(
                    REDIS_URL, encoding="utf-8", decode_responses=True
                )
            except Exception as e:
                logger.warning(f"Redis unavailable: {e} — will run without pub/sub")

        # Compute initial state at t=0
        await self._tick_internal(force_t=0.0)

        # Start the clock
        self._tick_task = asyncio.create_task(self._clock_loop())

        return self.run_id

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False

    # ------------------------------------------------------------------
    # State retrieval
    # ------------------------------------------------------------------

    def get_state(self, t_minutes: float) -> Optional[FloodState]:
        """Return the FloodState nearest to the requested simulation time."""
        if not self._state_store:
            return self._latest_state

        # Find nearest stored time
        stored_times = sorted(self._state_store.keys())
        nearest = min(stored_times, key=lambda t: abs(t - t_minutes))
        return self._state_store.get(nearest, self._latest_state)

    def get_latest_state(self) -> Optional[FloodState]:
        return self._latest_state

    def get_forecast_timeseries(self) -> List[Dict]:
        if self._forecast:
            return self._forecast.intensity_timeseries
        return []

    # ------------------------------------------------------------------
    # Clock loop
    # ------------------------------------------------------------------

    async def _clock_loop(self):
        """Background asyncio task: advance sim clock every SIM_TICK_REAL_SECONDS."""
        logger.info(f"Simulation clock started (tick every {SIM_TICK_REAL_SECONDS}s real time)")
        try:
            while self.is_running:
                await asyncio.sleep(SIM_TICK_REAL_SECONDS)
                if self.is_paused:
                    continue

                self.sim_clock += SIM_TICK_SIM_MINUTES
                if self.sim_clock > SIM_TOTAL_MINUTES:
                    self.sim_clock = SIM_TOTAL_MINUTES
                    logger.info("Simulation reached 180 min. Looping back to 0.")
                    self.sim_clock = 0.0
                    self.drainage.reset()

                await self._tick_internal()

        except asyncio.CancelledError:
            logger.info("Simulation clock stopped.")

    async def _tick_internal(self, force_t: Optional[float] = None):
        """Run one simulation tick and publish results."""
        t = force_t if force_t is not None else self.sim_clock

        if self._forecast is None or self.active_storm is None:
            return

        # Get rainfall from pre-computed forecast
        frame = self._forecast.at_time(t)
        rainfall_mm_hr = frame.node_intensities
        storm_center = frame.storm_center

        # Compute surface runoff Q = C·i·A
        dt_seconds = SIM_TICK_SIM_MINUTES * 60.0
        routed_runoff = self.runoff_calc.compute(rainfall_mm_hr)

        # Advance drainage model
        surcharge = self.drainage.tick(
            surface_runoff=routed_runoff,
            rainfall_mm_hr=rainfall_mm_hr,
            dt_seconds=dt_seconds,
        )

        # Produce flood prediction
        state = self.predictor.predict(
            rainfall_mm_hr=rainfall_mm_hr,
            surcharge=surcharge,
            t_minutes=t,
            run_id=self.run_id or "unknown",
            scenario_name=self.active_scenario or "unknown",
            storm_center=storm_center,
        )

        self._state_store[t] = state
        self._latest_state = state

        # Publish to Redis pub/sub
        if self._redis:
            try:
                state_dict = state.to_dict()
                await self._redis.publish(
                    FLOOD_PUBSUB_CHANNEL,
                    json.dumps(state_dict),
                )
            except Exception as e:
                logger.debug(f"Redis publish failed: {e}")

        # Notify in-process observers (WebSocket connections)
        dead = []
        for q in self._observers:
            try:
                q.put_nowait(state)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._observers.remove(q)

        logger.debug(
            f"Tick t={t:.0f}min | "
            f"severe={state.severe_count} "
            f"disruptive={state.disruptive_count} "
            f"max_depth={state.max_depth_cm:.1f}cm"
        )

    # ------------------------------------------------------------------
    # Observer pattern for WebSocket
    # ------------------------------------------------------------------

    def subscribe(self) -> asyncio.Queue:
        """Return a queue that receives FloodState objects on every tick."""
        q: asyncio.Queue = asyncio.Queue(maxsize=10)
        self._observers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self._observers:
            self._observers.remove(q)

    # ------------------------------------------------------------------
    # Graph export (for network API)
    # ------------------------------------------------------------------

    def get_network_geojson(self, current_state: Optional[FloodState] = None) -> dict:
        """
        Export full network as GeoJSON FeatureCollection.
        If current_state provided, augments nodes with flood attributes.
        """
        if self.graph is None:
            return {"type": "FeatureCollection", "features": []}

        features = []
        node_flood = {}
        if current_state:
            node_flood = {fn.node_id: fn for fn in current_state.nodes}

        # Node features
        for node_id, attrs in self.graph.nodes(data=True):
            flood = node_flood.get(node_id)
            props = {
                "type": "node",
                "node_id": node_id,
                "road_class": attrs.get("road_class", "default"),
                "elevation_m": attrs.get("elevation", 0.0),
                "predicted_depth_cm": flood.predicted_depth_cm if flood else 0.0,
                "risk_level": flood.risk_level if flood else "dry",
                "eta_minutes": flood.eta_minutes if flood else 180.0,
                "confidence": flood.confidence if flood else 0.95,
                "rainfall_mm_hr": flood.rainfall_mm_hr if flood else 0.0,
                "clogging_idx": flood.clogging_idx if flood else 0.0,
            }
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [attrs.get("lon", 80.26), attrs.get("lat", 13.085)],
                },
                "properties": props,
            })

        # Edge features
        for u, v, attrs in self.graph.edges(data=True):
            u_attrs = self.graph.nodes[u]
            v_attrs = self.graph.nodes[v]
            u_flood = node_flood.get(u)
            v_flood = node_flood.get(v)
            # Edge risk = worse of two endpoint risks
            risk_order = {"dry": 0, "nuisance": 1, "disruptive": 2, "severe": 3}
            u_risk = u_flood.risk_level if u_flood else "dry"
            v_risk = v_flood.risk_level if v_flood else "dry"
            edge_risk = u_risk if risk_order.get(u_risk, 0) >= risk_order.get(v_risk, 0) else v_risk
            avg_depth = (
                ((u_flood.predicted_depth_cm if u_flood else 0.0) +
                 (v_flood.predicted_depth_cm if v_flood else 0.0)) / 2
            )
            props = {
                "type": "edge",
                "from_node": u,
                "to_node": v,
                "road_class": attrs.get("road_class", "default"),
                "length_m": attrs.get("length_m", 100.0),
                "risk_level": edge_risk,
                "predicted_depth_cm": avg_depth,
                "pipe_capacity_m3s": attrs.get("pipe_capacity_m3s", 0.2),
            }
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [u_attrs.get("lon", 80.26), u_attrs.get("lat", 13.085)],
                        [v_attrs.get("lon", 80.26), v_attrs.get("lat", 13.085)],
                    ],
                },
                "properties": props,
            })

        return {"type": "FeatureCollection", "features": features}


# Global singleton
engine = SimulationEngine()
