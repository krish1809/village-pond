# Phase 2 — Contour Map Catchment Analysis API

## Objective
Implement a backend route that accepts a contour map (KML/KMZ), analyzes the
terrain it describes, identifies a suitable pond location, estimates the
catchment area draining into it, and returns the result as structured JSON.

**Hard constraint**: nothing about the sample map (coordinates, elevations,
place names, region size) may be hard-coded anywhere in the logic. Every
number in the response must be derived from parsing and processing the
uploaded file. The code must work on a different KML/KMZ of the same general
shape (contour lines tagged with elevation) without modification.

## Endpoint contract

```
POST /analyzeContour
Content-Type: multipart/form-data
Body: file=<contour.kml | contour.kmz>
```

Response `200 OK`:
```json
{
  "pond_location": {
    "latitude": 0.0,
    "longitude": 0.0,
    "elevation_m": 0.0
  },
  "catchment": {
    "area_sq_m": 0.0,
    "perimeter_m": 0.0,
    "boundary": { "type": "Polygon", "coordinates": [[[0,0],[0,0]]] }
  },
  "contour_summary": {
    "num_contour_lines": 0,
    "elevation_min_m": 0.0,
    "elevation_max_m": 0.0,
    "estimated_contour_interval_m": 0.0
  },
  "metadata": {
    "source_filename": "string",
    "processing_notes": ["string"]
  }
}
```

Error cases: invalid/unparseable file → `422` with a clear message; file with
no elevation data in contours → `422` explaining the requirement.

## Processing pipeline (suggested module split — keep these separate files,
not one big function, per the HLD's "no overlapping modules" principle)

1. **`kml_parser.py`** — Accept KML or KMZ (KMZ = zipped KML + assets; unzip
   first). Parse with `fastkml` or `pykml`, or fall back to raw `lxml`/
   `xml.etree.ElementTree` if the file uses non-standard extensions. Extract
   every contour feature as a list of (lat, lon, elevation) vertices —
   elevation may be in the coordinate's Z value, in `<name>`, or in
   `<ExtendedData>`, so support at least two of these sources defensively.

2. **`terrain_grid.py`** — Build a regular elevation grid from the scattered
   contour vertices via interpolation (`scipy.interpolate.griddata`, linear
   or cubic). This grid is what flow direction/accumulation will run on.

3. **`catchment.py`** — Compute D8 flow direction and flow accumulation on
   the grid (`richdem` or `pysheds`, or a hand-rolled D8 implementation if
   those aren't available in the environment). From flow accumulation,
   delineate the watershed feeding a given pour point.

4. **`pond_locator.py`** — Pick a candidate pond location/pour point from the
   grid: look for a local low point (small depression or flat area) that
   also has meaningful upstream flow accumulation, and isn't right at the
   grid boundary. Keep this heuristic simple and documented — it's fine for
   it to be a first-pass rule (e.g. lowest-elevation cell among the top-N
   flow-accumulation cells), since a smarter version is future-phase work.

5. **`geometry_utils.py`** — Shared helpers: contour polyline length,
   catchment polygon area/perimeter (Shapely, e.g. via UTM-projected
   coordinates for accurate metric area — don't compute area in raw
   lat/lon degrees).

6. **`api/routes/analyze_contour.py`** — The actual FastAPI route. Thin: file
   upload handling, calls into the modules above in order, assembles the
   JSON response, and error handling. No terrain logic should live here.

## Suggested libraries
`fastapi`, `python-multipart` (file upload), `fastkml` or `pykml` (KML
parsing), `lxml`, `numpy`, `scipy` (interpolation), `shapely` + `pyproj`
(geometry, projection for accurate area), `richdem` or `pysheds` (flow
accumulation/watershed) — if neither installs cleanly in the environment,
implement a minimal D8 flow-accumulation routine by hand rather than
skipping the step.

**Deployment constraint on library choice**: this route must run on a free
hosting tier (Render/Fly) reachable by a public URL for grading — see
`PROJECT_CONTEXT.md` section 7. Prefer pure-Python/pip-installable libraries
(`shapely`, `scipy`, `numpy`, `pysheds`) over ones with heavy native build
requirements (`richdem`, raw `GDAL` bindings), since those can fail or time
out building in a constrained free-tier container. If a heavier library is
used anyway, confirm `docker build` succeeds locally before assuming it'll
deploy — don't find out at submission time.

## Deliverable for this phase
Alongside the code: a standalone `backend/Dockerfile` that builds and runs
this service on its own (no dependency on the database or OpenCV service),
and a working public URL for the deployed route, since that's what will
actually be checked.

## Testing / demonstration
- Include a test or notebook that runs the provided sample KML/KMZ through
  the full pipeline and prints the JSON response.
- Include at least one unit test per module (parser returns non-empty vertex
  list; grid interpolation produces expected shape; catchment area is > 0
  and less than the total grid area) so extensibility to new maps in the
  next phase can be verified without eyeballing output.

## API documentation
FastAPI gives you Swagger (`/docs`) for free — make sure the route has a
docstring, a Pydantic response model (don't return a raw dict), and example
values so the auto-generated docs are actually useful for the report.

## Out of scope for this phase (don't build yet)
- OpenCV pond-detection microservice integration
- Rainfall API integration / runoff volume calculation
- Frontend map rendering
These come in later phases per the HLD — keep this route's dependencies
minimal and self-contained so it doesn't get entangled with them.
