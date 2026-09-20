"""Compare greenhouse simulation against measured AGC reference data.

The default run uses a bundled, checksummed three-day subset from the AGC
Reference compartment. It drives the surrogate from the recorded weather and
control choices, then reports daily resource errors and hourly indoor-climate
errors. Quantifying error does not imply calibration: the status remains
``quantified-not-calibrated`` and simulation outputs remain marked unvalidated.

The older cache layout is retained for researchers with a full export. No data is
downloaded silently; provenance and transformations for the bundled subset live in
``data/validation/agc2_reference_manifest.json``.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# The layout the tool expects under the cache root. Kept as constants because
# every message that mentions a path also has to match what the code reads.
AGC_ROOT_NAME = "agc2"
AGC_MANIFEST = "MANIFEST.json"
AGC_MEASURED_DIR = "measured"
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
    model: str = "unspecified"
    status: str = "quantified-not-calibrated"
    aggregate: dict[str, dict[str, float | str | int]] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_markdown(self) -> str:
        """Render as the ``docs/VALIDATION.md`` body."""
        lines = [
            f"Generated {self.generated_at} from {self.dataset} at `{self.dataset_root}`.",
            "",
            f"Model: `{self.model}` · status: **{self.status}** · "
            f"days compared: {self.days_compared}",
            "",
        ]
        if self.aggregate:
            lines.extend(
                [
                    "### Accuracy summary",
                    "",
                    "| Quantity | Samples | MAE | RMSE | MAPE |",
                    "|---|---:|---:|---:|---:|",
                ]
            )
            for quantity, values in self.aggregate.items():
                unit = str(values.get("unit", ""))
                mape = values.get("mape_pct")
                mape_text = f"{float(mape):.1f}%" if isinstance(mape, (int, float)) else "n/a"
                lines.append(
                    f"| {quantity} | {values.get('samples', 0)} | "
                    f"{float(values.get('mae', 0)):.2f} {unit} | "
                    f"{float(values.get('rmse', 0)):.2f} {unit} | {mape_text} |"
                )
            lines.extend(["", "### Day-level comparison", ""])
        lines.extend(
            [
                "| Day | Quantity | Measured | Simulated | Error | Rel. error |",
                "|---|---|---:|---:|---:|---:|",
            ]
        )
        for d in self.deviations:
            if not math.isfinite(d.simulated):
                simulated, error, rel = "not simulated", "n/a", "n/a"
            else:
                simulated = f"{d.simulated:.2f} {d.unit}"
                error = f"{d.absolute_error:+.2f} {d.unit}"
                rel = f"{d.relative_error * 100:+.1f}%" if d.measured else "n/a"
            lines.append(
                f"| {d.date} | {d.quantity} | {d.measured:.2f} {d.unit} "
                f"| {simulated} | {error} | {rel} |"
            )
        return "\n".join(lines) + "\n"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DatasetMissing(FileNotFoundError):
    """The AGC dataset is not on disk. The exception message names the remedy."""


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
        f"Then arrange the files as:\n"
        f"  {root}/\n"
        f"    {AGC_MANIFEST}                 (name, licence, retrieval date)\n"
        f"    {AGC_MEASURED_DIR}/YYYY-MM-DD.csv    (one file per compared day)\n\n"
        f"Each CSV needs at least the columns:\n"
        f"  heating_kwh, electricity_kwh, co2_kg\n\n"
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


def validate_against_agc(
    cache_dir: str | Path,
    simulate_day: Any = None,
) -> ValidationReport:
    """Compare simulated to measured daily totals for the AGC compartment.

    Args:
        cache_dir: root under which ``agc2/measured/*.csv`` lives.
        simulate_day: ``(iso_date) -> {quantity: value}``. Left ``None``, the
            simulated numbers are recorded as NaN and the report reads "not
            simulated yet" for each column. This is deliberate: the point of
            wiring the CLI now is that anybody with the dataset in hand can
            run the command, see the measurement stub, and only the
            greenhouse-side glue is missing. The plan (stage 1) is to plug in
            :class:`kasflex.adapters.greenhouse.SurrogateGreenhouse` and later
            the GreenLight worker.
    """
    measured = read_agc_measured(cache_dir)
    deviations: list[ValidationDeviation] = []
    for date, quantities in measured.items():
        simulated = simulate_day(date) if simulate_day is not None else {}
        for quantity, value in quantities.items():
            sim = float(simulated.get(quantity, float("nan")))
            unit = quantity.split("_")[-1] if "_" in quantity else ""
            deviations.append(
                ValidationDeviation(
                    date=date,
                    quantity=quantity,
                    measured=float(value),
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


def bundled_reference_root() -> Path:
    """Return the compact, redistributable AGC2 reference subset shipped with KasFlex."""
    if getattr(__import__("sys"), "frozen", False):
        from kasflex.resources import resource_root

        return resource_root() / "kasflex" / "validation_data"
    checkout = Path(__file__).resolve().parents[2] / "data" / "validation"
    return checkout if checkout.is_dir() else Path(__file__).resolve().parent / "validation_data"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _accuracy(pairs: list[tuple[float, float]], unit: str) -> dict[str, float | str | int]:
    errors = [simulated - measured for measured, simulated in pairs]
    nonzero = [(m, s) for m, s in pairs if abs(m) > 1e-12]
    return {
        "samples": len(pairs),
        "unit": unit,
        "mae": sum(abs(error) for error in errors) / len(errors),
        "rmse": math.sqrt(sum(error * error for error in errors) / len(errors)),
        "mape_pct": (
            100 * sum(abs((s - m) / m) for m, s in nonzero) / len(nonzero) if nonzero else "n/a"
        ),
        "bias": sum(errors) / len(errors),
    }


def validate_bundled_reference(
    model: Any = None,
    *,
    data_root: str | Path | None = None,
    days: tuple[str, ...] | None = None,
) -> ValidationReport:
    """Run the simulator against three measured AGC2 reference-compartment days.

    The bundled files are a compact derivation of the official CC0 dataset.  They
    retain hourly weather, recorded lighting/CO2 operation and measured indoor
    climate, plus whole-day resource totals.  This makes ``kasflex validate`` a
    real, offline, reproducible comparison instead of the previous NaN-producing
    stub.  It intentionally does not tune the model or declare it operationally
    validated: the result quantifies the gap so that claim can be judged.
    """
    from kasflex.adapters.greenhouse import SurrogateGreenhouse
    from kasflex.energy.dispatch import HourlyConditions
    from kasflex.intent import IntervalIntent, Plan

    root = Path(data_root) if data_root is not None else bundled_reference_root()
    manifest = json.loads((root / "agc2_reference_manifest.json").read_text(encoding="utf-8"))
    hourly = _read_csv(root / "agc2_reference_hourly.csv")
    totals = {row["date"]: row for row in _read_csv(root / "agc2_reference_totals.csv")}
    selected = set(days or tuple(manifest["sample_days"]))
    model = model or SurrogateGreenhouse()
    area = float(manifest["greenhouse_floor_area_m2"])

    grouped: dict[str, list[dict[str, str]]] = {}
    for row in hourly:
        if row["date"] in selected:
            grouped.setdefault(row["date"], []).append(row)
    if not grouped:
        raise DatasetMissing(f"No selected AGC2 reference days found in {root}.")

    units = {
        "heating_kwh": "kWh",
        "electricity_kwh": "kWh",
        "co2_kg": "kg",
        "temperature_c": "°C",
        "relative_humidity_pct": "%",
        "co2_concentration_ppm": "ppm",
    }
    samples: dict[str, list[tuple[float, float]]] = {key: [] for key in units}
    deviations: list[ValidationDeviation] = []

    for day, rows in sorted(grouped.items()):
        rows.sort(key=lambda row: int(row["hour"]))
        if len(rows) != 24:
            raise ValueError(f"AGC2 reference day {day} has {len(rows)} hours, expected 24")
        plan = Plan(
            date=day,
            planner="recorded-agc-controls",
            intervals=tuple(
                IntervalIntent(
                    hour=int(row["hour"]),
                    heat_source="boiler",
                    lighting_level=float(row["lighting_level"]),
                    co2_source="liquid" if int(row["co2_active"]) else "none",
                    reasoning="Recorded AGC reference-compartment operation",
                )
                for row in rows
            ),
        )
        conditions = tuple(
            HourlyConditions(
                hour=int(row["hour"]),
                outdoor_temp_c=float(row["outdoor_temp_c"]),
                irradiance_w_m2=float(row["irradiance_w_m2"]),
            )
            for row in rows
        )
        outcome = model.simulate_day(plan, conditions, area)
        measured = totals[day]
        daily = {
            "heating_kwh": (float(measured["heating_kwh"]), sum(outcome.heat_demand_kw)),
            "electricity_kwh": (
                float(measured["electricity_kwh"]),
                sum(float(row["lighting_level"]) * 0.110 * area for row in rows),
            ),
            "co2_kg": (float(measured["co2_kg"]), sum(outcome.co2_demand_kg_h)),
        }
        for quantity, pair in daily.items():
            samples[quantity].append(pair)
            deviations.append(ValidationDeviation(day, quantity, pair[0], pair[1], units[quantity]))

        climate = {
            "temperature_c": (
                [float(row["measured_temp_c"]) for row in rows],
                list(outcome.temp_c),
            ),
            "relative_humidity_pct": (
                [float(row["measured_rh_pct"]) for row in rows],
                list(outcome.rh_pct),
            ),
            "co2_concentration_ppm": (
                [float(row["measured_co2_ppm"]) for row in rows],
                list(outcome.co2_ppm),
            ),
        }
        for quantity, (observed, simulated) in climate.items():
            samples[quantity].extend(zip(observed, simulated, strict=True))
            deviations.append(
                ValidationDeviation(
                    day,
                    f"mean_{quantity}",
                    sum(observed) / len(observed),
                    sum(simulated) / len(simulated),
                    units[quantity],
                )
            )

    aggregate = {
        quantity: _accuracy(pairs, units[quantity]) for quantity, pairs in samples.items() if pairs
    }
    return ValidationReport(
        dataset=manifest["dataset"],
        dataset_root=str(root),
        days_compared=len(grouped),
        deviations=tuple(deviations),
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        model=getattr(model, "name", type(model).__name__),
        status="quantified-not-calibrated",
        aggregate=aggregate,
        provenance=manifest,
    )


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
