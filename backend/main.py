"""
FastAPI Application Entry Point — Village Pond Planning System API

Phase 2: Contour Map Catchment Analysis (POST /analyzeContour)
Phase 3: Map-region analysis with water volume (POST /analyzeArea) + web front-end

The compiled React front-end (frontend/dist copied to backend/static) is served
by this same app, so the whole system runs as one process behind one URL.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import telemetry
from api.routes.analyze_contour import router as analyze_router
from api.routes.analyze_area import router as area_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Send any telemetry still buffered before the process exits.
    telemetry.shutdown()


app = FastAPI(
    lifespan=lifespan,
    title="Village Pond Planning System API",
    description=(
        "Analyses terrain to plan village ponds. Two ways in: upload a contour "
        "map (POST /analyzeContour), or select a region on the map and let the "
        "system fetch its elevation and rainfall (POST /analyzeArea). Every result "
        "is computed from the terrain/rainfall of the input — nothing is hard-coded "
        "to any one place."
    ),
    version="0.3.0",
    contact={"name": "Village Pond Planning System"},
    license_info={"name": "MIT"},
)

# CORS — allow all for dev/demo; the built front-end is same-origin so this is
# mainly for calling the API directly from other tools during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Echo the request's trace id back to the caller, so a slow or failed request
# seen in the browser can be looked up directly in the tracing backend.
@app.middleware("http")
async def add_trace_id_header(request: Request, call_next):
    response = await call_next(request)
    trace_id = telemetry.current_trace_id()
    if trace_id:
        response.headers["X-Trace-Id"] = trace_id
    return response


# Register API routes BEFORE the static mount, so explicit routes always win
# over the catch-all that serves the single-page app.
app.include_router(analyze_router)
app.include_router(area_router)

# OpenTelemetry: traces, metrics and logs over OTLP (a no-op unless
# OTEL_EXPORTER_OTLP_ENDPOINT is set -- see telemetry.py).
telemetry.setup(app)


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint — confirms the API is running."""
    return {
        "status": "ok",
        "service": "Village Pond Planning System API",
        "phase": 3,
        "endpoints": {
            "analyze_contour": "POST /analyzeContour",
            "analyze_area": "POST /analyzeArea",
            "docs": "/docs",
            "openapi": "/openapi.json",
        },
    }


# --- Serve the compiled front-end (if present) at the site root ---
# In development the front-end runs from Vite (npm run dev); in the deployed
# build we copy frontend/dist into backend/static, and this mount serves it.
# Mounted last so it only handles paths the API routes above didn't claim.
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="frontend")
