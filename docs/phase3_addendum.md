# Village Pond Planning System — Phase 3 Technical Addendum

Phase 3 builds a web front-end on top of the Phase 2 analysis engine and adds two
things the brief asks for: **selecting a land area on a map** and reporting the
**expected water volume** a pond there could collect. It is deliberately additive
— the Phase 2 `POST /analyzeContour` route (upload a contour file) is unchanged,
and the terrain/hydrology modules (`catchment.py`, `pond_locator.py`,
`geometry_utils.py`) are reused as-is.

## 1. What changed at a glance

| Concern | Phase 2 | Phase 3 |
|---|---|---|
| Terrain input | Uploaded KML/KMZ contour file | A bounding box drawn on a map |
| Elevation source | Interpolated from contour lines | Fetched from the Open-Meteo elevation API |
| Rainfall | — | Open-Meteo historical archive (with offline fallback) |
| Output | Pond sites + catchment + footprint | …plus **expected water volume** per site |
| Interface | Swagger / curl | React + Leaflet web app, results overlaid on the map |

## 2. The new request flow (`POST /analyzeArea`)

```
Browser draws a rectangle → bbox
        │
        ▼
elevation_api.fetch_dem_grid(bbox)      ── Open-Meteo /v1/elevation (batched, cached)
        │  (a GridResult, identical in shape to the contour-derived one)
        ▼
catchment.compute_flow(dem)             ← reused from Phase 2
pond_locator.find_candidates(...)       ← reused from Phase 2
geometry_utils.catchment_polygon/…      ← reused from Phase 2
        │
        ├── rainfall_api.annual_rainfall(centre)   ── Open-Meteo archive-api (cached, fallback)
        │
        ▼
water_volume.compute(...)               → runoff, capacity, collectable
        │
        ▼
JSON: candidates[] (location, footprint, catchment, suitability, water_volume)
      + rainfall + area_summary + metadata
```

Because `elevation_api` returns the **same `GridResult`** dataclass that
`terrain_grid.build_grid` produces, the entire Phase 2 pipeline runs downstream
without a single change — the DEM's origin (contour file vs. API) is invisible to it.

## 3. Water volume model (`water_volume.py`)

Two independent limits are computed and the smaller one is reported as the
collectable volume:

1. **Annual runoff delivered by the catchment** (Rational method):
   `V_runoff = C · P · A_catchment` (m³/yr), where `P` is mean annual rainfall
   (m/yr) and `C` is a runoff coefficient (default 0.3, overridable — it depends
   on soil and land cover). This is how much water *arrives*.
2. **Basin storage capacity** from the DEM, over the pond's flood-fill footprint:
   `V_capacity = Σ_cells (water_level − cell_elevation) · cell_area` (m³). This is
   how much the basin can physically *hold*, and it's taken straight from the
   terrain rather than approximated as area × depth, so it accounts for the basin
   being shallower near its edges.

`V_collectable = min(V_runoff, V_capacity)`, and the response says which limit
binds, so the trade-off is explicit rather than hidden in one number.

## 4. Rainfall (`rainfall_api.py`)

Mean annual rainfall is averaged over the last ~10 full years of Open-Meteo
historical daily precipitation for the area centre, which smooths out wet/dry-year
swings. Every call is wrapped with a timeout and try/except; if the service can't
be reached the module returns a documented fallback value and flags the source as
`"fallback"`, so the analysis never hard-fails offline. A monthly climatology is
returned for the small rainfall chart in the UI.

## 5. Working within a free, rate-limited elevation service

The Open-Meteo elevation endpoint is free but limited to 600 weighted calls per
minute, and a 100-coordinate request is weighted roughly per coordinate. The
design keeps a single analysis inside that budget by separating two grids:

- **Sampling grid (≤500 points)** — what we actually query. One run stays under the
  minute limit. At village scale this is near the DEM's own 90 m resolution, so
  little real detail is lost.
- **Analysis grid (finer)** — the fetched samples are interpolated (linear, then
  nearest-fill — the same scheme `terrain_grid` uses between contour vertices) onto
  a finer grid (~70 cells on the long axis) that the hydrology runs on. This keeps
  flow routing, catchment delineation, and the pond footprint from being distorted
  by a blocky ~20×20 raster, without adding real detail beyond the source data or
  making a single extra API call.
- **Batching + bounded concurrency** — coordinates are sent in ≤100-point batches,
  a couple of requests at a time, with retry-and-backoff on transient 429/5xx.
- **In-memory caching** — fetched DEM grids (by bbox) and rainfall (by centre) are
  cached, so re-analysing the same or an adjusted area is instant and free.
- **Graceful degradation** — if the service is momentarily throttled, the API
  returns a clear message telling the user to wait a minute or pick a smaller area.

## 6. Front-end (`frontend/`, React + Leaflet)

- Esri satellite / OpenStreetMap basemaps, opening over the sample area but usable
  anywhere.
- A `leaflet-draw` rectangle tool captures the bbox.
- Results are drawn with `L.geoJSON`: the pond footprint as a filled polygon, the
  catchment as a dashed outline, and the pond location as a marker — colour-coded
  per rank to match the backend's rendered PNG. A side panel lists catchment area,
  pond footprint, runoff, capacity, and the headline collectable volume, plus the
  monthly rainfall chart.
- The compiled app is served as static files by the same FastAPI process
  (`backend/static/`, produced by `scripts/build.sh`), so the whole system runs as
  one process behind one URL — simple to keep alive on the single provided server.

## 7. Scaling and system-limits considerations

The brief asks for the solution to be "fast and functional, with appropriate
consideration for stress, scaling, and system limitations." Concretely:

- One process serves both the API and the web app — minimal footprint on the
  provided machine.
- The elevation point cap bounds both external-API load and compute time; a single
  analysis completes in a couple of seconds and is dominated by network, not CPU.
- Caching removes repeat external calls entirely for revisited areas.
- Oversized/degenerate area selections are rejected up front with a clear message,
  rather than being allowed to fan out into hundreds of requests.
