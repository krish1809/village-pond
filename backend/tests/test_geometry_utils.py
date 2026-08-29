"""
Unit tests for geometry_utils module.

Tests:
  - auto_utm_epsg returns valid EPSG code for known locations
  - catchment_polygon builds a non-empty polygon
  - catchment_geometry returns positive area and perimeter
  - contour_total_length returns positive length
  - polygon_to_geojson returns correct GeoJSON structure
"""

import pytest
import numpy as np
from shapely.geometry import Polygon

from modules.geometry_utils import (
    auto_utm_epsg,
    catchment_polygon,
    catchment_geometry,
    contour_total_length,
    polygon_to_geojson,
)
from modules.terrain_grid import GridMeta
from modules.kml_parser import ContourLine


def _small_meta(rows=10, cols=10):
    return GridMeta(
        lon_min=78.0, lon_max=78.1,
        lat_min=18.0, lat_max=18.1,
        cell_lon=0.01, cell_lat=0.01,
        rows=rows, cols=cols,
    )


def _full_mask(rows, cols):
    return np.ones((rows, cols), dtype=bool)


def _center_mask(rows, cols):
    mask = np.zeros((rows, cols), dtype=bool)
    mask[rows//4:3*rows//4, cols//4:3*cols//4] = True
    return mask


# ── UTM EPSG ──────────────────────────────────────────────────────────────────

def test_utm_epsg_india():
    # Sample file is near 81.3°E, 21.26°N — should be zone 44N (EPSG:32644)
    epsg = auto_utm_epsg(81.3, 21.26)
    assert epsg == 32644


def test_utm_epsg_southern_hemisphere():
    epsg = auto_utm_epsg(78.0, -20.0)
    # Should be 327xx for southern hemisphere
    assert 32700 <= epsg < 32800


def test_utm_epsg_reasonable_range():
    for lon in range(-180, 180, 30):
        for lat in [-45, 0, 45]:
            epsg = auto_utm_epsg(float(lon), float(lat))
            assert 32600 <= epsg <= 32760


# ── Catchment polygon ─────────────────────────────────────────────────────────

def test_catchment_polygon_non_empty():
    meta = _small_meta(10, 10)
    mask = _center_mask(10, 10)
    poly = catchment_polygon(mask, meta)
    assert poly.area > 0


def test_catchment_polygon_is_polygon_type():
    from shapely.geometry import Polygon, MultiPolygon
    meta = _small_meta(10, 10)
    mask = _center_mask(10, 10)
    poly = catchment_polygon(mask, meta)
    assert isinstance(poly, (Polygon, MultiPolygon))


def test_catchment_polygon_full_mask_bigger_than_partial():
    meta = _small_meta(10, 10)
    full = catchment_polygon(_full_mask(10, 10), meta)
    partial = catchment_polygon(_center_mask(10, 10), meta)
    assert full.area > partial.area


# ── Catchment geometry ────────────────────────────────────────────────────────

def test_catchment_geometry_positive_area():
    meta = _small_meta(10, 10)
    mask = _center_mask(10, 10)
    poly = catchment_polygon(mask, meta)
    area, perim = catchment_geometry(poly, 78.05, 18.05)
    assert area > 0
    assert perim > 0


def test_catchment_geometry_area_in_sqm():
    """Area should be in square metres, not degrees."""
    meta = _small_meta(10, 10)
    mask = _full_mask(10, 10)
    poly = catchment_polygon(mask, meta)
    area, _ = catchment_geometry(poly, 78.05, 18.05)
    # 0.1° × 0.1° ≈ ~11km × ~11km ≈ ~121 km² = 121_000_000 m²
    assert area > 1_000_000   # definitely more than 1 km²


# ── Contour length ────────────────────────────────────────────────────────────

def test_contour_total_length_positive():
    contours = [
        ContourLine(elevation=100.0, vertices=[(78.0, 18.0), (78.1, 18.0), (78.2, 18.0)]),
        ContourLine(elevation=101.0, vertices=[(78.0, 18.1), (78.1, 18.1)]),
    ]
    length = contour_total_length(contours, 78.1, 18.05)
    assert length > 0


def test_contour_length_single_point_skipped():
    """Single-point 'lines' should be skipped (length = 0 contribution)."""
    contours = [
        ContourLine(elevation=100.0, vertices=[(78.0, 18.0)]),  # only 1 vertex
        ContourLine(elevation=101.0, vertices=[(78.0, 18.1), (78.1, 18.1)]),
    ]
    length = contour_total_length(contours, 78.05, 18.05)
    assert length > 0  # should still count the valid one


# ── GeoJSON ───────────────────────────────────────────────────────────────────

def test_polygon_to_geojson_structure():
    poly = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    geojson = polygon_to_geojson(poly)
    assert geojson["type"] == "Polygon"
    assert "coordinates" in geojson
    assert isinstance(geojson["coordinates"], list)
    assert len(geojson["coordinates"]) >= 1


def test_polygon_to_geojson_coordinate_format():
    """Each coordinate should be [lon, lat] (list of 2 numbers)."""
    poly = Polygon([(78.0, 18.0), (79.0, 18.0), (79.0, 19.0), (78.0, 19.0)])
    geojson = polygon_to_geojson(poly)
    exterior = geojson["coordinates"][0]
    for pt in exterior:
        assert len(pt) == 2
        assert isinstance(pt[0], float)
        assert isinstance(pt[1], float)
