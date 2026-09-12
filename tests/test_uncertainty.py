"""Uncertainty estimation, and the refusal to invent it.

The tests that matter most here are the negative ones. A confidence interval built
on two placeholder constants looks exactly like a real one on screen, and the whole
value of the module is that it declines to draw that.
"""

from __future__ import annotations

import dataclasses

import pytest

from kasflex import uncertainty as unc
from kasflex.adapters.greenhouse import SurrogateGreenhouse
from kasflex.energy.assets import EnergyHub
from kasflex.energy.dispatch import HourlyConditions
from kasflex.intent import flat_plan


@pytest.fixture
def hub() -> EnergyHub:
    return EnergyHub()


@pytest.fixture
def plan():
    return flat_plan("2026-09-12", heat_source="boiler", lighting_level=0.4)


@pytest.fixture
def conditions(hub, plan):
    """A cold, dim winter day with a price peak in the evening."""
    base = tuple(
        HourlyConditions(hour=h, outdoor_temp_c=4.0 + 3 * (h > 8 and h < 18),
                         irradiance_w_m2=180.0 if 9 <= h <= 16 else 0.0,
                         power_price_eur_kwh=0.08 + (0.12 if 17 <= h <= 20 else 0.0))
        for h in range(24)
    )
    outcome = SurrogateGreenhouse().simulate_day(plan, base, hub.floor_area_m2)
    return tuple(
        dataclasses.replace(c, heat_demand_kw=outcome.heat_demand_kw[i],
                            co2_demand_kg_h=outcome.co2_demand_kg_h[i])
        for i, c in enumerate(base)
    )


MEASURED = unc.ForecastError(temp_rmse_c=1.4, irradiance_rmse_w_m2=40.0,
                             basis="measured", sample_days=30, source="test fixture")
ASSUMED = unc.ForecastError(temp_rmse_c=2.0, irradiance_rmse_w_m2=60.0, basis="assumed")


def history(n=30, temp=5.0, irradiance=150.0, price=0.10):
    return [{"mean_temp_c": temp + (i % 5) - 2,
             "mean_irradiance_w_m2": irradiance + (i % 7) * 10,
             "mean_price_eur_kwh": price + (i % 3) * 0.01} for i in range(n)]


# -- refusing to invent -----------------------------------------------------


def test_assumed_error_with_no_history_is_not_defensible(hub, plan, conditions):
    result = unc.estimate(plan, hub, conditions, SurrogateGreenhouse(),
                          forecast_error=ASSUMED, novelty=unc.Novelty(known=False))

    assert result.is_defensible is False
    assert result.confidence == "unknown"


def test_an_indefensible_estimate_says_so_in_words(hub, plan, conditions):
    result = unc.estimate(plan, hub, conditions, SurrogateGreenhouse(),
                          forecast_error=ASSUMED, novelty=unc.Novelty(known=False))
    words = unc.describe(result, "en")

    assert "can't tell you" in words["headline"]
    assert "assumption" in words["why"] or "isn't enough data" in words["detail"]


def test_measured_error_alone_is_enough_to_be_defensible(hub, plan, conditions):
    result = unc.estimate(plan, hub, conditions, SurrogateGreenhouse(),
                          forecast_error=MEASURED, novelty=unc.Novelty(known=False))
    assert result.is_defensible is True


def test_known_novelty_alone_is_enough_to_be_defensible(hub, plan, conditions):
    novelty = unc.day_novelty(conditions, history())
    result = unc.estimate(plan, hub, conditions, SurrogateGreenhouse(),
                          forecast_error=ASSUMED, novelty=novelty)
    assert novelty.known is True
    assert result.is_defensible is True


def test_assumed_error_always_carries_a_caveat(hub, plan, conditions):
    result = unc.estimate(plan, hub, conditions, SurrogateGreenhouse(),
                          forecast_error=ASSUMED, novelty=unc.day_novelty(conditions, history()))
    assert any("assumption" in c for c in result.caveats)


def test_the_unvalidated_model_is_always_disclosed(hub, plan, conditions):
    result = unc.estimate(plan, hub, conditions, SurrogateGreenhouse(),
                          forecast_error=MEASURED, novelty=unc.day_novelty(conditions, history()))
    assert any("unvalidated" in c for c in result.caveats)


# -- the band itself --------------------------------------------------------


def test_band_brackets_its_own_centre(hub, plan, conditions):
    result = unc.estimate(plan, hub, conditions, SurrogateGreenhouse(),
                          forecast_error=MEASURED)
    band = result.cost

    assert band is not None
    assert band.low_eur <= band.central_eur <= band.high_eur
    assert band.spread_eur > 0


def test_the_same_seed_gives_the_same_band(hub, plan, conditions):
    kwargs = {"forecast_error": MEASURED, "samples": 12}
    first = unc.estimate(plan, hub, conditions, SurrogateGreenhouse(), seed=7, **kwargs)
    second = unc.estimate(plan, hub, conditions, SurrogateGreenhouse(), seed=7, **kwargs)

    assert first.cost == second.cost, "a band that moves on reload is not a band"


def test_a_bigger_forecast_error_widens_the_band(hub, plan, conditions):
    tight = unc.estimate(plan, hub, conditions, SurrogateGreenhouse(), seed=3,
                         forecast_error=dataclasses.replace(MEASURED, temp_rmse_c=0.3,
                                                            irradiance_rmse_w_m2=8.0))
    loose = unc.estimate(plan, hub, conditions, SurrogateGreenhouse(), seed=3,
                         forecast_error=dataclasses.replace(MEASURED, temp_rmse_c=5.0,
                                                            irradiance_rmse_w_m2=200.0))
    assert loose.cost.spread_eur > tight.cost.spread_eur


def test_uncertain_hours_are_reported(hub, plan, conditions):
    result = unc.estimate(plan, hub, conditions, SurrogateGreenhouse(),
                          forecast_error=MEASURED)
    assert len(result.hours_most_uncertain) <= 3
    assert all(0 <= h <= 23 for h in result.hours_most_uncertain)


def test_a_failing_simulation_yields_no_band_rather_than_a_guess(hub, plan, conditions,
                                                                monkeypatch):
    import kasflex.forecast.cost as cost_module

    def explode(*args, **kwargs):
        raise RuntimeError("greenhouse model unavailable")

    monkeypatch.setattr(cost_module, "project_cost", explode)
    result = unc.estimate(plan, hub, conditions, SurrogateGreenhouse(),
                          forecast_error=MEASURED)

    assert result.cost is None
    assert result.is_defensible is False
    assert any("could not be computed" in c for c in result.caveats)


# -- novelty ----------------------------------------------------------------


def test_no_history_means_unknown_not_zero(conditions):
    novelty = unc.day_novelty(conditions, [])
    assert novelty.known is False
    assert novelty.band == "unknown"


def test_too_little_history_stays_unknown(conditions):
    assert unc.day_novelty(conditions, history(n=3)).known is False


def test_a_typical_day_scores_low(conditions):
    import statistics

    # Centred on today, with real spread. A history of 30 identical days has no
    # variance and is covered separately by the degenerate-history test.
    today = {
        "mean_temp_c": statistics.fmean(c.outdoor_temp_c for c in conditions),
        "mean_irradiance_w_m2": statistics.fmean(c.irradiance_w_m2 for c in conditions),
        "mean_price_eur_kwh": statistics.fmean(c.power_price_eur_kwh for c in conditions),
    }
    around = [{"mean_temp_c": today["mean_temp_c"] + (i % 7) - 3,
               "mean_irradiance_w_m2": today["mean_irradiance_w_m2"] + (i % 5) * 12 - 24,
               "mean_price_eur_kwh": today["mean_price_eur_kwh"] + (i % 3) * 0.01 - 0.01}
              for i in range(30)]

    assert unc.day_novelty(conditions, around).band == "typical"


def test_an_extreme_day_is_flagged_with_its_driver(hub, plan):
    freezing = tuple(HourlyConditions(hour=h, outdoor_temp_c=-18.0, irradiance_w_m2=0.0,
                                      power_price_eur_kwh=0.10) for h in range(24))
    novelty = unc.day_novelty(freezing, history(temp=6.0))

    assert novelty.known is True
    assert novelty.score > 2
    assert "temperature" in novelty.drivers


def test_identical_history_does_not_divide_by_zero(conditions):
    flat = [{"mean_temp_c": 5.0, "mean_irradiance_w_m2": 150.0,
             "mean_price_eur_kwh": 0.1}] * 30
    assert unc.day_novelty(conditions, flat).known is False


# -- measuring the forecast error -------------------------------------------


class FakeCache:
    """A cache of paired forecast/actual weather, with a controllable bias."""

    def __init__(self, days: int, temp_bias: float = 0.0, site: str = "51.990_4.250"):
        self.rows = {}
        for day in range(days):
            iso = f"2026-01-{day + 1:02d}"
            self.rows[f"weather_forecast_{iso}_{site}"] = [
                {"hour": h, "outdoor_temp_c": 5.0 + temp_bias, "irradiance_w_m2": 100.0}
                for h in range(24)]
            self.rows[f"weather_actual_{iso}_{site}"] = [
                {"hour": h, "outdoor_temp_c": 5.0, "irradiance_w_m2": 100.0}
                for h in range(24)]

    def entries(self):
        return dict.fromkeys(self.rows, object())

    def get(self, key):
        return self.rows[key]


def test_enough_paired_days_gives_a_measured_error():
    error = unc.measured_forecast_error(FakeCache(days=20, temp_bias=1.5), 51.99, 4.25)

    assert error.measured is True
    assert error.temp_rmse_c == pytest.approx(1.5, abs=0.01)
    assert error.sample_days == 20
    assert "reanalysis" in error.source


def test_too_few_days_falls_back_to_assumed_and_says_why():
    error = unc.measured_forecast_error(FakeCache(days=2), 51.99, 4.25)

    assert error.measured is False
    assert error.temp_rmse_c == unc.ASSUMED_TEMP_RMSE_C
    assert "needed to measure" in error.source


def test_an_empty_cache_is_not_an_error():
    class Empty:
        def entries(self):
            return {}

        def get(self, key):
            raise KeyError(key)

    assert unc.measured_forecast_error(Empty(), 51.99, 4.25).measured is False


def test_a_different_site_is_not_counted():
    cache = FakeCache(days=20, site="52.500_5.000")
    assert unc.measured_forecast_error(cache, 51.99, 4.25).measured is False


# -- wording ----------------------------------------------------------------


def test_dutch_description_uses_dutch_money_format(hub, plan, conditions):
    result = unc.estimate(plan, hub, conditions, SurrogateGreenhouse(),
                          forecast_error=MEASURED)
    words = unc.describe(result, "nl")

    assert "Waarschijnlijk tussen" in words["headline"]
    assert "€ " in words["headline"]


def test_english_description_reads_as_a_range(hub, plan, conditions):
    result = unc.estimate(plan, hub, conditions, SurrogateGreenhouse(),
                          forecast_error=MEASURED)
    words = unc.describe(result, "en")

    assert words["headline"].startswith("Likely between")
    assert "simulations" in words["why"]


def test_an_unusual_day_is_described_as_needing_care(hub, plan, conditions):
    result = unc.estimate(plan, hub, conditions, SurrogateGreenhouse(),
                          forecast_error=MEASURED,
                          novelty=unc.Novelty(score=4.0, known=True, sample_days=30,
                                              drivers=("temperature",)))
    assert "extra care" in unc.describe(result, "en")["detail"]
    assert result.confidence == "low"


# -- serialisation ----------------------------------------------------------


def test_to_dict_is_json_safe_and_keeps_the_basis(hub, plan, conditions):
    import json

    result = unc.estimate(plan, hub, conditions, SurrogateGreenhouse(),
                          forecast_error=MEASURED,
                          novelty=unc.day_novelty(conditions, history()))
    payload = json.loads(json.dumps(result.to_dict()))

    assert payload["forecast_error"]["basis"] == "measured"
    assert payload["novelty"]["band"] in {"typical", "unusual", "unlike anything seen"}
    assert payload["is_defensible"] is True
    assert payload["confidence"] in {"high", "medium", "low"}
