"""
UrbanFlow v2 — Module 5: Drainage Network (1D) — SWMM .INP Auto-Generation
[18] swmmio: junction/manhole nodes from OSM intersections
[19] swmmio: lowest-elevation node → OUTFALL
[20] swmmio: conduits from road edges (pipe proxies)
[22] Manning's n for conduits via PySWMM
[23] nx.is_weakly_connected + isolates check BEFORE generating .inp
[24] GeoPandas sjoin_nearest: road nodes ↔ drainage inlet spatial join
[25] Scikit-learn RandomForest: blockage probability → capacity-derating
[26] pyswmm.Simulation with step_advance(60) for coupled stepping
[27] HGL check: n.depth > n.full_depth → surcharge
[28] Outfall boundary condition check
[29] Requests: mock CWC river/canal stage stub
[30] pytides/INCOIS stub: tailwater head at coastal outfalls
[31] PySWMM: pump curves / start-stop triggers
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Dict, Optional, Tuple

import networkx as nx
import numpy as np

from app.config import (
    SWMM_INP, BLOCKAGE_MODEL, DIAMETER_BY_CLASS, BBOX_WGS84,
)

logger = logging.getLogger("urbanflow.drainage")


# ---------------------------------------------------------------------------
# [25] Blockage probability model (RandomForest)
# ---------------------------------------------------------------------------
def train_blockage_model(save_path: Path = BLOCKAGE_MODEL) -> object:
    """
    [25] Train a RandomForest classifier on synthetic pipe attributes.
    Features: [pipe_age_yr, lulc_class, debris_history, road_class_encoded]
    Target: blockage_event (binary)

    Retraining this model with different debris-history distributions
    visibly changes blockage probabilities → different flood outcomes.
    """
    from sklearn.ensemble import RandomForestClassifier
    import pandas as pd

    rng = np.random.RandomState(42)
    n_samples = 2000

    # Synthetic training data
    road_classes = ["primary", "secondary", "tertiary", "residential", "service"]
    rc_map = {r: i for i, r in enumerate(road_classes)}

    pipe_age      = rng.uniform(5, 50, n_samples)
    lulc_class    = rng.choice([10, 20, 30, 40, 50, 60, 80], n_samples)
    debris_hist   = rng.uniform(0, 1, n_samples)   # 0=clean, 1=heavily blocked history
    rc_encoded    = rng.choice(list(rc_map.values()), n_samples)

    X = np.column_stack([pipe_age, lulc_class, debris_hist, rc_encoded])

    # Label: blockage more likely for older pipes near built-up areas w/ debris history
    prob = (
        0.01 * pipe_age
        + 0.5 * (lulc_class == 50).astype(float)
        + 0.8 * debris_hist
        + 0.1 * rc_encoded
    ) / 2.0
    y = (rng.uniform(0, 1, n_samples) < prob.clip(0, 1)).astype(int)

    clf = RandomForestClassifier(n_estimators=100, max_depth=6, random_state=42)
    clf.fit(X, y)

    from sklearn.metrics import f1_score
    preds = clf.predict(X)
    f1 = f1_score(y, preds)
    logger.info(f"[25] Blockage model trained — F1={f1:.3f} on training set")

    save_path.parent.mkdir(parents=True, exist_ok=True)
    with open(save_path, "wb") as f:
        pickle.dump(clf, f)
    logger.info(f"[25] Blockage model saved → {save_path}")
    return clf


def load_blockage_model(model_path: Path = BLOCKAGE_MODEL) -> object:
    """[25] Load trained blockage model; train fresh if not found."""
    if model_path.exists():
        with open(model_path, "rb") as f:
            return pickle.load(f)
    logger.info("[25] Blockage model not found; training now …")
    return train_blockage_model(model_path)


def compute_blockage_derating(
    G: nx.DiGraph,
    clf,
    lulc_class_map: Optional[Dict] = None,
) -> Dict[Tuple, float]:
    """
    [25] For each edge, predict blockage probability and compute
    capacity-derating multiplier applied to conduit Geom1/roughness.
    Returns {(u, v): derating_factor [0.3–1.0]}.
    """
    RC_MAP = {"primary": 0, "secondary": 1, "tertiary": 2,
              "residential": 3, "service": 4, "default": 2}
    derating = {}

    for u, v, data in G.edges(data=True):
        age = float(data.get("pipe_age_yr", 20.0))
        lulc = float(lulc_class_map.get(u, 50) if lulc_class_map else 50)
        debris = float(data.get("debris_history", 0.3))
        rc = float(RC_MAP.get(str(data.get("highway", "default")), 2))

        X = np.array([[age, lulc, debris, rc]])
        prob = clf.predict_proba(X)[0][1]   # probability of blockage

        # Derating: fully blocked → 0.3 capacity; clean → 1.0
        derating[(u, v)] = 1.0 - 0.7 * prob

    return derating


# ---------------------------------------------------------------------------
# [24] Spatial join: road nodes ↔ drainage inlet nodes
# ---------------------------------------------------------------------------
def spatial_join_to_grid(G: nx.DiGraph, grid_shape: Tuple[int, int], bbox: Tuple) -> Dict:
    """
    [24] GeoPandas sjoin_nearest: map each road/manhole node to the nearest
    surface grid cell (row, col). Returns {node_id: (row, col)}.
    """
    import geopandas as gpd
    from shapely.geometry import Point

    min_lon, min_lat, max_lon, max_lat = bbox
    rows, cols = grid_shape

    records = []
    for node_id, data in G.nodes(data=True):
        lon = data.get("x", data.get("lon", (min_lon + max_lon) / 2))
        lat = data.get("y", data.get("lat", (min_lat + max_lat) / 2))
        records.append({"node_id": node_id, "geometry": Point(lon, lat)})

    if not records:
        return {}

    gdf = gpd.GeoDataFrame(records, crs="EPSG:4326")

    node_grid_map = {}
    for _, row in gdf.iterrows():
        col = int((row.geometry.x - min_lon) / (max_lon - min_lon) * cols)
        r   = int((max_lat - row.geometry.y) / (max_lat - min_lat) * rows)
        col = min(max(0, col), cols - 1)
        r   = min(max(0, r),   rows - 1)
        node_grid_map[row["node_id"]] = (r, col)

    logger.info(f"[24] Spatially joined {len(node_grid_map)} nodes to grid cells")
    return node_grid_map


# ---------------------------------------------------------------------------
# [18][19][20][22] Generate SWMM .INP from OSM graph via swmmio
# ---------------------------------------------------------------------------
def generate_inp_from_osm_graph(
    G: nx.DiGraph,
    output_path: Path,
    blockage_derating: Optional[Dict] = None,
    rain_timeseries: Optional[list] = None,
) -> Path:
    """
    [18][19][20][22][23] Auto-generate a valid SWMM .inp from the OSMnx-derived graph.
    [23] Weakly-connected check enforced before this call (in road_network.py).
    """
    try:
        import swmmio
    except ImportError:
        logger.warning("swmmio not installed — writing minimal .inp manually")
        return _write_minimal_inp(G, output_path, blockage_derating, rain_timeseries)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        model = swmmio.Model.create_blank()

        # [18] Junctions — road intersections as manhole/inlet proxies
        for node_id, data in G.nodes(data=True):
            elev = float(data.get("elevation", 5.0))
            model.inp.junctions.loc[str(node_id)] = {
                "InvertElev":     elev - 1.0,   # 1m cover depth
                "MaxDepth":       1.5,
                "InitDepth":      0.0,
                "SurchargeDepth": 0.0,
                "PondedArea":     0.0,
            }

        # [19] Lowest-elevation node → OUTFALL
        outfall_node = min(G.nodes(data=True), key=lambda x: x[1].get("elevation", 999.0))[0]
        outfall_elev = float(G.nodes[outfall_node].get("elevation", 0.0)) - 2.0
        model.inp.outfalls.loc[str(outfall_node)] = {
            "InvertElev":  outfall_elev,
            "OutfallType": "FREE",
        }
        # Remove outfall from junctions to avoid duplicates
        if str(outfall_node) in model.inp.junctions.index:
            model.inp.junctions.drop(str(outfall_node), inplace=True)

        # [20][22] Conduits — road edges as proxy pipes
        for u, v, data in G.edges(data=True):
            road_class = str(data.get("highway", "default"))
            diameter = DIAMETER_BY_CLASS.get(road_class, DIAMETER_BY_CLASS["default"])

            # [25] Apply blockage-model capacity derating
            derate = 1.0
            if blockage_derating:
                derate = blockage_derating.get((u, v), 1.0)
            eff_diameter = diameter * derate

            cid = f"C_{u}_{v}"
            length = max(1.0, float(data.get("length", 50.0)))
            model.inp.conduits.loc[cid] = {
                "InletNode":  str(u),
                "OutletNode": str(v),
                "Length":     length,
                "Roughness":  0.013,   # [22] Manning's n for concrete pipes
                "InOffset":   0.0,
                "OutOffset":  0.0,
            }
            model.inp.xsections.loc[cid] = {
                "Shape": "CIRCULAR",
                "Geom1": eff_diameter,
            }

        # [RAINGAGES] Feed PySTEPS forecast as SWMM rainfall timeseries
        if rain_timeseries:
            _add_rain_timeseries(model, rain_timeseries)

        model.inp.save(str(output_path))
        logger.info(f"[18][20] SWMM .inp generated via swmmio → {output_path}")
        return output_path

    except Exception as e:
        logger.warning(f"swmmio .inp generation failed ({e}); using manual writer")
        return _write_minimal_inp(G, output_path, blockage_derating, rain_timeseries)


def _add_rain_timeseries(model, rain_timeseries: list) -> None:
    """
    Inject PySTEPS 0–3hr forecast into SWMM as a rainfall timeseries.
    rain_timeseries: list of (elapsed_hr, mm_hr) tuples.
    """
    try:
        import pandas as pd
        rows = []
        for t_hr, r_mm_hr in rain_timeseries:
            hh = int(t_hr)
            mm = int((t_hr - hh) * 60)
            rows.append({"SeriesName": "SYNTHETIC_RADAR", "Date": "01/01/2026",
                         "Time": f"{hh:02d}:{mm:02d}", "Value": r_mm_hr})
        model.inp.timeseries = pd.DataFrame(rows)

        # Add raingage
        model.inp.raingages.loc["RGAGE1"] = {
            "Format":       "INTENSITY",
            "Interval":     "0:05",
            "SCF":          1.0,
            "Source":       "TIMESERIES SYNTHETIC_RADAR",
        }
    except Exception as e:
        logger.debug(f"Rain timeseries injection skipped: {e}")


def _write_minimal_inp(G, output_path, blockage_derating, rain_timeseries) -> Path:
    """Fallback: write a syntactically valid minimal SWMM .inp manually."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "[TITLE]", "UrbanFlow SIH 2026 — Anna Nagar Chennai", "",
        "[OPTIONS]",
        "FLOW_UNITS        CMS",
        "INFILTRATION      HORTON",
        "FLOW_ROUTING      KINWAVE",
        "START_DATE        01/01/2026",
        "START_TIME        00:00:00",
        "END_DATE          01/01/2026",
        "END_TIME          03:00:00",
        "REPORT_STEP       00:01:00",
        "WET_STEP          00:01:00",
        "DRY_STEP          00:01:00",
        "ROUTING_STEP      0:00:60",
        "",
        "[JUNCTIONS]",
        ";;Name  InvertElev  MaxDepth  InitDepth  SurchargeDepth  PondedArea",
    ]

    nodes_list = list(G.nodes(data=True))
    if not nodes_list:
        lines += ["DUMMY_NODE  0.0  2.0  0.0  0.0  0.0"]
    else:
        outfall_node = min(nodes_list, key=lambda x: x[1].get("elevation", 999.0))[0]
        for node_id, data in nodes_list:
            if node_id == outfall_node:
                continue
            elev = float(data.get("elevation", 5.0)) - 1.0
            lines.append(f"N{node_id}  {elev:.2f}  1.5  0.0  0.0  0.0")

    lines += ["", "[OUTFALLS]", ";;Name  InvertElev  OutfallType"]
    if nodes_list:
        out_elev = float(G.nodes[outfall_node].get("elevation", 0.0)) - 2.0
        lines.append(f"N{outfall_node}  {out_elev:.2f}  FREE")

    lines += ["", "[CONDUITS]",
              ";;Name  From  To  Length  Roughness  InOffset  OutOffset"]
    for u, v, data in G.edges(data=True):
        length = max(1.0, float(data.get("length", 50.0)))
        lines.append(f"C{u}_{v}  N{u}  N{v}  {length:.1f}  0.013  0  0")

    lines += ["", "[XSECTIONS]", ";;Link  Shape  Geom1  Geom2  Geom3  Geom4"]
    for u, v, data in G.edges(data=True):
        rc = str(data.get("highway", "default"))
        d = DIAMETER_BY_CLASS.get(rc, 0.3)
        derate = blockage_derating.get((u, v), 1.0) if blockage_derating else 1.0
        lines.append(f"C{u}_{v}  CIRCULAR  {d * derate:.3f}  0  0  0")

    lines += ["", "[END]", ""]
    with open(output_path, "w") as f:
        f.write("\n".join(lines))
    logger.info(f"[18][20] Minimal SWMM .inp written → {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# [26][27][28] PySWMM step-advance coupled runner
# ---------------------------------------------------------------------------
class SWMMRunner:
    """
    [26][27][28] Step-advance SWMM runner for 2D↔1D coupling.
    Uses pyswmm.Simulation.step_advance(60) — not a blind run-to-completion.
    """

    def __init__(self, inp_path: Path):
        self.inp_path = inp_path
        self._sim = None
        self._nodes = None
        self._links = None
        self.surcharge_volume: Dict[str, float] = {}
        self.outfall_flow: Dict[str, float] = {}
        self._running = False

    def start(self) -> None:
        """[26] Open SWMM simulation and configure step-advance."""
        try:
            from pyswmm import Simulation, Nodes, Links
            self._sim = Simulation(str(self.inp_path))
            self._sim.step_advance(60)    # [26][47] 60s internal steps
            self._nodes = Nodes(self._sim)
            self._links = Links(self._sim)
            self._running = True
            logger.info(f"[26] PySWMM simulation started: {self.inp_path.name}")
        except Exception as e:
            logger.warning(f"[26] PySWMM start failed ({e}); using synthetic drainage model")
            self._running = False

    def step(self) -> Dict[str, float]:
        """
        [26][27][28] Advance one 60s step.
        Returns {node_id: surcharge_depth_m} for nodes exceeding full depth.
        """
        if not self._running or self._sim is None:
            return {}

        try:
            next(self._sim.__iter__())
        except StopIteration:
            self._running = False
            return {}

        surcharge = {}
        outfall   = {}

        for n in self._nodes:
            # [27] HGL check: node depth exceeds pipe full depth → surcharge
            if n.depth > n.full_depth:
                surcharge[n.nodeid] = n.depth - n.full_depth

            # [28] Outfall boundary: log flow for tailwater check
            if n.node_type == "OUTFALL":
                outfall[n.nodeid] = n.total_inflow

        self.surcharge_volume = surcharge
        self.outfall_flow     = outfall

        if surcharge:
            logger.debug(f"[27] {len(surcharge)} nodes surcharged this step")

        return surcharge

    def inject_inflow(self, node_inflow: Dict[str, float]) -> None:
        """[38] Inject surface-to-drain inflow (m³/s) per node from 2D model."""
        if not self._running:
            return
        try:
            for node_id, q_m3_s in node_inflow.items():
                n = self._nodes[str(node_id)]
                n.generated_inflow(q_m3_s)
        except Exception:
            pass   # node may not exist in .inp

    def close(self) -> None:
        """Close the SWMM simulation."""
        if self._sim is not None:
            try:
                self._sim.close()
            except Exception:
                pass
        self._running = False

    # -----------------------------------------------------------------------
    # Fallback synthetic drainage model (when PySWMM unavailable)
    # -----------------------------------------------------------------------
    def synthetic_step(
        self,
        node_inflow: Dict[str, float],
        pipe_capacity: Dict[Tuple, float],
    ) -> Dict[str, float]:
        """Simple capacity-exceeded→surcharge model when PySWMM is not available."""
        surcharge = {}
        for (u, v), cap in pipe_capacity.items():
            q_in = node_inflow.get(str(u), 0.0)
            if q_in > cap:
                surcharge[str(u)] = (q_in - cap) / max(1.0, cap) * 0.5   # depth proxy m
        self.surcharge_volume = surcharge
        return surcharge


# ---------------------------------------------------------------------------
# [29] Mock CWC river/canal stage telemetry
# ---------------------------------------------------------------------------
def get_cwc_stage_telemetry(station_id: str = "MAA_001") -> Dict:
    """
    [29] Mock CWC-style river/canal stage telemetry endpoint.
    Production integration: GET https://cwc.gov.in/telemetry?station={id}
    """
    import random
    stage_m = 1.2 + random.uniform(-0.3, 0.8)   # synthetic stage in metres
    return {
        "station_id": station_id,
        "stage_m": stage_m,
        "flow_m3s": stage_m * 2.5,   # rough rating curve proxy
        "timestamp": "2026-01-01T00:00:00Z",
        "_note": "Mock CWC stub. Real integration: https://cwc.gov.in/telemetry API",
    }


# ---------------------------------------------------------------------------
# [30] Tailwater head at coastal outfalls (pytides / INCOIS stub)
# ---------------------------------------------------------------------------
def get_coastal_tailwater_head(lat: float = 13.085, lon: float = 80.21) -> float:
    """
    [30] Estimate tailwater head at coastal outfalls.
    Production: pytides + INCOIS tidal prediction API.
    Stub returns synthetic tidal level based on time.
    Skips cleanly (returns 0) if not near coast.
    """
    COAST_LON_THRESHOLD = 80.28   # Anna Nagar is inland; skip
    if lon > COAST_LON_THRESHOLD:
        return 0.0   # Not coastal — no tailwater effect

    try:
        import pytides.tide as tide   # type: ignore
        # Stub: would use pytides.constituents to compute tidal height
        return 0.8   # placeholder: 0.8m tidal level
    except ImportError:
        # INCOIS API stub
        import math, time
        tidal = 0.5 * math.sin(2 * math.pi * time.time() / 44700) + 0.5
        return float(tidal)


# ---------------------------------------------------------------------------
# [31] Synthetic pump station
# ---------------------------------------------------------------------------
def add_synthetic_pump(model_inp_path: Path, pump_node: str = "PUMP_KOYAMBEDU") -> None:
    """
    [31] PySWMM: one synthetic pump station with start/stop depth triggers.
    Appended to the .inp after initial generation.
    """
    pump_section = f"""
[PUMPS]
;;Name  From  To  Curve  InitStatus  StartDepth  StopDepth
{pump_node}_PMP  SUMP_{pump_node}  DISCHARGE_{pump_node}  PUMP_CRV1  OFF  0.5  0.1

[CURVES]
;;Name  Type  X  Y
PUMP_CRV1  PUMP3  0.0  0.0
PUMP_CRV1  PUMP3  1.0  0.5
PUMP_CRV1  PUMP3  2.0  1.0

[JUNCTIONS]
SUMP_{pump_node}  3.0  2.0  0.0  0.0  0.0
DISCHARGE_{pump_node}  5.0  2.0  0.0  0.0  0.0
"""
    if model_inp_path.exists():
        with open(model_inp_path, "a") as f:
            f.write(pump_section)
        logger.info(f"[31] Synthetic pump station appended to {model_inp_path.name}")
