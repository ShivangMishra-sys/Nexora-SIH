"""
UrbanFlow v2 — FastAPI Application
[61] /api/v1/route, /api/v1/nowcast, /api/flood-state, /ws/flood-stream
[42] MQTT subscriber stub
[62] Alert dispatch (Twilio/FCM stub)
[71] Address/landmark geocoding via Nominatim
[54] Celery task trigger endpoints
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import BBOX_WGS84, REDIS_URL, MQTT_BROKER_HOST, MQTT_BROKER_PORT

logger = logging.getLogger("urbanflow.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")


# ---------------------------------------------------------------------------
# Application lifespan — bootstrap on startup
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run bootstrap in a thread to avoid blocking the event loop."""
    loop = asyncio.get_event_loop()
    try:
        logger.info("Starting UrbanFlow v2 bootstrap …")
        ctx = await loop.run_in_executor(None, _run_bootstrap)
        app.state.ctx = ctx
        logger.info("Bootstrap complete — API ready")
        # Start MQTT subscriber [42]
        asyncio.create_task(_mqtt_subscriber())
        # Start simulation tick loop
        asyncio.create_task(_simulation_loop(app))
    except Exception as e:
        logger.error(f"Bootstrap failed: {e}. Running with empty state.")
        app.state.ctx = None
    yield
    # Shutdown
    ctx = getattr(app.state, "ctx", None)
    if ctx and ctx.get("swmm_runner"):
        ctx["swmm_runner"].close()
    logger.info("UrbanFlow v2 shutdown complete")


def _run_bootstrap():
    from app.startup.bootstrap import run_bootstrap
    from app.state import set_simulation_state
    from app.simulation.infiltration import AntecedentMoistureTracker
    ctx = run_bootstrap()
    ctx["redis_url"] = REDIS_URL
    ctx["amc_tracker"] = AntecedentMoistureTracker()
    ctx["last_flood_state"] = None
    ctx["scenario_active"] = "cloudburst_extreme"
    set_simulation_state(ctx)
    return ctx


async def _simulation_loop(app: FastAPI):
    """Background tick loop: advance simulation every 10s real time."""
    from app.simulation.infiltration import compute_infiltration_raster
    from scipy.ndimage import zoom

    while True:
        await asyncio.sleep(10)
        try:
            ctx = getattr(app.state, "ctx", None)
            if ctx is None:
                continue
            coupled  = ctx.get("coupled")
            rainfall = ctx.get("rainfall")
            lulc_arr = ctx.get("lulc_arr")
            tracker  = ctx.get("amc_tracker")
            if not coupled or not rainfall:
                continue

            rain_tick = rainfall.tick()
            amc = tracker.amc_class() if tracker else 2
            if tracker:
                tracker.update(float(rain_tick["rain_rate_mm_hr"].mean()))

            net_rain = compute_infiltration_raster(
                rain_tick["rain_rate_mm_hr"], lulc_arr,
                rain_tick["t_minutes"] / 60.0, amc,
            )
            gs = coupled.grid_shape
            if net_rain.shape != gs:
                net_rain = zoom(
                    net_rain.astype(float),
                    (gs[0] / net_rain.shape[0], gs[1] / net_rain.shape[1])
                ).astype(np.float32)

            result = coupled.tick(net_rain)
            ctx["last_flood_state"] = result

            # Broadcast over WebSocket to all connected clients
            msg = _build_ws_message(result, ctx)
            await _ws_broadcast(msg)

            # Publish to Redis
            await _redis_publish(msg)

        except Exception as e:
            logger.debug(f"Simulation loop tick error: {e}")


# ---------------------------------------------------------------------------
app = FastAPI(
    title="UrbanFlow v2 — Flood Nowcasting & Safe-Routing",
    version="2.0.0",
    description="SIH 2026 | Team Nexora | PS ID 26085 | Anna Nagar, Chennai",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket connection pool
_ws_clients: List[WebSocket] = []


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class ScenarioRunRequest(BaseModel):
    scenario: str = "cloudburst_extreme"
    intensity_dbz: float = 50.0
    storm_center: List[float] = [0.5, 0.5]
    radius_fraction: float = 0.25
    drain_blockage_pct: float = 0.0    # [72] what-if slider

class RouteRequest(BaseModel):
    start: List[float]   # [lat, lon]
    end:   List[float]   # [lat, lon]
    vehicle_class: str = "car"

class AlertTestRequest(BaseModel):
    message: str = "Test flood alert from UrbanFlow"
    depth_cm: float = 25.0

class GeocodingRequest(BaseModel):
    query: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ctx(app_state) -> Optional[Dict]:
    return getattr(app_state, "ctx", None)

def _depth_at_nodes(ctx: Dict) -> Dict[str, float]:
    """Extract per-node depth from current grid state."""
    state = ctx.get("last_flood_state")
    if state is None:
        return {}
    depth_cm = state.get("depth_cm", np.zeros((10, 10)))
    node_grid = ctx.get("node_grid_map", {})
    result = {}
    for node_id, (r, c) in node_grid.items():
        r = min(r, depth_cm.shape[0] - 1)
        c = min(c, depth_cm.shape[1] - 1)
        result[str(node_id)] = float(depth_cm[r, c])
    return result

def _build_ws_message(result: Dict, ctx: Dict) -> str:
    depth_cm = result.get("depth_cm", np.zeros((10, 10)))
    risk_grid = result.get("risk_grid", np.zeros_like(depth_cm, dtype=np.uint8))
    payload = {
        "type": "flood_state",
        "t_minutes": result.get("t_minutes", 0),
        "max_depth_cm": float(depth_cm.max()),
        "mean_depth_cm": float(depth_cm.mean()),
        "severe_count": int((depth_cm > 30).sum()),
        "critical_count": int(((depth_cm > 15) & (depth_cm <= 30)).sum()),
        "hotspots": result.get("hotspots", []),
        "validation": result.get("validation", {}),
        "scenario": ctx.get("scenario_active", ""),
    }
    return json.dumps(payload)

async def _ws_broadcast(msg: str):
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_text(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.remove(ws)

async def _redis_publish(msg: str):
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(REDIS_URL)
        await r.publish("urbanflow:flood_state", msg)
        await r.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# [42] MQTT subscriber stub
# ---------------------------------------------------------------------------
async def _mqtt_subscriber():
    """[42] paho-mqtt subscriber for ultrasonic water-level sensor telemetry."""
    try:
        import paho.mqtt.client as mqtt

        def on_message(client, userdata, msg):
            try:
                data = json.loads(msg.payload)
                logger.info(f"[42] MQTT sensor: {msg.topic} → {data}")
            except Exception:
                pass

        client = mqtt.Client()
        client.on_message = on_message
        client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, keepalive=60)
        client.subscribe(MQTT_TOPIC_SENSORS if hasattr(MQTT_BROKER_HOST, '__str__') else "#")
        client.loop_start()
        logger.info(f"[42] MQTT subscriber running on {MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}")
    except Exception as e:
        logger.info(f"[42] MQTT subscriber not started (broker unavailable): {e}")

MQTT_TOPIC_SENSORS = "urbanflow/sensors/#"


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    ctx = _ctx(app.state)
    return {
        "status": "ok",
        "bootstrap": ctx is not None,
        "scenario": ctx.get("scenario_active") if ctx else None,
    }


@app.post("/api/scenario/run")
def run_scenario(req: ScenarioRunRequest, background: BackgroundTasks):
    """[72] Start/switch storm scenario. 'drain_blockage_pct' = what-if slider."""
    ctx = _ctx(app.state)
    if ctx is None:
        raise HTTPException(503, "Simulation not initialized")

    rainfall = ctx["rainfall"]
    rainfall.set_storm(req.intensity_dbz, tuple(req.storm_center), req.radius_fraction)
    ctx["scenario_active"] = req.scenario

    # [72] What-if: reweight blockage derating and regenerate .inp
    if req.drain_blockage_pct > 0:
        background.add_task(
            _apply_blockage_whatif, ctx, req.drain_blockage_pct / 100.0
        )

    return {"status": "running", "scenario": req.scenario}


def _apply_blockage_whatif(ctx: Dict, blockage_frac: float):
    """[72] Degrade pipe capacities by blockage_frac and regenerate SWMM .inp."""
    try:
        from app.simulation.drainage_1d import (
            generate_inp_from_osm_graph, load_blockage_model, compute_blockage_derating
        )
        from app.data.road_network import prepare_graph_for_swmm
        import pickle, numpy as np

        simple_G = ctx["simple_G"]
        clf = load_blockage_model()
        derating = compute_blockage_derating(simple_G, clf)
        # Override: scale all deratings by additional blockage factor
        boosted = {k: max(0.2, v * (1 - blockage_frac)) for k, v in derating.items()}
        SWMM_INP.unlink(missing_ok=True)
        generate_inp_from_osm_graph(simple_G, SWMM_INP, blockage_derating=boosted)
        ctx["swmm_runner"].close()
        from app.simulation.drainage_1d import SWMMRunner
        ctx["swmm_runner"] = SWMMRunner(SWMM_INP)
        ctx["swmm_runner"].start()
        logger.info(f"[72] Blockage what-if applied: {blockage_frac*100:.0f}% capacity reduction")
    except Exception as e:
        logger.error(f"What-if blockage failed: {e}")


@app.get("/api/flood/state")
def get_flood_state(t: Optional[int] = None):
    """[48] Return flood state at time t (cached snapshot) or latest."""
    if t is not None:
        from app.simulation.coupling import load_snapshot
        snap = load_snapshot(t)
        if snap:
            return _serialize_state(snap)

    ctx = _ctx(app.state)
    if ctx is None or ctx.get("last_flood_state") is None:
        raise HTTPException(503, "No flood state available yet")
    return _serialize_state(ctx["last_flood_state"])


def _serialize_state(state: Dict) -> Dict:
    """Convert numpy arrays to JSON-serialisable form."""
    result = {}
    depth_cm = state.get("depth_cm", np.zeros((10, 10)))
    risk_grid = state.get("risk_grid", np.zeros_like(depth_cm, dtype=np.uint8))

    if isinstance(depth_cm, np.ndarray):
        from app.simulation.coupling import RISK_COLORS
        # Sample nodes from grid for frontend rendering
        rows, cols = depth_cm.shape
        sample_step = max(1, min(rows, cols) // 40)
        nodes = []
        for r in range(0, rows, sample_step):
            for c in range(0, cols, sample_step):
                d = float(depth_cm[r, c])
                risk_idx = int(risk_grid[r, c]) if isinstance(risk_grid, np.ndarray) else 0
                risk_label = ["safe", "caution", "critical", "impassable"][risk_idx]
                lat = BBOX_WGS84[3] - (r / rows) * (BBOX_WGS84[3] - BBOX_WGS84[1])
                lon = BBOX_WGS84[0] + (c / cols) * (BBOX_WGS84[2] - BBOX_WGS84[0])
                nodes.append({
                    "lat": lat, "lon": lon,
                    "depth_cm": round(d, 2),
                    "risk": risk_label,
                    "color": RISK_COLORS.get(risk_idx, "#6b7280"),
                })

        result["nodes"] = nodes
        result["max_depth_cm"] = float(depth_cm.max())
        result["mean_depth_cm"] = float(depth_cm.mean())
        result["severe_count"] = int((depth_cm > 30).sum())
        result["critical_count"] = int(((depth_cm > 15) & (depth_cm <= 30)).sum())
    else:
        result.update(state)

    result["t_minutes"] = state.get("t_minutes", 0)
    result["hotspots"] = state.get("hotspots", [])
    result["validation"] = state.get("validation", {})
    return result


@app.get("/api/flood/summary")
def get_flood_summary():
    ctx = _ctx(app.state)
    state = ctx.get("last_flood_state") if ctx else None
    if not state:
        return {"status": "no_data"}
    depth_cm = state.get("depth_cm", np.zeros((10, 10)))
    return {
        "max_depth_cm": float(depth_cm.max()),
        "mean_depth_cm": float(depth_cm.mean()),
        "safe_pct": float((depth_cm < 5).sum() / depth_cm.size * 100),
        "caution_pct": float(((depth_cm >= 5) & (depth_cm < 15)).sum() / depth_cm.size * 100),
        "critical_pct": float(((depth_cm >= 15) & (depth_cm < 30)).sum() / depth_cm.size * 100),
        "impassable_pct": float((depth_cm >= 30).sum() / depth_cm.size * 100),
        "hotspots": state.get("hotspots", []),
        "validation": state.get("validation", {}),
    }


@app.post("/api/v1/route")
def compute_route(req: RouteRequest):
    """[57][60][61] Compute flood-safe route between two lat/lon points."""
    ctx = _ctx(app.state)
    if ctx is None:
        raise HTTPException(503, "Simulation not initialized")

    from app.routing.safe_router import nearest_node, compute_safe_route
    G = ctx.get("G") or ctx.get("simple_G")
    if G is None:
        raise HTTPException(503, "Road network not loaded")

    depth_map = _depth_at_nodes(ctx)
    start_lat, start_lon = req.start[0], req.start[1]
    end_lat, end_lon     = req.end[0],   req.end[1]

    start_node = nearest_node(G, start_lat, start_lon)
    end_node   = nearest_node(G, end_lat,   end_lon)

    result = compute_safe_route(G, depth_map, start_node, end_node, req.vehicle_class)
    if result is None:
        raise HTTPException(404, "No route found between selected points")
    return result


@app.get("/api/v1/nowcast")
def get_nowcast():
    """[48][61] Current + forecast rainfall grid at all horizons."""
    ctx = _ctx(app.state)
    if ctx is None:
        raise HTTPException(503, "Simulation not initialized")
    rainfall = ctx.get("rainfall")
    if rainfall is None:
        raise HTTPException(503, "Rainfall system not ready")

    forecasts = rainfall.get_forecast()
    result = {}
    for t_min, grid in forecasts.items():
        if isinstance(grid, np.ndarray):
            result[str(t_min)] = {
                "max_mm_hr":  float(grid.max()),
                "mean_mm_hr": float(grid.mean()),
            }
    return {"bbox": BBOX_WGS84, "forecasts_mm_hr": result}


@app.get("/api/network/graph")
def get_network_graph():
    """GeoJSON FeatureCollection of nodes + edges for map rendering."""
    ctx = _ctx(app.state)
    if ctx is None:
        return {"type": "FeatureCollection", "features": []}

    G = ctx.get("G") or ctx.get("simple_G")
    if G is None:
        return {"type": "FeatureCollection", "features": []}

    depth_map = _depth_at_nodes(ctx)
    features = []

    # Node features
    for node, data in list(G.nodes(data=True))[:500]:   # cap for performance
        lon = data.get("x", data.get("lon", 80.21))
        lat = data.get("y", data.get("lat", 13.09))
        d = depth_map.get(str(node), 0.0)
        risk = "safe" if d < 5 else "caution" if d < 15 else "critical" if d < 30 else "impassable"
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"node_id": str(node), "depth_cm": d, "risk": risk,
                           "elevation": data.get("elevation", 5.0)},
        })

    # Edge features
    for u, v, data in list(G.edges(data=True))[:1000]:
        u_data = G.nodes[u]; v_data = G.nodes[v]
        u_lon = u_data.get("x", u_data.get("lon", 80.21))
        u_lat = u_data.get("y", u_data.get("lat", 13.09))
        v_lon = v_data.get("x", v_data.get("lon", 80.21))
        v_lat = v_data.get("y", v_data.get("lat", 13.09))
        d = max(depth_map.get(str(u), 0.0), depth_map.get(str(v), 0.0))
        risk = "safe" if d < 5 else "caution" if d < 15 else "critical" if d < 30 else "impassable"
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [[u_lon, u_lat], [v_lon, v_lat]]},
            "properties": {"depth_cm": d, "risk": risk,
                           "highway": data.get("highway", ""),
                           "high_risk": bool(data.get("high_risk_depression", False))},
        })

    return {"type": "FeatureCollection", "features": features}


@app.get("/api/network/bbox")
def get_bbox():
    return {"bbox": BBOX_WGS84, "city": "Anna Nagar, Chennai"}


@app.get("/api/snapshots")
def list_snapshots():
    """[48] List available cached forecast snapshots."""
    from app.simulation.coupling import list_available_snapshots
    return {"available_minutes": list_available_snapshots()}


@app.post("/api/alerts/test")
async def test_alert(req: AlertTestRequest, background: BackgroundTasks):
    """[62] Dispatch a test alert via Twilio/FCM."""
    background.add_task(_dispatch_alert, req.message, req.depth_cm)
    return {"status": "alert_dispatched", "message": req.message}


def _dispatch_alert(message: str, depth_cm: float):
    """[62] FastAPI BackgroundTasks + Twilio/FCM (stub with real call structure)."""
    from app.config import TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM, FCM_SERVER_KEY

    if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
        try:
            from twilio.rest import Client
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            client.messages.create(
                body=f"[UrbanFlow] {message} | Depth: {depth_cm:.1f}cm",
                from_=TWILIO_FROM,
                to="+910000000000",   # replace with real recipient
            )
            logger.info("[62] Twilio SMS alert sent")
        except Exception as e:
            logger.warning(f"[62] Twilio failed: {e}")

    if FCM_SERVER_KEY:
        try:
            import requests
            requests.post(
                "https://fcm.googleapis.com/fcm/send",
                headers={"Authorization": f"key={FCM_SERVER_KEY}",
                         "Content-Type": "application/json"},
                json={"to": "/topics/urbanflow_alerts",
                      "data": {"message": message, "depth_cm": depth_cm}},
                timeout=5,
            )
            logger.info("[62] FCM push alert sent")
        except Exception as e:
            logger.warning(f"[62] FCM failed: {e}")

    logger.info(f"[62] Alert dispatched: {message} (depth={depth_cm}cm)")


@app.get("/api/v1/geocode")
def geocode(q: str):
    """[71] Address/landmark search via Nominatim."""
    try:
        from geopy.geocoders import Nominatim
        geolocator = Nominatim(user_agent="UrbanFlow-SIH2026")
        location = geolocator.geocode(f"{q}, Anna Nagar, Chennai")
        if location:
            return {"lat": location.latitude, "lon": location.longitude,
                    "address": location.address}
        return {"error": "not_found"}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/simulation/retrain-blockage")
def retrain_blockage():
    """[25] Retrain blockage model — visibly changes flood outcomes."""
    try:
        from app.tasks import retrain_blockage_model_task
        task = retrain_blockage_model_task.delay()
        return {"status": "retraining_scheduled", "task_id": str(task.id)}
    except Exception:
        # Fallback: run synchronously
        from app.simulation.drainage_1d import train_blockage_model
        train_blockage_model()
        return {"status": "retrained_sync"}


@app.get("/api/validation")
def get_validation():
    """[64] Current model accuracy vs. seeded ground truth."""
    ctx = _ctx(app.state)
    state = ctx.get("last_flood_state") if ctx else None
    if not state:
        return {"error": "no_state"}
    return state.get("validation", {})


# ---------------------------------------------------------------------------
# WebSocket — live flood stream [ws/flood-stream]
# ---------------------------------------------------------------------------
@app.websocket("/ws/flood-stream")
async def websocket_flood_stream(ws: WebSocket):
    await ws.accept()
    _ws_clients.append(ws)
    try:
        # Send current state immediately on connect
        ctx = _ctx(app.state)
        if ctx and ctx.get("last_flood_state"):
            msg = _build_ws_message(ctx["last_flood_state"], ctx)
            await ws.send_text(msg)

        # Keep alive + receive any client messages
        while True:
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                await ws.send_text(json.dumps({"type": "keepalive"}))
    except WebSocketDisconnect:
        pass
    finally:
        if ws in _ws_clients:
            _ws_clients.remove(ws)
