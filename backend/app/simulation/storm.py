"""
UrbanFlow — Storm Cell Model
=============================
Models a synthetic rainfall storm as a 2-D Gaussian intensity field
that moves along a velocity vector and decays over time.

Scientific basis:
  - Spatial decay: Gaussian radial profile  I(d) = I₀ · exp(-d²/2σ²)
  - Temporal decay: exponential             I(t) = I(d) · exp(-λ·t)
  - Z–R relation:  Marshall-Palmer         Z = 200 · R^1.6   (Z in mm⁶/m³, R in mm/hr)
    (Used when converting from reflectivity dBZ → rainfall rate:
     R = (10^(dBZ/10) / 200)^(1/1.6))
  - Advection: storm center moves at constant velocity
    (approximates what pySTEPS optical-flow extrapolation does for one step)
"""
from __future__ import annotations

import math
import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Marshall–Palmer Z–R relation helpers
# ---------------------------------------------------------------------------

def reflectivity_to_rainfall(dbz: float) -> float:
    """
    Convert radar reflectivity (dBZ) to rainfall rate (mm/hr).
    Marshall–Palmer: Z = 200 * R^1.6  →  R = (Z/200)^(1/1.6)
    where Z = 10^(dBZ/10)
    """
    if dbz < 10.0:
        return 0.0
    Z = 10 ** (dbz / 10.0)
    R = (Z / 200.0) ** (1.0 / 1.6)
    return max(0.0, R)


def rainfall_to_reflectivity(r_mm_hr: float) -> float:
    """
    Convert rainfall rate (mm/hr) to reflectivity (dBZ).
    Z = 200 * R^1.6 → dBZ = 10 * log10(Z)
    """
    if r_mm_hr <= 0:
        return -10.0
    Z = 200.0 * (r_mm_hr ** 1.6)
    return 10.0 * math.log10(max(Z, 1e-9))


# ---------------------------------------------------------------------------
# Storm Cell dataclass
# ---------------------------------------------------------------------------

@dataclass
class StormCell:
    """
    A synthetic storm cell modelled as a Gaussian blob moving on the map.

    Attributes:
        center_lat:        Initial latitude of storm peak (degrees)
        center_lon:        Initial longitude of storm peak (degrees)
        intensity_mm_hr:   Peak rainfall intensity (mm/hr) at center
        radius_km:         Effective radius (1σ of Gaussian, in km)
        vel_lat_ms:        Northward velocity (m/s); positive = moves north
        vel_lon_ms:        Eastward velocity (m/s); positive = moves east
        decay_rate:        Temporal decay constant (1/minutes); 0 = no decay
        start_time_min:    Simulation time (minutes) at which storm begins
        end_time_min:      Simulation time (minutes) at which storm ends (intensity→0)
    """
    center_lat:      float
    center_lon:      float
    intensity_mm_hr: float
    radius_km:       float        = 3.0
    vel_lat_ms:      float        = 0.5    # m/s northward
    vel_lon_ms:      float        = 1.2    # m/s eastward
    decay_rate:      float        = 0.003  # per minute (half-life ≈ 230 min)
    start_time_min:  float        = 0.0
    end_time_min:    float        = 180.0

    # internal mutable state (not part of scenario definition)
    _current_lat:    float        = field(init=False, repr=False)
    _current_lon:    float        = field(init=False, repr=False)

    def __post_init__(self):
        self._current_lat = self.center_lat
        self._current_lon = self.center_lon

    # ------------------------------------------------------------------
    # Physics
    # ------------------------------------------------------------------

    @staticmethod
    def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Great-circle distance in km."""
        R = 6371.0
        φ1, φ2 = math.radians(lat1), math.radians(lat2)
        Δφ = math.radians(lat2 - lat1)
        Δλ = math.radians(lon2 - lon1)
        a = math.sin(Δφ/2)**2 + math.cos(φ1) * math.cos(φ2) * math.sin(Δλ/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def rainfall_at(self, lat: float, lon: float, t_minutes: float) -> float:
        """
        Rainfall intensity (mm/hr) at (lat, lon) at simulation time t_minutes.

        Steps:
          1. Advance storm center to position at time t
          2. Compute distance d from storm center
          3. Apply Gaussian spatial profile: I = I₀ · exp(-d²/2σ²)
          4. Apply exponential temporal decay: I *= exp(-λ·t)
          5. Clamp to 0 outside storm's active time window
        """
        if t_minutes < self.start_time_min or t_minutes > self.end_time_min:
            return 0.0

        # Position at time t
        dt_seconds = (t_minutes - self.start_time_min) * 60.0
        # 1 degree lat ≈ 111,320 m; 1 degree lon ≈ 111,320 * cos(lat) m
        lat_deg_per_m = 1.0 / 111_320.0
        lon_deg_per_m = 1.0 / (111_320.0 * math.cos(math.radians(self.center_lat)))

        storm_lat = self.center_lat + self.vel_lat_ms * dt_seconds * lat_deg_per_m
        storm_lon = self.center_lon + self.vel_lon_ms * dt_seconds * lon_deg_per_m

        # Distance from storm center
        d_km = self._haversine_km(lat, lon, storm_lat, storm_lon)

        # Gaussian spatial profile (σ = radius_km)
        sigma = self.radius_km
        spatial = math.exp(-(d_km**2) / (2 * sigma**2))

        # Temporal decay
        active_minutes = t_minutes - self.start_time_min
        temporal = math.exp(-self.decay_rate * active_minutes)

        return self.intensity_mm_hr * spatial * temporal

    def clone_at_time(self, t_minutes: float) -> "StormCell":
        """Return a copy of this storm cell with center advanced to time t."""
        clone = deepcopy(self)
        dt_seconds = (t_minutes - self.start_time_min) * 60.0
        lat_deg_per_m = 1.0 / 111_320.0
        lon_deg_per_m = 1.0 / (111_320.0 * math.cos(math.radians(self.center_lat)))
        clone.center_lat = self.center_lat + self.vel_lat_ms * dt_seconds * lat_deg_per_m
        clone.center_lon = self.center_lon + self.vel_lon_ms * dt_seconds * lon_deg_per_m
        return clone


# ---------------------------------------------------------------------------
# Scenario Library
# ---------------------------------------------------------------------------
# Storm center placed slightly west of Chennai bbox center so it tracks
# through the study area during the 3-hr simulation window.

_BASE_LAT = 13.075   # slightly south of bbox center
_BASE_LON = 80.215   # just west of bbox edge, moving east

SCENARIOS: Dict[str, StormCell] = {
    "cloudburst_extreme": StormCell(
        center_lat=_BASE_LAT,
        center_lon=_BASE_LON,
        intensity_mm_hr=100.0,
        radius_km=3.5,
        vel_lat_ms=0.3,      # slow northward drift
        vel_lon_ms=1.5,      # moving east through the bbox
        decay_rate=0.002,    # very slow decay → sustained event
        start_time_min=0.0,
        end_time_min=180.0,
    ),
    "moderate_steady": StormCell(
        center_lat=_BASE_LAT,
        center_lon=_BASE_LON,
        intensity_mm_hr=25.0,
        radius_km=8.0,       # wide, stratiform rain
        vel_lat_ms=0.2,
        vel_lon_ms=0.8,
        decay_rate=0.001,
        start_time_min=0.0,
        end_time_min=180.0,
    ),
    "heavy_localized": StormCell(
        center_lat=_BASE_LAT + 0.03,
        center_lon=_BASE_LON + 0.02,
        intensity_mm_hr=60.0,
        radius_km=2.0,       # tight convective cell
        vel_lat_ms=0.5,
        vel_lon_ms=2.0,
        decay_rate=0.005,    # fast-moving, quick decay
        start_time_min=10.0,
        end_time_min=120.0,
    ),
}


def get_scenario(name: str) -> StormCell:
    """Return a deep copy of a named scenario storm cell."""
    if name not in SCENARIOS:
        raise ValueError(
            f"Unknown scenario '{name}'. Available: {list(SCENARIOS.keys())}"
        )
    return deepcopy(SCENARIOS[name])


def list_scenarios() -> List[Dict]:
    """Return metadata about all available scenarios."""
    return [
        {
            "name": key,
            "peak_intensity_mm_hr": sc.intensity_mm_hr,
            "radius_km": sc.radius_km,
            "duration_minutes": sc.end_time_min - sc.start_time_min,
            "description": _SCENARIO_DESCRIPTIONS.get(key, ""),
        }
        for key, sc in SCENARIOS.items()
    ]


_SCENARIO_DESCRIPTIONS = {
    "cloudburst_extreme": (
        "Extreme cloudburst: 100 mm/hr peak, slow-moving, causes severe flooding "
        "across T. Nagar within 30–45 minutes."
    ),
    "moderate_steady": (
        "Moderate sustained rain: 25 mm/hr, wide stratiform pattern, "
        "nuisance flooding in low-lying areas after 60 minutes."
    ),
    "heavy_localized": (
        "Heavy localized convective cell: 60 mm/hr, tight 2 km radius, "
        "fast-moving eastward, disruptive flooding in impacted streets."
    ),
}
