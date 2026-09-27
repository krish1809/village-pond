"""Tests for the elevation-API grid building (Phase 3).

These cover the pure, offline parts — bbox validation, grid shaping, and turning
a flat array of elevations into a GridResult — without hitting the network.
"""

import numpy as np
import pytest

from modules import elevation_api
from modules.terrain_grid import GridResult


def test_rejects_too_large_bbox():
    with pytest.raises(ValueError, match="too large"):
        elevation_api._validate_bbox((0.0, 0.0, 5.0, 5.0))


def test_rejects_inverted_bbox():
    with pytest.raises(ValueError, match="Invalid bounding box"):
        elevation_api._validate_bbox((81.31, 21.26, 81.28, 21.24))


def test_rejects_too_small_bbox():
    with pytest.raises(ValueError, match="too small"):
        elevation_api._validate_bbox((81.2800, 21.2400, 81.2805, 21.2405))


def test_analysis_grid_preserves_aspect():
    # A wide, short box → cols (lon axis) should be the long axis.
    meta = elevation_api._plan_analysis_grid((81.0, 21.0, 81.4, 21.1), grid_size=60)
    assert meta.cols > meta.rows     # longer (lon) axis has more cells
    assert meta.rows * meta.cols <= elevation_api.MAX_ANALYSIS_CELLS


def test_sampling_grid_stays_within_api_budget():
    # The sampling grid must never exceed the rate-limit point cap, whatever the box.
    for box in [(81.0, 21.0, 81.3, 21.3), (81.0, 21.0, 81.5, 21.1), (81.0, 21.0, 81.02, 21.05)]:
        meta = elevation_api._plan_sampling_grid(box)
        assert meta.rows * meta.cols <= elevation_api.MAX_SAMPLE_POINTS


def test_analysis_grid_is_finer_than_sampling_grid():
    box = (81.0, 21.0, 81.3, 21.3)
    sample = elevation_api._plan_sampling_grid(box)
    analysis = elevation_api._plan_analysis_grid(box, grid_size=80)
    assert analysis.rows * analysis.cols > sample.rows * sample.cols


def test_interpolation_produces_full_analysis_grid():
    box = (81.0, 21.0, 81.05, 21.05)
    sample = elevation_api._plan_sampling_grid(box)
    s_lon, s_lat = elevation_api._grid_coordinates(sample)
    # A tilted plane so linear interpolation is exact and slope is non-zero.
    s_elev = (s_lon * 1000 + s_lat * 500).ravel()

    analysis = elevation_api._plan_analysis_grid(box, grid_size=40)
    dem_flat = elevation_api._interpolate_to_analysis_grid(
        s_lon.ravel(), s_lat.ravel(), s_elev, analysis
    )
    assert dem_flat.shape == (analysis.rows * analysis.cols,)
    assert not np.isnan(dem_flat).any()


def test_build_grid_result_reshapes_and_computes_slope():
    meta = elevation_api._plan_analysis_grid((81.0, 21.0, 81.05, 21.05), grid_size=20)
    lon_grid, lat_grid = elevation_api._grid_coordinates(meta)
    # A simple tilted plane so slope is well-defined and non-zero.
    elevations = (lon_grid * 1000 + lat_grid * 500).ravel()
    grid = elevation_api.build_grid_result(elevations, meta, lon_grid, lat_grid)

    assert isinstance(grid, GridResult)
    assert grid.dem.shape == (meta.rows, meta.cols)
    assert grid.slope.shape == (meta.rows, meta.cols)
    assert not np.isnan(grid.dem).any()
    assert grid.slope.min() >= 0.0


def test_build_grid_result_fills_missing_values():
    meta = elevation_api._plan_analysis_grid((81.0, 21.0, 81.05, 21.05), grid_size=20)
    lon_grid, lat_grid = elevation_api._grid_coordinates(meta)
    elevations = np.full(meta.rows * meta.cols, 300.0)
    elevations[0] = np.nan
    grid = elevation_api.build_grid_result(elevations, meta, lon_grid, lat_grid)
    assert not np.isnan(grid.dem).any()
