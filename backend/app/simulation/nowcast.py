"""
UrbanFlow — Rainfall Nowcasting Engine
=======================================
Generates a 0–180 minute rainfall forecast by extrapolating the storm
cell forward in time (advection nowcast).

Technique:
  - Simple Lagrangian advection: storm cell moves at constant velocity.
  - This approximates the first-step extrapolation that pySTEPS would produce
    using optical-flow (Lucas-Kanade or DARTS) on radar composites.
  - Temporal decay is applied via the storm cell's built-in decay_rate.
  - The Marshall–Palmer Z–R relation (Z = 200·R^1.6) is the bridge between
    radar reflectivity and rainfall rate; here we store intensities directly,
    but Z-R is used when interpreting hypothetical dBZ inputs.

Future upgrade path:
  - Replace StormCell.rainfall_at() calls with pySTEPS extrapolation:
      1. Load real IMD radar CAPPI composite (BUFR/NetCDF)
      2. Run pysteps.nowcasts.extrapolation.forecast(R, V, timesteps)
      3. The rest of the pipeline (runoff, drainage) is unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .storm import StormCell


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RainfallFrame:
    """Rainfall intensity at each network node for a single forecast step."""
    t_minutes: float                          # minutes from scenario start
    node_intensities: Dict[str, float]        # node_id → mm/hr
    storm_center: Tuple[float, float]         # (lat, lon) of storm peak at t

    @property
    def mean_intensity(self) -> float:
        if not self.node_intensities:
            return 0.0
        return sum(self.node_intensities.values()) / len(self.node_intensities)

    @property
    def max_intensity(self) -> float:
        if not self.node_intensities:
            return 0.0
        return max(self.node_intensities.values())


@dataclass
class NowcastForecast:
    """Complete 0–180 min nowcast as a list of RainfallFrames."""
    frames: List[RainfallFrame] = field(default_factory=list)

    def at_time(self, t_minutes: float) -> RainfallFrame:
        """Interpolate or pick the nearest frame to the requested time."""
        if not self.frames:
            return RainfallFrame(t_minutes, {}, (0.0, 0.0))

        # Find bracketing frames
        for i, frame in enumerate(self.frames):
            if frame.t_minutes >= t_minutes:
                if i == 0:
                    return frame
                prev = self.frames[i - 1]
                # Linear interpolation
                alpha = ((t_minutes - prev.t_minutes) /
                         (frame.t_minutes - prev.t_minutes))
                interp = {
                    nid: prev.node_intensities.get(nid, 0.0) * (1 - alpha)
                         + frame.node_intensities.get(nid, 0.0) * alpha
                    for nid in set(prev.node_intensities) | set(frame.node_intensities)
                }
                center = (
                    prev.storm_center[0] * (1 - alpha) + frame.storm_center[0] * alpha,
                    prev.storm_center[1] * (1 - alpha) + frame.storm_center[1] * alpha,
                )
                return RainfallFrame(t_minutes, interp, center)

        return self.frames[-1]

    @property
    def intensity_timeseries(self) -> List[Dict]:
        """Return [{t_minutes, mean_mm_hr, max_mm_hr}, ...] for charting."""
        return [
            {
                "t_minutes": f.t_minutes,
                "mean_mm_hr": round(f.mean_intensity, 2),
                "max_mm_hr": round(f.max_intensity, 2),
                "storm_lat": f.storm_center[0],
                "storm_lon": f.storm_center[1],
            }
            for f in self.frames
        ]


# ---------------------------------------------------------------------------
# Nowcast Engine
# ---------------------------------------------------------------------------

class NowcastEngine:
    """
    Generates the full 0–180 min nowcast for a set of network nodes.
    """

    def __init__(self, timestep_minutes: int = 15):
        self.timestep_minutes = timestep_minutes

    def generate(
        self,
        storm: StormCell,
        node_locations: List[Tuple[str, float, float]],
        t_start_minutes: float = 0.0,
        t_end_minutes: float = 180.0,
    ) -> NowcastForecast:
        """
        Compute rainfall at every node for each forecast step.

        Args:
            storm:          The active StormCell to extrapolate
            node_locations: list of (node_id, lat, lon)
            t_start_minutes: forecast start (usually 0)
            t_end_minutes:  forecast end (usually 180)

        Returns:
            NowcastForecast with one RainfallFrame per timestep
        """
        import math

        frames: List[RainfallFrame] = []
        t = t_start_minutes

        while t <= t_end_minutes + 1e-9:
            intensities: Dict[str, float] = {}

            # Compute storm center position at time t
            dt_seconds = t * 60.0
            lat_deg_per_m = 1.0 / 111_320.0
            lon_deg_per_m = 1.0 / (
                111_320.0 * math.cos(math.radians(storm.center_lat))
            )
            storm_lat_t = storm.center_lat + storm.vel_lat_ms * dt_seconds * lat_deg_per_m
            storm_lon_t = storm.center_lon + storm.vel_lon_ms * dt_seconds * lon_deg_per_m

            for node_id, lat, lon in node_locations:
                intensity = storm.rainfall_at(lat, lon, t)
                intensities[node_id] = round(intensity, 3)

            frames.append(RainfallFrame(
                t_minutes=t,
                node_intensities=intensities,
                storm_center=(storm_lat_t, storm_lon_t),
            ))
            t += self.timestep_minutes

        return NowcastForecast(frames=frames)

    def nowcast_at_step(
        self,
        storm: StormCell,
        node_locations: List[Tuple[str, float, float]],
        t_minutes: float,
    ) -> RainfallFrame:
        """
        Compute a single-step nowcast (used during live ticking).
        """
        import math

        dt_seconds = t_minutes * 60.0
        lat_deg_per_m = 1.0 / 111_320.0
        lon_deg_per_m = 1.0 / (
            111_320.0 * math.cos(math.radians(storm.center_lat))
        )
        storm_lat_t = storm.center_lat + storm.vel_lat_ms * dt_seconds * lat_deg_per_m
        storm_lon_t = storm.center_lon + storm.vel_lon_ms * dt_seconds * lon_deg_per_m

        intensities: Dict[str, float] = {}
        for node_id, lat, lon in node_locations:
            intensities[node_id] = round(storm.rainfall_at(lat, lon, t_minutes), 3)

        return RainfallFrame(t_minutes, intensities, (storm_lat_t, storm_lon_t))
