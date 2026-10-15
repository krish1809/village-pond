"""
Telemetry — OpenTelemetry for the Village Pond API (traces, metrics, logs).

Responsibility: installing the OpenTelemetry SDK once at startup, and defining
the app's own instruments. The rest of the code only uses the OpenTelemetry
*API* (`opentelemetry.trace` / `opentelemetry.metrics`), which is a no-op until
`setup()` installs the SDK. So the analysis modules don't know or care where the
data goes, and the tests (which never call `setup()`) run exactly as before.

Everything is exported as plain OTLP over HTTP and configured with the standard
OpenTelemetry environment variables, so the backend can be swapped without
touching code (OpenObserve here; Jaeger, Grafana Tempo or an OTel Collector would
work the same):

  OTEL_EXPORTER_OTLP_ENDPOINT  base URL, e.g. http://172.17.0.27:5000/api/default
                               (the exporters append /v1/traces, /v1/metrics, /v1/logs)
  OTEL_EXPORTER_OTLP_HEADERS   e.g. Authorization=Basic%20<base64(user:password)>
  OTEL_SERVICE_NAME            defaults to "village-pond-api"
  DEPLOYMENT_ENV               defaults to "lab"

If OTEL_EXPORTER_OTLP_ENDPOINT is not set, `setup()` leaves telemetry off.
"""

import atexit
import logging
import os
import socket
import time
from contextlib import contextmanager
from typing import Optional

from opentelemetry import metrics, trace
from opentelemetry.metrics import CallbackOptions, Observation

SERVICE_VERSION = "0.3.0"

# --- Tracer / meter / logger the app code uses -----------------------------
# Created through the API, so they are proxies until setup() installs the SDK.
tracer = trace.get_tracer("village_pond")
meter = metrics.get_meter("village_pond", SERVICE_VERSION)
log = logging.getLogger("village_pond")

# --- Custom metrics ---------------------------------------------------------
ANALYSES = meter.create_counter(
    "pond.analyses", unit="{analysis}",
    description="Analyses served, by endpoint and outcome (ok / invalid_request / upstream_error / error)",
)
STAGE_DURATION = meter.create_histogram(
    "pond.pipeline.stage.duration", unit="s",
    description="Time spent in each stage of the analysis pipeline",
)
DEM_REQUESTS = meter.create_counter(
    "pond.dem.requests", unit="{request}",
    description="Elevation-model requests, split by in-memory cache hit/miss",
)
UPSTREAM_ERRORS = meter.create_counter(
    "pond.upstream.errors", unit="{error}",
    description="Failures talking to external data services, by service and kind",
)
RAINFALL_LOOKUPS = meter.create_counter(
    "pond.rainfall.lookups", unit="{lookup}",
    description="Rainfall lookups, by source (open-meteo live vs offline fallback)",
)
CANDIDATES_FOUND = meter.create_histogram(
    "pond.candidates.found", unit="{site}",
    description="Number of pond sites returned per analysis",
)
COLLECTABLE_VOLUME = meter.create_histogram(
    "pond.collectable_volume", unit="m3",
    description="Collectable water volume of the suggested ponds",
)


@contextmanager
def stage(name: str, **attributes):
    """
    Run one pipeline stage inside its own span and record how long it took.
    Exceptions are recorded on the span (and mark it as an error) by the SDK.
    """
    attrs = {k: v for k, v in attributes.items() if v is not None}
    start = time.perf_counter()
    with tracer.start_as_current_span(f"pond.{name}", attributes=attrs) as span:
        try:
            yield span
        finally:
            STAGE_DURATION.record(time.perf_counter() - start, {"stage": name})


def current_trace_id() -> Optional[str]:
    """Hex trace id of the active span, or None when tracing is off."""
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None


# --- Resource-usage gauges (the lab containers are capped at 512 MB) --------
def _rss_bytes() -> Optional[int]:
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


def _cgroup_value(name: str) -> Optional[int]:
    try:
        with open(f"/sys/fs/cgroup/{name}") as fh:
            raw = fh.read().strip()
        return None if raw == "max" else int(raw)
    except (OSError, ValueError):
        return None


def _observe_rss(options: CallbackOptions):
    value = _rss_bytes()
    if value is not None:
        yield Observation(value)


def _observe_container_memory(options: CallbackOptions):
    used = _cgroup_value("memory.current")
    limit = _cgroup_value("memory.max")
    if used is not None:
        yield Observation(used, {"kind": "used"})
    if limit is not None:
        yield Observation(limit, {"kind": "limit"})


_providers: list = []


def shutdown() -> None:
    """
    Flush and close the providers so buffered spans, metrics and logs are sent.
    Called from the app's lifespan on shutdown: uvicorn re-raises SIGTERM once it
    has stopped, which kills the process before atexit hooks would run.
    """
    while _providers:
        provider = _providers.pop()
        try:
            provider.shutdown()
        except Exception:
            pass


def configure_console_logging() -> None:
    """App logs to stdout (server.log on the lab box), always on."""
    log.setLevel(logging.INFO)
    log.propagate = False  # our handlers only; avoids duplicates via the root logger
    if not any(isinstance(h, logging.StreamHandler) for h in log.handlers):
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        log.addHandler(console)
    # httpx logs every request URL at INFO -- and the OpenTopography URL carries
    # the API key -- so keep that logger quiet.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def setup(app) -> bool:
    """
    Install the OpenTelemetry SDK (traces, metrics, logs) and auto-instrument the
    FastAPI app. Returns True if telemetry was enabled.
    """
    configure_console_logging()

    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        log.info("OpenTelemetry disabled (OTEL_EXPORTER_OTLP_ENDPOINT not set)")
        return False

    # SDK imports live here so the module stays importable without exporting.
    from opentelemetry._logs import set_logger_provider
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    # Who is sending: attached to every span, metric point and log record.
    resource = Resource.create({
        "service.name": os.environ.get("OTEL_SERVICE_NAME", "village-pond-api"),
        "service.version": SERVICE_VERSION,
        "deployment.environment.name": os.environ.get("DEPLOYMENT_ENV", "lab"),
        "host.name": socket.gethostname(),
    })

    # Traces: batched in the background so exporting never slows a request.
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    # Metrics: pushed every 10 s.
    reader = PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=10_000)
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(meter_provider)
    sdk_meter = metrics.get_meter("village_pond", SERVICE_VERSION)
    sdk_meter.create_observable_gauge(
        "process.memory.rss", callbacks=[_observe_rss], unit="By",
        description="Resident memory of the API process",
    )
    sdk_meter.create_observable_gauge(
        "container.memory", callbacks=[_observe_container_memory], unit="By",
        description="Container (cgroup) memory used vs. its limit",
    )

    # Logs: Python logging -> OTLP. Records emitted inside a span automatically
    # carry its trace_id/span_id, which is what links logs to traces.
    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(logger_provider)
    log.addHandler(LoggingHandler(level=logging.INFO, logger_provider=logger_provider))

    # Auto-instrumentation: one server span (plus duration/active-request metrics)
    # per HTTP request. Static front-end assets are skipped, and so are the ASGI
    # "receive"/"send" sub-spans -- a 6 MB contour upload otherwise produces dozens
    # of them, which buries the pipeline stages in the trace view.
    FastAPIInstrumentor.instrument_app(
        app, excluded_urls="/assets/,/favicon", exclude_spans=["receive", "send"],
    )

    _providers.extend([tracer_provider, meter_provider, logger_provider])
    atexit.register(shutdown)  # backup; the app's lifespan calls shutdown() first

    log.info(
        "OpenTelemetry enabled: exporting traces, metrics and logs",
        extra={"otlp_endpoint": os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"]},
    )
    return True
