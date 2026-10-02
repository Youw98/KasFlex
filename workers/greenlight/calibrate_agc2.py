"""Fit GreenLight construction parameters to an AGC2 compartment, then test them.

Run inside the GreenLight worker environment, on a cache prepared with
``kasflex prepare-agc2 --all-days --compartment <name>``::

    ./.venv-greenlight/bin/python workers/greenlight/calibrate_agc2.py \\
        --cache-dir data/cache --out results/calibration-agc2.json

Days are split by ISO week: even weeks fit, odd weeks test. Whole weeks rather
than alternate days, so a test day is never the day after a training day with
nearly the same weather. The search is a coordinate search over parameters with
a physical meaning, each over a short explicit list of values, starting from the
previous calibration; ``etaLampCool`` is fixed at 0 because it is a fact about
the lamps, not a free parameter (see ``AGC2_CALIBRATION`` in
``kasflex.validation_agc2``). The score weighs daily heat, daily CO2 and hourly
indoor air temperature, so a fit cannot buy lower heat with a greenhouse that
runs too warm.

``--confirm-cache-dir`` scores the result, without refitting, on a second
compartment prepared the same way (for example ``--compartment Reference``).

Heat is compared as the AGC2 dataset defines it: pipe heat release computed from
pipe and air temperature, not boiler input. See docs/CALIBRATION.md.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import warnings
from datetime import date
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

#: Values tried per parameter. Ranges: aCov from roof glass only to gl-gym's
#: free-standing house (per 144 m2 model floor); aRoof from 5% to gl-gym's 36% of
#: floor area; cLeakage around gl-gym's default; tauRfNir from diffuse to clear
#: glass; kThScr and tauThScrFir a factor of about four either side of gl-gym.
CANDIDATES = {
    "aCov": (140.0, 156.0, 180.0, 216.6),
    "aRoof": (7.2, 12.0, 17.4, 26.0, 52.2),
    "cLeakage": (0.5e-5, 1e-5, 2e-5, 3e-5),
    "tauRfNir": (0.45, 0.57, 0.7, 0.85),
    "kThScr": (1.25e-4, 2.5e-4, 5e-4, 1e-3, 2e-3),
    "tauThScrFir": (0.05, 0.15, 0.3, 0.5),
}
#: Where the search starts: the previous calibration, gl-gym defaults elsewhere.
START = {"aCov": 156.0, "aRoof": 17.4, "cLeakage": 1e-5, "tauRfNir": 0.57,
         "kThScr": 5e-4, "tauThScrFir": 0.15}
PREVIOUS = {"etaLampCool": 0.0, "aCov": 156.0, "aRoof": 17.4, "cLeakage": 1e-5}
FIXED = {"etaLampCool": 0.0}
PASSES = 2


def score(summary: dict) -> float:
    """Equal weight to a typical daily heat error (~50 kWh), daily CO2 error (~3 kg)
    and hourly indoor temperature error (~2 K)."""
    return (summary["heating_kwh"]["mae"] / 50.0 + summary["co2_kg"]["mae"] / 3.0
            + summary["temp_c"]["mae"] / 2.0)


def split(iso_day: str) -> str:
    return "fit" if date.fromisoformat(iso_day).isocalendar()[1] % 2 == 0 else "test"


def _simulate(job: tuple[str, str, dict[str, float]]) -> tuple[str, dict[str, float] | None]:
    root, iso_day, calibration = job
    warnings.filterwarnings("ignore")
    import worker  # noqa: PLC0415 - imported in the pool process

    payload = json.loads((Path(root) / "replay" / f"{iso_day}.json").read_text())
    request = {
        "plan": payload["plan"],
        "floor_area_m2": float(payload["floor_area_m2"]),
        "seed": int(payload.get("seed", 0)),
        "scenario": payload["greenlight_scenario"],
        "env_kwargs": payload["greenlight_env_kwargs"],
        "replay_controls": payload["replay_controls"],
        "parameter_overrides": payload.get("greenlight_parameter_overrides") or {},
        "calibration": calibration,
    }
    try:
        outcome = worker.simulate_day(request)
    except Exception:  # noqa: BLE001 - a failed day is counted, never silently scored
        return iso_day, None
    diagnostics = outcome["diagnostics"]
    return iso_day, {
        "heating_kwh": diagnostics["pipe_heat_agc_formula_kwh"],
        "boiler_kwh": diagnostics["heating_energy_kwh"],
        "electricity_kwh": diagnostics["lighting_electricity_kwh"],
        "co2_kg": diagnostics["co2_dosed_kg"],
        "temp_c": [float(t) for t in outcome["temp_c"]],
    }


def _measured(root: Path, iso_day: str) -> dict[str, object]:
    with (root / "measured" / f"{iso_day}.csv").open() as handle:
        totals: dict[str, object] = {
            key: float(value) for key, value in next(csv.DictReader(handle)).items()}
    replay = json.loads((root / "replay" / f"{iso_day}.json").read_text())
    measured_indoor = replay.get("measured_indoor") or {}
    if "temperature_c" not in measured_indoor:
        raise SystemExit("the cache has no measured indoor temperature; re-run "
                         "kasflex prepare-agc2 with this version")
    totals["temp_c"] = [float(t) for t in measured_indoor["temperature_c"]]
    return totals


def evaluate(pool: Pool, root: Path, days: list[str], calibration: dict[str, float]) -> dict:
    simulated = dict(pool.map(_simulate, [(str(root), day, calibration) for day in days]))
    failed = sorted(day for day, value in simulated.items() if value is None)
    rows = [(day, _measured(root, day), simulated[day]) for day in days if simulated[day]]
    summary: dict[str, object] = {"days": len(rows), "failed_days": failed}
    temp_errors = [s_t - m_t for _day, meas, sim in rows
                   for s_t, m_t in zip(sim["temp_c"], meas["temp_c"], strict=True)]
    midday = [s_t - m_t for _day, meas, sim in rows
              for hour, (s_t, m_t) in enumerate(zip(sim["temp_c"], meas["temp_c"],
                                                    strict=True)) if 11 <= hour <= 15]
    summary["temp_c"] = {
        "mae": sum(abs(e) for e in temp_errors) / len(temp_errors),
        "bias": sum(temp_errors) / len(temp_errors),
        "midday_bias": sum(midday) / len(midday),
    }
    for quantity in ("heating_kwh", "co2_kg", "electricity_kwh"):
        errors = [sim[quantity] - meas[quantity] for _day, meas, sim in rows]
        relative = [
            abs(sim[quantity] - meas[quantity]) / meas[quantity]
            for _day, meas, sim in rows
            if meas[quantity] > 1e-9
        ]
        summary[quantity] = {
            "mae": sum(abs(e) for e in errors) / len(errors),
            "bias": sum(errors) / len(errors),
            "mean_abs_relative_error_pct": 100 * sum(relative) / len(relative),
            "simulated_over_measured_total": (
                sum(sim[quantity] for _d, _m, sim in rows)
                / sum(meas[quantity] for _d, meas, _s in rows)
            ),
        }
    per_day = {
        day: {**{k: v for k, v in sim.items() if k != "temp_c"},
              "measured_heating_kwh": meas["heating_kwh"],
              "temp_mae_c": sum(abs(a - b) for a, b in zip(sim["temp_c"], meas["temp_c"],
                                                         strict=True)) / 24}
        for day, meas, sim in rows
    }
    return {"summary": summary, "per_day": per_day}


def by_month(per_day: dict[str, dict]) -> dict[str, dict[str, float]]:
    """Mean measured and simulated heat, and temperature error, per month."""
    months: dict[str, list[dict]] = {}
    for day, row in per_day.items():
        months.setdefault(day[:7], []).append(row)
    return {
        month: {
            "days": len(rows),
            "measured_heating_kwh": sum(r["measured_heating_kwh"] for r in rows) / len(rows),
            "simulated_heating_kwh": sum(r["heating_kwh"] for r in rows) / len(rows),
            "temp_mae_c": sum(r["temp_mae_c"] for r in rows) / len(rows),
        }
        for month, rows in sorted(months.items())
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=Path("data/cache"))
    parser.add_argument("--confirm-cache-dir", type=Path, default=None,
                        help="a second compartment's cache, scored without refitting")
    parser.add_argument("--out", type=Path, default=Path("results/calibration-agc2.json"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)

    root = args.cache_dir / "agc2"
    manifest = json.loads((root / "MANIFEST.json").read_text())
    days = sorted(path.stem for path in (root / "replay").glob("*.json"))
    fit = [day for day in days if split(day) == "fit"]
    test = [day for day in days if split(day) == "test"]
    if not fit or not test:
        raise SystemExit("need both even-week and odd-week days; prepare with --all-days")

    search = []
    seen: dict[tuple, float] = {}
    with Pool(args.workers) as pool:
        def trial(values: dict[str, float]) -> float:
            key = tuple(sorted(values.items()))
            if key not in seen:
                calibration = {**FIXED, **values}
                summary = evaluate(pool, root, fit, calibration)["summary"]
                seen[key] = score(summary)
                search.append({"calibration": calibration, "score": seen[key], "fit": summary})
                print(json.dumps({"calibration": calibration, "score": round(seen[key], 3)}),
                      flush=True)
            return seen[key]

        current = dict(START)
        for _ in range(PASSES):
            for name, options in CANDIDATES.items():
                current[name] = min(options, key=lambda v, n=name: trial({**current, n: v}))
        best = {**FIXED, **current}
        configurations = (
            ("gl_gym_defaults", {}),
            ("lamp_cooling_only", dict(FIXED)),
            ("previous_calibration", dict(PREVIOUS)),
            ("calibrated", best),
        )
        results = {}
        for label, calibration in configurations:
            held_out = evaluate(pool, root, test, calibration)
            results[label] = {
                "fit": evaluate(pool, root, fit, calibration)["summary"],
                "test": held_out,
                "test_by_month": by_month(held_out["per_day"]),
            }
        confirmation = None
        if args.confirm_cache_dir is not None:
            other = args.confirm_cache_dir / "agc2"
            other_manifest = json.loads((other / "MANIFEST.json").read_text())
            other_days = sorted(path.stem for path in (other / "replay").glob("*.json"))
            confirmation = {"compartment": other_manifest.get("compartment"),
                            "archive_checksum_verified":
                                other_manifest.get("archive_checksum_verified"),
                            "days": len(other_days), "results": {}}
            for label, calibration in configurations:
                scored = evaluate(pool, other, other_days, calibration)
                confirmation["results"][label] = {"summary": scored["summary"],
                                                  "by_month": by_month(scored["per_day"])}

    record = {
        "dataset": manifest.get("dataset"),
        "compartment": manifest.get("compartment"),
        "archive_checksum_verified": manifest.get("archive_checksum_verified"),
        "heat_definition": "AGC2 Heat_cons formula applied to simulated pipe temperatures",
        "temperature_definition": "hourly mean of measured Tair against simulated air temperature",
        "split": "even ISO weeks fit, odd ISO weeks test",
        "score": "heat MAE / 50 kWh + CO2 MAE / 3 kg + hourly temperature MAE / 2 K",
        "fit_days": fit,
        "test_days": test,
        "candidates": CANDIDATES,
        "start": START,
        "fixed": FIXED,
        "best": best,
        "search": search,
        "results": results,
        "confirmation": confirmation,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    held_out = results["calibrated"]["test"]["summary"]
    print("best", json.dumps(best))
    print("held-out", json.dumps({q: round(held_out[q]["mae"], 2)
                                  for q in ("heating_kwh", "co2_kg", "electricity_kwh",
                                            "temp_c")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
