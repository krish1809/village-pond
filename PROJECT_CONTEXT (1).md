# Project Context: AI-based Village Pond Planning System

This file is the single source of truth for the project. Read this fully
before writing any code. If anything here conflicts with a later instruction
in chat, ask before assuming — don't silently pick one.

---

## 1. Course & assignment background

This is a system design course project, built phase-by-phase over a
semester, developed **solo**. Each phase has its own deadline and its own
graded deliverable (a working piece of the system + a short report). Earlier
phases are not thrown away — later phases build on top of them, so code
quality and extensibility matter as much as making the current phase's demo
work.

**LLM usage policy (course rule)**: AI tools are allowed for brainstorming,
debugging, refactoring, and documentation, but the student must be able to
explain and justify every part of the submitted code and every design
decision during review. Because of this: prefer clear, conventional
implementations over clever/opaque ones, and comment non-obvious logic
(especially the catchment/flow-accumulation math) so it can be explained
later without re-deriving it from scratch.

## 2. Overall project objective

Build a web application that helps village administrators identify suitable
pond construction sites, by analyzing terrain (contour/elevation data),
delineating catchment areas, pulling historical rainfall data, and
recommending pond depth/storage capacity — presented on an interactive map.

## 3. System architecture (from the approved HLD)

Layered / microservice architecture:

```
Browser (React + Leaflet)
        |
        v
Backend API gateway (FastAPI)
   |                              |
   v                              v
OpenCV microservice        Analysis modules (in-process)
(own Docker container)       - terrain: contour length, catchment delineation
- pond detection              - rainfall: historical query, runoff calc
- land-cover masking          - pond sizing: area, depth, storage capacity
   |                              |
   v                              v
                    PostgreSQL + PostGIS (villages, ponds,
                    catchment, detection records)
                              |
                              v
        External APIs: OpenZenith (elevation/weather/tides,
        openzenith.org, free, no key), Open-Meteo / NASA POWER
        (rainfall fallback/cross-check), Esri/Sentinel (imagery)
```

**Design principles from the HLD (enforce these in code, not just docs)**:
- **No overlapping modules** — each module has one clear responsibility.
  E.g. the module that parses/interprets terrain data must never contain
  rainfall logic, and vice versa. If you find yourself adding a rainfall
  concern inside a terrain file, stop and split it out.
- **Simplicity and efficiency** over cleverness. Prefer a well-documented,
  simple heuristic over an elaborate one that's hard to justify in review.
- **OpenCV runs in its own container**, separate from the rest of the
  backend, because it has a heavier/different dependency footprint and
  should be independently deployable. (Not relevant to the current phase's
  task, but don't add OpenCV code into the main backend service.)

## 4. Tech stack

- Frontend: React, Leaflet.js, Chart.js
- Backend: Python, FastAPI
- OpenCV service: Python, OpenCV, FastAPI — separate container (future phase)
- Database: PostgreSQL + PostGIS
- Elevation/weather API: **OpenZenith** (https://openzenith.org — free,
  no API key/signup, covers elevation, weather, tides). Fallback if
  unreliable: Open-Meteo Elevation API.
- Rainfall API: Open-Meteo Historical Weather API or NASA POWER (both free,
  no key required)
- Satellite imagery: Esri World Imagery / Sentinel Hub
- Deployment: Docker Compose, Nginx reverse proxy

## 5. Repo structure (already scaffolded)

```
frontend/         React app (not yet built)
backend/          FastAPI gateway + analysis modules  <-- current phase's work goes here
opencv-service/   Standalone OpenCV microservice (future phase, empty for now)
docs/             HLD, API docs, technical report, lab-copy scans
docker/           docker-compose.yml, per-service Dockerfiles
```

Within `backend/`, keep the module-per-responsibility structure described in
the phase task spec (parser, terrain grid, catchment, pond locator, geometry
utils, and a thin route file) — do not collapse this into one file.

## 6. Current phase: Phase 2 — Contour Map Catchment Analysis API

Full requirements, endpoint contract, JSON response schema, suggested
libraries, module breakdown, and test expectations are in the accompanying
file **`PHASE2_SPEC_contour_catchment.md`** — treat that as the authoritative
task spec for this phase. Read it in full before starting.

**Non-negotiable constraint repeated here because it's the #1 grading
criterion**: nothing in the response may be hard-coded from the sample map.
All coordinates, elevations, areas, and boundaries must be computed from
whatever KML/KMZ file is uploaded, so the same code works on a different
contour map next phase without modification.

## 7. Deployment requirement (Phase 2 specific)

Phase 2 requires a **working, publicly reachable API URL** that a TA can hit
directly — not just something running on localhost. Plan: `Render.com` or
`Fly.io` free tier, deployed straight from a Dockerfile in `backend/`.

This has a direct consequence for library choices: the free tier has to be
able to build the container within its resource limits. Before locking in a
geospatial library, weigh this:
- `shapely`, `numpy`, `scipy`, `fastkml`/`pykml`, `pyproj` — lightweight,
  pip-installable, safe for a free-tier build.
- `richdem` and `GDAL`-based packages — powerful but can have heavy native
  build dependencies that are slow or fail to build on constrained free
  hosts. If used, confirm the Docker build actually succeeds on the target
  host before relying on it; otherwise prefer `pysheds` (pure Python +
  numpy, generally lighter) or a hand-rolled D8 flow-accumulation routine.

Only the `backend` service needs to be deployed for Phase 2 — the database
(PostgreSQL/PostGIS) and OpenCV microservice are not required for this
phase's grading and can stay undeployed until a later phase needs them. Keep
the Phase 2 route self-contained (no DB dependency) so it can run and be
tested without provisioning Postgres.

Deployment steps to follow once the route works locally:
1. Add a standalone `backend/Dockerfile` (installs `backend/requirements.txt`,
   runs `uvicorn` bound to `0.0.0.0:$PORT` since the host injects `PORT`).
2. Push to GitHub; connect Render or Fly to the repo with root directory
   `backend/`.
3. Deploy, then test the live URL from outside the dev machine (curl/Postman)
   with the sample KML/KMZ before considering the phase done.
4. Note free-tier cold starts (~20–50s after inactivity) so it doesn't look
   broken during a check.
5. Record the base URL, the full route URL, and the `/docs` Swagger link for
   the report.

## 8. What to do first

1. Read this file and `PHASE2_SPEC_contour_catchment.md` in full.
2. Inspect the provided sample contour KML/KMZ file to confirm how elevation
   is actually encoded in it (Z-coordinate, `<name>`, or `<ExtendedData>`) —
   don't assume; check the real file.
3. Propose the module file layout inside `backend/` before writing code, so
   it can be reviewed against the "no overlapping modules" principle. Include
   in that proposal which geospatial libraries you plan to use, with the
   free-tier deployment constraint from section 7 in mind — flag it upfront
   if a chosen library (e.g. `richdem`/GDAL) is a deployment risk, rather
   than discovering a failed Docker build after the code is written.
4. Implement module by module (parser → grid → catchment → pond locator →
   route), with a quick test/print-check after each one against the sample
   file, rather than writing everything then debugging at the end.
5. Wire up the `/analyzeContour` route last, once the underlying modules are
   verified independently.
6. Add the standalone `backend/Dockerfile` and confirm it builds locally
   (`docker build`) before assuming it'll build on Render/Fly.
7. Once deployed, verify the live URL responds correctly to the sample file
   from outside the dev machine — this is the actual Phase 2 deliverable.
