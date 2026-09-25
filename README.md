# UrbanFlow — Urban Flood Nowcasting & Safe-Routing System

> **Team**: Nexora | **SIH 2026** | **PS ID**: 26085 | **Theme**: Disaster Management  
> **Demo Area**: Chennai T. Nagar / Anna Nagar (`13.05–13.12°N, 80.22–80.30°E`)

---

## Quick Start

```bash
# Clone / navigate to project root
cd urbanflow

# Start everything
docker compose up --build

# Wait ~90s for bootstrap (OSM fetch + graph build + default scenario start)
# Then open:
open http://localhost:3000       # Frontend dashboard
open http://localhost:8000/docs  # FastAPI Swagger UI
```

**Acceptance criteria checklist:**
- [ ] Map loads with Chennai road network colored by flood risk
- [ ] Storm cell animates; flooding spreads from low-elevation areas outward
- [ ] Timeline scrubber (bottom) updates map to any 0–180 min point
- [ ] Clicking two map points returns a safe route (green) vs naive route (gray dashed)
- [ ] Every visible control is functional (no static mocks)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          DATA LAYER                                  │
│  SimulatedProvider (active)          LiveProvider (stub, documented) │
│  ├─ OSM Overpass API (real roads)    ├─ IMD Doppler Radar BUFR/FTP  │
│  ├─ Open-Elevation API (real DEM)    ├─ Copernicus GLO-30 DEM (S3)  │
│  └─ Gaussian storm cell (synthetic)  └─ Municipal GIS shapefiles    │
└────────────────────────┬────────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────────┐
│                   SIMULATION ENGINE                                  │
│  StormCell (Gaussian + advection, Z-R Marshall-Palmer)               │
│    → NowcastEngine (0–180 min forecast, 15-min steps)                │
│    → RunoffCalculator (Rational Method: Q = C·i·A, D8 routing)       │
│    → DrainageModel (NetworkX graph, clogging index CI, surcharge)    │
│    → FloodPredictor (depth → risk bands: dry/nuisance/disruptive/severe) │
│  SimulationEngine (asyncio clock, Redis pub/sub, observer pattern)   │
└────────────────────────┬────────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────────┐
│                     BACKEND API (FastAPI)                            │
│  POST /api/scenario/run      — start/switch storm scenario           │
│  GET  /api/flood-state?t=N   — flood state at simulation minute N    │
│  WS   /ws/flood-stream       — live push every 5 sim-minutes         │
│  POST /api/route/safe        — Dijkstra with flood-risk penalties    │
│  GET  /api/network/graph     — full GeoJSON FeatureCollection        │
│  GET  /docs                  — Swagger UI (all endpoints documented) │
└────────────────────────┬────────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────────┐
│               FRONTEND (Next.js + MapLibre GL JS)                    │
│  /             — Dashboard (map + timeline + scenario + incident feed)│
│  /route-planner — click-to-route flow                                │
│  /analytics     — Recharts: rainfall, risk distribution, depth trend  │
└─────────────────────────────────────────────────────────────────────┘
       ▲                    ▲
  PostgreSQL+PostGIS      Redis
  (graph, run history)   (pub/sub, tick state)
```

---

## Simulation Science

### Rainfall Nowcasting
- **Method**: Simple Lagrangian advection — storm cell moves at constant velocity vector
- **Z-R Relation**: Marshall-Palmer `Z = 200·R^1.6` (implemented in `storm.py`)
- **Forecast horizon**: 0–180 min at 15-min steps
- **pySTEPS upgrade path**: Replace `StormCell.rainfall_at()` with `pysteps.nowcasts.extrapolation.forecast(R, V, timesteps)` on real IMD radar composites

### Surface Runoff
- **Method**: Rational Method `Q = C·i·A`
  - `C` = runoff coefficient from OSM road class (0.85–0.95 for urban)
  - `i` = rainfall intensity (mm/hr → m/s)
  - `A` = contributing catchment area (m²) from Voronoi tessellation
- **D8 routing**: Water flows entirely to lowest-elevation neighbour

### Drainage Model
- **Graph**: NetworkX undirected graph (nodes = intersections/manholes, edges = pipes)
- **Clogging Index**: `CI = min(1, 0.30·RC + 0.40·(CR/100) + 0.30·GS)` where:
  - `RC` = road class factor (local roads clog more easily)
  - `CR` = cumulative rainfall mm
  - `GS` = per-node seeded grime factor
- **Surcharge**: When `water_volume > effective_capacity`, overflow = street flood depth

### Risk Classification
| Band | Depth | Color | Description |
|---|---|---|---|
| Dry | < 5 cm | Gray | Normal conditions |
| Nuisance | 5–15 cm | Amber | Pedestrian risk |
| Disruptive | 15–30 cm | Orange | Vehicle disruption |
| Severe | > 30 cm | Red | Life safety risk |

### Safe Routing
- **Algorithm**: Dijkstra with penalised edge weights
- **Penalty multipliers**: dry=1×, nuisance=2×, disruptive=10×, severe=1000×
- **Returns**: Safe path (green) + naive shortest path (gray dashed) + comparison stats

---

## API Reference

### Quick smoke tests
```bash
# Health check
curl http://localhost:8000/health

# Flood state at T+60 min
curl "http://localhost:8000/api/flood-state?t=60"

# Network GeoJSON
curl http://localhost:8000/api/network/graph | head -c 500

# Safe route (Chennai T. Nagar example)
curl -X POST http://localhost:8000/api/route/safe \
  -H "Content-Type: application/json" \
  -d '{"start": [13.07, 80.26], "end": [13.10, 80.28]}'

# Switch to moderate scenario
curl -X POST http://localhost:8000/api/scenario/run \
  -H "Content-Type: application/json" \
  -d '{"scenario": "moderate_steady"}'
```

### WebSocket
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/flood-stream');
ws.onmessage = (e) => {
  const state = JSON.parse(e.data);
  console.log(`T+${state.t_minutes}min: ${state.summary.severe_count} severe nodes`);
};
```

---

## Project Structure

```
urbanflow/
├── backend/
│   ├── app/
│   │   ├── config.py                  # All settings & constants
│   │   ├── main.py                    # FastAPI app entry point
│   │   ├── data/
│   │   │   ├── provider.py            # DataProvider ABC
│   │   │   ├── simulated_provider.py  # OSM + synthetic storm (active)
│   │   │   └── live_provider.py       # Documented stub (production)
│   │   ├── simulation/
│   │   │   ├── storm.py               # Gaussian storm + Z-R + scenarios
│   │   │   ├── nowcast.py             # 0–180 min advection nowcast
│   │   │   ├── runoff.py              # Q=CiA + D8 routing
│   │   │   ├── drainage.py            # NetworkX model + clogging index
│   │   │   ├── flood_predictor.py     # Risk bands + FloodState
│   │   │   └── simulation_engine.py   # Async clock + Redis pub/sub
│   │   ├── routing/
│   │   │   └── safe_router.py         # Dijkstra + flood penalties
│   │   ├── api/                       # FastAPI routers
│   │   ├── db/                        # SQLAlchemy models + PostGIS
│   │   └── startup/bootstrap.py       # OSM fetch + graph init
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   └── src/
│       ├── app/                       # Next.js pages
│       ├── components/map/            # FloodMap (MapLibre GL JS)
│       ├── components/panels/         # Scenario, NodeDetail, IncidentFeed, Route
│       ├── components/timeline/       # TimelineScrubber + sparkline
│       ├── hooks/                     # useFloodStream, useSimulation, useMapInteraction
│       ├── lib/                       # api.ts, mapStyles.ts
│       └── types/flood.ts             # TypeScript types
├── docker-compose.yml
├── docs/data-sources.md               # Production vs demo data contract
└── README.md
```

---

## Technology Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI (Python 3.12) + uvicorn |
| Simulation | NetworkX, NumPy, SciPy |
| Database | PostgreSQL 15 + PostGIS 3.3 |
| Cache/PubSub | Redis 7 |
| Frontend | Next.js 14 + TypeScript |
| Map | MapLibre GL JS (CartoDB Dark Matter tiles — no API key) |
| Charts | Recharts |
| UI | Tailwind CSS + Radix UI + Lucide icons |
| Container | Docker Compose (4 services) |

---

## Data Sources

See [`docs/data-sources.md`](docs/data-sources.md) for the full production data contract
vs demo data layer breakdown (required for honest judging).

---

## Team Nexora | SIH 2026 | PS ID 26085 | Theme: Disaster Management
