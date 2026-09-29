"""Fit GreenLight construction parameters to an AGC2 compartment, then test them.

Run inside the GreenLight worker environment, on a cache prepared with
``kasflex prepare-agc2 --all-days --compartment <name>``::

    ./.venv-greenlight/bin/python workers/greenlight/calibrate_agc2.py \\
        --cache-dir data/cache --out results/calibration-agc2.json

Days are split by ISO week: even weeks fit, odd weeks test. Whole weeks rather
than alternate days, so a test day is never the day after a training day with
nearly the same weather. The search is a small, explicit grid over parameters
with a physical meaning; ``etaLampCool`` is fixed at 0 because it is a fact about
the lamps, not a free parameter (see ``AGC2_CALIBRATION`` in
``kasflex.validation_agc2``).

Heat is compared as the AGC2 dataset defines it: pipe heat release computed from
pipe and air temperature, not boiler input. See docs/CALIBRATION.md.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import sys
import warnings
from datetime import date
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

GRID = {
    "aCov": (156.0, 180.0, 216.6),
    "aRoof": (7.2, 17.4, 52.2),
    "cLeakage": (1e-5, 3e-5, 1e-4),
}
FIXED = {"etaLampCool": 0.0}


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
        diagnostics = worker.simulate_day(request)["diagnostics"]
    except Exception:  # noqa: BLE001 - a failed day is counted, never silently scored
        return iso_day, None
    return iso_day, {
        "heating_kwh": diagnostics["pipe_heat_agc_formula_kwh"],
        "boiler_kwh": diagnostics["heating_energy_kwh"],
        "electricity_kwh": diagnostics["lighting_electricity_kwh"],
        "co2_kg": diagnostics["co2_dosed_kg"],
    }


def _measured(root: Path, iso_day: str) -> dict[str, float]:
    with (root / "measured" / f"{iso_day}.csv").open() as handle:
        return {key: float(value) for key, value in next(csv.DictReader(handle)).items()}


def evaluate(pool: Pool, root: Path, days: list[str], calibration: dict[str, float]) -> dict:
    simulated = dict(pool.map(_simulate, [(str(root), day, calibration) for day in days]))
    failed = sorted(day for day, value in simulated.items() if value is None)
    rows = [(day, _measured(root, day), simulated[day]) for day in days if simulated[day]]
    summary: dict[str, object] = {"days": len(rows), "failed_days": failed}
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
    return {"summary": summary, "per_day": {day: sim for day, _m, sim in rows}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=Path("data/cache"))
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
    with Pool(args.workers) as pool:
        for values in itertools.product(*GRID.values()):
            calibration = {**FIXED, **dict(zip(GRID, values, strict=True))}
            summary = evaluate(pool, root, fit, calibration)["summary"]
            # Equal weight to a typical daily heat error (~50 kWh) and CO2 error (~3 kg).
            score = summary["heating_kwh"]["mae"] / 50.0 + summary["co2_kg"]["mae"] / 3.0
            search.append({"calibration": calibration, "score": score, "fit": summary})
            print(json.dumps({"calibration": calibration, "score": round(score, 3)}), flush=True)
        best = min(search, key=lambda row: row["score"])["calibration"]
        results = {
            label: {
                "fit": evaluate(pool, root, fit, calibration)["summary"],
                "test": evaluate(pool, root, test, calibration),
            }
            for label, calibration in (
                ("gl_gym_defaults", {}),
                ("lamp_cooling_only", dict(FIXED)),
                ("calibrated", best),
            )
        }

    record = {
        "dataset": manifest.get("dataset"),
        "compartment": manifest.get("compartment"),
        "archive_checksum_verified": manifest.get("archive_checksum_verified"),
        "heat_definition": "AGC2 Heat_cons formula applied to simulated pipe temperatures",
        "split": "even ISO weeks fit, odd ISO weeks test",
        "fit_days": fit,
        "test_days": test,
        "grid": GRID,
        "fixed": FIXED,
        "best": best,
        "search": search,
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    held_out = results["calibrated"]["test"]["summary"]
    print("best", json.dumps(best))
    print("held-out", json.dumps({q: round(held_out[q]["mae"], 2)
                                  for q in ("heating_kwh", "co2_kg", "electricity_kwh")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
