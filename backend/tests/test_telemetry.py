"""Tests for the OpenTelemetry instrumentation (Lab 8).

Spans are captured with an in-memory exporter, so no collector or network is
needed. Only manual spans are checked here: setup() is not called in tests, so
the FastAPI auto-instrumentation (server spans) is not installed.
"""

import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import telemetry
from main import app

SAMPLE_KML_PATH = "../contours_1m.kml"
_exporter = InMemorySpanExporter()


@pytest.fixture(scope="module", autouse=True)
def tracing():
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(_exporter))
    yield


@pytest.fixture(autouse=True)
def clear_spans():
    _exporter.clear()
    yield


def test_stage_creates_named_span_with_attributes():
    with telemetry.stage("unit_test", **{"grid.cells": 42, "skipped": None}):
        pass
    spans = _exporter.get_finished_spans()
    assert [s.name for s in spans] == ["pond.unit_test"]
    assert spans[0].attributes["grid.cells"] == 42
    assert "skipped" not in spans[0].attributes  # None values are dropped


def test_stage_marks_span_as_error_on_exception():
    with pytest.raises(ValueError):
        with telemetry.stage("failing"):
            raise ValueError("boom")
    span = _exporter.get_finished_spans()[0]
    assert span.status.status_code == trace.StatusCode.ERROR
    assert any(e.name == "exception" for e in span.events)


def test_current_trace_id_inside_and_outside_span():
    assert telemetry.current_trace_id() is None
    with telemetry.stage("tid"):
        tid = telemetry.current_trace_id()
    assert tid is not None and len(tid) == 32


def test_contour_analysis_emits_pipeline_spans():
    with open(SAMPLE_KML_PATH, "rb") as fh:
        data = fh.read()
    resp = TestClient(app).post(
        "/analyzeContour?num_candidates=2",
        files={"contour_map": ("contours_1m.kml", data, "application/vnd.google-earth.kml+xml")},
    )
    assert resp.status_code == 200
    names = [s.name for s in _exporter.get_finished_spans()]
    for expected in ("pond.parse_contours", "pond.build_grid", "pond.flow_routing",
                     "pond.rank_candidates", "pond.candidate"):
        assert expected in names, f"missing span {expected}: {names}"
    assert names.count("pond.candidate") == 2
