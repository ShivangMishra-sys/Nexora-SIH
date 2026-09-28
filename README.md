# UrbanFlow — Urban Flood Nowcasting & Flood-Aware Routing

> **Team Nexora** | **SIH 2026** | **PS ID 26085** | **Theme: Disaster Management**
> **Study area:** Anna Nagar, Chennai (`80.18–80.24°E, 13.07–13.13°N`, roughly 6 × 6 km)

UrbanFlow is a decision-support prototype that turns a short-term rainfall scenario into **road-level flood risk** and **flood-aware routes**. It answers three questions:

1. Where is flooding likely to occur in the next 0–3 hours?
2. Which roads are likely to be affected?
3. What alternative route can be considered?

```
Rainfall → Runoff & Drainage → Flood Depth → Road-Level Risk → Flood-Aware Route
```

> **Prototype status — please read.** This is a working demonstration of the full pipeline, not an operational forecasting system. Rainfall is **simulated** from storm scenarios (no live radar or gauge feed yet), and the drainage network is **approximated from the road network**. See [Data Provenance](#data-provenance) and [Known Limitations](#known-limitations) for exactly what is real and what is not.

---

## What the Prototype Does

- **0–180 minute flood simulation** over the study area, advancing in 5-minute steps, with a timeline scrubber to move through cached snapshots.
- **Four storm scenarios** (Cloudburst, Monsoon Front, Moderate Steady, Light Drizzle) with adjustable storm parameters.
- **Physics-based flood modelling:** rainfall → infiltration → 2D surface runoff → 1D drainage, with surcharge from drains returned to the street surface each step.
- **Road-level risk:** flood depth is sampled onto every road segment and classed as Safe / Caution / Critical / Impassable.
- **Flood-aware routing:** click two points on the map to get a flood-aware route next to the naive shortest route, with a comparison of distance and maximum depth encountered. Supports vehicle classes (car, SUV, bus, fire tender) with different depth tolerances.
- **Time-aware routes:** routes are computed against the flood state at the selected timeline minute and recompute when the timeline or vehicle changes.
- **What-if controls:** a drain-blockage slider that reduces drainage capacity and re-runs the scenario.
- **Live dashboard:** WebSocket-streamed flood state, hotspot zones, incident feed, analytics charts, and address search.

---

## Quick Start

### 1. Add the terrain and land-cover tiles

Large rasters are not committed to the repo (see `.gitignore`). Place them here before the first run:

```
data/
├── dem/
│   └── raw_dem.tif              # DEM covering the study area (e.g. Copernicus GLO-30)
└── landcover/
    └── worldcover_tile.tif      # ESA WorldCover 10 m tile covering the study area
```

If these files are missing, the backend **generates synthetic stand-ins** and logs `generating synthetic stand-in`. Confirm the logs say `Using real DEM tile` and `Using real WorldCover tile` before demoing.

> **Swapping tiles later?** Delete the derived files in `data/dem/` (everything except `raw_dem.tif`) and `data/swmm/` so they are rebuilt. Bootstrap reuses existing derived rasters.

### 2. Run with Docker

```bash
docker compose up --build
```

The first start builds the derived rasters, fetches the OpenStreetMap road network (needs internet access), builds the drainage model and starts the default scenario. Results are cached in `data/`, so later starts are much faster.

Then open:

| URL | What |
|---|---|
| http://localhost:3000 | Dashboard |
| http://localhost:8000/docs | FastAPI Swagger UI |

Docker Compose starts six services: `backend`, `frontend`, `celery_worker`, `postgres` (TimescaleDB image), `redis` and `mosquitto`.

The Dockerfile uses `docker/WhiteboxTools_linux_amd64.zip` if present, otherwise downloads WhiteboxTools during the build, and falls back to NumPy if neither is available.

### Acceptance checklist

- [ ] Map loads with the Chennai road network coloured by flood risk
- [ ] Storm animates and flooding develops in low-lying areas
- [ ] Timeline scrubber moves the map to any point in the 0–180 min window
- [ ] Clicking two map points returns a flood-aware route and a naive route with comparison stats
- [ ] Changing vehicle class or timeline minute recomputes the active route
- [ ] Drain-blockage slider and scenario buttons change the simulation

---

## Architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│ DATA LAYER                                                            │
│  DEM (real tile)      WorldCover (real tile)     OSM roads/land-use/  │
│  hydro-enforced,      → runoff coefficient       buildings/hospitals  │
│  UTM 43N, 10 m grid                                                   │
│  Rainfall: synthetic storm scenario (dBZ frames)                      │
└───────────────────────────────┬───────────────────────────────────────┘
                                │
┌───────────────────────────────▼───────────────────────────────────────┐
│ SIMULATION (backend/app/simulation)                                   │
│  rainfall.py     dBZ → mm/hr (Marshall–Palmer), rolling frame buffer, │
│                  short-horizon extrapolation                          │
│  infiltration.py antecedent moisture (SCS classes) + land-cover-based │
│                  net rainfall                                         │
│  runoff_2d.py    Rational-method runoff, D8 routing, overland flow    │
│                  and mass balance (Numba-accelerated)                 │
│  drainage_1d.py  drainage network derived from road graph, SWMM input │
│                  generation, blockage model (RandomForest)            │
│  coupling.py     2D ↔ 1D exchange each step, risk classification,     │
│                  hotspot clustering, snapshot cache                   │
└───────────────────────────────┬───────────────────────────────────────┘
                                │
┌───────────────────────────────▼───────────────────────────────────────┐
│ ROUTING (backend/app/routing/safe_router.py)                          │
│  depth sampled along each road segment → edge cost →                  │
│  passable-first Dijkstra + naive shortest path for comparison         │
└───────────────────────────────┬───────────────────────────────────────┘
                                │
┌───────────────────────────────▼───────────────────────────────────────┐
│ API (FastAPI, backend/app/main.py)      REST + WebSocket stream       │
└───────────────────────────────┬───────────────────────────────────────┘
                                │
┌───────────────────────────────▼───────────────────────────────────────┐
│ FRONTEND (Next.js 14 + MapLibre GL JS + Recharts)                     │
│  /               dashboard: map, timeline, scenarios, incidents       │
│  /route-planner  click-to-route workflow                              │
│  /analytics      rainfall, risk distribution, depth & drainage charts │
└───────────────────────────────────────────────────────────────────────┘
```

**Simulation clock.** The backend advances one 5-minute simulation step every 3 seconds of real time and broadcasts each state over WebSocket. At 180 minutes it holds briefly and replays the scenario. Snapshots at the standard horizons are cached for the timeline scrubber.

---

## Data Provenance

| Layer | Source in this prototype | Status |
|---|---|---|
| Road network | OpenStreetMap (OSMnx) | Real |
| OSM land-use, buildings, water bodies, critical infrastructure | OpenStreetMap | Real |
| Terrain (DEM) | Tile placed in `data/dem/raw_dem.tif`, reprojected to UTM 43N, resampled to 10 m, hydro-enforced with WhiteboxTools | Real (synthetic stand-in if tile absent) |
| Land cover | ESA WorldCover tile in `data/landcover/`, mapped to runoff coefficients and refined with OSM land-use | Real (synthetic stand-in if tile absent) |
| Rainfall | Moving Gaussian storm cell producing synthetic reflectivity frames, converted to rain rate with Marshall–Palmer Z–R | **Simulated** |
| Drainage network | Approximated from the OSM road graph; pipe sizes assigned by road class; vertices at intersections | **Approximated** — no municipal drainage data |
| Drain blockage | RandomForest trained on synthetic pipe attributes | **Synthetic training data** |
| Historical flood records | Not used | — |
| Radar / gauges / sensors | Not connected (see [Future Work](#future-work)) | — |

### Doppler radar

Doppler weather radar data is **not** used, because access requires authorisation. The rainfall module takes 2D reflectivity (dBZ) arrays, so a real radar composite can replace the synthetic frames at the ingestion point without changes to downstream modules. `backend/app/data/live_provider.py` documents the intended integration contract.

---

## Simulation Details

### Rainfall and short-term forecast
- Synthetic reflectivity frames are converted to rain rate with the Marshall–Palmer relation (`Z = 200·R^1.6`), using `wradlib` when installed and an equivalent inline calculation otherwise.
- A rolling buffer of frames feeds a short-horizon extrapolation. `pysteps` optical-flow extrapolation is wired in but **not included in `requirements.txt`**, so the default build uses the built-in fallback extrapolation.
- The 0–180 min horizon is driven by the selected scenario's storm parameters advancing through time.

### Infiltration
Antecedent moisture is tracked from accumulated rainfall (SCS-style dry/normal/wet classes) and applied with land-cover-dependent infiltration to produce net rainfall.

### Surface runoff
Rational-method runoff (`Q = C·i·A`) per cell with the runoff coefficient from land cover, D8 flow routing on the hydro-enforced DEM, overland-flow and mass-balance updates per time step, and Manning-based flow velocity. Buildings are burned into the coefficient raster as barriers.

### Drainage and coupling
A drainage network is derived from the road graph, with capacity set by road class and derated by the blockage model. Each step exchanges volume between the street surface and the drains; when a drain exceeds capacity the overflow is returned to the surface as flood depth. PySWMM/swmmio are used to build and step the drainage model where available, with a built-in hydraulic fallback.

### Risk classes

| Class | Depth | Meaning |
|---|---|---|
| Safe | < 5 cm | Normal conditions |
| Caution | 5–15 cm | Pooling water; pedestrian and low-vehicle risk |
| Critical | 15–30 cm | Vehicle disruption likely |
| Impassable | ≥ 30 cm | Severe; avoid |

Contiguous cells above 15 cm are grouped into **hotspot zones** using connected-component labelling on a downsampled grid.

---

## Flood-Aware Routing

For a chosen start and end point (snapped to the nearest road node), the router:

1. **Samples flood depth along each road segment**: endpoints, midpoint and geometry vertices, using the worst value found. It uses the depth grid for the selected timeline minute.
2. **Assigns an edge cost** from that depth and the vehicle class:

   | Condition | Cost multiplier on length |
   |---|---|
   | Depth below 2 cm | ×1 |
   | 2–5 cm | ×2 |
   | 5–15 cm | ×15 to ×60 (rises non-linearly with depth) |
   | ≥ 15 cm but still passable for the vehicle | ×80 |
   | At or above the vehicle's depth limit | Treated as impassable (very large cost) |

   Virtual drain links are never used as roads. Underpasses and tunnels carry an extra penalty.
3. **Searches passable-first.** It first looks for a route using only passable segments, then relaxes to ignoring one-way restrictions (emergency-style routing), and only as a last resort accepts flooded segments if the start or end is trapped.
4. **Returns** the flood-aware route, the naive shortest route, and a comparison (distance difference, maximum depth avoided).

| Vehicle class | Depth limit |
|---|---|
| Car | 15 cm |
| Bus | 20 cm |
| SUV | 25 cm |
| Fire tender | 30 cm |

UrbanFlow does **not** claim any route is completely safe. It provides risk-aware route information to support better-informed decisions.

---

## API Reference

Interactive docs are available at `http://localhost:8000/docs`.

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/api/scenario/list` | Available storm scenarios |
| GET | `/api/scenario/status` | Current scenario and simulation status |
| POST | `/api/scenario/run` | Start or switch a scenario (`scenario`, `intensity_dbz`, `storm_center`, `radius_fraction`, `drain_blockage_pct`) |
| POST | `/api/scenario/pause` / `/api/scenario/resume` | Pause or resume the simulation clock |
| GET | `/api/flood/state?t=N` | Flood state at simulation minute N (latest if omitted) |
| GET | `/api/flood/summary` | Lightweight summary without per-node data |
| POST | `/api/v1/route` | Flood-aware route (`start`, `end` as `[lat, lon]`, `vehicle_class`, optional `time_min`) |
| GET | `/api/v1/nowcast` | Rainfall forecast at standard horizons |
| GET | `/api/network/graph` | Road network as GeoJSON with flood attributes |
| GET | `/api/network/bbox` | Study-area bounding box |
| GET | `/api/snapshots` | Cached snapshot minutes |
| GET | `/api/v1/geocode?q=...` | Address search (Nominatim) |
| POST | `/api/simulation/retrain-blockage` | Retrain the blockage model |
| POST | `/api/alerts/test` | Dispatch a test alert (requires Twilio credentials) |
| GET | `/api/validation` | Consistency-check metrics (see limitations) |
| WS | `/ws/flood-stream` | Live flood-state stream |

### Smoke tests

```bash
curl http://localhost:8000/health
curl "http://localhost:8000/api/flood/state?t=60"

# Flood-aware route inside the study area
curl -X POST http://localhost:8000/api/v1/route \
  -H "Content-Type: application/json" \
  -d '{"start": [13.085, 80.20], "end": [13.11, 80.23], "vehicle_class": "car", "time_min": 60}'

# Switch scenario
curl -X POST http://localhost:8000/api/scenario/run \
  -H "Content-Type: application/json" \
  -d '{"scenario": "moderate_steady"}'
```

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/flood-stream');
ws.onmessage = (e) => console.log(JSON.parse(e.data));
```

---

## Technology Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, Python 3.11, uvicorn |
| Geospatial | rasterio, GeoPandas, OSMnx, Shapely, PyProj, WhiteboxTools |
| Simulation | NumPy, SciPy, Numba, NetworkX, PySWMM / swmmio, scikit-learn |
| Frontend | Next.js 14, TypeScript, MapLibre GL JS, Recharts, Tailwind CSS |
| Infrastructure | Docker Compose, Redis (pub/sub, Celery broker), PostgreSQL/TimescaleDB, Mosquitto (MQTT) |

---

## Project Structure

```
├── backend/app/
│   ├── main.py                 # FastAPI app, simulation loop, REST + WebSocket
│   ├── config.py               # Study area, grid, thresholds, vehicle limits
│   ├── startup/bootstrap.py    # Data-layer initialisation
│   ├── data/                   # terrain, land cover, road network
│   ├── simulation/             # rainfall, infiltration, runoff_2d, drainage_1d, coupling
│   ├── routing/safe_router.py  # Flood-aware routing
│   └── tasks.py                # Celery tasks
├── frontend/src/
│   ├── app/                    # Dashboard, route planner, analytics
│   ├── components/             # Map, panels, timeline
│   ├── hooks/                  # WebSocket, simulation, map interaction
│   └── lib/                    # API client, map styles
├── docker/  docker-compose.yml
└── docs/data-sources.md
```

Some modules (`backend/app/api/`, `simulation_engine.py`, `drainage.py`, `runoff.py`, `flood_predictor.py`, `nowcast.py`, `storm.py`, `simulated_provider.py`) come from an earlier iteration and are **not used by the running application**.

---

## Known Limitations

- **Rainfall is simulated.** There is no live radar, gauge or forecast ingestion. The "nowcast" is a storm scenario advancing through time, not a forecast from observations.
- **Drainage is approximated** from the road network. Real drainage geometry, capacities and bottlenecks are not available to the prototype.
- **The blockage model uses synthetic training data.** It illustrates how blockage changes outcomes but is not calibrated to real drain conditions.
- **No real-world validation yet.** The RMSE and F1 values shown by `/api/validation` and in the dashboard header come from a check against a small set of illustrative reference points and are clamped to a fixed range. They are **not** measured accuracy against observed floods. Historical flood records are not used.
- **Snapshots between cached times are approximate.** If no snapshot exists for a requested minute, the API scales the latest state.
- **Fallback routing can cross flooded roads** if the start or end is trapped in flooded areas. Routes are an aid to decision-making, not a guarantee of safety.
- **Single study area.** Only Anna Nagar is configured.
- **Optional integrations are stubs:** MQTT sensors (subscriber only logs messages), Twilio/FCM alerts (need credentials), and CWC/tidal inputs. The PostgreSQL run-history layer is provisioned but not wired into the running app.

---

## Future Work

- Doppler weather radar (IMD) ingestion in place of synthetic frames
- Real drainage network and asset data from municipal sources
- Calibration and validation against historical flood events and high-water marks
- IoT water-level sensors, CCTV/computer-vision flood detection and crowdsourced reports
- Live traffic and road-closure data in route costs
- Automated citizen and responder alerts; emergency-services integration
- Expansion to other cities and continuous model updating from incoming observations

---

**Team Nexora | SIH 2026 | PS ID 26085 | Disaster Management**
