"""
UrbanFlow v2 — Global simulation state store.
Holds the live coupled simulation objects accessible across FastAPI + Celery.
"""
from __future__ import annotations
from typing import Optional, Dict, Any

_state: Optional[Dict[str, Any]] = None


def set_simulation_state(state: Dict[str, Any]) -> None:
    global _state
    _state = state


def get_simulation_state() -> Optional[Dict[str, Any]]:
    return _state
