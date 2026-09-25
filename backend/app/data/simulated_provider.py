"""
UrbanFlow — Simulated Data Provider
======================================
The active default provider for demo/hackathon builds.

Data sources used:
  - Road network: OpenStreetMap via Overpass API (real Chennai roads)
  - Elevation: Open-Elevation API with synthetic coastal fallback
  - Rainfall: Gaussian storm cell (see simulation/storm.py)

This is a fully functional, spatially coherent simulation — not random noise.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from app.config import (
    BOUNDING_BOX,
    ELEVATION_BATCH_SIZE,
    ELEVATION_FALLBACK_BASE_M,
    ELEVATION_FALLBACK_SLOPE,
    ELEVATION_TIMEOUT_S,
    OPEN_ELEVATION_URL,
    OVERPASS_TIMEOUT_S,
    OVERPASS_URL,
    PIPE_CAPACITY_BY_ROAD_CLASS,
)
from .provider import DataProvider

logger = logging.getLogger("urbanflow.simulated_provider")

# OSM highway tags we want to include in the network
OSM_HIGHWAY_TAGS = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "residential", "service", "unclassified", "living_street",
    "motorway_link", "trunk_link", "primary_link", "secondary_link",
}


class SimulatedProvider(DataProvider):
    """
    Provides real Chennai road topology + synthetic storm data.
    """

    def provider_name(self) -> str:
        return "SimulatedProvider (OSM roads + synthetic rainfall)"

    def get_bounding_box(self) -> Tuple[float, float, float, float]:
        return BOUNDING_BOX

    # ------------------------------------------------------------------
    # Road network (real OSM data via Overpass)
    # ------------------------------------------------------------------

    def fetch_road_network(self) -> Dict[str, Any]:
        """
        Fetch Chennai road network from Overpass API.
        Returns parsed nodes and edges suitable for graph construction.
        """
        min_lon, min_lat, max_lon, max_lat = BOUNDING_BOX
        # Overpass bbox format: (min_lat, min_lon, max_lat, max_lon)
        bbox_str = f"{min_lat},{min_lon},{max_lat},{max_lon}"

        query = f"""
        [out:json][timeout:{OVERPASS_TIMEOUT_S}];
        (
          way["highway"]({bbox_str});
        );
        out body;
        >;
        out skel qt;
        """

        logger.info(f"Fetching OSM road network for bbox {bbox_str}...")
        try:
            resp = requests.post(
                OVERPASS_URL,
                data={"data": query},
                headers={
                    "User-Agent": "UrbanFlow-SIH2026/1.0 (contact: demo@nexora.example.com)",
                    "Accept": "*/*"
                },
                timeout=OVERPASS_TIMEOUT_S + 5,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info(
                f"OSM fetch complete: {len(data.get('elements', []))} elements"
            )
        except Exception as e:
            logger.warning(
                f"Overpass API failed ({e}). Using synthetic road network."
            )
            return self._generate_synthetic_network()

        return self._parse_overpass(data)

    def _parse_overpass(self, data: dict) -> Dict[str, Any]:
        """Parse Overpass JSON → nodes and edges."""
        # Index all OSM nodes by ID
        osm_nodes: Dict[int, Dict] = {}
        for el in data.get("elements", []):
            if el["type"] == "node":
                osm_nodes[el["id"]] = {"lat": el["lat"], "lon": el["lon"]}

        nodes: List[Dict] = []
        edges: List[Dict] = []
        seen_nodes = set()

        for el in data.get("elements", []):
            if el["type"] != "way":
                continue
            tags = el.get("tags", {})
            highway = tags.get("highway", "")
            if highway not in OSM_HIGHWAY_TAGS:
                continue

            # Normalise link roads
            road_class = highway.replace("_link", "")
            if road_class not in PIPE_CAPACITY_BY_ROAD_CLASS:
                road_class = "default"

            way_node_ids = el.get("nodes", [])
            if len(way_node_ids) < 2:
                continue

            # Add intersection nodes only (first, last, and OSM nodes
            # that appear in multiple ways — approximate with all)
            for osm_id in way_node_ids:
                if osm_id not in osm_nodes:
                    continue
                if osm_id not in seen_nodes:
                    seen_nodes.add(osm_id)
                    n = osm_nodes[osm_id]
                    nodes.append({
                        "id": str(osm_id),
                        "lat": n["lat"],
                        "lon": n["lon"],
                        "road_class": road_class,
                        "elevation_m": 0.0,  # filled later
                    })

            # Add edges between consecutive way nodes
            for i in range(len(way_node_ids) - 1):
                u_id = way_node_ids[i]
                v_id = way_node_ids[i + 1]
                if u_id not in osm_nodes or v_id not in osm_nodes:
                    continue
                u_n = osm_nodes[u_id]
                v_n = osm_nodes[v_id]
                length_m = self._haversine_m(
                    u_n["lat"], u_n["lon"], v_n["lat"], v_n["lon"]
                )
                if length_m < 0.5:   # skip degenerate segments
                    continue
                edges.append({
                    "from_id": str(u_id),
                    "to_id": str(v_id),
                    "road_class": road_class,
                    "length_m": length_m,
                    "pipe_capacity_m3s": PIPE_CAPACITY_BY_ROAD_CLASS.get(
                        road_class, PIPE_CAPACITY_BY_ROAD_CLASS["default"]
                    ),
                    "osm_id": el["id"],
                })

        # Limit to nodes that actually appear in edges
        edge_node_ids = set()
        for e in edges:
            edge_node_ids.add(e["from_id"])
            edge_node_ids.add(e["to_id"])
        nodes = [n for n in nodes if n["id"] in edge_node_ids]

        # Deduplicate nodes
        seen = set()
        unique_nodes = []
        for n in nodes:
            if n["id"] not in seen:
                seen.add(n["id"])
                unique_nodes.append(n)

        logger.info(
            f"Parsed: {len(unique_nodes)} nodes, {len(edges)} edges"
        )
        return {"nodes": unique_nodes, "edges": edges}

    def _generate_synthetic_network(self) -> Dict[str, Any]:
        """
        Fallback: generate a regular grid network approximating the bbox.
        Used when Overpass API is unreachable.
        """
        import random
        rng = random.Random(42)
        min_lon, min_lat, max_lon, max_lat = BOUNDING_BOX
        rows, cols = 15, 20
        lat_step = (max_lat - min_lat) / rows
        lon_step = (max_lon - min_lon) / cols
        road_classes = ["primary", "secondary", "residential", "tertiary"]

        nodes, edges = [], []
        node_ids = {}
        for r in range(rows + 1):
            for c in range(cols + 1):
                lat = min_lat + r * lat_step + rng.uniform(-lat_step * 0.1, lat_step * 0.1)
                lon = min_lon + c * lon_step + rng.uniform(-lon_step * 0.1, lon_step * 0.1)
                rc = road_classes[(r + c) % len(road_classes)]
                nid = f"syn_{r}_{c}"
                node_ids[(r, c)] = nid
                nodes.append({"id": nid, "lat": lat, "lon": lon,
                               "road_class": rc, "elevation_m": 0.0})

        for r in range(rows + 1):
            for c in range(cols + 1):
                nid = node_ids[(r, c)]
                if c < cols:
                    mid = node_ids[(r, c + 1)]
                    rc = road_classes[(r + c) % len(road_classes)]
                    n1 = nodes[r * (cols + 1) + c]
                    n2 = nodes[r * (cols + 1) + c + 1]
                    edges.append({
                        "from_id": nid, "to_id": mid,
                        "road_class": rc,
                        "length_m": self._haversine_m(n1["lat"], n1["lon"], n2["lat"], n2["lon"]),
                        "pipe_capacity_m3s": PIPE_CAPACITY_BY_ROAD_CLASS.get(rc, 0.2),
                        "osm_id": 0,
                    })
                if r < rows:
                    mid = node_ids[(r + 1, c)]
                    rc = road_classes[(r + c) % len(road_classes)]
                    n1 = nodes[r * (cols + 1) + c]
                    n2 = nodes[(r + 1) * (cols + 1) + c]
                    edges.append({
                        "from_id": nid, "to_id": mid,
                        "road_class": rc,
                        "length_m": self._haversine_m(n1["lat"], n1["lon"], n2["lat"], n2["lon"]),
                        "pipe_capacity_m3s": PIPE_CAPACITY_BY_ROAD_CLASS.get(rc, 0.2),
                        "osm_id": 0,
                    })

        logger.info(
            f"Synthetic network: {len(nodes)} nodes, {len(edges)} edges"
        )
        return {"nodes": nodes, "edges": edges}

    # ------------------------------------------------------------------
    # Elevation
    # ------------------------------------------------------------------

    def fetch_elevations(self, locations: List[Tuple[float, float]]) -> List[float]:
        """
        Fetch elevation from Open-Elevation API in batches.
        Falls back to synthetic coastal gradient on failure.
        """
        results: List[Optional[float]] = [None] * len(locations)

        # Batch API calls
        batch_size = ELEVATION_BATCH_SIZE
        for batch_start in range(0, len(locations), batch_size):
            batch = locations[batch_start: batch_start + batch_size]
            try:
                payload = {
                    "locations": [
                        {"latitude": lat, "longitude": lon}
                        for lat, lon in batch
                    ]
                }
                resp = requests.post(
                    OPEN_ELEVATION_URL,
                    json=payload,
                    timeout=ELEVATION_TIMEOUT_S,
                )
                resp.raise_for_status()
                api_results = resp.json().get("results", [])
                for i, res in enumerate(api_results):
                    results[batch_start + i] = float(res.get("elevation", 0.0))
                time.sleep(0.3)   # rate-limit courtesy
            except Exception as e:
                logger.warning(
                    f"Open-Elevation API failed for batch {batch_start}: {e}. "
                    f"Using synthetic coastal DEM fallback."
                )
                for i, (lat, lon) in enumerate(batch):
                    results[batch_start + i] = self._synthetic_elevation(lat, lon)

        # Fill any remaining None (e.g. partial batches)
        return [
            v if v is not None else self._synthetic_elevation(*locations[i])
            for i, v in enumerate(results)
        ]

    def _synthetic_elevation(self, lat: float, lon: float) -> float:
        """
        Approximate elevation using a linear coastal gradient.
        Chennai rises from sea level (~1m) near the coast (east, low lat)
        to ~20m inland (north-west, higher lat).
        """
        min_lat = BOUNDING_BOX[1]
        elev = ELEVATION_FALLBACK_BASE_M + ELEVATION_FALLBACK_SLOPE * (lat - min_lat)
        return max(0.1, elev)

    # ------------------------------------------------------------------
    # Rainfall (delegates to storm cell)
    # ------------------------------------------------------------------

    def get_current_rainfall_grid(
        self,
        node_locations: List[Tuple[str, float, float]],
        sim_time_minutes: float = 0.0,
    ) -> Dict[str, float]:
        """
        In SimulatedProvider, rainfall comes from the active storm cell
        in the SimulationEngine. This method is a passthrough used by
        the bootstrap for initial state checks.

        The actual per-tick rainfall computation is done in:
          SimulationEngine._tick_internal() → NowcastEngine.nowcast_at_step()
        """
        return {nid: 0.0 for nid, _, _ in node_locations}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Great-circle distance in metres."""
        R = 6_371_000.0
        φ1, φ2 = math.radians(lat1), math.radians(lat2)
        Δφ = math.radians(lat2 - lat1)
        Δλ = math.radians(lon2 - lon1)
        a = math.sin(Δφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(Δλ / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
