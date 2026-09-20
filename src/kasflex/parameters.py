"""Machine-readable provenance for operational numbers.

The Markdown provenance page is for people.  This module backs it with a registry
that the CLI, UI and tests can inspect.  A number is either sourced, an explicit
assumption, or a software/experiment choice; an empty provenance field is an error.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import yaml

from kasflex.adapters.greenhouse import SurrogateGreenhouse
from kasflex.config import ScenarioConfig
from kasflex.energy.dispatch import LIQUID_CO2_EUR_KG
from kasflex.resources import default_config_path, is_frozen, resource_root

ALLOWED_STATUSES = {"sourced", "assumption", "choice"}


def registry_path() -> Path:
    if is_frozen():
        return resource_root() / "configs" / "parameter_sources.yaml"
    checkout = Path(__file__).resolve().parents[2] / "configs" / "parameter_sources.yaml"
    return checkout if checkout.is_file() else resource_root() / "parameter_sources.yaml"


def _walk(prefix: str, value: Any, out: dict[str, Any]) -> None:
    if dataclasses.is_dataclass(value):
        for item in dataclasses.fields(value):
            _walk(f"{prefix}.{item.name}" if prefix else item.name, getattr(value, item.name), out)
    elif isinstance(value, dict):
        # A mapping such as congestion windows is one governed parameter: splitting
        # each hour into an invented schema makes the source harder, not easier, to read.
        out[prefix] = value
    elif isinstance(value, (int, float, bool)):
        out[prefix] = value


def operational_values(config: ScenarioConfig | None = None) -> dict[str, Any]:
    """Numbers and booleans that materially affect planning or simulation."""
    config = config or ScenarioConfig.from_yaml(default_config_path())
    values: dict[str, Any] = {}
    _walk("hub", config.hub, values)
    values.update(
        {
            "scenario.seed": config.seed,
            "scenario.latitude": config.latitude,
            "scenario.longitude": config.longitude,
            "gas_price_eur_kwh": config.gas_price_eur_kwh,
            "history_days": config.history_days,
            "checker.max_revisions": config.checker.max_revisions,
            "dispatch.liquid_co2_eur_kg": LIQUID_CO2_EUR_KG,
        }
    )
    surrogate: dict[str, Any] = {}
    _walk("surrogate", SurrogateGreenhouse(), surrogate)
    values.update(surrogate)
    return values


def parameter_registry(config: ScenarioConfig | None = None) -> dict[str, Any]:
    """Load, validate and enrich the registry with current configured values."""
    enforce_registered_values = config is None
    document = yaml.safe_load(registry_path().read_text(encoding="utf-8")) or {}
    entries = document.get("parameters") or {}
    if not isinstance(entries, dict):
        raise ValueError("parameter_sources.yaml: parameters must be a mapping")

    current = operational_values(config)
    missing = sorted(set(current) - set(entries))
    extra = sorted(set(entries) - set(current))
    if missing:
        raise ValueError(f"operational parameters missing provenance: {missing}")
    if extra:
        raise ValueError(f"parameter registry names unknown operational parameters: {extra}")

    enriched = []

    def comparable(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: comparable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [comparable(item) for item in value]
        return value

    for path, raw in entries.items():
        item = dict(raw or {})
        status = item.get("status")
        if status not in ALLOWED_STATUSES:
            raise ValueError(f"{path}: status must be one of {sorted(ALLOWED_STATUSES)}")
        if not str(item.get("rationale", "")).strip():
            raise ValueError(f"{path}: rationale is required")
        if status == "sourced" and not str(item.get("source_url", "")).strip():
            raise ValueError(f"{path}: sourced parameters need source_url")
        if "value" not in item:
            raise ValueError(f"{path}: registered value is required")
        if enforce_registered_values and comparable(item["value"]) != comparable(current[path]):
            raise ValueError(
                f"{path}: registered value {item['value']!r} does not match "
                f"configured value {current[path]!r}"
            )
        enriched.append({"path": path, "configured_value": current[path], **item})

    counts = {
        status: sum(row["status"] == status for row in enriched)
        for status in sorted(ALLOWED_STATUSES)
    }
    return {
        "schema_version": document.get("schema_version"),
        "updated": document.get("updated"),
        "statuses": document.get("statuses", {}),
        "counts": counts,
        "parameters": enriched,
    }


def render_markdown(config: ScenarioConfig | None = None) -> str:
    registry = parameter_registry(config)
    lines = [
        "| Parameter | Current value | Plausible range | Unit | Status | Source or rationale |",
        "|---|---:|---|---|---|---|",
    ]
    for row in registry["parameters"]:
        source = row.get("source") or row["rationale"]
        if row.get("source_url"):
            source = f"[{source}]({row['source_url']}) — {row['rationale']}"
        lines.append(
            f"| `{row['path']}` | {row['configured_value']} | "
            f"{row.get('plausible_range', 'site-specific')} | {row.get('unit', '')} | "
            f"{row['status']} | {source} |"
        )
    return "\n".join(lines) + "\n"
