"""
Demonstration script for the report's "Demonstration using the provided
contour map" requirement.

Runs the full analysis pipeline on a KML file and produces the same image
the API returns when called with format=image — this script and the API
share the exact same rendering function (modules/visualization.py), so
they can never drift out of sync with each other.

Usage:
    python tests/demo_visual_report.py ../contours_1m.kml
    python tests/demo_visual_report.py ../contours_1m.kml --candidates 3 --out demo.png
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import kml_parser, terrain_grid, catchment, pond_locator, geometry_utils, visualization


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kml_path", help="Path to the contour KML/KMZ file")
    parser.add_argument("--candidates", type=int, default=3, help="Number of ranked candidates")
    parser.add_argument("--out", default="demo_report_figure.png", help="Output image path")
    args = parser.parse_args()

    with open(args.kml_path, "rb") as f:
        raw = f.read()

    print(f"Parsing {args.kml_path} ...")
    parsed = kml_parser.parse(raw, Path(args.kml_path).name)
    print(f"  {parsed.num_lines} contour lines found")

    print("Building elevation grid ...")
    grid = terrain_grid.build_grid(parsed.contour_lines, grid_size=150)

    print("Computing flow direction/accumulation ...")
    flow = catchment.compute_flow(grid.dem)

    print(f"Ranking top {args.candidates} candidate pond sites ...")
    candidates = pond_locator.find_candidates(grid, flow.flow_acc, num_candidates=args.candidates)

    print()
    for cand in candidates:
        catch = catchment.delineate_from_flow(flow, cand.row, cand.col)
        poly = geometry_utils.catchment_polygon(catch.mask, grid.meta)
        area_m2, _ = geometry_utils.catchment_geometry(poly, cand.lon, cand.lat)

        footprint_mask, footprint_info = pond_locator.compute_pond_footprint(grid.dem, cand.row, cand.col)
        footprint_poly = geometry_utils.catchment_polygon(footprint_mask, grid.meta)
        footprint_area_m2, _ = geometry_utils.catchment_geometry(footprint_poly, cand.lon, cand.lat)

        capped_note = "  [CAPPED -- very flat terrain, needs engineered dam]" if footprint_info["capped"] else ""
        print(f"Rank {cand.rank}: lat={cand.lat:.5f} lon={cand.lon:.5f} "
              f"elevation={cand.elevation_m:.1f}m slope={cand.slope_deg:.2f}deg "
              f"score={cand.suitability_score:.4f}")
        print(f"           catchment_area={area_m2:.1f}sqm  "
              f"pond_footprint_area={footprint_area_m2:.1f}sqm (at {footprint_info['assumed_depth_m']}m assumed depth){capped_note}")

    print("\nRendering figure (shared with the API's format=image option) ...")
    png_bytes = visualization.render_analysis_png(
        parsed.contour_lines, grid, flow, candidates, catchment, geometry_utils,
        source_filename=Path(args.kml_path).name,
    )
    with open(args.out, "wb") as f:
        f.write(png_bytes)
    print(f"Saved demonstration figure to {args.out}")


if __name__ == "__main__":
    main()
