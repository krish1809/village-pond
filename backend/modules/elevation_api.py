"""
Elevation — Fetch a real DEM for a selected map region from OpenTopography.

Responsibility: turning a bounding box into an elevation grid ONLY. No flow
routing, no pond scoring, no volume maths — those consume the GridResult this
produces, the same GridResult that terrain_grid.build_grid produces from a
contour file. So the Phase 2 hydrology pipeline runs downstream unchanged: it
doesn't care whether the DEM came from a contour KML or from a real DEM tile.

Why OpenTopography (and not a per-coordinate elevation API): OpenTopography's
Global DEM API returns a whole raster for a bounding box in a SINGLE request, so
one analysis = one call — no per-coordinate rate-limit starvation. It serves
SRTM/Copernicus DEMs (30 m / 90 m) for the selected block, which is exactly what
"generate the terrain for the area the user picked" needs. It requires a free API
key (set in the OPENTOPOGRAPHY_API_KEY environment variable).

We request the ASCII-grid output format (`AAIGrid`), an ESRI ASCII raster, so we
can parse it with numpy and need NO native GDAL/rasterio dependency (the lab
containers don't have them).
"""

import os
from typing import Optional, Tuple

import httpx
import numpy as np

from modules.terrain_grid import GridResult, GridMeta, compute_slope

GLOBALDEM_URL = "https://portal.opentopography.org/API/globaldem"

# 30 m global DEM. SRTMGL3 (90 m) or COP90 could be used for very large areas,
# but village-scale blocks are small, so the higher resolution is worth it.
DEFAULT_DEMTYPE = "SRTMGL1"

REQUEST_TIMEOUT_S = 40.0

# Guardrails on the selected area (degrees). Below ~a few hundred metres there
# isn't enough terrain to delineate anything; above this the raster gets large
# and the 30 m detail is wasted, so we refuse and ask for a smaller block.
MIN_BBOX_SPAN_DEG = 0.003     # ~330 m
MAX_BBOX_SPAN_DEG = 0.25      # ~28 km

# Cap the analysis grid so flow routing stays fast and memory stays modest on the
# 512 MB lab containers. If the native raster is larger, it's downsampled by an
# integer stride to roughly this many cells on the longer axis.
MAX_LONG_AXIS_CELLS = 220

# Simple in-memory cache keyed by rounded bbox + demtype.
_CACHE: dict = {}


class ElevationConfigError(RuntimeError):
    """Raised when the API key is missing — a configuration problem, not a bad request."""


def _api_key() -> str:
    key = os.environ.get("OPENTOPOGRAPHY_API_KEY", "").strip()
    if not key:
        raise ElevationConfigError(
            "OpenTopography API key is not configured. Set the OPENTOPOGRAPHY_API_KEY "
            "environment variable (register free at https://portal.opentopography.org/)."
        )
    return key


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
            f"Zoom in and select a smaller, village-scale block."
        )
    if lon_span < MIN_BBOX_SPAN_DEG or lat_span < MIN_BBOX_SPAN_DEG:
        raise ValueError(
            "Selected area is too small to analyse — draw a larger block "
            "(at least a few hundred metres per side)."
        )


def parse_aaigrid(text: str) -> Tuple[np.ndarray, GridMeta]:
    """
    Parse an ESRI ASCII grid (AAIGrid) into a DEM array and GridMeta.

    Header: ncols, nrows, xllcorner, yllcorner, cellsize, NODATA_value.
    Data rows run north→south (first data row is the northernmost), so we flip
    vertically to match GridMeta's convention (row 0 = southernmost, i.e. row
    index increases with latitude).
    """
    header = {}
    tokens = text.split()
    i = 0
    # Read the 6 header key/value pairs.
    for _ in range(6):
        key = tokens[i].lower()
        val = tokens[i + 1]
        header[key] = val
        i += 2

    ncols = int(header["ncols"])
    nrows = int(header["nrows"])
    xll = float(header["xllcorner"])
    yll = float(header["yllcorner"])
    cell = float(header["cellsize"])
    nodata = float(header.get("nodata_value", -9999))

    values = np.array(tokens[i:i + ncols * nrows], dtype=np.float64)
    if values.size != ncols * nrows:
        raise ValueError(
            f"AAIGrid data size mismatch: expected {ncols*nrows} values, got {values.size}."
        )
    dem = values.reshape(nrows, ncols)

    # Flip so row 0 = south (increasing latitude with row index).
    dem = np.flipud(dem)

    # Replace NODATA with the grid mean so the pipeline never sees a sentinel.
    bad = dem == nodata
    if bad.any():
        good_mean = dem[~bad].mean() if (~bad).any() else 0.0
        dem[bad] = good_mean

    meta = GridMeta(
        lon_min=xll, lon_max=xll + ncols * cell,
        lat_min=yll, lat_max=yll + nrows * cell,
        cell_lon=cell, cell_lat=cell,
        rows=nrows, cols=ncols,
    )
    return dem, meta


def _downsample(dem: np.ndarray, meta: GridMeta) -> Tuple[np.ndarray, GridMeta]:
    """Stride-downsample the DEM if it's larger than MAX_LONG_AXIS_CELLS, keeping
    cells square and metadata consistent."""
    long_axis = max(meta.rows, meta.cols)
    if long_axis <= MAX_LONG_AXIS_CELLS:
        return dem, meta
    stride = int(np.ceil(long_axis / MAX_LONG_AXIS_CELLS))
    dem2 = dem[::stride, ::stride]
    rows2, cols2 = dem2.shape
    meta2 = GridMeta(
        lon_min=meta.lon_min, lon_max=meta.lon_min + cols2 * meta.cell_lon * stride,
        lat_min=meta.lat_min, lat_max=meta.lat_min + rows2 * meta.cell_lat * stride,
        cell_lon=meta.cell_lon * stride, cell_lat=meta.cell_lat * stride,
        rows=rows2, cols=cols2,
    )
    return dem2, meta2


def _build_grid_result(dem: np.ndarray, meta: GridMeta, notes) -> GridResult:
    col_centres = meta.lon_min + (np.arange(meta.cols) + 0.5) * meta.cell_lon
    row_centres = meta.lat_min + (np.arange(meta.rows) + 0.5) * meta.cell_lat
    lon_grid, lat_grid = np.meshgrid(col_centres, row_centres)

    cell_m = min(meta.cell_lon, meta.cell_lat) * 111_000
    slope = compute_slope(dem, cell_m)

    notes = list(notes)
    notes.append(f"DEM grid: {meta.rows}×{meta.cols} cells, cell size ≈ {cell_m:.0f} m")
    notes.append(f"Elevation range: {dem.min():.1f}–{dem.max():.1f} m")
    notes.append(f"Slope range: {slope.min():.2f}°–{slope.max():.2f}°")

    return GridResult(dem=dem, slope=slope, lon_grid=lon_grid, lat_grid=lat_grid, meta=meta, notes=notes)


async def fetch_dem_grid(
    bbox: Tuple[float, float, float, float],
    demtype: str = DEFAULT_DEMTYPE,
) -> GridResult:
    """
    Fetch a DEM GridResult for a bounding box from OpenTopography.

    Parameters
    ----------
    bbox : (min_lon, min_lat, max_lon, max_lat)
    demtype : OpenTopography DEM type (default SRTMGL1, 30 m)

    Raises
    ------
    ValueError : bbox invalid / too large / too small (→ 422 upstream)
    ElevationConfigError : API key missing (→ 500 upstream, a config issue)
    RuntimeError : OpenTopography unreachable or returned an error (→ 502 upstream)
    """
    _validate_bbox(bbox)
    key = _api_key()

    cache_key = (tuple(round(v, 5) for v in bbox), demtype)
    if cache_key in _CACHE:
        cached = _CACHE[cache_key]
        return GridResult(
            dem=cached.dem, slope=cached.slope,
            lon_grid=cached.lon_grid, lat_grid=cached.lat_grid,
            meta=cached.meta, notes=list(cached.notes) + ["(DEM served from cache)"],
        )

    lon_min, lat_min, lon_max, lat_max = bbox
    params = {
        "demtype": demtype,
        "south": lat_min, "north": lat_max,
        "west": lon_min, "east": lon_max,
        "outputFormat": "AAIGrid",
        "API_Key": key,
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(GLOBALDEM_URL, params=params, timeout=REQUEST_TIMEOUT_S)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Could not reach the OpenTopography DEM service: {exc}") from exc

    if resp.status_code == 401:
        raise ElevationConfigError("OpenTopography rejected the API key (401). Check OPENTOPOGRAPHY_API_KEY.")
    if resp.status_code == 400:
        raise ValueError(f"OpenTopography rejected the request: {resp.text[:200]}")
    if resp.status_code != 200:
        raise RuntimeError(
            f"OpenTopography returned HTTP {resp.status_code}: {resp.text[:200]}"
        )

    try:
        dem, meta = parse_aaigrid(resp.text)
    except Exception as exc:
        raise RuntimeError(f"Could not parse the DEM returned by OpenTopography: {exc}") from exc

    notes = [f"Fetched DEM from OpenTopography ({demtype}) for the selected block"]
    dem, meta = _downsample(dem, meta)
    grid = _build_grid_result(dem, meta, notes)

    _CACHE[cache_key] = grid
    return grid
