"""
UrbanFlow — Drainage Network Model
=====================================
Models the stormwater drainage network as a directed graph (NetworkX).

Nodes = road intersections (treated as manholes / storm drain inlets)
Edges = road segments (treated as drain pipes)

At each simulation tick:
  1. Incoming surface runoff (from runoff.py) is added to each node's volume.
  2. Each pipe (edge) drains water from upstream to downstream at its effective capacity.
  3. If water volume at a node exceeds the node's storage capacity, the excess
     becomes "surcharge" — water that backs up onto the street surface.
  4. Surcharge depth at each node is the primary flood depth signal.

Clogging Index Formula (documented, callable):
  ─────────────────────────────────────────────
  CI(node) = min(1, w₁·RC + w₂·(CR/100) + w₃·GS)

  where:
    RC  — road_class_factor (0–1): local/service→1.0, arterial→0.3
    CR  — cumulative rainfall (mm) at node since scenario start
    GS  — grime_seed ∈ [0,1]: seeded random "baseline fouling" per node
    w₁=0.30, w₂=0.40, w₃=0.30 (weights sum to 1)

  effective_capacity(pipe) = base_capacity_m3s × (1 − CI(upstream_node))

  Interpretation: a node on a local road, under heavy rain, with high
  baseline fouling → CI ≈ 0.9 → pipe effectively at 10% of design capacity.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import networkx as nx

from app.config import (
    GRIME_RANDOM_SEED,
    NODE_CAPACITY_M3_BY_ROAD_CLASS,
    PIPE_CAPACITY_BY_ROAD_CLASS,
)


# ---------------------------------------------------------------------------
# Clogging Index
# ---------------------------------------------------------------------------

ROAD_CLASS_FACTOR = {
    "motorway":     0.10,   # well-maintained, rarely clogged
    "trunk":        0.15,
    "primary":      0.20,
    "secondary":    0.30,
    "tertiary":     0.45,
    "residential":  0.70,
    "service":      0.85,
    "unclassified": 0.60,
    "path":         0.95,
    "footway":      1.00,
    "default":      0.60,
}


def clogging_index(
    road_class: str,
    cumulative_rain_mm: float,
    grime_seed: float,
    w1: float = 0.30,
    w2: float = 0.40,
    w3: float = 0.30,
) -> float:
    """
    Compute the clogging index CI ∈ [0, 1] for a drainage node.

    Formula:
        CI = min(1, w1·RC + w2·(CR/100) + w3·GS)

    Args:
        road_class:          OSM highway tag value
        cumulative_rain_mm:  Total rainfall (mm) accumulated at this node
                             since the scenario started
        grime_seed:          Per-node seeded random baseline fouling [0, 1]
        w1, w2, w3:         Weighting factors (default: 0.30, 0.40, 0.30)

    Returns:
        CI ∈ [0, 1] — higher means more blockage
    """
    RC  = ROAD_CLASS_FACTOR.get(road_class, ROAD_CLASS_FACTOR["default"])
    CR  = min(cumulative_rain_mm, 100.0)   # cap at 100 mm for normalisation
    GS  = grime_seed
    return min(1.0, w1 * RC + w2 * (CR / 100.0) + w3 * GS)


# ---------------------------------------------------------------------------
# Node State
# ---------------------------------------------------------------------------

@dataclass
class NodeState:
    node_id:            str
    lat:                float
    lon:                float
    elevation:          float
    road_class:         str
    base_capacity_m3:   float
    grime_seed:         float

    # mutable simulation state
    water_volume_m3:    float = 0.0
    surcharge_m3:       float = 0.0
    cumulative_rain_mm: float = 0.0
    inflow_m3s:         float = 0.0   # inflow rate this tick

    @property
    def clogging_idx(self) -> float:
        return clogging_index(self.road_class, self.cumulative_rain_mm, self.grime_seed)

    @property
    def effective_capacity_m3(self) -> float:
        return self.base_capacity_m3 * (1.0 - self.clogging_idx)

    @property
    def is_flooded(self) -> bool:
        return self.surcharge_m3 > 0.0


# ---------------------------------------------------------------------------
# Edge State
# ---------------------------------------------------------------------------

@dataclass
class EdgeState:
    from_id:             str
    to_id:               str
    road_class:          str
    base_pipe_cap_m3s:   float   # design capacity m³/s
    current_flow_m3s:    float = 0.0

    @property
    def utilisation_pct(self) -> float:
        if self.base_pipe_cap_m3s <= 0:
            return 100.0
        return min(100.0, 100.0 * self.current_flow_m3s / self.base_pipe_cap_m3s)


# ---------------------------------------------------------------------------
# Drainage Model
# ---------------------------------------------------------------------------

class DrainageModel:
    """
    Simulates the stormwater drainage network tick by tick.
    """

    def __init__(self, graph: nx.Graph):
        """
        Args:
            graph: NetworkX graph with node attrs:
                     lat, lon, elevation, road_class, pipe_capacity_m3s
                   and edge attrs:
                     road_class, pipe_capacity_m3s, length_m
        """
        self.graph = graph
        self.nodes: Dict[str, NodeState] = {}
        self.edges: Dict[Tuple[str, str], EdgeState] = {}
        self._init_state()

    def _init_state(self):
        rng = random.Random(GRIME_RANDOM_SEED)

        for node_id, attrs in self.graph.nodes(data=True):
            road_class = attrs.get("road_class", "default")
            base_cap = NODE_CAPACITY_M3_BY_ROAD_CLASS.get(
                road_class, NODE_CAPACITY_M3_BY_ROAD_CLASS.get("default", 60.0)
            )
            self.nodes[node_id] = NodeState(
                node_id=node_id,
                lat=attrs.get("lat", 13.085),
                lon=attrs.get("lon", 80.26),
                elevation=attrs.get("elevation", 5.0),
                road_class=road_class,
                base_capacity_m3=base_cap,
                grime_seed=rng.random(),
            )

        for u, v, attrs in self.graph.edges(data=True):
            road_class = attrs.get("road_class", "default")
            base_cap = PIPE_CAPACITY_BY_ROAD_CLASS.get(
                road_class, PIPE_CAPACITY_BY_ROAD_CLASS.get("default", 0.2)
            )
            # Actual pipe capacity from edge attrs overrides class default
            cap = attrs.get("pipe_capacity_m3s", base_cap)
            self.edges[(u, v)] = EdgeState(
                from_id=u,
                to_id=v,
                road_class=road_class,
                base_pipe_cap_m3s=cap,
            )

    def reset(self):
        """Reset all node volumes and edge flows to zero (start of new scenario)."""
        for ns in self.nodes.values():
            ns.water_volume_m3 = 0.0
            ns.surcharge_m3 = 0.0
            ns.cumulative_rain_mm = 0.0
            ns.inflow_m3s = 0.0
        for es in self.edges.values():
            es.current_flow_m3s = 0.0

    def tick(
        self,
        surface_runoff: Dict[str, float],  # node_id → m³/s inflow from surface
        rainfall_mm_hr: Dict[str, float],  # node_id → mm/hr (for cumulative tracking)
        dt_seconds: float,
    ) -> Dict[str, float]:
        """
        Advance drainage simulation by dt_seconds.

        Steps:
          1. Add surface runoff inflow to each node's volume.
          2. Route water through pipes from each node to its downstream neighbours.
          3. Apply clogging reduction to effective pipe capacity.
          4. Compute surcharge (overflow onto street) per node.
          5. Update cumulative rainfall for clogging index.

        Returns:
            dict node_id → surcharge volume (m³) on the street surface
        """
        # Step 1 — add inflow from surface runoff
        for node_id, ns in self.nodes.items():
            inflow_m3 = surface_runoff.get(node_id, 0.0) * dt_seconds
            ns.water_volume_m3 += max(0.0, inflow_m3)
            ns.inflow_m3s = surface_runoff.get(node_id, 0.0)
            # Update cumulative rainfall (mm = mm/hr × hr)
            rain_mm = rainfall_mm_hr.get(node_id, 0.0) * (dt_seconds / 3600.0)
            ns.cumulative_rain_mm += rain_mm

        # Step 2 & 3 — pipe routing with clogging
        # Process edges: drain water from upstream node to downstream node
        # Sort edges by upstream elevation (highest first → natural drainage order)
        node_elevations = {
            nid: self.nodes[nid].elevation for nid in self.nodes
        }
        sorted_edges = sorted(
            self.edges.items(),
            key=lambda item: -node_elevations.get(item[0][0], 0.0)
        )

        for (u, v), es in sorted_edges:
            ns_u = self.nodes.get(u)
            ns_v = self.nodes.get(v)
            if ns_u is None or ns_v is None:
                continue

            # Effective pipe capacity reduced by clogging at upstream node
            ci = ns_u.clogging_idx
            eff_cap_m3s = es.base_pipe_cap_m3s * (1.0 - ci)

            # Max flow = min(available water, capacity × dt)
            max_flow_m3 = eff_cap_m3s * dt_seconds
            actual_flow_m3 = min(ns_u.water_volume_m3, max(0.0, max_flow_m3))

            # Only drain if pipe goes downhill (or for connected network, always drain)
            elev_diff = ns_u.elevation - ns_v.elevation
            flow_factor = 1.0 if elev_diff >= 0 else 0.5  # reduced backflow

            actual_flow_m3 *= flow_factor

            ns_u.water_volume_m3 -= actual_flow_m3
            ns_v.water_volume_m3 += actual_flow_m3
            es.current_flow_m3s = actual_flow_m3 / dt_seconds if dt_seconds > 0 else 0.0

        # Step 4 — compute surcharge
        surcharge: Dict[str, float] = {}
        for node_id, ns in self.nodes.items():
            eff_cap = ns.effective_capacity_m3
            if ns.water_volume_m3 > eff_cap:
                ns.surcharge_m3 = ns.water_volume_m3 - eff_cap
                # Water backs up onto street; cap node volume at capacity
                ns.water_volume_m3 = eff_cap
            else:
                ns.surcharge_m3 = 0.0
            surcharge[node_id] = ns.surcharge_m3

        return surcharge

    def get_drainage_utilisation_pct(self) -> float:
        """Average pipe utilisation across all edges (%)."""
        if not self.edges:
            return 0.0
        return sum(es.utilisation_pct for es in self.edges.values()) / len(self.edges)
