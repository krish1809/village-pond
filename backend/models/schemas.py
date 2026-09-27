"""
Pydantic response models for the /analyzeContour endpoint.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class PondLocation(BaseModel):
    """A candidate pond site."""

    latitude: float = Field(..., description="Latitude of the site (WGS84)")
    longitude: float = Field(..., description="Longitude of the site (WGS84)")
    elevation_m: float = Field(..., description="Estimated elevation at the site (metres)")
    slope_deg: float = Field(..., description="Local ground slope at the site (degrees)")


class GeoJSONPolygon(BaseModel):
    """GeoJSON Polygon geometry."""

    type: str = Field(default="Polygon", description="GeoJSON geometry type")
    coordinates: List[List[List[float]]] = Field(
        ..., description="Polygon coordinates as [[[lon, lat], ...]]"
    )


class CatchmentInfo(BaseModel):
    """Delineated catchment (watershed) draining into a candidate site."""

    area_sq_m: float = Field(..., description="Catchment area in square metres")
    perimeter_m: float = Field(..., description="Catchment perimeter in metres")
    boundary: GeoJSONPolygon = Field(..., description="Catchment boundary as a GeoJSON Polygon")


class SuitabilityFactors(BaseModel):
    """The two factors behind a candidate's suitability score."""

    wetness_index: float = Field(
        ..., description="How much runoff drains toward this site, relative to the rest of the map (higher = more)"
    )
    depression_index: float = Field(
        ..., description="How much lower this site sits than the ground around it (negative = below surroundings)"
    )
    suitability_score: float = Field(
        ..., description="Combined score (0-1) averaging the two factors above"
    )


class PondFootprint(BaseModel):
    """The pond's own estimated shape and size, distinct from its catchment.

    Derived by flood-filling from the candidate point up to an assumed
    water depth (a fixed placeholder depth for this phase — a later phase
    will replace this with a depth computed from rainfall/runoff data).
    This answers "what area and shape will the pond itself cover," which
    is different from the catchment (the area draining water toward it).
    """

    area_sq_m: float = Field(..., description="Estimated surface area of the pond itself, in square metres")
    perimeter_m: float = Field(..., description="Estimated shoreline perimeter of the pond, in metres")
    boundary: GeoJSONPolygon = Field(..., description="Estimated pond footprint as a GeoJSON Polygon")
    assumed_depth_m: float = Field(..., description="Assumed water depth used to derive this footprint")
    water_level_m: float = Field(..., description="Assumed water surface elevation (site elevation + assumed depth)")
    capped: bool = Field(
        ..., description="True if the flood-fill hit its safety growth limit — indicates very flat "
                          "terrain that would need an engineered dam/spillway, not just a dug basin"
    )


class PondCandidateResult(BaseModel):
    """One ranked candidate pond site with its footprint, catchment, and scoring."""

    rank: int = Field(..., description="1 = best candidate, 2 = second best, etc.")
    location: PondLocation
    pond_footprint: PondFootprint
    catchment: CatchmentInfo
    suitability: SuitabilityFactors


class ContourSummary(BaseModel):
    """Summary statistics of the parsed contour data."""

    num_contour_lines: int
    elevation_min_m: float
    elevation_max_m: float
    estimated_contour_interval_m: float


class AnalysisMetadata(BaseModel):
    """Processing metadata and notes."""

    source_filename: str
    processing_notes: List[str] = Field(default_factory=list)
    grid_resolution: Optional[str] = None
    total_processing_time_s: Optional[float] = None


class AnalyzeContourResponse(BaseModel):
    """
    Complete response from the /analyzeContour endpoint.

    Returns a ranked list of candidate pond sites (best first), each with
    its own catchment boundary and suitability scoring, plus a summary of
    the parsed contour data.
    """

    candidates: List[PondCandidateResult] = Field(
        ..., description="Ranked candidate pond sites, best first"
    )
    contour_summary: ContourSummary
    metadata: AnalysisMetadata

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "candidates": [
                        {
                            "rank": 1,
                            "location": {
                                "latitude": 21.2596,
                                "longitude": 81.2999,
                                "elevation_m": 279.27,
                                "slope_deg": 2.1,
                            },
                            "catchment": {
                                "area_sq_m": 34621.3,
                                "perimeter_m": 772.3,
                                "boundary": {
                                    "type": "Polygon",
                                    "coordinates": [[[81.30, 21.259], [81.301, 21.259], [81.301, 21.260], [81.30, 21.260], [81.30, 21.259]]],
                                },
                            },
                            "suitability": {
                                "wetness_index": 13.87,
                                "depression_index": -6.25,
                                "suitability_score": 0.73,
                            },
                        }
                    ],
                    "contour_summary": {
                        "num_contour_lines": 1355,
                        "elevation_min_m": 267.0,
                        "elevation_max_m": 298.0,
                        "estimated_contour_interval_m": 1.0,
                    },
                    "metadata": {
                        "source_filename": "contours_1m.kml",
                        "processing_notes": ["Parsed 1355 contour lines"],
                        "grid_resolution": "114x150",
                        "total_processing_time_s": 0.4,
                    },
                }
            ]
        }
    }


# ---------------------------------------------------------------------------
# Phase 3 — area-based analysis (select a region on a map, fetch a DEM for it,
# and report suggested pond, catchment, and expected water volume).
# Defined after the base models above so all referenced types already exist.
# ---------------------------------------------------------------------------


class WaterVolume(BaseModel):
    """Estimated water volumes for a candidate site.

    Two independent limits are reported plus their minimum: the catchment can
    only deliver so much runoff per year, and the basin can only hold so much —
    the collectable volume is bounded by whichever is smaller.
    """

    annual_runoff_m3: float = Field(
        ..., description="Water the catchment delivers per year (C x rainfall x catchment area)"
    )
    storage_capacity_m3: float = Field(
        ..., description="Volume the pond basin can physically hold below the assumed water level"
    )
    expected_collectable_m3: float = Field(
        ..., description="Realistically collectable volume = min(annual runoff, storage capacity)"
    )
    limiting_factor: str = Field(
        ..., description="Which limit binds: 'catchment_runoff' or 'basin_capacity'"
    )
    runoff_coefficient: float = Field(..., description="Runoff coefficient C used in the estimate")
    annual_rainfall_mm: float = Field(..., description="Mean annual rainfall used, in millimetres")


class RainfallInfo(BaseModel):
    """Rainfall context used for the volume estimate."""

    annual_rainfall_mm: float = Field(..., description="Mean annual rainfall (mm)")
    source: str = Field(..., description="'open-meteo' (live) or 'fallback' (offline default)")
    years_averaged: int = Field(..., description="Number of years averaged (0 if fallback)")
    monthly_climatology_mm: List[float] = Field(
        default_factory=list, description="Mean rainfall per month Jan..Dec (mm), for charting"
    )


class AreaSummary(BaseModel):
    """Summary of the selected area and the DEM built for it."""

    bbox: List[float] = Field(..., description="Selected bounding box [min_lon, min_lat, max_lon, max_lat]")
    center_lat: float
    center_lon: float
    grid_resolution: str = Field(..., description="DEM grid shape, e.g. '50x40'")
    elevation_min_m: float
    elevation_max_m: float
    dem_source: str = Field(
        default="", description="Where the elevation model came from: 'contour map (offline)' or 'Open-Meteo elevation API'"
    )


class AreaCandidateResult(BaseModel):
    """One ranked candidate for the area-based analysis: everything the contour
    result carries, plus the water-volume estimate."""

    rank: int = Field(..., description="1 = best candidate, 2 = second best, etc.")
    location: PondLocation
    pond_footprint: PondFootprint
    catchment: CatchmentInfo
    suitability: SuitabilityFactors
    water_volume: WaterVolume


class AnalyzeAreaRequest(BaseModel):
    """Request body for /analyzeArea."""

    bbox: List[float] = Field(
        ...,
        description="Bounding box of the selected area: [min_lon, min_lat, max_lon, max_lat]",
        min_length=4,
        max_length=4,
    )
    num_candidates: int = Field(
        default=3, ge=1, le=10, description="How many ranked candidate sites to return."
    )
    runoff_coefficient: Optional[float] = Field(
        default=None, gt=0, le=1,
        description="Fraction of rainfall becoming runoff (default ~0.3 if omitted).",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{"bbox": [81.28, 21.24, 81.31, 21.26], "num_candidates": 3}]
        }
    }


class ContourFeature(BaseModel):
    """One contour polyline generated from the DEM, for display on the map."""

    elevation: float = Field(..., description="Elevation of this contour line (metres)")
    coordinates: List[List[float]] = Field(..., description="Polyline as [[lon, lat], ...]")


class AnalyzeAreaResponse(BaseModel):
    """Complete response from the /analyzeArea endpoint."""

    candidates: List[AreaCandidateResult] = Field(
        ..., description="Ranked candidate pond sites, best first"
    )
    contours: List[ContourFeature] = Field(
        default_factory=list, description="Elevation contour lines generated from the DEM, for map display"
    )
    rainfall: RainfallInfo
    area_summary: AreaSummary
    metadata: AnalysisMetadata
