"""
UrbanFlow v2 — Celery Task Queue [54]
[54] Celery + Redis: schedule tick-advance as async background job
"""
from __future__ import annotations

import logging
from celery import Celery
from app.config import CELERY_BROKER, CELERY_BACKEND

logger = logging.getLogger("urbanflow.tasks")

celery_app = Celery(
    "urbanflow",
    broker=CELERY_BROKER,
    backend=CELERY_BACKEND,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_track_started=True,
)

# [54] Celery task — triggered on each new synthetic radar frame
@celery_app.task(name="urbanflow.tick_advance", bind=True, max_retries=3)
def tick_advance_task(self, scenario_params: dict = None):
    """
    [54] Advance the coupled simulation by one tick.
    Triggered every 10–15 simulated minutes via Celery beat or external trigger.
    """
    try:
        from app.state import get_simulation_state
        state = get_simulation_state()
        if state is None or not state.get("coupled"):
            return {"status": "no_simulation_running"}

        coupled   = state["coupled"]
        rainfall  = state["rainfall"]
        lulc_arr  = state["lulc_arr"]

        from app.simulation.infiltration import compute_infiltration_raster
        rain_tick = rainfall.tick()
        amc_class = state.get("amc_tracker").amc_class() if state.get("amc_tracker") else 2
        net_rain  = compute_infiltration_raster(
            rain_tick["rain_rate_mm_hr"],
            lulc_arr,
            rain_tick["t_minutes"] / 60.0,
            amc_class,
        )
        from scipy.ndimage import zoom
        gs = coupled.grid_shape
        if net_rain.shape != gs:
            net_rain = zoom(net_rain.astype(float), (gs[0]/net_rain.shape[0], gs[1]/net_rain.shape[1])).astype("float32")

        result = coupled.tick(net_rain)

        # Publish to Redis pub/sub for WebSocket broadcast
        import redis, json, numpy as np
        r = redis.from_url(state.get("redis_url", "redis://redis:6379/0"))
        payload = {
            "t_minutes": result["t_minutes"],
            "max_depth_cm": float(result["depth_cm"].max()),
            "hotspot_count": len(result.get("hotspots", [])),
            "validation": result.get("validation", {}),
        }
        r.publish("urbanflow:flood_state", json.dumps(payload))

        return {"status": "ok", "t_minutes": result["t_minutes"]}

    except Exception as exc:
        logger.error(f"tick_advance_task failed: {exc}")
        raise self.retry(exc=exc, countdown=5)


@celery_app.task(name="urbanflow.retrain_blockage_model")
def retrain_blockage_model_task():
    """[25] Retrain blockage model — visibly changes flood outcomes when called."""
    from app.simulation.drainage_1d import train_blockage_model
    from app.config import BLOCKAGE_MODEL
    clf = train_blockage_model(BLOCKAGE_MODEL)
    return {"status": "retrained", "model_path": str(BLOCKAGE_MODEL)}
