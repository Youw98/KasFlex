"""A local web server for the KasFlex interface.

Built on ``http.server`` from the standard library. That is an unusual choice and a
deliberate one: the alternative is adding FastAPI, Starlette and uvicorn to a
project whose core dependencies are numpy and PyYAML, in order to serve one page to
one person on their own machine. The interface requirement is "browser-based, no
installation" (R27) -- a framework would work against that.

.. warning::

   **Localhost only, single user, no authentication.** This is a research tool that
   runs a simulation on the machine it is started on. It binds to 127.0.0.1 and
   should not be exposed to a network. If this ever needs to be multi-user or
   hosted, it needs a real framework and a real auth story; do not simply change
   the bind address.

The API is deliberately thin. Everything it does is a call into the same functions
the CLI uses, so the interface cannot drift from what a scripted run would produce.
"""

from __future__ import annotations

import dataclasses
import json
import mimetypes
import os
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from kasflex import i18n
from kasflex.actions import derive_actions
from kasflex.actions import summarise as summarise_actions
from kasflex.api_connections import ApiConnections
from kasflex.checker.rules import SafetyChecker
from kasflex.config import ConfigError, ScenarioConfig
from kasflex.consent import SCOPES as CONSENT_SCOPES
from kasflex.consent import ConsentLog
from kasflex.conversation import (
    PlanContext,
    PlanExplainer,
    detect_conflicts,
    extract_preference,
    propose_compromise,
)
from kasflex.fair import DatasetMetadata, build_bundle, conflict_table, to_csv
from kasflex.forecast.cost import project_cost
from kasflex.intent import IntentSchemaError, IntervalIntent, Plan
from kasflex.llm_providers import PROVIDERS, LlmError, build_call_fn, check_provider, provider_status
from kasflex.memory import STRENGTHS, GrowerMemory
from kasflex.oversight import AuditLog
from kasflex.profiles import ProfileStore
from kasflex.reliance import RelianceLog
from kasflex.resources import resolve_output, static_dir
from kasflex.ui.reviews import ReviewConflict, ReviewStore
from kasflex.uncertainty import (
    ASSUMED_IRRADIANCE_RMSE_W_M2,
    ASSUMED_TEMP_RMSE_C,
    ForecastError,
    day_novelty,
    history_from_conditions,
    measured_forecast_error,
)
from kasflex.uncertainty import describe as describe_uncertainty
from kasflex.uncertainty import estimate as uncertainty_estimate

STATIC_DIR = static_dir()

def _favicon() -> bytes:
    """The mark, served as the tab icon.

    Read from the same file the pages use, so the icon cannot drift from the
    logo. Falls back to a plain badge if the file is missing from a build.
    """
    try:
        return (STATIC_DIR / "mark.svg").read_bytes()
    except OSError:
        return (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
                b'<rect width="16" height="16" rx="3" fill="#1d4220"/></svg>')

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
     "choices": ["synthetic", "cache"],
     "help": "Demo uses generated inputs. Real data reads downloaded prices and weather."},
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
    {"path": "planner", "label": "Planner", "kind": "choice",
     "choices": ["rule-based", "learned", "naive", "llm", "mpc"],
     "help": "Which planner proposes the day. 'learned' forecasts demand and optimises."},
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
     "min": 0, "max": 40000, "step": 500, "unit": "kWh"},
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

    try:
        return ScenarioConfig.from_dict(payload, where="interface")
    except ConfigError as exc:
        raise ApiError(str(exc)) from exc


def _day_for(config: ScenarioConfig):
    from kasflex.data.synthetic import synthetic_day

    try:
        target = date.fromisoformat(config.date)
    except ValueError as exc:
        raise ApiError("Choose a valid date in Configuration.") from exc
    if config.data_source == "cache":
        from types import SimpleNamespace

        from kasflex.data.pipeline import ensure_day
        from kasflex.data.sources import FetchError

        try:
            data = ensure_day(target, latitude=config.latitude, longitude=config.longitude,
                              gas_price_eur_kwh=config.gas_price_eur_kwh,
                              entsoe_zone=config.entsoe_zone, allow_network=False)
        except (FetchError, ValueError, KeyError, OSError) as exc:
            raise ApiError(f"Real data is not ready for {config.date}. "
                           "Open Configuration → Data sources and check availability. "
                           f"Details: {exc}") from exc
        forecast, actual = data.conditions()
        return SimpleNamespace(forecast=forecast, actual=actual,
                               actuals_available=data.actuals_available, sources=data.sources)
    if config.data_source != "synthetic":
        raise ApiError("Choose Demo or Downloaded real data in Configuration.")
    day = synthetic_day(
        config.date,
        seed=config.seed,
        floor_area_m2=config.hub.floor_area_m2,
        winter=config.winter,
    )
    return dataclasses.replace(
        day,
        forecast=tuple(dataclasses.replace(c, gas_price_eur_kwh=config.gas_price_eur_kwh)
                       for c in day.forecast),
        actual=tuple(dataclasses.replace(c, gas_price_eur_kwh=config.gas_price_eur_kwh)
                     for c in day.actual),
    )


def _normal_settings(config: ScenarioConfig, greenhouse, conditions):
    """The same day under normal settings, and what it would cost.

    "Normal settings" is the rule-based planner: the conventional control a grower
    already has. Every action shown answers "instead of what?", and the
    keep-normal-settings choice needs something real to fall back to, so this is
    computed on every run rather than described in the abstract.
    """
    from kasflex.controllers.base import PlanningContext  # noqa: PLC0415
    from kasflex.controllers.rule_based import RuleBasedPlanner  # noqa: PLC0415

    plan = RuleBasedPlanner().plan(
        PlanningContext(date=config.date, forecast=tuple(conditions), hub=config.hub))
    return plan, project_cost(plan, config.hub, tuple(conditions), greenhouse)


def _conditions_for(config: ScenarioConfig, greenhouse, base):
    """Attach the greenhouse's heat and CO2 demand to a weather series."""
    from kasflex.controllers.base import PlanningContext
    from kasflex.controllers.rule_based import RuleBasedPlanner

    nominal = RuleBasedPlanner().plan(
        PlanningContext(date=config.date, forecast=tuple(base), hub=config.hub)
    )
    outcome = greenhouse.simulate_day(nominal, tuple(base), config.hub.floor_area_m2)
    return tuple(
        dataclasses.replace(
            c,
            heat_demand_kw=outcome.heat_demand_kw[i],
            co2_demand_kg_h=outcome.co2_demand_kg_h[i],
        )
        for i, c in enumerate(base)
    ), outcome


def _plan_payload(plan: Plan, conditions) -> list[dict[str, Any]]:
    return [
        {
            "hour": iv.hour,
            "heat_source": iv.heat_source,
            "lighting_level": iv.lighting_level,
            "battery": iv.battery,
            "battery_power_kw": iv.battery_power_kw,
            "chp_mode": iv.chp_mode,
            "co2_source": iv.co2_source,
            "reasoning": iv.reasoning,
            "power_price_eur_kwh": conditions[i].power_price_eur_kwh,
            "heat_demand_kw": round(conditions[i].heat_demand_kw, 1),
            "outdoor_temp_c": round(getattr(conditions[i], "outdoor_temp_c", 0), 1),
            "irradiance_w_m2": round(getattr(conditions[i], "irradiance_w_m2", 0), 0),
        }
        for i, iv in enumerate(plan.intervals)
    ]


@dataclass
class UiServer:
    """Holds the scenario the interface is editing and serves the API."""

    config_path: str = "configs/scenario_westland_winter.yaml"
    anonymous: bool = False
    base: ScenarioConfig = field(init=False)
    connections: ApiConnections = field(init=False)
    reviews: ReviewStore = field(init=False)
    memory: GrowerMemory = field(init=False)
    reliance: RelianceLog = field(init=False)
    consent: ConsentLog = field(init=False)
    profiles: ProfileStore = field(init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.base = ScenarioConfig.from_yaml(self.config_path)
        self.connections = ApiConnections(resolve_output(".env"))
        self.reviews = ReviewStore(resolve_output("results/reviews.sqlite3"))
        self.memory = GrowerMemory(resolve_output(self.base.memory_path))
        self.reliance = RelianceLog(resolve_output(self.base.memory_path))
        self.consent = ConsentLog(resolve_output("results/consent.sqlite3"))
        self.profiles = ProfileStore(resolve_output("results/profiles"))

    # -- what this plan changes, against normal settings --------------------

    def _against_normal(self, config: ScenarioConfig, result, conditions,
                        greenhouse) -> dict[str, Any]:
        """Actions, the saving, and the fallback plan, for the Tomorrow screen.

        Returns empty-but-present fields rather than omitting them on failure: the
        interface can say "nothing needs to change" honestly, but it cannot render
        a key that is sometimes missing.
        """
        try:
            baseline, baseline_cost = _normal_settings(config, greenhouse, conditions)
            normal_total = float((baseline_cost.get("totals") or {}).get("net_cost_eur", 0.0))
            planned_total = float(result.metrics.get("net_cost_eur", 0.0))
            saving = normal_total - planned_total
            baseline_rows = _plan_payload(baseline, conditions)
            actions = derive_actions(
                _plan_payload(result.plan, conditions), baseline_rows,
                language=config.language,
                saving_eur=saving if saving > 0 else None)
            return {
                "actions": [a.to_dict() for a in actions],
                "actions_summary": summarise_actions(actions, config.language),
                "normal_settings": {
                    "plan": baseline_rows,
                    "net_cost_eur": normal_total,
                    "saving_eur": saving,
                },
            }
        except Exception:  # noqa: BLE001 - a plan is still usable without the comparison
            return {"actions": [], "actions_summary": "", "normal_settings": None}

    # -- uncertainty --------------------------------------------------------

    def _novelty_history(self, config: ScenarioConfig) -> list[dict[str, float]]:
        """Past days to judge today against, from whichever source this run uses.

        Returns an empty list rather than inventing a comparison set; the caller
        then reports epistemic uncertainty as unknown, which is the honest answer.
        """
        try:
            if config.data_source == "cache":
                from kasflex.data.cache import DataCache  # noqa: PLC0415
                from kasflex.data.pipeline import cached_days, ensure_day  # noqa: PLC0415

                cache = DataCache()
                days = cached_days(cache, config.latitude, config.longitude)[-90:]
                series = []
                for iso in days:
                    data = ensure_day(date.fromisoformat(iso), cache=cache,
                                      latitude=config.latitude, longitude=config.longitude,
                                      gas_price_eur_kwh=config.gas_price_eur_kwh,
                                      entsoe_zone=config.entsoe_zone,
                                      allow_network=False, want_actuals=False)
                    series.append(data.conditions()[0])
                return history_from_conditions(series)

            from kasflex.data.synthetic import synthetic_history  # noqa: PLC0415

            weather = synthetic_history(config.history_days, seed=config.seed + 9_000,
                                        floor_area_m2=config.hub.floor_area_m2,
                                        winter=config.winter)
            return history_from_conditions([day.forecast for day in weather.days])
        except Exception:  # noqa: BLE001 - absence of history is not an error
            return []

    def _uncertainty(self, config: ScenarioConfig, plan, conditions,
                     greenhouse) -> dict[str, Any]:
        """Cost band and novelty for one plan, with its basis stated."""
        from kasflex.data.cache import DataCache  # noqa: PLC0415

        try:
            error = measured_forecast_error(DataCache(), config.latitude, config.longitude)
        except Exception:  # noqa: BLE001 - fall back to the labelled assumption
            error = ForecastError(temp_rmse_c=ASSUMED_TEMP_RMSE_C,
                                  irradiance_rmse_w_m2=ASSUMED_IRRADIANCE_RMSE_W_M2)
        novelty = day_novelty(conditions, self._novelty_history(config))
        estimate = uncertainty_estimate(plan, config.hub, conditions, greenhouse,
                                        forecast_error=error, novelty=novelty,
                                        seed=config.seed)
        return {**estimate.to_dict(),
                "words": describe_uncertainty(estimate, config.language)}

    # -- the model that talks to the grower --------------------------------

    def _model_settings(self, overrides: dict[str, Any]) -> tuple[str, str, str, str, bool]:
        """(provider, model, base_url, language, fold_system) after UI overrides."""
        config = _apply_overrides(self.base, overrides or {})
        return (config.llm_provider, config.llm_model, config.llm_base_url,
                i18n.normalise(config.language), config.llm_fold_system)

    def _explainer(self, overrides: dict[str, Any]) -> tuple[PlanExplainer, str]:
        """Build an explainer, or say plainly that no model is configured.

        Raises:
            ApiError: when the chosen provider has no key. The message is the one
                shown to the grower, so it says what to do rather than what failed.
        """
        provider, model, base_url, language, fold = self._model_settings(overrides)
        if provider not in PROVIDERS:
            raise ApiError(i18n.translate("chat.no_model", language))
        spec = PROVIDERS[provider]
        if spec.env_var and not os.environ.get(spec.env_var):
            raise ApiError(i18n.translate("chat.no_model", language))
        try:
            call_fn = build_call_fn(provider, base_url=base_url or None, fold_system=fold)
        except LlmError as exc:
            raise ApiError(str(exc)) from exc
        return PlanExplainer(call_fn, model, self.memory), language

    def _plan_context(self, payload: dict[str, Any], language: str) -> PlanContext:
        plan = payload.get("plan") or []
        if not isinstance(plan, list) or not plan:
            raise ApiError("Generate a plan before asking about it.", 409)
        return PlanContext(
            run_id=str(payload.get("run_id") or "unsaved"),
            date=str(payload.get("date") or self.base.date),
            plan=plan,
            metrics=payload.get("metrics") or {},
            language=language,
            cost_forecast=payload.get("cost_forecast"),
            verdict_note=str(payload.get("verdict_note") or ""),
            data_source=str(payload.get("data_source") or self.base.data_source),
        )

    # -- conversation -------------------------------------------------------

    def explain(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Answer one grower question about a plan."""
        # Validate the request before checking configuration: a grower with no plan
        # and no model should be told to make a plan, not sent to set up an AI.
        language = self._model_settings(payload.get("overrides", {}))[3]
        context = self._plan_context(payload, language)
        explainer, _ = self._explainer(payload.get("overrides", {}))
        hour = payload.get("hour")
        # Without consent for verbatim storage the grower still gets their answer;
        # what stops is the transcript. Refusing to answer would punish someone for
        # declining, which is how consent stops being freely given.
        record = self._may_record(payload.get("overrides", {}), "quotes")
        try:
            return {**explainer.ask(context, str(payload.get("question", "")),
                                    hour=int(hour) if hour is not None else None,
                                    record=record),
                    "recorded": record}
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
        except LlmError as exc:
            raise ApiError(str(exc), status=502) from exc

    def conversation(self, run_id: str) -> dict[str, Any]:
        return {"run_id": run_id, "turns": self.memory.turns(run_id)}

    def suggested_questions(self, overrides: dict[str, Any]) -> dict[str, Any]:
        language = self._model_settings(overrides)[3]
        return {"questions": PlanExplainer(lambda *a: "", "").opening_questions(language)}

    # -- preferences --------------------------------------------------------

    def list_preferences(self) -> dict[str, Any]:
        return {
            "preferences": [p.to_dict() for p in
                            self.memory.preferences(include_unconfirmed=True)],
            "statistics": self.memory.statistics(),
            "strengths": list(STRENGTHS),
        }

    def add_preference(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            pref = self.memory.add_preference(
                str(payload.get("rule", "")),
                str(payload.get("reason", "")),
                strength=str(payload.get("strength", "preference")),
                scope=payload.get("scope") or {},
                source=str(payload.get("source", "grower")),
                origin_run_id=str(payload.get("run_id", "")),
                origin_revision=int(payload.get("revision", 0) or 0),
                confirmed=payload.get("confirmed", True) is not False,
            )
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
        return pref.to_dict()

    def change_preference(self, payload: dict[str, Any]) -> dict[str, Any]:
        pref_id = str(payload.get("pref_id", ""))
        action = str(payload.get("action", ""))
        try:
            if action == "retire":
                pref = self.memory.retire_preference(pref_id, str(payload.get("reason", "")))
            elif action == "confirm":
                pref = self.memory.confirm_preference(pref_id)
            else:
                raise ApiError("Unknown action for a preference.")
        except KeyError as exc:
            raise ApiError("That preference no longer exists.", 404) from exc
        return pref.to_dict()

    def preference_from_objection(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Turn a grower's objection into a rule they can confirm."""
        explainer, language = self._explainer(payload.get("overrides", {}))
        context = None
        if payload.get("plan"):
            context = self._plan_context(payload, language)
        hour = payload.get("hour")
        try:
            proposal = extract_preference(
                explainer.call_fn, explainer.model, str(payload.get("objection", "")),
                language=language, plan_context=context,
                hour=int(hour) if hour is not None else None)
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
        except LlmError as exc:
            raise ApiError(str(exc), status=502) from exc
        run_id = str(payload.get("run_id") or "unsaved")
        self.memory.add_turn(run_id, "grower", str(payload.get("objection", "")),
                             hour=proposal.get("scope", {}).get("hours", [None])[0]
                             if proposal.get("scope", {}).get("hours") else None,
                             meta={"kind": "objection"})
        stored = self.memory.add_preference(
            proposal["rule"], proposal["reason"], strength=proposal["strength"],
            scope=proposal["scope"], source="inferred", origin_run_id=run_id,
            confirmed=False)
        return {**proposal, "pref_id": stored.pref_id}

    # -- conflict and compromise -------------------------------------------

    def record_conflicts(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Store every field the grower changed, against what the planner chose."""
        original, edited = payload.get("original") or [], payload.get("edited") or []
        if not original or not edited:
            raise ApiError("Nothing to compare.", 409)
        run_id = str(payload.get("run_id") or "unsaved")
        revision = int(payload.get("revision", 0) or 0)
        reason = str(payload.get("reason", ""))
        stored = []
        for found in detect_conflicts(original, edited):
            conflict = self.memory.record_conflict(
                run_id=run_id, revision=revision, grower_reason=reason, **found)
            stored.append(dataclasses.asdict(conflict))
        return {"conflicts": stored, "count": len(stored)}

    def list_conflicts(self, run_id: str = "") -> dict[str, Any]:
        return {"conflicts": [dataclasses.asdict(c) for c in self.memory.conflicts(run_id)],
                "statistics": self.memory.statistics()}

    def resolve_conflict(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            conflict = self.memory.resolve_conflict(
                str(payload.get("conflict_id", "")),
                str(payload.get("resolution", "")),
                str(payload.get("resolved_value", "")),
                str(payload.get("note", "")))
        except KeyError as exc:
            raise ApiError("That disagreement is no longer on record.", 404) from exc
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
        return dataclasses.asdict(conflict)

    def find_compromise(self, payload: dict[str, Any]) -> dict[str, Any]:
        explainer, language = self._explainer(payload.get("overrides", {}))
        context = self._plan_context(payload, language)
        try:
            result = propose_compromise(
                explainer.call_fn, explainer.model, context=context,
                hour=int(payload.get("hour", 0)),
                field_name=str(payload.get("field_name", "")),
                ai_value=str(payload.get("ai_value", "")),
                grower_value=str(payload.get("grower_value", "")),
                grower_reason=str(payload.get("grower_reason", "")),
                safety_blocked=bool(payload.get("safety_blocked")),
                cost_delta_eur=float(payload.get("cost_delta_eur", 0) or 0))
        except LlmError as exc:
            raise ApiError(str(exc), status=502) from exc
        return result

    # -- consent -------------------------------------------------------------

    def _may_record(self, overrides: dict[str, Any], scope: str) -> bool:
        """Whether this scope may be written to for the current participant.

        With no ``consent_version`` configured no study is running, so nothing is
        gated -- the ordinary case of one person using the tool on their own
        machine. Once a version is set, absence of consent means no.
        """
        config = _apply_overrides(self.base, overrides or {})
        if not config.consent_version:
            return True
        return self.consent.allows(config.participant_id, scope)

    def consent_status(self, overrides: dict[str, Any]) -> dict[str, Any]:
        config = _apply_overrides(self.base, overrides or {})
        current = self.consent.current(config.participant_id)
        return {
            "study_active": bool(config.consent_version),
            "version": config.consent_version,
            "participant_id": config.participant_id,
            "condition": config.condition,
            "needs_consent": bool(config.consent_version)
                             and self.consent.needs_consent(config.participant_id,
                                                            config.consent_version),
            "current": current.to_dict() if current else None,
            "scopes": dict(CONSENT_SCOPES),
            "summary": self.consent.summary(),
        }

    def grant_consent(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = _apply_overrides(self.base, payload.get("overrides", {}))
        participant = str(payload.get("participant_id") or config.participant_id)
        version = str(payload.get("version") or config.consent_version)
        try:
            consent = self.consent.grant(participant, payload.get("scopes") or {},
                                         version=version,
                                         note=str(payload.get("note", "")))
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
        return consent.to_dict()

    def withdraw_consent(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Withdraw, and erase the participant's data unless asked not to."""
        config = _apply_overrides(self.base, payload.get("overrides", {}))
        participant = str(payload.get("participant_id") or config.participant_id)
        try:
            consent = self.consent.withdraw(participant, str(payload.get("reason", "")))
            deleted = ({} if payload.get("erase") is False
                       else self.consent.erase(participant,
                                               [resolve_output(self.base.memory_path)]))
        except KeyError as exc:
            raise ApiError("No consent record for that participant.", 404) from exc
        return {**consent.to_dict(), "deleted": deleted}

    # -- reliance measurement -----------------------------------------------

    def elicit(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Record what the grower would do, before any suggestion is shown."""
        if not self._may_record(payload.get("overrides", {}), "research"):
            raise ApiError("This has not been consented to.", 403)
        try:
            item = self.reliance.elicit(
                run_id=str(payload.get("run_id") or "unsaved"),
                question=str(payload.get("question", "day_overall")),
                grower_choice=str(payload.get("grower_choice", "")),
                confidence=payload.get("confidence", 0),
                hour=(int(payload["hour"]) if payload.get("hour") is not None else None),
                condition=str(payload.get("condition", "")),
                note=str(payload.get("note", "")))
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
        return item.to_dict()

    def elicitation_step(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Advance one elicitation: ``reveal``, ``resolve`` or ``score``."""
        elicitation_id = str(payload.get("elicitation_id", ""))
        action = str(payload.get("action", ""))
        try:
            if action == "reveal":
                item = self.reliance.reveal(elicitation_id,
                                            str(payload.get("ai_choice", "")),
                                            str(payload.get("ai_confidence", "")))
            elif action == "resolve":
                item = self.reliance.resolve(elicitation_id,
                                             str(payload.get("final_choice", "")),
                                             str(payload.get("note", "")))
            elif action == "score":
                item = self.reliance.score(elicitation_id,
                                           str(payload.get("better_choice", "")),
                                           str(payload.get("note", "")))
            else:
                raise ApiError("Unknown step for an elicitation.")
        except KeyError as exc:
            raise ApiError("That decision is no longer on record.", 404) from exc
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
        return item.to_dict()

    def list_elicitations(self, run_id: str = "") -> dict[str, Any]:
        return {"elicitations": [e.to_dict() for e in self.reliance.elicitations(run_id)]}

    def record_outcome(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Record what a day actually cost, against what was predicted."""
        if not self._may_record(payload.get("overrides", {}), "outcomes"):
            raise ApiError("This has not been consented to.", 403)
        try:
            outcome = self.reliance.record_outcome(
                run_id=str(payload.get("run_id") or "unsaved"),
                predicted_cost_eur=float(payload.get("predicted_cost_eur", 0) or 0),
                actual_cost_eur=float(payload.get("actual_cost_eur", 0) or 0),
                ai_plan_cost_eur=(None if payload.get("ai_plan_cost_eur") is None
                                  else float(payload["ai_plan_cost_eur"])),
                final_plan_cost_eur=(None if payload.get("final_plan_cost_eur") is None
                                     else float(payload["final_plan_cost_eur"])),
                within_predicted_band=payload.get("within_predicted_band"),
                note=str(payload.get("note", "")))
        except (TypeError, ValueError) as exc:
            raise ApiError("An outcome needs numeric costs.") from exc
        return outcome.to_dict()

    def reliance_metrics(self, condition: str = "") -> dict[str, Any]:
        return self.reliance.metrics(condition)

    # -- saved setups -------------------------------------------------------

    def list_profiles(self) -> dict[str, Any]:
        return {"profiles": [dataclasses.asdict(p) for p in self.profiles.list()]}

    def save_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            profile = self.profiles.create(
                str(payload.get("name", "")), payload.get("settings") or {},
                equipment=payload.get("equipment") or {},
                language=str(payload.get("language", "en")),
                notes=str(payload.get("notes", "")))
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
        return dataclasses.asdict(profile)

    def delete_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.profiles.delete(str(payload.get("profile_id", "")))
        return self.list_profiles()

    def import_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            profile = self.profiles.import_text(str(payload.get("text", "")))
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
        return dataclasses.asdict(profile)

    def export_profile(self, profile_id: str) -> str:
        try:
            return self.profiles.export_text(profile_id)
        except KeyError as exc:
            raise ApiError("That setup no longer exists.", 404) from exc

    # -- models -------------------------------------------------------------

    def model_status(self) -> dict[str, Any]:
        provider, model, base_url, language, fold = self._model_settings({})
        return {"providers": provider_status(), "selected": {
            "provider": provider, "model": model, "base_url": base_url,
            "fold_system": fold},
            "language": language}

    def test_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider = str(payload.get("provider") or self.base.llm_provider)
        model = str(payload.get("model") or self.base.llm_model)
        if provider not in PROVIDERS:
            raise ApiError("Choose one of the listed AI services.")
        return check_provider(provider, model,
                              base_url=str(payload.get("base_url") or "") or None)

    # -- language -----------------------------------------------------------

    def translations(self, language: str) -> dict[str, Any]:
        code = i18n.normalise(language)
        return {"language": code, "languages": i18n.language_options(),
                "strings": i18n.catalog_for(code)}

    # -- research export ----------------------------------------------------

    def fair_bundle(self, anonymous: bool = True) -> dict[str, Any]:
        from kasflex.data.cache import DataCache  # noqa: PLC0415

        # A study in progress exports only what people agreed to share. With no
        # consent version configured there is no study and nothing to filter.
        if self.base.consent_version:
            withdrawn = [c.participant_id for c in self.consent.participants()
                         if not c.allows("research")]
            if withdrawn:
                raise ApiError(
                    "Export blocked: "
                    f"{len(withdrawn)} participant(s) have not consented to research "
                    "use or have withdrawn. Erase their data first, or export per "
                    "participant.", 409)

        try:
            provenance = {k: dataclasses.asdict(v) for k, v in DataCache().entries().items()}
        except OSError:
            provenance = {}
        return build_bundle(
            metadata=DatasetMetadata(language=i18n.normalise(self.base.language)),
            memory_export={**self.memory.export(), **self.reliance.export()},
            runs=self.reviews.history(limit=100),
            data_provenance=provenance,
            software={"scenario": self.base.name, "planner": self.base.planner,
                      "greenhouse_model": self.base.greenhouse,
                      "llm_provider": self.base.llm_provider,
                      "llm_model": self.base.llm_model},
            anonymous=anonymous,
        )

    # -- endpoints ---------------------------------------------------------

    def get_settings(self) -> dict[str, Any]:
        """The adjustable fields, their current values and their metadata."""
        fields = []
        for entry in ADJUSTABLE:
            item = dict(entry)
            item["value"] = _get_path(self.base, entry["path"])
            fields.append(item)
        return {
            "scenario": self.base.name,
            "config_path": self.config_path,
            "fields": fields,
            "entsoe_configured": bool(os.environ.get("ENTSOE_API_KEY")),
        }

    def data_status(self, overrides: dict[str, Any], download: bool = False) -> dict[str, Any]:
        """Check local coverage or explicitly acquire data; never silently substitute demo data."""
        from kasflex.data.cache import DataCache
        from kasflex.data.pipeline import ensure_day
        from kasflex.data.sources import FetchError

        config = _apply_overrides(self.base, overrides)
        try:
            target = date.fromisoformat(config.date)
        except ValueError as exc:
            raise ApiError("Choose a valid date in Configuration.") from exc
        cache = DataCache()
        site = f"{config.latitude:.3f}_{config.longitude:.3f}"
        keys = {"Electricity prices": f"entsoe_da_{config.date}",
                "Weather forecast": f"weather_forecast_{config.date}_{site}",
                "Weather reanalysis": f"weather_actual_{config.date}_{site}"}
        message = ""
        if download:
            if target < date.today():
                raise ApiError("Downloading archived forecasts is not available here yet. "
                               "Choose today or tomorrow, or use an existing historical cache. "
                               "Historical observations cannot replace a forecast.")
            try:
                ensure_day(target, cache=cache, latitude=config.latitude,
                           longitude=config.longitude, gas_price_eur_kwh=config.gas_price_eur_kwh,
                           entsoe_zone=config.entsoe_zone, allow_network=True, want_actuals=False)
                message = "Prices and forecast downloaded. Runs can now use this day offline."
            except (FetchError, ValueError, OSError):
                # Never return a transport exception containing a credential-bearing URL.
                message = ("Download incomplete. Check your server's ENTSOE_API_KEY, network "
                           "connection, and whether prices for this date have been published. "
                           "Any completed downloads remain cached.")
        entries = cache.entries()
        rows = []
        for label, key in keys.items():
            valid = False
            if cache.has(key):
                try:
                    values = cache.get(key)
                    hours = sorted(int(r["hour"]) for r in values)
                    valid = len(values) == 24 and hours == list(range(24))
                except (ValueError, KeyError, OSError):
                    valid = False
            entry = entries.get(key)
            rows.append({"label": label, "ready": valid,
                         "retrieved_on": entry.retrieved_on if entry else None,
                         "source": entry.source if entry else None})
        return {"date": config.date, "ready": all(r["ready"] for r in rows[:2]),
                "actuals_available": rows[2]["ready"], "series": rows,
                "entsoe_configured": bool(os.environ.get("ENTSOE_API_KEY")), "message": message}

    def run(self, overrides: dict[str, Any]) -> dict[str, Any]:
        """Run one scenario and return everything the page needs to show it."""
        from kasflex.experiment import build_greenhouse, build_planner
        from kasflex.run import run_scenario

        config = _apply_overrides(self.base, overrides)
        day = _day_for(config)
        greenhouse = build_greenhouse(config.greenhouse, config)

        started = time.time()
        try:
            planner = build_planner(config.planner, config)
        except ValueError as exc:
            raise ApiError(str(exc)) from exc

        try:
            result = run_scenario(
                scenario=f"{config.name}/ui",
                date=config.date,
                hub=config.hub,
                forecast=day.forecast,
                actual=day.actual,
                planner=planner,
                greenhouse=greenhouse,
                checker_config=config.checker,
                audit_log=AuditLog(resolve_output(config.audit_path), anonymous=self.anonymous),
                brief=config.brief,
                seed=config.seed,
                provenance={"data_source": config.data_source, "via": "ui",
                            "actuals_available": getattr(day, "actuals_available", False),
                            "series": getattr(day, "sources", {})},
            )
        except NotImplementedError as exc:
            raise ApiError(str(exc), status=501) from exc

        conditions, _ = _conditions_for(config, greenhouse, day.forecast)
        hard = result.realised_hard_violations
        response = {
            "date": result.date,
            "planner": result.planner,
            "greenhouse_model": result.greenhouse_model,
            "validated": result.outcome.validated,
            "checker_enabled": result.checker_enabled,
            "accepted": result.verdict.accepted,
            "fell_back": result.fell_back_to_baseline,
            "revisions_used": result.revisions_used,
            "feedback": result.verdict.feedback(explain=config.checker.explain),
            "violations": [v.to_dict() for v in result.verdict.violations],
            "realised_hard": hard,
            "realised_projected": len(result.realised_violations) - hard,
            "metrics": result.metrics,
            "uncertainty": self._uncertainty(config, result.plan, conditions, greenhouse),
            "cost_forecast": project_cost(result.plan, config.hub, day.forecast, greenhouse),
            **self._against_normal(config, result, conditions, greenhouse),
            "plan": _plan_payload(result.plan, conditions),
            "elapsed_s": round(time.time() - started, 2),
            "overrides": overrides,
            "data_source": config.data_source,
            "actuals_available": getattr(day, "actuals_available", False),
            "series_origin": getattr(day, "sources", {}),
            "battery_config": {
                "capacity_kwh": config.hub.battery.capacity_kwh,
                "soc_init_kwh": config.hub.battery.soc_init_kwh,
            },
        }
        snapshot = {"config": dataclasses.asdict(config),
                    "forecast": [dataclasses.asdict(c) for c in day.forecast],
                    "actual": [dataclasses.asdict(c) for c in day.actual]}
        response["configuration"] = {f["path"]: _get_path(config, f["path"]) for f in ADJUSTABLE}
        return self.reviews.create(snapshot, response)

    def verify(self, overrides: dict[str, Any], plan_rows: list[dict[str, Any]],
               reference: dict | None = None) -> dict[str, Any]:
        """Re-verify a plan a person has edited (R23).

        An edit is never accepted on the strength of having been made by a human.
        It goes back through exactly the same checker the planner's output did.
        """
        from kasflex.experiment import build_greenhouse

        snapshot, previous = self.reviews.current(reference) if reference else (None, None)
        config = (ScenarioConfig.from_dict(snapshot["config"]) if snapshot
                  else _apply_overrides(self.base, overrides))
        # The rows sent back carry the display-only columns this server added when
        # it rendered the plan (price, heat demand). The intent schema rightly
        # rejects unknown fields, so strip them here rather than loosening the
        # schema: the strictness is what stops a planner inventing fields.
        intent_fields = set(IntervalIntent.__dataclass_fields__)
        cleaned = [
            {k: v for k, v in row.items() if k in intent_fields} for row in plan_rows
        ]
        try:
            plan = Plan.from_dict({"date": config.date, "planner": "human-edited",
                                   "intervals": cleaned})
        except IntentSchemaError as exc:
            raise ApiError(f"edited plan is not valid: {exc}") from exc

        if snapshot:
            from kasflex.energy.dispatch import HourlyConditions

            forecast = tuple(HourlyConditions(**row) for row in snapshot["forecast"])
        else:
            forecast = _day_for(config).forecast
        greenhouse = build_greenhouse(config.greenhouse, config)
        conditions, outcome = _conditions_for(config, greenhouse, forecast)
        verification_config = dataclasses.replace(config.checker, enabled=True)
        verdict = SafetyChecker(config.hub, verification_config).verify(
            plan, conditions, outcome.projection()
        )

        from kasflex.energy.dispatch import dispatch_plan

        dispatch = dispatch_plan(plan, config.hub, list(conditions))
        response = {
            "accepted": verdict.accepted,
            "checker_enabled": True,
            "verification_config": dataclasses.asdict(verification_config),
            "feedback": verdict.feedback(explain=config.checker.explain),
            "violations": [v.to_dict() for v in verdict.violations],
            "metrics": dispatch.summary(),
            "cost_forecast": project_cost(plan, config.hub, forecast, greenhouse),
        }
        if reference:
            # Restore all display-only inputs from the frozen server snapshot.
            response = {**previous, **response, "plan": _plan_payload(plan, conditions),
                        "planner": "human-edited", "realised_hard": None,
                        "realised_projected": None, "edited_preview": True,
                        "fell_back": False, "revisions_used": 0}
            return self.reviews.revise(reference, response)
        # Direct callers can inspect a detached plan; only saved revisions can be approved.
        return response

    def decide(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Record a human decision in the append-only log (R25, R26)."""
        decision = str(payload.get("decision", "")).lower()
        if decision not in {"approve", "reject", "edit"}:
            raise ApiError("decision must be approve, reject or edit")
        snapshot, _ = self.reviews.current(payload)
        # Interaction timing is optional research data, not a condition of using the app.
        consent = payload.get("research_consent") is True
        duration = payload.get("seconds_to_decide") if consent else None
        if duration is not None and (not isinstance(duration, (int, float))
                                     or not 0 <= duration <= 86400):
            raise ApiError("Review duration must be between zero and 24 hours.")
        saved = self.reviews.decide(payload, {
            "decision": decision, "comment": str(payload.get("comment", ""))[:2000],
            "seconds_to_decide": duration, "research_consent": consent,
            "operator": "anonymous" if self.anonymous else str(payload.get("operator", "")),
        })
        if not saved["duplicate"]:
            AuditLog(resolve_output(snapshot["config"]["audit_path"]),
                     anonymous=self.anonymous).append("human_decision_ui", saved,
                                                     operator=saved["operator"])
        return {"recorded": True, "anonymous": self.anonymous, **saved}

    def compare(self, overrides: dict[str, Any], planners: list[str]) -> dict[str, Any]:
        """Run several planners on the identical scenario (R29)."""
        rows = []
        for name in planners:
            try:
                rows.append({"planner": name, **self._compare_row(overrides, name)})
            except ApiError as exc:
                rows.append({"planner": name, "error": str(exc)})
        return {"rows": rows}

    def _compare_row(self, overrides: dict[str, Any], planner: str) -> dict[str, Any]:
        result = self.run({**overrides, "planner": planner})
        return {
            "cost_eur": result["metrics"]["net_cost_eur"],
            "cost_eur_per_m2": result["metrics"]["net_cost_eur_per_m2"],
            "hard_violations": result["realised_hard"],
            "projected_violations": result["realised_projected"],
            "peak_import_kw": result["metrics"]["peak_import_kw"],
            "dli_mol_m2": result["metrics"]["supplemental_dli_mol_m2"],
            "band_hours": result["metrics"]["temperature_band_hours"],
            "growth_kg_m2": result["metrics"]["fruit_growth_kg_m2"],
            "fell_back": result["fell_back"],
            "accepted": result["accepted"],
        }


class _Handler(BaseHTTPRequestHandler):
    server_version = "kasflex"
    ui: UiServer

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A002
        """Quieter than the default, which prints a line per asset request."""
        if args and "api" in str(args[0]):
            super().log_message(fmt, *args)

    # -- plumbing ----------------------------------------------------------

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: Any, status: int = 200) -> None:
        self._send(status, json.dumps(payload, default=str).encode(), "application/json")

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            data = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ApiError(f"request body is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ApiError("request body must be a JSON object")
        return data

    #: The grower page is the front door; the researcher interface is a step aside
    #: from it. A grower who has been told "just open KasFlex" must not land in a
    #: screen built for someone comparing planners.
    _PAGES = {"": "grower.html", "/": "grower.html",
              "/advanced": "index.html", "/research": "index.html",
              "/setup": "setup.html"}

    def _static(self, path: str) -> None:
        name = self._PAGES.get(path.rstrip("/") or "/") or path.lstrip("/")
        target = (STATIC_DIR / name).resolve()
        if not target.is_file() or STATIC_DIR.resolve() not in target.parents:
            self._send(404, b"not found", "text/plain")
            return
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._send(200, target.read_bytes(), kind)

    # -- routes ------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        try:
            if self.path == "/api/connections":
                self._json(self.ui.connections.status())
            elif self.path == "/api/reviews":
                self._json({"runs": self.ui.reviews.history()})
            elif self.path.startswith("/api/reviews/"):
                self._json(self.ui.reviews.get(self.path.removeprefix("/api/reviews/")))
            elif self.path.startswith("/api/settings"):
                self._json(self.ui.get_settings())
            elif self.path.startswith("/api/i18n"):
                query = dict(parse_qsl(urlsplit(self.path).query))
                self._json(self.ui.translations(query.get("lang", "")))
            elif self.path == "/api/models":
                self._json(self.ui.model_status())
            elif self.path == "/api/preferences":
                self._json(self.ui.list_preferences())
            elif self.path.startswith("/api/conflicts"):
                query = dict(parse_qsl(urlsplit(self.path).query))
                self._json(self.ui.list_conflicts(query.get("run_id", "")))
            elif self.path.startswith("/api/conversation/"):
                self._json(self.ui.conversation(
                    self.path.removeprefix("/api/conversation/").split("?")[0]))
            elif self.path.startswith("/api/consent"):
                query = dict(parse_qsl(urlsplit(self.path).query))
                overrides = {k: v for k, v in query.items()
                             if k in ("participant_id", "condition")}
                self._json(self.ui.consent_status(overrides))
            elif self.path.startswith("/api/reliance"):
                query = dict(parse_qsl(urlsplit(self.path).query))
                self._json(self.ui.reliance_metrics(query.get("condition", "")))
            elif self.path.startswith("/api/elicitations"):
                query = dict(parse_qsl(urlsplit(self.path).query))
                self._json(self.ui.list_elicitations(query.get("run_id", "")))
            elif self.path == "/api/profiles":
                self._json(self.ui.list_profiles())
            elif self.path.startswith("/api/profiles/export/"):
                profile_id = self.path.removeprefix("/api/profiles/export/").split("?")[0]
                body = self.ui.export_profile(profile_id).encode("utf-8")
                self._send(200, body, "application/json; charset=utf-8")
            elif self.path.startswith("/api/export/fair"):
                query = dict(parse_qsl(urlsplit(self.path).query))
                bundle = self.ui.fair_bundle(query.get("anonymous", "1") != "0")
                if query.get("format") == "csv":
                    body = to_csv(conflict_table({
                        "conflicts": bundle.get("kasflex:conflicts", [])})).encode("utf-8")
                    self._send(200, body, "text/csv; charset=utf-8")
                else:
                    self._json(bundle)
            elif self.path.startswith("/favicon.ico"):
                # Answer rather than 404: a browser asks for this unprompted, and a
                # console full of red on first load makes a working page look broken.
                self._send(200, _favicon(), "image/svg+xml")
            else:
                self._static(self.path.split("?")[0])
        except ReviewConflict as exc:
            self._json({"error": str(exc)}, 409)
        except ApiError as exc:
            self._json({"error": str(exc)}, exc.status)
        except Exception as exc:  # noqa: BLE001
            self._json({"error": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc()[-1500:]}, 500)

    def do_POST(self) -> None:  # noqa: N802
        try:
            if self.path == "/api/connections":
                # Require a same-origin JSON request before accepting local credentials.
                origin = self.headers.get("Origin")
                if origin and urlsplit(origin).netloc != self.headers.get("Host"):
                    raise ApiError("API keys can only be saved from this local workspace.", 403)
                if self.headers.get("Sec-Fetch-Site") == "cross-site":
                    raise ApiError("API keys can only be saved from this local workspace.", 403)
                if self.headers.get_content_type() != "application/json":
                    raise ApiError("Use a JSON request to save an API key.", 415)
                if int(self.headers.get("Content-Length") or 0) > 8192:
                    raise ApiError("API key request is too large.", 413)
            body = self._body()
            overrides = body.get("overrides", {})
            if self.path == "/api/connections":
                try:
                    with self.ui._lock:
                        result = self.ui.connections.save(body.get("provider", ""),
                                                          body.get("api_key", ""),
                                                          remove=body.get("remove") is True)
                except ValueError as exc:
                    raise ApiError(str(exc)) from exc
                except OSError as exc:
                    raise ApiError("Could not save the local .env file. "
                                   "Check folder permissions.") from exc
                self._json(result)
            elif self.path.startswith("/api/run"):
                self._json(self.ui.run(overrides))
            elif self.path == "/api/data-status":
                self._json(self.ui.data_status(overrides))
            elif self.path == "/api/data-download":
                with self.ui._lock:
                    self._json(self.ui.data_status(overrides, download=True))
            elif self.path.startswith("/api/verify"):
                if not all(k in body for k in ("run_id", "revision", "plan_hash")):
                    raise ApiError("Generate or reopen a saved plan before verifying edits.", 409)
                self._json(self.ui.verify(overrides, body.get("plan", []), reference=body))
            elif self.path.startswith("/api/decision"):
                self._json(self.ui.decide(body))
            elif self.path.startswith("/api/compare"):
                self._json(self.ui.compare(
                    overrides,
                    body.get("planners") or ["rule-based", "learned", "naive"],
                ))
            elif self.path == "/api/explain":
                self._json(self.ui.explain(body))
            elif self.path == "/api/suggested-questions":
                self._json(self.ui.suggested_questions(overrides))
            elif self.path == "/api/preferences":
                with self.ui._lock:
                    self._json(self.ui.add_preference(body))
            elif self.path == "/api/preferences/change":
                with self.ui._lock:
                    self._json(self.ui.change_preference(body))
            elif self.path == "/api/preferences/from-objection":
                with self.ui._lock:
                    self._json(self.ui.preference_from_objection(body))
            elif self.path == "/api/conflicts":
                with self.ui._lock:
                    self._json(self.ui.record_conflicts(body))
            elif self.path == "/api/conflicts/resolve":
                with self.ui._lock:
                    self._json(self.ui.resolve_conflict(body))
            elif self.path == "/api/compromise":
                self._json(self.ui.find_compromise(body))
            elif self.path == "/api/models/test":
                self._json(self.ui.test_model(body))
            elif self.path == "/api/consent":
                with self.ui._lock:
                    self._json(self.ui.grant_consent(body))
            elif self.path == "/api/consent/withdraw":
                with self.ui._lock:
                    self._json(self.ui.withdraw_consent(body))
            elif self.path == "/api/elicit":
                with self.ui._lock:
                    self._json(self.ui.elicit(body))
            elif self.path == "/api/elicit/step":
                with self.ui._lock:
                    self._json(self.ui.elicitation_step(body))
            elif self.path == "/api/outcomes":
                with self.ui._lock:
                    self._json(self.ui.record_outcome(body))
            elif self.path == "/api/profiles":
                with self.ui._lock:
                    self._json(self.ui.save_profile(body))
            elif self.path == "/api/profiles/delete":
                with self.ui._lock:
                    self._json(self.ui.delete_profile(body))
            elif self.path == "/api/profiles/import":
                with self.ui._lock:
                    self._json(self.ui.import_profile(body))
            else:
                self._json({"error": f"no such endpoint: {self.path}"}, 404)
        except ReviewConflict as exc:
            self._json({"error": str(exc)}, 409)
        except ApiError as exc:
            self._json({"error": str(exc)}, exc.status)
        except Exception as exc:  # noqa: BLE001
            self._json({"error": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc()[-1500:]}, 500)


def serve(
    config_path: str = "configs/scenario_westland_winter.yaml",
    host: str = "127.0.0.1",
    port: int = 8765,
    anonymous: bool = False,
) -> ThreadingHTTPServer:
    """Create the server. The caller decides whether to serve forever."""
    ui = UiServer(config_path=config_path, anonymous=anonymous)
    handler = type("Handler", (_Handler,), {"ui": ui})
    return ThreadingHTTPServer((host, port), handler)
