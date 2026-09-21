"""Compare the greenhouse model against measured data (stage 1).

This is the piece that turns every KasFlex figure from apparatus into a
finding. Until the deviation between the model's projection and a measured
day is quantified and written down, every result stays stamped
``greenhouse_validated: false`` and is reported that way.

The command is deliberately dumb. It does two things:

* If the Autonomous Greenhouse Challenge dataset (D1) is not on disk, tell
  the user exactly what to fetch, from where, and where to put it. Do not
  try to download it -- the dataset landing page requires acceptance of
  terms, and silently accepting terms on someone's behalf is not a thing this
  tool does.
* If the dataset is on disk, read the reference compartment's measured
  heating, electricity and CO2 series, run the greenhouse model over the
  same days, and print a table of deviations. Write the same table to
  ``docs/VALIDATION.md`` under the current date, so the file the plan asks
  for exists as soon as data does.

The point is to make the missing measurement visible in the tooling, not
just in prose. ``kasflex doctor`` grew a matching row so ``kasflex validate``
is discoverable.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# The layout the tool expects under the cache root. Kept as constants because
# every message that mentions a path also has to match what the code reads.
AGC_ROOT_NAME = "agc2"
AGC_MANIFEST = "MANIFEST.json"
AGC_MEASURED_DIR = "measured"
AGC_REPLAY_DIR = "replay"
DEFAULT_RESULT_PATH = "results/validation-agc2.json"
"""Where the AGC reference compartment's measured hourly series are expected.

Each day is one CSV file named ``YYYY-MM-DD.csv`` with, at minimum, columns
``heating_kwh``, ``electricity_kwh`` and ``co2_kg``. The manifest names the
files and their provenance.
"""

AGC_DOI = "10.4121/uuid:88d22c60-21b3-4ea8-90db-20249a5be2a7"
AGC_URL = f"https://doi.org/{AGC_DOI}"


@dataclass(frozen=True)
class ValidationDeviation:
    """One quantity, one day, measured vs simulated."""

    date: str
    quantity: str
    measured: float
    simulated: float
    unit: str

    @property
    def absolute_error(self) -> float:
        return self.simulated - self.measured

    @property
    def relative_error(self) -> float:
        if self.measured == 0.0:
            return float("nan")
        return (self.simulated - self.measured) / self.measured


@dataclass(frozen=True)
class ValidationReport:
    """The output of one validation run over one or more days."""

    dataset: str
    dataset_root: str
    days_compared: int
    deviations: tuple[ValidationDeviation, ...]
    generated_at: str

    def summaries(self) -> dict[str, dict[str, float | int]]:
        """Aggregate absolute and relative error by physical quantity."""
        result: dict[str, dict[str, float | int]] = {}
        for quantity in sorted({item.quantity for item in self.deviations}):
            rows = [item for item in self.deviations if item.quantity == quantity]
            relative = [abs(item.relative_error) for item in rows if item.measured != 0.0]
            result[quantity] = {
                "count": len(rows),
                "mae": sum(abs(item.absolute_error) for item in rows) / len(rows),
                "mean_absolute_relative_error": (
                    sum(relative) / len(relative) if relative else float("nan")
                ),
            }
        return result

    def to_markdown(self) -> str:
        """Render as the ``docs/VALIDATION.md`` body."""
        lines = [
            f"Generated {self.generated_at} from {self.dataset} at `{self.dataset_root}`.",
            "",
            f"Days compared: {self.days_compared}",
            "",
            "## Aggregate error",
            "",
            "| Quantity | Days | MAE | Mean absolute relative error |",
            "|---|---:|---:|---:|",
        ]
        for quantity, summary in self.summaries().items():
            unit = next(item.unit for item in self.deviations if item.quantity == quantity)
            relative = float(summary["mean_absolute_relative_error"])
            relative_text = f"{relative * 100:.1f}%" if math.isfinite(relative) else "n/a"
            lines.append(
                f"| {quantity} | {summary['count']} | {float(summary['mae']):.2f} {unit} "
                f"| {relative_text} |"
            )
        lines.extend(
            [
                "",
                "## Per-day deviation",
                "",
            "| Day | Quantity | Measured | Simulated | Error | Rel. error |",
            "|---|---|---:|---:|---:|---:|",
            ]
        )
        for d in self.deviations:
            rel = f"{d.relative_error * 100:+.1f}%" if d.measured else "n/a"
            lines.append(
                f"| {d.date} | {d.quantity} | {d.measured:.2f} {d.unit} "
                f"| {d.simulated:.2f} {d.unit} | {d.absolute_error:+.2f} {d.unit} | {rel} |"
            )
        return "\n".join(lines) + "\n"


class DatasetMissing(FileNotFoundError):
    """The AGC dataset is not on disk. The exception message names the remedy."""


class ValidationNotRunnable(RuntimeError):
    """Measured data exist, but a real simulator replay cannot yet be performed."""


def _agc_root(cache_dir: str | Path) -> Path:
    return Path(cache_dir) / AGC_ROOT_NAME


def instructions_when_missing(cache_dir: str | Path) -> str:
    """The plain-language 'the dataset is missing, here is how to get it' message.

    Exposed as a function so both the CLI and any programmatic caller print
    the same text -- and so a test can assert it without capturing stdout.
    """
    root = _agc_root(cache_dir)
    return (
        f"AGC dataset not found at {root}.\n\n"
        f"The Autonomous Greenhouse Challenge dataset (D1) is where KasFlex's\n"
        f"validation measurement comes from. It is not shipped with this\n"
        f"repository.\n\n"
        f"Get it, once, from 4TU.ResearchData:\n"
        f"  {AGC_URL}\n\n"
        f"Extract the archive and run `kasflex prepare-agc2`, which creates:\n"
        f"  {root}/\n"
        f"    {AGC_MANIFEST}                 (name, licence, retrieval date)\n"
        f"    {AGC_MEASURED_DIR}/YYYY-MM-DD.csv    (measured daily totals)\n"
        f"    {AGC_REPLAY_DIR}/YYYY-MM-DD.json      (24 h measured-day replay)\n\n"
        f"Each measured CSV needs at least the columns:\n"
        f"  heating_kwh, electricity_kwh, co2_kg\n"
        f"Each replay JSON carries the same day's 24 hourly intent rows, external\n"
        f"conditions, the 96 m2 floor area, and the GreenLight scenario.\n\n"
        f"Read Hemming et al., Sensors 2020, first -- it is the paper that\n"
        f"describes the compartment. Configure the scenario at 96 m2 (the\n"
        f"AGC compartment area) and 2019-2020 weather (see docs/DECISIONS.md\n"
        f"ADR-0004). Then re-run:  kasflex validate"
    )


def read_agc_measured(cache_dir: str | Path) -> dict[str, dict[str, float]]:
    """Read the AGC measured series from disk, keyed by ISO date.

    Returns a mapping ``{date: {quantity: value}}`` where quantities are the
    columns of each daily CSV. Raises :class:`DatasetMissing` if the folder
    does not exist -- the caller is expected to print
    :func:`instructions_when_missing` and stop.
    """
    root = _agc_root(cache_dir)
    measured_dir = root / AGC_MEASURED_DIR
    if not measured_dir.is_dir():
        raise DatasetMissing(instructions_when_missing(cache_dir))

    days: dict[str, dict[str, float]] = {}
    for csv_path in sorted(measured_dir.glob("*.csv")):
        rows = csv_path.read_text().strip().splitlines()
        if len(rows) < 2:
            continue
        header = [h.strip() for h in rows[0].split(",")]
        totals: dict[str, float] = dict.fromkeys(header, 0.0)
        counted = 0
        for row in rows[1:]:
            values = row.split(",")
            if len(values) != len(header):
                continue
            for name, raw in zip(header, values, strict=False):
                try:
                    totals[name] += float(raw)
                except ValueError:
                    pass
            counted += 1
        if counted:
            days[csv_path.stem] = totals
    return days


def _read_manifest(cache_dir: str | Path) -> dict[str, Any]:
    manifest = _agc_root(cache_dir) / AGC_MANIFEST
    if not manifest.is_file():
        return {}
    try:
        return json.loads(manifest.read_text())
    except json.JSONDecodeError:
        return {}


def _replay_path(cache_dir: str | Path, iso_date: str) -> Path:
    return _agc_root(cache_dir) / AGC_REPLAY_DIR / f"{iso_date}.json"


def replay_simulator(cache_dir: str | Path, model: str = "greenlight"):
    """Build a simulator callback from canonical AGC replay files.

    A replay file contains the 24 hourly intent rows, external conditions,
    the 96 m2 compartment scale and, for GreenLight, its weather scenario.
    Missing replay input is a hard stop: KasFlex never replaces it with NaN.
    """
    if model not in {"greenlight", "surrogate"}:
        raise ValueError("validation model must be greenlight or surrogate")

    def simulate(iso_date: str) -> dict[str, float]:
        replay_path = _replay_path(cache_dir, iso_date)
        if not replay_path.is_file():
            raise ValidationNotRunnable(
                f"Measured AGC data exist for {iso_date}, but {replay_path} is missing. "
                "Prepare the canonical replay from the AGC Reference compartment first."
            )
        try:
            payload = json.loads(replay_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ValidationNotRunnable(f"Cannot read AGC replay {replay_path}: {exc}") from exc

        from kasflex.energy.dispatch import HourlyConditions
        from kasflex.intent import Plan

        try:
            plan = Plan.from_dict(payload["plan"])
            conditions = tuple(HourlyConditions(**row) for row in payload["conditions"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationNotRunnable(
                f"{replay_path} is not a valid canonical replay: {exc}"
            ) from exc
        if len(conditions) != 24:
            raise ValidationNotRunnable(f"{replay_path}: expected 24 hourly conditions")

        floor_area = float(payload.get("floor_area_m2", 96.0))
        if abs(floor_area - 96.0) > 1e-6:
            raise ValidationNotRunnable(
                f"{replay_path}: validation must use the 96 m2 AGC compartment, "
                f"not {floor_area:g} m2"
            )

        if model == "greenlight":
            from kasflex.adapters.greenlight_worker import GreenLightWorker

            greenhouse = GreenLightWorker(
                scenario=dict(payload.get("greenlight_scenario") or {}),
                env_kwargs=dict(payload.get("greenlight_env_kwargs") or {}),
                replay_controls=dict(payload.get("replay_controls") or {}),
                parameter_overrides={
                    str(key): float(value)
                    for key, value in dict(
                        payload.get("greenlight_parameter_overrides") or {}
                    ).items()
                },
                seed=int(payload.get("seed", 0)),
            )
        else:
            from kasflex.adapters.greenhouse import SurrogateGreenhouse

            greenhouse = SurrogateGreenhouse()

        outcome = greenhouse.simulate_day(plan, conditions, floor_area)
        diagnostics = outcome.diagnostics
        heating = float(diagnostics.get("heating_energy_kwh", sum(outcome.heat_demand_kw)))
        lighting = diagnostics.get("lighting_electricity_kwh")
        if lighting is None:
            lamp_power_w_m2 = float(payload.get("lamp_power_w_m2", 110.0))
            lighting = sum(
                float(iv.lighting_level) * lamp_power_w_m2 * floor_area / 1000.0
                for iv in plan.intervals
            )
        co2 = float(diagnostics.get("co2_dosed_kg", sum(outcome.co2_demand_kg_h)))
        return {
            "heating_kwh": heating,
            "electricity_kwh": float(lighting),
            "co2_kg": co2,
        }

    return simulate


def validate_against_agc(
    cache_dir: str | Path,
    simulate_day: Any,
) -> ValidationReport:
    """Compare a real simulator replay to measured AGC daily totals.

    The simulator callback is mandatory. This prevents an empty/NaN table from
    looking like completed measured-data validation.
    """
    if simulate_day is None:
        raise ValidationNotRunnable(
            "No simulator replay was supplied. KasFlex refuses to create a validation "
            "report from measured data alone."
        )

    measured = read_agc_measured(cache_dir)
    deviations: list[ValidationDeviation] = []
    required = ("heating_kwh", "electricity_kwh", "co2_kg")
    for iso_date, quantities in measured.items():
        simulated = simulate_day(iso_date)
        for quantity in required:
            if quantity not in quantities:
                raise ValidationNotRunnable(
                    f"{iso_date}: measured AGC file is missing required column {quantity!r}"
                )
            if quantity not in simulated:
                raise ValidationNotRunnable(
                    f"{iso_date}: simulator replay did not return {quantity!r}"
                )
            value = float(quantities[quantity])
            sim = float(simulated[quantity])
            if not math.isfinite(value) or not math.isfinite(sim):
                raise ValidationNotRunnable(
                    f"{iso_date} {quantity}: validation values must be finite"
                )
            unit = {"heating_kwh": "kWh", "electricity_kwh": "kWh", "co2_kg": "kg"}[
                quantity
            ]
            deviations.append(
                ValidationDeviation(
                    date=iso_date,
                    quantity=quantity,
                    measured=value,
                    simulated=sim,
                    unit=unit,
                )
            )
    return ValidationReport(
        dataset=_read_manifest(cache_dir).get("dataset", "AGC 2nd edition"),
        dataset_root=str(_agc_root(cache_dir)),
        days_compared=len(measured),
        deviations=tuple(deviations),
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


def write_validation_json(
    report: ValidationReport,
    path: str | Path = DEFAULT_RESULT_PATH,
    *,
    model: str = "unknown",
) -> None:
    """Persist only a completed numeric report for the browser status indicator."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "dataset": report.dataset,
                "dataset_root": report.dataset_root,
                "days_compared": report.days_compared,
                "generated_at": report.generated_at,
                "model": model,
                "summaries": report.summaries(),
                "deviations": [asdict(item) for item in report.deviations],
            },
            indent=2,
            sort_keys=True,
        ) + "\n"
    )


def validation_status(path: str | Path = DEFAULT_RESULT_PATH) -> dict[str, Any]:
    """Return an honest browser status; incomplete reports count as pending."""
    target = Path(path)
    pending = {
        "validated": False,
        "status": "pending",
        "days_compared": 0,
        "dataset": "Autonomous Greenhouse Challenge, Second Edition (2019)",
        "doi": AGC_DOI,
        "message": "No completed measured-data replay has been published yet.",
    }
    if not target.is_file():
        return pending
    try:
        payload = json.loads(target.read_text())
        deviations = payload.get("deviations") or []
        days = int(payload.get("days_compared", 0))
        if days <= 0 or not deviations:
            return pending
        for row in deviations:
            if not all(
                math.isfinite(float(row[key])) for key in ("measured", "simulated")
            ):
                return pending
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return pending
    return {
        "validated": True,
        "status": "measured",
        "days_compared": days,
        "dataset": str(payload.get("dataset") or pending["dataset"]),
        "doi": AGC_DOI,
        "generated_at": str(payload.get("generated_at") or ""),
        "model": str(payload.get("model") or "unknown"),
        "message": (
            f"Measured simulator deviation published for {days} day(s); "
            "this is not a calibration pass."
        ),
    }


def write_validation_doc(report: ValidationReport, doc_path: str | Path) -> None:
    """Write or overwrite ``docs/VALIDATION.md`` with the current report table.

    The prose header of the file is preserved: only the block between the
    machine markers is replaced. That is what lets ``kasflex validate`` be
    run repeatedly without stomping on the analyst's own notes.
    """
    START = "<!-- kasflex:validation:start -->"
    END = "<!-- kasflex:validation:end -->"
    body = f"{START}\n{report.to_markdown()}{END}"

    path = Path(doc_path)
    if path.is_file():
        text = path.read_text()
        if START in text and END in text:
            head, _, rest = text.partition(START)
            _, _, tail = rest.partition(END)
            path.write_text(head + body + tail)
            return
        path.write_text(text.rstrip() + "\n\n" + body + "\n")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body + "\n")
