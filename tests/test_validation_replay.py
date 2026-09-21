from __future__ import annotations

import json
import math

import pytest

from kasflex.validation import (
    ValidationNotRunnable,
    replay_simulator,
    validate_against_agc,
    validation_status,
    write_validation_json,
)


def _flat_replay(date: str) -> dict:
    intervals = [
        {
            "hour": hour,
            "heat_source": "boiler",
            "lighting_level": 0.5,
            "battery": "idle",
            "battery_power_kw": 0.0,
            "chp_mode": "off",
            "co2_source": "liquid",
            "reasoning": "measured-day replay fixture",
        }
        for hour in range(24)
    ]
    conditions = [
        {
            "hour": hour,
            "heat_demand_kw": 0.0,
            "co2_demand_kg_h": 0.0,
            "irradiance_w_m2": 0.0,
            "outdoor_temp_c": 5.0,
            "power_price_eur_kwh": 0.1,
            "gas_price_eur_kwh": 0.035,
            "feed_in_price_eur_kwh": None,
        }
        for hour in range(24)
    ]
    return {
        "floor_area_m2": 96.0,
        "lamp_power_w_m2": 110.0,
        "plan": {"date": date, "planner": "measured-replay", "intervals": intervals},
        "conditions": conditions,
    }


def _agc_fixture(tmp_path):
    root = tmp_path / "agc2"
    measured = root / "measured"
    replay = root / "replay"
    measured.mkdir(parents=True)
    replay.mkdir()
    (root / "MANIFEST.json").write_text(
        json.dumps(
            {
                "dataset": "AGC 2nd edition - Reference compartment test fixture",
                "licence": "CC0",
            }
        )
    )
    date = "2020-01-15"
    (measured / f"{date}.csv").write_text(
        "heating_kwh,electricity_kwh,co2_kg\n100,126.72,5\n"
    )
    (replay / f"{date}.json").write_text(json.dumps(_flat_replay(date)))
    return date


def test_validation_refuses_measured_only_nan_style_reports(tmp_path):
    with pytest.raises(ValidationNotRunnable, match="No simulator replay"):
        validate_against_agc(tmp_path, simulate_day=None)


def test_canonical_replay_runs_a_real_simulator_and_produces_finite_errors(tmp_path):
    _agc_fixture(tmp_path)
    report = validate_against_agc(
        tmp_path,
        simulate_day=replay_simulator(tmp_path, model="surrogate"),
    )
    assert report.days_compared == 1
    assert len(report.deviations) == 3
    assert all(math.isfinite(row.simulated) for row in report.deviations)
    assert all(math.isfinite(row.absolute_error) for row in report.deviations)
    assert report.summaries()["heating_kwh"]["mae"] >= 0
    markdown = report.to_markdown()
    assert "## Aggregate error" in markdown
    assert "Mean absolute relative error" in markdown


def test_only_completed_numeric_validation_becomes_green_status(tmp_path):
    _agc_fixture(tmp_path)
    report = validate_against_agc(
        tmp_path,
        simulate_day=replay_simulator(tmp_path, model="surrogate"),
    )
    result = tmp_path / "validation.json"
    write_validation_json(report, result, model="surrogate")
    status = validation_status(result)
    assert status["validated"] is True
    assert status["days_compared"] == 1
    assert status["model"] == "surrogate"
    assert "not a calibration pass" in status["message"]

    result.write_text(
        json.dumps(
            {
                "days_compared": 1,
                "deviations": [{"measured": 1.0, "simulated": float("nan")}],
            }
        )
    )
    assert validation_status(result)["validated"] is False
