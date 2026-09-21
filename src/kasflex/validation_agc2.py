"""Prepare official AGC2 Reference data for an honest GreenLight replay.

The raw 4TU archive is intentionally not distributed with KasFlex.  This
module converts a locally extracted copy into the small, canonical input
layout consumed by :mod:`kasflex.validation`.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

AGC2_DOI = "10.4121/uuid:88d22c60-21b3-4ea8-90db-20249a5be2a7"
AGC2_ARCHIVE_SHA256 = "b889e9ab1663fe3b8a90a3dab71d4340a6ecd49492532c43784cc82d799708ca"
REFERENCE_AREA_M2 = 96.0
# ReadMe.pdf, Resources section: 81 W/m2 HPS plus four LED channels
# (7.27 + 25.3 + 6.23 + 22.72 W/m2). ``AssimLight`` is their aggregate state.
AGC2_LAMP_POWER_W_M2 = 81.0 + 7.27 + 25.3 + 6.23 + 22.72
STEFAN_BOLTZMANN = 5.670374419e-8
EXCEL_EPOCH = datetime(1899, 12, 30)

CLIMATE_FIELDS = (
    "Tair",
    "Rhair",
    "CO2air",
    "t_heat_vip",
    "co2_vip",
    "AssimLight",
    "EnScr",
    "BlackScr",
    "VentLee",
    "Ventwind",
)
WEATHER_FIELDS = ("Iglob", "Tout", "Rhout", "Windsp", "Pyrgeo")


def numeric(value: object) -> float:
    """Parse a finite AGC cell, returning NaN for empty/sentinel text."""
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return math.nan
    return parsed if math.isfinite(parsed) else math.nan


def excel_datetime(value: object) -> datetime:
    """Convert the AGC Excel serial and snap it to its five-minute grid."""
    serial = float(str(value).strip())
    seconds = round((serial - math.floor(serial)) * 86_400 / 300) * 300
    return EXCEL_EPOCH + timedelta(days=math.floor(serial), seconds=seconds)


def _read_timed(path: Path) -> dict[date, list[tuple[datetime, dict[str, str]]]]:
    grouped: dict[date, list[tuple[datetime, dict[str, str]]]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            row = {str(key).strip(): str(value).strip() for key, value in raw.items()}
            timestamp = excel_datetime(row["%time"])
            grouped[timestamp.date()].append((timestamp, row))
    return dict(grouped)


def _read_resources(path: Path) -> dict[date, dict[str, float]]:
    result: dict[date, dict[str, float]] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for raw in csv.DictReader(handle):
            row = {str(key).strip(): str(value).strip() for key, value in raw.items()}
            result[excel_datetime(row["%Time"]).date()] = {
                key: numeric(row[key]) for key in ("Heat_cons", "ElecHigh", "ElecLow", "CO2_cons")
            }
    return result


def _complete_day(
    climate: list[tuple[datetime, dict[str, str]]],
    weather: list[tuple[datetime, dict[str, str]]],
) -> bool:
    if len(climate) != 288 or len(weather) != 288:
        return False
    for _timestamp, row in climate:
        values = {key: numeric(row.get(key)) for key in CLIMATE_FIELDS}
        if not all(math.isfinite(value) for value in values.values()):
            return False
        if not (0 < values["CO2air"] < 2_000 and 0 <= values["Rhair"] <= 100):
            return False
    return all(
        all(math.isfinite(numeric(row.get(key))) for key in WEATHER_FIELDS)
        for _timestamp, row in weather
    )


def select_days(
    resources: dict[date, dict[str, float]],
    available: Iterable[date],
    count: int | None,
) -> list[date]:
    """Select deterministic heating-load quantiles, never hand-picked days."""
    candidates = [
        day for day in available if day in resources and math.isfinite(resources[day]["Heat_cons"])
    ]
    ranked = sorted(candidates, key=lambda day: (resources[day]["Heat_cons"], day))
    if count is None or count >= len(ranked):
        return sorted(ranked)
    if count < 1:
        raise ValueError("sample-days must be at least 1")
    if count == 1:
        selected = [ranked[len(ranked) // 2]]
    else:
        indices = [round(index * (len(ranked) - 1) / (count - 1)) for index in range(count)]
        selected = [ranked[index] for index in indices]
    return sorted(set(selected))


def _quarter_hours(rows: list[tuple[datetime, dict[str, str]]], key: str) -> list[float]:
    buckets: list[list[float]] = [[] for _ in range(96)]
    for timestamp, row in rows:
        slot = (timestamp.hour * 60 + timestamp.minute) // 15
        value = numeric(row.get(key))
        if 0 <= slot < 96 and math.isfinite(value):
            buckets[slot].append(value)
    if any(len(bucket) != 3 for bucket in buckets):
        raise ValueError(f"{key}: day is not a complete five-minute series")
    return [sum(bucket) / len(bucket) for bucket in buckets]


def _hourly(values: list[float]) -> list[float]:
    return [sum(values[index : index + 4]) / 4 for index in range(0, 96, 4)]


def sky_temperature_c(outdoor_c: float, net_longwave_w_m2: float) -> float:
    """Derive effective sky temperature from AGC net longwave radiation."""
    emitted = net_longwave_w_m2 + STEFAN_BOLTZMANN * (outdoor_c + 273.15) ** 4
    if emitted <= 0:
        raise ValueError("net longwave radiation produces a non-physical sky temperature")
    return (emitted / STEFAN_BOLTZMANN) ** 0.25 - 273.15


def _weather_row(timestamp: datetime, row: dict[str, str]) -> list[float]:
    tout = numeric(row["Tout"])
    start = datetime(timestamp.year, 1, 1)
    return [
        (timestamp - start).total_seconds(),
        max(0.0, numeric(row["Iglob"])),
        max(0.0, numeric(row["Windsp"])),
        tout,
        sky_temperature_c(tout, numeric(row["Pyrgeo"])),
        0.0,
        400.0,
        float((timestamp.date() - start.date()).days),
        min(100.0, max(0.0, numeric(row["Rhout"]))),
    ]


def write_greenlight_weather(
    weather_by_day: dict[date, list[tuple[datetime, dict[str, str]]]], target: Path
) -> None:
    """Write complete calendar-year files in gl-gym's positional CSV format."""
    observed: dict[int, dict[datetime, dict[str, str]]] = defaultdict(dict)
    for rows in weather_by_day.values():
        for timestamp, row in rows:
            if all(math.isfinite(numeric(row.get(key))) for key in WEATHER_FIELDS):
                observed[timestamp.year][timestamp] = row

    header = [
        "time",
        "global radiation",
        "wind speed",
        "air temperature",
        "sky temperature",
        "??",
        "CO2 concentration",
        "day number",
        "RH",
    ]
    target.mkdir(parents=True, exist_ok=True)
    for year, mapping in sorted(observed.items()):
        known = sorted(mapping)
        if not known:
            continue
        start = datetime(year, 1, 1)
        end = datetime(year + 1, 1, 1)
        with (target / f"{year}.csv").open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            current = start
            while current < end:
                row = mapping.get(current)
                if row is None:
                    position = bisect.bisect_left(known, current)
                    neighbours = known[max(0, position - 1) : min(len(known), position + 1)]
                    nearest = min(neighbours, key=lambda item: abs(item - current))
                    row = mapping[nearest]
                writer.writerow(_weather_row(current, row))
                current += timedelta(minutes=5)


def _measured_totals(resources: dict[str, float]) -> dict[str, float]:
    return {
        "heating_kwh": resources["Heat_cons"] * REFERENCE_AREA_M2 / 3.6,
        "electricity_kwh": (resources["ElecHigh"] + resources["ElecLow"]) * REFERENCE_AREA_M2,
        "co2_kg": resources["CO2_cons"] * REFERENCE_AREA_M2,
    }


def _replay_payload(
    day: date,
    climate: list[tuple[datetime, dict[str, str]]],
    weather: list[tuple[datetime, dict[str, str]]],
    weather_dir: Path,
) -> dict[str, Any]:
    series = {key: _quarter_hours(climate, key) for key in CLIMATE_FIELDS}
    weather_series = {key: _quarter_hours(weather, key) for key in WEATHER_FIELDS}
    lighting = [min(1.0, max(0.0, value / 100)) for value in series["AssimLight"]]
    vent = [
        min(1.0, max(0.0, (lee + wind) / 200))
        for lee, wind in zip(series["VentLee"], series["Ventwind"], strict=True)
    ]
    hourly_light = _hourly(lighting)
    hourly_irradiance = _hourly(weather_series["Iglob"])
    hourly_temperature = _hourly(weather_series["Tout"])
    intervals = [
        {
            "hour": hour,
            "heat_source": "boiler",
            "lighting_level": hourly_light[hour],
            "battery": "idle",
            "battery_power_kw": 0.0,
            "chp_mode": "off",
            "co2_source": "liquid",
            "reasoning": "Measured AGC2 Reference-compartment replay",
        }
        for hour in range(24)
    ]
    conditions = [
        {
            "hour": hour,
            "heat_demand_kw": 0.0,
            "co2_demand_kg_h": 0.0,
            "irradiance_w_m2": hourly_irradiance[hour],
            "outdoor_temp_c": hourly_temperature[hour],
            "power_price_eur_kwh": 0.0,
            "gas_price_eur_kwh": 0.0,
            "feed_in_price_eur_kwh": 0.0,
        }
        for hour in range(24)
    ]
    initial = {
        "temperature_c": series["Tair"][0],
        "relative_humidity_pct": series["Rhair"][0],
        "co2_ppm": series["CO2air"][0],
    }
    return {
        "floor_area_m2": REFERENCE_AREA_M2,
        "lamp_power_w_m2": AGC2_LAMP_POWER_W_M2,
        "seed": 0,
        "plan": {
            "date": day.isoformat(),
            "planner": "agc2-measured-replay",
            "intervals": intervals,
        },
        "conditions": conditions,
        "greenlight_scenario": {
            "location": "BleiswijkAGC2",
            "growth_year": day.year,
            "start_day": (day - date(day.year, 1, 1)).days,
        },
        "greenlight_env_kwargs": {
            # gl-gym appends ``<location>/<year>.csv`` itself.
            "weather_data_dir": str(weather_dir.parent.resolve()),
            "season_length": 1,
            "pred_horizon": 0,
        },
        "greenlight_parameter_overrides": {"lamp_power": AGC2_LAMP_POWER_W_M2},
        "replay_controls": {
            "heating_setpoint_c": series["t_heat_vip"],
            "co2_setpoint_ppm": series["co2_vip"],
            "lighting_fraction": lighting,
            "thermal_screen_fraction": [value / 100 for value in series["EnScr"]],
            "blackout_screen_fraction": [value / 100 for value in series["BlackScr"]],
            "ventilation_fraction": vent,
            "initial_indoor": initial,
            "source_columns": {
                "heating_setpoint_c": "t_heat_vip",
                "co2_setpoint_ppm": "co2_vip",
                "lighting_fraction": "AssimLight",
                "thermal_screen_fraction": "EnScr",
                "blackout_screen_fraction": "BlackScr",
                "ventilation_fraction": "mean(VentLee, Ventwind)",
            },
        },
    }


def prepare_agc2(source: Path, cache_dir: Path, sample_days: int | None = 12) -> list[date]:
    """Convert an extracted official archive into canonical validation inputs."""
    resources_path = source / "Reference" / "Resources.csv"
    climate_path = source / "Reference" / "GreenhouseClimate.csv"
    weather_path = source / "Weather" / "Weather.csv"
    missing = [path for path in (resources_path, climate_path, weather_path) if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing AGC2 file(s): " + ", ".join(map(str, missing)))

    archives = sorted(source.parent.glob("*.7z"))
    archive_hash = None
    archive_name = None
    if archives:
        archive_name = archives[0].name
        digest = hashlib.sha256()
        with archives[0].open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        archive_hash = digest.hexdigest()
        if archive_hash != AGC2_ARCHIVE_SHA256:
            raise ValueError(
                f"AGC2 archive checksum mismatch: expected {AGC2_ARCHIVE_SHA256}, "
                f"got {archive_hash}"
            )

    resources = _read_resources(resources_path)
    climate = _read_timed(climate_path)
    weather = _read_timed(weather_path)
    complete = [
        day
        for day in sorted(set(climate) & set(weather))
        if _complete_day(climate[day], weather[day])
    ]
    selected = select_days(resources, complete, sample_days)
    if not selected:
        raise ValueError("no complete AGC2 Reference days were found")

    root = cache_dir / "agc2"
    measured_dir = root / "measured"
    replay_dir = root / "replay"
    weather_dir = root / "weather" / "BleiswijkAGC2"
    measured_dir.mkdir(parents=True, exist_ok=True)
    replay_dir.mkdir(parents=True, exist_ok=True)
    # A new deterministic selection replaces an older one. Leaving old daily
    # files in place silently changes the sample size on the next validation.
    for old in measured_dir.glob("*.csv"):
        old.unlink()
    for old in replay_dir.glob("*.json"):
        old.unlink()
    write_greenlight_weather(weather, weather_dir)

    for day in selected:
        totals = _measured_totals(resources[day])
        with (measured_dir / f"{day.isoformat()}.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(totals))
            writer.writeheader()
            writer.writerow(totals)
        payload = _replay_payload(day, climate[day], weather[day], weather_dir)
        (replay_dir / f"{day.isoformat()}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n"
        )

    manifest = {
        "dataset": "Autonomous Greenhouse Challenge, Second Edition — Reference compartment",
        "doi": AGC2_DOI,
        "licence": "CC0-1.0",
        "retrieved_at": datetime.now(UTC).date().isoformat(),
        "archive_name": archive_name,
        "archive_sha256": archive_hash or AGC2_ARCHIVE_SHA256,
        "archive_checksum_verified": archive_hash is not None,
        "compartment": "Reference",
        "floor_area_m2": REFERENCE_AREA_M2,
        "lamp_power_w_m2": AGC2_LAMP_POWER_W_M2,
        "lamp_power_source": (
            "ReadMe.pdf Resources: HPS 81 + LED blue 7.27 + red 25.3 + "
            "far-red 6.23 + white 22.72 W/m2"
        ),
        "selected_dates": [day.isoformat() for day in selected],
        "selection": (
            "All complete days"
            if sample_days is None
            else f"{len(selected)} deterministic, evenly spaced heating-consumption quantiles"
        ),
        "conversions": {
            "heating_kwh": "Heat_cons [MJ/m2/day] * 96 m2 / 3.6",
            "electricity_kwh": "(ElecHigh + ElecLow) [kWh/m2/day] * 96 m2",
            "co2_kg": "CO2_cons [kg/m2/day] * 96 m2",
        },
        "replay_note": (
            "Measured setpoints and actuator positions drive GreenLight; measured heating and "
            "CO2 consumption are withheld as outputs. Electricity uses measured lamp state and "
            "is therefore primarily an energy-accounting check, not an independent control "
            "prediction."
        ),
    }
    (root / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return selected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("data/raw/agc2/extracted"))
    parser.add_argument("--cache-dir", type=Path, default=Path("data/cache"))
    parser.add_argument("--sample-days", type=int, default=12)
    parser.add_argument("--all-days", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    selected = prepare_agc2(
        args.source,
        args.cache_dir,
        sample_days=None if args.all_days else args.sample_days,
    )
    print(f"Prepared {len(selected)} AGC2 day(s): " + ", ".join(map(str, selected)))
    print(f"Canonical cache: {(args.cache_dir / 'agc2').resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
