"""The browser must use the selected inputs, never a silent synthetic substitute."""
from pathlib import Path

import pytest

from kasflex.data.cache import DataCache
from kasflex.ui.server import ApiError, UiServer


@pytest.fixture
def real_ui(tmp_path, monkeypatch):
    config = Path("configs/scenario_westland_winter.yaml").resolve()
    monkeypatch.chdir(tmp_path)
    return UiServer(config_path=str(config))


def seed_cache():
    cache = DataCache()
    common = {"source": "test fixture", "licence": "test only", "prefer_parquet": False}
    cache.put("entsoe_da_2023-01-15",
              [{"hour": h, "price_eur_kwh": 0.321} for h in range(24)], **common)
    cache.put("weather_forecast_2023-01-15_51.990_4.250",
              [{"hour": h, "outdoor_temp_c": 10, "irradiance_w_m2": 0}
               for h in range(24)], **common)
    return cache


def test_real_mode_refuses_missing_data(real_ui):
    with pytest.raises(ApiError, match="Real data is not ready"):
        real_ui.run({"data_source": "cache"})


def test_real_mode_uses_prices_and_labels_forecast_only(real_ui):
    seed_cache()
    result = real_ui.run({"data_source": "cache"})
    assert all(row["power_price_eur_kwh"] == 0.321 for row in result["plan"])
    assert result["data_source"] == "cache"
    assert result["actuals_available"] is False
    assert result["series_origin"]["forecast_weather"] == "cache"


def test_status_checks_integrity_and_never_returns_a_token(real_ui, monkeypatch):
    cache = seed_cache()
    monkeypatch.setenv("ENTSOE_API_KEY", "test-secret-not-for-display")
    status = real_ui.data_status({})
    assert status["ready"] is True
    assert status["entsoe_configured"] is True
    assert "test-secret" not in str(status)
    entry = cache.entries()["entsoe_da_2023-01-15"]
    (cache.root / entry.filename).write_text("broken")
    assert real_ui.data_status({})["ready"] is False


def test_gas_assumption_affects_demo_cost(real_ui):
    low = real_ui.run({"gas_price_eur_kwh": 0.01})
    high = real_ui.run({"gas_price_eur_kwh": 0.1})
    assert high["metrics"]["net_cost_eur"] > low["metrics"]["net_cost_eur"]


def test_historical_download_does_not_replace_forecasts_with_observations(real_ui):
    with pytest.raises(ApiError, match="archived forecasts"):
        real_ui.data_status({"date": "2023-01-15"}, download=True)


def test_duplicate_hours_and_missing_weather_are_rejected():
    from datetime import date

    from kasflex.data.pipeline import _column
    from kasflex.data.sources import FetchError, parse_openmeteo_hourly

    with pytest.raises(FetchError, match="exactly once"):
        _column([{"hour": 0, "price": 0.1}] * 24, "price")
    with pytest.raises(FetchError, match="non-finite"):
        _column([{"hour": h, "price": float("nan")} for h in range(24)], "price")
    payload = {"hourly": {"time": ["2023-01-15T00:00"],
                          "temperature_2m": [None], "shortwave_radiation": [0]}}
    with pytest.raises(FetchError, match="missing weather"):
        parse_openmeteo_hourly(payload, date(2023, 1, 15))
