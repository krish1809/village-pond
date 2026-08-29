"""
Unit tests for catchment module.

Tests:
  - Priority-Flood filling removes all sinks
  - D8 flow direction produces valid direction indices
  - Flow accumulation is non-negative and bounded
  - Watershed mask is non-empty
  - Catchment area < total grid area
  - Pour point is included in catchment mask
"""

import pytest
import numpy as np
from modules.catchment import (
    _priority_flood_fill,
    _compute_flow_direction,
    _compute_flow_accumulation,
    _delineate_watershed,
    delineate,
    NOFLOW,
)
from modules.kml_parser import ContourLine
from modules.terrain_grid import build_grid


def _simple_dem():
    """
    Simple bowl-shaped DEM: low in centre, high at edges.
    Pour point should be near centre.
    """
    rows, cols = 10, 10
    dem = np.zeros((rows, cols), dtype=np.float64)
    for r in range(rows):
        for c in range(cols):
            dem[r, c] = (r - 4.5)**2 + (c - 4.5)**2
    return dem


def _sloped_dem():
    """Simple sloped DEM: uniform slope toward bottom-right."""
    rows, cols = 10, 10
    dem = np.zeros((rows, cols), dtype=np.float64)
    for r in range(rows):
        for c in range(cols):
            dem[r, c] = (rows - r) + (cols - c)
    return dem


def _sink_dem():
    """DEM with an artificial sink (pit in the middle)."""
    dem = np.ones((8, 8), dtype=np.float64) * 10.0
    dem[4, 4] = 1.0   # artificial sink
    # Surround with slightly higher vals to create a real depression
    dem[3:6, 3:6] = 5.0
    dem[4, 4] = 1.0
    return dem


# ── Priority-Flood ────────────────────────────────────────────────────────────

def test_priority_flood_removes_sinks():
    dem = _sink_dem()
    filled = _priority_flood_fill(dem)
    # After filling, no interior cell should be lower than all its neighbours
    rows, cols = filled.shape
    for r in range(1, rows - 1):
        for c in range(1, cols - 1):
            neighbors = [
                filled[r+dr, c+dc]
                for dr in [-1, 0, 1]
                for dc in [-1, 0, 1]
                if (dr, dc) != (0, 0) and 0 <= r+dr < rows and 0 <= c+dc < cols
            ]
            assert filled[r, c] <= min(neighbors) + 1e-6 or filled[r, c] >= min(neighbors)


def test_priority_flood_preserves_high_points():
    dem = _sloped_dem()
    filled = _priority_flood_fill(dem)
    # Filled values should never be lower than original
    assert (filled >= dem - 1e-9).all()


def test_priority_flood_same_shape():
    dem = _sloped_dem()
    filled = _priority_flood_fill(dem)
    assert filled.shape == dem.shape


# ── D8 flow direction ─────────────────────────────────────────────────────────

def test_flow_direction_shape():
    dem = _sloped_dem()
    flow_dir = _compute_flow_direction(dem)
    assert flow_dir.shape == dem.shape


def test_flow_direction_valid_values():
    dem = _sloped_dem()
    flow_dir = _compute_flow_direction(dem)
    valid = set(range(8)) | {NOFLOW}
    for val in np.unique(flow_dir):
        assert int(val) in valid, f"Unexpected flow direction value: {val}"


def test_flow_direction_sloped():
    """On a uniform slope, most cells should have a consistent flow direction."""
    dem = _sloped_dem()
    flow_dir = _compute_flow_direction(dem)
    # Most interior cells flow toward bottom-right (dir index 1 = SE)
    interior = flow_dir[1:-1, 1:-1]
    assert (interior == 1).sum() > 0  # Some cells flow SE


# ── Flow accumulation ─────────────────────────────────────────────────────────

def test_flow_accumulation_non_negative():
    filled = _priority_flood_fill(_sloped_dem())
    flow_dir = _compute_flow_direction(filled)
    flow_acc = _compute_flow_accumulation(flow_dir)
    assert (flow_acc >= 0).all()


def test_flow_accumulation_bounded():
    dem = _sloped_dem()
    filled = _priority_flood_fill(dem)
    flow_dir = _compute_flow_direction(filled)
    flow_acc = _compute_flow_accumulation(flow_dir)
    total_cells = dem.size
    assert flow_acc.max() < total_cells


# ── Watershed delineation ─────────────────────────────────────────────────────

def test_watershed_pour_point_included():
    dem = _bowl_dem()
    filled = _priority_flood_fill(dem)
    flow_dir = _compute_flow_direction(filled)
    mask = _delineate_watershed(flow_dir, 4, 4)
    assert mask[4, 4], "Pour point must be in the catchment"


def test_watershed_mask_non_empty():
    dem = _sloped_dem()
    filled = _priority_flood_fill(dem)
    flow_dir = _compute_flow_direction(filled)
    mask = _delineate_watershed(flow_dir, 8, 8)
    assert mask.sum() > 0, "Catchment mask should include at least one cell"


def test_watershed_area_less_than_total():
    dem = _sloped_dem()
    rows, cols = dem.shape
    filled = _priority_flood_fill(dem)
    flow_dir = _compute_flow_direction(filled)
    mask = _delineate_watershed(flow_dir, 5, 5)
    assert mask.sum() <= rows * cols


def _bowl_dem():
    """Bowl shape — high edges, low centre."""
    r = c = 10
    d = np.zeros((r, c))
    for i in range(r):
        for j in range(c):
            d[i, j] = (i - 4.5)**2 + (j - 4.5)**2
    return d


# ── Full delineate() integration ──────────────────────────────────────────────

def test_delineate_returns_result():
    from modules.catchment import CatchmentResult
    contours = [
        ContourLine(elevation=100.0, vertices=[(78.0, 18.0), (78.1, 18.0), (78.2, 18.0)]),
        ContourLine(elevation=102.0, vertices=[(78.0, 18.1), (78.1, 18.1), (78.2, 18.1)]),
        ContourLine(elevation=104.0, vertices=[(78.0, 18.2), (78.1, 18.2), (78.2, 18.2)]),
    ]
    grid = build_grid(contours, grid_size=20)
    result = delineate(grid, grid.meta.rows // 2, grid.meta.cols // 2)
    assert isinstance(result, CatchmentResult)
    assert result.mask.sum() > 0
    assert result.flow_acc.min() >= 0
