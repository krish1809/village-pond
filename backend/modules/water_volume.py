"""
Water Volume — Estimate how much water a candidate pond can actually collect.

Responsibility: volume/runoff arithmetic ONLY. No terrain building, no API
calls, no geometry. Takes already-computed terrain masks and a rainfall figure
and returns the volume numbers.

Two different volumes matter, and they answer different questions:

  1. Annual runoff delivered by the catchment (how much water arrives).
     Rational-method style estimate:

         V_runoff = C · P · A_catchment                         (m³/year)

     where P is mean annual rainfall (metres/year), A_catchment is the
     contributing catchment area (m²), and C is a runoff coefficient — the
     fraction of rain that becomes surface runoff instead of infiltrating or
     evaporating. C≈0.3 is a common default for mixed rural/agricultural
     ground; it's exposed as a parameter rather than baked in, since it really
     depends on soil and land cover.

  2. Basin storage capacity (how much water the pond can physically hold).
     Computed straight from the DEM over the pond's flood-fill footprint:

         V_capacity = Σ_cells (water_level − cell_elevation) · cell_area   (m³)

     i.e. the volume of the empty basin below the assumed water surface. This
     is more faithful than a flat area×depth product because it accounts for
     the basin actually being shallower near its edges.

The water that can realistically be *collected* is bounded by both — you can't
store more than the basin holds, and you can't collect more than the catchment
delivers — so:

     V_collectable = min(V_runoff, V_capacity)

All three are returned so the trade-off is visible, not hidden behind one
number.
"""

from dataclasses import dataclass, field
from typing import List

import numpy as np


# Fraction of annual rainfall that becomes surface runoff (vs. infiltrating /
# evaporating). 0.3 is a reasonable default for mixed rural terrain; overridable
# per request because the "right" value depends on soil type and land cover.
DEFAULT_RUNOFF_COEFFICIENT = 0.3


@dataclass
class WaterVolumeResult:
    """Volume estimates for one candidate pond site."""

    catchment_area_m2: float
    annual_rainfall_m: float          # mean annual rainfall used, in metres
    runoff_coefficient: float

    annual_runoff_m3: float           # water the catchment delivers per year
    storage_capacity_m3: float        # what the basin can physically hold
    expected_collectable_m3: float    # min of the two — the headline figure

    limiting_factor: str              # "catchment_runoff" or "basin_capacity"
    notes: List[str] = field(default_factory=list)


def annual_runoff_volume(
    catchment_area_m2: float,
    annual_rainfall_m: float,
    runoff_coefficient: float = DEFAULT_RUNOFF_COEFFICIENT,
) -> float:
    """V = C · P · A  (m³/year). See module docstring."""
    return runoff_coefficient * annual_rainfall_m * catchment_area_m2


def basin_storage_capacity(
    dem: np.ndarray,
    footprint_mask: np.ndarray,
    water_level_m: float,
    cell_area_m2: float,
) -> float:
    """
    Volume of the empty basin below `water_level_m`, summed cell-by-cell over
    the pond footprint. Only cells genuinely below the water surface count.
    """
    if not footprint_mask.any():
        return 0.0
    depths = water_level_m - dem[footprint_mask]
    depths = depths[depths > 0.0]
    return float(depths.sum() * cell_area_m2)


def compute(
    catchment_area_m2: float,
    annual_rainfall_m: float,
    dem: np.ndarray,
    footprint_mask: np.ndarray,
    water_level_m: float,
    cell_area_m2: float,
    runoff_coefficient: float = DEFAULT_RUNOFF_COEFFICIENT,
) -> WaterVolumeResult:
    """
    Assemble the full water-volume picture for one candidate: annual runoff
    delivered by the catchment, the basin's storage capacity, and the
    collectable volume (the smaller of the two).
    """
    runoff = annual_runoff_volume(catchment_area_m2, annual_rainfall_m, runoff_coefficient)
    capacity = basin_storage_capacity(dem, footprint_mask, water_level_m, cell_area_m2)

    collectable = min(runoff, capacity)
    limiting = "catchment_runoff" if runoff <= capacity else "basin_capacity"

    notes = [
        f"Annual runoff = {runoff_coefficient} × {annual_rainfall_m:.3f} m rain × "
        f"{catchment_area_m2:.0f} m² catchment ≈ {runoff:.0f} m³/yr",
        f"Basin storage capacity below the assumed water level ≈ {capacity:.0f} m³",
        f"Collectable volume is limited by the {limiting.replace('_', ' ')} "
        f"≈ {collectable:.0f} m³",
    ]

    return WaterVolumeResult(
        catchment_area_m2=round(catchment_area_m2, 2),
        annual_rainfall_m=round(annual_rainfall_m, 4),
        runoff_coefficient=runoff_coefficient,
        annual_runoff_m3=round(runoff, 2),
        storage_capacity_m3=round(capacity, 2),
        expected_collectable_m3=round(collectable, 2),
        limiting_factor=limiting,
        notes=notes,
    )
