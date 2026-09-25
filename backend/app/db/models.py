"""
UrbanFlow — Database Models (SQLAlchemy + PostGIS)
====================================================
Stores simulation runs and periodic snapshots for historical replay
and recalibration.

Tables:
  simulation_runs  — metadata per scenario run
  network_snapshots — flood state snapshots (persisted every 15 sim-min)
  road_nodes        — the bootstrapped road network nodes (PostGIS POINT)
  road_edges        — the bootstrapped road network edges (PostGIS LINESTRING)
"""
from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class SimulationRun(Base):
    __tablename__ = "simulation_runs"

    id            = Column(String(36), primary_key=True)  # UUID
    scenario_name = Column(String(64), nullable=False)
    started_at    = Column(DateTime, default=datetime.datetime.utcnow)
    ended_at      = Column(DateTime, nullable=True)
    status        = Column(String(16), default="running")   # running|completed|error
    config_json   = Column(JSON, nullable=True)
    node_count    = Column(Integer, default=0)
    edge_count    = Column(Integer, default=0)


class NetworkSnapshot(Base):
    """
    Persisted flood state at a specific simulation time.
    Enables historical replay and long-term recalibration.
    """
    __tablename__ = "network_snapshots"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    run_id     = Column(String(36), ForeignKey("simulation_runs.id"), nullable=False, index=True)
    t_minutes  = Column(Float, nullable=False, index=True)
    state_json = Column(JSON, nullable=False)   # full FloodState.to_dict()
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class RoadNode(Base):
    """Bootstrapped road network node (manhole/inlet proxy)."""
    __tablename__ = "road_nodes"

    id         = Column(String(32), primary_key=True)   # OSM node ID
    lat        = Column(Float, nullable=False)
    lon        = Column(Float, nullable=False)
    elevation  = Column(Float, default=0.0)
    road_class = Column(String(32), default="default")
    # PostGIS geometry stored as WKT for simplicity (no GeoAlchemy2 required)
    geom_wkt   = Column(Text, nullable=True)


class RoadEdge(Base):
    """Bootstrapped road network edge (drain pipe proxy)."""
    __tablename__ = "road_edges"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    from_node_id       = Column(String(32), ForeignKey("road_nodes.id"), nullable=False)
    to_node_id         = Column(String(32), ForeignKey("road_nodes.id"), nullable=False)
    road_class         = Column(String(32), default="default")
    length_m           = Column(Float, default=100.0)
    pipe_capacity_m3s  = Column(Float, default=0.2)
    slope              = Column(Float, default=0.0)
    osm_way_id         = Column(Integer, default=0)
    # PostGIS geometry stored as WKT
    geom_wkt           = Column(Text, nullable=True)
