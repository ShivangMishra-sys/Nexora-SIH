"""
UrbanFlow v2 — Bootstrap: Data Layer Initialization
Runs once at startup (or if cached files are absent):
  1. Generate/validate synthetic DEM + WorldCover tiles
  2. Reproject to EPSG:32643 (UTM 43N) [56]
  3. Resample to 10m [46]
  4. WhiteboxTools hydro-enforce [44]
  5. Slope rasters [2]
  6. RMSE check [43]
  7. Fetch OSM road network [8]
  8. Add elevations [9], flag underpasses [10]
  9. Prepare SWMM graph [23], generate .inp [18-22]
  10. Train blockage model [25]
  11. Spatial join nodes→grid [24]
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path

from app.config import (
    BBOX_WGS84, DEM_RAW, DEM_BREACHED, DEM_SLOPE_X, DEM_SLOPE_Y,
    LANDCOVER_TIF, OSM_GRAPH_PKL, SWMM_INP, BLOCKAGE_MODEL,
    GRID_RESOLUTION_M, SNAPSHOTS_DIR,
)

logger = logging.getLogger("urbanflow.bootstrap")

# Paths for UTM-reprojected intermediate rasters
_DEM_UTM  = DEM_RAW.parent / "dem_utm.tif"
_DEM_10M  = DEM_RAW.parent / "dem_10m.tif"
_BREACHED = DEM_BREACHED


def ensure_dem() -> Path:
    """[1][46][44][56] Ensure hydro-enforced 10m DEM exists."""
    from app.data.terrain import (
        _generate_synthetic_dem, reproject_to_utm,
        resample_to_resolution, breach_depressions,
        compute_slope_rasters, compute_vertical_rmse,
    )

    # Generate synthetic if real tile not present
    if not DEM_RAW.exists():
        logger.info("DEM tile not found — generating synthetic stand-in …")
        _generate_synthetic_dem(BBOX_WGS84, output_path=DEM_RAW)
    else:
        logger.info(f"Using real DEM tile: {DEM_RAW}")

    # [56] Reproject to UTM 43N
    if not _DEM_UTM.exists():
        reproject_to_utm(DEM_RAW, _DEM_UTM)

    # [46] Resample to 10m
    if not _DEM_10M.exists():
        resample_to_resolution(_DEM_UTM, _DEM_10M, res_m=GRID_RESOLUTION_M)

    # [44] WhiteboxTools breach
    if not _BREACHED.exists():
        breach_depressions(_DEM_10M, _BREACHED)

    # [2] Slope rasters
    if not DEM_SLOPE_X.exists() or not DEM_SLOPE_Y.exists():
        compute_slope_rasters(_BREACHED, DEM_SLOPE_X, DEM_SLOPE_Y)

    # [43] Vertical RMSE (log only)
    compute_vertical_rmse(_BREACHED)

    return _BREACHED


def ensure_landcover() -> Path:
    """[4][5] Ensure WorldCover tile exists."""
    from app.data.terrain import _generate_synthetic_landcover
    if not LANDCOVER_TIF.exists():
        logger.info("WorldCover tile not found — generating synthetic stand-in …")
        _generate_synthetic_landcover(BBOX_WGS84, output_path=LANDCOVER_TIF)
    else:
        logger.info(f"Using real WorldCover tile: {LANDCOVER_TIF}")
    return LANDCOVER_TIF


def ensure_road_network(dem_path: Path):
    """[8][9][10][66] Fetch and prepare OSM road network."""
    from app.data.road_network import (
        fetch_road_network, add_elevations_from_dem,
        flag_underpasses, add_missing_drain_edges,
    )

    G = fetch_road_network(BBOX_WGS84, use_cache=OSM_GRAPH_PKL.exists())
    G = add_elevations_from_dem(G, dem_path)
    G = flag_underpasses(G)
    G = add_missing_drain_edges(G)

    # Re-save with elevations
    with open(OSM_GRAPH_PKL, "wb") as f:
        pickle.dump(G, f)
    logger.info(f"Road network ready: {G.number_of_nodes()} nodes")
    return G


def ensure_swmm_inp(G) -> Path:
    """[18-25][23] Generate SWMM .inp and train blockage model."""
    from app.data.road_network import prepare_graph_for_swmm
    from app.simulation.drainage_1d import (
        generate_inp_from_osm_graph, load_blockage_model,
        compute_blockage_derating, add_synthetic_pump,
    )

    simple_G = prepare_graph_for_swmm(G)

    # [25] Load or train blockage model
    clf = load_blockage_model(BLOCKAGE_MODEL)
    derating = compute_blockage_derating(simple_G, clf)

    if not SWMM_INP.exists():
        generate_inp_from_osm_graph(simple_G, SWMM_INP, blockage_derating=derating)
        add_synthetic_pump(SWMM_INP)   # [31]
    else:
        logger.info(f"Reusing cached SWMM .inp: {SWMM_INP}")

    return SWMM_INP


def run_bootstrap() -> dict:
    """
    Full bootstrap sequence. Returns references to all initialized objects.
    Called once at application startup.
    """
    logger.info("=" * 60)
    logger.info("UrbanFlow v2 Bootstrap — Anna Nagar, Chennai")
    logger.info("=" * 60)

    from app.compute_backend import backend_name
    logger.info(f"Compute backend: {backend_name}")

    # Data layer
    dem_path  = ensure_dem()
    lc_path   = ensure_landcover()
    G         = ensure_road_network(dem_path)
    swmm_inp  = ensure_swmm_inp(G)

    # Load rasters for simulation
    import numpy as np
    import rasterio
    from rasterio.enums import Resampling

    def load_raster(path: Path, target_shape=None):
        with rasterio.open(path) as src:
            if target_shape:
                data = src.read(
                    1,
                    out_shape=(1, *target_shape),
                    resampling=Resampling.bilinear,
                )[0]
            else:
                data = src.read(1)
            return data.astype(np.float32), src.transform

    dem_arr, dem_transform = load_raster(_BREACHED)
    grid_shape = dem_arr.shape
    logger.info(f"Grid shape: {grid_shape} @ {GRID_RESOLUTION_M}m")

    slope_x_arr, _ = load_raster(DEM_SLOPE_X, target_shape=grid_shape)
    slope_y_arr, _ = load_raster(DEM_SLOPE_Y, target_shape=grid_shape)

    # Land cover → C raster
    from app.data.landcover import CachedTileProvider, refine_c_raster_with_osm_landuse, \
        get_building_footprints, burn_buildings_as_barriers
    lc_provider = CachedTileProvider()
    lulc_arr = np.resize(lc_provider.get_landcover(BBOX_WGS84), grid_shape).astype(np.uint8)
    c_raster = lc_provider.get_runoff_coeff_raster(BBOX_WGS84)
    c_raster = np.resize(c_raster, grid_shape).astype(np.float32)
    c_raster = refine_c_raster_with_osm_landuse(c_raster, dem_transform, BBOX_WGS84)
    buildings = get_building_footprints(BBOX_WGS84)
    c_raster = burn_buildings_as_barriers(c_raster, dem_transform, buildings)

    # Surface model
    from app.simulation.runoff_2d import SurfaceRunoffModel
    surface = SurfaceRunoffModel(grid_shape, GRID_RESOLUTION_M)
    surface.initialize(dem_arr, slope_x_arr, slope_y_arr, c_raster)

    # SWMM runner
    from app.simulation.drainage_1d import SWMMRunner, spatial_join_to_grid, load_blockage_model
    from app.data.road_network import prepare_graph_for_swmm
    simple_G = prepare_graph_for_swmm(G)
    swmm_runner = SWMMRunner(swmm_inp)
    swmm_runner.start()

    # Spatial join [24]
    node_grid_map = spatial_join_to_grid(simple_G, grid_shape, BBOX_WGS84)

    # Rainfall system
    from app.simulation.rainfall import RainfallSystem
    rainfall = RainfallSystem(BBOX_WGS84, GRID_RESOLUTION_M)

    # Coupled simulation
    from app.simulation.coupling import CoupledSimulation
    coupled = CoupledSimulation(surface, swmm_runner, node_grid_map, BBOX_WGS84, grid_shape)

    # Critical infrastructure [63]
    from app.data.road_network import get_critical_infrastructure, get_water_bodies
    infra_gdf = get_critical_infrastructure(BBOX_WGS84)
    water_gdf = get_water_bodies(BBOX_WGS84)

    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Bootstrap complete ✓")
    logger.info("=" * 60)

    return {
        "G":            G,
        "simple_G":     simple_G,
        "surface":      surface,
        "swmm_runner":  swmm_runner,
        "rainfall":     rainfall,
        "coupled":      coupled,
        "node_grid_map": node_grid_map,
        "dem_arr":      dem_arr,
        "dem_transform": dem_transform,
        "lulc_arr":     lulc_arr,
        "grid_shape":   grid_shape,
        "infra_gdf":    infra_gdf,
        "water_gdf":    water_gdf,
        "swmm_inp":     swmm_inp,
    }
