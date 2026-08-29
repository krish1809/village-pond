"""
Unit tests for terrain_grid module.

Tests:
  - Grid builds successfully from minimal contour data
  - Grid shape is correct (rows × cols)
  - No NaN cells remain in the DEM
  - Slope grid has same shape as DEM
  - Elevation range in grid is within contour data range
  - GridMeta coordinate conversion is self-consistent
"""

import pytest
import numpy as np
from modules.kml_parser import ContourLine
from modules.terrain_grid import build_grid, GridMeta


def _make_contours_flat():
    """Flat terrain — one contour ring at a single elevation."""
    return [
        ContourLine(
            elevation=100.0,
            vertices=[(78.0, 18.0), (78.1, 18.0), (78.1, 18.1), (78.0, 18.1), (78.0, 18.0)],
        )
    ]


def _make_contours_sloped():
    """Simple sloped terrain — three elevation levels."""
    return [
        ContourLine(elevation=100.0, vertices=[(78.0, 18.0), (78.1, 18.0), (78.2, 18.0)]),
        ContourLine(elevation=102.0, vertices=[(78.0, 18.1), (78.1, 18.1), (78.2, 18.1)]),
        ContourLine(elevation=104.0, vertices=[(78.0, 18.2), (78.1, 18.2), (78.2, 18.2)]),
    ]


def test_build_grid_returns_grid_result():
    from modules.terrain_grid import GridResult
    result = build_grid(_make_contours_sloped(), grid_size=30)
    assert isinstance(result, GridResult)


def test_grid_shape():
    result = build_grid(_make_contours_sloped(), grid_size=30)
    rows, cols = result.dem.shape
    assert rows > 0 and cols > 0
    assert result.slope.shape == (rows, cols)
    assert result.lon_grid.shape == (rows, cols)
    assert result.lat_grid.shape == (rows, cols)


def test_no_nan_in_dem():
    result = build_grid(_make_contours_sloped(), grid_size=30)
    assert not np.isnan(result.dem).any(), "DEM should have no NaN cells after fill"


def test_elevation_range_within_contour_bounds():
    contours = _make_contours_sloped()
    result = build_grid(contours, grid_size=30)
    dem_min = result.dem.min()
    dem_max = result.dem.max()
    assert dem_min >= 99.0   # slight float room after smoothing
    assert dem_max <= 105.0


def test_slope_non_negative():
    result = build_grid(_make_contours_sloped(), grid_size=30)
    assert (result.slope >= 0).all(), "Slope should be non-negative everywhere"


def test_grid_meta_coordinate_roundtrip():
    result = build_grid(_make_contours_sloped(), grid_size=30)
    meta = result.meta
    # Convert center of grid to lon/lat then back → same cell
    r, c = meta.rows // 2, meta.cols // 2
    lon, lat = meta.grid_to_lonlat(r, c)
    r2, c2 = meta.lonlat_to_grid(lon, lat)
    assert abs(r2 - r) <= 1
    assert abs(c2 - c) <= 1


def test_grid_size_respected():
    result = build_grid(_make_contours_sloped(), grid_size=50)
    rows, cols = result.dem.shape
    # One axis should be close to 50 (the longer axis)
    assert max(rows, cols) >= 45


def test_notes_populated():
    result = build_grid(_make_contours_sloped(), grid_size=30)
    assert len(result.notes) > 0
