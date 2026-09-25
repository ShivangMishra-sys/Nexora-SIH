"""
UrbanFlow v2 — Module 3: Soil / Infiltration
[16] PySWMM/NumPy: Antecedent Moisture Condition from rolling precipitation record
[17] SciPy/PySWMM: Horton or Green-Ampt infiltration keyed to LULC soil class
"""
from __future__ import annotations

import logging
from collections import deque

import numpy as np
from scipy.optimize import minimize   # used in [65] calibration

logger = logging.getLogger("urbanflow.infiltration")

# ---------------------------------------------------------------------------
# AMC classification (SCS curve number method)
# AMC-I (dry): 5-day antecedent < 35mm (dormant season) or < 52mm (growing)
# AMC-II: normal
# AMC-III (wet): > 53mm dormant or > 77mm growing
# ---------------------------------------------------------------------------
AMC_THRESHOLDS = {
    "dormant":  (35.0, 53.0),
    "growing":  (52.0, 77.0),
}


def compute_amc_class(
    cumulative_5day_mm: float, season: str = "growing"
) -> int:
    """[16] Return AMC class 1, 2 or 3 from 5-day antecedent rainfall."""
    lo, hi = AMC_THRESHOLDS.get(season, AMC_THRESHOLDS["growing"])
    if cumulative_5day_mm < lo:
        return 1   # dry
    elif cumulative_5day_mm < hi:
        return 2   # normal
    else:
        return 3   # wet


# ---------------------------------------------------------------------------
# [16] Rolling 5-day precipitation record tracker
# ---------------------------------------------------------------------------
class AntecedentMoistureTracker:
    """[16] Maintains a sliding window of synthetic daily rainfall totals."""

    def __init__(self, window_days: int = 5, dt_minutes: float = 5.0):
        self.dt_minutes = dt_minutes
        self.steps_per_day = int(24 * 60 / dt_minutes)
        self.window_steps = window_days * self.steps_per_day
        self._record: deque[float] = deque(
            [2.0] * self.window_steps, maxlen=self.window_steps
        )  # pre-seeded with light drizzle (AMC-II)

    def update(self, rain_rate_mm_hr: float) -> None:
        """Push one timestep's mean rain rate (mm/hr)."""
        rain_mm = rain_rate_mm_hr * (self.dt_minutes / 60.0)
        self._record.append(rain_mm)

    def five_day_total_mm(self) -> float:
        """[16] Total mm over the rolling 5-day window."""
        return float(np.sum(list(self._record)))

    def amc_class(self, season: str = "growing") -> int:
        """[16] Current AMC class (1/2/3)."""
        return compute_amc_class(self.five_day_total_mm(), season)


# ---------------------------------------------------------------------------
# [17] Horton infiltration model
# ---------------------------------------------------------------------------
def horton_infiltration(
    f0: float,         # initial infiltration capacity (mm/hr)
    fc: float,         # final/saturated capacity (mm/hr)
    k:  float,         # decay constant (1/hr)
    t:  float,         # elapsed time since start of rain (hr)
    amc_class: int = 2,
) -> float:
    """
    [17] Horton exponential decay: f(t) = fc + (f0 - fc) * exp(-k * t)
    AMC adjustment: drier soil → higher f0; wetter → lower fc.
    """
    amc_mult = {1: 1.5, 2: 1.0, 3: 0.6}.get(amc_class, 1.0)
    f0_eff = f0 * amc_mult
    fc_eff = fc * (1.0 / amc_mult)
    f_t = fc_eff + (f0_eff - fc_eff) * np.exp(-k * t)
    return max(float(f_t), float(fc_eff))


def horton_infiltration_array(
    f0: float, fc: float, k: float,
    t: np.ndarray, amc_class: int = 2
) -> np.ndarray:
    """Vectorised Horton infiltration over a time array."""
    amc_mult = {1: 1.5, 2: 1.0, 3: 0.6}.get(amc_class, 1.0)
    f0_eff = f0 * amc_mult
    fc_eff = fc * (1.0 / amc_mult)
    return np.maximum(fc_eff, fc_eff + (f0_eff - fc_eff) * np.exp(-k * t))


# ---------------------------------------------------------------------------
# [17] Green-Ampt infiltration model
# ---------------------------------------------------------------------------
def green_ampt_infiltration(
    Ks: float,         # saturated hydraulic conductivity (mm/hr)
    psi: float,        # wetting-front suction (mm)
    theta_e: float,    # effective porosity (fraction)
    F: float,          # cumulative infiltration so far (mm)
    dt_hr: float,      # timestep (hr)
) -> tuple[float, float]:
    """
    [17] Green-Ampt: f = Ks * (1 + psi * theta_e / F)
    Returns (infiltration rate mm/hr, new cumulative F mm).
    """
    F = max(F, 1e-6)
    f = Ks * (1.0 + psi * theta_e / F)
    F_new = F + f * dt_hr
    return f, F_new


# ---------------------------------------------------------------------------
# LULC → soil parameters (keyed to WorldCover classes)
# ---------------------------------------------------------------------------
SOIL_PARAMS_BY_LULC = {
    # class: (f0 mm/hr, fc mm/hr, k 1/hr, Ks mm/hr, psi mm, theta_e)
    10: (50.0, 10.0, 2.0,  20.0, 150.0, 0.40),  # Tree cover (forest soil)
    20: (40.0,  8.0, 1.8,  15.0, 130.0, 0.35),  # Shrubland
    30: (35.0,  7.0, 1.5,  12.0, 120.0, 0.30),  # Grassland
    40: (25.0,  5.0, 1.2,   8.0, 100.0, 0.25),  # Cropland
    50: ( 5.0,  1.0, 3.0,   2.0,  60.0, 0.10),  # Built-up (urban, impervious)
    60: (15.0,  3.0, 1.0,   5.0,  80.0, 0.18),  # Bare/sparse
    80: ( 0.0,  0.0, 0.0,   0.0,   0.0, 0.00),  # Water (no infiltration)
}
SOIL_PARAMS_DEFAULT = (8.0, 2.0, 1.5, 4.0, 90.0, 0.15)


def get_soil_params(lulc_class: int) -> tuple:
    """[17] Lookup Horton/Green-Ampt params for a WorldCover LULC class."""
    return SOIL_PARAMS_BY_LULC.get(int(lulc_class), SOIL_PARAMS_DEFAULT)


def compute_infiltration_raster(
    rain_rate: np.ndarray,      # mm/hr, shape (rows, cols)
    lulc_raster: np.ndarray,    # WorldCover uint8 class codes
    elapsed_hr: float,          # time since rain start
    amc_class: int = 2,
    model: str = "horton",
) -> np.ndarray:
    """
    [17] Compute per-cell infiltration rate (mm/hr) based on LULC-derived
    soil params. Returns net rain rate after infiltration.
    """
    rows, cols = rain_rate.shape
    infiltration = np.zeros((rows, cols), dtype=np.float32)

    unique_classes = np.unique(lulc_raster)
    for cls in unique_classes:
        mask = lulc_raster == cls
        params = get_soil_params(int(cls))
        f0, fc, k, Ks, psi, theta_e = params

        if model == "horton":
            f_rate = horton_infiltration(f0, fc, k, elapsed_hr, amc_class)
        else:  # green-ampt
            cum_f = float(np.mean(rain_rate[mask])) * elapsed_hr
            f_rate, _ = green_ampt_infiltration(Ks, psi, theta_e, cum_f + 0.1, elapsed_hr / max(1, int(elapsed_hr * 12)))

        infiltration[mask] = min(f_rate, float(np.mean(rain_rate[mask])))

    # Net runoff = rain - infiltration (clamp to 0)
    return np.maximum(0.0, rain_rate - infiltration).astype(np.float32)
