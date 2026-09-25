"""
UrbanFlow — Coupled Flood Predictor
=====================================
Combines surface runoff accumulation and drainage surcharge into
per-node flood depth predictions with risk classification.

Risk bands (matches PPT legend exactly):
  dry         < 5  cm   — normal conditions
  nuisance    5–15 cm   — minor ponding, pedestrian risk
  disruptive  15–30 cm  — vehicle disruption, road closures possible
  severe      > 30 cm   — life safety risk, road impassable
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.config import (
    RISK_DISRUPTIVE_MAX_CM,
    RISK_DRY_MAX_CM,
    RISK_NUISANCE_MAX_CM,
)
from .drainage import DrainageModel, NodeState


# ---------------------------------------------------------------------------
# Output data structures
# ---------------------------------------------------------------------------

@dataclass
class FloodNode:
    """Flood prediction for a single network node."""
    node_id:           str
    lat:               float
    lon:               float
    elevation_m:       float
    predicted_depth_cm: float
    risk_level:        str    # "dry" | "nuisance" | "disruptive" | "severe"
    eta_minutes:       float  # estimated minutes until flooding onset (0 = already flooded)
    confidence:        float  # 0.0–1.0 (decreases with forecast horizon)
    rainfall_mm_hr:    float  # current rainfall at this node
    drainage_util_pct: float  # pipe utilisation percentage
    clogging_idx:      float  # CI 0–1

    def to_dict(self) -> dict:
        return {
            "node_id":            self.node_id,
            "lat":                self.lat,
            "lon":                self.lon,
            "elevation_m":        round(self.elevation_m, 2),
            "predicted_depth_cm": round(self.predicted_depth_cm, 1),
            "risk_level":         self.risk_level,
            "eta_minutes":        round(self.eta_minutes, 1),
            "confidence":         round(self.confidence, 3),
            "rainfall_mm_hr":     round(self.rainfall_mm_hr, 2),
            "drainage_util_pct":  round(self.drainage_util_pct, 1),
            "clogging_idx":       round(self.clogging_idx, 3),
        }


@dataclass
class FloodState:
    """Complete flood prediction state at a given simulation time."""
    t_minutes:     float
    nodes:         List[FloodNode]
    run_id:        str
    scenario_name: str
    storm_center:  tuple        # (lat, lon)
    mean_depth_cm: float
    max_depth_cm:  float
    severe_count:  int
    disruptive_count: int
    nuisance_count:   int
    dry_count:        int
    drainage_util_pct: float

    def to_dict(self) -> dict:
        return {
            "t_minutes":        self.t_minutes,
            "run_id":           self.run_id,
            "scenario_name":    self.scenario_name,
            "storm_center":     {"lat": self.storm_center[0], "lon": self.storm_center[1]},
            "summary": {
                "mean_depth_cm":     round(self.mean_depth_cm, 1),
                "max_depth_cm":      round(self.max_depth_cm, 1),
                "severe_count":      self.severe_count,
                "disruptive_count":  self.disruptive_count,
                "nuisance_count":    self.nuisance_count,
                "dry_count":         self.dry_count,
                "drainage_util_pct": round(self.drainage_util_pct, 1),
            },
            "nodes": [n.to_dict() for n in self.nodes],
        }


# ---------------------------------------------------------------------------
# Risk classification
# ---------------------------------------------------------------------------

def classify_risk(depth_cm: float) -> str:
    if depth_cm < RISK_DRY_MAX_CM:
        return "dry"
    elif depth_cm < RISK_NUISANCE_MAX_CM:
        return "nuisance"
    elif depth_cm < RISK_DISRUPTIVE_MAX_CM:
        return "disruptive"
    else:
        return "severe"


def estimate_eta(
    depth_cm: float,
    inflow_rate_m3s: float,
    node_capacity_m3: float,
    current_volume_m3: float,
    t_minutes: float,
) -> float:
    """
    Estimate minutes until this node reaches flood threshold (5 cm depth).

    If already flooded, returns 0.
    If inflow rate is zero, returns a large number (effectively never).
    """
    if depth_cm >= RISK_DRY_MAX_CM:
        return 0.0   # already flooding

    # Estimate from time-to-fill: how long until surcharge begins?
    remaining_capacity = max(0.0, node_capacity_m3 - current_volume_m3)
    if inflow_rate_m3s <= 1e-9:
        return 180.0   # no meaningful inflow → no forecast of flooding

    eta_s = remaining_capacity / inflow_rate_m3s
    return min(180.0, eta_s / 60.0)   # convert to minutes


def compute_confidence(t_minutes: float, total_minutes: float = 180.0) -> float:
    """
    Confidence decreases linearly with forecast horizon.
    At t=0: confidence = 0.95 (near-certainty for current state)
    At t=180: confidence = 0.45
    """
    return max(0.45, 0.95 - 0.50 * (t_minutes / total_minutes))


# ---------------------------------------------------------------------------
# Flood depth from surcharge
# ---------------------------------------------------------------------------

# Approximate road surface area per node (m²) for converting
# surcharge volume → depth. In a real system this comes from DEM/LiDAR.
# We use a simple estimate based on road class.
PONDING_AREA_BY_ROAD_CLASS = {
    "motorway":     2000.0,   # wide, large median
    "trunk":        1500.0,
    "primary":      800.0,
    "secondary":    500.0,
    "tertiary":     300.0,
    "residential":  200.0,
    "service":      100.0,
    "unclassified": 250.0,
    "path":         50.0,
    "default":      250.0,
}


def surcharge_to_depth_cm(
    surcharge_m3: float,
    road_class: str,
) -> float:
    """
    Convert surcharge volume (m³) to average water depth (cm) on the road.

    Depth (m) = Volume (m³) / Ponding Area (m²)
    """
    area = PONDING_AREA_BY_ROAD_CLASS.get(road_class, 250.0)
    depth_m = surcharge_m3 / max(area, 1.0)
    return depth_m * 100.0   # → cm


# ---------------------------------------------------------------------------
# Flood Predictor
# ---------------------------------------------------------------------------

class FloodPredictor:
    """
    Combines surface runoff + drainage surcharge into flood depth predictions.
    """

    def __init__(self, drainage_model: DrainageModel):
        self.drainage = drainage_model

    def predict(
        self,
        rainfall_mm_hr: Dict[str, float],
        surcharge: Dict[str, float],
        t_minutes: float,
        run_id: str,
        scenario_name: str,
        storm_center: tuple,
    ) -> FloodState:
        """
        Generate FloodState from current drainage model state.

        Args:
            rainfall_mm_hr: node_id → current rainfall (mm/hr)
            surcharge:       node_id → surcharge volume (m³)
            t_minutes:       current simulation time
            run_id:          active simulation run ID
            scenario_name:   active scenario name
            storm_center:    (lat, lon) of storm peak

        Returns:
            FloodState with per-node FloodNode predictions
        """
        flood_nodes: List[FloodNode] = []
        confidence = compute_confidence(t_minutes)

        for node_id, ns in self.drainage.nodes.items():
            surcharge_m3 = surcharge.get(node_id, 0.0)
            depth_cm = surcharge_to_depth_cm(surcharge_m3, ns.road_class)
            risk = classify_risk(depth_cm)
            eta = estimate_eta(
                depth_cm=depth_cm,
                inflow_rate_m3s=ns.inflow_m3s,
                node_capacity_m3=ns.effective_capacity_m3,
                current_volume_m3=ns.water_volume_m3,
                t_minutes=t_minutes,
            )

            # Find an edge from this node to get pipe utilisation
            out_edges = [
                es for (u, v), es in self.drainage.edges.items() if u == node_id
            ]
            util_pct = (
                sum(e.utilisation_pct for e in out_edges) / len(out_edges)
                if out_edges else 0.0
            )

            flood_nodes.append(FloodNode(
                node_id=node_id,
                lat=ns.lat,
                lon=ns.lon,
                elevation_m=ns.elevation,
                predicted_depth_cm=depth_cm,
                risk_level=risk,
                eta_minutes=eta,
                confidence=confidence,
                rainfall_mm_hr=rainfall_mm_hr.get(node_id, 0.0),
                drainage_util_pct=util_pct,
                clogging_idx=ns.clogging_idx,
            ))

        depths = [fn.predicted_depth_cm for fn in flood_nodes]
        counts = {r: sum(1 for fn in flood_nodes if fn.risk_level == r)
                  for r in ("dry", "nuisance", "disruptive", "severe")}

        return FloodState(
            t_minutes=t_minutes,
            nodes=flood_nodes,
            run_id=run_id,
            scenario_name=scenario_name,
            storm_center=storm_center,
            mean_depth_cm=sum(depths) / len(depths) if depths else 0.0,
            max_depth_cm=max(depths) if depths else 0.0,
            severe_count=counts["severe"],
            disruptive_count=counts["disruptive"],
            nuisance_count=counts["nuisance"],
            dry_count=counts["dry"],
            drainage_util_pct=self.drainage.get_drainage_utilisation_pct(),
        )
