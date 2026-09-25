"""
UrbanFlow v2 — Configuration
Anna Nagar, Chennai bounding box (EPSG:4326), all constants centralised here.
"""
from __future__ import annotations
from pathlib import Path

# ---------------------------------------------------------------------------
# Fixed bounding box — Anna Nagar, Chennai
# (min_lon, min_lat, max_lon, max_lat) in WGS-84 / EPSG:4326
# ---------------------------------------------------------------------------
BBOX_WGS84 = (80.18, 13.07, 80.24, 13.13)   # ~6x6 km, historically flood-prone
BBOX_PLACE = "Anna Nagar, Chennai, India"
WORKING_CRS = "EPSG:32643"                    # [56] UTM 43N — single working CRS

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------
DATA_DIR      = Path("/data")
DEM_RAW       = DATA_DIR / "dem" / "raw_dem.tif"
DEM_BREACHED  = DATA_DIR / "dem" / "breached.tif"
DEM_SLOPE_X   = DATA_DIR / "dem" / "slope_x.tif"
DEM_SLOPE_Y   = DATA_DIR / "dem" / "slope_y.tif"
LANDCOVER_TIF = DATA_DIR / "landcover" / "worldcover_tile.tif"
OSM_GRAPH_PKL = DATA_DIR / "osm" / "road_graph.pkl"
SWMM_INP      = DATA_DIR / "swmm" / "urbanflow.inp"
BLOCKAGE_MODEL= DATA_DIR / "swmm" / "blockage_model.pkl"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"

# Whitebox binary location (set via ENV in Docker; falls back for local dev)
import os
WBT_PATH = os.environ.get("WBT_PATH", "/opt/whitebox/WBT")

# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------
GRID_RESOLUTION_M = 10          # [46] uniform 10m grid
H3_RESOLUTION     = 10          # [45] H3 hex resolution (~15m edge)

# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------
SIMULATION_DT_S        = 60     # [47] internal timestep, seconds
SIMULATION_DT_MIN      = 1      # minutes
FORECAST_HORIZONS_MIN  = [15, 30, 60, 120, 180]   # [48] cached snapshots
PYSTEPS_BUFFER_FRAMES  = 10     # [14] rolling buffer for optical-flow
ENSEMBLE_MEMBERS       = 20     # [49] Monte Carlo ensemble size

# ---------------------------------------------------------------------------
# Manning's n (default; calibrated by [65] SciPy optimize)
# ---------------------------------------------------------------------------
MANNING_N_DEFAULT = 0.015

# ---------------------------------------------------------------------------
# Risk classification thresholds (cm) [50]
# ---------------------------------------------------------------------------
RISK_THRESHOLDS = {
    "safe":       5.0,    # < 5 cm
    "caution":    15.0,   # 5–15 cm
    "critical":   30.0,   # 15–30 cm
    "impassable": 1e9,    # > 30 cm
}

# ---------------------------------------------------------------------------
# Routing — flood impedance multipliers [57]
# ---------------------------------------------------------------------------
ROUTE_IMPEDANCE = {
    "safe":       1.0,
    "caution":    2.0,
    "critical":   10.0,
    "impassable": 1000.0,
}
# Vehicle-class impassable thresholds (cm) [60]
VEHICLE_IMPASSABLE_CM = {
    "car":         15.0,
    "suv":         25.0,
    "fire_tender": 30.0,
    "bus":         20.0,
}

# ---------------------------------------------------------------------------
# WorldCover → runoff coefficient C [4][5]
# ---------------------------------------------------------------------------
WORLDCOVER_C = {
    10: 0.25,   # Tree cover
    20: 0.30,   # Shrubland
    30: 0.35,   # Grassland
    40: 0.40,   # Cropland
    50: 0.90,   # Built-up (impervious) ← urban Chennai
    60: 0.50,   # Bare / sparse
    80: 1.00,   # Permanent water body
}
WORLDCOVER_C_DEFAULT = 0.70  # fallback for unmapped classes

# ---------------------------------------------------------------------------
# Pipe diameter by road class (m) [20][22]
# ---------------------------------------------------------------------------
DIAMETER_BY_CLASS = {
    "motorway":   1.20,
    "trunk":      1.00,
    "primary":    0.90,
    "secondary":  0.60,
    "tertiary":   0.45,
    "residential":0.30,
    "service":    0.25,
    "default":    0.30,
}

# ---------------------------------------------------------------------------
# Infrastructure buffers for alerting (m) [63]
# ---------------------------------------------------------------------------
INFRA_BUFFER_M = 200   # 200 m radius around hospitals, metro, substations

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://urbanflow:urbanflow@postgres:5432/urbanflow"
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
CELERY_BROKER = REDIS_URL
CELERY_BACKEND = REDIS_URL

# ---------------------------------------------------------------------------
# MQTT stub
# ---------------------------------------------------------------------------
MQTT_BROKER_HOST = os.environ.get("MQTT_BROKER", "localhost")
MQTT_BROKER_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_TOPIC_SENSORS = "urbanflow/sensors/#"

# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN  = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM        = os.environ.get("TWILIO_FROM", "")
FCM_SERVER_KEY     = os.environ.get("FCM_SERVER_KEY", "")
