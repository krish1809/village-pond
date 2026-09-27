"""Tests for the offline contour-map DEM (Phase 3), no network involved."""

from modules import local_dem
from modules.terrain_grid import GridResult


def test_coverage_bounds_available():
    b = local_dem.coverage_bounds()
    assert b is not None
    lon_min, lat_min, lon_max, lat_max = b
    assert lon_min < lon_max and lat_min < lat_max


def test_covers_inside_and_outside():
    b = local_dem.coverage_bounds()
    cx = (b[0] + b[2]) / 2
    cy = (b[1] + b[3]) / 2
    # A small box at the centre is covered...
    assert local_dem.covers((cx - 0.005, cy - 0.004, cx + 0.005, cy + 0.004))
    # ...an area far away is not.
    assert not local_dem.covers((0.0, 0.0, 0.01, 0.01))


def test_build_local_grid_returns_dem_for_covered_area():
    b = local_dem.coverage_bounds()
    cx = (b[0] + b[2]) / 2
    cy = (b[1] + b[3]) / 2
    grid = local_dem.build_local_grid((cx - 0.006, cy - 0.004, cx + 0.006, cy + 0.004), grid_size=60)
    assert isinstance(grid, GridResult)
    assert grid.dem.shape[0] >= 10 and grid.dem.shape[1] >= 10
    assert grid.dem.max() > grid.dem.min()  # real relief from the contours


def test_build_local_grid_none_for_uncovered_area():
    # Nothing bundled out in the ocean → no contour data → None (caller uses API).
    assert local_dem.build_local_grid((0.0, 0.0, 0.02, 0.02), grid_size=60) is None
