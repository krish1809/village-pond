"""Tests for the water-volume estimates (Phase 3)."""

import numpy as np

from modules import water_volume


def test_annual_runoff_is_c_times_p_times_area():
    # 0.3 runoff of 1 m rain over 10,000 m² = 3,000 m³
    v = water_volume.annual_runoff_volume(catchment_area_m2=10_000, annual_rainfall_m=1.0, runoff_coefficient=0.3)
    assert v == 3000.0


def test_basin_capacity_sums_depth_below_water_level():
    # A 2x2 basin, water level 5 m. Depths below it: (5-3)+(5-4)+(5-5=0, excluded)+(5-1)
    dem = np.array([[3.0, 4.0], [5.0, 1.0]])
    mask = np.ones((2, 2), dtype=bool)
    # cell_area 100 m² → volume = (2 + 1 + 0 + 4) * 100 = 700
    vol = water_volume.basin_storage_capacity(dem, mask, water_level_m=5.0, cell_area_m2=100.0)
    assert vol == 700.0


def test_basin_capacity_ignores_cells_above_water_level():
    dem = np.array([[10.0, 10.0]])
    mask = np.ones((1, 2), dtype=bool)
    # everything is above the water level → zero storage
    assert water_volume.basin_storage_capacity(dem, mask, water_level_m=5.0, cell_area_m2=50.0) == 0.0


def test_collectable_is_the_smaller_limit():
    dem = np.zeros((3, 3))                 # flat basin at 0 m
    mask = np.ones((3, 3), dtype=bool)
    # capacity = 9 cells * 2 m depth * 100 m² = 1800 m³
    # runoff   = 0.3 * 0.05 m * 100000 m² = 1500 m³  → runoff is the limit
    res = water_volume.compute(
        catchment_area_m2=100_000,
        annual_rainfall_m=0.05,
        dem=dem,
        footprint_mask=mask,
        water_level_m=2.0,
        cell_area_m2=100.0,
        runoff_coefficient=0.3,
    )
    assert res.storage_capacity_m3 == 1800.0
    assert res.annual_runoff_m3 == 1500.0
    assert res.expected_collectable_m3 == 1500.0
    assert res.limiting_factor == "catchment_runoff"


def test_collectable_limited_by_capacity_when_basin_is_small():
    dem = np.zeros((1, 1))
    mask = np.ones((1, 1), dtype=bool)
    # tiny basin: capacity = 1 * 1 m * 10 m² = 10 m³; lots of runoff
    res = water_volume.compute(
        catchment_area_m2=1_000_000,
        annual_rainfall_m=1.0,
        dem=dem,
        footprint_mask=mask,
        water_level_m=1.0,
        cell_area_m2=10.0,
    )
    assert res.expected_collectable_m3 == 10.0
    assert res.limiting_factor == "basin_capacity"
