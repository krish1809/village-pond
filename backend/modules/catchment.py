"""
Catchment Delineation — D8 flow direction, flow accumulation, and watershed
delineation from a DEM grid.

Responsibility: Hydrology computations ONLY on the DEM.
No KML parsing, no geometry area calculations (those go in geometry_utils).

Algorithms:
  1. Priority-Flood sink filling (Barnes et al., 2014) — O(n log n) optimal.
     Avoids the slow iterative naive fill. Uses a min-heap to process cells
     in elevation order from the boundary inward.

  2. D8 flow direction (O'Callaghan & Mark, 1984) — each cell drains to the
     steepest-descent neighbour out of 8. Simple, hydrologically interpretable,
     and fully explainable in review.

  3. Flow accumulation — count of upstream cells for every cell, computed via
     topological sort of the flow-direction DAG.

  4. Watershed delineation — BFS/DFS from a pour point reverse-tracing the
     flow-direction graph to find all contributing cells.

References:
  Barnes, R., Lehman, C., Mulla, D. (2014). Priority-flood: An optimal
      depression-filling and watershed-labeling algorithm for digital elevation
      models. Computers & Geosciences, 62, 117-127.
  O'Callaghan, J.F., Mark, D.M. (1984). The extraction of drainage networks
      from digital elevation data. Computer Vision, Graphics and Image
      Processing, 28(3), 323-344.
"""

import heapq
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from modules.terrain_grid import GridResult, GridMeta


# D8 direction offsets: (row_delta, col_delta) for each of 8 neighbours
# Ordered: E, SE, S, SW, W, NW, N, NE
_D8_OFFSETS = [
    (0, 1), (1, 1), (1, 0), (1, -1),
    (0, -1), (-1, -1), (-1, 0), (-1, 1),
]
# Distance weights for diagonal vs cardinal (for slope-based steepest descent)
_D8_DIST = [1.0, 1.4142, 1.0, 1.4142, 1.0, 1.4142, 1.0, 1.4142]

NOFLOW = -1  # sentinel: no downslope neighbour


@dataclass
class CatchmentResult:
    """Output of watershed delineation."""
    flow_dir: np.ndarray      # shape (rows, cols), direction index 0-7 or NOFLOW
    flow_acc: np.ndarray      # shape (rows, cols), upstream cell count
    mask: np.ndarray          # shape (rows, cols), bool — True = in catchment
    pour_point: Tuple[int, int]  # (row, col) used as the outlet
    notes: List[str]


def _priority_flood_fill(dem: np.ndarray) -> np.ndarray:
    """
    Fill depressions using the Priority-Flood algorithm (Barnes et al., 2014).

    After filling, applies a tiny epsilon gradient across flat regions
    (Martz & Garbrecht, 1999) so that D8 can always determine a downslope
    direction — without this, flat-filled areas produce NOFLOW cells that
    fragment the watershed.

    Reference: Martz, L.W., Garbrecht, J. (1999). An outlet breaching algorithm
        for the treatment of closed depressions in a raster DEM. Computers &
        Geosciences, 25(7), 835-844.

    Returns a new filled DEM (same shape as input).
    """
    rows, cols = dem.shape
    filled = dem.copy().astype(np.float64)
    closed = np.zeros((rows, cols), dtype=bool)

    # Seed the heap with all boundary cells
    heap = []
    for r in range(rows):
        for c in [0, cols - 1]:
            if not closed[r, c]:
                heapq.heappush(heap, (filled[r, c], r, c))
                closed[r, c] = True
    for c in range(cols):
        for r in [0, rows - 1]:
            if not closed[r, c]:
                heapq.heappush(heap, (filled[r, c], r, c))
                closed[r, c] = True

    while heap:
        elev, r, c = heapq.heappop(heap)
        for dr, dc in _D8_OFFSETS:
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols and not closed[nr, nc]:
                filled[nr, nc] = max(filled[nr, nc], elev)
                closed[nr, nc] = True
                heapq.heappush(heap, (filled[nr, nc], nr, nc))

    # --- Epsilon gradient on flat areas (Martz & Garbrecht, 1999) ---
    # Vectorised check: flat cell = all 8 neighbours have elevation >= cell
    eps = 1e-5
    padded = np.pad(filled, 1, mode="edge")
    min_neighbor = np.minimum.reduce([
        padded[:-2, 1:-1], padded[2:, 1:-1], padded[1:-1, :-2], padded[1:-1, 2:],
        padded[:-2, :-2], padded[:-2, 2:], padded[2:, :-2], padded[2:, 2:]
    ])
    flat = (min_neighbor >= filled)

    if flat.any():
        # Distance to nearest edge (approximate)
        dist_from_edge = np.minimum(
            np.minimum(np.arange(rows)[:, None], rows - 1 - np.arange(rows)[:, None]),
            np.minimum(np.arange(cols)[None, :], cols - 1 - np.arange(cols)[None, :])
        )
        filled[flat] -= dist_from_edge[flat] * eps

    return filled


def _compute_flow_direction(dem: np.ndarray) -> np.ndarray:
    """
    Compute D8 flow direction for each cell — vectorised with numpy.

    For each cell, direction = index of the steepest-descent neighbour
    among 8 directions (E, SE, S, SW, W, NW, N, NE).
    Returns direction index (0-7) or NOFLOW (-1) for local minima.
    """
    rows, cols = dem.shape
    # slope_layers[d] = slope toward direction d for every cell
    slope_layers = np.full((8, rows, cols), -np.inf)

    for d, ((dr, dc), dist) in enumerate(zip(_D8_OFFSETS, _D8_DIST)):
        # Compute source and target slices
        r_src = slice(max(0, -dr), rows + min(0, -dr))
        c_src = slice(max(0, -dc), cols + min(0, -dc))
        r_dst = slice(max(0, dr), rows + min(0, dr))
        c_dst = slice(max(0, dc), cols + min(0, dc))
        drop = dem[r_src, c_src] - dem[r_dst, c_dst]
        slope_layers[d, r_src, c_src] = drop / dist

    best_dir = np.argmax(slope_layers, axis=0).astype(np.int8)
    best_slope = slope_layers[best_dir, np.arange(rows)[:, None], np.arange(cols)[None, :]]
    # Cells with no downslope neighbour get NOFLOW
    best_dir[best_slope <= 0] = NOFLOW

    return best_dir


def _compute_flow_accumulation(flow_dir: np.ndarray) -> np.ndarray:
    """
    Compute flow accumulation (upslope cell count) via topological sort.

    Uses Kahn's algorithm on the flow-direction DAG — processes cells with
    no incoming flow first, then propagates counts downstream. O(n).
    """
    rows, cols = flow_dir.shape
    # Count incoming edges for each cell
    in_degree = np.zeros((rows, cols), dtype=np.int32)
    for r in range(rows):
        for c in range(cols):
            d = flow_dir[r, c]
            if d == NOFLOW:
                continue
            dr, dc = _D8_OFFSETS[d]
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols:
                in_degree[nr, nc] += 1

    # Queue cells with no upstream (sources)
    queue = []
    for r in range(rows):
        for c in range(cols):
            if in_degree[r, c] == 0:
                queue.append((r, c))

    flow_acc = np.zeros((rows, cols), dtype=np.int32)

    while queue:
        next_queue = []
        for r, c in queue:
            d = flow_dir[r, c]
            if d == NOFLOW:
                continue
            dr, dc = _D8_OFFSETS[d]
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols:
                flow_acc[nr, nc] += flow_acc[r, c] + 1
                in_degree[nr, nc] -= 1
                if in_degree[nr, nc] == 0:
                    next_queue.append((nr, nc))
        queue = next_queue

    return flow_acc


def _delineate_watershed(
    flow_dir: np.ndarray, pour_row: int, pour_col: int
) -> np.ndarray:
    """
    Delineate the watershed (catchment) draining to a given pour point.

    Uses BFS tracing the flow-direction graph in reverse — finds all cells
    whose flow path eventually reaches (pour_row, pour_col).

    Returns a boolean mask (True = in catchment).
    """
    rows, cols = flow_dir.shape

    # Build reverse adjacency: for each cell, which cells flow INTO it?
    # We do this on the fly during BFS to avoid memory overhead
    mask = np.zeros((rows, cols), dtype=bool)
    mask[pour_row, pour_col] = True

    # BFS queue
    queue = [(pour_row, pour_col)]
    visited = set(queue)

    while queue:
        next_queue = []
        for r, c in queue:
            # Check all 8 neighbours: does any of them flow into (r, c)?
            for d, (dr, dc) in enumerate(_D8_OFFSETS):
                nr, nc = r - dr, c - dc   # reverse direction
                if 0 <= nr < rows and 0 <= nc < cols and (nr, nc) not in visited:
                    if flow_dir[nr, nc] == d:   # neighbour flows toward (r, c)
                        mask[nr, nc] = True
                        visited.add((nr, nc))
                        next_queue.append((nr, nc))
        queue = next_queue

    return mask


def delineate(
    grid: GridResult,
    pour_row: int,
    pour_col: int,
) -> CatchmentResult:
    """
    Full catchment delineation pipeline for a given pour point.

    Steps:
      1. Priority-Flood sink filling
      2. D8 flow direction
      3. Flow accumulation (topological sort)
      4. Watershed delineation (reverse BFS from pour point)

    Parameters
    ----------
    grid : GridResult
        DEM grid from terrain_grid.build_grid().
    pour_row, pour_col : int
        Grid indices of the outlet/pour point (from pond_locator).

    Returns
    -------
    CatchmentResult
    """
    notes: List[str] = []
    dem = grid.dem

    # 1. Fill depressions
    notes.append("Filling depressions: Priority-Flood (Barnes et al., 2014)")
    filled_dem = _priority_flood_fill(dem)
    depressions_filled = int(np.sum(filled_dem > dem))
    notes.append(f"Filled {depressions_filled} depressed cells")

    # 2. D8 flow direction
    notes.append("Computing D8 flow directions (O'Callaghan & Mark, 1984)")
    flow_dir = _compute_flow_direction(filled_dem)

    # 3. Flow accumulation
    notes.append("Computing flow accumulation via topological sort")
    flow_acc = _compute_flow_accumulation(flow_dir)
    notes.append(f"Max flow accumulation: {flow_acc.max()} cells")

    # 4. Watershed delineation
    notes.append(f"Delineating watershed from pour point ({pour_row}, {pour_col})")
    mask = _delineate_watershed(flow_dir, pour_row, pour_col)
    catchment_cells = int(mask.sum())
    notes.append(f"Catchment covers {catchment_cells} grid cells")

    return CatchmentResult(
        flow_dir=flow_dir,
        flow_acc=flow_acc,
        mask=mask,
        pour_point=(pour_row, pour_col),
        notes=notes,
    )
