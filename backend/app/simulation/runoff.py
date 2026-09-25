"""
UrbanFlow — Surface Runoff Calculator (Rational Method)
========================================================
Computes surface runoff at each network node using the Rational Method:

    Q = C · i · A

where:
  Q — peak runoff rate (m³/s)
  C — dimensionless runoff coefficient (0–1), road-class dependent
  i — rainfall intensity (m/s), converted from mm/hr
  A — contributing catchment area (m²), approximated from Voronoi cells

D8 flow routing:
  Surface runoff generated at each node is routed downhill to adjacent nodes
  using a simplified D8 scheme: water flows entirely to the single lowest
  adjacent node (by elevation). This creates the surface accumulation that,
  when it exceeds drainage capacity, causes flooding.

Reference:
  Chow, Maidment & Mays (1988) "Applied Hydrology", §14.4 (Rational Method)
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple
import networkx as nx

from app.config import RUNOFF_COEFF_BY_ROAD_CLASS


# ---------------------------------------------------------------------------
# mm/hr → m/s conversion
# ---------------------------------------------------------------------------

def mm_hr_to_m_s(mm_hr: float) -> float:
    """Convert rainfall intensity from mm/hr to m/s."""
    return mm_hr / (1000.0 * 3600.0)


# ---------------------------------------------------------------------------
# Contributing Area (Voronoi approximation)
# ---------------------------------------------------------------------------

def compute_voronoi_areas(
    nodes: List[Tuple[str, float, float]],  # (node_id, lat, lon)
    bbox: Tuple[float, float, float, float],  # (min_lon, min_lat, max_lon, max_lat)
) -> Dict[str, float]:
    """
    Approximate contributing catchment area for each node using 2-D Voronoi
    tessellation in projected coordinates (Web Mercator approximation).

    Returns:
        dict mapping node_id → area in m²
    """
    from scipy.spatial import Voronoi, ConvexHull
    import numpy as np

    if len(nodes) < 4:
        # Fall back to equal-area split for tiny networks
        total_area = _bbox_area_m2(bbox)
        per_node = total_area / max(len(nodes), 1)
        return {nid: per_node for nid, _, _ in nodes}

    # Project lat/lon to approximate metres (flat-Earth for small bbox)
    ref_lat = (bbox[1] + bbox[3]) / 2
    lat_m = 111_320.0                          # metres per degree latitude
    lon_m = 111_320.0 * math.cos(math.radians(ref_lat))  # metres per degree longitude

    ids = [n[0] for n in nodes]
    pts = np.array([[n[2] * lon_m, n[1] * lat_m] for n in nodes])  # (x=lon, y=lat)

    # Add mirror points outside the bbox to bound the Voronoi diagram
    # (prevents infinite regions at the boundary)
    min_x = bbox[0] * lon_m
    max_x = bbox[2] * lon_m
    min_y = bbox[1] * lat_m
    max_y = bbox[3] * lat_m
    margin = max(max_x - min_x, max_y - min_y) * 2

    mirrors = np.array([
        [min_x - margin, (min_y + max_y) / 2],
        [max_x + margin, (min_y + max_y) / 2],
        [(min_x + max_x) / 2, min_y - margin],
        [(min_x + max_x) / 2, max_y + margin],
    ])
    all_pts = np.vstack([pts, mirrors])

    try:
        vor = Voronoi(all_pts)
    except Exception:
        total_area = _bbox_area_m2(bbox)
        per_node = total_area / len(nodes)
        return {nid: per_node for nid in ids}

    # Compute area of each Voronoi region for the original (non-mirror) points
    bbox_poly = np.array([
        [min_x, min_y], [max_x, min_y], [max_x, max_y], [min_x, max_y]
    ])

    areas: Dict[str, float] = {}
    for i, node_id in enumerate(ids):
        region_idx = vor.point_region[i]
        vertices_idx = vor.regions[region_idx]
        if -1 in vertices_idx or len(vertices_idx) < 3:
            # Unbounded region — use bbox-clipped fallback
            areas[node_id] = _bbox_area_m2(bbox) / len(nodes)
            continue
        polygon = vor.vertices[vertices_idx]
        try:
            area = _polygon_area(polygon)
        except Exception:
            area = _bbox_area_m2(bbox) / len(nodes)
        # Minimum area: 100 m² (street-width × short segment)
        areas[node_id] = max(area, 100.0)

    return areas


def _polygon_area(points) -> float:
    """Shoelace formula for polygon area."""
    import numpy as np
    x = points[:, 0]
    y = points[:, 1]
    return 0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))


def _bbox_area_m2(bbox: Tuple[float, float, float, float]) -> float:
    """Approximate area of bounding box in m²."""
    ref_lat = (bbox[1] + bbox[3]) / 2
    lat_m = 111_320.0
    lon_m = 111_320.0 * math.cos(math.radians(ref_lat))
    return abs(bbox[2] - bbox[0]) * lon_m * abs(bbox[3] - bbox[1]) * lat_m


# ---------------------------------------------------------------------------
# Runoff Calculator
# ---------------------------------------------------------------------------

class RunoffCalculator:
    """
    Computes surface runoff Q (m³/s) at each network node and routes
    excess surface water downhill using a D8-style scheme.
    """

    def __init__(
        self,
        graph: nx.Graph,
        voronoi_areas: Dict[str, float],
    ):
        """
        Args:
            graph:          NetworkX graph with node attrs: lat, lon, elevation, road_class
            voronoi_areas:  Pre-computed contributing area per node (m²)
        """
        self.graph = graph
        self.voronoi_areas = voronoi_areas
        self._runoff_coeffs: Dict[str, float] = {}
        self._node_neighbours: Dict[str, List[str]] = {}
        self._precompute()

    def _precompute(self):
        """Cache road-class-based coefficients and neighbour lists."""
        for node_id, attrs in self.graph.nodes(data=True):
            road_class = attrs.get("road_class", "default")
            self._runoff_coeffs[node_id] = RUNOFF_COEFF_BY_ROAD_CLASS.get(
                road_class, RUNOFF_COEFF_BY_ROAD_CLASS["default"]
            )
            self._node_neighbours[node_id] = list(self.graph.neighbors(node_id))

    def compute_node_runoff(
        self,
        rainfall_dict: Dict[str, float],  # node_id → mm/hr
    ) -> Dict[str, float]:
        """
        Apply Rational Method at each node.

        Returns:
            dict node_id → Q in m³/s (local generation, before D8 routing)
        """
        runoff: Dict[str, float] = {}
        for node_id in self.graph.nodes():
            C = self._runoff_coeffs.get(node_id, 0.82)
            i_mm_hr = rainfall_dict.get(node_id, 0.0)
            i_m_s = mm_hr_to_m_s(i_mm_hr)
            A = self.voronoi_areas.get(node_id, 500.0)
            Q = C * i_m_s * A  # m³/s
            runoff[node_id] = max(0.0, Q)
        return runoff

    def route_d8(
        self,
        local_runoff: Dict[str, float],
    ) -> Dict[str, float]:
        """
        D8 surface flow routing: each node's runoff drains entirely to
        the single lowest-elevation adjacent node.

        Returns:
            dict node_id → accumulated runoff inflow (m³/s), including
            contributions from uphill neighbours.
        """
        node_elevations: Dict[str, float] = {
            nid: self.graph.nodes[nid].get("elevation", 5.0)
            for nid in self.graph.nodes()
        }
        accumulated = dict(local_runoff)  # start with local generation

        # Process nodes in order from highest to lowest elevation
        sorted_nodes = sorted(
            self.graph.nodes(),
            key=lambda nid: -node_elevations.get(nid, 0.0)
        )

        for node_id in sorted_nodes:
            neighbours = self._node_neighbours.get(node_id, [])
            if not neighbours:
                continue
            own_elev = node_elevations.get(node_id, 5.0)
            # D8: find lowest neighbour
            lowest_neighbour = min(
                neighbours,
                key=lambda nid: node_elevations.get(nid, own_elev)
            )
            lowest_elev = node_elevations.get(lowest_neighbour, own_elev)
            if lowest_elev < own_elev:
                # Route all accumulated water downhill
                flow = accumulated.get(node_id, 0.0)
                accumulated[lowest_neighbour] = accumulated.get(lowest_neighbour, 0.0) + flow
                accumulated[node_id] = 0.0   # water has left this node

        return accumulated

    def compute(
        self,
        rainfall_dict: Dict[str, float],
    ) -> Dict[str, float]:
        """
        Full runoff computation: Rational Method → D8 routing.

        Returns:
            dict node_id → total inflow rate (m³/s) arriving at each node
        """
        local = self.compute_node_runoff(rainfall_dict)
        routed = self.route_d8(local)
        return routed
