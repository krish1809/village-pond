"""
Visualization — Renders the analysis result as a PNG image.

Responsibility: Plotting ONLY. Takes already-computed results (contour
lines, grid, flow, candidates) and produces image bytes. Does not parse
files, compute terrain, or run any analysis itself.

Used by both:
  - the API's /analyzeContour route when format=image is requested
  - tests/demo_visual_report.py, the standalone report-demonstration script

Kept as one shared function so the two never drift out of sync with each
other.
"""

import io
from typing import List

import numpy as np
import matplotlib
matplotlib.use("Agg")  # no display backend needed on a server
import matplotlib.pyplot as plt
from scipy.ndimage import binary_dilation

from modules import pond_locator
from shapely.geometry import MultiPolygon


def _largest_polygon(geom):
    """catchment_polygon can return a MultiPolygon if the mask has
    disconnected clusters (this can happen with the exact-union geometry
    method, e.g. two cells touching only diagonally). Plotting needs a
    single Polygon's exterior ring, so take the largest piece — same
    convention already used in geometry_utils.catchment_geometry and
    polygon_to_geojson, kept consistent here."""
    if isinstance(geom, MultiPolygon):
        return max(geom.geoms, key=lambda p: p.area)
    return geom


def render_analysis_png(
    contour_lines,
    grid,
    flow,
    candidates: List,
    catchment_module,
    geometry_utils_module,
    source_filename: str = "",
) -> bytes:
    """
    Render the full analysis result (contours, excluded channel zone,
    ranked candidates with footprints and catchments) as a PNG.

    Parameters mirror what the route already has in hand after running
    the analysis pipeline, so no recomputation happens here.

    Returns
    -------
    PNG image bytes.
    """
    channel_threshold = np.percentile(flow.flow_acc, pond_locator.CHANNEL_FLOW_ACC_PERCENTILE)
    channel_mask = flow.flow_acc > channel_threshold
    channel_buffered = binary_dilation(channel_mask, iterations=pond_locator.CHANNEL_BUFFER_CELLS)

    fig, ax = plt.subplots(figsize=(11, 9))
    cmap = plt.get_cmap("terrain")
    elevations = [cl.elevation for cl in contour_lines]
    emin, emax = min(elevations), max(elevations)

    for cl in contour_lines:
        lons = [pt[0] for pt in cl.vertices]
        lats = [pt[1] for pt in cl.vertices]
        color = cmap((cl.elevation - emin) / (emax - emin)) if emax > emin else cmap(0.5)
        ax.plot(lons, lats, color=color, linewidth=0.5, zorder=1)

    ax.contourf(
        grid.lon_grid, grid.lat_grid, channel_buffered.astype(int),
        levels=[0.5, 1.5], colors=["red"], alpha=0.35, zorder=2,
    )

    colors = ["#0033cc", "#009933", "#cc6600", "#aa00aa", "#00aaaa"]
    for cand, color in zip(candidates, colors):
        catch = catchment_module.delineate_from_flow(flow, cand.row, cand.col)
        catch_poly = _largest_polygon(geometry_utils_module.catchment_polygon(catch.mask, grid.meta))

        footprint_mask, footprint_info = pond_locator.compute_pond_footprint(grid.dem, cand.row, cand.col)
        footprint_poly = _largest_polygon(geometry_utils_module.catchment_polygon(footprint_mask, grid.meta))
        footprint_area_m2, _ = geometry_utils_module.catchment_geometry(footprint_poly, cand.lon, cand.lat)

        xs, ys = catch_poly.exterior.xy
        ax.plot(xs, ys, color=color, linewidth=1.5, linestyle="--", zorder=3, alpha=0.7)

        fxs, fys = footprint_poly.exterior.xy
        ax.plot(fxs, fys, color=color, linewidth=2, zorder=4)
        ax.fill(fxs, fys, color=color, alpha=0.55, zorder=4)

        ax.scatter([cand.lon], [cand.lat], color=color, s=180, marker="*",
                   edgecolor="black", linewidth=1.2, zorder=5)
        ax.annotate(
            f"Rank {cand.rank}\npond: {footprint_area_m2:.0f} m\u00b2",
            (cand.lon, cand.lat), textcoords="offset points", xytext=(10, 10),
            fontsize=9, fontweight="bold", color=color,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor=color, alpha=0.9),
        )

    title_source = f"{source_filename} — " if source_filename else ""
    ax.set_title(
        f"{title_source}{len(candidates)} ranked pond candidates\n"
        f"Solid fill = estimated pond footprint, dashed outline = catchment (water source area)\n"
        f"Red = excluded drainage-channel zone",
        fontsize=10,
    )
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_aspect("equal")
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf.read()
