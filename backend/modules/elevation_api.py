"""
Elevation API — Fetch a DEM for an arbitrary map region from the Open-Meteo
Elevation API and hand it to the rest of the pipeline as a GridResult.

Responsibility: turning a bounding box into an elevation grid ONLY. No flow
routing, no pond scoring, no volume maths — those stay in their own modules and
consume the GridResult this produces, exactly the same GridResult that
terrain_grid.build_grid produces from a contour file. That's the whole point:
Phase 2's hydrology pipeline doesn't care whether the DEM came from a contour
KML or from an elevation API, so both feed the same downstream code.

Open-Meteo's elevation endpoint (https://api.open-meteo.com/v1/elevation) is
free, needs no API key, returns 90 m Copernicus DEM values, and accepts up to
100 coordinates per request. We build a regular grid over the bbox, query the
elevations in batches (concurrently, but politely rate-limited), and reshape the
results back into a DEM.

Scaling / robustness notes (this endpoint is a shared free service and the
region is user-chosen, so both matter):
  - The bbox is validated and capped — an oversized area is rejected with a
    clear message rather than firing hundreds of requests.
  - Total sample points are capped, so the number of API calls is bounded
    regardless of how the grid_size is set.
  - Requests are batched (<=100 coords) and run with bounded concurrency.
  - Results are cached in-memory by rounded bbox, so re-analysing the same or a
    just-adjusted area is instant.
"""

import asyncio
from typing import Dict, List, Tuple

import httpx
import numpy as np
from scipy.interpolate import griddata
from scipy.ndimage import uniform_filter

from modules.terrain_grid import GridResult, GridMeta, compute_slope

ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"

# Open-Meteo accepts at most 100 coordinate pairs per request.
MAX_COORDS_PER_REQUEST = 100

# How many elevation requests to have in flight at once. Deliberately small: the
# API is a free shared service that rate-limits bursts (HTTP 429), so a couple of
# parallel requests keeps the total wait short without tripping the limiter.
MAX_CONCURRENT_REQUESTS = 2

REQUEST_TIMEOUT_S = 20.0

# Retry a batch a few times on rate-limit / transient errors, backing off each
# time, before giving up. This is what makes bursts against the free tier robust.
MAX_RETRIES = 4
RETRY_BACKOFF_S = 0.75

# Two grids, decoupled on purpose:
#
#  * SAMPLING grid — how many elevation points we actually fetch from the API.
#    Capped by Open-Meteo's free-tier rate limit (600 "calls"/min, weighted ≈ one
#    per coordinate), so one analysis must stay well under 600 total coordinates
#    or it gets a 429. 500 keeps a whole analysis inside a single minute's budget
#    with headroom for the rainfall call.
#
#  * ANALYSIS grid — the resolution the hydrology actually runs at. We interpolate
#    the fetched samples onto this finer grid (linear, like terrain_grid does
#    between sparse contour vertices) so flow routing, catchment delineation, and
#    the pond footprint behave like they do on a proper DEM instead of a blocky
#    ~20×20 raster. This adds no real detail beyond the 90 m source data — it just
#    stops the coarse sampling grid from distorting the analysis.
MAX_SAMPLE_POINTS = 500
MAX_ANALYSIS_CELLS = 8000

# Reject bounding boxes wider/taller than this (degrees ≈ 66 km). Beyond a
# village/small-catchment scale the 90 m DEM is too coarse to be meaningful and
# the point count explodes, so we refuse rather than return something misleading.
MAX_BBOX_SPAN_DEG = 0.6

# Refuse a degenerate/too-tiny box as well — below this there isn't enough
# terrain to delineate anything sensible.
MIN_BBOX_SPAN_DEG = 0.002

# Cache fetched grids by rounded bbox + grid_size.
_CACHE: Dict[tuple, GridResult] = {}


def _validate_bbox(bbox: Tuple[float, float, float, float]) -> None:
    """Raise ValueError (→ 422 upstream) if the bbox is unusable."""
    lon_min, lat_min, lon_max, lat_max = bbox

    if not (lon_min < lon_max and lat_min < lat_max):
        raise ValueError(
            "Invalid bounding box: expected [min_lon, min_lat, max_lon, max_lat] "
            "with min < max on each axis."
        )
    if not (-180 <= lon_min <= 180 and -180 <= lon_max <= 180 and -90 <= lat_min <= 90 and -90 <= lat_max <= 90):
        raise ValueError("Bounding box coordinates are outside valid lon/lat ranges.")

    lon_span = lon_max - lon_min
    lat_span = lat_max - lat_min
    if lon_span > MAX_BBOX_SPAN_DEG or lat_span > MAX_BBOX_SPAN_DEG:
        raise ValueError(
            f"Selected area is too large (up to ~{MAX_BBOX_SPAN_DEG*111:.0f} km per side). "
            f"Zoom in and select a smaller village-scale region — the elevation data is "
            f"90 m resolution and isn't meaningful over very large areas."
        )
    if lon_span < MIN_BBOX_SPAN_DEG or lat_span < MIN_BBOX_SPAN_DEG:
        raise ValueError(
            "Selected area is too small to analyse — draw a larger region "
            "(at least a few hundred metres per side)."
        )


def _plan_grid(
    bbox: Tuple[float, float, float, float],
    target_long_axis: int,
    max_cells: int,
) -> GridMeta:
    """
    Work out an aspect-preserved grid shape for a bbox: the longer axis gets
    `target_long_axis` cells, the other is scaled to match, and the whole thing is
    capped at `max_cells`. Mirrors terrain_grid.build_grid's shape logic so both
    DEM sources produce comparable grids.
    """
    lon_min, lat_min, lon_max, lat_max = bbox
    lon_span = lon_max - lon_min
    lat_span = lat_max - lat_min

    aspect = lat_span / lon_span if lon_span > 0 else 1.0
    if aspect >= 1.0:
        rows = target_long_axis
        cols = max(10, int(target_long_axis / aspect))
    else:
        cols = target_long_axis
        rows = max(10, int(target_long_axis * aspect))

    # Cap total cells: scale both dimensions by the same factor so aspect holds.
    if rows * cols > max_cells:
        scale = (max_cells / (rows * cols)) ** 0.5
        rows = max(10, int(rows * scale))
        cols = max(10, int(cols * scale))

    return GridMeta(
        lon_min=lon_min, lon_max=lon_max,
        lat_min=lat_min, lat_max=lat_max,
        cell_lon=lon_span / cols, cell_lat=lat_span / rows,
        rows=rows, cols=cols,
    )


def _plan_sampling_grid(bbox: Tuple[float, float, float, float]) -> GridMeta:
    """The coarse grid we actually query the elevation API on (rate-limit capped)."""
    # A large target_long_axis just lets the max_cells cap decide the shape.
    return _plan_grid(bbox, target_long_axis=1000, max_cells=MAX_SAMPLE_POINTS)


def _plan_analysis_grid(bbox: Tuple[float, float, float, float], grid_size: int) -> GridMeta:
    """The finer grid the hydrology runs on, built by interpolating the samples."""
    return _plan_grid(bbox, target_long_axis=grid_size, max_cells=MAX_ANALYSIS_CELLS)


def _grid_coordinates(meta: GridMeta) -> Tuple[np.ndarray, np.ndarray]:
    """Return (lon_grid, lat_grid) meshgrids of cell centres, shape (rows, cols)."""
    col_centres = meta.lon_min + (np.arange(meta.cols) + 0.5) * meta.cell_lon
    row_centres = meta.lat_min + (np.arange(meta.rows) + 0.5) * meta.cell_lat
    lon_grid, lat_grid = np.meshgrid(col_centres, row_centres)
    return lon_grid, lat_grid


def _interpolate_to_analysis_grid(
    sample_lons: np.ndarray,
    sample_lats: np.ndarray,
    sample_elevs: np.ndarray,
    analysis_meta: GridMeta,
) -> np.ndarray:
    """
    Interpolate the fetched (coarse) elevation samples onto the finer analysis
    grid. Linear interpolation first, nearest-neighbour to fill any edge cells —
    the same two-step scheme terrain_grid uses when going from sparse contour
    vertices to a regular DEM. Returns a flat (rows*cols,) array in row-major
    order matching _grid_coordinates(analysis_meta).
    """
    a_lon, a_lat = _grid_coordinates(analysis_meta)
    pts = np.column_stack([sample_lons, sample_lats])
    query = np.column_stack([a_lon.ravel(), a_lat.ravel()])

    dem = griddata(pts, sample_elevs, query, method="linear")
    nan_mask = np.isnan(dem)
    if nan_mask.any():
        dem_near = griddata(pts, sample_elevs, query, method="nearest")
        dem[nan_mask] = dem_near[nan_mask]
    return dem


def build_grid_result(
    elevations: np.ndarray,
    meta: GridMeta,
    lon_grid: np.ndarray,
    lat_grid: np.ndarray,
    extra_notes: List[str] = None,
) -> GridResult:
    """
    Turn a flat array of elevations (in row-major order matching lon/lat grids)
    into a GridResult: reshape, light-smooth, and compute slope — the same
    finishing steps terrain_grid applies, so downstream code sees a consistent
    DEM regardless of source.
    """
    notes: List[str] = list(extra_notes or [])
    rows, cols = meta.rows, meta.cols

    dem = np.asarray(elevations, dtype=np.float64).reshape(rows, cols)

    # Any missing values (rare) get filled from the grid mean so the pipeline
    # never sees a NaN.
    if np.isnan(dem).any():
        n_nan = int(np.isnan(dem).sum())
        dem[np.isnan(dem)] = np.nanmean(dem)
        notes.append(f"Filled {n_nan} missing elevation samples with the local mean")

    # Same light smoothing terrain_grid uses to damp interpolation/sampling noise.
    dem = uniform_filter(dem, size=3, mode="nearest")

    cell_m = min(meta.cell_lon, meta.cell_lat) * 111_000
    slope = compute_slope(dem, cell_m)

    notes.append(f"DEM grid: {rows}×{cols} cells, cell size ≈ {cell_m:.1f} m")
    notes.append(f"Elevation range: {dem.min():.1f}–{dem.max():.1f} m")
    notes.append(f"Slope range: {slope.min():.2f}°–{slope.max():.2f}°")

    return GridResult(
        dem=dem, slope=slope,
        lon_grid=lon_grid, lat_grid=lat_grid,
        meta=meta, notes=notes,
    )


async def _fetch_batch(
    client: httpx.AsyncClient,
    lats: List[float],
    lons: List[float],
    sem: asyncio.Semaphore,
) -> List[float]:
    """
    Fetch elevations for one batch of <=100 coordinates, retrying with backoff
    on rate-limit (429) or transient 5xx errors — the free tier throttles bursts,
    so a couple of retries makes the whole grid fetch reliable.
    """
    lat_str = ",".join(f"{v:.6f}" for v in lats)
    lon_str = ",".join(f"{v:.6f}" for v in lons)
    params = {"latitude": lat_str, "longitude": lon_str}

    last_exc: Exception = RuntimeError("no attempt made")
    for attempt in range(MAX_RETRIES):
        async with sem:
            resp = await client.get(ELEVATION_URL, params=params, timeout=REQUEST_TIMEOUT_S)
        if resp.status_code == 200:
            return list(resp.json().get("elevation", []))
        if resp.status_code == 429 or resp.status_code >= 500:
            # Respect Retry-After when the server sends one, else exponential backoff.
            retry_after = resp.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else RETRY_BACKOFF_S * (2 ** attempt)
            last_exc = httpx.HTTPStatusError(
                f"{resp.status_code} from elevation service", request=resp.request, response=resp
            )
            await asyncio.sleep(delay)
            continue
        resp.raise_for_status()  # other 4xx: fail fast, no point retrying

    raise last_exc


async def fetch_dem_grid(
    bbox: Tuple[float, float, float, float],
    grid_size: int = 50,
) -> GridResult:
    """
    Build a DEM GridResult for a bounding box by querying the Open-Meteo
    elevation API.

    Parameters
    ----------
    bbox : (min_lon, min_lat, max_lon, max_lat)
    grid_size : target number of cells along the longer axis (capped internally)

    Returns
    -------
    GridResult — identical in shape to what terrain_grid.build_grid returns.

    Raises
    ------
    ValueError : bbox invalid or too large/small (→ 422 upstream)
    RuntimeError : the elevation service could not be reached / returned no data
    """
    _validate_bbox(bbox)

    cache_key = (tuple(round(v, 5) for v in bbox), grid_size)
    if cache_key in _CACHE:
        cached = _CACHE[cache_key]
        # Return a shallow copy with a fresh notes list so callers can append.
        return GridResult(
            dem=cached.dem, slope=cached.slope,
            lon_grid=cached.lon_grid, lat_grid=cached.lat_grid,
            meta=cached.meta, notes=list(cached.notes) + ["(elevation grid served from cache)"],
        )

    # 1. Query the API on the coarse, rate-limit-capped sampling grid.
    sample_meta = _plan_sampling_grid(bbox)
    s_lon, s_lat = _grid_coordinates(sample_meta)
    flat_lons = s_lon.ravel()
    flat_lats = s_lat.ravel()
    n_points = flat_lons.size

    batches = [
        (flat_lats[i:i + MAX_COORDS_PER_REQUEST].tolist(),
         flat_lons[i:i + MAX_COORDS_PER_REQUEST].tolist())
        for i in range(0, n_points, MAX_COORDS_PER_REQUEST)
    ]

    sem = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    try:
        async with httpx.AsyncClient() as client:
            results = await asyncio.gather(
                *[_fetch_batch(client, lats, lons, sem) for lats, lons in batches]
            )
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 429:
            raise RuntimeError(
                "The free elevation service is rate-limited right now (too many requests "
                "in the last minute). Please wait about a minute and try again — or select "
                "a smaller area, which needs fewer elevation samples."
            ) from exc
        raise RuntimeError(f"Could not reach the elevation service: {exc}") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Could not reach the elevation service: {exc}") from exc

    elevations: List[float] = []
    for batch in results:
        elevations.extend(batch)

    if len(elevations) != n_points:
        raise RuntimeError(
            f"Elevation service returned {len(elevations)} values for {n_points} "
            f"requested points — cannot build a complete DEM."
        )

    # 2. Interpolate the samples onto the finer analysis grid the hydrology runs on.
    analysis_meta = _plan_analysis_grid(bbox, grid_size)
    a_lon, a_lat = _grid_coordinates(analysis_meta)
    dem_flat = _interpolate_to_analysis_grid(
        flat_lons, flat_lats, np.array(elevations, dtype=np.float64), analysis_meta
    )

    notes = [
        f"Fetched {n_points} elevation samples from Open-Meteo "
        f"({sample_meta.rows}×{sample_meta.cols}) in {len(batches)} batched request(s)",
        f"Interpolated onto a {analysis_meta.rows}×{analysis_meta.cols} analysis grid",
    ]
    grid = build_grid_result(dem_flat, analysis_meta, a_lon, a_lat, notes)

    _CACHE[cache_key] = grid
    return grid
