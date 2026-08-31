"""
Unit tests for pond_locator module.

Tests:
  - Candidates are returned in descending score order
  - Candidates are spatially distinct (not clustered on one local maximum)
  - Overly steep terrain returns no infeasible candidates
"""

import numpy as np

from modules.pond_locator import find_candidates, MAX_FEASIBLE_SLOPE_DEG
from modules.terrain_grid import GridResult, GridMeta
from modules.catchment import compute_flow


def _make_grid(dem: np.ndarray) -> GridResult:
    rows, cols = dem.shape
    meta = GridMeta(
        lon_min=78.0, lon_max=78.0 + cols * 0.0001,
        lat_min=18.0, lat_max=18.0 + rows * 0.0001,
        cell_lon=0.0001, cell_lat=0.0001,
        rows=rows, cols=cols,
    )
    slope = np.gradient(dem)[0]  # placeholder slope, not used precisely here
    slope = np.abs(slope)
    lon_grid, lat_grid = np.meshgrid(
        meta.lon_min + (np.arange(cols) + 0.5) * meta.cell_lon,
        meta.lat_min + (np.arange(rows) + 0.5) * meta.cell_lat,
    )
    return GridResult(dem=dem, slope=slope, lon_grid=lon_grid, lat_grid=lat_grid, meta=meta, notes=[])


def _multi_basin_dem(size=60):
    """Three separated bowl-shaped basins on one map."""
    dem = np.full((size, size), 100.0)
    centers = [(15, 15), (15, 45), (45, 30)]
    for cy, cx in centers:
        for r in range(size):
            for c in range(size):
                d2 = (r - cy) ** 2 + (c - cx) ** 2
                dem[r, c] = min(dem[r, c], 50.0 + 0.05 * d2)
    return dem


def test_candidates_ranked_descending():
    dem = _multi_basin_dem()
    grid = _make_grid(dem)
    flow = compute_flow(grid.dem)
    candidates = find_candidates(grid, flow.flow_acc, num_candidates=3)
    scores = [c.suitability_score for c in candidates]
    assert scores == sorted(scores, reverse=True)


def test_candidates_are_spatially_distinct():
    dem = _multi_basin_dem()
    grid = _make_grid(dem)
    flow = compute_flow(grid.dem)
    candidates = find_candidates(grid, flow.flow_acc, num_candidates=3)
    coords = [(c.row, c.col) for c in candidates]
    for i in range(len(coords)):
        for j in range(i + 1, len(coords)):
            dist = ((coords[i][0] - coords[j][0]) ** 2 + (coords[i][1] - coords[j][1]) ** 2) ** 0.5
            assert dist > 3, f"Candidates {i} and {j} are too close: {coords[i]} vs {coords[j]}"


def test_respects_num_candidates_limit():
    dem = _multi_basin_dem()
    grid = _make_grid(dem)
    flow = compute_flow(grid.dem)
    candidates = find_candidates(grid, flow.flow_acc, num_candidates=2)
    assert len(candidates) <= 2


def test_pond_footprint_basic():
    """Footprint should be non-empty, contain the pour point, and respect the water level."""
    from modules.pond_locator import compute_pond_footprint

    dem = _multi_basin_dem()
    mask, info = compute_pond_footprint(dem, 15, 15, assumed_depth_m=2.0)

    assert mask[15, 15]  # pour point itself is always included
    assert mask.sum() >= 1
    assert info["assumed_depth_m"] == 2.0
    assert info["water_level_m"] == dem[15, 15] + 2.0

    # Every flooded cell must be at or below the water level
    flooded_elevations = dem[mask]
    assert (flooded_elevations <= info["water_level_m"] + 1e-9).all()


def test_pond_footprint_caps_on_flat_terrain():
    """A perfectly flat DEM should flood-fill until the growth cap kicks in."""
    from modules.pond_locator import compute_pond_footprint

    flat_dem = np.full((60, 60), 100.0)
    mask, info = compute_pond_footprint(flat_dem, 30, 30, assumed_depth_m=2.0)
    assert info["capped"] is True
    assert mask.sum() > 1  # grew well beyond a single cell before being capped


def test_pond_footprint_smaller_on_steep_terrain():
    """A steep, narrow basin should flood a small area and not need capping."""
    from modules.pond_locator import compute_pond_footprint

    size = 60
    dem = np.zeros((size, size))
    cy, cx = size // 2, size // 2
    for r in range(size):
        for c in range(size):
            dem[r, c] = 50.0 + 2.0 * np.hypot(r - cy, c - cx)  # steep cone-shaped basin
    mask, info = compute_pond_footprint(dem, cy, cx, assumed_depth_m=2.0)
    assert info["capped"] is False
    assert mask.sum() < (size * size) * 0.05


def test_excludes_infeasible_slopes():
    """A uniformly very steep DEM should exclude most/all cells as infeasible."""
    size = 20
    dem = np.zeros((size, size))
    for r in range(size):
        for c in range(size):
            dem[r, c] = r * 50.0  # extremely steep uniform slope
    grid = _make_grid(dem)
    # Override slope directly to guarantee it's above threshold everywhere except one row
    grid.slope[:, :] = MAX_FEASIBLE_SLOPE_DEG + 5.0
    grid.slope[0, :] = 1.0  # one feasible row
    flow = compute_flow(grid.dem)
    candidates = find_candidates(grid, flow.flow_acc, num_candidates=3, boundary_margin=0.0)
    for c in candidates:
        assert c.slope_deg <= MAX_FEASIBLE_SLOPE_DEG


def test_excludes_main_drainage_channel():
    """No candidate should sit on the highest-flow-accumulation cells,
    which represent the existing stream/river channel rather than a site
    suitable for excavated storage."""
    dem = _multi_basin_dem()
    grid = _make_grid(dem)
    flow = compute_flow(grid.dem)
    channel_threshold = np.percentile(flow.flow_acc, 97.0)

    candidates = find_candidates(grid, flow.flow_acc, num_candidates=3)
    for c in candidates:
        flow_acc_here = flow.flow_acc[c.row, c.col]
        assert flow_acc_here <= channel_threshold, (
            f"Candidate rank {c.rank} sits on the channel: "
            f"flow_acc={flow_acc_here} > threshold={channel_threshold}"
        )
