# Village Pond Planning System

AI-assisted web application to help village administrators identify suitable
locations for pond construction using terrain, catchment, and rainfall analysis.

## Status
- [x] Phase 1 — High-Level Design (HLD)
- [x] Phase 2 — Contour catchment analysis API (`POST /analyzeContour`)
- [x] Phase 3 — Web front-end + map-region analysis with water volume (`POST /analyzeArea`)

## Architecture

```
Browser (React + Leaflet)
        |
        v
Backend API gateway (FastAPI)
   |                  |
   v                  v
OpenCV microservice   Analysis modules (terrain / rainfall / pond-sizing)
(own container)              |
   |                         v
   +----------------> PostgreSQL + PostGIS
                              |
                              v
                     External APIs (OpenZenith, Open-Meteo, satellite imagery)
```

See `/docs` for the full HLD document and diagrams.

## Repo structure
```
frontend/         React app: map, contour overlay, region-draw tool, charts
backend/          FastAPI gateway + terrain, rainfall, and pond-sizing modules
opencv-service/   Standalone OpenCV microservice (pond detection, land classification)
docs/             HLD, API docs, technical report, lab-copy scans
docker/           docker-compose.yml and per-service Dockerfiles
```

## Tech stack
- Frontend: React, Leaflet.js, Chart.js
- Backend: Python, FastAPI
- OpenCV service: Python, OpenCV, FastAPI (separate container)
- Database: PostgreSQL + PostGIS
- Elevation/weather API: OpenZenith (fallback: Open-Meteo Elevation)
- Rainfall API: Open-Meteo Historical Weather API / NASA POWER
- Satellite imagery: Esri World Imagery / Sentinel Hub

## How it works (Phase 3)

1. Open the web app and **draw a rectangle** over any area on the map.
2. The backend fetches an elevation model for that area from the **Open-Meteo
   elevation API** and runs the terrain/hydrology pipeline (depression filling →
   D8 flow direction → flow accumulation → TWI/TPI pond siting → catchment
   delineation → UTM geometry) — the same pipeline used for uploaded contour maps.
3. It pulls **historical rainfall** for the area from Open-Meteo and estimates,
   for each suggested pond: the **catchment area**, the **pond footprint**, and
   the **water volume** it can collect (annual runoff vs. basin capacity).
4. The suggested pond, its catchment, and the volume figures are **overlaid on
   the map**.

### Endpoints
- `POST /analyzeArea` — body `{ "bbox": [min_lon, min_lat, max_lon, max_lat], "grid_size"?, "num_candidates"?, "runoff_coefficient"? }`. Phase 3.
- `POST /analyzeContour` — upload a KML/KMZ contour map (`contour_map` field). Phase 2, unchanged.
- Swagger docs at `/docs`, health at `/health`.

## Getting started (local)

```bash
# 1. Backend deps
cd backend && pip install -r requirements.txt

# 2. Build the front-end and let the backend serve it (one URL)
cd .. && ./scripts/build.sh
cd backend && uvicorn main:app --host 0.0.0.0 --port 5228
# open http://localhost:5228/
```

For front-end development with hot-reload, run the API and Vite separately:

```bash
cd backend && uvicorn main:app --reload            # API on :8000
cd frontend && npm install && npm run dev           # app on :5173, proxies API to :8000
```

Run the tests:

```bash
cd backend && python -m pytest tests/ -v
```

## Note on the elevation API
The free Open-Meteo elevation tier is rate-limited (600 calls/minute, weighted by
how many coordinates you request). Each analysis is capped at ~500 elevation
samples so one run fits inside that budget; fetched grids and rainfall are cached
in memory, so re-analysing the same or an adjacent area is instant. Rainfall has
an offline fallback; if the elevation service is momentarily throttled, wait a
minute or select a smaller area.

## Author
Solo project — Rishi Kharya
