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
from dataclasses import dataclass
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

    def to_markdown(self) -> str:
        """Render as the ``docs/VALIDATION.md`` body."""
        lines = [
            f"Generated {self.generated_at} from {self.dataset} at `{self.dataset_root}`.",
            "",
            f"Days compared: {self.days_compared}",
            "",
            "| Day | Quantity | Measured | Simulated | Error | Rel. error |",
            "|---|---|---:|---:|---:|---:|",
        ]
        for d in self.deviations:
            rel = f"{d.relative_error * 100:+.1f}%" if d.measured else "n/a"
            lines.append(
                f"| {d.date} | {d.quantity} | {d.measured:.2f} {d.unit} "
                f"| {d.simulated:.2f} {d.unit} | {d.absolute_error:+.2f} {d.unit} | {rel} |"
            )
        return "\n".join(lines) + "\n"


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
