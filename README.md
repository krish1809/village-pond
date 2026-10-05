# Village Pond Planning System

AI-assisted web application to help village administrators identify suitable
locations for pond construction using terrain, catchment, and rainfall analysis.

## Links
- **Demo video:** https://youtu.be/RUvhIV-HOOs
- **Live app:** http://10.1.75.79:5228/
- **API docs:** http://10.1.75.79:5228/docs
- **Final report:** [docs/final_report.pdf](docs/final_report.pdf)

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

1. Open the web app (plain map, with a satellite toggle) and **select a block**
   over any area — either "Use current map view" or draw a rectangle.
2. The backend fetches a **real DEM for exactly that block from OpenTopography**
   (SRTMGL1, 30 m) and runs the terrain/hydrology pipeline (depression filling →
   D8 flow direction → flow accumulation → TWI/TPI pond siting → **river/channel
   exclusion** → catchment delineation → UTM geometry) — the same pipeline used
   for uploaded contour maps, so suggested ponds stay out of the drainage network.
3. It pulls **historical rainfall** for the area from Open-Meteo and estimates,
   for each suggested pond: the **catchment area**, the **pond footprint**, and
   the **water volume** it can collect (annual runoff vs. basin capacity).
4. Contour lines generated from the DEM, the suggested pond, its catchment, and
   the volume figures are all **overlaid on the map**.

### Endpoints
- `POST /analyzeArea` — body `{ "bbox": [min_lon, min_lat, max_lon, max_lat], "num_candidates"?, "runoff_coefficient"? }`. Phase 3. Needs `OPENTOPOGRAPHY_API_KEY` set in the environment.
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

## Elevation data (OpenTopography)
The DEM for the selected block comes from the **OpenTopography Global DEM API**
(SRTMGL1, 30 m). One request returns the whole raster for the block (requested as
an ESRI ASCII grid, so no GDAL/rasterio is needed), which is parsed into the DEM
the pipeline runs on. It needs a **free API key** — register at
https://portal.opentopography.org/ and set it in the environment:

```bash
export OPENTOPOGRAPHY_API_KEY=your_key_here   # or put it in a .env file (gitignored)
```

On the lab systems the key lives in `village-pond/.env`, which `scripts/deploy_on_system.sh`
loads automatically. Rainfall comes from Open-Meteo's historical archive with an
offline fallback, so volume figures are always produced. Fetched DEMs and rainfall
are cached in memory, so re-analysing the same block is instant.

## Author
Solo project — Rishi Kharya
