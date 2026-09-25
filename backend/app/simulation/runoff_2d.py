"""
UrbanFlow v2 — Module 4: 2D Surface Runoff
[32] NumPy: Rational Method Q = C·I·A per grid cell
[33] RichDEM / WhiteboxTools D8 flow-direction routing
[34] NumPy/Numba: kinematic/diffusive-wave overland sheet-flow velocity
[35] SciPy/NumPy: per-cell mass-balance update each Δt tick
[36] NumPy: volume ÷ cell footprint → water depth (cm)
[37] NumPy: 2D Manning V = (1/n)·d^(2/3)·S^(1/2) flow-speed hazard layer
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from app.compute_backend import overland_flow_step, mass_balance_update, compute_flow_velocity
from app.config import GRID_RESOLUTION_M, MANNING_N_DEFAULT

logger = logging.getLogger("urbanflow.runoff")

# ---------------------------------------------------------------------------
# [33] D8 flow-direction from DEM (RichDEM or WhiteboxTools)
# ---------------------------------------------------------------------------
D8_DIRECTIONS = {
    # (row_delta, col_delta) for each D8 direction
    0: ( 0,  1),  # E
    1: (-1,  1),  # NE
    2: (-1,  0),  # N
    3: (-1, -1),  # NW
    4: ( 0, -1),  # W
    5: ( 1, -1),  # SW
    6: ( 1,  0),  # S
    7: ( 1,  1),  # SE
}


def compute_d8_flow_direction(dem: np.ndarray) -> np.ndarray:
    """[33] Compute D8 flow direction matrix from a DEM. Returns integer matrix [0-7]."""
    try:
        import richdem as rd
        dem_rd = rd.rdarray(dem.astype(np.float64), no_data=-9999)
        accum = rd.FlowAccumulation(dem_rd, method="D8")
        fd = rd.FlowDirections(dem_rd, method="D8")
        logger.info("[33] D8 flow direction computed via RichDEM")
        return np.array(fd, dtype=np.int32)
    except ImportError:
        logger.warning("[33] RichDEM unavailable; computing D8 flow direction with NumPy")
        return _numpy_d8(dem)


def _numpy_d8(dem: np.ndarray) -> np.ndarray:
    """NumPy fallback for D8 flow direction."""
    rows, cols = dem.shape
    fd = np.zeros((rows, cols), dtype=np.int32)
    padded = np.pad(dem, 1, mode="edge")
    for d, (dr, dc) in D8_DIRECTIONS.items():
        neighbour = padded[1 + dr: rows + 1 + dr, 1 + dc: cols + 1 + dc]
        diff = dem - neighbour
        # Assign direction d where this neighbour is lowest
        if d == 0:
            best = diff.copy()
            fd[:] = d
        else:
            update = diff > best
            best = np.where(update, diff, best)
            fd = np.where(update, d, fd)
    return fd


# ---------------------------------------------------------------------------
# [32] Rational Method: Q = C·I·A
# ---------------------------------------------------------------------------
def rational_method_runoff(
    rain_rate_mm_hr: np.ndarray,    # I: intensity mm/hr
    runoff_coeff: np.ndarray,       # C: dimensionless [0–1]
    cell_area_m2: float,            # A: m² per cell
) -> np.ndarray:
    """
    [32] Q = C · I · A per grid cell.
    Returns volumetric flow rate in m³/hr per cell.
    """
    # Convert I from mm/hr to m/hr
    I_m_hr = rain_rate_mm_hr / 1000.0
    Q = runoff_coeff * I_m_hr * cell_area_m2   # m³/hr
    return np.maximum(0.0, Q).astype(np.float32)


# ---------------------------------------------------------------------------
# Flow routing
# ---------------------------------------------------------------------------
def route_d8_flow(
    inflow_volume: np.ndarray,   # m³ per cell per tick
    flow_direction: np.ndarray,  # D8 direction matrix
) -> Tuple[np.ndarray, np.ndarray]:
    """
    [33] Route overland inflow volume one step downstream via D8.
    Returns (outflow_from_each_cell, inflow_into_each_cell).
    """
    rows, cols = inflow_volume.shape
    out_volume = inflow_volume.copy()
    in_volume  = np.zeros_like(inflow_volume)

    for r in range(1, rows - 1):
        for c in range(1, cols - 1):
            vol = out_volume[r, c]
            if vol <= 0:
                continue
            d = flow_direction[r, c]
            dr, dc = D8_DIRECTIONS[d]
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols:
                in_volume[nr, nc] += vol
                out_volume[r, c] = 0.0

    return out_volume, in_volume


# ---------------------------------------------------------------------------
# Full 2D surface runoff state
# ---------------------------------------------------------------------------
class SurfaceRunoffModel:
    """
    2D surface runoff model coupling Modules 3 (infiltration) and 4 (flow).
    Exchanges volume with the 1D SWMM model in Module 6.
    """

    def __init__(
        self,
        grid_shape: Tuple[int, int],
        cell_res_m: float = GRID_RESOLUTION_M,
        n_manning: float = MANNING_N_DEFAULT,
    ):
        rows, cols = grid_shape
        self.grid_shape  = grid_shape
        self.cell_area   = cell_res_m ** 2          # m² per cell
        self.cell_res    = cell_res_m
        self.n_manning   = n_manning

        # State arrays
        self.depth_m      = np.zeros(grid_shape, dtype=np.float32)   # water depth (m)
        self.flow_dir     = np.zeros(grid_shape, dtype=np.int32)
        self.slope_x      = np.zeros(grid_shape, dtype=np.float32)
        self.slope_y      = np.zeros(grid_shape, dtype=np.float32)
        self.runoff_coeff = np.full(grid_shape, 0.7, dtype=np.float32)  # default C
        self.surcharge_input = np.zeros(grid_shape, dtype=np.float32)   # from SWMM [39]

        logger.info(f"SurfaceRunoffModel ready — {rows}×{cols} @ {cell_res_m}m")

    def initialize(
        self,
        dem: np.ndarray,
        slope_x: np.ndarray,
        slope_y: np.ndarray,
        runoff_coeff: np.ndarray,
    ) -> None:
        """Set terrain + land-cover inputs from data layer."""
        self.flow_dir     = compute_d8_flow_direction(dem)
        self.slope_x      = np.resize(slope_x, self.grid_shape).astype(np.float32)
        self.slope_y      = np.resize(slope_y, self.grid_shape).astype(np.float32)
        self.runoff_coeff = np.resize(runoff_coeff, self.grid_shape).astype(np.float32)
        logger.info("SurfaceRunoffModel initialized from DEM/land-cover")

    def tick(
        self,
        net_rain_mm_hr: np.ndarray,    # after infiltration
        dt_s: float = 60.0,            # [47] timestep in seconds
    ) -> dict:
        """
        [32][33][34][35][36] Advance model one timestep:
          1. Rational Method → volumetric inflow
          2. D8 routing
          3. Mass-balance depth update
          4. Kinematic-wave velocity
          5. Compute depth in cm
        """
        dt_hr = dt_s / 3600.0

        # [32] Q = C · I · A (m³/hr → m³ per tick)
        Q_m3_hr = rational_method_runoff(net_rain_mm_hr, self.runoff_coeff, self.cell_area)
        Q_tick   = Q_m3_hr * dt_hr   # m³ added this tick

        # [33] Route flow downstream
        _, inflow = route_d8_flow(Q_tick, self.flow_dir)

        # [39] Add SWMM surcharge (from flooded manholes)
        inflow += self.surcharge_input * dt_hr

        # [35] Mass-balance: depth += inflow / cell_area
        outflow_est = overland_flow_step(
            self.depth_m, self.slope_x, self.slope_y, dt_s, self.n_manning
        ) * 0.0   # overland_flow_step returns updated depth, not outflow

        # Update depth directly from mass-balance
        new_depth = mass_balance_update(
            self.depth_m,
            inflow / self.cell_area,        # m inflow per m²
            np.zeros_like(self.depth_m),    # outflow handled by routing
            dt_s,
            1.0,                            # per unit area
        )

        # Apply kinematic-wave decay
        new_depth = overland_flow_step(
            new_depth, self.slope_x, self.slope_y, dt_s, self.n_manning
        )
        self.depth_m = new_depth

        # [34][37] Flow velocity
        velocity = compute_flow_velocity(self.depth_m, self.slope_x, self.slope_y, self.n_manning)

        # [36] Depth in cm
        depth_cm = self.depth_m * 100.0

        return {
            "depth_m":    self.depth_m,
            "depth_cm":   depth_cm,
            "velocity_m_s": velocity,
            "q_m3_hr":    Q_m3_hr,
        }

    def apply_swmm_surcharge(self, surcharge_map: np.ndarray) -> None:
        """[39] Receive flooded manhole surcharge volume from SWMM coupling."""
        self.surcharge_input = surcharge_map.astype(np.float32)

    def extract_inflow_to_swmm(self, node_grid_map: dict) -> dict:
        """
        [38] Extract per-node surface inflow volume (m³/tick) for SWMM.
        node_grid_map: {node_id: (row, col)} from spatial join [24].
        """
        node_inflow = {}
        for node_id, (r, c) in node_grid_map.items():
            if 0 <= r < self.grid_shape[0] and 0 <= c < self.grid_shape[1]:
                # Volume = depth * cell_area (m³), treat as runoff into manhole
                node_inflow[node_id] = float(self.depth_m[r, c] * self.cell_area * 0.1)
        return node_inflow

    def get_depth_cm(self) -> np.ndarray:
        """[36] Current water depth in cm."""
        return (self.depth_m * 100.0).astype(np.float32)

    def classify_risk(self, thresholds: dict) -> np.ndarray:
        """[50] Classify each cell: 0=safe,1=caution,2=critical,3=impassable."""
        depth_cm = self.get_depth_cm()
        risk = np.zeros_like(depth_cm, dtype=np.uint8)
        risk[depth_cm > thresholds["safe"]]      = 1
        risk[depth_cm > thresholds["caution"]]   = 2
        risk[depth_cm > thresholds["critical"]]  = 3
        return risk
