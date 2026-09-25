"""
UrbanFlow — Live Provider (Stub)
=================================
Documents the production data contract for real sensor integration.
This class raises NotImplementedError with detailed docstrings pointing
to the real APIs that would replace each method.

PRODUCTION DATA CONTRACT:
─────────────────────────
| Data Layer      | Source                              | Format           |
|─────────────────|─────────────────────────────────────|──────────────────|
| Doppler Radar   | IMD BUFR FTP / IMD Weather API      | BUFR/NetCDF/JSON |
| Elevation DEM   | Copernicus GLO-30 (AWS S3)          | GeoTIFF          |
| Road/Drain GIS  | Municipal Corp. ArcGIS/QGIS Server  | Shapefile/GDB    |
| Gauge Data      | CWC Telemetry API                   | JSON/CSV         |
| Gauge Data      | WRIS (Water Resources Info System)  | JSON             |

Integration steps (NOT implemented in this build):
  1. Register at: https://mausam.imd.gov.in/imd_latest/contents/radar-data.php
  2. Obtain FTP credentials for BUFR radar composite (every 15 min)
  3. Decode using eccodes / cfgrib Python libraries
  4. Extract CAPPI PPI reflectivity grid → apply Marshall-Palmer Z-R
  5. Feed resulting rainfall grid to NowcastEngine
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .provider import DataProvider


class LiveProvider(DataProvider):
    """
    Production-ready stub. All methods raise NotImplementedError with
    documentation of the real API endpoints and data schemas.
    """

    def provider_name(self) -> str:
        return "LiveProvider (stub — not connected)"

    def is_live(self) -> bool:
        return True   # would be True if connected

    def get_bounding_box(self) -> Tuple[float, float, float, float]:
        """
        In production: configurable per deployment; could come from a
        PostGIS query on the municipal drain GIS layer extent.
        """
        raise NotImplementedError(
            "LiveProvider.get_bounding_box: Configure via environment variable "
            "URBANFLOW_BBOX=min_lon,min_lat,max_lon,max_lat"
        )

    def fetch_road_network(self) -> Dict[str, Any]:
        """
        Production source: Municipal Corporation GIS drain shapefiles
        served via ArcGIS REST API or QGIS Server WFS.

        Example ArcGIS endpoint (Greater Chennai Corporation):
          https://gis.chennaicorporation.gov.in/arcgis/rest/services/
          DrainageNetwork/FeatureServer/0/query?...

        Alternatively, BBMP/MCGM equivalents for other cities.

        Library: `fiona` or `geopandas` for shapefile parsing.
        """
        raise NotImplementedError(
            "LiveProvider.fetch_road_network: Connect to municipal GIS WFS endpoint. "
            "See docs/data-sources.md for full integration guide."
        )

    def fetch_elevations(self, locations: List[Tuple[float, float]]) -> List[float]:
        """
        Production source: Copernicus GLO-30 DEM tiles (30m resolution)
        hosted on AWS S3 as Cloud-Optimized GeoTIFFs (COGs).

        S3 path pattern:
          s3://copernicus-dem-30m/Copernicus_DSM_COG_10_N{lat:02d}_00_E{lon:03d}_00_DEM/

        Library: `rasterio` with `rasterio.open(s3_path)` for COG streaming.
        No download needed — sample pixels on-the-fly via HTTP range requests.

        Alternative: OpenTopography API (https://opentopography.org/)
        with the `globe` or `srtm30m` datasets.
        """
        raise NotImplementedError(
            "LiveProvider.fetch_elevations: Stream from Copernicus GLO-30 COG on S3. "
            "Requires: pip install rasterio boto3"
        )

    def get_current_rainfall_grid(
        self,
        node_locations: List[Tuple[str, float, float]],
        sim_time_minutes: float = 0.0,
    ) -> Dict[str, float]:
        """
        Production source: IMD Doppler Weather Radar BUFR composite.

        Acquisition:
          1. FTP: ftp.imd.gov.in/pub/radar/{station_id}/CAPPI_{yyyymmddHHMM}.buf
          2. Or: IMD Weather API (requires registration)
             POST https://api.weatherunion.com/gw/weather/external/v0/get_weather_data
          3. Decode BUFR: eccodes Python library (pip install eccodes cfgrib)
          4. Interpolate from radar grid (0.25° × 0.25°) to road network nodes
             using bilinear interpolation (scipy.interpolate.griddata)
          5. Apply Marshall-Palmer: R = (10^(dBZ/10) / 200)^(1/1.6)

        Radar stations covering Chennai:
          - Chennai (MAA): 13.0°N, 80.18°E, WSR-88D
          - Machilipatnam: backup coverage

        Update frequency: 10-minute volumetric scans, 15-min composites.

        CWC Gauge API (for ground-truth correction):
          https://cwc.gov.in/telemetry (gauge-radar merging with GAGE_R)
        """
        raise NotImplementedError(
            "LiveProvider.get_current_rainfall_grid: Connect to IMD BUFR FTP or "
            "Weather API and decode using eccodes. See docs/data-sources.md."
        )
