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


# ---------------------------------------------------------------------------
# [58] Build routable graph with live flood weights
# ---------------------------------------------------------------------------
def build_flood_weighted_graph(
    G: nx.DiGraph,
    depth_cm_at_node: Dict,          # {node_id: depth_cm}
    vehicle_class: str = "car",      # [60]
) -> nx.DiGraph:
    """
    [57][58][59][60] Build a weighted copy of G with flood-adjusted edge costs.
    Edge weight = base_length × impedance_multiplier.
    """
    impassable_threshold = VEHICLE_IMPASSABLE_CM.get(vehicle_class, 15.0)  # [60]
    weighted = nx.DiGraph()

    for node, data in G.nodes(data=True):
        weighted.add_node(node, **data)

    for u, v, data in G.edges(data=True):
        base_len = float(data.get("length", 50.0))

        # Use the WORSE of the two endpoint depths
        d_u = depth_cm_at_node.get(str(u), 0.0)
        d_v = depth_cm_at_node.get(str(v), 0.0)
        depth_cm = max(d_u, d_v)

        # [59] Impassable beyond vehicle-class threshold
        if depth_cm >= impassable_threshold:
            weight = base_len * ROUTE_IMPEDANCE["impassable"]   # [59]
        elif depth_cm >= RISK_THRESHOLDS["critical"]:
            weight = base_len * ROUTE_IMPEDANCE["critical"]
        elif depth_cm >= RISK_THRESHOLDS["caution"]:
            weight = base_len * ROUTE_IMPEDANCE["caution"]
        else:
            weight = base_len * ROUTE_IMPEDANCE["safe"]

        # Underpass/tunnel boost [10]
        if data.get("high_risk_depression"):
            weight *= float(data.get("flood_impedance_boost", 3.0))

        weighted.add_edge(u, v, weight=weight, flood_depth_cm=depth_cm,
                          base_length=base_len, **data)

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
) -> Optional[Dict]:
    """
    [57] Dijkstra + flood impedance function.
    Returns safe route path and comparison stats vs. naive shortest.
    """
    if start_node not in G or end_node not in G:
        logger.warning(f"[57] Start ({start_node}) or end ({end_node}) not in graph")
        return None

    weighted = build_flood_weighted_graph(G, depth_cm_at_node, vehicle_class)

    try:
        # [57] Flood-safe route (flood-weighted)
        safe_path = nx.dijkstra_path(weighted, start_node, end_node, weight="weight")
        safe_length = nx.dijkstra_path_length(weighted, start_node, end_node, weight="base_length")
        safe_weight  = nx.dijkstra_path_length(weighted, start_node, end_node, weight="weight")

        # Naive shortest (unweighted by flood)
        naive_path = nx.dijkstra_path(G, start_node, end_node,
                                       weight=lambda u,v,d: d.get("length", 50.0))
        naive_length = nx.dijkstra_path_length(G, start_node, end_node,
                                                weight=lambda u,v,d: d.get("length", 50.0))
    except nx.NetworkXNoPath:
        logger.warning(f"[57] No path found between {start_node} and {end_node}")
        return None

    def path_to_coords(path, graph):
        coords = []
        for n in path:
            data = graph.nodes[n]
            lon = data.get("x", data.get("lon", 80.21))
            lat = data.get("y", data.get("lat", 13.09))
            coords.append({"lat": float(lat), "lon": float(lon)})
        return coords

    # Max depth along safe path
    safe_depths = [depth_cm_at_node.get(str(n), 0.0) for n in safe_path]
    naive_depths = [depth_cm_at_node.get(str(n), 0.0) for n in naive_path]

    return {
        "start": {"node": start_node},
        "end":   {"node": end_node},
        "vehicle_class": vehicle_class,
        "safe_route": {
            "node_ids":     [str(n) for n in safe_path],
            "coordinates":  path_to_coords(safe_path, G),
            "distance_m":   safe_length,
            "max_depth_cm": float(max(safe_depths, default=0.0)),
        },
        "naive_route": {
            "node_ids":     [str(n) for n in naive_path],
            "coordinates":  path_to_coords(naive_path, G),
            "distance_m":   naive_length,
            "max_depth_cm": float(max(naive_depths, default=0.0)),
        },
        "comparison": {
            "distance_saved_m":      naive_length - safe_length,
            "max_depth_avoided_cm":  max(naive_depths, default=0.0) - max(safe_depths, default=0.0),
            "safe_weight_ratio":     safe_weight / max(1.0, naive_length),
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
def update_edge_weights(G: nx.DiGraph, depth_cm_at_node: Dict, vehicle_class: str = "car") -> None:
    """[58] In-place update of edge weights from latest depth data."""
    impassable_threshold = VEHICLE_IMPASSABLE_CM.get(vehicle_class, 15.0)
    for u, v, data in G.edges(data=True):
        d_u = depth_cm_at_node.get(str(u), 0.0)
        d_v = depth_cm_at_node.get(str(v), 0.0)
        depth_cm = max(d_u, d_v)

        base = float(data.get("base_length", data.get("length", 50.0)))
        if depth_cm >= impassable_threshold:
            data["weight"] = base * ROUTE_IMPEDANCE["impassable"]
        elif depth_cm >= RISK_THRESHOLDS["critical"]:
            data["weight"] = base * ROUTE_IMPEDANCE["critical"]
        elif depth_cm >= RISK_THRESHOLDS["caution"]:
            data["weight"] = base * ROUTE_IMPEDANCE["caution"]
        else:
            data["weight"] = base * ROUTE_IMPEDANCE["safe"]
        data["flood_depth_cm"] = depth_cm


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
