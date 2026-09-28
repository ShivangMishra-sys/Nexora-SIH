"""
UrbanFlow v2 — Module 9: Routing Engine
[57] NetworkX astar_path/dijkstra_path: flood-safe routes with custom edge impedance
[58] Dynamic edge weight updates each tick from live depth
[59] Edge weight → ∞ when depth > 15cm
[60] Vehicle-class impassable threshold parameterization
[61] FastAPI endpoints: /api/v1/route, /api/v1/nowcast
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import networkx as nx
import numpy as np

from app.config import ROUTE_IMPEDANCE, RISK_THRESHOLDS, VEHICLE_IMPASSABLE_CM

logger = logging.getLogger("urbanflow.routing")


def _sample_point_depth(
    lat: float,
    lon: float,
    depth_grid: Optional[np.ndarray],
    bbox: Optional[Tuple[float, float, float, float]],
) -> float:
    """Sample flood depth at a geographic coordinate using a 3x3 window."""
    if depth_grid is None or bbox is None:
        return 0.0
    min_lon, min_lat, max_lon, max_lat = bbox
    if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
        return 0.0
    rows, cols = depth_grid.shape
    c = int((lon - min_lon) / (max_lon - min_lon) * cols)
    r = int((max_lat - lat) / (max_lat - min_lat) * rows)
    c = min(max(0, c), cols - 1)
    r = min(max(0, r), rows - 1)
    r_min, r_max = max(0, r - 1), min(rows, r + 2)
    c_min, c_max = max(0, c - 1), min(cols, c + 2)
    win = depth_grid[r_min:r_max, c_min:c_max]
    return float(np.max(win)) if win.size > 0 else float(depth_grid[r, c])


def _sample_edge_depth(
    u,
    v,
    data: Dict,
    G: nx.DiGraph,
    depth_cm_at_node: Dict,
    depth_grid: Optional[np.ndarray] = None,
    bbox: Optional[Tuple[float, float, float, float]] = None,
) -> float:
    """Sample the worst flood depth along an edge including endpoints, midpoint, and vertices."""
    d_u = float(depth_cm_at_node.get(str(u), 0.0))
    d_v = float(depth_cm_at_node.get(str(v), 0.0))
    max_d = max(d_u, d_v)

    if depth_grid is not None and bbox is not None:
        u_data = G.nodes.get(u, {})
        v_data = G.nodes.get(v, {})
        u_lat = u_data.get("y", u_data.get("lat"))
        u_lon = u_data.get("x", u_data.get("lon"))
        v_lat = v_data.get("y", v_data.get("lat"))
        v_lon = v_data.get("x", v_data.get("lon"))

        if u_lat is not None and v_lat is not None and u_lon is not None and v_lon is not None:
            mid_lat = (float(u_lat) + float(v_lat)) / 2.0
            mid_lon = (float(u_lon) + float(v_lon)) / 2.0
            max_d = max(max_d, _sample_point_depth(mid_lat, mid_lon, depth_grid, bbox))

        geom = data.get("geometry")
        if geom is not None:
            try:
                coords = list(geom.coords) if hasattr(geom, "coords") else geom
                for pt in coords:
                    max_d = max(max_d, _sample_point_depth(float(pt[1]), float(pt[0]), depth_grid, bbox))
            except Exception:
                pass

    return float(max_d)


# ---------------------------------------------------------------------------
# [58] Build routable graph with live flood weights
# ---------------------------------------------------------------------------
def build_flood_weighted_graph(
    G: nx.DiGraph,
    depth_cm_at_node: Dict,          # {node_id: depth_cm}
    vehicle_class: str = "car",      # [60]
    depth_cm_2d: Optional[np.ndarray] = None,
    grid_bbox: Optional[Tuple[float, float, float, float]] = None,
) -> nx.DiGraph:
    """
    [57][58][59][60] Build a weighted copy of G with flood-adjusted edge costs.
    Applies strict Passable-First marking and non-linear penalties for flooded corridors.
    """
    impassable_threshold = VEHICLE_IMPASSABLE_CM.get(vehicle_class, 15.0)  # [60]
    weighted = nx.DiGraph()

    for node, data in G.nodes(data=True):
        weighted.add_node(node, **data)

    for u, v, data in G.edges(data=True):
        # Synthetic drain edges are virtual SWMM conduits, NOT drivable streets
        if data.get("synthetic_drain"):
            continue

        base_len = float(data.get("length", data.get("base_length", 50.0)))
        depth_cm = _sample_edge_depth(u, v, data, G, depth_cm_at_node, depth_cm_2d, grid_bbox)

        # Flood impedance & passability determination
        is_passable = depth_cm < impassable_threshold
        if not is_passable:
            # Extreme barrier penalty so fallback pathfinder avoids it if any alternative exists
            weight = base_len * 10_000_000.0 * (1.0 + depth_cm)
        elif depth_cm >= RISK_THRESHOLDS["caution"]:           # 15.0 cm (if vehicle has higher threshold)
            weight = base_len * 80.0
        elif depth_cm >= RISK_THRESHOLDS["safe"]:              # 5.0 cm
            # Aggressive non-linear penalty: 5cm -> 15x, 10cm -> 35x, 14cm -> 60x
            ratio = min(1.0, max(0.0, (depth_cm - RISK_THRESHOLDS["safe"]) / 10.0))
            weight = base_len * (15.0 + 45.0 * (ratio ** 2))
        elif depth_cm >= 2.0:
            weight = base_len * 2.0                             # Shallow pooling (2-5cm)
        else:
            weight = base_len * 1.0                             # Dry / negligible (< 2cm)

        # Underpass/tunnel boost [10]
        if data.get("high_risk_depression"):
            weight *= float(data.get("flood_impedance_boost", 3.0))

        # Parallel edge deduplication: retain the safest (lowest weight) edge
        if weighted.has_edge(u, v):
            if weight < weighted[u][v]["weight"]:
                weighted[u][v].update(data)
                weighted[u][v]["weight"] = weight
                weighted[u][v]["flood_depth_cm"] = depth_cm
                weighted[u][v]["base_length"] = base_len
                weighted[u][v]["is_passable"] = is_passable
        else:
            weighted.add_edge(
                u, v,
                weight=weight,
                flood_depth_cm=depth_cm,
                base_length=base_len,
                is_passable=is_passable,
                **data,
            )

    return weighted


def _heuristic(u, v, G):
    """A* heuristic: straight-line distance in metres (lat/lon approx)."""
    try:
        x1 = G.nodes[u].get("x", 0); y1 = G.nodes[u].get("y", 0)
        x2 = G.nodes[v].get("x", 0); y2 = G.nodes[v].get("y", 0)
        return ((x1 - x2)**2 + (y1 - y2)**2)**0.5 * 111_320
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# [57] Flood-safe route computation
# ---------------------------------------------------------------------------
def compute_safe_route(
    G: nx.DiGraph,
    depth_cm_at_node: Dict,
    start_node,
    end_node,
    vehicle_class: str = "car",
    depth_cm_2d: Optional[np.ndarray] = None,
    grid_bbox: Optional[Tuple[float, float, float, float]] = None,
) -> Optional[Dict]:
    """
    [57] Passable-First Dijkstra + flood impedance function.
    Guarantees that impassable flooded streets are actively detoured if any passable route exists.
    Returns safe route path and comparison stats vs. naive shortest.
    """
    if start_node not in G or end_node not in G:
        logger.warning(f"[57] Start ({start_node}) or end ({end_node}) not in graph")
        return None

    weighted = build_flood_weighted_graph(
        G, depth_cm_at_node, vehicle_class, depth_cm_2d, grid_bbox
    )

    # 1. Build Passable-First subgraph containing only passable edges
    passable_subgraph = nx.DiGraph()
    for node, ndata in weighted.nodes(data=True):
        passable_subgraph.add_node(node, **ndata)
    for u, v, edata in weighted.edges(data=True):
        if edata.get("is_passable", True):
            passable_subgraph.add_edge(u, v, **edata)

    safe_path = None

    # Attempt 1: Directed passable subgraph
    if start_node in passable_subgraph and end_node in passable_subgraph:
        try:
            safe_path = nx.dijkstra_path(passable_subgraph, start_node, end_node, weight="weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            safe_path = None

    # Attempt 2: Undirected passable subgraph (emergency disaster routing)
    if safe_path is None:
        try:
            undir_passable = passable_subgraph.to_undirected(as_view=True)
            safe_path = nx.dijkstra_path(undir_passable, start_node, end_node, weight="weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            safe_path = None

    # Attempt 3: Fallback with extreme barrier weights if start/end trapped in flooded zone
    if safe_path is None:
        try:
            safe_path = nx.dijkstra_path(weighted, start_node, end_node, weight="weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            try:
                undir_weighted = weighted.to_undirected(as_view=True)
                safe_path = nx.dijkstra_path(undir_weighted, start_node, end_node, weight="weight")
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                logger.warning(f"[57] No safe path found between {start_node} and {end_node}")
                return None

    # 2. Naive shortest path (ignores flood, uses pure physical road distance)
    try:
        naive_path = nx.dijkstra_path(weighted, start_node, end_node, weight="base_length")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        try:
            undir_weighted = weighted.to_undirected(as_view=True)
            naive_path = nx.dijkstra_path(undir_weighted, start_node, end_node, weight="base_length")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            logger.warning(f"[57] No naive path between {start_node} and {end_node}")
            return None

    def _path_length(path, graph):
        length = 0.0
        for u, v in zip(path[:-1], path[1:]):
            ed = graph.get_edge_data(u, v) or graph.get_edge_data(v, u) or {}
            length += float(ed.get("base_length", ed.get("length", 50.0)))
        return length

    def _path_weight(path, graph):
        total_w = 0.0
        for u, v in zip(path[:-1], path[1:]):
            ed = graph.get_edge_data(u, v) or graph.get_edge_data(v, u) or {}
            total_w += float(ed.get("weight", ed.get("base_length", 50.0)))
        return total_w

    def _path_max_depth(path, graph, node_depths):
        max_d = 0.0
        for n in path:
            max_d = max(max_d, float(node_depths.get(str(n), 0.0)))
        for u, v in zip(path[:-1], path[1:]):
            ed = graph.get_edge_data(u, v) or graph.get_edge_data(v, u) or {}
            max_d = max(max_d, float(ed.get("flood_depth_cm", 0.0)))
        return max_d

    def path_to_coords(path, graph):
        coords = []
        for i, n in enumerate(path):
            data = graph.nodes[n]
            lon = float(data.get("x", data.get("lon", 80.21)))
            lat = float(data.get("y", data.get("lat", 13.09)))

            # If edge has detailed OSM geometry, use it for curved street fidelity
            if i < len(path) - 1:
                nxt = path[i + 1]
                ed = graph.get_edge_data(n, nxt) or graph.get_edge_data(nxt, n) or {}
                geom = ed.get("geometry")
                if geom is not None and hasattr(geom, "coords"):
                    pts = list(geom.coords)
                    if pts:
                        # Ensure geometry points run in direction from n to nxt
                        first_pt, last_pt = pts[0], pts[-1]
                        dist_first = (first_pt[0] - lon)**2 + (first_pt[1] - lat)**2
                        dist_last = (last_pt[0] - lon)**2 + (last_pt[1] - lat)**2
                        if dist_last < dist_first:
                            pts = list(reversed(pts))
                        for pt in pts:
                            coords.append({"lat": round(float(pt[1]), 6), "lon": round(float(pt[0]), 6)})
                        continue
            coords.append({"lat": round(lat, 6), "lon": round(lon, 6)})
        return coords

    safe_length = _path_length(safe_path, weighted)
    safe_weight = _path_weight(safe_path, weighted)
    naive_length = _path_length(naive_path, weighted)

    safe_max_d = _path_max_depth(safe_path, weighted, depth_cm_at_node)
    naive_max_d = _path_max_depth(naive_path, weighted, depth_cm_at_node)

    return {
        "start": {"node": start_node},
        "end":   {"node": end_node},
        "vehicle_class": vehicle_class,
        "safe_route": {
            "node_ids":     [str(n) for n in safe_path],
            "coordinates":  path_to_coords(safe_path, G),
            "distance_m":   round(safe_length, 1),
            "max_depth_cm": round(safe_max_d, 1),
        },
        "naive_route": {
            "node_ids":     [str(n) for n in naive_path],
            "coordinates":  path_to_coords(naive_path, G),
            "distance_m":   round(naive_length, 1),
            "max_depth_cm": round(naive_max_d, 1),
        },
        "comparison": {
            "distance_saved_m":      round(naive_length - safe_length, 1),
            "max_depth_avoided_cm":  round(naive_max_d - safe_max_d, 1),
            "safe_weight_ratio":     round(safe_weight / max(1.0, naive_length), 2),
        },
    }


# ---------------------------------------------------------------------------
# Snap lat/lon to nearest graph node
# ---------------------------------------------------------------------------
def nearest_node(G: nx.DiGraph, lat: float, lon: float):
    """Return the graph node nearest to the given lat/lon."""
    best_node = None
    best_dist = float("inf")
    for node, data in G.nodes(data=True):
        nlat = data.get("y", data.get("lat", 0.0))
        nlon = data.get("x", data.get("lon", 0.0))
        dist = (nlat - lat)**2 + (nlon - lon)**2
        if dist < best_dist:
            best_dist = dist
            best_node = node
    return best_node


# ---------------------------------------------------------------------------
# [58] Live edge weight update
# ---------------------------------------------------------------------------
def update_edge_weights(
    G: nx.DiGraph,
    depth_cm_at_node: Dict,
    vehicle_class: str = "car",
    depth_cm_2d: Optional[np.ndarray] = None,
    grid_bbox: Optional[Tuple[float, float, float, float]] = None,
) -> None:
    """[58] In-place update of edge weights from latest depth data."""
    impassable_threshold = VEHICLE_IMPASSABLE_CM.get(vehicle_class, 15.0)
    for u, v, data in G.edges(data=True):
        if data.get("synthetic_drain"):
            continue
        depth_cm = _sample_edge_depth(u, v, data, G, depth_cm_at_node, depth_cm_2d, grid_bbox)
        base = float(data.get("base_length", data.get("length", 50.0)))
        is_passable = depth_cm < impassable_threshold

        if not is_passable:
            data["weight"] = base * 10_000_000.0 * (1.0 + depth_cm)
        elif depth_cm >= RISK_THRESHOLDS["caution"]:
            data["weight"] = base * 80.0
        elif depth_cm >= RISK_THRESHOLDS["safe"]:
            ratio = min(1.0, max(0.0, (depth_cm - RISK_THRESHOLDS["safe"]) / 10.0))
            data["weight"] = base * (15.0 + 45.0 * (ratio ** 2))
        elif depth_cm >= 2.0:
            data["weight"] = base * 2.0
        else:
            data["weight"] = base * 1.0

        data["flood_depth_cm"] = depth_cm
        data["is_passable"] = is_passable


# ---------------------------------------------------------------------------
# [63] Infrastructure alert check
# ---------------------------------------------------------------------------
def check_infrastructure_alerts(
    infra_gdf,
    depth_cm: np.ndarray,
    grid_transform,
    buffer_m: float = 200.0,
) -> List[Dict]:
    """[63] Flag critical infrastructure when predicted risk falls within buffer."""
    alerts = []
    if infra_gdf is None or len(infra_gdf) == 0:
        return alerts

    from rasterio.transform import rowcol
    for _, row in infra_gdf.iterrows():
        try:
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            r, c = rowcol(grid_transform, geom.centroid.x, geom.centroid.y)
            r = min(max(0, int(r)), depth_cm.shape[0] - 1)
            c = min(max(0, int(c)), depth_cm.shape[1] - 1)
            d = float(depth_cm[r, c])
            if d > RISK_THRESHOLDS["caution"]:
                amenity = row.get("amenity", row.get("railway", "infrastructure"))
                alerts.append({
                    "type":      str(amenity),
                    "depth_cm":  d,
                    "severity":  "critical" if d > RISK_THRESHOLDS["critical"] else "caution",
                    "lat":       float(geom.centroid.y),
                    "lon":       float(geom.centroid.x),
                    "name":      str(row.get("name", "Unknown")),
                })
        except Exception:
            pass
    return alerts
