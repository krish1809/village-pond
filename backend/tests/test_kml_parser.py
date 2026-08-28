"""
Unit tests for kml_parser module.

Tests:
  - Parser returns non-empty contour list from valid KML
  - Elevation is correctly read from <name> tags
  - Elevation range matches expected values for the sample file
  - KMZ handling works (zip extraction)
  - Invalid XML raises ValueError
  - File with no elevation raises ValueError
"""

import io
import zipfile
import pytest
from modules.kml_parser import parse, ContourLine, ParseResult


MINIMAL_KML = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <Placemark>
    <name>100.0</name>
    <LineString>
      <coordinates>78.0,18.0 78.1,18.1 78.2,18.0</coordinates>
    </LineString>
  </Placemark>
  <Placemark>
    <name>101.0</name>
    <LineString>
      <coordinates>78.0,18.2 78.1,18.3 78.2,18.2</coordinates>
    </LineString>
  </Placemark>
  <Placemark>
    <name>not_a_number</name>
    <LineString>
      <coordinates>78.0,18.4 78.1,18.5</coordinates>
    </LineString>
  </Placemark>
</Document>
</kml>"""

KML_WITH_Z = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <Placemark>
    <LineString>
      <coordinates>78.0,18.0,250.0 78.1,18.1,250.0 78.2,18.0,250.0</coordinates>
    </LineString>
  </Placemark>
</Document>
</kml>"""

NO_ELEVATION_KML = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <Placemark>
    <name>not_numeric</name>
    <LineString>
      <coordinates>78.0,18.0 78.1,18.1</coordinates>
    </LineString>
  </Placemark>
</Document>
</kml>"""


def _make_kmz(kml_bytes: bytes) -> bytes:
    """Wrap KML bytes in a KMZ (ZIP) archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.kml", kml_bytes)
    return buf.getvalue()


# ── Basic parsing ─────────────────────────────────────────────────────────────

def test_parse_returns_parse_result():
    result = parse(MINIMAL_KML, "test.kml")
    assert isinstance(result, ParseResult)


def test_parse_correct_count():
    """Should parse 2 valid contour lines and skip the one with non-numeric name."""
    result = parse(MINIMAL_KML, "test.kml")
    assert result.num_lines == 2


def test_parse_elevation_from_name():
    result = parse(MINIMAL_KML, "test.kml")
    elevations = sorted(cl.elevation for cl in result.contour_lines)
    assert elevations == [100.0, 101.0]


def test_parse_vertices_populated():
    result = parse(MINIMAL_KML, "test.kml")
    for cl in result.contour_lines:
        assert cl.num_vertices >= 2
        assert all(isinstance(v, tuple) and len(v) == 2 for v in cl.vertices)


def test_elevation_range():
    result = parse(MINIMAL_KML, "test.kml")
    assert result.elevation_range == (100.0, 101.0)


# ── Z-coordinate fallback ─────────────────────────────────────────────────────

def test_elevation_from_z_coordinates():
    result = parse(KML_WITH_Z, "test.kml")
    assert result.num_lines == 1
    assert result.contour_lines[0].elevation == 250.0


# ── KMZ handling ──────────────────────────────────────────────────────────────

def test_kmz_extraction():
    kmz_bytes = _make_kmz(MINIMAL_KML)
    result = parse(kmz_bytes, "test.kmz")
    assert result.num_lines == 2


# ── Error cases ───────────────────────────────────────────────────────────────

def test_invalid_xml_raises_value_error():
    with pytest.raises(ValueError, match="Invalid XML"):
        parse(b"this is not xml at all!!!", "bad.kml")


def test_no_elevation_raises_value_error():
    with pytest.raises(ValueError):
        parse(NO_ELEVATION_KML, "no_elev.kml")


def test_empty_file_raises_error():
    with pytest.raises((ValueError, Exception)):
        parse(b"", "empty.kml")


# ── Sample file test (integration — requires the actual file) ─────────────────

def test_sample_kml_file():
    """Integration test against the provided sample contour map."""
    import os
    sample_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "contours_1m.kml"
    )
    if not os.path.exists(sample_path):
        pytest.skip("Sample file not found — skipping integration test")

    with open(sample_path, "rb") as f:
        data = f.read()

    result = parse(data, "contours_1m.kml")

    assert result.num_lines > 100, "Expected many contour lines in sample file"
    lo, hi = result.elevation_range
    assert lo is not None and hi is not None
    assert lo < hi
    assert lo >= 200, "Elevation should be realistic (sample is ~267-298m)"
    assert hi <= 400
