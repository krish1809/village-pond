"""
Contour lines — Generate elevation contour lines from a DEM for display.

Responsibility: turning the DEM grid into contour polylines (as lon/lat
coordinates) ONLY, so the front-end can draw the terrain the same way a printed
topographic map shows it. This is purely for visualization — the pond-siting
algorithm works on the DEM grid directly, not on these lines.

Uses contourpy (matplotlib's contour engine, a small C extension) rather than
importing all of matplotlib, so it's cheap on the memory-limited lab systems.
"""

from typing import Dict, List

import contourpy
import numpy as np


def generate(
    dem: np.ndarray,
    lon_grid: np.ndarray,
    lat_grid: np.ndarray,
    num_levels: int = 12,
    max_points_per_line: int = 400,
) -> List[Dict]:
    """
    Generate contour lines at evenly spaced elevations.

    Returns a list of {"elevation": float, "coordinates": [[lon, lat], ...]},
    one entry per contour segment. Very long segments are decimated to keep the
    response light.
    """
    lo = float(np.min(dem))
    hi = float(np.max(dem))
    if hi - lo < 0.5:
        return []  # essentially flat — no meaningful contours

    # Interior levels only (skip the exact min/max, which trace the border).
    levels = np.linspace(lo, hi, num_levels + 2)[1:-1]
    gen = contourpy.contour_generator(x=lon_grid, y=lat_grid, z=dem)

    features: List[Dict] = []
    for level in levels:
        for line in gen.lines(float(level)):
            if len(line) < 2:
                continue
            pts = line
            if len(pts) > max_points_per_line:
                step = int(np.ceil(len(pts) / max_points_per_line))
                pts = pts[::step]
            features.append({
                "elevation": round(float(level), 1),
                "coordinates": [[round(float(x), 6), round(float(y), 6)] for x, y in pts],
            })
    return features
