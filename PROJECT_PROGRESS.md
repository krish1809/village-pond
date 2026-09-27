# Village Pond Planning System — Project Progress

> **Purpose**: This file is the living record of what's been built, what's working,
> and what's left. Any agent or collaborator should read this FIRST before touching code.

---

## Current Phase: Phase 3 — Web front-end, map-region analysis, water volume

### Status: 🔨 IN PROGRESS

Phase 3 is **additive** — Phase 2's `/analyzeContour` (upload a contour file) is
untouched. Phase 3 adds:

- **`POST /analyzeArea`** — the user selects a region on a map; the backend fetches
  a DEM for that bbox from the **Open-Meteo elevation API**, runs the same Phase 2
  hydrology pipeline, then adds an **expected water volume** estimate from live
  **Open-Meteo historical rainfall** (with an offline fallback).
- **React + Leaflet front-end** (`frontend/`) — satellite map, draw-a-rectangle
  area selection, and pond/catchment/volume results overlaid on the map. Built to
  `frontend/dist` and served as static files by the same FastAPI process, so the
  whole system is one URL (`scripts/build.sh`).

New backend modules: `elevation_api.py` (DEM from Open-Meteo, batched + cached +
rate-limit-resilient), `rainfall_api.py` (mean annual rainfall + fallback),
`water_volume.py` (runoff vs. basin-capacity → collectable volume). New route:
`api/routes/analyze_area.py`. Reuses `catchment.py`, `pond_locator.py`,
`geometry_utils.py` unchanged.

Water volume model:
- Annual runoff delivered by catchment: `V = C · P · A_catchment` (Rational method).
- Basin storage capacity: `Σ (water_level − cell_elev) · cell_area` over the pond
  flood-fill footprint (true basin volume from the DEM, not flat area×depth).
- Expected collectable = `min(runoff, capacity)`.

---

## Architecture Overview

```
backend/
├── main.py                          # FastAPI app (title, CORS, health check, router)
├── requirements.txt                 # Pure-pip dependencies (no GDAL/richdem)
├── Dockerfile                       # Standalone, free-tier deployable
├── modules/
│   ├── kml_parser.py                # KML/KMZ → ContourLine objects
│   ├── terrain_grid.py              # Scattered contour vertices → regular DEM grid (scipy griddata)
│   ├── catchment.py                 # Priority-Flood sink fill + D8 flow direction + flow accumulation + watershed
│   ├── pond_locator.py              # Multi-criteria scoring: TWI + TPI + SPI + curvature
│   └── geometry_utils.py            # UTM-projected polygon area/perimeter, polyline length
├── api/routes/
│   └── analyze_contour.py           # POST /analyzeContour — thin orchestration handler
├── models/
│   └── schemas.py                   # Pydantic response/request models
└── tests/
    ├── test_*.py                    # Unit tests per module
    └── demo_full_pipeline.py        # End-to-end demo with sample KML
```

## Key Design Decisions

1. **Hand-rolled D8 + Priority-Flood**: No `richdem`/`pysheds` — avoids native build deps that break on free-tier hosting. Fully explainable in review.
2. **Multi-criteria pond siting**: Uses TWI (Topographic Wetness Index), TPI (Topographic Position Index), SPI (Stream Power Index), and plan/profile curvature instead of naive "lowest point" heuristic. Based on GIS hydrology literature.
3. **Elevation from `<name>` tags**: The sample KML encodes elevation in `<name>` (e.g., `<name>277.0</name>`), with fallbacks for Z-coordinates and ExtendedData.
4. **UTM projection for area/distance**: All metric calculations use auto-detected UTM zone via pyproj, not raw lat/lon degrees.
5. **No hard-coded values**: Everything derived from the uploaded file.

## Sample Data Summary (contours_1m.kml)
- **Size**: 6.5 MB, ~49K lines, 2,712 placemarks (1,355 LineStrings)
- **Elevation**: 267–298 m (1m interval, 32 levels)
- **Location**: ~81.28–81.31°E, 21.24–21.26°N (Chhattisgarh, India)
- **Coordinate format**: `lon,lat` pairs in `<coordinates>`, no Z-values

## Dependencies (requirements.txt)
```
fastapi, uvicorn[standard], python-multipart, lxml, numpy, scipy, shapely, pyproj, pytest
```

## How to Run
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload                    # Dev server on :8000
curl -X POST http://localhost:8000/analyzeContour -F "contour_map=@../contours_1m.kml"
python -m pytest tests/ -v                   # Unit tests
python tests/demo_full_pipeline.py ../contours_1m.kml  # Full demo
```

## Live Public Backend API
- **Base URL**: `https://insights-holders-rick-show.trycloudflare.com`
- **POST Route**: `https://insights-holders-rick-show.trycloudflare.com/analyzeContour`
- **Swagger Docs**: `https://insights-holders-rick-show.trycloudflare.com/docs`

## Phase 2 Status: COMPLETED ✅ (43/43 Tests Passing, 0.30s Response Time)

### Module Completion Checklist
- [x] **Pydantic Schemas** (`backend/models/schemas.py`)
- [x] **Streaming KML/KMZ Parser** (`backend/modules/kml_parser.py`)
- [x] **Terrain Grid Interpolation** (`backend/modules/terrain_grid.py`)
- [x] **Hydrological Catchment Delineation** (`backend/modules/catchment.py`)
- [x] **Multi-Criteria Pond Locator** (`backend/modules/pond_locator.py`)
- [x] **Metric Geometry Utilities** (`backend/modules/geometry_utils.py`)
- [x] **FastAPI Route Orchestrator** (`backend/api/routes/analyze_contour.py`)
- [x] **Unit & Integration Test Suite** (`backend/tests/`)
- [x] **Main Application Entry** (`backend/main.py`)
- [x] **Containerization** (`backend/Dockerfile`)
- [x] **Deployment** (Cloudflare Tunnel)

## Novelty / Research-Backed Techniques
- **Priority-Flood** (Barnes et al., 2014) for sink filling — O(n log n), optimal
- **TWI** = ln(As / tan β) — Topographic Wetness Index (Beven & Kirkby, 1979)
- **TPI** = z₀ - mean(z_neighborhood) — Topographic Position Index (Guisan et al., 1999)
- **SPI** = ln(As × tan β) — Stream Power Index (Moore et al., 1991)
- **Plan/Profile Curvature** — second derivatives of DEM for flow convergence
- **Multi-criteria suitability score** combining all indices via weighted sum

---
*Last updated: 2026-08-29*
