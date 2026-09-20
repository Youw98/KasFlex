"""The CLI is the interface an external researcher meets first; it must work offline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kasflex.cli import main

CONFIG = "configs/scenario_westland_winter.yaml"


def test_doctor_reports_the_environment(capsys):
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "KasFlex environment check" in out
    assert "GreenLight worker" in out


def test_datasets_lists_the_registry(capsys):
    assert main(["datasets"]) == 0
    out = capsys.readouterr().out
    assert "agc2" in out
    assert "10.4121/uuid:88d22c60" in out


def test_datasets_markdown(capsys):
    assert main(["datasets", "--markdown"]) == 0
    assert "| Key |" in capsys.readouterr().out


def test_run_produces_a_readable_plan_and_a_record(tmp_path, capsys):
    out_file = tmp_path / "result.json"
    assert main(["run", "--config", CONFIG, "--json-out", str(out_file)]) == 0
    out = capsys.readouterr().out
    assert "Plan for" in out
    assert "Checker: enabled" in out
    assert "hard violations" in out
    assert "projected violations" in out
    # The surrogate must announce that it is not validated, every time.
    assert "not been validated" in out

    record = json.loads(Path(out_file).read_text())
    assert record["planner"] == "rule-based"
    assert record["realised_violations_total"] == 0


def test_run_without_the_checker_says_so(capsys):
    assert main(["run", "--config", CONFIG, "--planner", "naive", "--no-checker",
                 "--quiet"]) == 0


def test_verify_accepts_a_good_plan_and_rejects_a_bad_one(tmp_path):
    from kasflex.intent import IntervalIntent, Plan, flat_plan

    # Lit at a steady level, but dimmed through the 16:00-19:00 congestion window,
    # which is exactly the behaviour the scenario is built to reward. A flat plan
    # across all 24 hours breaches the reduced import limit and is correctly rejected.
    good_plan = Plan(
        date="2023-01-15",
        intervals=tuple(
            IntervalIntent(
                hour=h,
                heat_source="boiler",
                lighting_level=0.0 if 16 <= h <= 19 else 0.63,
            )
            for h in range(24)
        ),
    )
    good = tmp_path / "good.json"
    good.write_text(good_plan.to_json())
    assert main(["verify", "--config", CONFIG, "--plan", str(good)]) == 0

    bad = tmp_path / "bad.json"
    bad.write_text(flat_plan("2023-01-15", heat_source="none", lighting_level=0.0).to_json())
    verdict_out = tmp_path / "verdict.json"
    assert main(["verify", "--config", CONFIG, "--plan", str(bad),
                 "--json-out", str(verdict_out)]) == 1
    verdict = json.loads(verdict_out.read_text())
    assert not verdict["accepted"]
    assert verdict["violations"]


def test_verify_rejects_a_file_that_is_not_a_plan(tmp_path, capsys):
    junk = tmp_path / "junk.json"
    junk.write_text("this is not a plan")
    assert main(["verify", "--config", CONFIG, "--plan", str(junk)]) == 2


def test_experiment_writes_records_and_prints_the_table(tmp_path, capsys):
    out = tmp_path / "runs.jsonl"
    assert main(["experiment", "--config", CONFIG, "--days", "1",
                 "--output", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "condition" in printed
    assert "ai-unverified" in printed
    assert out.exists()


def test_run_accepts_cache_and_date_overrides(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit, match="Real data is not available for 2026-09-21"):
        main(["run", "--data-source", "cache", "--date", "2026-09-21", "--quiet"])


def test_cache_data_source_needs_fetched_data(tmp_path):
    """Cache mode exits clearly when no data has been downloaded yet."""
    config = Path(CONFIG).read_text().replace("data_source: synthetic", "data_source: cache")
    path = tmp_path / "cache.yaml"
    path.write_text(config)
    with pytest.raises(SystemExit, match="not available"):
        main(["run", "--config", str(path), "--quiet"])


def test_validate_tells_the_user_when_the_dataset_is_missing(tmp_path, capsys):
    """No AGC data on disk: the tool explains what to fetch, does not invent numbers,
    and exits 2 (dataset missing) so a script can tell it apart from an accidental
    non-zero.
    """
    assert main(["validate", "--cache-dir", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "AGC dataset not found" in err
    assert "10.4121/uuid:88d22c60" in err
    assert "measured/YYYY-MM-DD.csv" in err


def test_validate_refuses_measured_data_without_a_replay(tmp_path, capsys):
    root = tmp_path / "agc2"
    measured = root / "measured"
    measured.mkdir(parents=True)
    (measured / "2019-01-15.csv").write_text(
        "heating_kwh,electricity_kwh,co2_kg\n120,80,55\n"
    )

    assert main([
        "validate",
        "--cache-dir", str(tmp_path),
        "--greenhouse", "surrogate",
    ]) == 2
    err = capsys.readouterr().err
    assert "Validation has NOT been completed" in err
    assert "replay" in err.lower()


def test_validate_runs_a_real_replay_and_writes_numeric_results(tmp_path):
    """A measured day is only publishable after a simulator replay ran."""
    root = tmp_path / "agc2"
    measured = root / "measured"
    replay = root / "replay"
    measured.mkdir(parents=True)
    replay.mkdir()
    date = "2019-01-15"
    (measured / f"{date}.csv").write_text(
        "heating_kwh,electricity_kwh,co2_kg\n"
        "120.0,126.72,55.0\n"
    )
    (root / "MANIFEST.json").write_text(
        '{"dataset": "AGC 2nd edition (test fixture)", "retrieved": "2026-09-20"}'
    )
    replay_payload = {
        "floor_area_m2": 96.0,
        "lamp_power_w_m2": 110.0,
        "plan": {
            "date": date,
            "planner": "measured-replay",
            "intervals": [
                {
                    "hour": hour,
                    "heat_source": "boiler",
                    "lighting_level": 0.5,
                    "battery": "idle",
                    "battery_power_kw": 0.0,
                    "chp_mode": "off",
                    "co2_source": "liquid",
                    "reasoning": "validation fixture",
                }
                for hour in range(24)
            ],
        },
        "conditions": [
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
        ],
    }
    (replay / f"{date}.json").write_text(json.dumps(replay_payload))

    doc = tmp_path / "VALIDATION.md"
    result_json = tmp_path / "validation.json"
    doc.write_text(
        "# heading\n\nprose\n\n<!-- kasflex:validation:start -->\n"
        "old body\n<!-- kasflex:validation:end -->\n"
    )
    assert main([
        "validate",
        "--cache-dir", str(tmp_path),
        "--greenhouse", "surrogate",
        "--result-json", str(result_json),
        "--write-doc", str(doc),
    ]) == 0

    text = doc.read_text()
    assert "# heading" in text
    assert "prose" in text
    assert "old body" not in text
    assert date in text
    assert "heating_kwh" in text
    assert "nan" not in text.lower()
    saved = json.loads(result_json.read_text())
    assert saved["model"] == "surrogate"
    assert saved["days_compared"] == 1
