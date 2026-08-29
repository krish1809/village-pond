"""
End-to-end demo script — runs the sample contour KML through the full pipeline
and prints the JSON response. Use this for demonstration and debugging.

Usage:
    python tests/demo_full_pipeline.py [path/to/contour.kml]
"""

import json
import sys
import time
import os

# Make sure we can import from backend root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules import kml_parser, terrain_grid, catchment, pond_locator, geometry_utils
from modules.catchment import (
    _priority_flood_fill,
    _compute_flow_direction,
    _compute_flow_accumulation,
)


def run_pipeline(kml_path: str, grid_size: int = 150):
    print(f"\n{'='*60}")
    print(f"Village Pond Planning System — Phase 2 Demo")
    print(f"{'='*60}")
    print(f"Input  : {kml_path}")
    print(f"Grid   : {grid_size}×{grid_size}")
    print()

    t0 = time.time()

    # ── Step 1: Parse KML ────────────────────────────────────────────────────
    print("Step 1/5  Parsing KML...")
    with open(kml_path, "rb") as f:
        file_bytes = f.read()
    filename = os.path.basename(kml_path)
    parse_result = kml_parser.parse(file_bytes, filename)
    for n in parse_result.notes:
        print(f"          {n}")

    # ── Step 2: Build terrain grid ───────────────────────────────────────────
    print(f"\nStep 2/5  Building DEM grid ({grid_size})...")
    grid = terrain_grid.build_grid(parse_result.contour_lines, grid_size=grid_size)
    for n in grid.notes:
        print(f"          {n}")

    # ── Step 3: Flow direction + accumulation ────────────────────────────────
    print("\nStep 3/5  Priority-Flood + D8 flow direction + accumulation...")
    t_flow = time.time()
    filled_dem = _priority_flood_fill(grid.dem)
    flow_dir = _compute_flow_direction(filled_dem)
    flow_acc = _compute_flow_accumulation(flow_dir)
    print(f"          Flow computed in {time.time()-t_flow:.2f}s | max acc={flow_acc.max()}")

    # ── Step 4: Find best pond site ──────────────────────────────────────────
    print("\nStep 4/5  Multi-criteria pond site scoring (TWI+TPI+SPI+Curvature)...")
    candidate = pond_locator.find_pond(grid, flow_acc)
    for n in candidate.notes:
        print(f"          {n}")

    # ── Step 5: Catchment delineation ────────────────────────────────────────
    print("\nStep 5/5  Delineating catchment watershed...")
    catchment_result = catchment.delineate(grid, candidate.row, candidate.col)
    for n in catchment_result.notes:
        print(f"          {n}")

    catch_poly = geometry_utils.catchment_polygon(catchment_result.mask, grid.meta)
    area_m2, perim_m = geometry_utils.catchment_geometry(
        catch_poly, candidate.lon, candidate.lat
    )
    geojson_boundary = geometry_utils.polygon_to_geojson(catch_poly)

    elapsed = time.time() - t0

    # ── Contour summary ──────────────────────────────────────────────────────
    elevations = sorted(set(cl.elevation for cl in parse_result.contour_lines))
    diffs = [elevations[i+1] - elevations[i] for i in range(len(elevations)-1)]
    diffs.sort()
    interval = diffs[len(diffs)//2] if diffs else 0.0

    # ── Build response JSON ──────────────────────────────────────────────────
    response = {
        "pond_location": {
            "latitude": round(candidate.lat, 6),
            "longitude": round(candidate.lon, 6),
            "elevation_m": round(candidate.elevation_m, 2),
        },
        "catchment": {
            "area_sq_m": round(area_m2, 2),
            "area_sq_km": round(area_m2 / 1_000_000, 4),
            "perimeter_m": round(perim_m, 2),
            "boundary": geojson_boundary,
        },
        "contour_summary": {
            "num_contour_lines": parse_result.num_lines,
            "elevation_min_m": elevations[0],
            "elevation_max_m": elevations[-1],
            "estimated_contour_interval_m": round(interval, 2),
        },
        "terrain_indices": {
            "twi": round(candidate.twi, 4),
            "tpi": round(candidate.tpi, 4),
            "spi": round(candidate.spi, 4),
            "plan_curvature": round(candidate.plan_curvature, 6),
            "profile_curvature": round(candidate.profile_curvature, 6),
            "suitability_score": round(candidate.suitability_score, 4),
        },
        "metadata": {
            "source_filename": filename,
            "total_processing_time_s": round(elapsed, 2),
            "grid_resolution": f"{grid.meta.rows}×{grid.meta.cols}",
            "algorithms_used": [
                "Priority-Flood sink filling (Barnes et al., 2014)",
                "D8 flow direction (O'Callaghan & Mark, 1984)",
                "TWI - Topographic Wetness Index (Beven & Kirkby, 1979)",
                "TPI - Topographic Position Index (Guisan et al., 1999)",
                "SPI - Stream Power Index (Moore et al., 1991)",
                "Plan/Profile Curvature (Zevenbergen & Thorne, 1987)",
                "Multi-criteria weighted suitability scoring",
                "Reverse-BFS watershed delineation",
            ],
        },
    }

    print(f"\n{'='*60}")
    print(f"RESULT  (total time: {elapsed:.2f}s)")
    print(f"{'='*60}")
    # Print everything except the full boundary coordinates (too long)
    display = dict(response)
    display["catchment"] = {
        k: v for k, v in response["catchment"].items() if k != "boundary"
    }
    display["catchment"]["boundary_vertices"] = len(
        geojson_boundary["coordinates"][0]
    )
    print(json.dumps(display, indent=2))

    print(f"\n{'='*60}")
    print("Full GeoJSON boundary (first 3 coords + count):")
    first3 = geojson_boundary["coordinates"][0][:3]
    total = len(geojson_boundary["coordinates"][0])
    print(f"  {first3} ... ({total} vertices)")

    return response


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "../contours_1m.kml"
    grid_sz = int(sys.argv[2]) if len(sys.argv) > 2 else 150
    if not os.path.exists(path):
        print(f"ERROR: File not found: {path}")
        print("Usage: python tests/demo_full_pipeline.py [path/to/contour.kml] [grid_size]")
        sys.exit(1)
    run_pipeline(path, grid_size=grid_sz)
