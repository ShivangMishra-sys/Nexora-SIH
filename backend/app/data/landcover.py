"""
UrbanFlow v2 — Data Layer: Land Cover / Imperviousness
[4][5] WorldCover class codes → runoff coefficient C
[6]    OSMnx geometries_from_place: vector land-use polygons → refine C raster
[7]    OSMnx building footprints (impermeable non-flow barriers)
[45]   H3-py: discrete H3 hex grid (res ~10) over bbox as overland-flow grid
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

from app.config import (
    BBOX_WGS84, BBOX_PLACE, WORLDCOVER_C, WORLDCOVER_C_DEFAULT,
    H3_RESOLUTION, GRID_RESOLUTION_M, LANDCOVER_TIF,
)

logger = logging.getLogger("urbanflow.landcover")


# ---------------------------------------------------------------------------
# [4][5] WorldCover class → C lookup
# ---------------------------------------------------------------------------
def worldcover_to_runoff_coeff(class_code: int) -> float:
    """[4][5] Map ESA WorldCover class integer to runoff coefficient C."""
    return WORLDCOVER_C.get(int(class_code), WORLDCOVER_C_DEFAULT)


# ---------------------------------------------------------------------------
# Provider interface (matches spec §1.2)
# ---------------------------------------------------------------------------
class CachedTileProvider:
    """[ACTIVE] Reads the pre-downloaded WorldCover GeoTIFF via Rasterio windowed read."""

    def get_landcover(self, bbox: Tuple[float, float, float, float]) -> np.ndarray:
        """[4][5] Return raw WorldCover uint8 array clipped to bbox."""
        import rasterio
        from rasterio.windows import from_bounds

        if not Path(LANDCOVER_TIF).exists():
            logger.warning("WorldCover tile missing; using synthetic fallback")
            return self._synthetic_landcover(bbox)

        with rasterio.open(str(LANDCOVER_TIF)) as src:
            window = from_bounds(*bbox, transform=src.transform)
            data = src.read(1, window=window)
            return data

    def get_runoff_coeff_raster(
        self, bbox: Tuple[float, float, float, float]
    ) -> np.ndarray:
        """[4][5] WorldCover → C raster."""
        lc = self.get_landcover(bbox)
        vec_map = np.vectorize(worldcover_to_runoff_coeff)
        return vec_map(lc).astype(np.float32)

    @staticmethod
    def _synthetic_landcover(bbox) -> np.ndarray:
        """Synthetic WorldCover array if tile absent."""
        from app.data.terrain import _generate_synthetic_landcover
        out = Path(LANDCOVER_TIF)
        _generate_synthetic_landcover(bbox, output_path=out)
        import rasterio
        with rasterio.open(str(out)) as src:
            return src.read(1)


class GEEProvider:
    """
    STUB ONLY — never instantiated.

    Production integration:
      import ee
      ee.Initialize(credentials=<service_account_json>)
      ic = ee.ImageCollection('ESA/WorldCover/v200')
      img = ic.first().select('Map').clip(ee.Geometry.BBox(*bbox))
      data = geemap.ee_to_numpy(img)

    Requires:
      - A registered GCP project with Earth Engine API enabled
      - A service-account JSON key mounted at runtime
      - Network access to earthengine.googleapis.com

    Why it is a stub here:
      OAuth/service-account setup is unreliable inside a hackathon Docker build.
      The CachedTileProvider above provides identical data from the pre-downloaded
      ESA WorldCover GeoTIFF, which is the same source dataset GEE would serve.
    """

    def get_landcover(self, bbox):
        raise NotImplementedError("GEEProvider requires production GCP credentials")


# ---------------------------------------------------------------------------
# [6] OSM vector land-use to refine C raster
# ---------------------------------------------------------------------------
def refine_c_raster_with_osm_landuse(
    c_raster: np.ndarray,
    transform,  # rasterio Affine
    bbox: Tuple[float, float, float, float],
) -> np.ndarray:
    """
    [6] Fetch OSM land-use polygons via OSMnx and burn refined C values
    onto the raster (parks → lower C, industrial → higher C).
    """
    try:
        import osmnx as ox
        import geopandas as gpd
        from rasterio.features import rasterize

        tags = {"landuse": True, "leisure": ["park", "garden", "recreation_ground"]}
        gdf: gpd.GeoDataFrame = ox.features_from_bbox(*bbox, tags=tags)
        if gdf.empty:
            return c_raster

        rows, cols = c_raster.shape
        for _, row in gdf.iterrows():
            luse = str(row.get("landuse", "")).lower()
            if luse in ("park", "forest", "garden", "grass"):
                new_c = 0.15
            elif luse in ("industrial", "commercial", "retail"):
                new_c = 0.90
            else:
                continue

            geom = [row.geometry.__geo_interface__]
            mask = rasterize(geom, out_shape=(rows, cols), transform=transform,
                             fill=0, default_value=1, dtype=np.uint8)
            c_raster[mask == 1] = new_c

        logger.info("[6] OSM land-use polygons applied to C raster")
    except Exception as e:
        logger.warning(f"[6] OSM land-use refinement skipped: {e}")

    return c_raster


# ---------------------------------------------------------------------------
# [7] Building footprints — impermeable non-flow barriers
# ---------------------------------------------------------------------------
def get_building_footprints(bbox: Tuple[float, float, float, float]):
    """
    [7] Fetch building footprints from OSM via OSMnx.
    Returns GeoDataFrame of Shapely polygons (impermeable, non-flow-through).
    """
    try:
        import osmnx as ox
        import geopandas as gpd

        tags = {"building": True}
        gdf: gpd.GeoDataFrame = ox.features_from_bbox(*bbox, tags=tags)
        logger.info(f"[7] Fetched {len(gdf)} building footprints from OSM")
        return gdf
    except Exception as e:
        logger.warning(f"[7] Building footprint fetch failed: {e}")
        import geopandas as gpd
        return gpd.GeoDataFrame()


def burn_buildings_as_barriers(
    c_raster: np.ndarray,
    transform,
    gdf,
    barrier_value: float = 0.99,
) -> np.ndarray:
    """[7] Set building cells to near-1.0 runoff coefficient (impermeable)."""
    if gdf is None or len(gdf) == 0:
        return c_raster
    try:
        from rasterio.features import rasterize
        rows, cols = c_raster.shape
        geoms = [g.__geo_interface__ for g in gdf.geometry if g is not None and g.is_valid]
        if not geoms:
            return c_raster
        mask = rasterize(geoms, out_shape=(rows, cols), transform=transform,
                         fill=0, default_value=1, dtype=np.uint8)
        c_raster[mask == 1] = barrier_value
    except Exception as e:
        logger.warning(f"[7] Building barrier burn failed: {e}")
    return c_raster


# ---------------------------------------------------------------------------
# [45] H3 hex grid over bbox
# ---------------------------------------------------------------------------
def generate_h3_grid(bbox: Tuple[float, float, float, float], resolution: int = H3_RESOLUTION):
    """
    [45] Generate H3 hexagonal grid (res ~10, ~15m edge) over the study area.
    Returns list of H3 cell IDs.
    """
    try:
        import h3
        from shapely.geometry import Polygon

        min_lon, min_lat, max_lon, max_lat = bbox
        polygon = Polygon([
            (min_lon, min_lat), (max_lon, min_lat),
            (max_lon, max_lat), (min_lon, max_lat),
            (min_lon, min_lat),
        ])
        cells = list(h3.polyfill_geojson(polygon.__geo_interface__, resolution))
        logger.info(f"[45] H3 grid: {len(cells)} cells at resolution {resolution}")
        return cells
    except ImportError:
        logger.warning("[45] h3 not available; returning empty grid")
        return []
