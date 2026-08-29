"""
POST /analyzeContour — FastAPI route handler.

This is intentionally a THIN orchestration layer:
  - Accepts uploaded KML/KMZ file
  - Calls each module in sequence
  - Assembles the Pydantic response
  - Handles errors with informative 422 responses

No terrain logic or geometry calculations live here — those are in their
respective modules (kml_parser, terrain_grid, catchment, pond_locator,
geometry_utils). This keeps the route testable in isolation and the modules
independently reusable.
"""

import time
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse

from models.schemas import (
    AnalysisMetadata,
    AnalyzeContourResponse,
    CatchmentInfo,
    ContourSummary,
    GeoJSONPolygon,
    PondLocation,
    TerrainIndices,
)
from modules import kml_parser, terrain_grid, catchment, pond_locator, geometry_utils

router = APIRouter()


@router.post(
    "/analyzeContour",
    response_model=AnalyzeContourResponse,
    summary="Analyze a contour map and identify the best pond location with catchment",
    description="""
Upload a KML or KMZ contour map file. The API will:

1. **Parse** the contour lines and their elevations
2. **Build a DEM** (Digital Elevation Model) via spatial interpolation  
3. **Fill depressions** using the Priority-Flood algorithm (Barnes et al., 2014)
4. **Compute D8 flow direction** and flow accumulation
5. **Score every cell** using TWI, TPI, SPI, and curvature indices
6. **Select the best pond site** as the highest-scoring interior cell
7. **Delineate the catchment** draining to that site via reverse watershed BFS
8. **Return** the pond location, catchment boundary (GeoJSON), terrain indices,
   and contour summary

**Hard constraint**: all results are derived entirely from the uploaded file —
no coordinates, elevations, or results are hard-coded. Works on any KML/KMZ
contour map with elevation in `<name>`, Z-coordinates, or `<ExtendedData>`.
    """,
    tags=["Catchment Analysis"],
)
def analyze_contour(
    file: UploadFile = File(
        ...,
        description="KML or KMZ contour map file with contour lines tagged with elevation",
    ),
    grid_size: Optional[int] = Query(
        default=150,
        ge=50,
        le=400,
        description="DEM grid resolution (cells along the longer axis). Higher = more accurate but slower."
    ),
):
    """
    Analyze a contour map and return catchment information for pond planning.

    Accepts KML or KMZ. Elevation must be encoded in contour `<name>` tags,
    coordinate Z-values, or `<ExtendedData>/<SimpleData>` elements.

    Returns structured JSON with pond location, catchment boundary (GeoJSON),
    terrain indices, contour summary, and processing metadata.
    """
    t_start = time.time()
    filename = file.filename or "uploaded_file"
    all_notes: list[str] = []
    algorithms_used = [
        "scipy.interpolate.griddata (linear + nearest-neighbour fill)",
        "Horn (1981) slope — 3×3 finite difference gradient",
        "Priority-Flood sink filling (Barnes et al., 2014)",
        "D8 flow direction (O'Callaghan & Mark, 1984)",
        "Flow accumulation via topological sort (Kahn's algorithm)",
        "TWI — Topographic Wetness Index (Beven & Kirkby, 1979)",
        "TPI — Topographic Position Index (Guisan et al., 1999)",
        "SPI — Stream Power Index (Moore et al., 1991)",
        "Plan/profile curvature (Zevenbergen & Thorne, 1987)",
        "Multi-criteria weighted suitability score",
        "Reverse-BFS watershed delineation",
        "UTM projection for accurate metric area/perimeter (pyproj + shapely)",
    ]

    # ── Step 1: Read and parse KML/KMZ ──────────────────────────────────────
    try:
        file_bytes = file.file.read()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not read uploaded file: {exc}")

    if not file_bytes:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")

    try:
        parse_result = kml_parser.parse(file_bytes, filename)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"KML parsing error: {exc}")

    all_notes.extend(parse_result.notes)
    contour_lines = parse_result.contour_lines

    # Contour summary stats
    elevations = sorted(set(cl.elevation for cl in contour_lines))
    elev_min = elevations[0]
    elev_max = elevations[-1]
    # Estimated interval: median difference between consecutive unique elevations
    if len(elevations) > 1:
        diffs = [elevations[i+1] - elevations[i] for i in range(len(elevations)-1)]
        diffs.sort()
        contour_interval = diffs[len(diffs) // 2]
    else:
        contour_interval = 0.0

    # ── Step 2: Build terrain grid ───────────────────────────────────────────
    try:
        grid = terrain_grid.build_grid(contour_lines, grid_size=grid_size)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Terrain grid error: {exc}")

    all_notes.extend(grid.notes)

    # ── Step 3: Find best pond site (needs flow acc → do a quick pre-pass) ───
    # We need flow accumulation *before* full catchment delineation to score cells.
    # Strategy: run Priority-Flood + D8 + accumulation first (fast on NumPy arrays),
    # use it for pond scoring, then use the chosen pour point for full delineation.
    try:
        from modules.catchment import (
            _priority_flood_fill,
            _compute_flow_direction,
            _compute_flow_accumulation,
        )
        filled_dem = _priority_flood_fill(grid.dem)
        flow_dir_pre = _compute_flow_direction(filled_dem)
        flow_acc_pre = _compute_flow_accumulation(flow_dir_pre)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Flow pre-computation error: {exc}")

    try:
        candidate = pond_locator.find_pond(grid, flow_acc_pre)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pond location error: {exc}")

    all_notes.extend(candidate.notes)

    # ── Step 4: Full catchment delineation ──────────────────────────────────
    try:
        catchment_result = catchment.delineate(grid, candidate.row, candidate.col)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Catchment delineation error: {exc}")

    all_notes.extend(catchment_result.notes)

    # ── Step 5: Geometry — area, perimeter, catchment polygon ────────────────
    try:
        catch_poly = geometry_utils.catchment_polygon(catchment_result.mask, grid.meta)
        area_m2, perim_m = geometry_utils.catchment_geometry(
            catch_poly, candidate.lon, candidate.lat
        )
        geojson_boundary = geometry_utils.polygon_to_geojson(catch_poly)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Geometry calculation error: {exc}")

    t_elapsed = time.time() - t_start
    all_notes.append(f"Total processing time: {t_elapsed:.2f}s")

    # ── Step 6: Assemble response ────────────────────────────────────────────
    return AnalyzeContourResponse(
        pond_location=PondLocation(
            latitude=candidate.lat,
            longitude=candidate.lon,
            elevation_m=round(candidate.elevation_m, 2),
        ),
        catchment=CatchmentInfo(
            area_sq_m=round(area_m2, 2),
            perimeter_m=round(perim_m, 2),
            boundary=GeoJSONPolygon(**geojson_boundary),
        ),
        contour_summary=ContourSummary(
            num_contour_lines=parse_result.num_lines,
            elevation_min_m=elev_min,
            elevation_max_m=elev_max,
            estimated_contour_interval_m=round(contour_interval, 2),
        ),
        terrain_indices=TerrainIndices(
            twi=round(candidate.twi, 4),
            tpi=round(candidate.tpi, 4),
            spi=round(candidate.spi, 4),
            plan_curvature=round(candidate.plan_curvature, 6),
            profile_curvature=round(candidate.profile_curvature, 6),
            suitability_score=round(candidate.suitability_score, 4),
        ),
        metadata=AnalysisMetadata(
            source_filename=filename,
            processing_notes=all_notes,
            grid_resolution=f"{grid.meta.rows}×{grid.meta.cols}",
            algorithms_used=algorithms_used,
        ),
    )
