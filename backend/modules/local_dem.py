"""
Local DEM — an offline elevation source built from the bundled contour map.

Why this exists: /analyzeArea can fetch a DEM for any location from the Open-Meteo
elevation API, but that's a free service with a hard daily request limit. For a
live demo/viva we need something that always works, instantly, with no external
dependency. Phase 2 already ships a real contour map (`contours_1m.kml`) of a
village-scale area, so for any region inside that map's coverage we can build the
DEM straight from those contours — exactly the Phase 2 approach — with no API call
at all.

The route uses this first (when the selected area is within the contour map) and
only falls back to the elevation API for areas outside it. This keeps the sample
area 100% reliable while still supporting "select anywhere" when the API has
budget.

Responsibility: turning the bundled contour file into a GridResult for a sub-area
ONLY. It reuses kml_parser and terrain_grid — no new terrain logic here.
"""

from pathlib import Path
from typing import List, Optional, Tuple

from modules import kml_parser, terrain_grid
from modules.kml_parser import ContourLine
from modules.terrain_grid import GridResult

# The bundled contour map lives at the repository root (two levels up from here).
_CONTOUR_FILE = Path(__file__).resolve().parents[2] / "contours_1m.kml"

# Fraction of the selected bbox that must lie within the contour map's coverage
# for us to use the offline DEM instead of the elevation API.
_MIN_OVERLAP = 0.5

# Minimum number of contour lines that must fall inside the selected area for the
# offline DEM to be worth building (otherwise there isn't enough data — fall back).
_MIN_LINES_IN_AREA = 15

# Lazily-loaded, cached once: (contour_lines, coverage_bounds).
_cache: dict = {"lines": None, "bounds": None}


def _load() -> Tuple[Optional[List[ContourLine]], Optional[Tuple[float, float, float, float]]]:
    """Parse and cache the bundled contour file. Returns (lines, bounds) or (None, None)."""
    if _cache["lines"] is None:
        if not _CONTOUR_FILE.is_file():
            _cache["lines"] = []  # mark as attempted so we don't re-check every call
            _cache["bounds"] = None
            return None, None
        data = _CONTOUR_FILE.read_bytes()
        result = kml_parser.parse(data, _CONTOUR_FILE.name)
        lines = result.contour_lines

        lon_min = lat_min = float("inf")
        lon_max = lat_max = float("-inf")
        for cl in lines:
            for lon, lat in cl.vertices:
                if lon < lon_min: lon_min = lon
                if lon > lon_max: lon_max = lon
                if lat < lat_min: lat_min = lat
                if lat > lat_max: lat_max = lat

        _cache["lines"] = lines
        _cache["bounds"] = (lon_min, lat_min, lon_max, lat_max)

    if not _cache["lines"]:
        return None, None
    return _cache["lines"], _cache["bounds"]


def coverage_bounds() -> Optional[Tuple[float, float, float, float]]:
    """Bounding box (min_lon, min_lat, max_lon, max_lat) of the bundled contour map."""
    return _load()[1]


def covers(bbox: Tuple[float, float, float, float]) -> bool:
    """True if enough of the selected bbox lies within the contour map's coverage."""
    bounds = coverage_bounds()
    if bounds is None:
        return False
    w, s, e, n = bbox
    lw, ls, le, ln = bounds
    ix = max(0.0, min(e, le) - max(w, lw))
    iy = max(0.0, min(n, ln) - max(s, ls))
    inter = ix * iy
    bbox_area = (e - w) * (n - s)
    return bbox_area > 0 and (inter / bbox_area) >= _MIN_OVERLAP


def build_local_grid(
    bbox: Tuple[float, float, float, float],
    grid_size: int = 70,
) -> Optional[GridResult]:
    """
    Build a DEM for the selected area from the bundled contours, offline.

    Filters the contour vertices to the selected area (plus a small margin) and
    feeds them to terrain_grid.build_grid — the same construction Phase 2 uses.
    Returns None if the area doesn't contain enough contour data to be meaningful,
    so the caller can fall back to the elevation API.
    """
    lines, _ = _load()
    if not lines:
        return None

    w, s, e, n = bbox
    mx = (e - w) * 0.05
    my = (n - s) * 0.05
    lo_w, lo_s, lo_e, lo_n = w - mx, s - my, e + mx, n + my

    sub: List[ContourLine] = []
    for cl in lines:
        verts = [(lon, lat) for lon, lat in cl.vertices if lo_w <= lon <= lo_e and lo_s <= lat <= lo_n]
        if len(verts) >= 2:
            sub.append(ContourLine(elevation=cl.elevation, vertices=verts))

    if len(sub) < _MIN_LINES_IN_AREA:
        return None

    grid = terrain_grid.build_grid(sub, grid_size=grid_size)
    grid.notes.insert(0, "DEM built from the bundled contour map (offline — no external API needed)")
    return grid
