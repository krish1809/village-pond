"""
POST /analyzeContour — FastAPI route handler.

Kept thin on purpose: this file just wires the modules together in order
and builds the response. The actual terrain/hydrology logic lives in
kml_parser, terrain_grid, catchment, pond_locator, and geometry_utils.
"""

import logging
import time
from typing import List, Literal, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

from models.schemas import (
    AnalysisMetadata,
    AnalyzeContourResponse,
    CatchmentInfo,
    ContourSummary,
    GeoJSONPolygon,
    PondCandidateResult,
    PondFootprint,
    PondLocation,
    SuitabilityFactors,
)
from modules import kml_parser, terrain_grid, catchment, pond_locator, geometry_utils, visualization

import telemetry
from telemetry import stage

router = APIRouter()
log = logging.getLogger("village_pond.analyze_contour")
_OUTCOME_BY_STATUS = {422: "invalid_request", 502: "upstream_error"}


@router.post(
    "/analyzeContour",
    summary="Analyze a contour map and return ranked candidate pond sites with catchment info",
    description=(
        "Upload a KML or KMZ contour map. The route parses the contour lines, "
        "builds an elevation grid from them, computes flow direction/accumulation, "
        "and returns the top-ranked candidate pond sites along with the catchment "
        "area draining into each one. All results are derived from the uploaded "
        "file — nothing is hard-coded, so this works on any similarly-structured "
        "contour map, not just the provided sample. Set format=image to get a "
        "rendered PNG of the same result instead of JSON."
    ),
    tags=["Catchment Analysis"],
)
def analyze_contour(
    contour_map: UploadFile = File(
        ...,
        description="KML or KMZ contour map, with contour lines tagged with elevation",
    ),
    grid_size: Optional[int] = Query(
        default=150,
        ge=50,
        le=400,
        description="Elevation grid resolution (cells along the longer axis). Higher = more detail, slower.",
    ),
    num_candidates: Optional[int] = Query(
        default=3,
        ge=1,
        le=10,
        description="How many ranked candidate pond sites to return.",
    ),
    format: Literal["json", "image"] = Query(
        default="json",
        description="Response format. 'json' (default) returns structured data. "
                    "'image' returns a rendered PNG map of the same result.",
    ),
):
    """Analyze a contour map and return ranked candidate pond sites with catchment info."""
    log.info("analyzeContour request received",
             extra={"file_name": contour_map.filename or "uploaded_file", "grid_size": grid_size,
                    "num_candidates": num_candidates, "response_format": format})
    try:
        response = _run_contour_analysis(contour_map, grid_size, num_candidates, format)
    except HTTPException as exc:
        outcome = _OUTCOME_BY_STATUS.get(exc.status_code, "error")
        telemetry.ANALYSES.add(1, {"endpoint": "analyzeContour", "outcome": outcome})
        log.log(logging.ERROR if exc.status_code >= 500 else logging.WARNING,
                "analyzeContour failed: %s", exc.detail,
                extra={"status_code": exc.status_code, "outcome": outcome})
        raise
    telemetry.ANALYSES.add(1, {"endpoint": "analyzeContour", "outcome": "ok"})
    return response


def _run_contour_analysis(contour_map, grid_size, num_candidates, format):
    """The Phase 2 pipeline; each stage runs inside its own OpenTelemetry span."""
    t_start = time.time()
    filename = contour_map.filename or "uploaded_file"
    all_notes: List[str] = []

    # --- Read and parse the uploaded file ---
    try:
        file_bytes = contour_map.file.read()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not read uploaded file: {exc}")

    if not file_bytes:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")

    with stage("parse_contours", **{"file.size": len(file_bytes)}) as span:
        try:
            parse_result = kml_parser.parse(file_bytes, filename)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"KML parsing error: {exc}")
        span.set_attribute("contours.lines", parse_result.num_lines)

    all_notes.extend(parse_result.notes)
    contour_lines = parse_result.contour_lines

    elevations = sorted(set(cl.elevation for cl in contour_lines))
    elev_min, elev_max = elevations[0], elevations[-1]
    if len(elevations) > 1:
        diffs = sorted(elevations[i + 1] - elevations[i] for i in range(len(elevations) - 1))
        contour_interval = diffs[len(diffs) // 2]
    else:
        contour_interval = 0.0

    # --- Build the elevation grid ---
    with stage("build_grid", **{"grid.size": grid_size}):
        try:
            grid = terrain_grid.build_grid(contour_lines, grid_size=grid_size)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Terrain grid error: {exc}")
    all_notes.extend(grid.notes)

    # --- Flow direction/accumulation, computed once and reused for every candidate ---
    with stage("flow_routing", **{"grid.cells": int(grid.dem.size)}):
        try:
            flow = catchment.compute_flow(grid.dem)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Flow computation error: {exc}")
    all_notes.extend(flow.notes)

    # --- Rank candidate pond sites ---
    with stage("rank_candidates", **{"candidates.requested": num_candidates}) as span:
        try:
            ranked = pond_locator.find_candidates(grid, flow.flow_acc, num_candidates=num_candidates)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Pond ranking error: {exc}")
        span.set_attribute("candidates.found", len(ranked))

    if not ranked:
        raise HTTPException(
            status_code=422,
            detail="No feasible pond site found — the terrain may be uniformly too steep, "
                   "or the contour data doesn't cover enough of a slope to locate a catchment.",
        )

    # --- Delineate catchment + geometry for each candidate ---
    candidate_results: List[PondCandidateResult] = []
    for cand in ranked:
        all_notes.extend(cand.notes)
        with stage("candidate", **{"candidate.rank": cand.rank}):
            try:
                catch = catchment.delineate_from_flow(flow, cand.row, cand.col)
                catch_poly = geometry_utils.catchment_polygon(catch.mask, grid.meta)
                area_m2, perim_m = geometry_utils.catchment_geometry(catch_poly, cand.lon, cand.lat)
                geojson_boundary = geometry_utils.polygon_to_geojson(catch_poly)

                footprint_mask, footprint_info = pond_locator.compute_pond_footprint(
                    grid.dem, cand.row, cand.col
                )
                footprint_poly = geometry_utils.catchment_polygon(footprint_mask, grid.meta)
                footprint_area_m2, footprint_perim_m = geometry_utils.catchment_geometry(
                    footprint_poly, cand.lon, cand.lat
                )
                footprint_geojson = geometry_utils.polygon_to_geojson(footprint_poly)
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Catchment/geometry error for rank {cand.rank}: {exc}")

        if footprint_info["capped"]:
            all_notes.append(
                f"Rank {cand.rank}: pond footprint hit its growth cap — terrain here is very flat; "
                f"an engineered dam/spillway would be needed, not just a dug basin"
            )

        candidate_results.append(PondCandidateResult(
            rank=cand.rank,
            location=PondLocation(
                latitude=cand.lat,
                longitude=cand.lon,
                elevation_m=round(cand.elevation_m, 2),
                slope_deg=round(cand.slope_deg, 2),
            ),
            pond_footprint=PondFootprint(
                area_sq_m=round(footprint_area_m2, 2),
                perimeter_m=round(footprint_perim_m, 2),
                boundary=GeoJSONPolygon(**footprint_geojson),
                assumed_depth_m=footprint_info["assumed_depth_m"],
                water_level_m=footprint_info["water_level_m"],
                capped=footprint_info["capped"],
            ),
            catchment=CatchmentInfo(
                area_sq_m=round(area_m2, 2),
                perimeter_m=round(perim_m, 2),
                boundary=geojson_boundary,
            ),
            suitability=SuitabilityFactors(
                wetness_index=round(cand.wetness_index, 4),
                depression_index=round(cand.depression_index, 4),
                suitability_score=round(cand.suitability_score, 4),
            ),
        ))

    t_elapsed = time.time() - t_start
    all_notes.append(f"Total processing time: {t_elapsed:.2f}s")

    log.info("contour analysis complete: %d pond sites in %.2fs", len(candidate_results), t_elapsed,
             extra={"sites": len(candidate_results), "duration_s": round(t_elapsed, 3)})

    if format == "image":
        with stage("render_png"):
            try:
                png_bytes = visualization.render_analysis_png(
                    contour_lines, grid, flow, ranked, catchment, geometry_utils,
                    source_filename=filename,
                )
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Image rendering error: {exc}")
        return Response(content=png_bytes, media_type="image/png")

    return AnalyzeContourResponse(
        candidates=candidate_results,
        contour_summary=ContourSummary(
            num_contour_lines=parse_result.num_lines,
            elevation_min_m=elev_min,
            elevation_max_m=elev_max,
            estimated_contour_interval_m=round(contour_interval, 2),
        ),
        metadata=AnalysisMetadata(
            source_filename=filename,
            processing_notes=all_notes,
            grid_resolution=f"{grid.meta.rows}x{grid.meta.cols}",
            total_processing_time_s=round(t_elapsed, 3),
            trace_id=telemetry.current_trace_id(),
        ),
    )
