"""
POST /analyzeArea — Phase 3 route: analyse a user-selected map region.

Unlike /analyzeContour (which parses an uploaded contour file), this takes a
bounding box the user drew on the map, fetches a DEM for it from the Open-Meteo
elevation API, and then runs the *same* Phase 2 hydrology pipeline — flow
routing, pond siting, catchment delineation, geometry — before adding the Phase 3
water-volume estimate on top.

Kept thin on purpose: it wires modules together in order and shapes the response.
All the real logic lives in elevation_api, catchment, pond_locator,
geometry_utils, rainfall_api, and water_volume.
"""

import time
from typing import List

from fastapi import APIRouter, HTTPException

from models.schemas import (
    AnalysisMetadata,
    AnalyzeAreaRequest,
    AnalyzeAreaResponse,
    AreaCandidateResult,
    AreaSummary,
    CatchmentInfo,
    GeoJSONPolygon,
    PondFootprint,
    PondLocation,
    RainfallInfo,
    SuitabilityFactors,
    WaterVolume,
)
from modules import (
    catchment,
    elevation_api,
    geometry_utils,
    local_dem,
    pond_locator,
    rainfall_api,
    water_volume,
)

router = APIRouter()


@router.post(
    "/analyzeArea",
    response_model=AnalyzeAreaResponse,
    summary="Analyse a selected map region: suggested pond, catchment, and expected water volume",
    description=(
        "Select a land area on the map (a bounding box). The route fetches an "
        "elevation model for that area from the Open-Meteo elevation API, runs the "
        "same terrain/hydrology pipeline used for uploaded contour maps, and returns "
        "ranked candidate pond sites — each with its catchment, its own footprint, "
        "and an estimate of the water volume it could collect based on live historical "
        "rainfall for the location. Nothing is hard-coded to any one place; it works "
        "for any region you select."
    ),
    tags=["Catchment Analysis"],
)
async def analyze_area(req: AnalyzeAreaRequest):
    """Analyse a selected region and return ranked pond sites with water volumes."""
    t_start = time.time()
    notes: List[str] = []

    lon_min, lat_min, lon_max, lat_max = req.bbox
    center_lon = (lon_min + lon_max) / 2.0
    center_lat = (lat_min + lat_max) / 2.0

    # --- Build a DEM for the selected area ---
    # Prefer the offline contour-map DEM when the area is within its coverage
    # (fast, reliable, no external API). Only fall back to the elevation API for
    # areas outside the bundled map. This keeps the sample area working even when
    # the free elevation API is rate-limited or unreachable.
    bbox = tuple(req.bbox)
    try:
        elevation_api._validate_bbox(bbox)  # sane bbox for either path
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    grid = None
    dem_source = None
    try:
        if local_dem.covers(bbox):
            grid = local_dem.build_local_grid(bbox, grid_size=req.grid_size)
            if grid is not None:
                dem_source = "contour map (offline)"
    except Exception:
        grid = None  # any trouble with the local DEM → fall back to the API

    if grid is None:
        try:
            grid = await elevation_api.fetch_dem_grid(bbox, grid_size=req.grid_size)
            dem_source = "Open-Meteo elevation API"
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Elevation grid error: {exc}")

    notes.append(f"Elevation source: {dem_source}")
    notes.extend(grid.notes)

    # --- Flow direction/accumulation (computed once, reused per candidate) ---
    try:
        flow = catchment.compute_flow(grid.dem)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Flow computation error: {exc}")
    notes.extend(flow.notes)

    # --- Rank candidate pond sites ---
    # First pass is strict (reject sites whose pond can't be bounded). If the
    # terrain is gentle enough that nothing passes at this DEM resolution, fall
    # back to a lenient pass so we still return the best-scoring sites, flagged
    # as flat ground that would need an engineered dam, rather than nothing.
    try:
        ranked = pond_locator.find_candidates(grid, flow.flow_acc, num_candidates=req.num_candidates)
        if not ranked:
            ranked = pond_locator.find_candidates(
                grid, flow.flow_acc, num_candidates=req.num_candidates,
                reject_unbounded_footprint=False,
            )
            if ranked:
                notes.append(
                    "No naturally bounded pond basin was resolvable here at this resolution — "
                    "showing the best-scoring sites, which sit on flat ground and would need an "
                    "engineered dam/spillway rather than a simple dug basin."
                )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pond ranking error: {exc}")

    if not ranked:
        raise HTTPException(
            status_code=422,
            detail="No feasible pond site found in this area — the terrain may be uniformly "
                   "too steep. Try selecting a region with more relief (a valley or basin).",
        )

    # --- Rainfall for the region centre (live, with offline fallback) ---
    rain = rainfall_api.annual_rainfall(center_lat, center_lon)
    notes.extend(rain.notes)

    # Cell area in m² — used for both the flood-fill volume and consistent with
    # how pond_locator sizes cells.
    cell_size_m = min(grid.meta.cell_lon, grid.meta.cell_lat) * 111_000
    cell_area_m2 = cell_size_m ** 2
    runoff_coeff = req.runoff_coefficient or water_volume.DEFAULT_RUNOFF_COEFFICIENT

    # --- Per-candidate: catchment, footprint, geometry, water volume ---
    results: List[AreaCandidateResult] = []
    for cand in ranked:
        notes.extend(cand.notes)
        try:
            catch = catchment.delineate_from_flow(flow, cand.row, cand.col)
            catch_poly = geometry_utils.catchment_polygon(catch.mask, grid.meta)
            catch_area_m2, catch_perim_m = geometry_utils.catchment_geometry(catch_poly, cand.lon, cand.lat)
            catch_geojson = geometry_utils.polygon_to_geojson(catch_poly)

            footprint_mask, footprint_info = pond_locator.compute_pond_footprint(
                grid.dem, cand.row, cand.col
            )
            footprint_poly = geometry_utils.catchment_polygon(footprint_mask, grid.meta)
            footprint_area_m2, footprint_perim_m = geometry_utils.catchment_geometry(
                footprint_poly, cand.lon, cand.lat
            )
            footprint_geojson = geometry_utils.polygon_to_geojson(footprint_poly)

            vol = water_volume.compute(
                catchment_area_m2=catch_area_m2,
                annual_rainfall_m=rain.annual_rainfall_m,
                dem=grid.dem,
                footprint_mask=footprint_mask,
                water_level_m=footprint_info["water_level_m"],
                cell_area_m2=cell_area_m2,
                runoff_coefficient=runoff_coeff,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Analysis error for rank {cand.rank}: {exc}")

        notes.extend(vol.notes)

        results.append(AreaCandidateResult(
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
                area_sq_m=round(catch_area_m2, 2),
                perimeter_m=round(catch_perim_m, 2),
                boundary=GeoJSONPolygon(**catch_geojson),
            ),
            suitability=SuitabilityFactors(
                wetness_index=round(cand.wetness_index, 4),
                depression_index=round(cand.depression_index, 4),
                suitability_score=round(cand.suitability_score, 4),
            ),
            water_volume=WaterVolume(
                annual_runoff_m3=vol.annual_runoff_m3,
                storage_capacity_m3=vol.storage_capacity_m3,
                expected_collectable_m3=vol.expected_collectable_m3,
                limiting_factor=vol.limiting_factor,
                runoff_coefficient=vol.runoff_coefficient,
                annual_rainfall_mm=rain.annual_rainfall_mm,
            ),
        ))

    t_elapsed = time.time() - t_start
    notes.append(f"Total processing time: {t_elapsed:.2f}s")

    return AnalyzeAreaResponse(
        candidates=results,
        rainfall=RainfallInfo(
            annual_rainfall_mm=rain.annual_rainfall_mm,
            source=rain.source,
            years_averaged=rain.years_averaged,
            monthly_climatology_mm=rain.monthly_climatology_mm,
        ),
        area_summary=AreaSummary(
            bbox=req.bbox,
            center_lat=round(center_lat, 6),
            center_lon=round(center_lon, 6),
            grid_resolution=f"{grid.meta.rows}x{grid.meta.cols}",
            elevation_min_m=round(float(grid.dem.min()), 2),
            elevation_max_m=round(float(grid.dem.max()), 2),
            dem_source=dem_source,
        ),
        metadata=AnalysisMetadata(
            source_filename=f"open-meteo DEM for bbox {req.bbox}",
            processing_notes=notes,
            grid_resolution=f"{grid.meta.rows}x{grid.meta.cols}",
            total_processing_time_s=round(t_elapsed, 3),
        ),
    )
