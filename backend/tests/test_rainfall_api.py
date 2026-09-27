"""Tests for the rainfall lookup (Phase 3), focused on the offline-safe parts."""

from modules import rainfall_api


def test_summarise_computes_mean_annual_and_monthly():
    # Two years, 1 mm every day → ~365 mm/year.
    times, precip = [], []
    for year in ("2022", "2023"):
        for month in range(1, 13):
            for day in range(1, 29):  # 28 days each month keeps it simple
                times.append(f"{year}-{month:02d}-{day:02d}")
                precip.append(1.0)
    res = rainfall_api._summarise(times, precip, years=2)

    assert res.source == "open-meteo"
    assert res.years_averaged == 2
    assert len(res.monthly_climatology_mm) == 12
    # 28 days * 12 months = 336 mm per year
    assert abs(res.annual_rainfall_mm - 336.0) < 1.0
    # each month averaged over 2 years = 28 mm
    assert all(abs(m - 28.0) < 0.5 for m in res.monthly_climatology_mm)


def test_summarise_skips_none_values():
    times = ["2022-01-01", "2022-01-02", "2022-01-03"]
    precip = [10.0, None, 5.0]
    res = rainfall_api._summarise(times, precip, years=1)
    assert res.annual_rainfall_mm == 15.0


def test_fallback_marks_source_and_uses_default():
    fb = rainfall_api._fallback()
    assert fb.source == "fallback"
    assert fb.annual_rainfall_mm == rainfall_api.FALLBACK_ANNUAL_RAINFALL_MM
    assert fb.annual_rainfall_m == rainfall_api.FALLBACK_ANNUAL_RAINFALL_MM / 1000.0


def test_annual_rainfall_falls_back_when_service_unreachable(monkeypatch):
    import httpx

    def boom(*args, **kwargs):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(rainfall_api.httpx, "get", boom)
    # use a coordinate unlikely to be cached from a previous test
    res = rainfall_api.annual_rainfall(1.2345, 2.3456)
    assert res.source == "fallback"
