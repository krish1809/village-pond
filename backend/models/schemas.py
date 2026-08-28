"""
Pydantic response models for the /analyzeContour endpoint.

Matches the JSON schema specified in PHASE2_SPEC_contour_catchment.md,
with additional terrain-analysis fields for novelty.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class PondLocation(BaseModel):
    """Identified candidate pond site."""

    latitude: float = Field(..., description="Latitude of the pond location (WGS84)")
    longitude: float = Field(..., description="Longitude of the pond location (WGS84)")
    elevation_m: float = Field(..., description="Estimated elevation at the pond site (metres)")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "latitude": 21.2520,
                    "longitude": 81.2950,
                    "elevation_m": 272.5,
                }
            ]
        }
    }


class GeoJSONPolygon(BaseModel):
    """GeoJSON Polygon geometry."""

    type: str = Field(default="Polygon", description="GeoJSON geometry type")
    coordinates: List[List[List[float]]] = Field(
        ..., description="Polygon coordinates as [[[lon, lat], ...]]"
    )


class CatchmentInfo(BaseModel):
    """Delineated catchment (watershed) information."""

    area_sq_m: float = Field(..., description="Catchment area in square metres")
    perimeter_m: float = Field(..., description="Catchment perimeter in metres")
    boundary: GeoJSONPolygon = Field(
        ..., description="Catchment boundary as a GeoJSON Polygon"
    )


class ContourSummary(BaseModel):
    """Summary statistics of the parsed contour data."""

    num_contour_lines: int = Field(
        ..., description="Total number of contour lines parsed from the file"
    )
    elevation_min_m: float = Field(
        ..., description="Minimum contour elevation in metres"
    )
    elevation_max_m: float = Field(
        ..., description="Maximum contour elevation in metres"
    )
    estimated_contour_interval_m: float = Field(
        ..., description="Estimated contour interval in metres"
    )


class TerrainIndices(BaseModel):
    """
    Advanced terrain analysis indices computed at the pond site.

    References:
    - TWI: Beven & Kirkby (1979) — ln(As / tan β)
    - TPI: Guisan et al. (1999) — z₀ - mean(z_neighborhood)
    - SPI: Moore et al. (1991) — ln(As × tan β)
    """

    twi: float = Field(
        ...,
        description="Topographic Wetness Index — higher = more water accumulation potential",
    )
    tpi: float = Field(
        ...,
        description="Topographic Position Index — negative = valley/depression",
    )
    spi: float = Field(
        ...,
        description="Stream Power Index — higher = more water erosion/flow energy",
    )
    plan_curvature: float = Field(
        ...,
        description="Plan curvature — positive = convergent flow (good for pond)",
    )
    profile_curvature: float = Field(
        ...,
        description="Profile curvature — positive = concave (decelerating flow)",
    )
    suitability_score: float = Field(
        ...,
        description="Composite suitability score (0-1) from multi-criteria analysis",
    )


class AnalysisMetadata(BaseModel):
    """Processing metadata and notes."""

    source_filename: str = Field(
        ..., description="Name of the uploaded contour file"
    )
    processing_notes: List[str] = Field(
        default_factory=list,
        description="Informational messages from the processing pipeline",
    )
    grid_resolution: Optional[str] = Field(
        default=None, description="DEM grid resolution used (rows × cols)"
    )
    algorithms_used: List[str] = Field(
        default_factory=list,
        description="List of algorithms/methods applied during analysis",
    )


class AnalyzeContourResponse(BaseModel):
    """
    Complete response from the /analyzeContour endpoint.

    Contains the identified pond location, catchment information,
    contour summary, terrain analysis indices, and processing metadata.
    """

    pond_location: PondLocation
    catchment: CatchmentInfo
    contour_summary: ContourSummary
    terrain_indices: TerrainIndices
    metadata: AnalysisMetadata

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "pond_location": {
                        "latitude": 21.2520,
                        "longitude": 81.2950,
                        "elevation_m": 272.5,
                    },
                    "catchment": {
                        "area_sq_m": 125000.0,
                        "perimeter_m": 1800.0,
                        "boundary": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [81.29, 21.25],
                                    [81.30, 21.25],
                                    [81.30, 21.26],
                                    [81.29, 21.26],
                                    [81.29, 21.25],
                                ]
                            ],
                        },
                    },
                    "contour_summary": {
                        "num_contour_lines": 2710,
                        "elevation_min_m": 267.0,
                        "elevation_max_m": 298.0,
                        "estimated_contour_interval_m": 1.0,
                    },
                    "terrain_indices": {
                        "twi": 12.5,
                        "tpi": -2.3,
                        "spi": 8.1,
                        "plan_curvature": 0.05,
                        "profile_curvature": 0.03,
                        "suitability_score": 0.85,
                    },
                    "metadata": {
                        "source_filename": "contours_1m.kml",
                        "processing_notes": [
                            "Parsed 2710 contour lines",
                            "DEM grid: 200×200 cells",
                            "Catchment delineated using D8 flow direction",
                        ],
                        "grid_resolution": "200×200",
                        "algorithms_used": [
                            "Priority-Flood sink filling (Barnes et al., 2014)",
                            "D8 flow direction",
                            "TWI/TPI/SPI multi-criteria suitability scoring",
                        ],
                    },
                }
            ]
        }
    }
