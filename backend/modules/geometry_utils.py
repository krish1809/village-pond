"""
Geometry Utilities — Accurate metric geometry for contour lines, catchment
polygons, and spatial projections.

Responsibility: Geometry calculations ONLY. No parsing, no flow computation,
no pond scoring. All metric results use UTM projection (not raw lat/lon degrees).

Functions:
  - auto_utm_epsg     : Detect the correct UTM CRS EPSG for a lon/lat centroid
  - catchment_polygon : Convert a boolean catchment mask to a Shapely polygon
                        (fast: uses scipy.ndimage boundary tracing, not per-cell union)
  - catchment_geometry: Compute area + perimeter of catchment in metres
  - contour_length    : Total length of all contour lines in metres
  - polygon_to_geojson: Convert Shapely polygon to GeoJSON dict

Why UTM projection?
  Computing area or distance in raw degrees is incorrect — a degree of longitude
  shrinks toward the poles. UTM (Universal Transverse Mercator) gives near-
  true area/distance for regions up to ~6° wide, which covers any single
  village-scale map comfortably.
"""

from typing import Dict, List, Tuple

import numpy as np
from scipy.ndimage import binary_fill_holes, binary_dilation
from pyproj import Transformer
from shapely.geometry import Polygon, MultiPolygon, mapping
from shapely.ops import unary_union

from modules.kml_parser import ContourLine
from modules.terrain_grid import GridMeta


def auto_utm_epsg(lon: float, lat: float) -> int:
    """
    Return the EPSG code of the UTM zone appropriate for a given (lon, lat).

    Formula: zone = ceil((lon + 180) / 6), band = N or S.
    """
    zone = int((lon + 180) / 6) + 1
    hemisphere = "6" if lat >= 0 else "7"  # 326xx = N, 327xx = S
    return int(f"32{hemisphere}{zone:02d}")


def _make_transformer(lon: float, lat: float) -> Transformer:
    """Create a WGS84 → UTM transformer for the given location."""
    epsg = auto_utm_epsg(lon, lat)
    return Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)


def catchment_polygon(
    mask: np.ndarray,
    meta: GridMeta,
):
    """
    Convert a boolean catchment/footprint mask to an exact Shapely geometry
    by unioning each True cell's own rectangle — not an approximation.

    An earlier version of this function used a convex hull of cell centres,
    buffered outward, as a faster approximation. That was found (by directly
    comparing its output against a raw cell-count area) to overestimate area
    by up to ~78% for irregular or scattered catchment shapes, since a convex
    hull fills in any concave or disconnected parts of the real shape. That's
    not an acceptable margin of error for a reported area, so this function
    now builds the exact union of the raster cells instead: correct by
    construction, since it's built from the same cells the mask contains,
    not the space around them.

    Trade-off: the resulting polygon's edges follow the grid's cell
    boundaries exactly, so its perimeter has a "staircase" shape rather than
    a smooth line — perimeter is therefore somewhat longer than a smoothed
    real-world boundary would be. This is a well-known, expected property of
    converting a raster grid to a vector shape (not a flaw specific to this
    project), and area is unaffected by it.

    Parameters
    ----------
    mask : np.ndarray (bool)
        Boolean grid, True = cell is part of the shape.
    meta : GridMeta
        Spatial metadata from terrain_grid.

    Returns
    -------
    Shapely Polygon or MultiPolygon (MultiPolygon if the True cells form
    more than one disconnected cluster).
    """
    from shapely.geometry import box

    cell_lon = meta.cell_lon
    cell_lat = meta.cell_lat

    rows_idx, cols_idx = np.where(mask)

    if len(rows_idx) == 0:
        # Fallback: 1-cell polygon at grid centre (mask was empty)
        lon_c, lat_c = meta.grid_to_lonlat(meta.rows // 2, meta.cols // 2)
        return box(lon_c - cell_lon/2, lat_c - cell_lat/2, lon_c + cell_lon/2, lat_c + cell_lat/2)

    lons = meta.lon_min + cols_idx * cell_lon
    lats = meta.lat_min + rows_idx * cell_lat

    squares = [
        box(lon, lat, lon + cell_lon, lat + cell_lat)
        for lon, lat in zip(lons, lats)
    ]

    merged = unary_union(squares)
    return merged


def catchment_geometry(
    poly: Polygon,
    lon_centroid: float,
    lat_centroid: float,
) -> Tuple[float, float]:
    """
    Compute catchment area (m²) and perimeter (m) in UTM projection.

    Parameters
    ----------
    poly : Shapely Polygon
        Catchment boundary polygon in WGS84 (lon/lat).
    lon_centroid, lat_centroid : float
        Representative point for selecting the UTM zone.

    Returns
    -------
    (area_sq_m, perimeter_m) : tuple of floats
    """
    transformer = _make_transformer(lon_centroid, lat_centroid)

    # Project polygon vertices to UTM
    def project_coords(coords):
        xs = [pt[0] for pt in coords]
        ys = [pt[1] for pt in coords]
        ux, uy = transformer.transform(xs, ys)
        return list(zip(ux, uy))

    if isinstance(poly, MultiPolygon):
        # Work with the largest sub-polygon
        poly = max(poly.geoms, key=lambda p: p.area)

    exterior_utm = project_coords(list(poly.exterior.coords))
    holes_utm = [project_coords(list(hole.coords)) for hole in poly.interiors]

    utm_poly = Polygon(exterior_utm, holes_utm)
    return utm_poly.area, utm_poly.length


def contour_total_length(
    contour_lines: List[ContourLine],
    lon_centroid: float,
    lat_centroid: float,
) -> float:
    """
    Compute total length of all contour lines in metres.

    Each contour is a polyline; length = sum of consecutive vertex distances.
    Uses UTM projection for accuracy.

    Parameters
    ----------
    contour_lines : list of ContourLine
        Parsed contour features.
    lon_centroid, lat_centroid : float
        Representative point for UTM zone selection.

    Returns
    -------
    Total length in metres.
    """
    transformer = _make_transformer(lon_centroid, lat_centroid)
    total = 0.0

    for cl in contour_lines:
        if len(cl.vertices) < 2:
            continue
        lons = [v[0] for v in cl.vertices]
        lats = [v[1] for v in cl.vertices]
        ux, uy = transformer.transform(lons, lats)
        ux = np.array(ux)
        uy = np.array(uy)
        dists = np.sqrt(np.diff(ux)**2 + np.diff(uy)**2)
        total += dists.sum()

    return float(total)


def polygon_to_geojson(poly) -> Dict:
    """
    Convert a Shapely Polygon or MultiPolygon to a GeoJSON geometry dict.

    Returns the exterior ring as a simple Polygon for the catchment case.
    """
    if isinstance(poly, MultiPolygon):
        # Use the largest sub-polygon
        poly = max(poly.geoms, key=lambda p: p.area)

    # GeoJSON coordinates: list of rings, each ring is list of [lon, lat]
    exterior = [[lon, lat] for lon, lat in poly.exterior.coords]
    holes = [[[lon, lat] for lon, lat in hole.coords] for hole in poly.interiors]
    coordinates = [exterior] + holes

    return {"type": "Polygon", "coordinates": coordinates}
