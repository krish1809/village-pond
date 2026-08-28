"""
FastAPI Application Entry Point — Village Pond Planning System API

Phase 2: Contour Map Catchment Analysis
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.analyze_contour import router as analyze_router

app = FastAPI(
    title="Village Pond Planning System API",
    description="""
## Phase 2 — Contour Map Catchment Analysis

This API accepts contour maps (KML/KMZ) and returns:
- **Pond location**: The best candidate site identified by multi-criteria terrain analysis
- **Catchment boundary**: The watershed draining into that site (GeoJSON Polygon)
- **Terrain indices**: TWI, TPI, SPI, curvature values at the identified site
- **Contour summary**: Elevation range, interval, number of contour lines

### Algorithms used
- **Priority-Flood** depression filling (Barnes et al., 2014) — O(n log n) optimal
- **D8** flow direction (O'Callaghan & Mark, 1984)
- **TWI** Topographic Wetness Index (Beven & Kirkby, 1979)
- **TPI** Topographic Position Index (Guisan et al., 1999)  
- **SPI** Stream Power Index (Moore et al., 1991)
- **Plan/Profile Curvature** (Zevenbergen & Thorne, 1987)
- **Multi-criteria weighted suitability scoring**

### Key constraint
All results are computed from the uploaded file — no values are hard-coded.
Works on any KML/KMZ contour map, not just the sample file.
    """,
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
