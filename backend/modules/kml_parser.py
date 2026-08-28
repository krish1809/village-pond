"""
KML/KMZ Parser — Extract contour lines with elevation from KML/KMZ files.

Responsibility: File I/O and XML parsing ONLY. No terrain logic, no geometry
calculations. Outputs a list of ContourLine dataclass objects.

Supports elevation encoded in:
  1. <name> tag  (primary — e.g., <name>277.0</name>)
  2. Coordinate Z-values  (fallback — lon,lat,elev)
  3. <ExtendedData>  (fallback — SimpleData with name containing 'elev')

Handles both KML (plain XML) and KMZ (ZIP archive containing .kml).
"""

import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import xml.etree.ElementTree as ET


@dataclass
class ContourLine:
    """A single contour line with its elevation and vertex coordinates."""

    elevation: float  # metres
    vertices: List[Tuple[float, float]]  # list of (longitude, latitude)

    @property
    def num_vertices(self) -> int:
        return len(self.vertices)


@dataclass
class ParseResult:
    """Result of parsing a KML/KMZ file."""

    contour_lines: List[ContourLine]
    notes: List[str] = field(default_factory=list)

    @property
    def num_lines(self) -> int:
        return len(self.contour_lines)

    @property
    def elevation_range(self) -> Tuple[Optional[float], Optional[float]]:
        if not self.contour_lines:
            return (None, None)
        elevations = [c.elevation for c in self.contour_lines]
        return (min(elevations), max(elevations))


def _extract_kml_from_kmz(file_bytes: bytes) -> bytes:
    """Extract the first .kml file from a KMZ (ZIP) archive."""
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
        kml_names = [n for n in zf.namelist() if n.lower().endswith(".kml")]
        if not kml_names:
            raise ValueError("KMZ archive contains no .kml file")
        target = "doc.kml" if "doc.kml" in kml_names else kml_names[0]
        return zf.read(target)


_ELEV_RE = re.compile(r"^-?\d+\.?\d*$")


def _parse_coords(text: str) -> List[Tuple[float, float]]:
    """Parse KML coordinates string → list of (lon, lat). Optimized for speed."""
    result = []
    for token in text.split():
        c = token.find(",")
        if c < 0:
            continue
        try:
            lon = float(token[:c])
            rest = token[c + 1:]
            c2 = rest.find(",")
            lat = float(rest[:c2] if c2 > 0 else rest)
            result.append((lon, lat))
        except ValueError:
            continue
    return result


def parse(file_bytes: bytes, filename: str = "unknown") -> ParseResult:
    """
    Parse a KML or KMZ file and extract contour lines with elevation.

    Parameters
    ----------
    file_bytes : bytes
        Raw file content (KML XML or KMZ ZIP archive).
    filename : str
        Original filename, used to detect KMZ by extension.

    Returns
    -------
    ParseResult
        Parsed contour lines and processing notes.

    Raises
    ------
    ValueError
        If the file cannot be parsed or contains no elevation data.
    """
    notes: List[str] = []

    # --- Step 1: Handle KMZ ---
    kml_bytes = file_bytes
    if filename.lower().endswith(".kmz"):
        try:
            kml_bytes = _extract_kml_from_kmz(file_bytes)
            notes.append(f"Extracted KML from KMZ archive: {filename}")
        except (zipfile.BadZipFile, ValueError) as exc:
            raise ValueError(f"Failed to extract KML from KMZ: {exc}") from exc
    elif zipfile.is_zipfile(io.BytesIO(file_bytes)):
        try:
            kml_bytes = _extract_kml_from_kmz(file_bytes)
            notes.append("File detected as ZIP archive, extracted KML")
        except Exception:
            pass

    # --- Step 2: Parse XML with stdlib ElementTree (fast, no lxml overhead) ---
    try:
        root = ET.fromstring(kml_bytes)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid XML in KML file: {exc}") from exc

    # Detect namespace from root tag
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    # --- Step 3: Find all Placemarks via simple iteration ---
    pm_tag = f"{ns}Placemark"
    ls_tag = f"{ns}LineString"
    coord_tag = f"{ns}coordinates"
    name_tag = f"{ns}name"
    simple_data_tag = f"{ns}SimpleData"

    contour_lines: List[ContourLine] = []
    skipped_no_geom = 0
    skipped_no_elev = 0
    elev_sources = {"name": 0, "z_coord": 0, "extended_data": 0}

    for pm in root.iter(pm_tag):
        # --- Get coordinates from LineString ---
        ls = pm.find(f".//{ls_tag}")
        if ls is None:
            skipped_no_geom += 1
            continue
        coord_el = ls.find(coord_tag)
        if coord_el is None or not coord_el.text:
            skipped_no_geom += 1
            continue

        coord_text = coord_el.text.strip()

        # --- Get elevation: try <name> first ---
        elevation: Optional[float] = None
        source = ""

        name_el = pm.find(name_tag)
        if name_el is not None and name_el.text:
            txt = name_el.text.strip()
            if _ELEV_RE.match(txt):
                elevation = float(txt)
                source = "name"

        # --- Fallback: Z-value in coordinates ---
        if elevation is None:
            # Quick check: does the first token have 3 commas?
            first_token = coord_text.split(None, 1)[0] if coord_text else ""
            if first_token.count(",") >= 2:
                parts = first_token.split(",")
                try:
                    z = float(parts[2])
                    if z != 0.0:
                        elevation = z
                        source = "z_coord"
                except (ValueError, IndexError):
                    pass

        # --- Fallback: ExtendedData ---
        if elevation is None:
            for sd in pm.iter(simple_data_tag):
                attr = (sd.get("name") or "").lower()
                if any(k in attr for k in ("elev", "height", "alt", "contour")):
                    try:
                        elevation = float((sd.text or "").strip())
                        source = "extended_data"
                        break
                    except ValueError:
                        continue

        if elevation is None:
            skipped_no_elev += 1
            continue

        # --- Parse coordinates ---
        vertices = _parse_coords(coord_text)
        if len(vertices) < 2:
            skipped_no_geom += 1
            continue

        contour_lines.append(ContourLine(elevation=elevation, vertices=vertices))
        elev_sources[source] += 1

    # --- Reporting ---
    total = len(contour_lines) + skipped_no_geom + skipped_no_elev
    notes.append(f"Found {total} Placemark elements")
    if skipped_no_geom > 0:
        notes.append(f"Skipped {skipped_no_geom} placemarks with no line geometry")
    if skipped_no_elev > 0:
        notes.append(f"Skipped {skipped_no_elev} placemarks with no parseable elevation")

    src_report = ", ".join(f"{k}: {v}" for k, v in elev_sources.items() if v > 0)
    notes.append(f"Elevation sources — {src_report}")

    if not contour_lines:
        raise ValueError(
            "No contour lines with elevation data found. "
            "Elevation must be in <name>, coordinate Z-values, or <ExtendedData>."
        )

    notes.append(f"Successfully parsed {len(contour_lines)} contour lines")
    return ParseResult(contour_lines=contour_lines, notes=notes)
