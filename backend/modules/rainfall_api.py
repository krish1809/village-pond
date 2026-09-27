"""
Rainfall API — Fetch mean annual rainfall for a location from the Open-Meteo
historical weather archive, with an offline fallback.

Responsibility: rainfall lookup ONLY. It returns a rainfall figure (and a bit of
context for charting); it does not compute runoff or volumes — that's
water_volume.py's job.

We use Open-Meteo's historical archive (https://archive-api.open-meteo.com), which
is free and needs no key, pulling daily precipitation totals for the last several
full years and averaging them into a mean annual rainfall. Averaging over ~10
years smooths out wet/dry-year swings so the pond sizing isn't tuned to a single
freak year.

Robustness: the archive is an external service, so every call is wrapped with a
timeout and a try/except. If it's unreachable (e.g. the demo machine is offline),
we fall back to a documented default annual rainfall rather than failing the whole
analysis — the response clearly flags which source was used.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

import httpx

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# How many full past years to average over.
YEARS_TO_AVERAGE = 10

REQUEST_TIMEOUT_S = 20.0

# Fallback mean annual rainfall (mm) used only if the archive can't be reached.
# ~1100 mm is a reasonable central-India average; it's a stated assumption, not a
# silent magic number, and the response marks the source as "fallback" when used.
FALLBACK_ANNUAL_RAINFALL_MM = 1100.0

_CACHE: Dict[tuple, "RainfallResult"] = {}


@dataclass
class RainfallResult:
    """Rainfall context for a location."""

    annual_rainfall_mm: float           # mean annual total
    source: str                         # "open-meteo" or "fallback"
    years_averaged: int
    monthly_climatology_mm: List[float] = field(default_factory=list)  # 12 values, Jan..Dec
    notes: List[str] = field(default_factory=list)

    @property
    def annual_rainfall_m(self) -> float:
        return self.annual_rainfall_mm / 1000.0


def _summarise(times: List[str], daily_mm: List[Optional[float]], years: int) -> RainfallResult:
    """Turn a daily precipitation series into mean-annual + monthly climatology."""
    monthly_totals = [0.0] * 12
    monthly_years = [set() for _ in range(12)]
    grand_total = 0.0
    year_set = set()

    for t, v in zip(times, daily_mm):
        if v is None:
            continue
        month = int(t[5:7]) - 1
        year = t[:4]
        monthly_totals[month] += v
        monthly_years[month].add(year)
        grand_total += v
        year_set.add(year)

    n_years = max(1, len(year_set))
    annual_mean = grand_total / n_years
    monthly_clim = [
        monthly_totals[m] / max(1, len(monthly_years[m])) for m in range(12)
    ]

    return RainfallResult(
        annual_rainfall_mm=round(annual_mean, 1),
        source="open-meteo",
        years_averaged=n_years,
        monthly_climatology_mm=[round(x, 1) for x in monthly_clim],
        notes=[
            f"Mean annual rainfall averaged over {n_years} year(s) of Open-Meteo "
            f"historical daily precipitation"
        ],
    )


def _fallback() -> RainfallResult:
    return RainfallResult(
        annual_rainfall_mm=FALLBACK_ANNUAL_RAINFALL_MM,
        source="fallback",
        years_averaged=0,
        monthly_climatology_mm=[],
        notes=[
            "Rainfall service unreachable — using a documented default annual "
            f"rainfall of {FALLBACK_ANNUAL_RAINFALL_MM:.0f} mm. Volume figures are "
            "therefore indicative; connect the machine to refresh with live data."
        ],
    )


def annual_rainfall(lat: float, lon: float) -> RainfallResult:
    """
    Mean annual rainfall (mm) for a location, from the Open-Meteo archive.

    Falls back to FALLBACK_ANNUAL_RAINFALL_MM if the service can't be reached.
    Cached in-memory by rounded coordinate.
    """
    cache_key = (round(lat, 2), round(lon, 2))
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    end_year = date.today().year - 1  # last complete calendar year
    start_year = end_year - YEARS_TO_AVERAGE + 1
    params = {
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "start_date": f"{start_year}-01-01",
        "end_date": f"{end_year}-12-31",
        "daily": "precipitation_sum",
        "timezone": "UTC",
    }

    try:
        resp = httpx.get(ARCHIVE_URL, params=params, timeout=REQUEST_TIMEOUT_S)
        resp.raise_for_status()
        daily = resp.json().get("daily", {})
        times = daily.get("time", [])
        precip = daily.get("precipitation_sum", [])
        if not times or not precip:
            result = _fallback()
        else:
            result = _summarise(times, precip, YEARS_TO_AVERAGE)
    except (httpx.HTTPError, ValueError, KeyError):
        result = _fallback()

    _CACHE[cache_key] = result
    return result
