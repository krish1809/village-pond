"""
Tests for the format=image option on POST /analyzeContour.
"""

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
SAMPLE_KML_PATH = "../contours_1m.kml"


def _read_sample():
    with open(SAMPLE_KML_PATH, "rb") as f:
        return f.read()


def test_format_image_returns_png():
    data = _read_sample()
    resp = client.post(
        "/analyzeContour",
        params={"num_candidates": 3, "format": "image"},
        files={"contour_map": ("contours_1m.kml", data, "application/vnd.google-earth.kml+xml")},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"  # PNG file signature
    assert len(resp.content) > 10_000  # a real rendered map, not an empty/broken image


def test_format_json_is_still_the_default():
    data = _read_sample()
    resp = client.post(
        "/analyzeContour",
        params={"num_candidates": 3},
        files={"contour_map": ("contours_1m.kml", data, "application/vnd.google-earth.kml+xml")},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert "candidates" in body


def test_invalid_format_value_rejected():
    data = _read_sample()
    resp = client.post(
        "/analyzeContour",
        params={"format": "xml"},  # not a supported value
        files={"contour_map": ("contours_1m.kml", data, "application/vnd.google-earth.kml+xml")},
    )
    assert resp.status_code == 422
