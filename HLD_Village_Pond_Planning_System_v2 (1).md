# High-Level Design (HLD)
## AI-based Village Pond Planning System

*Incorporates the sir's in-class clarifications: contour-based calculations, non-overlapping modules, OpenCV as a separate containerized service, and manual/auto region input.*

---

## 1. Problem Statement and Objectives

Selecting a good pond site in a village requires combining three things that are normally judged by eye: the shape of the land (contours), how much water a catchment can funnel toward a point, and how much rain actually falls there over time. Manual site selection is slow, inconsistent, and gives no quantitative basis for deciding pond depth or capacity.

This project builds a web application where an administrator selects (or the system auto-detects) a village region, and the system computes, from a contour map and rainfall history, the region's usable pond area, the required depth, and expected storage capacity — visualized on an interactive map.

### Objectives
- Take a contour map (elevation lines) of a village area as the primary spatial input.
- Let the user either draw a candidate pond region manually, or have the system suggest/detect regions automatically from satellite imagery (extra-credit path).
- Compute, from the contours: (a) the length of the relevant contour curve(s), (b) the area of the proposed pond region, (c) the catchment area draining into that region.
- Fetch historical rainfall/precipitation data for that location from a public API.
- Compute the required pond depth from catchment area and precipitation rate, and derive approximate storage capacity.
- Detect whether a pond already exists at/near the selected location, using satellite image processing (extra credit), with defined evaluation metrics for detection accuracy.
- Present location, catchment, rainfall stats, computed depth/capacity, and contour/area visualizations as a single overlay.
- Design goals emphasised in review: **each module has one clear, non-overlapping responsibility**, and the system favours **simplicity and efficiency** over unnecessary complexity.

---

## 2. Overall System Architecture (Block Diagram)

See the rendered block diagram above. In your lab copy, draw it as five stacked layers with the OpenCV box drawn with a **dashed border** to show it runs in its own container (separate from the other analysis modules, which run in-process inside the backend):

```
                [ Village admin — browser ]
                            |
                            v
              [ Frontend: React + Leaflet ]
    (map, contour overlay, region-draw tool, charts)
                            |
                            v
            [ Backend API gateway: FastAPI ]
         (routing, orchestration, validation)
                 |                      |
                 v                      v
   +-------------------------+  +---------------------------+
   | OpenCV microservice     |  | Analysis modules           |
   | (own Docker container)  |  | (in-process, backend)      |
   | - pond detection on     |  |  - Terrain: contour length, |
   |   satellite imagery     |  |    catchment delineation    |
   | - land-cover /          |  |  - Rainfall: historical      |
   |   suitability masking   |  |    query + runoff calc       |
   +-------------------------+  |  - Pond sizing: area, depth, |
                 |              |    storage capacity          |
                 |              +---------------------------+
                 v                          v
        +----------------+       +-----------------------+
        | Database:      |       | External APIs:          |
        | PostgreSQL     |       | Elevation (Open-Elevation/|
        | + PostGIS      |       | Open-Meteo/OpenTopography),|
        | (villages,     |       | Rainfall (Open-Meteo,     |
        | ponds, catch-  |       | NASA POWER), Satellite     |
        | ment, detection|       | imagery (Esri/Sentinel)    |
        | records)       |       +-----------------------+
        +----------------+
```

**Why OpenCV is its own container**: image processing (pond detection, land classification) is CPU/GPU-heavy and has a different dependency footprint (OpenCV, image libraries) than the rest of the API. Isolating it lets it scale, fail, or be redeployed independently without touching the core FastAPI backend — this is exactly the separation the "OpenCV as a service" note in the notes was pointing at, and it will also be reused by Assignment 2.

**Why the analysis modules are split three ways, not merged**: each has a single distinct responsibility (terrain geometry vs. rainfall statistics vs. sizing math), so a change to the runoff formula doesn't risk touching the contour-length code — this is the "no overlapping modules" principle from the notes.

---

## 3. Functional Requirements and Project Workflow

### Functional Requirements
| ID | Requirement |
|----|-------------|
| FR1 | Display satellite imagery for a selected village |
| FR2 | Visualize contour maps (elevation lines) for the selected area |
| FR3 | Let the user draw a candidate pond region manually, or auto-detect available/suitable land |
| FR4 | Estimate the length of the relevant contour curve(s) around the proposed region |
| FR5 | Estimate the area of the proposed pond region |
| FR6 | Estimate the catchment area contributing runoff to the selected region |
| FR7 | Query historical rainfall/precipitation data via a public API |
| FR8 | Compute required pond depth from catchment area and precipitation rate, and estimate storage capacity |
| FR9 | (Extra credit) Detect existing ponds in the region from satellite imagery, with evaluation metrics for detection quality |
| FR10 | Overlay all results: region, catchment, rainfall stats, runoff volume, pond dimensions, detected ponds, on the map |
| FR11 | Persist village/pond/catchment records in the database for reuse |

### Workflow
1. User selects a village → frontend loads satellite imagery and contour lines for that area (FR1, FR2).
2. User either draws a candidate region on the map, or requests auto-suggested candidate regions from land-suitability + pond-detection output (FR3, FR9).
3. Backend computes contour curve length and region area for the selected polygon (FR4, FR5) — geometry only, no external API needed.
4. Backend runs catchment delineation from the region's boundary using the elevation data (FR6).
5. Backend queries the rainfall API for the region's coordinates, pulling historical daily/annual precipitation (FR7).
6. Backend computes required depth and storage capacity from catchment area × precipitation rate (FR8).
7. If auto-detection was used, the OpenCV microservice separately reports which parts of the region already contain a pond, with a confidence/accuracy metric (FR9).
8. Backend merges all of the above into one JSON payload; frontend renders it as a combined map overlay + summary panel (FR10).
9. Analysis is saved to the database so it can be revisited without recomputation (FR11).

---

## 4. Proposed Technology Stack

- **Frontend**: React.js, Leaflet.js (map, contour rendering, polygon-draw tool via Leaflet.Draw), Chart.js (rainfall graphs)
- **Backend**: Python, FastAPI (API gateway + terrain/rainfall/sizing modules, auto-generates Swagger docs)
- **OpenCV microservice**: Python, OpenCV, FastAPI/Flask — packaged as its own Docker container, exposed as an internal REST service (e.g. `/detect-pond`, `/classify-land`)
- **Database**: PostgreSQL + PostGIS (spatial queries: polygon area/intersection, distance, storing village/pond/catchment geometry)
- **Geospatial libraries**: GDAL, Rasterio, Shapely (contour length/area via the Shoelace formula), NumPy, `pysheds`/`richdem` (flow accumulation for catchment delineation)
- **Elevation API**: **OpenZenith** (openzenith.org) — a free global geospatial API providing elevation, weather, and tide data for any point, no API key or signup required. This matches the "OpenZenith" name in the assignment brief directly. Open-Elevation or Open-Meteo's Elevation API are noted as fallbacks in case OpenZenith's uptime/rate limits turn out to be a problem during development (it appears to be a smaller/newer service, so worth a quick reliability check before committing to it fully).
- **Rainfall API**: Open-Meteo Historical Weather API (free, no API key, daily precipitation back to 1940) or NASA POWER (free, no key, global agroclimatology data)
- **Satellite imagery**: Esri World Imagery tiles (free basemap) or Sentinel Hub (free tier) for the OpenCV detection input
- **Deployment**: Docker Compose (frontend, backend, OpenCV service, database as separate containers), Nginx reverse proxy
- **Version control**: Git + GitHub

> **Note on "OpenZenith"**: it's a real free geospatial API (openzenith.org) offering elevation, weather, and tide lookups for any coordinate with no key or signup — worth a quick uptime/rate-limit check during development since it's a smaller service than the likes of Open-Meteo, but it's a valid primary choice and matches the assignment brief exactly.

---

## 5. API Design (Major Endpoints)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/village/{village_id}/imagery` | Satellite tile layer info / bounding box |
| GET | `/api/village/{village_id}/elevation` | DEM-derived contour lines as GeoJSON |
| POST | `/api/region/geometry` `{polygon}` | Returns contour curve length + area for a user-drawn region (FR4, FR5) |
| POST | `/api/catchment/delineate` `{polygon}` | Returns catchment boundary polygon for the region |
| GET | `/api/rainfall?lat=&lon=&years=` | Historical rainfall time series + annual stats |
| POST | `/api/pond/depth-capacity` `{catchment_area, precipitation_rate}` | Returns required depth + estimated storage capacity (FR8) |
| POST | `/api/opencv/detect-pond` `{image_tile}` | (OpenCV microservice) Returns detected pond polygons + confidence score |
| POST | `/api/opencv/classify-land` `{image_tile}` | (OpenCV microservice) Returns land-suitability mask |
| POST | `/api/analysis/full` `{village_id, region}` | Orchestrator: runs the full pipeline, returns one combined overlay JSON |
| GET | `/api/report/{analysis_id}` | Downloadable summary report |

---

## 6. Algorithms / Methodology

- **Contour curve length**: Represent the contour as an ordered list of (x, y) points; sum the Euclidean distance between consecutive points (polyline length). Straightforward, no external dependency.
- **Region (pond) area**: Apply the **Shoelace formula** to the drawn/detected polygon's vertices — exact for any simple polygon, and what Shapely's `.area` does internally.
- **Catchment delineation**: D8 flow-direction algorithm on the DEM around the region → flow accumulation → watershed boundary from the region's lowest edge as the pour point (`pysheds`/`richdem`).
- **Rainfall analysis**: Pull the historical daily precipitation series for the region's centroid; compute mean annual rainfall and variability.
- **Required depth / storage capacity**: Runoff volume ≈ catchment area × annual precipitation × a runoff coefficient (Rational Method, `Q = C·I·A`). Required depth is then chosen so the pond's volume (area × depth, assuming a simple trapezoidal cross-section) can hold that runoff volume, solved for depth given the fixed drawn/detected surface area.
- **Existing-pond detection (extra credit)**: Classical CV pipeline in the OpenCV service — e.g. water-index thresholding on the imagery (NDWI-style band ratio) + contour extraction, or a lightweight trained classifier if time permits. **Evaluation metric**: precision/recall (or IoU) of detected pond polygons against a small hand-labelled validation set, since the notes explicitly call out needing "evaluation metrics."
- **Land suitability masking**: rule-based filtering on slope range + land-cover class, independent of the pond-detection step (kept as a separate function so the two don't get coupled).

---

## 7. Expected Challenges and Proposed Solutions

| Challenge | Proposed Solution |
|-----------|-------------------|
| OpenZenith is a smaller/newer service — uptime or rate limits are unverified at scale | Test the live endpoint early; keep Open-Elevation or Open-Meteo Elevation as a documented fallback in case of downtime during the demo |
| DEM resolution from any free source may misrepresent small village-scale contours | Use the highest-resolution free dataset available for the region; clearly state resolution limits in the report rather than overclaiming precision |
| OpenCV pond detection accuracy on varied imagery | Keep the detection pipeline simple and rule-based first (water index + contour), report precision/recall on a small labelled set, and treat it explicitly as an "extra credit" capability rather than a load-bearing requirement |
| Running OpenCV as a separate container adds deployment complexity | Use Docker Compose locally so both containers start together with one command; document the internal service URL clearly in the installation guide |
| Manual region-drawing vs. auto-detected region may give inconsistent geometry | Route both paths through the same `/api/region/geometry` endpoint, so length/area calculations are identical regardless of how the region was produced |
| Rainfall data granularity doesn't match a single small catchment | Use the region centroid's coordinates for the rainfall query and state this simplification explicitly |
| Keeping modules from overlapping in responsibility | One module = one file/service with a single public function signature (e.g. terrain module only returns geometry, never touches rainfall data) — enforced by the API design above |

---

*Note: This is a design reference — rewrite it in your own words and hand-drawn diagrams in the lab copy so you can explain and justify each decision (especially the OpenZenith substitution and the module split) during the HLD review.*
