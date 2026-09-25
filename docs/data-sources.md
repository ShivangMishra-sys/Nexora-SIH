# UrbanFlow v2 — Data Sources Documentation
# Updated for v2 rebuild

## Overview
This document distinguishes **real (open dataset / real computation)** from **simulated/stubbed**
for every module, per the judging requirement.

---

## Data Layer Comparison

| Module | Component | Status | Source / Computation |
|---|---|---|---|
| **1.1 Terrain** | DEM | ✅ **Real tile (manual download)** or synthetic stand-in | Copernicus GLO-30 via AWS S3 |
| **1.1** | Vertical RMSE [43] | ✅ **Real computation** | vs. synthetic GCPs; logged, non-blocking |
| **1.1** | Hydro-enforcement [44] | ✅ **Real WBT computation** | WhiteboxTools `BreachDepressionsLeastCost` |
| **1.1** | Slope rasters [2] | ✅ **Real computation** | NumPy gradient on hydro-enforced DEM |
| **1.1** | Depression sinks [3] | ✅ **Real computation** | WhiteboxTools Wang & Liu fill |
| **1.1** | UTM reprojection [56] | ✅ **Real computation** | PyProj/Rasterio `.to_crs(EPSG:32643)` |
| **1.2 Land cover** | WorldCover tile | ✅ **Real tile (manual download)** or synthetic | ESA WorldCover 2021, 10m |
| **1.2** | C raster [4][5] | ✅ **Real lookup** | WorldCover class → runoff coefficient |
| **1.2** | OSM land-use [6] | ✅ **Real OSM fetch** | OSMnx `features_from_bbox` |
| **1.2** | Buildings [7] | ✅ **Real OSM fetch** | OSMnx `building=True` footprints |
| **1.2** | H3 grid [45] | ✅ **Real computation** | h3-py polyfill at resolution 10 |
| **1.2** | GEE provider | ⚠️ **Stub** | Requires GCP service-account + OAuth |
| **1.3 Road network** | OSM roads [8] | ✅ **Real OSM data** | OSMnx `graph_from_bbox` |
| **1.3** | Node elevations [9] | ✅ **Real computation** | OSMnx `add_node_elevations_raster` |
| **1.3** | Underpass flags [10] | ✅ **Real filter** | `tunnel=yes`, `layer<0`, `highway=underpass` |
| **1.3** | MST drain edges [66] | ✅ **Real computation** | NetworkX min-spanning-tree |
| **2. Rainfall** | Reflectivity frames | ⚠️ **Synthetic** | Gaussian Lagrangian storm cell |
| **2** | Z→R conversion [11] | ✅ **Real wradlib** | `wrl.trafo.idecibel` + `wrl.zr.z_to_r(a=200,b=1.6)` |
| **2** | Precipitation tracker [12] | ✅ **Real computation** | Pandas/NumPy sliding window |
| **2** | Grid interpolation [13] | ✅ **Real computation** | SciPy `griddata` |
| **2** | Nowcast [14] | ✅ **Real PySTEPS optical flow** | `pysteps.motion.lucaskanade` + extrapolation |
| **2** | Cumulative integration [15] | ✅ **Real computation** | Xarray time-axis integral |
| **3. Infiltration** | AMC [16] | ✅ **Real computation** | SCS rolling 5-day record |
| **3** | Horton / Green-Ampt [17] | ✅ **Real computation** | SciPy-compatible formulas, LULC-keyed |
| **4. Runoff** | Rational method [32] | ✅ **Real computation** | Q = C·I·A per cell |
| **4** | D8 routing [33] | ✅ **Real computation** | RichDEM or NumPy D8 |
| **4** | Manning velocity [34][37] | ✅ **Real computation** | Numba-JIT kinematic wave |
| **4** | Mass balance [35] | ✅ **Real computation** | NumPy per-cell |
| **5. Drainage** | SWMM .inp [18-22] | ✅ **Real swmmio generation** | From OSMnx graph |
| **5** | Blockage model [25] | ✅ **Real RandomForest** | sklearn, retraining changes outcomes |
| **5** | PySWMM runner [26-28] | ✅ **Real PySWMM** | `step_advance(60)` coupled stepping |
| **5** | CWC telemetry [29] | ⚠️ **Stub** | Mock endpoint; real: cwc.gov.in/telemetry |
| **5** | Tidal tailwater [30] | ⚠️ **Stub** | pytides/INCOIS stub; skips if inland |
| **5** | Pump station [31] | ✅ **Real PySWMM** | Synthetic pump with start/stop triggers |
| **6. Coupling** | 2D↔1D exchange [38][39] | ✅ **Real bidirectional loop** | Volume exchange per tick via weir equations |
| **7. Context** | Water bodies [40] | ✅ **Real OSM** | `natural=water`, `waterway=riverbank` |
| **7** | Critical infra [63] | ✅ **Real OSM** | Hospitals, metro, substations |
| **7** | MQTT sensors [42] | ⚠️ **Stub publisher** | paho-mqtt subscriber wired; mock publisher |
| **8. Simulation** | GPU/CPU dispatch [47] | ✅ **Real Numba JIT** | `@njit(parallel=True)` CPU; CuPy GPU |
| **8** | Ensemble [49] | ✅ **Real Monte Carlo** | N=20 perturbed rainfall members |
| **8** | Risk classification [50] | ✅ **Real computation** | `np.select` 4-band |
| **8** | DBSCAN hotspots [51] | ✅ **Real sklearn DBSCAN** | Contiguous >15cm cell clustering |
| **8** | Celery tasks [54] | ✅ **Real Celery + Redis** | Background tick-advance |
| **9. Routing** | Dijkstra [57] | ✅ **Real computation** | NetworkX with flood impedance |
| **9** | Live edge weights [58] | ✅ **Real update** | Per-tick depth → weight |
| **9** | Vehicle classes [60] | ✅ **Real logic** | Parameterised impassable threshold |
| **10. Persistence** | PostgreSQL + PostGIS [55] | ✅ **Real DB** | TimescaleDB image |
| **10** | Validation [64] | ✅ **Real sklearn** | RMSE + F1 vs. seeded ground truth |
| **10** | Calibration [65] | ✅ **Real SciPy** | `optimize.minimize` on Manning's n |
| **12. Frontend** | MapLibre GL JS [52] | ✅ **Real rendering** | Flood-colored road network |
| **12** | Timeline scrubber [53] | ✅ **Real cached snapshots** | Never recomputes on scrub |
| **12** | Geocoding [71] | ✅ **Real Nominatim** | geopy |
| **12** | What-if controls [72] | ✅ **Real backend wiring** | Blockage slider → POST /api/scenario/run |

---

## Known Constraints & Production Swap Points

### Swap 1 — Rainfall (Module 2)
**Current**: `synthetic_reflectivity_frame()` produces a NumPy dBZ array.
**Production swap**: Replace with `wrl.io.read_opera_hdf5(path)['dataset1/data1/data']`
pointed at IMD Doppler BUFR/ODIM-H5 files fetched from `ftp://ftp.imd.gov.in/pub/radar/`.
**Zero downstream changes required** — wradlib Z→R, PySTEPS, SciPy griddata all run identically.

### Swap 2 — Land Cover (Module 1.2)
**Current**: Pre-downloaded ESA WorldCover GeoTIFF in `/data/landcover/worldcover_tile.tif`.
**Production swap**: Instantiate `GEEProvider` instead of `CachedTileProvider`.
Requires GCP service account JSON + registered Earth Engine project.
The `GEEProvider` class is present in `landcover.py` as documented dead code.

### Swap 3 — WhiteboxTools binary (Docker)
**Current**: `docker/WhiteboxTools_linux_amd64.zip` committed to repo (or fallback to NumPy D8).
**Production**: Download latest release from GitHub at CI time to avoid binary staleness.

### Swap 4 — CWC Stage Telemetry (Module 5.29)
**Current**: `get_cwc_stage_telemetry()` returns synthetic stage values.
**Production swap**: `GET https://cwc.gov.in/telemetry?station={id}` (requires CWC API registration).

### Swap 5 — MQTT Sensors (Module 7.42)
**Current**: paho-mqtt subscriber running; mock publisher generates synthetic level readings.
**Production**: Wire real ultrasonic sensor publishers (e.g., ESP32 + paho) to the same topic `urbanflow/sensors/#`.

---

## Honest Assessment for Judges

| Component | Real? |
|---|---|
| Road topology (OSM real roads) | ✅ Yes |
| Terrain (DEM) | ✅ Yes (if tile downloaded) / synthetic stand-in otherwise |
| Land cover | ✅ Yes (if tile downloaded) / synthetic stand-in otherwise |
| Rainfall reflectivity | ⚠️ Synthetic Gaussian; **real wradlib/PySTEPS math runs on it** |
| Drainage network | ✅ Yes (auto-generated from real OSM topology via swmmio/PySWMM) |
| Coupled 2D↔1D solve | ✅ Yes (bidirectional volume exchange each tick) |
| Blockage model | ✅ Yes (RandomForest; retraining changes outcomes) |
| Model accuracy dashboard | ✅ Yes (sklearn RMSE+F1 vs. seeded ground truth) |
| CWC gauge telemetry | ⚠️ Stub — integration point documented |
| Tidal tailwater | ⚠️ Stub — pytides integration point documented |
| Sensor MQTT | ⚠️ Stub publisher — subscriber infrastructure real |
