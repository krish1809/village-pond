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
from scipy.ndimage import binary_dilation

from modules import pond_locator
from shapely.geometry import MultiPolygon

# NOTE: matplotlib is imported lazily inside render_analysis_png(), not at module
# top level. It's only needed for the optional PNG output of /analyzeContour, and
# it pulls in ~tens of MB of RAM on import. The lab systems cap the container at
# 512 MB, so keeping matplotlib out of the startup import path (and out of the
# /analyzeArea request path, which never renders a PNG) leaves more headroom.


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
    # Lazy import (see module note): keeps matplotlib out of RAM until a PNG is
    # actually requested, which matters on the memory-capped lab systems.
    import matplotlib
    matplotlib.use("Agg")  # no display backend needed on a server
    import matplotlib.pyplot as plt

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


def render_area_png(grid, drainage_geojson, candidates, source_label: str = "") -> bytes:
    """
    Render the /analyzeArea result as a report-quality PNG: the DEM as a shaded
    terrain background, the excluded drainage network in blue, and each ranked
    candidate's catchment (dashed) and pond footprint (filled) with a marker.

    Draws from the response geometries already computed by the route (lon/lat), so
    it never re-runs the analysis. matplotlib is imported lazily to keep it out of
    RAM until a PNG is actually requested.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    meta = grid.meta
    extent = [meta.lon_min, meta.lon_max, meta.lat_min, meta.lat_max]

    fig, ax = plt.subplots(figsize=(11, 8))
    ax.imshow(grid.dem, origin="lower", extent=extent, cmap="terrain", alpha=0.9, aspect="auto")

    if drainage_geojson:
        for poly in drainage_geojson.get("coordinates", []):
            ring = poly[0]
            ax.fill([p[0] for p in ring], [p[1] for p in ring],
                    color="#1e6fd6", alpha=0.30, linewidth=0, zorder=2)

    def _exterior_rings(geom):
        """Exterior ring(s) of a GeoJSON Polygon or MultiPolygon geometry dict."""
        if geom.get("type") == "MultiPolygon":
            return [poly[0] for poly in geom["coordinates"]]
        return [geom["coordinates"][0]]

    colors = ["#0033cc", "#009933", "#cc6600", "#aa00aa", "#00aaaa"]
    for cand, color in zip(candidates, colors):
        for ring in _exterior_rings(cand.catchment.boundary):
            ax.plot([p[0] for p in ring], [p[1] for p in ring], "--", color=color, lw=1.5, alpha=0.8, zorder=3)

        fc = cand.pond_footprint.boundary.coordinates[0]
        ax.fill([p[0] for p in fc], [p[1] for p in fc], color=color, alpha=0.6, zorder=4)
        ax.plot([p[0] for p in fc], [p[1] for p in fc], color=color, lw=2, zorder=4)

        lon, lat = cand.location.longitude, cand.location.latitude
        ax.scatter([lon], [lat], marker="*", s=200, c=color, edgecolor="black", linewidth=1, zorder=5)
        ax.annotate(
            f"Rank {cand.rank}\n{cand.pond_footprint.area_sq_m:.0f} m² pond",
            (lon, lat), textcoords="offset points", xytext=(8, 8), fontsize=9,
            fontweight="bold", color=color,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor=color, alpha=0.9),
        )

    src = f"{source_label} — " if source_label else ""
    ax.set_title(
        f"{src}{len(candidates)} ranked pond candidates\n"
        f"Filled = pond footprint, dashed = catchment, blue = existing drainage",
        fontsize=10,
    )
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=140)
    plt.close(fig)
    buf.seek(0)
    return buf.read()
