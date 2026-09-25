"""
UrbanFlow — WebSocket: Live Flood Stream
=========================================
Pushes FloodState JSON to all connected clients on every simulation tick.
Uses the SimulationEngine's observer queue pattern (no Redis required for
in-process clients; Redis pub/sub handles multi-process scalability).
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.simulation.simulation_engine import engine

logger = logging.getLogger("urbanflow.api.websocket")
router = APIRouter(tags=["websocket"])


@router.websocket("/ws/flood-stream")
async def flood_stream(websocket: WebSocket):
    """
    WebSocket endpoint — push FloodState JSON every simulation tick.

    Message format:
    {
      "t_minutes": 15.0,
      "run_id": "uuid",
      "scenario_name": "cloudburst_extreme",
      "storm_center": {"lat": 13.08, "lon": 80.23},
      "summary": { ... },
      "nodes": [ { "node_id": ..., "risk_level": ..., ... }, ... ]
    }

    Connect with:
      ws://localhost:8000/ws/flood-stream
    """
    await websocket.accept()
    logger.info(f"WebSocket client connected: {websocket.client}")

    # Subscribe to engine tick notifications
    queue = engine.subscribe()

    # Send the current state immediately on connect (no waiting for next tick)
    current = engine.get_latest_state()
    if current:
        try:
            await websocket.send_text(json.dumps(current.to_dict()))
        except Exception:
            pass

    try:
        while True:
            try:
                # Wait for next flood state update (with timeout for keepalive)
                state = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_text(json.dumps(state.to_dict()))
            except asyncio.TimeoutError:
                # Send keepalive ping
                try:
                    await websocket.send_text(json.dumps({"type": "keepalive"}))
                except Exception:
                    break
    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected: {websocket.client}")
    except Exception as e:
        logger.warning(f"WebSocket error: {e}")
    finally:
        engine.unsubscribe(queue)
