"""
UrbanFlow — DataProvider Abstraction
====================================
All data ingestion must go through this interface so that swapping
SimulatedProvider → LiveProvider is a one-line config change.

Production data contract (what LiveProvider would implement):
  - Rainfall: IMD Doppler Radar BUFR files via FTP (ftp://ftp.imd.gov.in/...)
              or the IMD Weather API (https://api.weatherunion.com/)
  - Elevation: Copernicus GLO-30 DEM tiles on AWS S3
               (s3://copernicus-dem-30m/Copernicus_DSM_COG_10_*)
  - Road/Drain: Municipal Corporation GIS drain shapefiles (SHAPE/GDB)
                served via ArcGIS or QGIS Server endpoints
  - Gauge data: CWC telemetry API (Central Water Commission)

Demo data layer (what SimulatedProvider implements):
  - Rainfall: Gaussian storm cell ticking on simulation clock
  - Elevation: Open-Elevation API with synthetic coastal fallback
  - Road network: OSM Overpass API (real roads, treated as drain pipes)
  - Gauge data: derived from the drainage simulation model
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Tuple, Optional
import numpy as np


class DataProvider(ABC):
    """Abstract base class for all data ingestion backends."""

    # ------------------------------------------------------------------
    # Spatial metadata
    # ------------------------------------------------------------------
    @abstractmethod
    def get_bounding_box(self) -> Tuple[float, float, float, float]:
        """Return (min_lon, min_lat, max_lon, max_lat) for the study area."""
        ...

    # ------------------------------------------------------------------
    # Road / Drainage network
    # ------------------------------------------------------------------
    @abstractmethod
    def fetch_road_network(self) -> Dict[str, Any]:
        """
        Fetch and return raw road network data.

        Returns a dict with:
          'nodes': list of {id, lat, lon, elevation_m, road_class}
          'edges': list of {from_id, to_id, road_class, length_m, osm_id}
        """
        ...

    # ------------------------------------------------------------------
    # Elevation
    # ------------------------------------------------------------------
    @abstractmethod
    def fetch_elevations(
        self, locations: List[Tuple[float, float]]
    ) -> List[float]:
        """
        Fetch elevation (metres above sea level) for a list of (lat, lon) pairs.

        Args:
            locations: list of (latitude, longitude) tuples

        Returns:
            list of elevation values in metres, same order as input
        """
        ...

    # ------------------------------------------------------------------
    # Rainfall
    # ------------------------------------------------------------------
    @abstractmethod
    def get_current_rainfall_grid(
        self,
        node_locations: List[Tuple[str, float, float]],
        sim_time_minutes: float = 0.0,
    ) -> Dict[str, float]:
        """
        Return current rainfall intensity (mm/hr) at each node location.

        Args:
            node_locations: list of (node_id, lat, lon) tuples
            sim_time_minutes: current simulation clock (minutes from scenario start)

        Returns:
            dict mapping node_id → rainfall intensity in mm/hr
        """
        ...

    # ------------------------------------------------------------------
    # Provider metadata
    # ------------------------------------------------------------------
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable name of this provider."""
        ...

    def is_live(self) -> bool:
        """Return True if this provider sources real sensor data."""
        return False
