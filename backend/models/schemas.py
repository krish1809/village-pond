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
