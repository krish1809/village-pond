"""
FastAPI Application Entry Point — Village Pond Planning System API

Phase 2: Contour Map Catchment Analysis
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.analyze_contour import router as analyze_router

app = FastAPI(
    title="Village Pond Planning System API",
    description=(
        "Phase 2 — accepts a contour map (KML/KMZ), builds an elevation model "
        "from it, and returns ranked candidate pond sites with the catchment "
        "area draining into each one. Everything in the response is computed "
        "from the uploaded file; nothing is hard-coded to the sample map."
    ),
    version="0.2.0",
    contact={"name": "Village Pond Planning System"},
    license_info={"name": "MIT"},
)

# CORS — allow all for dev/demo; restrict origin list in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(analyze_router)


@app.get("/", tags=["Health"])
async def health_check():
    """Health check endpoint — confirms the API is running."""
    return {
        "status": "ok",
        "service": "Village Pond Planning System API",
        "phase": 2,
        "endpoints": {
            "analyze_contour": "POST /analyzeContour",
            "docs": "/docs",
            "openapi": "/openapi.json",
        },
    }
