"""
UrbanFlow v2 — Module 6: 2D–1D Coupling (surface ↔ drainage)
[38] PySWMM + orchestrator: bidirectional volume exchange each tick
[39] NetworkX/PySWMM: route surcharge from manholes back to surface grid cells

Also handles:
[48] Cache snapshots at +15,+30,+60,+120,+180min (timeline scrubber reads these)
[49] Monte Carlo ensemble: perturb rainfall → confidence intervals
[50] Risk classification: Safe/Caution/Critical/Impassable
[51] DBSCAN: cluster contiguous high-depth cells into flood hotspot zones
[64] Scikit-learn: validate predicted depth vs. seeded ground-truth
[65] SciPy optimize: calibrate Manning's n / infiltration params
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.config import (
    BBOX_WGS84, GRID_RESOLUTION_M, SIMULATION_DT_S,
    FORECAST_HORIZONS_MIN, RISK_THRESHOLDS, SNAPSHOTS_DIR,
    ENSEMBLE_MEMBERS, MANNING_N_DEFAULT, SWMM_INP, BLOCKAGE_MODEL,
)

logger = logging.getLogger("urbanflow.coupling")


# ---------------------------------------------------------------------------
# [48] Snapshot cache
# ---------------------------------------------------------------------------
def save_snapshot(t_minutes: int, state: Dict) -> None:
    """[48] Cache a simulation snapshot so the timeline scrubber never recomputes."""
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOTS_DIR / f"t{t_minutes:04d}.json"
    # Convert numpy arrays to lists for JSON serialisation
    serialisable = {}
    for k, v in state.items():
        if isinstance(v, np.ndarray):
            serialisable[k] = v.tolist()
        else:
            serialisable[k] = v
    with open(path, "w") as f:
        json.dump(serialisable, f)


def load_snapshot(t_minutes: int) -> Optional[Dict]:
    """[48] Load a cached snapshot for timeline scrubber."""
    path = SNAPSHOTS_DIR / f"t{t_minutes:04d}.json"
    if not path.exists():
        return None
    with open(path) as f:
        data = json.load(f)
    # Restore numpy arrays
    for k in ["depth_cm", "risk_grid", "velocity"]:
        if k in data and isinstance(data[k], list):
            data[k] = np.array(data[k], dtype=np.float32)
    return data


def list_available_snapshots() -> List[int]:
    """Return sorted list of cached snapshot times (minutes)."""
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    times = []
    for p in SNAPSHOTS_DIR.glob("t*.json"):
        try:
            times.append(int(p.stem[1:]))
        except ValueError:
            pass
    return sorted(times)


# ---------------------------------------------------------------------------
# [50] Risk classification
# ---------------------------------------------------------------------------
def classify_risk_grid(depth_cm: np.ndarray) -> np.ndarray:
    """[50] NumPy np.select: classify each cell into 4 risk bands."""
    conditions = [
        depth_cm < RISK_THRESHOLDS["safe"],
        depth_cm < RISK_THRESHOLDS["caution"],
        depth_cm < RISK_THRESHOLDS["critical"],
    ]
    choices = [0, 1, 2]
    return np.select(conditions, choices, default=3).astype(np.uint8)


RISK_LABELS = {0: "safe", 1: "caution", 2: "critical", 3: "impassable"}
RISK_COLORS = {0: "#6b7280", 1: "#f59e0b", 2: "#f97316", 3: "#ef4444"}


# ---------------------------------------------------------------------------
# [49] Monte Carlo ensemble
# ---------------------------------------------------------------------------
def run_ensemble(
    surface_model,        # SurfaceRunoffModel instance
    base_rain: np.ndarray,
    n_members: int = ENSEMBLE_MEMBERS,
    perturb_std_frac: float = 0.2,
    dt_s: float = SIMULATION_DT_S,
) -> Dict:
    """
    [49] Perturb rainfall intensity across N ensemble members.
    Returns mean depth + 10th/90th percentile confidence interval.
    """
    import copy
    depths = []
    rng = np.random.RandomState(0)

    for _ in range(n_members):
        perturb = 1.0 + rng.normal(0, perturb_std_frac, base_rain.shape).astype(np.float32)
        perturbed_rain = np.maximum(0.0, base_rain * perturb)

        # Clone model state (lightweight copy)
        depth_save = surface_model.depth_m.copy()
        result = surface_model.tick(perturbed_rain, dt_s)
        depths.append(result["depth_cm"].copy())
        surface_model.depth_m = depth_save   # restore

    depth_stack = np.stack(depths, axis=0)
    return {
        "mean_depth_cm":  depth_stack.mean(axis=0).astype(np.float32),
        "p10_depth_cm":   np.percentile(depth_stack, 10, axis=0).astype(np.float32),
        "p90_depth_cm":   np.percentile(depth_stack, 90, axis=0).astype(np.float32),
    }


# ---------------------------------------------------------------------------
# [51] DBSCAN flood hotspot clustering
# ---------------------------------------------------------------------------
def cluster_flood_hotspots(depth_cm: np.ndarray, min_depth: float = 15.0) -> List[Dict]:
    """
    [51] Scikit-learn DBSCAN: cluster contiguous cells with depth >15cm
    into macro flood-hotspot zones for the incident-feed UI panel.
    """
    from sklearn.cluster import DBSCAN

    rows, cols = depth_cm.shape
    yy, xx = np.mgrid[0:rows, 0:cols]
    mask = depth_cm > min_depth
    pts = np.column_stack([yy[mask], xx[mask]])

    if len(pts) == 0:
        return []

    eps_cells = max(3, int(50 / GRID_RESOLUTION_M))   # 50m in grid cells
    db = DBSCAN(eps=eps_cells, min_samples=5).fit(pts)
    labels = db.labels_

    hotspots = []
    for lbl in set(labels):
        if lbl == -1:
            continue
        cluster_pts = pts[labels == lbl]
        mean_r = float(cluster_pts[:, 0].mean())
        mean_c = float(cluster_pts[:, 1].mean())
        max_depth = float(depth_cm[cluster_pts[:, 0], cluster_pts[:, 1]].max())
        hotspots.append({
            "cluster_id":  int(lbl),
            "cell_count":  int(len(cluster_pts)),
            "mean_row":    mean_r,
            "mean_col":    mean_c,
            "max_depth_cm": max_depth,
            "severity":    "critical" if max_depth > 30 else "caution",
        })

    logger.info(f"[51] DBSCAN: {len(hotspots)} flood hotspot zones identified")
    return hotspots


# ---------------------------------------------------------------------------
# [64] Model validation vs. seeded ground-truth
# ---------------------------------------------------------------------------
SEEDED_GROUND_TRUTH = [
    # (row, col, known_depth_cm) — synthetic historical high-water marks
    (20, 30, 22.0),
    (35, 45, 8.5),
    (15, 20, 35.0),
    (50, 60, 5.0),
    (25, 25, 15.0),
]


def validate_model(depth_cm: np.ndarray) -> Dict:
    """
    [64] Compare predicted depth vs. seeded historical ground-truth.
    Returns RMSE, F1 (binary >15cm classification), displayed on dashboard.
    """
    from sklearn.metrics import mean_squared_error, f1_score

    predicted = []
    observed  = []
    for r, c, true_depth in SEEDED_GROUND_TRUTH:
        r = min(r, depth_cm.shape[0] - 1)
        c = min(c, depth_cm.shape[1] - 1)
        predicted.append(float(depth_cm[r, c]))
        observed.append(true_depth)

    p_arr = np.array(predicted)
    o_arr = np.array(observed)
    rmse = float(np.sqrt(mean_squared_error(o_arr, p_arr)))
    f1   = float(f1_score(
        (o_arr > 15.0).astype(int),
        (p_arr > 15.0).astype(int),
        zero_division=0,
    ))

    return {"rmse_cm": rmse, "f1_flood_detection": f1}


# ---------------------------------------------------------------------------
# [65] SciPy calibration of Manning's n
# ---------------------------------------------------------------------------
def calibrate_manning_n(
    surface_model,
    base_rain: np.ndarray,
    dt_s: float = SIMULATION_DT_S,
) -> float:
    """
    [65] SciPy optimize.minimize: calibrate Manning's n against seeded
    historical high-water marks to minimize RMSE.
    """
    from scipy.optimize import minimize

    def objective(params):
        n = params[0]
        if n <= 0 or n > 0.5:
            return 1e9
        n_save = surface_model.n_manning
        d_save = surface_model.depth_m.copy()
        surface_model.n_manning = n
        surface_model.depth_m[:] = 0.0
        for _ in range(10):
            surface_model.tick(base_rain, dt_s)
        metrics = validate_model(surface_model.get_depth_cm())
        surface_model.n_manning = n_save
        surface_model.depth_m = d_save
        return metrics["rmse_cm"]

    result = minimize(objective, x0=[MANNING_N_DEFAULT], method="Nelder-Mead",
                      options={"maxiter": 30, "xatol": 0.001})
    best_n = float(result.x[0])
    logger.info(f"[65] Manning's n calibrated: {MANNING_N_DEFAULT:.4f} → {best_n:.4f} (RMSE={result.fun:.2f}cm)")
    return best_n


# ---------------------------------------------------------------------------
# [38][39] 2D–1D Coupling Orchestrator
# ---------------------------------------------------------------------------
class CoupledSimulation:
    """
    [38][39] Real bidirectional coupling between:
      - SurfaceRunoffModel (2D overland)
      - SWMMRunner (1D drainage)
    Exchange happens every tick via weir/orifice equations.
    """

    def __init__(
        self,
        surface_model,
        swmm_runner,
        node_grid_map: Dict,
        bbox=BBOX_WGS84,
        grid_shape=None,
        dt_s: float = SIMULATION_DT_S,
    ):
        self.surface = surface_model
        self.swmm    = swmm_runner
        self.node_grid_map = node_grid_map
        self.bbox    = bbox
        self.grid_shape = grid_shape or surface_model.grid_shape
        self.dt_s    = dt_s
        self.t_steps = 0
        self.t_minutes = 0
        self._observers: List = []
        logger.info("[38] CoupledSimulation ready (2D↔1D)")

    def add_observer(self, fn) -> None:
        self._observers.append(fn)

    def _notify(self, state: Dict) -> None:
        for fn in self._observers:
            try:
                fn(state)
            except Exception:
                pass

    def tick(self, net_rain: np.ndarray) -> Dict:
        """
        [38] One coupled timestep:
        1. Surface model computes runoff
        2. Extract node inflows → inject into SWMM
        3. SWMM steps forward → returns surcharges
        4. [39] Map surcharges back to surface grid cells
        5. Classify risk, cluster hotspots
        """
        # Step 1: 2D surface
        surface_result = self.surface.tick(net_rain, self.dt_s)

        # Step 2: surface → pipe inflow [38]
        node_inflow = self.surface.extract_inflow_to_swmm(self.node_grid_map)

        # Convert m³/tick to m³/s for SWMM
        node_inflow_m3s = {k: v / self.dt_s for k, v in node_inflow.items()}

        # Step 3: SWMM step [26][27][28]
        self.swmm.inject_inflow(node_inflow_m3s)
        surcharge = self.swmm.step(node_inflow_m3s)   # returns {node_id: depth_m}

        # Step 4: surcharge → surface grid [39]
        surcharge_grid = np.zeros(self.grid_shape, dtype=np.float32)
        for node_id, depth_m in surcharge.items():
            if node_id in self.node_grid_map:
                r, c = self.node_grid_map[node_id]
                if 0 <= r < self.grid_shape[0] and 0 <= c < self.grid_shape[1]:
                    # Distribute surcharge volume to adjacent cells
                    for dr in range(-1, 2):
                        for dc in range(-1, 2):
                            nr, nc = r + dr, c + dc
                            if 0 <= nr < self.grid_shape[0] and 0 <= nc < self.grid_shape[1]:
                                surcharge_grid[nr, nc] += depth_m / 9.0
        self.surface.apply_swmm_surcharge(surcharge_grid)

        # Step 5: classify + cluster
        depth_cm  = surface_result["depth_cm"]
        risk_grid = classify_risk_grid(depth_cm)
        hotspots  = cluster_flood_hotspots(depth_cm)
        validation = validate_model(depth_cm)

        self.t_steps  += 1
        self.t_minutes = int(self.t_steps * self.dt_s / 60)

        state = {
            "t_minutes":      self.t_minutes,
            "depth_cm":       depth_cm,
            "risk_grid":      risk_grid,
            "velocity":       surface_result["velocity_m_s"],
            "hotspots":       hotspots,
            "surcharge_nodes": list(surcharge.keys()),
            "validation":     validation,
        }

        self._notify(state)
        return state

    def run_to_horizon(self, rainfall_system, lulc_raster, amc_class: int = 2) -> Dict:
        """
        [48] Run forward to all forecast horizons; save snapshots.
        Uses PySTEPS forecast rain rates from rainfall_system.
        """
        from app.simulation.infiltration import compute_infiltration_raster

        forecasts = rainfall_system.get_forecast()
        snapshots = {}

        for t_min in FORECAST_HORIZONS_MIN:
            rain = forecasts.get(t_min, np.zeros(self.grid_shape, dtype=np.float32))
            # Resize to grid
            if rain.shape != self.grid_shape:
                from scipy.ndimage import zoom
                zy = self.grid_shape[0] / rain.shape[0]
                zx = self.grid_shape[1] / rain.shape[1]
                rain = zoom(rain.astype(np.float64), (zy, zx)).astype(np.float32)

            lulc_r = np.resize(lulc_raster, self.grid_shape).astype(np.uint8)
            net_rain = compute_infiltration_raster(rain, lulc_r, t_min / 60.0, amc_class)

            state = self.tick(net_rain)
            state["t_minutes"] = t_min
            save_snapshot(t_min, state)
            snapshots[t_min] = state
            logger.info(f"[48] Snapshot saved: t={t_min}min, max_depth={state['depth_cm'].max():.1f}cm")

        return snapshots
