"""
Pond Locator — Identify and rank candidate pond sites from a DEM and its
flow accumulation.

Responsibility: Scoring and ranking cells ONLY. No KML parsing, no flow
computation (done upstream in catchment.py). Takes the DEM grid and flow
accumulation as inputs, returns a ranked list of candidate sites.

Why only two factors, not a large multi-index composite:
A pond needs two things to be true at the same place: (1) it should
actually receive a meaningful amount of runoff, and (2) it should sit in
ground that is naturally lower than what's around it, so water gathers
there instead of just passing through. We use one index for each:

  - Wetness index (TWI-style): TWI = ln(upslope_area / tan(slope))
    Higher value = more water draining toward that cell, taking the local
    slope into account. Standard formulation from Beven & Kirkby (1979).

  - Depression index (TPI-style): TPI = elevation - mean(neighbourhood)
    Negative value = the cell sits lower than the ground around it (a
    basin/valley floor), which is exactly the shape you want a pond site
    to have. We flip the sign so higher = better, matching the wetness
    index's direction.

  Site score = average of the two, after each is scaled to 0-1 over the
  map. Equal weighting because neither factor alone is sufficient — a
  cell can look "wet" simply from a steep short slope above it, or can
  look like a depression that's actually a dry knoll if slope-based flow
  is weak; requiring both to be reasonably high is a simple, defensible
  filter rather than trying to finely tune five different terms.

Before scoring, cells are excluded for three hard reasons, regardless of
score: (1) the local slope exceeds a feasibility threshold — excavating
and maintaining pond walls on steep ground is not standard practice; (2)
the cell is part of the existing drainage channel/river itself (identified
as unusually high flow accumulation) — a pond needs to be a depression
that runoff feeds into, not a spot sitting inside a flowing watercourse;
and (3) the site's own flood-fill footprint (see compute_pond_footprint)
can't be bounded within a reasonable growth cap — this catches broad,
flat floodplain-like ground that (2) alone can miss, since flow
accumulation on this kind of terrain often fragments into many small,
similarly-sized local dips rather than one obvious channel to exclude by
a simple threshold. A site that floods without bound at a shallow assumed
depth isn't a natural bounded pond — it's part of a much larger flat area
that would need an engineered dam/spillway, so it's rejected outright and
the search continues to the next-best cell instead.

Multiple candidates are then chosen by picking the best remaining cell,
excluding a radius around it, and repeating — so the 2nd and 3rd ranked
candidates are genuinely different regions of the map, not neighbouring
pixels of the same spot.
"""

from dataclasses import dataclass, field
from collections import deque
from typing import List, Tuple

import numpy as np
from scipy.ndimage import uniform_filter, binary_dilation

from modules.terrain_grid import GridResult

# Slopes steeper than this (degrees) are treated as infeasible for pond
# excavation. 15 degrees is a commonly used rule-of-thumb ceiling for
# small earthen pond construction; steeper sites need engineered
# structures that are out of scope here.
MAX_FEASIBLE_SLOPE_DEG = 15.0

# Cells whose flow accumulation is above this percentile of the map are
# treated as part of the existing drainage channel/stream network, not as
# a depression suitable for excavated storage. A pond needs to be fed by
# runoff, not sit directly in a flowing watercourse — this is the same
# reasoning GIS hydrology tools use to separate "stream" cells from
# "hillslope" cells from a flow-accumulation raster (a channel initiation
# threshold), just picked as a percentile of this map rather than a fixed
# contributing-area count, since that generalizes across differently
# sized catchments.
CHANNEL_FLOW_ACC_PERCENTILE = 97.0

# Cells within this many grid cells of a channel cell are also excluded,
# so a candidate isn't picked immediately adjacent to the watercourse due
# to grid coarseness.
CHANNEL_BUFFER_CELLS = 2

# Minimum separation between ranked candidates, as a fraction of the
# smaller grid dimension. Keeps the top-N candidates spatially distinct
# instead of clustering around one local maximum.
MIN_SEPARATION_FRACTION = 0.12

# Assumed water depth used to derive the pond's own footprint (as opposed
# to its catchment). This phase doesn't yet compute a rainfall/runoff-based
# depth (that requires the rainfall API integration planned for a later
# phase), so a fixed, conservative shallow-pond depth is assumed purely to
# answer "what shape and size would the pond itself be" from the terrain
# alone. This should be replaced with a computed depth once runoff-based
# sizing is implemented.
ASSUMED_POND_DEPTH_M = 2.0

# Safety cap on how large the flood-fill footprint is allowed to grow, as a
# fraction of the whole grid. Without a cap, a very flat area could flood
# an unreasonably large, unbounded region for a small assumed depth — if
# the cap is hit, that's itself useful information (the site is on very
# flat ground and would need an engineered spillway/dam, not just a dug
# basin), and is reported back as a note rather than silently truncated.
MAX_FOOTPRINT_FRACTION = 0.05


@dataclass
class PondCandidate:
    """A single ranked candidate pond site."""
    rank: int
    row: int
    col: int
    lon: float
    lat: float
    elevation_m: float
    slope_deg: float

    wetness_index: float      # TWI-style
    depression_index: float   # TPI-style (raw, negative = valley)
    suitability_score: float  # composite 0-1, higher = better

    notes: List[str] = field(default_factory=list)


def _compute_wetness_index(flow_acc: np.ndarray, slope_deg: np.ndarray, cell_area_m2: float) -> np.ndarray:
    """TWI = ln(upslope_area / tan(slope)). Higher = more water convergence."""
    eps = 1e-6
    slope_rad = np.radians(slope_deg)
    upslope_area = (flow_acc + 1).astype(np.float64) * cell_area_m2
    return np.log(upslope_area / (np.tan(slope_rad) + eps))


def _compute_depression_index(dem: np.ndarray, window: int = 11) -> np.ndarray:
    """TPI = elevation - mean(neighbourhood). Negative = local low point."""
    mean_neighbourhood = uniform_filter(dem, size=window, mode="nearest")
    return dem - mean_neighbourhood


def _normalise_0_1(arr: np.ndarray) -> np.ndarray:
    """Min-max normalise to [0, 1], handling constant arrays safely."""
    lo, hi = arr.min(), arr.max()
    if hi == lo:
        return np.zeros_like(arr, dtype=np.float64)
    return (arr - lo) / (hi - lo)


def find_candidates(
    grid: GridResult,
    flow_acc: np.ndarray,
    num_candidates: int = 3,
    boundary_margin: float = 0.1,
) -> List[PondCandidate]:
    """
    Rank the top `num_candidates` distinct pond sites on the map.

    Parameters
    ----------
    grid : GridResult
        DEM and slope grids from terrain_grid.build_grid().
    flow_acc : np.ndarray
        Flow accumulation grid (from catchment.compute_flow()).
    num_candidates : int
        How many ranked candidates to return (default 3).
    boundary_margin : float
        Fraction of the grid to exclude from edges, to avoid picking a
        site right at the boundary of the analysed area.

    Returns
    -------
    List[PondCandidate], best first (rank=1).
    """
    dem = grid.dem
    slope = grid.slope
    rows, cols = dem.shape

    cell_size_m = min(grid.meta.cell_lon, grid.meta.cell_lat) * 111_000
    cell_area_m2 = cell_size_m ** 2

    twi = _compute_wetness_index(flow_acc, slope, cell_area_m2)
    tpi = _compute_depression_index(dem, window=11)

    twi_n = _normalise_0_1(twi)
    tpi_n = _normalise_0_1(-tpi)  # flip sign: valleys should score high

    score = 0.5 * twi_n + 0.5 * tpi_n

    # --- Hard feasibility filter: exclude cells too steep to excavate ---
    infeasible_slope = slope > MAX_FEASIBLE_SLOPE_DEG

    # --- Hard feasibility filter: exclude the existing channel/river network ---
    # Cells with unusually high flow accumulation are part of the drainage
    # network itself (a stream or river channel), not a depression that
    # collects and holds runoff. Siting a "pond" directly on the channel
    # would just be intercepting flowing water, not creating storage, and
    # is a real hydrological mistake we exclude explicitly rather than
    # relying on the score to naturally avoid it.
    channel_threshold = np.percentile(flow_acc, CHANNEL_FLOW_ACC_PERCENTILE)
    channel_cells = flow_acc > channel_threshold
    channel_buffer = binary_dilation(channel_cells, iterations=CHANNEL_BUFFER_CELLS)

    infeasible = infeasible_slope | channel_buffer

    # --- Exclude boundary margin (edge interpolation artefacts) ---
    margin_r = max(1, int(rows * boundary_margin))
    margin_c = max(1, int(cols * boundary_margin))
    edge_mask = np.zeros((rows, cols), dtype=bool)
    edge_mask[:margin_r, :] = True
    edge_mask[-margin_r:, :] = True
    edge_mask[:, :margin_c] = True
    edge_mask[:, -margin_c:] = True

    working_score = score.copy()
    working_score[infeasible | edge_mask] = -np.inf

    n_slope_excluded = int(infeasible_slope.sum())
    n_channel_excluded = int(channel_buffer.sum())
    n_valid = int(np.isfinite(working_score).sum())

    # --- Greedy selection with minimum-separation suppression, and a
    # footprint-boundedness check: a candidate is only accepted if its
    # flood-fill footprint (see compute_pond_footprint) stays within the
    # growth cap. If it doesn't, that means the "depression" this cell
    # sits in isn't actually a contained basin — it's part of a much
    # larger flat area (a floodplain, effectively), and a real pond there
    # would need an engineered dam/spillway rather than being a natural
    # bounded pond. This check is what actually distinguishes a genuinely
    # containable pond site from broad low-lying ground, which the
    # flow-accumulation channel exclusion above cannot reliably do on its
    # own (see PROJECT_PROGRESS.md for why: flow accumulation on this
    # kind of terrain fragments into many small, similar-sized local
    # dips rather than one clean channel to exclude).
    min_sep_cells = max(2, int(min(rows, cols) * MIN_SEPARATION_FRACTION))
    candidates: List[PondCandidate] = []
    n_footprint_rejected = 0

    for rank in range(1, num_candidates + 1):
        accepted = False

        while not accepted:
            if not np.isfinite(working_score).any():
                break

            best_flat = int(np.argmax(working_score))
            best_row, best_col = np.unravel_index(best_flat, working_score.shape)
            best_score = float(working_score[best_row, best_col])

            if best_score == -np.inf:
                break

            footprint_mask, footprint_info = compute_pond_footprint(dem, best_row, best_col)

            if footprint_info["capped"]:
                # This cell can't form a bounded pond — reject it and its
                # immediate neighbourhood, then keep searching for this
                # same rank rather than accepting an unbounded site.
                n_footprint_rejected += 1
                r0, r1 = max(0, best_row - min_sep_cells), min(rows, best_row + min_sep_cells + 1)
                c0, c1 = max(0, best_col - min_sep_cells), min(cols, best_col + min_sep_cells + 1)
                working_score[r0:r1, c0:c1] = -np.inf
                continue

            accepted = True

        if not accepted:
            break

        lon, lat = grid.meta.grid_to_lonlat(best_row, best_col)

        notes = [f"Rank {rank}: row={best_row}, col={best_col}, score={best_score:.4f}"]
        if rank == 1:
            notes.append(
                f"{n_slope_excluded} of {rows*cols} cells excluded as too steep "
                f"(> {MAX_FEASIBLE_SLOPE_DEG}\u00b0)"
            )
            notes.append(
                f"{n_channel_excluded} cells excluded as part of the existing drainage "
                f"channel (flow accumulation above the {CHANNEL_FLOW_ACC_PERCENTILE:.0f}th "
                f"percentile, plus a {CHANNEL_BUFFER_CELLS}-cell buffer) — a pond site "
                f"should be fed by this channel, not sit inside it"
            )
            notes.append(f"{n_valid} cells remained as feasible candidates")
        if n_footprint_rejected:
            notes.append(
                f"{n_footprint_rejected} candidate site(s) so far rejected because their "
                f"flood-fill footprint couldn't be bounded (would need an engineered dam, "
                f"not a natural basin)"
            )

        candidates.append(PondCandidate(
            rank=rank,
            row=int(best_row),
            col=int(best_col),
            lon=lon,
            lat=lat,
            elevation_m=float(dem[best_row, best_col]),
            slope_deg=float(slope[best_row, best_col]),
            wetness_index=float(twi[best_row, best_col]),
            depression_index=float(tpi[best_row, best_col]),
            suitability_score=best_score,
            notes=notes,
        ))

        # Suppress a neighbourhood around this pick so the next one is
        # a genuinely different region of the map.
        r0, r1 = max(0, best_row - min_sep_cells), min(rows, best_row + min_sep_cells + 1)
        c0, c1 = max(0, best_col - min_sep_cells), min(cols, best_col + min_sep_cells + 1)
        working_score[r0:r1, c0:c1] = -np.inf

    return candidates


def compute_pond_footprint(
    dem: np.ndarray,
    pour_row: int,
    pour_col: int,
    assumed_depth_m: float = ASSUMED_POND_DEPTH_M,
) -> Tuple[np.ndarray, dict]:
    """
    Estimate the pond's own footprint (as opposed to its catchment) by
    flood-filling from the candidate point up to a fixed assumed water
    depth above it.

    This answers "what area and shape would the pond itself cover," which
    is a different question from the catchment (which answers "what area
    drains water toward this point"). A pond doesn't fill its whole
    catchment — it only floods the contiguous low ground immediately
    around the site, up to whatever water level a dam/excavation wall of a
    given height would create.

    Method: starting from the pour point, expand to any 8-connected
    neighbour whose elevation is at or below (site elevation +
    assumed_depth_m), stopping once no more neighbours qualify or the
    growth cap is reached. This is a standard flood-fill / "bathtub model"
    approach to reservoir footprint estimation from a DEM.

    Parameters
    ----------
    dem : np.ndarray
        Elevation grid.
    pour_row, pour_col : int
        Grid indices of the candidate pond site.
    assumed_depth_m : float
        Assumed water depth above the site elevation.

    Returns
    -------
    (mask, info) where mask is a boolean grid (True = flooded) and info is
    a dict with 'water_level_m', 'capped' (bool, True if the growth cap
    was hit), and 'assumed_depth_m'.
    """
    rows, cols = dem.shape
    site_elev = float(dem[pour_row, pour_col])
    water_level = site_elev + assumed_depth_m
    max_cells = max(4, int(rows * cols * MAX_FOOTPRINT_FRACTION))

    visited = np.zeros((rows, cols), dtype=bool)
    visited[pour_row, pour_col] = True
    queue = deque([(pour_row, pour_col)])
    count = 1
    capped = False

    neighbours = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

    while queue:
        if count >= max_cells:
            capped = True
            break
        r, c = queue.popleft()
        for dr, dc in neighbours:
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols and not visited[nr, nc]:
                if dem[nr, nc] <= water_level:
                    visited[nr, nc] = True
                    queue.append((nr, nc))
                    count += 1
                    if count >= max_cells:
                        capped = True
                        break

    info = {
        "water_level_m": round(water_level, 2),
        "assumed_depth_m": assumed_depth_m,
        "capped": capped,
    }
    return visited, info
