"""A local web server for the KasFlex interface.

Built on ``http.server`` from the standard library. That is an unusual choice and a
deliberate one: the alternative is adding FastAPI, Starlette and uvicorn to a
project whose core dependencies are numpy and PyYAML, in order to serve one page to
one person on their own machine. The interface requirement is "browser-based, no
installation" (R27) -- a framework would work against that.

.. warning::

   **Localhost only, single user.** This is a research tool that runs a simulation
   on the machine it is started on. It binds to 127.0.0.1 and should not be exposed
   to a network. Settings, research data and API keys sit behind the settings
   password (:mod:`kasflex.admin_auth`); that stops participants at a workshop
   laptop, not someone with access to the computer itself. If this ever needs to be multi-user or
   hosted, it needs a real framework and a real auth story; do not simply change
   the bind address.

The API is deliberately thin. Everything it does is a call into the same functions
the CLI uses, so the interface cannot drift from what a scripted run would produce.
"""

from __future__ import annotations

import dataclasses
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from http.server import ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from kasflex import i18n
from kasflex.actions import derive_actions
from kasflex.actions import summarise as summarise_actions
from kasflex.admin_auth import (
    DEFAULT_PASSWORD,
    SITE_FIELDS,
    AdminGate,
    ConsentKeys,
    SiteSettings,
    admin_password,
)
from kasflex.api_connections import ApiConnections
from kasflex.checker.rules import SafetyChecker
from kasflex.checker.verdict import plain_message
from kasflex.config import ScenarioConfig
from kasflex.consent import ConsentLog
from kasflex.conversation import (
    PlanContext,
    PlanExplainer,
)
from kasflex.deliberation import DeliberationLog
from kasflex.documents import DocumentStore
from kasflex.energy.contracts import CONTRACT_TYPES
from kasflex.energy.contracts import describe as describe_contract
from kasflex.forecast.cost import project_cost
from kasflex.intent import IntentSchemaError, IntervalIntent, Plan
from kasflex.llm_providers import (
    PROVIDERS,
    LlmError,
    build_call_fn,
)
from kasflex.memory import GrowerMemory
from kasflex.oversight import AuditLog
from kasflex.profiles import ProfileStore
from kasflex.reasons import apply_effects
from kasflex.reliance import RelianceLog
from kasflex.resources import resolve_output
from kasflex.scenarios import ScenarioStore, scenario_day
from kasflex.ui.common import (  # noqa: F401 - re-exported for callers and tests
    ADJUSTABLE,
    SHOWCASE_DATE,
    SHOWCASE_SEED,
    SITE_FIELDS_SET,
    STATIC_DIR,
    VISITOR_HEADER,
    ApiError,
    _apply_overrides,
    _coerce,
    _get_path,
    _private_directory,
    _reject_constant,
    _scenario_store,
)
from kasflex.ui.deliberation_api import DeliberationMixin
from kasflex.ui.research_api import ResearchMixin
from kasflex.ui.reviews import ReviewStore
from kasflex.ui.workshop_api import (
    WorkshopMixin,
    clean_goals,
    clean_import_caps,
    clean_targets,
    evaluate_goals,
    participant_key,
    scenario_check,
    work_metrics,
)
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
from kasflex.workshop import ParticipantCodes, WorkshopStore


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

def _day_for(config: ScenarioConfig):
    from kasflex.data.synthetic import synthetic_day

    try:
        target = date.fromisoformat(config.date)
    except ValueError as exc:
        raise ApiError("Choose a valid date in Configuration.") from exc
    if config.data_source in {"cache", "demo"}:
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
    if config.data_source == "scenario":
        try:
            scenario = _scenario_store().get(config.scenario_id)
        except KeyError as exc:
            raise ApiError(f"Unknown workshop scenario {config.scenario_id!r}.", 404) from exc
        return scenario_day(scenario, floor_area_m2=config.hub.floor_area_m2,
                            gas_price_eur_kwh=config.gas_price_eur_kwh)
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


def _is_cold(forecast) -> bool:
    """A night at or below freezing, when cold-weather reasons come back into play."""
    night = [c.outdoor_temp_c for c in forecast if c.hour in (0, 1, 2, 3, 4, 5, 22, 23)]
    return bool(night) and min(night) <= 0.5


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
class UiServer(WorkshopMixin, DeliberationMixin, ResearchMixin):
    """Holds the scenario the interface is editing and serves the API."""

    config_path: str = "configs/scenario_westland_winter.yaml"
    anonymous: bool = False
    base: ScenarioConfig = field(init=False)
    connections: ApiConnections = field(init=False)
    reviews: ReviewStore = field(init=False)
    memory: GrowerMemory = field(init=False)
    reliance: RelianceLog = field(init=False)
    deliberation: DeliberationLog = field(init=False)
    consent: ConsentLog = field(init=False)
    profiles: ProfileStore = field(init=False)
    scenarios: ScenarioStore = field(init=False)
    workshop: WorkshopStore = field(init=False)
    documents: DocumentStore = field(init=False)
    file_base: ScenarioConfig = field(init=False, repr=False)
    gate: AdminGate = field(init=False, repr=False)
    consent_keys: ConsentKeys = field(init=False, repr=False)
    codes: ParticipantCodes = field(init=False, repr=False)
    site: SiteSettings = field(init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.file_base = ScenarioConfig.from_yaml(self.config_path)
        _private_directory(resolve_output("results/.private").parent)
        self.gate = AdminGate()
        self.consent_keys = ConsentKeys(resolve_output("results/consent-keys.json"))
        self.codes = ParticipantCodes(resolve_output("results/participant-codes.json"))
        self.site = SiteSettings(resolve_output("results/site-settings.json"))
        self.base = self._with_site_settings(self.site.get())
        self.connections = ApiConnections(resolve_output(".env"))
        self.reviews = ReviewStore(resolve_output("results/reviews.sqlite3"))
        self.memory = GrowerMemory(resolve_output(self.base.memory_path))
        self.reliance = RelianceLog(resolve_output(self.base.memory_path))
        self.deliberation = DeliberationLog(resolve_output("results/deliberation.sqlite3"))
        self.consent = ConsentLog(resolve_output("results/consent.sqlite3"))
        self.profiles = ProfileStore(resolve_output("results/profiles"))
        self.scenarios = _scenario_store()
        self.workshop = WorkshopStore(resolve_output("results/workshop.json"))
        self.documents = DocumentStore(resolve_output("results/documents"))

    # -- the settings menu (behind the admin password) ------------------------

    def _with_site_settings(self, values: dict[str, Any]) -> ScenarioConfig:
        """The scenario file with the saved site settings on top. A saved value that
        no longer validates (a file edited by hand) is dropped, not fatal."""
        try:
            return _apply_overrides(self.file_base, values)
        except ApiError:
            return self.file_base

    def site_settings(self) -> dict[str, Any]:
        saved = self.site.get()
        fields = []
        for entry in ADJUSTABLE:
            if entry["path"] in SITE_FIELDS:
                fields.append({**entry, "value": _get_path(self.base, entry["path"]),
                               "default": _get_path(self.file_base, entry["path"]),
                               "saved": entry["path"] in saved})
        language = i18n.normalise(self.base.language)
        return {"fields": fields, "models": self.model_status(),
                "connections": self.connections.status(),
                # The admin page warns while the published default still opens it.
                "default_password": admin_password() == DEFAULT_PASSWORD,
                "contract_names": {key: describe_contract(key, language)["name"]
                                   for key in CONTRACT_TYPES}}

    def save_site_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        values = payload.get("values")
        if not isinstance(values, dict):
            raise ApiError("Send the settings to save.")
        unknown = set(values) - set(SITE_FIELDS)
        if unknown:
            raise ApiError(f"Not a setting of this menu: {sorted(unknown)}")
        merged = {**self.site.get(), **values}
        merged = {k: v for k, v in merged.items() if v not in (None, "")}
        # Validate everything together before anything is written.
        self.base = _apply_overrides(self.file_base, merged)
        self.site.save({**{k: None for k in SITE_FIELDS}, **merged})
        return self.site_settings()

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

    # -- grower collaboration ------------------------------------------------

    def _compile_policy(self, supplied: dict[str, Any] | None, *,
                        overrides: dict[str, Any] | None = None,
                        cold: bool | None = None) -> dict[str, Any]:
        """Validate the daily choices and merge what the grower said before.

        Remembered disagreement reasons come back here. A standing one (``always``)
        is applied every day; a cold-weather one only on a cold day; a one-off fact
        (``once``, such as a maintenance visit) is never applied automatically, it is
        only shown again as a reminder, and applied when the grower says so
        (``reuse_memory``: the ids of earlier reasons to apply to this plan too).
        """
        raw = supplied if isinstance(supplied, dict) else {}
        priority = str(raw.get("priority", "balanced")).lower()
        if priority not in {"balanced", "cost", "grid", "crop"}:
            priority = "balanced"

        try:
            reserve = max(0.0, min(80.0, float(raw.get("battery_reserve_pct", 45))))
        except (TypeError, ValueError):
            reserve = 45.0

        avoid_hours: set[int] = set()
        if raw.get("avoid_chp_night") is True:
            avoid_hours.update((22, 23, 0, 1, 2, 3, 4, 5))
        for value in raw.get("avoid_chp_hours") or []:
            try:
                hour = int(value)
            except (TypeError, ValueError):
                continue
            if 0 <= hour <= 23:
                avoid_hours.add(hour)

        remembered_ids: list[str] = []
        negative = ("no ", "don't", "do not", "avoid", "never", "geen ", "niet ", "vermijd")
        for pref in self.memory.preferences():
            if pref.scope.get("kind") == "disagreement":
                continue
            text = pref.rule.lower()
            assets = {str(v).lower() for v in (pref.scope.get("assets") or [])}
            mentions_chp = "chp" in assets or "chp" in text or "wkk" in text
            # Strength says how firmly a rule is held, not which way it points: an
            # absolute "always run the CHP 17-20h" must not become a blackout.
            forbids = any(token in text for token in negative)
            if not (mentions_chp and forbids):
                continue
            hours = pref.scope.get("hours") or []
            parsed = []
            for value in hours:
                try:
                    hour = int(value)
                except (TypeError, ValueError):
                    continue
                if 0 <= hour <= 23:
                    parsed.append(hour)
            if not parsed and ("night" in text or "nacht" in text or "overnight" in text):
                parsed = [22, 23, 0, 1, 2, 3, 4, 5]
            if parsed:
                avoid_hours.update(parsed)
                remembered_ids.append(pref.pref_id)

        try:
            switch_penalty = max(0.0, min(500.0, float(raw.get("switch_penalty_eur", 0) or 0)))
        except (TypeError, ValueError):
            switch_penalty = 0.0
        night_temp = raw.get("night_temp_c")
        try:
            night_temp = None if night_temp in (None, "") else float(night_temp)
        except (TypeError, ValueError):
            night_temp = None

        policy: dict[str, Any] = {
            "priority": priority,
            "battery_reserve_pct": reserve,
            "avoid_chp_night": raw.get("avoid_chp_night") is True,
            "avoid_chp_hours": sorted(avoid_hours),
            "prefer_stored_heat": raw.get("prefer_stored_heat") is True,
            "switch_penalty_eur": switch_penalty,
            "night_temp_c": night_temp,
            "import_caps": clean_import_caps(raw.get("import_caps")),
            "targets": clean_targets(raw.get("targets")),
            "goals": clean_goals(raw.get("goals")),
            "brief": str(raw.get("brief", ""))[:1000],
            "remembered_preference_ids": remembered_ids,
        }
        if raw.get("use_memory") is False:
            return policy
        reuse = {str(i) for i in raw.get("reuse_memory") or [] if isinstance(i, str)}
        for pref in self.remembered(participant_key(overrides)):
            applies = pref.scope.get("applies", "once")
            if applies == "always" or (applies == "cold" and cold) or pref.pref_id in reuse:
                policy = apply_effects(policy, pref.scope.get("effects") or {})
                remembered_ids.append(pref.pref_id)
        policy["remembered_preference_ids"] = remembered_ids
        return policy

    def day_context(self, overrides: dict[str, Any]) -> dict[str, Any]:
        """Return the market/weather story a grower should see before planning."""
        config = _apply_overrides(self.base, overrides)
        if config.data_source == "demo":
            prepared = self.prepare_demo(overrides)
            config = dataclasses.replace(config, date=prepared["date"], data_source="demo")

        day = _day_for(config)
        prices = [float(c.power_price_eur_kwh) for c in day.forecast]
        temps = [float(c.outdoor_temp_c) for c in day.forecast]
        irradiance = [float(c.irradiance_w_m2) for c in day.forecast]
        cheap = sorted(range(24), key=lambda h: prices[h])[:4]
        dear = sorted(range(24), key=lambda h: prices[h], reverse=True)[:4]
        sun_hours = sum(1 for value in irradiance if value >= 50.0)

        provenance: dict[str, Any] = {}
        if config.data_source in {"cache", "demo"}:
            from kasflex.data.cache import DataCache  # noqa: PLC0415

            site = f"{config.latitude:.3f}_{config.longitude:.3f}"
            entries = DataCache().entries()
            keys = {
                "prices": f"entsoe_da_{config.date}",
                "forecast_weather": f"weather_forecast_{config.date}_{site}",
                "actual_weather": f"weather_actual_{config.date}_{site}",
            }
            for role, key in keys.items():
                entry = entries.get(key)
                if entry is not None:
                    provenance[role] = {
                        "dataset_key": entry.dataset_key,
                        "source": entry.source,
                        "licence": entry.licence,
                        "retrieved_on": entry.retrieved_on,
                        "sha256": entry.sha256,
                    }

        return {
            "date": config.date,
            "data_source": config.data_source,
            "actuals_available": getattr(day, "actuals_available", False),
            "sources": getattr(day, "sources", {}),
            "provenance": provenance,
            "price": {
                "min_eur_kwh": min(prices),
                "max_eur_kwh": max(prices),
                "avg_eur_kwh": sum(prices) / len(prices),
                "cheapest_hours": sorted(cheap),
                "dearest_hours": sorted(dear),
                "series": prices,
            },
            "weather": {
                "min_temp_c": min(temps),
                "max_temp_c": max(temps),
                "peak_irradiance_w_m2": max(irradiance),
                "sun_hours": sun_hours,
                "temperature_series": temps,
                "irradiance_series": irradiance,
            },
            # The debrief and the flaw stay server-side until the plan is approved:
            # a participant must find the trap from the story, not from the payload.
            "scenario": ({key: value for key, value in self.scenarios.get(
                config.scenario_id).to_dict(i18n.normalise(config.language)).items()
                if key not in ("debrief", "debrief_text", "flaw")}
                if config.data_source == "scenario" else None),
            "grid": {
                "contract": describe_contract(config.grid_contract_type,
                                              i18n.normalise(config.language)),
                "hourly_import_kw": [config.hub.contract.limits_at(h)[0] for h in range(24)],
                "import_limit_kw": config.hub.contract.import_limit_kw,
                "export_limit_kw": config.hub.contract.export_limit_kw,
                "congestion_windows": {
                    str(hour): {"import_kw": limits[0], "export_kw": limits[1]}
                    for hour, limits in config.hub.contract.congestion_windows.items()
                },
            },
            "site": {
                "name": config.name,
                "latitude": config.latitude,
                "longitude": config.longitude,
                "area_m2": config.hub.floor_area_m2,
            },
        }

    def measured_validation_status(self) -> dict[str, Any]:
        """Status shown beside the real-data badge in the grower workspace."""
        from kasflex.validation import validation_status

        return validation_status(resolve_output("results/validation-agc2.json"))

    # -- uncertainty --------------------------------------------------------

    def _novelty_history(self, config: ScenarioConfig) -> list[dict[str, float]]:
        """Past days to judge today against, from whichever source this run uses.

        Returns an empty list rather than inventing a comparison set; the caller
        then reports epistemic uncertainty as unknown, which is the honest answer.
        """
        try:
            if config.data_source in {"cache", "demo"}:
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

    def chat_destination(self) -> dict[str, Any]:
        """Where a chat question is sent, so the page can say so before it is asked.

        ``local`` is true when nothing leaves this computer: no usable model (the
        offline assistant answers) or a model running here.
        """
        provider, _, base_url, _, _ = self._model_settings({})
        spec = PROVIDERS.get(provider)
        if spec is None or (spec.env_var and not os.environ.get(spec.env_var)):
            return {"name": "", "local": True}
        if spec.base_url_env and os.environ.get(spec.base_url_env):
            base_url = base_url or os.environ[spec.base_url_env]
        local = spec.local and (not base_url or _is_loopback(urlsplit(base_url).hostname or ""))
        return {"name": spec.name, "local": local}

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
                    "recorded": record, "ai_generated": True}  # AI Act art. 50(2)
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
        except LlmError as exc:
            raise ApiError(str(exc), status=502) from exc

    def conversation(self, run_id: str) -> dict[str, Any]:
        return {"run_id": run_id, "turns": self.memory.turns(run_id)}

    def suggested_questions(self, overrides: dict[str, Any]) -> dict[str, Any]:
        language = self._model_settings(overrides)[3]
        return {"questions": PlanExplainer(lambda *a: "", "").opening_questions(language)}

    def prepare_demo(self, overrides: dict[str, Any], refresh: bool = False) -> dict[str, Any]:
        """Prepare a one-click historical demo from real market/weather inputs.

        Reuses the cached demo day unless ``refresh`` asks for the newest one. A
        failed refresh falls back to the cached day rather than to synthetic data.
        """
        from kasflex.data.cache import DataCache
        from kasflex.data.demo import prepare_real_demo
        from kasflex.data.sources import FetchError

        config = _apply_overrides(self.base, {**overrides, "data_source": "demo"})
        try:
            prepared = prepare_real_demo(
                cache=DataCache(),
                latitude=config.latitude,
                longitude=config.longitude,
                allow_network=True,
                refresh=refresh,
            )
        except (FetchError, ValueError, OSError) as exc:
            try:
                prepared = prepare_real_demo(
                    cache=DataCache(),
                    latitude=config.latitude,
                    longitude=config.longitude,
                    allow_network=False,
                )
            except (FetchError, ValueError, OSError):
                raise ApiError(
                    "Could not prepare the real-input demo. KasFlex did not "
                    "silently substitute synthetic data."
                ) from exc
        return {
            "date": prepared.date,
            "data_source": "demo",
            "reused_cache": prepared.reused_cache,
            "actuals_available": prepared.actual_key is not None,
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

    def run(
        self,
        overrides: dict[str, Any],
        policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run one scenario and return everything the page needs to show it."""
        from kasflex.experiment import build_greenhouse, build_planner
        from kasflex.run import run_scenario

        config = _apply_overrides(self.base, overrides)
        day = _day_for(config)
        compiled_policy = self._compile_policy(policy, overrides=overrides,
                                               cold=_is_cold(day.forecast))
        if compiled_policy["brief"]:
            config = dataclasses.replace(config, brief=compiled_policy["brief"])
        # The grower's own targets tighten the hub that both planner and checker see;
        # what they know better than the forecast (a frost warning) reshapes it.
        config = self.planning_config(config, compiled_policy)
        forecast = self.adjusted_forecast(day.forecast, compiled_policy)
        greenhouse = self.planning_greenhouse(build_greenhouse(config.greenhouse, config),
                                              compiled_policy)

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
                forecast=forecast,
                actual=day.actual,
                planner=planner,
                greenhouse=greenhouse,
                checker_config=config.checker,
                audit_log=AuditLog(resolve_output(config.audit_path), anonymous=self.anonymous),
                brief=config.brief,
                seed=config.seed,
                provenance={"data_source": config.data_source, "via": "ui",
                            "actuals_available": getattr(day, "actuals_available", False),
                            "series": getattr(day, "sources", {}),
                            "llm_provider": config.llm_provider,
                            "llm_model": config.llm_model,
                            "llm_sampling": {"temperature": None, "mode": "provider_default"},
                            "language": config.language},
                planning_metadata={"policy": compiled_policy},
            )
        except NotImplementedError as exc:
            raise ApiError(str(exc), status=501) from exc

        conditions, _ = _conditions_for(config, greenhouse, forecast)

        from kasflex.energy.dispatch import dispatch_plan  # noqa: PLC0415
        from kasflex.energy.position import (  # noqa: PLC0415
            ProcurementContract,
            settle_position,
        )

        dispatch = dispatch_plan(result.plan, config.hub, list(conditions))
        position = settle_position(
            dispatch,
            conditions,
            ProcurementContract(
                base_import_kw=config.contracted_base_kw,
                contract_price_eur_kwh=config.contracted_price_eur_kwh,
                short_spread_eur_kwh=config.imbalance_short_spread_eur_kwh,
                long_spread_eur_kwh=config.imbalance_long_spread_eur_kwh,
            ),
        ).to_dict()

        hard = result.realised_hard_violations
        plan_rows = _plan_payload(result.plan, conditions)
        for row, interval in zip(plan_rows, dispatch.intervals, strict=False):
            row.update({
                "battery_soc_kwh": round(interval.battery_soc_kwh, 1),
                "buffer_level_kwh": round(interval.buffer_level_kwh, 1),
                "grid_import_kw": round(interval.grid_import_kw, 1),
                "grid_export_kw": round(interval.grid_export_kw, 1),
                "chp_running": interval.chp_running,
                "heat_shortfall_kw": round(interval.heat_shortfall_kw, 1),
                "import_limit_kw": config.hub.contract.limits_at(row["hour"])[0],
            })
        against_normal = self._against_normal(config, result, conditions, greenhouse)
        normal_rows = (against_normal.get("normal_settings") or {}).get("plan")
        work = work_metrics(plan_rows, normal_rows)
        goals, targets = evaluate_goals(compiled_policy["goals"], compiled_policy["targets"],
                                        result.metrics, work)
        for row in targets:
            if row["key"] in ("heat_day_c", "heat_night_c"):
                # Only a model with heating setpoints can plan to the grower's temperature.
                row["met"] = hasattr(greenhouse, "setpoint_day_c")
        scenario_info = None
        if config.data_source == "scenario":
            scenario = self.scenarios.get(config.scenario_id)
            planned = float((project_cost(result.plan, config.hub, forecast, greenhouse)
                             .get("totals") or {}).get("net_cost_eur", 0) or 0)
            scenario_info = {"id": scenario.id, "kind": scenario.kind,
                             "title": scenario.text("title", config.language),
                             "check": scenario_check(scenario, plan_rows, result.metrics,
                                                     planned, i18n.normalise(config.language))}
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
            "violations": [{**v.to_dict(), "plain": plain_message(
                v.to_dict(), i18n.normalise(config.language))} for v in result.verdict.violations],
            "realised_hard": hard,
            "realised_projected": len(result.realised_violations) - hard,
            "metrics": result.metrics,
            "uncertainty": self._uncertainty(config, result.plan, conditions, greenhouse),
            "cost_forecast": project_cost(result.plan, config.hub, day.forecast, greenhouse),
            "position": position,
            "model": {
                "planner": result.planner,
                "provider": config.llm_provider,
                "model": config.llm_model,
                "sampling": {"temperature": None, "mode": "provider_default"},
            },
            **against_normal,
            "plan": plan_rows,
            "work": work,
            "goals": goals,
            "targets": targets,
            "grid": {
                "contract_type": config.grid_contract_type,
                "import_limit_kw": config.hub.contract.import_limit_kw,
                "export_limit_kw": config.hub.contract.export_limit_kw,
                "peak_import_kw": result.metrics.get("peak_import_kw", 0),
                "within_contract": all(
                    row["grid_import_kw"] <= row["import_limit_kw"] + 1e-6
                    for row in plan_rows),
            },
            "storage": {"battery_kwh": config.hub.battery.capacity_kwh,
                        "buffer_kwh": config.hub.buffer.capacity_kwh},
            "crop_target_mol_m2": config.hub.crop.dli_target_mol_m2,
            "scenario": scenario_info,
            "version": config.condition or self.workshop.get().version,
            "remembered_applied": [
                {"said": p.reason, "summary": p.rule}
                for p in self.memory.preferences()
                if p.pref_id in set(compiled_policy["remembered_preference_ids"])
                and p.scope.get("kind") == "disagreement"],
            "elapsed_s": round(time.time() - started, 2),
            "overrides": overrides,
            "data_source": config.data_source,
            "actuals_available": getattr(day, "actuals_available", False),
            "series_origin": getattr(day, "sources", {}),
            "battery_config": {
                "capacity_kwh": config.hub.battery.capacity_kwh,
                "soc_init_kwh": config.hub.battery.soc_init_kwh,
            },
            "policy": compiled_policy,
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

    def run_experiment_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run a configurable experiment matrix from the browser."""

        import csv
        import io

        from kasflex.checker.rules import CheckerConfig  # noqa: PLC0415
        from kasflex.experiment import (  # noqa: PLC0415
            Condition,
            ExperimentMatrix,
            summarise,
        )

        overrides = payload.get("overrides") or {}
        config = _apply_overrides(self.base, overrides)
        try:
            days = int(payload.get("days", 3))
        except (TypeError, ValueError) as exc:
            raise ApiError("Repetitions must be a whole number.") from exc
        if not 1 <= days <= 30:
            raise ApiError("Repetitions must be between 1 and 30.")

        allowed = {"collaborative", "rule-based", "learned", "naive", "llm"}
        planners = [str(p) for p in (payload.get("planners") or ["collaborative", "rule-based"])]
        if not planners or set(planners) - allowed:
            raise ApiError(f"Planners must be chosen from {sorted(allowed)}.")

        checker_modes = payload.get("checker_modes") or ["verified"]
        if not set(checker_modes) <= {"verified", "unverified"}:
            raise ApiError("Checker modes must be verified and/or unverified.")
        explain = payload.get("feedback", True) is not False

        conditions = []
        for planner in planners:
            for mode in checker_modes:
                enabled = mode == "verified"
                label = f"{planner}-{mode}" + ("" if explain else "-silent")
                conditions.append(
                    Condition(
                        label=label,
                        planner=planner,
                        checker=CheckerConfig(
                            enabled=enabled,
                            explain=explain,
                            max_revisions=config.checker.max_revisions,
                            fail_on_projected=config.checker.fail_on_projected,
                            excluded_checks=config.checker.excluded_checks,
                        ),
                    )
                )

        stamp = int(time.time())
        output = resolve_output(f"results/experiments/batch-{stamp}.jsonl")
        records = ExperimentMatrix(
            config=config,
            conditions=conditions,
            days=days,
            output_path=str(output),
            continue_on_error=True,
        ).run(verbose=False)
        summary = summarise(records)

        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(
            [
                "condition",
                "runs",
                "mean_cost_eur",
                "mean_violations",
                "hard_violations",
                "fallback_rate",
                "mean_peak_import_kw",
            ]
        )
        for label, row in summary.items():
            writer.writerow(
                [
                    label,
                    row.get("runs"),
                    row.get("mean_cost_eur"),
                    row.get("mean_violations"),
                    row.get("hard_violations"),
                    row.get("fallback_rate"),
                    row.get("mean_peak_import_kw"),
                ]
            )
        return {
            "summary": summary,
            "records": len(records),
            "output_path": str(output),
            "csv": stream.getvalue(),
            "settings": {
                "days": days,
                "planners": planners,
                "checker_modes": checker_modes,
                "feedback": explain,
                "date": config.date,
                "latitude": config.latitude,
                "longitude": config.longitude,
                "model": {"provider": config.llm_provider, "model": config.llm_model},
            },
        }


    def compare(self, overrides: dict[str, Any], planners: list[str]) -> dict[str, Any]:
        """Run several planners on the identical scenario (R29)."""
        rows = []
        for name in planners:
            try:
                rows.append({"planner": name, **self._compare_row(overrides, name)})
            except ApiError as exc:
                rows.append({"planner": name, "error": str(exc)})
        return {"rows": rows}

    def compare_checker(self, overrides: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
        """Run identical grower choices with verification disabled and enabled."""
        rows = []
        for enabled in (False, True):
            result = self.run({**overrides, "checker.enabled": enabled}, policy)
            rows.append({
                "checker_enabled": enabled,
                "verified": bool(enabled and result["accepted"]),
                "accepted": result["accepted"] if enabled else None,
                "hard_violations": result["realised_hard"],
                "cost_eur": result["metrics"]["net_cost_eur"],
                "growth_kg_m2": result["metrics"]["fruit_growth_kg_m2"],
                "fell_back": result["fell_back"],
            })
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


def _is_loopback(host: str) -> bool:
    import ipaddress  # noqa: PLC0415

    name = host.strip("[]").lower()
    if name == "localhost":
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def serve(
    config_path: str = "configs/scenario_westland_winter.yaml",
    host: str = "127.0.0.1",
    port: int = 8765,
    anonymous: bool = False,
    allow_network: bool = False,
) -> ThreadingHTTPServer:
    """Create the server. The caller decides whether to serve forever.

    Only this computer may connect unless ``allow_network`` is set. The Host-header
    check below stops a malicious website from reaching the local app (DNS
    rebinding); it does not stop another computer, which can send any Host header.
    So listening on a network address is refused unless asked for explicitly, and
    then only with a settings password other than the default.

    Raises:
        ValueError: for a network address without ``allow_network``, or with the
            default password.
    """

    network = not _is_loopback(host)
    if network and not allow_network:
        raise ValueError(
            f"Refusing to listen on {host}: other computers could use KasFlex. Use the "
            "default 127.0.0.1, or add --allow-network (with KASFLEX_ADMIN_PASSWORD set) "
            "if a workshop really needs tablets on the same network.")
    if network and admin_password() == DEFAULT_PASSWORD:
        raise ValueError(
            "Set KASFLEX_ADMIN_PASSWORD to a password of your own before allowing "
            "network access; the default one is published in the README.")
    # Imported here: the handler module imports this one for UiServer.
    from kasflex.ui.http import RequestHandler  # noqa: PLC0415

    ui = UiServer(config_path=config_path, anonymous=anonymous)
    allowed_hosts = {"127.0.0.1", "localhost", "[::1]", host.lower()}
    handler = type("Handler", (RequestHandler,), {
        "ui": ui,
        "allowed_hosts": frozenset(allowed_hosts),
        "network": network,
    })
    return ThreadingHTTPServer((host, port), handler)
