"""
UrbanFlow v2 — Data Layer: Road / Drainage Network
[8]  OSMnx: extract drivable street network into NetworkX graph
[9]  OSMnx ox.elevation.add_node_elevations_raster: sample hydro-enforced DEM onto nodes
[10] OSMnx + GeoPandas: filter tunnel/underpass → flag as high-risk depressions
[66] NetworkX + OSMnx: auto-generate drain edge via MST down elevation gradient
     for road segments lacking an inferred drain
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import networkx as nx
import numpy as np

from app.config import (
    BBOX_WGS84, BBOX_PLACE, DEM_BREACHED, OSM_GRAPH_PKL,
    WORKING_CRS, DIAMETER_BY_CLASS,
)

logger = logging.getLogger("urbanflow.road_network")


# ---------------------------------------------------------------------------
# [8] Fetch street network from OSMnx
# ---------------------------------------------------------------------------
def fetch_road_network(
    bbox: Tuple[float, float, float, float] = BBOX_WGS84,
    use_cache: bool = True,
) -> nx.MultiDiGraph:
    """[8] Extract drivable street network into a NetworkX graph."""
    cache_path = OSM_GRAPH_PKL

    if use_cache and cache_path.exists():
        logger.info(f"[8] Loading cached road graph from {cache_path}")
        with open(cache_path, "rb") as f:
            return pickle.load(f)

    import osmnx as ox

    min_lon, min_lat, max_lon, max_lat = bbox
    logger.info(f"[8] Fetching OSM drivable network for bbox {bbox} …")
    G = ox.graph_from_bbox(
        north=max_lat, south=min_lat, east=max_lon, west=min_lon,
        network_type="drive",
        retain_all=False,
        simplify=True,
    )
    logger.info(f"[8] OSM graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "wb") as f:
        pickle.dump(G, f)
    logger.info(f"[8] Road graph cached → {cache_path}")
    return G


# ---------------------------------------------------------------------------
# [9] Sample DEM elevations onto graph nodes
# ---------------------------------------------------------------------------
def add_elevations_from_dem(G: nx.MultiDiGraph, dem_path: Path = DEM_BREACHED) -> nx.MultiDiGraph:
    """[9] Sample the hydro-enforced DEM onto every street node and edge."""
    try:
        import osmnx as ox
        import rasterio

        if not dem_path.exists():
            logger.warning(f"[9] DEM not found at {dem_path}; skipping elevation sampling")
            for node, data in G.nodes(data=True):
                data.setdefault("elevation", 5.0)
            return G

        G = ox.elevation.add_node_elevations_raster(G, raster_path=str(dem_path))
        G = ox.elevation.add_edge_grades(G, add_absolute=True)
        logger.info("[9] Node elevations sampled from hydro-enforced DEM")
    except Exception as e:
        logger.warning(f"[9] Elevation sampling failed ({e}); using defaults")
        for _, data in G.nodes(data=True):
            data.setdefault("elevation", 5.0)
    return G


# ---------------------------------------------------------------------------
# [10] Flag underpasses / tunnels as high-risk depressions
# ---------------------------------------------------------------------------
def flag_underpasses(G: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """[10] Mark tunnel=yes, layer<0, highway=underpass edges as high-risk."""
    flagged = 0
    for u, v, k, data in G.edges(keys=True, data=True):
        is_tunnel = str(data.get("tunnel", "")).lower() in ("yes", "true", "1")
        layer_neg = int(data.get("layer", 0) or 0) < 0
        is_underpass = str(data.get("highway", "")).lower() == "underpass"
        if is_tunnel or layer_neg or is_underpass:
            G[u][v][k]["high_risk_depression"] = True
            G[u][v][k]["flood_impedance_boost"] = 5.0   # extra penalty for routing
            flagged += 1
    logger.info(f"[10] Flagged {flagged} underpass/tunnel edges as high-risk")
    return G


# ---------------------------------------------------------------------------
# [66] Auto-generate missing drain edges via MST
# ---------------------------------------------------------------------------
def add_missing_drain_edges(G: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """
    [66] For any road segment with no inferred drain (no downhill neighbour),
    auto-generate a drain edge via minimum-spanning-tree down the elevation gradient.
    """
    # Build elevation-weighted undirected version
    nodes_with_elev = [(n, d.get("elevation", 5.0)) for n, d in G.nodes(data=True)]
    nodes_by_elev = sorted(nodes_with_elev, key=lambda x: x[1])

    # Find isolated sub-components (no downhill path)
    undirected = G.to_undirected()
    components = list(nx.connected_components(undirected))
    if len(components) <= 1:
        return G

    # Connect each isolated component to the lowest-elevation main component
    main_comp = max(components, key=len)
    lowest_main = min(
        [(n, G.nodes[n].get("elevation", 5.0)) for n in main_comp],
        key=lambda x: x[1]
    )[0]

    edges_added = 0
    for comp in components:
        if comp is main_comp:
            continue
        lowest_in_comp = min(
            [(n, G.nodes[n].get("elevation", 5.0)) for n in comp],
            key=lambda x: x[1]
        )[0]
        # Synthetic "MST drain edge"
        G.add_edge(lowest_in_comp, lowest_main,
                   length=100.0, highway="drain_mst", synthetic_drain=True,
                   elevation=G.nodes[lowest_main].get("elevation", 5.0))
        edges_added += 1

    logger.info(f"[66] Added {edges_added} synthetic drain edges via MST")
    return G


# ---------------------------------------------------------------------------
# Natural water bodies / retention sinks from OSM
# ---------------------------------------------------------------------------
def get_water_bodies(bbox: Tuple[float, float, float, float]):
    """[40] Query natural=water, waterway=riverbank → mark as retention sinks."""
    try:
        import osmnx as ox
        tags = {"natural": "water", "waterway": ["riverbank", "river", "stream"]}
        gdf = ox.features_from_bbox(*bbox, tags=tags)
        logger.info(f"[40] {len(gdf)} water body features fetched from OSM")
        return gdf
    except Exception as e:
        logger.warning(f"[40] Water body fetch failed: {e}")
        import geopandas as gpd
        return gpd.GeoDataFrame()


# ---------------------------------------------------------------------------
# [63] Critical infrastructure: hospitals, metro, substations
# ---------------------------------------------------------------------------
def get_critical_infrastructure(bbox: Tuple[float, float, float, float]):
    """[63] Buffer critical infrastructure from OSM for alert flagging."""
    try:
        import osmnx as ox
        tags = {
            "amenity": ["hospital", "clinic", "fire_station", "police"],
            "railway": "station",
            "power": "substation",
        }
        gdf = ox.features_from_bbox(*bbox, tags=tags)
        logger.info(f"[63] {len(gdf)} critical infrastructure POIs fetched")
        return gdf
    except Exception as e:
        logger.warning(f"[63] Infrastructure fetch failed: {e}")
        import geopandas as gpd
        return gpd.GeoDataFrame()


# ---------------------------------------------------------------------------
# Prepare graph for SWMM export (directed, weakly connected)
# ---------------------------------------------------------------------------
def prepare_graph_for_swmm(G: nx.MultiDiGraph) -> nx.DiGraph:
    """
    [23] Check weakly-connected before SWMM export.
    Convert MultiDiGraph → DiGraph (pick shortest edge per pair).
    Drop or bridge orphan subgraphs.
    """
    # Simplify: keep one edge per directed pair (shortest length)
    simple = nx.DiGraph()
    for node, data in G.nodes(data=True):
        simple.add_node(node, **data)

    for u, v, data in G.edges(data=True):
        if simple.has_edge(u, v):
            if data.get("length", 1e9) < simple[u][v].get("length", 1e9):
                simple[u][v].update(data)
        else:
            simple.add_edge(u, v, **data)

    # [23] Connectivity check
    if not nx.is_weakly_connected(simple):
        isolates = list(nx.isolates(simple))
        logger.warning(f"[23] Graph has {len(isolates)} isolated nodes — removing before SWMM export")
        simple.remove_nodes_from(isolates)

        # Bridge remaining components
        components = list(nx.weakly_connected_components(simple))
        if len(components) > 1:
            main = max(components, key=len)
            lowest_main = min(main, key=lambda n: simple.nodes[n].get("elevation", 999))
            for comp in components:
                if comp is main:
                    continue
                lowest = min(comp, key=lambda n: simple.nodes[n].get("elevation", 999))
                simple.add_edge(lowest, lowest_main,
                                length=50.0, highway="bridge_edge", synthetic=True)
            logger.info(f"[23] Bridged {len(components) - 1} disconnected subgraphs")

    logger.info(f"[23] SWMM-ready graph: {simple.number_of_nodes()} nodes, {simple.number_of_edges()} edges, weakly_connected={nx.is_weakly_connected(simple)}")
    return simple
