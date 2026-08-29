"""
Pond Locator — Identify the most suitable pond location using a multi-criteria
terrain suitability index derived from research literature.

Responsibility: Scoring cells using terrain indices ONLY. No KML parsing,
no flow computation (those are done upstream). Takes the DEM grid and
flow accumulation as inputs, returns a single (row, col) pour point.

Multi-criteria suitability score (weighted composite):

  Score = w1*TWI_norm + w2*TPI_norm + w3*SPI_norm + w4*Curvature_norm

  Where:
    TWI  = ln(As / tan β + ε)           Topographic Wetness Index
           [Beven & Kirkby, 1979]
           High TWI → more water accumulation potential → good for pond

    TPI  = z₀ - mean(z_neighborhood)    Topographic Position Index
           [Guisan et al., 1999]
           Negative TPI → valley / depression → good for pond

    SPI  = ln(As × tan β + ε)           Stream Power Index
           [Moore et al., 1991]
           Moderate SPI → water concentrates but not eroding → good

    Plan Curvature (∂²z/∂x² + ∂²z/∂y²)
           Positive plan curvature → convergent flow paths → good for pond

All four indices are normalised to [0, 1] and combined with literature-
guided weights (TWI highest since it directly measures wetness potential).

References:
  Beven, K.J., Kirkby, M.J. (1979). A physically based variable contributing
      area model of basin hydrology. Hydrological Sciences Bulletin, 24(1).
  Guisan, A. et al. (1999). Predictive habitat models in ecology. Ecological
      Modelling, 135(2–3), 147-186.
  Moore, I.D., Grayson, R.B., Ladson, A.R. (1991). Digital terrain modelling.
      Hydrological Processes, 5(1), 3-30.
"""

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np
from scipy.ndimage import uniform_filter

from modules.terrain_grid import GridResult


@dataclass
class PondCandidate:
    """Best pond location returned by the locator."""
    row: int
    col: int
    lon: float
    lat: float
    elevation_m: float

    # Terrain indices at the selected site
    twi: float
    tpi: float
    spi: float
    plan_curvature: float
    profile_curvature: float
    suitability_score: float  # composite 0-1

    notes: List[str]


def _compute_twi(flow_acc: np.ndarray, slope_deg: np.ndarray, cell_area_m2: float) -> np.ndarray:
    """
    Topographic Wetness Index: TWI = ln(As / tan β)
    As = upslope contributing area (m²) = flow_acc × cell_area
    β  = local slope (radians)

    High TWI → topographic convergence, saturated soils → ideal pond location.
    """
    eps = 1e-6
    slope_rad = np.radians(slope_deg)
    As = (flow_acc + 1).astype(np.float64) * cell_area_m2  # +1 avoids ln(0)
    twi = np.log(As / (np.tan(slope_rad) + eps))
    return twi


def _compute_tpi(dem: np.ndarray, window: int = 11) -> np.ndarray:
    """
    Topographic Position Index: TPI = z₀ - mean(z_neighborhood)

    Negative TPI → valley or depression (lower than surroundings).
    We want negative TPI for pond siting → invert for scoring.
    Window size 11 ≈ captures hillslope-scale variation.
    """
    mean_neighborhood = uniform_filter(dem, size=window, mode="nearest")
    return dem - mean_neighborhood


def _compute_spi(flow_acc: np.ndarray, slope_deg: np.ndarray, cell_area_m2: float) -> np.ndarray:
    """
    Stream Power Index: SPI = ln(As × tan β)

    High SPI indicates high erosive/transport energy. We want MODERATE SPI
    (water concentrates but terrain is not actively channel-eroding) → the
    score peaks in the middle range after normalisation.
    """
    eps = 1e-6
    slope_rad = np.radians(slope_deg)
    As = (flow_acc + 1).astype(np.float64) * cell_area_m2
    spi = np.log(As * (np.tan(slope_rad) + eps))
    return spi


def _compute_plan_curvature(dem: np.ndarray, cell_size_m: float) -> np.ndarray:
    """
    Plan curvature: curvature of the contour lines (perpendicular to slope).

    Computed as ∂²z/∂x² + ∂²z/∂y² (Laplacian approximation).
    Positive → convergent flow (concave plan shape) → water concentrates → good.

    Reference: Zevenbergen & Thorne (1987), Earth Surface Processes and
    Landforms, 12(1), 47-56.
    """
    # Second-order finite differences
    dxx = np.gradient(np.gradient(dem, cell_size_m, axis=1), cell_size_m, axis=1)
    dyy = np.gradient(np.gradient(dem, cell_size_m, axis=0), cell_size_m, axis=0)
    return dxx + dyy  # Laplacian — positive = concave = flow convergence


def _compute_profile_curvature(dem: np.ndarray, cell_size_m: float) -> np.ndarray:
    """
    Profile curvature: curvature in the direction of steepest descent.

    Approximated as the second derivative of elevation in the steepest-descent
    direction. Positive profile curvature → concave slope → flow decelerates
    and pools → favorable for pond.
    """
    dy, dx = np.gradient(dem, cell_size_m, cell_size_m)
    grad_mag = np.sqrt(dx**2 + dy**2) + 1e-10
    # Unit gradient vector components
    ux = dx / grad_mag
    uy = dy / grad_mag
    # Second derivative in that direction (directional second derivative)
    dxx = np.gradient(np.gradient(dem, cell_size_m, axis=1), cell_size_m, axis=1)
    dyy = np.gradient(np.gradient(dem, cell_size_m, axis=0), cell_size_m, axis=0)
    dxy = np.gradient(np.gradient(dem, cell_size_m, axis=1), cell_size_m, axis=0)
    return dxx * ux**2 + 2 * dxy * ux * uy + dyy * uy**2


def _normalise_0_1(arr: np.ndarray) -> np.ndarray:
    """Min-max normalise array to [0, 1], handling constant arrays."""
    lo, hi = arr.min(), arr.max()
    if hi == lo:
        return np.zeros_like(arr, dtype=np.float64)
    return (arr - lo) / (hi - lo)


def find_pond(
    grid: GridResult,
    flow_acc: np.ndarray,
    boundary_margin: float = 0.1,
) -> PondCandidate:
    """
    Find the best pond location using multi-criteria terrain analysis.

    Parameters
    ----------
    grid : GridResult
        DEM and slope grids from terrain_grid.build_grid().
    flow_acc : np.ndarray
        Flow accumulation grid from catchment.delineate() (or pre-computed).
    boundary_margin : float
        Fraction of grid to exclude from edges (avoids boundary artifacts).

    Returns
    -------
    PondCandidate
        Location and terrain index values at the best site.
    """
    notes: List[str] = []
    dem = grid.dem
    slope = grid.slope
    rows, cols = dem.shape

    # --- Cell area in m² (used in TWI and SPI) ---
    # 1° latitude ≈ 111 km; cell size in metres
    cell_size_m = min(grid.meta.cell_lon, grid.meta.cell_lat) * 111_000
    cell_area_m2 = cell_size_m ** 2

    # --- Compute terrain indices ---
    notes.append("Computing TWI (Beven & Kirkby, 1979)")
    twi = _compute_twi(flow_acc, slope, cell_area_m2)

    notes.append("Computing TPI (Guisan et al., 1999), 11-cell window")
    tpi = _compute_tpi(dem, window=11)

    notes.append("Computing SPI (Moore et al., 1991)")
    spi = _compute_spi(flow_acc, slope, cell_area_m2)

    notes.append("Computing plan + profile curvature (Zevenbergen & Thorne, 1987)")
    plan_curv = _compute_plan_curvature(dem, cell_size_m)
    profile_curv = _compute_profile_curvature(dem, cell_size_m)

    # --- Normalise each index to [0, 1] with desired polarity ---
    # TWI: higher = better (more water accumulation) → normalise directly
    twi_n = _normalise_0_1(twi)

    # TPI: we want NEGATIVE TPI (valleys/depressions) → invert
    tpi_n = _normalise_0_1(-tpi)

    # SPI: want MODERATE values → peak around median → use inverted-distance-to-median scoring
    spi_median = np.median(spi)
    spi_dist = np.abs(spi - spi_median)
    spi_n = _normalise_0_1(-spi_dist)  # highest score at median SPI

    # Plan curvature: positive = convergent = good → normalise directly
    plan_n = _normalise_0_1(plan_curv)

    # Profile curvature: positive = concave = flow decelerates = good → normalise directly
    profile_n = _normalise_0_1(profile_curv)

    # --- Weighted composite score ---
    # Weights based on literature importance for water harvesting siting:
    # TWI is the dominant hydrological signal; TPI screen for depressions;
    # curvature refines within valleys; SPI secondary.
    W_TWI     = 0.35
    W_TPI     = 0.30
    W_PLAN    = 0.15
    W_PROFILE = 0.10
    W_SPI     = 0.10

    score = (
        W_TWI     * twi_n
        + W_TPI   * tpi_n
        + W_PLAN  * plan_n
        + W_PROFILE * profile_n
        + W_SPI   * spi_n
    )

    notes.append(
        f"Suitability weights — TWI:{W_TWI} TPI:{W_TPI} PlanCurv:{W_PLAN} "
        f"ProfCurv:{W_PROFILE} SPI:{W_SPI}"
    )

    # --- Exclude boundary margin to avoid edge artifacts ---
    margin_r = max(1, int(rows * boundary_margin))
    margin_c = max(1, int(cols * boundary_margin))
    inner_score = score.copy()
    inner_score[:margin_r, :] = -np.inf
    inner_score[-margin_r:, :] = -np.inf
    inner_score[:, :margin_c] = -np.inf
    inner_score[:, -margin_c:] = -np.inf

    # --- Pick cell with highest composite score ---
    best_flat = int(np.argmax(inner_score))
    best_row, best_col = np.unravel_index(best_flat, score.shape)

    lon, lat = grid.meta.grid_to_lonlat(best_row, best_col)
    elevation = float(dem[best_row, best_col])

    notes.append(
        f"Best pond site: row={best_row}, col={best_col}, "
        f"lon={lon:.6f}, lat={lat:.6f}, elev={elevation:.2f}m, "
        f"score={score[best_row, best_col]:.4f}"
    )

    return PondCandidate(
        row=best_row,
        col=best_col,
        lon=lon,
        lat=lat,
        elevation_m=elevation,
        twi=float(twi[best_row, best_col]),
        tpi=float(tpi[best_row, best_col]),
        spi=float(spi[best_row, best_col]),
        plan_curvature=float(plan_curv[best_row, best_col]),
        profile_curvature=float(profile_curv[best_row, best_col]),
        suitability_score=float(score[best_row, best_col]),
        notes=notes,
    )
