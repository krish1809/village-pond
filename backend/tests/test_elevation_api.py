"""Tests for the OpenTopography elevation module (Phase 3).

These cover the offline parts — bbox validation, AAIGrid parsing, and
downsampling — without hitting the network or needing an API key.
"""

import numpy as np
import pytest

from modules import elevation_api
from modules.terrain_grid import GridResult


def test_rejects_too_large_bbox():
    with pytest.raises(ValueError, match="too large"):
        elevation_api._validate_bbox((0.0, 0.0, 1.0, 1.0))


def test_rejects_inverted_bbox():
    with pytest.raises(ValueError, match="Invalid bounding box"):
        elevation_api._validate_bbox((81.31, 21.26, 81.28, 21.24))


def test_rejects_too_small_bbox():
    with pytest.raises(ValueError, match="too small"):
        elevation_api._validate_bbox((81.2800, 21.2400, 81.2810, 21.2410))


def _make_aaigrid(nrows, ncols, xll, yll, cell, values_north_to_south):
    header = (
        f"ncols {ncols}\nnrows {nrows}\n"
        f"xllcorner {xll}\nyllcorner {yll}\n"
        f"cellsize {cell}\nNODATA_value -9999\n"
    )
    rows = "\n".join(" ".join(str(v) for v in row) for row in values_north_to_south)
    return header + rows + "\n"


def test_parse_aaigrid_shapes_and_metadata():
    # 2 rows x 3 cols. Data is north-to-south; parser flips so row 0 = south.
    north = [10, 11, 12]
    south = [20, 21, 22]
    text = _make_aaigrid(2, 3, 81.0, 21.0, 0.001, [north, south])
    dem, meta = elevation_api.parse_aaigrid(text)

    assert dem.shape == (2, 3)
    assert meta.rows == 2 and meta.cols == 3
    # After the vertical flip, row 0 (southernmost) should be the 'south' row.
    assert list(dem[0]) == [20, 21, 22]
    assert list(dem[1]) == [10, 11, 12]
    assert meta.lon_min == 81.0
    assert abs(meta.lat_max - (21.0 + 2 * 0.001)) < 1e-9


def test_parse_aaigrid_replaces_nodata():
    text = _make_aaigrid(1, 3, 81.0, 21.0, 0.001, [[100, -9999, 200]])
    dem, _ = elevation_api.parse_aaigrid(text)
    assert not (dem == -9999).any()
    # the NODATA cell is filled with the mean of the good cells (150)
    assert dem[0, 1] == 150


def test_downsample_caps_long_axis():
    n = elevation_api.MAX_LONG_AXIS_CELLS * 3
    dem = np.random.rand(n, n)
    from modules.terrain_grid import GridMeta
    meta = GridMeta(lon_min=81.0, lon_max=81.3, lat_min=21.0, lat_max=21.3,
                    cell_lon=0.0003 / 3, cell_lat=0.0003 / 3, rows=n, cols=n)
    dem2, meta2 = elevation_api._downsample(dem, meta)
    assert max(meta2.rows, meta2.cols) <= elevation_api.MAX_LONG_AXIS_CELLS
    assert dem2.shape == (meta2.rows, meta2.cols)


def test_build_grid_result_from_parsed_dem():
    # A tilted plane so slope is well-defined.
    ncols, nrows = 20, 15
    rows_vals = [[c + r * 2 for c in range(ncols)] for r in range(nrows)]
    text = _make_aaigrid(nrows, ncols, 81.0, 21.0, 0.001, rows_vals)
    dem, meta = elevation_api.parse_aaigrid(text)
    grid = elevation_api._build_grid_result(dem, meta, ["note"])
    assert isinstance(grid, GridResult)
    assert grid.dem.shape == (meta.rows, meta.cols)
    assert grid.slope.shape == (meta.rows, meta.cols)
    assert grid.slope.min() >= 0.0


def test_missing_api_key_raises_config_error(monkeypatch):
    monkeypatch.delenv("OPENTOPOGRAPHY_API_KEY", raising=False)
    with pytest.raises(elevation_api.ElevationConfigError):
        elevation_api._api_key()
