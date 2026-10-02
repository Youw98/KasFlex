"""What the server and its endpoint mixins share: the adjustable settings, the
request error, and turning interface overrides into a validated scenario."""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path
from typing import Any

from kasflex.admin_auth import (
    SITE_FIELDS,
)
from kasflex.config import ConfigError, ScenarioConfig
from kasflex.llm_providers import (
    PROVIDERS,
)
from kasflex.resources import resolve_output, static_dir
from kasflex.scenarios import HUB_FIELDS, ScenarioStore

STATIC_DIR = static_dir()
SITE_FIELDS_SET = frozenset(SITE_FIELDS)


#: The settings the interface exposes. Everything else stays in the scenario file.
#:
#: This list is the answer to "what can I change from the UI". It is deliberately a
#: curated subset: the point is the handful of things an experiment actually varies,
#: not every field in the configuration. Each entry is
#: ``(path, label, kind, minimum, maximum, step, help)`` where ``path`` is a
#: dotted path into the scenario config.
#: Fields carrying ``"scope": "researcher"`` are hidden from the grower interface
#: and editable only from the setup screen. A grower who can retune the checker or
#: reassign their own experiment condition is not a participant in a controlled
#: study, and a grower who is *shown* those controls is being handed a way to break
#: their own session.
ADJUSTABLE: tuple[dict[str, Any], ...] = (
    {"path": "language", "label": "Language", "kind": "choice",
     "choices": ["en", "nl"],
     "help": "Sets the interface and the language the assistant explains in."},
    {"path": "participant_id", "label": "Participant", "kind": "text",
     "scope": "researcher",
     "help": "Pseudonymous identifier for this session. Never a name."},
    {"path": "condition", "label": "Experiment condition", "kind": "text",
     "scope": "researcher",
     "help": "Which condition this session is assigned to. Reported per condition."},
    {"path": "consent_version", "label": "Consent text version", "kind": "text",
     "scope": "researcher", "readonly": True,
     "help": "Set this in the scenario file to run as a study: consent is then "
             "required before anything is recorded, and re-asked whenever this "
             "string changes. Deliberately not settable from a browser, so that "
             "nobody can switch the consent regime off from the page."},
    {"path": "data_source", "label": "Data mode", "kind": "choice",
     "choices": ["demo", "cache", "synthetic", "scenario"],
     "help": ("Demo replays real historical Dutch market/weather inputs; "
              "cache uses your downloaded day; synthetic is for deliberate tests; "
              "scenario is a fixed workshop day.")},
    {"path": "scenario_id", "label": "Workshop scenario", "kind": "text",
     "help": "Which fixed workshop day to plan when the data mode is scenario."},
    {"path": "grid_contract_type", "label": "Grid contract type", "kind": "choice",
     "choices": ["firm", "cbc", "time_block", "duration", "non_firm"],
     "help": ("When the contracted grid capacity is available: firm (always), CBC "
              "(less in congestion hours), time-block, duration (85%) or non-firm.")},
    {"path": "llm_provider", "label": "AI service", "kind": "choice",
     "choices": sorted(PROVIDERS),
     "help": "Which model explains plans and answers questions. Ollama runs locally."},
    {"path": "llm_model", "label": "AI model", "kind": "text",
     "help": "The model name at that service, for example claude-opus-5 or llama3.1."},
    {"path": "llm_base_url", "label": "AI server address", "kind": "text",
     "help": "Only for a local or self-hosted model. Leave blank for the default."},
    {"path": "latitude", "label": "Latitude", "kind": "number",
     "min": -90, "max": 90, "step": 0.001},
    {"path": "longitude", "label": "Longitude", "kind": "number",
     "min": -180, "max": 180, "step": 0.001},
    {"path": "gas_price_eur_kwh", "label": "Gas price assumption", "kind": "number",
     "min": 0, "max": 10, "step": 0.001, "unit": "€/kWh",
     "help": "Enter your gas energy price. This is a manual assumption, not a live TTF quote."},
    {"path": "contracted_base_kw", "label": "Contracted base position", "kind": "number",
     "min": 0, "max": 20000, "step": 100, "unit": "kW",
     "help": "Electricity volume already contracted before day-ahead settlement."},
    {"path": "contracted_price_eur_kwh", "label": "Contract price", "kind": "number",
     "min": 0, "max": 1, "step": 0.001, "unit": "€/kWh",
     "help": "Price of the contracted base electricity volume."},
    {"path": "imbalance_short_spread_eur_kwh", "label": "Short-position spread", "kind": "number",
     "min": 0, "max": 0.5, "step": 0.001, "unit": "€/kWh", "scope": "researcher"},
    {"path": "imbalance_long_spread_eur_kwh", "label": "Long-position spread", "kind": "number",
     "min": 0, "max": 0.5, "step": 0.001, "unit": "€/kWh", "scope": "researcher"},
    {"path": "grid_peak_value_eur_per_kw", "label": "Value of 1 kW less peak", "kind": "number",
     "min": 0, "max": 100, "step": 0.01, "unit": "€/kW",
     "help": ("Used by 'grid relief': a lower peak is only bought when it saves more "
              "than this per kW. Default: Liander 2026 kWmax tariff, per kW per month.")},
    {"path": "planner", "label": "Planner", "kind": "choice",
     "choices": ["collaborative", "rule-based", "learned", "naive", "llm", "mpc"],
     "help": ("Collaborative uses the current day, optimisation and grower choices. "
              "Learned is the research demand-forecast planner.")},
    {"path": "checker.enabled", "label": "Safety checker", "kind": "bool",
     "help": "Turn verification off to measure what it is worth. This is the experiment."},
    {"path": "checker.explain", "label": "Explain rejections", "kind": "bool",
     "help": "Whether a rejected planner is told why. Separates verification from explanation."},
    {"path": "checker.max_revisions", "label": "Revisions allowed", "kind": "int",
     "min": 0, "max": 10, "step": 1,
     "help": "How many times a planner may revise before the baseline takes over."},

    {"path": "date", "label": "Date", "kind": "text", "help": "The day to simulate."},
    {"path": "seed", "label": "Seed", "kind": "int", "min": 0, "max": 9999, "step": 1,
     "help": "Same seed, same day, every time."},
    {"path": "winter", "label": "Winter conditions", "kind": "bool",
     "help": "Winter: low light, high heat demand. Summer is the reverse."},

    {"path": "hub.contract.import_limit_kw", "label": "Grid import limit", "kind": "number",
     "min": 500, "max": 20000, "step": 100, "unit": "kW",
     "help": "The connection contract. Exceeding it is a hard violation."},
    {"path": "hub.contract.export_limit_kw", "label": "Grid export limit", "kind": "number",
     "min": 0, "max": 20000, "step": 100, "unit": "kW",
     "help": "Feed-in limit. Often lower than import, and zero under a non-firm contract."},

    {"path": "hub.battery.capacity_kwh", "label": "Battery capacity", "kind": "number",
     "min": 0, "max": 20000, "step": 100, "unit": "kWh"},
    {"path": "hub.battery.max_charge_kw", "label": "Battery power", "kind": "number",
     "min": 0, "max": 10000, "step": 50, "unit": "kW",
     "help": "Applied to both charge and discharge."},

    {"path": "hub.chp.electrical_capacity_kw", "label": "CHP size", "kind": "number",
     "min": 0, "max": 10000, "step": 100, "unit": "kWe"},
    {"path": "hub.chp.min_run_hours", "label": "CHP minimum run", "kind": "int",
     "min": 1, "max": 12, "step": 1, "unit": "h"},
    {"path": "hub.chp.min_down_hours", "label": "CHP minimum down", "kind": "int",
     "min": 1, "max": 12, "step": 1, "unit": "h"},

    {"path": "hub.buffer.capacity_kwh", "label": "Heat buffer", "kind": "number",
     # 43 600 kWh is the sourced 5 ha default; 200 MWh also covers the 20 ha
     # maximum demo site without making the browser form invalid on load.
     "min": 0, "max": 200000, "step": 500, "unit": "kWh"},
    {"path": "hub.pv.peak_kw", "label": "PV peak power", "kind": "number",
     "min": 0, "max": 20000, "step": 100, "unit": "kWp"},
    {"path": "hub.crop.dli_target_mol_m2", "label": "Light target", "kind": "number",
     "min": 0, "max": 30, "step": 0.5, "unit": "mol/m2",
     "help": "Supplemental daily light integral the crop needs."},
    {"path": "hub.floor_area_m2", "label": "Greenhouse area", "kind": "number",
     "min": 96, "max": 200000, "step": 1000, "unit": "m2",
     "help": "Validation runs at 96 m2; scenarios at commercial scale. Do not mix them."},

    {"path": "brief", "label": "Operator brief", "kind": "textarea",
     "help": "Plain language instruction passed to the planner."},
)


class ApiError(Exception):
    """A request the server understood and refused, with an HTTP status."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


#: The offline showcase day the grower page plans when no scenario is chosen
#: (``SHOWCASE_DATE`` and ``SHOWCASE_SEED`` in demo.js).
SHOWCASE_DATE = "2023-01-15"
#: A random id each browser tab sends, so a shared laptop can keep anonymous
#: visitors' remembered reasons apart (the workshop "separate visitors" setting).
VISITOR_HEADER = "X-KasFlex-Visitor"
SHOWCASE_SEED = 0


def _private_directory(directory: Path) -> None:
    """Let only this user account open the research data (consent, reasons, chats).

    On a shared computer other accounts could otherwise read the stores, which are
    created with the default, world-readable permissions. Windows keeps a user's
    profile private already, and chmod there cannot express this.
    """
    if os.name != "posix":
        return
    try:
        directory.chmod(0o700)
    except OSError:
        pass  # not ours to change (a mounted or shared folder); the data still works


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not a number JSON allows")


def _get_path(obj: Any, path: str) -> Any:
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def _coerce(spec: dict[str, Any], value: Any) -> Any:
    """Convert an incoming value to the declared kind and check its range.

    Raises:
        ApiError: naming the field, what arrived and what was expected.
    """
    kind, label = spec["kind"], spec["label"]
    try:
        if kind == "bool":
            if isinstance(value, str):
                return value.strip().lower() in {"true", "1", "yes", "on"}
            return bool(value)
        if kind == "int":
            coerced: Any = int(value)
        elif kind == "number":
            coerced = float(value)
        elif kind == "choice":
            coerced = str(value)
            if coerced not in spec["choices"]:
                raise ApiError(
                    f"{label}: {coerced!r} is not one of {spec['choices']}"
                )
            return coerced
        else:
            return str(value)
    except ApiError:
        raise
    except (TypeError, ValueError) as exc:
        raise ApiError(f"{label}: {value!r} is not a valid {kind}") from exc

    low, high = spec.get("min"), spec.get("max")
    if low is not None and coerced < low:
        raise ApiError(f"{label}: {coerced} is below the minimum of {low}")
    if high is not None and coerced > high:
        raise ApiError(f"{label}: {coerced} is above the maximum of {high}")
    return coerced


def _scenario_store() -> ScenarioStore:
    return ScenarioStore(resolve_output("results/scenarios"))


def _apply_overrides(config: ScenarioConfig, overrides: dict[str, Any]) -> ScenarioConfig:
    """Rebuild a scenario config with dotted-path overrides applied.

    Round-trips through :meth:`ScenarioConfig.from_dict` rather than mutating, so
    the interface gets exactly the same validation as a YAML file -- including the
    rejection of unknown keys. A UI that could set a field the config parser would
    refuse is a UI that can produce runs nobody can reproduce from a file.
    """
    spec = {entry["path"]: entry for entry in ADJUSTABLE}
    unknown = set(overrides) - set(spec)
    if unknown:
        raise ApiError(f"not adjustable from the interface: {sorted(unknown)}")

    # Some fields are shown but never accepted from a request. consent_version is
    # the reason this exists: a participant who could set it from the browser could
    # switch off the consent gating that governs their own data.
    locked = sorted(p for p in overrides if spec[p].get("readonly"))
    if locked:
        raise ApiError(f"set only in the scenario file, not from a request: {locked}", 403)

    # Coerce and range-check against the metadata the interface already publishes.
    # Dataclasses do not validate types, so without this a value of "three" for a
    # revision count is accepted here and fails much later inside the run, with an
    # error that says nothing about where it came from.
    overrides = {path: _coerce(spec[path], value) for path, value in overrides.items()}

    # Enumerated from the dataclass rather than listed by hand. A hand-written list
    # silently drops any field added later: the value loaded from YAML disappears
    # and the dataclass default takes its place, which looks like the setting never
    # worked rather than like a bug here.
    payload: dict[str, Any] = {
        f.name: getattr(config, f.name)
        for f in dataclasses.fields(ScenarioConfig)
        if f.name not in ("hub", "checker")
    }
    payload |= {
        "checker": {
            "enabled": config.checker.enabled,
            "explain": config.checker.explain,
            "max_revisions": config.checker.max_revisions,
            "excluded_checks": list(config.checker.excluded_checks),
            "fail_on_projected": config.checker.fail_on_projected,
        },
        "hub": {
            "floor_area_m2": config.hub.floor_area_m2,
            "lamp_power_w_m2": config.hub.lamp_power_w_m2,
            "lamp_ppfd_umol_m2_s": config.hub.lamp_ppfd_umol_m2_s,
            "base_load_kw": config.hub.base_load_kw,
            "contract": dataclasses.asdict(config.hub.contract),
            "battery": dataclasses.asdict(config.hub.battery),
            "chp": dataclasses.asdict(config.hub.chp),
            "boiler": dataclasses.asdict(config.hub.boiler),
            "buffer": dataclasses.asdict(config.hub.buffer),
            "pv": dataclasses.asdict(config.hub.pv),
            "crop": dataclasses.asdict(config.hub.crop),
        },
    }

    for path, value in overrides.items():
        target = payload
        parts = path.split(".")
        for part in parts[:-1]:
            target = target[part]
        target[parts[-1]] = value

    # Battery power is one control in the interface and two fields in the model.
    if "hub.battery.max_charge_kw" in overrides:
        payload["hub"]["battery"]["max_discharge_kw"] = overrides["hub.battery.max_charge_kw"]

    # A workshop scenario fixes its own day, season, grid contract and installation
    # changes (for example a boiler out of order), so every participant plans the
    # same situation whatever else the page sends.
    if payload.get("data_source") == "scenario" and payload.get("scenario_id"):
        try:
            scenario = _scenario_store().get(str(payload["scenario_id"]))
        except KeyError as exc:
            raise ApiError(f"Unknown workshop scenario {payload['scenario_id']!r}.", 404) from exc
        payload["date"] = scenario.date
        payload["winter"] = scenario.winter
        if "grid_contract_type" not in overrides:
            payload["grid_contract_type"] = scenario.grid_contract_type
        for name, value in scenario.hub.items():
            section, key = HUB_FIELDS[name][0]
            payload["hub"][section][key] = value

    try:
        return ScenarioConfig.from_dict(payload, where="interface")
    except ConfigError as exc:
        raise ApiError(str(exc)) from exc
