"""
Terrain Grid — Build a regular DEM (Digital Elevation Model) grid from
scattered contour vertices via spatial interpolation.

Responsibility: ONLY terrain grid construction. No flow/catchment logic,
no pond picking, no geometry area calculations.

Algorithm:
  1. Flatten all contour vertices + their elevations into point clouds
  2. Determine bounding box and create a regular grid of (grid_rows × grid_cols)
  3. Interpolate using scipy.interpolate.griddata (linear, then nearest-neighbour
     fill for any remaining NaN cells at the edges)
  4. Compute local slope at every cell (used by downstream modules)

Returns a GridResult dataclass with:
  - dem      : 2D numpy array of elevations (rows × cols)
  - slope    : 2D numpy array of slope in degrees
  - lon_grid : 2D array of longitude at each cell centre
  - lat_grid : 2D array of latitude at each cell centre
  - meta     : GridMeta (bbox, cell size, shape)
"""

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np
from scipy.interpolate import griddata
from scipy.ndimage import uniform_filter

from modules.kml_parser import ContourLine


@dataclass
class GridMeta:
    """Spatial metadata for the DEM grid."""
    lon_min: float
    lon_max: float
    lat_min: float
    lat_max: float
    cell_lon: float   # longitudinal cell size (degrees)
    cell_lat: float   # latitudinal cell size (degrees)
    rows: int
    cols: int

    def grid_to_lonlat(self, row: int, col: int) -> Tuple[float, float]:
        """Convert grid index to (longitude, latitude) of cell centre."""
        lon = self.lon_min + (col + 0.5) * self.cell_lon
        lat = self.lat_min + (row + 0.5) * self.cell_lat
        return lon, lat

    def lonlat_to_grid(self, lon: float, lat: float) -> Tuple[int, int]:
        """Convert (longitude, latitude) to nearest grid (row, col)."""
        col = int((lon - self.lon_min) / self.cell_lon)
        row = int((lat - self.lat_min) / self.cell_lat)
        col = max(0, min(self.cols - 1, col))
        row = max(0, min(self.rows - 1, row))
        return row, col


@dataclass
class GridResult:
    """Output of terrain grid construction."""
    dem: np.ndarray        # shape (rows, cols), elevation in metres
    slope: np.ndarray      # shape (rows, cols), slope in degrees
    lon_grid: np.ndarray   # shape (rows, cols), longitude of each cell
    lat_grid: np.ndarray   # shape (rows, cols), latitude of each cell
    meta: GridMeta
    notes: List[str]


def _compute_slope(dem: np.ndarray, cell_size_m: float) -> np.ndarray:
    """
    Compute slope in degrees using the 3×3 Horn (1981) algorithm.
    Widely used in GIS/hydrology as the standard finite-difference gradient.

    Reference: Horn, B.K.P. (1981). Hill shading and the reflectance map.
               Proceedings of the IEEE, 69(1), 14-47.
    """
    # Use numpy gradient for clean implementation
    dy, dx = np.gradient(dem, cell_size_m, cell_size_m)
    slope_rad = np.arctan(np.sqrt(dx**2 + dy**2))
    return np.degrees(slope_rad)


def build_grid(
    contour_lines: List[ContourLine],
    grid_size: int = 200,
    margin_factor: float = 0.02,
) -> GridResult:
    """
    Build a regular DEM grid from contour line vertices.

    Parameters
    ----------
    contour_lines : list of ContourLine
        Parsed contour features with elevation and (lon, lat) vertices.
    grid_size : int
        Target number of cells along the longer axis. The other axis is
        scaled to maintain cell aspect ratio. Default 200.
    margin_factor : float
        Fractional padding around the bounding box (avoids edge NaN artifacts).

    Returns
    -------
    GridResult
        DEM grid, slope grid, lon/lat grids, and spatial metadata.
    """
    notes: List[str] = []

    # --- Step 1: Collect all (lon, lat, elev) sample points ---
    # Smart subsampling: target ~6,000 total points max for instant Delaunay triangulation
    target_pts_per_line = max(3, 6000 // max(1, len(contour_lines)))
    lons, lats, elevs = [], [], []
    for cl in contour_lines:
        verts = cl.vertices
        n = max(1, len(verts) // target_pts_per_line)
        for v in verts[::n]:
            lons.append(v[0])
            lats.append(v[1])
            elevs.append(cl.elevation)

    lons = np.array(lons, dtype=np.float64)
    lats = np.array(lats, dtype=np.float64)
    elevs = np.array(elevs, dtype=np.float64)

    notes.append(f"Using {len(lons)} sample points from {len(contour_lines)} contour lines")

    # --- Step 2: Bounding box with margin ---
    lon_min, lon_max = lons.min(), lons.max()
    lat_min, lat_max = lats.min(), lats.max()
    lon_span = lon_max - lon_min
    lat_span = lat_max - lat_min

    margin_lon = lon_span * margin_factor
    margin_lat = lat_span * margin_factor
    lon_min -= margin_lon
    lon_max += margin_lon
    lat_min -= margin_lat
    lat_max += margin_lat

    # --- Step 3: Determine grid shape preserving aspect ratio ---
    aspect = lat_span / lon_span if lon_span > 0 else 1.0
    if aspect >= 1.0:
        rows = grid_size
        cols = max(10, int(grid_size / aspect))
    else:
        cols = grid_size
        rows = max(10, int(grid_size * aspect))

    cell_lon = (lon_max - lon_min) / cols
    cell_lat = (lat_max - lat_min) / rows

    meta = GridMeta(
        lon_min=lon_min, lon_max=lon_max,
        lat_min=lat_min, lat_max=lat_max,
        cell_lon=cell_lon, cell_lat=cell_lat,
        rows=rows, cols=cols,
    )

    notes.append(f"DEM grid: {rows}×{cols} cells, cell size ≈ {cell_lon*111000:.1f}m × {cell_lat*111000:.1f}m")

    # --- Step 4: Create regular grid of cell centres ---
    col_centres = lon_min + (np.arange(cols) + 0.5) * cell_lon
    row_centres = lat_min + (np.arange(rows) + 0.5) * cell_lat
    lon_grid, lat_grid = np.meshgrid(col_centres, row_centres)

    # --- Step 5: Interpolate elevation onto grid ---
    # Linear interpolation first (respects contour structure)
    points = np.column_stack([lons, lats])
    grid_pts = np.column_stack([lon_grid.ravel(), lat_grid.ravel()])

    dem_linear = griddata(points, elevs, grid_pts, method="linear")
    dem_grid = dem_linear.reshape(rows, cols)

    # Fill NaN edges with nearest-neighbour (guaranteed no NaN)
    nan_mask = np.isnan(dem_grid)
    if nan_mask.any():
        dem_nearest = griddata(points, elevs, grid_pts, method="nearest")
        dem_nearest = dem_nearest.reshape(rows, cols)
        dem_grid[nan_mask] = dem_nearest[nan_mask]
        notes.append(f"Filled {nan_mask.sum()} edge cells with nearest-neighbour interpolation")

    # Light smoothing to reduce interpolation noise (σ=1 cell, 3×3 window)
    dem_grid = uniform_filter(dem_grid, size=3, mode="nearest")

    # --- Step 6: Compute slope ---
    # Approximate cell size in metres (1° lat ≈ 111 km)
    cell_m = min(cell_lon, cell_lat) * 111_000
    slope_grid = _compute_slope(dem_grid, cell_m)

    notes.append(f"Slope range: {slope_grid.min():.2f}° – {slope_grid.max():.2f}°")

    return GridResult(
        dem=dem_grid,
        slope=slope_grid,
        lon_grid=lon_grid,
        lat_grid=lat_grid,
        meta=meta,
        notes=notes,
    )
