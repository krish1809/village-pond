# Village Pond Planning System

AI-assisted web application to help village administrators identify suitable
locations for pond construction using terrain, catchment, and rainfall analysis.

## Status
- [x] Phase 1 — High-Level Design (HLD)
- [ ] Phase 2 — Prototype
- [ ] Phase 3 — Final submission

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

## Getting started

```bash
git clone <your-repo-url>
cd village-pond-planning-system
docker compose -f docker/docker-compose.yml up --build
```

Frontend: http://localhost:5173
Backend API docs (Swagger): http://localhost:8000/docs
OpenCV service: http://localhost:8001/docs

## Author
Solo project — [your name]
