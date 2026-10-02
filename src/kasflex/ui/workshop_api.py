"""Workshop endpoints: study versions, scenarios, AI-first advice, chat, explanations.

A mixin for :class:`kasflex.ui.server.UiServer`, kept apart so the core server
stays readable. Everything here builds on the same planner, dispatch model and
checker as the rest of the interface; nothing in this file plans on its own.
"""

from __future__ import annotations

import dataclasses
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from kasflex import i18n
from kasflex.assistant import answer as offline_answer
from kasflex.documents import search as search_documents
from kasflex.documents import text_from_upload
from kasflex.energy.contracts import CONTRACT_TYPES, describe
from kasflex.factors import explain_factors
from kasflex.recommend import recommend
from kasflex.scenarios import BUILTIN, FLAW_TYPES
from kasflex.workshop import VERSIONS

NIGHT = (0, 1, 2, 3, 4, 5, 6, 7, 20, 21, 22, 23)
GOAL_METRICS = {
    "cost_eur": ("net_cost_eur", "Daily cost (€)", "Dagkosten (€)"),
    "peak_import_kw": ("peak_import_kw", "Peak grid import (kW)", "Hoogste netafname (kW)"),
    "light_mol_m2": ("supplemental_dli_mol_m2", "Extra light (mol/m²)", "Extra licht (mol/m²)"),
    "chp_hours": ("chp_hours", "CHP running hours", "Draaiuren WKK"),
    "switches": ("switches", "Equipment switches", "Schakelingen"),
}
GOAL_OPS = ("<=", ">=")


#: The anonymous visitor the current request comes from, set per request thread by
#: the HTTP handler when the workshop keeps visitors apart (see ``use_visitor``).
_request = threading.local()
_VISITOR = re.compile(r"[A-Za-z0-9-]{8,40}")


@contextmanager
def use_visitor(visitor: str | None) -> Iterator[None]:
    """Scope remembered reasons to one anonymous browser tab for this request.

    Only a well-formed id counts; anything else falls back to the shared grower.
    """
    _request.visitor = visitor if visitor and _VISITOR.fullmatch(visitor) else ""
    try:
        yield
    finally:
        _request.visitor = ""


def participant_key(overrides: dict[str, Any] | None) -> str:
    """Whose memory this is.

    Without a participant id: the anonymous visitor when the workshop keeps visitors
    apart, otherwise one shared local grower (one person on their own computer).
    """
    participant = str((overrides or {}).get("participant_id") or "")
    if participant:
        return participant[:64]
    visitor = getattr(_request, "visitor", "")
    return f"visitor:{visitor}" if visitor else "local"


def clean_targets(raw: Any) -> dict[str, float | None]:
    raw = raw if isinstance(raw, dict) else {}
    limits = {"max_import_kw": (0.0, 50_000.0), "light_mol_m2": (0.0, 30.0),
              "budget_eur": (0.0, 1_000_000.0),
              # Heating setpoints, the targets a grower's climate computer works to.
              "heat_day_c": (10.0, 30.0), "heat_night_c": (8.0, 28.0)}
    out: dict[str, float | None] = {}
    for key, (low, high) in limits.items():
        value = raw.get(key)
        if value in (None, ""):
            out[key] = None
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            out[key] = None
            continue
        out[key] = min(high, max(low, number))
    return out


def clean_import_caps(raw: Any) -> dict[int, float]:
    """Hourly import limits the grower knows about (a curtailment notice)."""
    caps: dict[int, float] = {}
    for hour, value in (raw.items() if isinstance(raw, dict) else []):
        try:
            h, kw = int(hour), float(value)
        except (TypeError, ValueError):
            continue
        if 0 <= h <= 23 and 0 <= kw <= 50_000:
            caps[h] = kw
    return caps


def clean_goals(raw: Any) -> list[dict[str, Any]]:
    goals = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        metric, op = str(item.get("metric", "")), str(item.get("op", "<="))
        name = " ".join(str(item.get("name", "")).split())[:80]
        try:
            value = float(item.get("value"))
        except (TypeError, ValueError):
            continue
        if metric in GOAL_METRICS and op in GOAL_OPS and name:
            goals.append({"name": name, "metric": metric, "op": op, "value": value})
    return goals[:5]


def work_metrics(rows: list[dict[str, Any]], normal_rows: list[dict[str, Any]] | None) -> dict:
    """What a plan asks of the people running the greenhouse, in countable terms."""
    switches = 0
    starts = 0
    previous = None
    for row in rows:
        current = (row["heat_source"], bool(row.get("chp_running")), row["battery"])
        if previous is not None and current != previous:
            switches += 1
        if previous is not None and current[1] and not previous[1]:
            starts += 1
        previous = current
    fields = ("heat_source", "lighting_level", "battery", "chp_mode")
    changed = 0
    if normal_rows:
        changed = sum(1 for a, b in zip(rows, normal_rows, strict=False)
                      if any(a.get(f) != b.get(f) for f in fields))
    return {
        "switches": switches,
        "chp_starts": starts,
        "chp_hours": sum(1 for row in rows if row.get("chp_running")),
        "chp_night_hours": sum(1 for row in rows if row.get("chp_running")
                               and row["hour"] in NIGHT),
        "hours_changed_vs_normal": changed,
    }


def evaluate_goals(goals, targets, metrics, work) -> tuple[list[dict], list[dict]]:
    values = {**metrics, **work}
    goal_rows = []
    for goal in goals:
        actual = float(values.get(GOAL_METRICS[goal["metric"]][0], 0) or 0)
        met = actual <= goal["value"] if goal["op"] == "<=" else actual >= goal["value"]
        goal_rows.append({**goal, "actual": round(actual, 2), "met": met})
    target_rows = []
    checks = {"max_import_kw": ("peak_import_kw", "<="), "light_mol_m2":
              ("supplemental_dli_mol_m2", ">="), "budget_eur": ("net_cost_eur", "<=")}
    for key, value in targets.items():
        if value is None:
            continue
        if key in ("heat_day_c", "heat_night_c"):
            # A setpoint is an input the plan is built on, not an outcome to check.
            target_rows.append({"key": key, "value": value, "actual": value, "op": "=",
                                "met": True})
            continue
        metric, op = checks[key]
        actual = float(values.get(metric, 0) or 0)
        met = actual <= value + 1e-6 if op == "<=" else actual >= value - 0.05
        target_rows.append({"key": key, "value": value, "actual": round(actual, 2),
                            "op": op, "met": met})
    return goal_rows, target_rows


def similar_situation(pref, config, conditions) -> str:
    """Why an earlier one-off reason may fit tomorrow too, or "" if nothing suggests it.

    KasFlex never reapplies a one-off reason by itself ("only two staff tomorrow"
    was about that day); it offers it again when tomorrow looks alike, and the
    grower decides. The signals are deliberately plain so the grower can check
    them: the same weekday, a cold night again, or a lowered grid limit again.
    """
    import datetime as _dt  # noqa: PLC0415

    effects = pref.scope.get("effects") or {}
    try:
        said = _dt.datetime.fromisoformat(str(pref.created_at)).date()
        planned = _dt.date.fromisoformat(str(config.date))
        # A reason given today was about tomorrow: compare with the planned weekday.
        if (said + _dt.timedelta(days=1)).weekday() == planned.weekday():
            return "weekday"
    except ValueError:
        pass
    if "night_temp_c" in effects and min(
            (c.outdoor_temp_c for c in conditions if c.hour in NIGHT), default=99) <= 1.0:
        return "cold"
    if "import_caps" in effects and config.hub.contract.congestion_windows:
        return "grid"
    return ""


def scenario_check(scenario, rows: list[dict[str, Any]], metrics: dict[str, Any],
                   planned_cost_eur: float, language: str = "en") -> dict[str, Any]:
    """How the day turned out against what the story told the participant.

    Shown after approval. For a good scenario there is nothing to catch; for a
    flawed one this checks the plan against the fact only the participant knew.
    """
    nl = language == "nl"
    flaw = scenario.flaw or {}
    kind = flaw.get("type", "")
    problems: list[int] = []
    if kind == "hidden_maintenance":
        blocked = {int(h) for h in flaw.get("hours", [])}
        problems = [r["hour"] for r in rows if r.get("chp_running") and r["hour"] in blocked]
        message = ((f"De WKK draaide tijdens het onderhoud op {len(problems)} uur."
                    if problems else "De WKK bleef uit tijdens het onderhoud.") if nl else
                   (f"The CHP ran during the maintenance visit in {len(problems)} hour(s)."
                    if problems else "The CHP stayed off during the maintenance visit."))
    elif kind == "hidden_curtailment":
        hours = {int(h) for h in flaw.get("hours", [])}
        cap = float(flaw.get("import_kw", 0))
        problems = [r["hour"] for r in rows
                    if r["hour"] in hours and r.get("grid_import_kw", 0) > cap + 1e-6]
        message = ((f"Het plan haalde op {len(problems)} uur meer dan {cap / 1000:.1f} MW van "
                    "het net, tegen de melding van de netbeheerder in." if problems else
                    "Het plan bleef binnen de melding van de netbeheerder.") if nl else
                   (f"The plan took more than {cap / 1000:.1f} MW from the grid in "
                    f"{len(problems)} hour(s), against the grid operator's notice."
                    if problems else "The plan kept to the grid operator's notice."))
    elif kind == "forecast_miss":
        realised = float(metrics.get("net_cost_eur", 0) or 0)
        shortfall = float(metrics.get("heat_shortfall_kwh", 0) or 0)
        extra = realised - planned_cost_eur
        problems = [r["hour"] for r in rows if r.get("heat_shortfall_kw", 0) > 0]
        message = ((f"De echte nacht was kouder dan verwacht: €{extra:+,.0f} ten opzichte van het "
                    f"plan, {shortfall:,.0f} kWh warmtetekort.") if nl else
                   (f"The real night was colder than forecast: €{extra:+,.0f} against the plan, "
                    f"{shortfall:,.0f} kWh of heat short."))
    else:
        message = ("Geen valkuil in deze dag: het plan was in orde." if nl else
                   "No trap in this day: the plan was sound.")
    return {"ok": not problems, "problem_hours": problems, "message": message,
            "debrief": scenario.text("debrief", language)}


class WorkshopMixin:
    """Endpoints the grower and admin pages use for workshops and collaboration."""

    # -- version and scenario --------------------------------------------------

    def workshop_status(self, language: str = "en") -> dict[str, Any]:
        state = self.workshop.get()
        scenarios = [s.to_dict(language) for s in self.scenarios.all()]
        return {
            "version": state.version,
            "versions": list(VERSIONS),
            "scenario_id": state.scenario_id,
            "lock_scenario": state.lock_scenario,
            "separate_visitors": state.separate_visitors,
            "issued_ids_only": state.issued_ids_only,
            "chat_destination": self.chat_destination(),
            "scenarios": scenarios,
            "contract_types": [describe(k, language) for k in CONTRACT_TYPES],
            "builtin_ids": [s.id for s in BUILTIN],
            "flaw_types": [t for t in FLAW_TYPES if t],
        }

    def set_workshop(self, payload: dict[str, Any]) -> dict[str, Any]:
        from kasflex.ui.server import ApiError  # noqa: PLC0415

        scenario_id = payload.get("scenario_id")
        if scenario_id:
            try:
                self.scenarios.get(str(scenario_id))
            except KeyError as exc:
                raise ApiError("That scenario does not exist.", 404) from exc
        if payload.get("issued_ids_only") is True and not self.codes.all():
            raise ApiError("Make participant codes first, or nobody could take part.", 409)
        try:
            self.workshop.set(
                version=payload.get("version"),
                scenario_id=None if scenario_id is None else str(scenario_id),
                lock_scenario=payload.get("lock_scenario"),
                separate_visitors=payload.get("separate_visitors"),
                issued_ids_only=payload.get("issued_ids_only"),
            )
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
        return self.workshop_status(str(payload.get("language") or "en"))

    def save_scenario(self, payload: dict[str, Any]) -> dict[str, Any]:
        from kasflex.ui.server import ApiError  # noqa: PLC0415

        data = payload.get("scenario")
        if not isinstance(data, dict):
            raise ApiError("Send the scenario to save.")
        if data.get("grid_contract_type", "cbc") not in CONTRACT_TYPES:
            raise ApiError("Unknown grid contract type.")
        try:
            saved = self.scenarios.save(data)
        except (ValueError, TypeError) as exc:
            raise ApiError(f"Scenario not saved: {exc}") from exc
        return {"saved": saved.to_dict()}

    def delete_scenario(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"deleted": self.scenarios.delete(str(payload.get("scenario_id", "")))}

    # -- memory ------------------------------------------------------------------

    def remembered(self, participant: str) -> list[Any]:
        return [p for p in self.memory.preferences()
                if p.scope.get("kind") == "disagreement"
                and p.scope.get("participant", "local") == participant]

    def list_remembered(self, overrides: dict[str, Any], *, everyone: bool = False
                        ) -> dict[str, Any]:
        prefs = ([p for p in self.memory.preferences() if p.scope.get("kind") == "disagreement"]
                 if everyone else self.remembered(participant_key(overrides)))
        return {"remembered": [
            {"pref_id": p.pref_id, "said": p.reason, "summary": p.rule,
             "dimension": p.scope.get("dimension"), "applies": p.scope.get("applies"),
             "participant": p.scope.get("participant", "local"), "created_at": p.created_at}
            for p in prefs]}

    def forget_remembered(self, payload: dict[str, Any]) -> dict[str, Any]:
        everyone = payload.get("everyone") is True
        participant = participant_key(payload.get("overrides"))
        count = 0
        for pref in self.memory.preferences():
            if pref.scope.get("kind") != "disagreement":
                continue
            if everyone or pref.scope.get("participant", "local") == participant:
                self.memory.retire_preference(pref.pref_id, "forgotten from the interface")
                count += 1
        return {"forgotten": count}

    # -- planning inputs -------------------------------------------------------

    def _forecast_conditions(self, overrides: dict[str, Any], policy: dict[str, Any]):
        """Config and hourly conditions (with heat demand) as the planner sees them."""
        from kasflex.experiment import build_greenhouse  # noqa: PLC0415
        from kasflex.ui.server import _apply_overrides, _conditions_for, _day_for  # noqa: PLC0415

        config = self.planning_config(_apply_overrides(self.base, overrides), policy)
        day = _day_for(config)
        forecast = self.adjusted_forecast(day.forecast, policy)
        greenhouse = self.planning_greenhouse(build_greenhouse(config.greenhouse, config), policy)
        conditions, _ = _conditions_for(config, greenhouse, forecast)
        return config, conditions

    @staticmethod
    def planning_greenhouse(greenhouse, policy: dict[str, Any]):
        """The greenhouse model with the grower's heating setpoints, where it has them.

        The surrogate turns day and night setpoints into the heat demand the planner
        meets, so a warmer target costs more heat. GreenLight runs its own climate
        control and is returned unchanged; the run reports that the target did not
        apply.
        """
        targets = policy.get("targets") or {}
        changes = {}
        if targets.get("heat_day_c") is not None and hasattr(greenhouse, "setpoint_day_c"):
            changes["setpoint_day_c"] = float(targets["heat_day_c"])
        if targets.get("heat_night_c") is not None and hasattr(greenhouse, "setpoint_night_c"):
            changes["setpoint_night_c"] = float(targets["heat_night_c"])
        return dataclasses.replace(greenhouse, **changes) if changes else greenhouse

    @staticmethod
    def planning_config(config, policy: dict[str, Any]):
        """Apply the grower's own targets to the hub the planner and checker use."""
        targets = policy.get("targets") or {}
        hub = config.hub
        cap = targets.get("max_import_kw")
        if cap:
            contract = hub.contract
            hub = dataclasses.replace(hub, contract=dataclasses.replace(
                contract,
                import_limit_kw=min(contract.import_limit_kw, cap),
                congestion_windows={h: (min(i, cap), e) for h, (i, e)
                                    in contract.congestion_windows.items()},
            ))
        caps = policy.get("import_caps") or {}
        if caps:
            contract = hub.contract
            windows = dict(contract.congestion_windows)
            for hour, kw in caps.items():
                current = windows.get(int(hour), (contract.import_limit_kw,
                                                  contract.export_limit_kw))
                windows[int(hour)] = (min(current[0], float(kw)), current[1])
            hub = dataclasses.replace(hub, contract=dataclasses.replace(
                contract, congestion_windows=windows))
        light = targets.get("light_mol_m2")
        if light:
            hub = dataclasses.replace(hub, crop=dataclasses.replace(
                hub.crop, dli_target_mol_m2=light))
        return dataclasses.replace(config, hub=hub)

    @staticmethod
    def adjusted_forecast(forecast, policy: dict[str, Any]):
        """The forecast with what the grower knows better applied (a colder night)."""
        night = policy.get("night_temp_c")
        if night is None:
            return tuple(forecast)
        return tuple(
            dataclasses.replace(c, outdoor_temp_c=min(c.outdoor_temp_c, float(night)))
            if c.hour in NIGHT else c
            for c in forecast)

    # -- AI first --------------------------------------------------------------

    def recommendation(self, payload: dict[str, Any]) -> dict[str, Any]:
        """What KasFlex would choose for tomorrow, before the grower chooses."""
        overrides = dict(payload.get("overrides") or {})
        base = self._compile_policy(payload.get("policy") or {}, overrides=overrides)
        config, conditions = self._forecast_conditions(overrides, base)
        language = i18n.normalise(config.language)
        advice = recommend(config.hub, conditions, date=config.date, base_policy=base,
                           peak_value_eur_per_kw=config.grid_peak_value_eur_per_kw,
                           language=language)
        participant = participant_key(overrides)
        applied_ids = set(base.get("remembered_preference_ids") or [])
        advice["remembered"] = sorted(
            ({"pref_id": p.pref_id, "said": p.reason, "summary": p.rule,
              "applies": p.scope.get("applies", "once"), "applied": p.pref_id in applied_ids,
              "similar": similar_situation(p, config, conditions)}
             for p in self.remembered(participant)),
            key=lambda item: (not item["similar"], item["applied"]))
        merged = {**base, **advice["policy"]}
        merged["avoid_chp_hours"] = base.get("avoid_chp_hours", [])
        advice["policy"] = {k: v for k, v in merged.items()
                            if k not in ("remembered_preference_ids", "brief")}
        return advice

    # -- explanation graph -----------------------------------------------------

    def factor_explanation(self, payload: dict[str, Any]) -> dict[str, Any]:
        snapshot, current = self.reviews.current(payload)
        overrides = dict(current.get("overrides") or {})
        policy = dict(current.get("policy") or {})
        config, conditions = self._forecast_conditions(overrides, policy)
        return explain_factors(config.hub, conditions, date=config.date, policy=policy,
                               peak_value_eur_per_kw=config.grid_peak_value_eur_per_kw,
                               language=i18n.normalise(config.language))

    # -- chat --------------------------------------------------------------------

    def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Answer a question about the current plan: a configured model, else offline."""
        from kasflex.ui.server import (
            ApiError,  # noqa: PLC0415
            LlmError,  # noqa: PLC0415
        )

        snapshot, current = self.reviews.current(payload)
        overrides = dict(current.get("overrides") or {})
        question = " ".join(str(payload.get("question") or "").split())[:500]
        if not question:
            raise ApiError("Type a question first.")
        language = i18n.normalise(str(overrides.get("language") or self.base.language))
        participant = participant_key(overrides)
        record = self._may_record(overrides, "quotes")
        run_payload = {**current, "grid": {"import_limit_kw":
                                           snapshot["config"]["hub"]["contract"]["import_limit_kw"]}}
        passages = search_documents(question, self.documents.all(language))
        try:
            explainer, _ = self._explainer(payload.get("overrides") or overrides)
            context = self._plan_context({**current, "overrides": overrides}, language)
            context = dataclasses.replace(context, background="\n\n".join(
                f"[{hit['title']}] {hit['passage']}" for hit in passages))
            reply = explainer.ask(context, question, record=record)
            model = reply.get("model", "")
            text = reply["answer"]
        except (ApiError, LlmError):
            said = [p.reason for p in self.remembered(participant)]
            text = offline_answer(question, run_payload, language=language, remembered=said,
                                  passages=passages)
            model = "kasflex-offline-assistant"
            if record:
                self.memory.add_turn(current["run_id"], "grower", question)
                self.memory.add_turn(current["run_id"], "assistant", text, model=model)
        # Machine-readable marking of generated text (EU AI Act art. 50(2)). The
        # offline assistant fills templates with the plan's numbers; marked too,
        # since the page presents both as the assistant's answer.
        return {"question": question, "answer": text, "model": model, "recorded": record,
                "ai_generated": True,
                "sources": [{"title": hit["title"], "passage": hit["passage"]}
                            for hit in passages]}

    # -- documents ---------------------------------------------------------------

    def list_documents(self, language: str = "en") -> dict[str, Any]:
        return {"documents": [
            {"id": d.id, "title": d.title, "text": d.text, "added_at": d.added_at,
             "builtin": d.builtin, "characters": len(d.text)}
            for d in self.documents.all(i18n.normalise(language))]}

    def save_document(self, payload: dict[str, Any]) -> dict[str, Any]:
        from kasflex.ui.server import ApiError  # noqa: PLC0415

        try:
            text = payload.get("text", "")
            if payload.get("file_base64") or payload.get("docx_xml"):
                text = text_from_upload(str(payload.get("filename", "")),
                                        str(payload.get("file_base64") or ""),
                                        str(payload.get("docx_xml") or ""))
            document = self.documents.save(payload.get("title", ""), text,
                                           str(payload.get("id") or ""))
        except ValueError as exc:
            raise ApiError(str(exc)) from exc
        return {"saved": {"id": document.id, "title": document.title}}

    def delete_document(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"deleted": self.documents.delete(str(payload.get("id", "")))}

    # -- a week ahead ----------------------------------------------------------

    def week_outlook(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Plan seven simulated days one by one, and sum savings and crop growth.

        KasFlex plans one day at a time on purpose: the day-ahead market clears one
        day at a time and weather forecasts lose most of their skill after two or
        three days. A week outlook therefore repeats the day plan on a simulated
        week like the chosen day; it estimates, it does not plan the week.
        """
        from kasflex.controllers.base import PlanningContext  # noqa: PLC0415
        from kasflex.controllers.collaborative import CollaborativePlanner  # noqa: PLC0415
        from kasflex.controllers.rule_based import RuleBasedPlanner  # noqa: PLC0415
        from kasflex.data.synthetic import synthetic_day  # noqa: PLC0415
        from kasflex.experiment import build_greenhouse  # noqa: PLC0415
        from kasflex.ui.server import (  # noqa: PLC0415
            _apply_overrides,
            _conditions_for,
            project_cost,  # noqa: PLC0415
        )

        overrides = dict(payload.get("overrides") or {})
        policy = self._compile_policy(payload.get("policy") or {}, overrides=overrides)
        config = self.planning_config(_apply_overrides(self.base, overrides), policy)
        greenhouse = self.planning_greenhouse(build_greenhouse(config.greenhouse, config), policy)
        days = []
        for offset in range(7):
            day = synthetic_day(f"{config.date}+{offset}", seed=config.seed + 100 + offset,
                                floor_area_m2=config.hub.floor_area_m2, winter=config.winter)
            base = tuple(dataclasses.replace(c, gas_price_eur_kwh=config.gas_price_eur_kwh)
                         for c in day.forecast)
            conditions, _ = _conditions_for(config, greenhouse, base)
            context = PlanningContext(date=config.date, forecast=conditions, hub=config.hub,
                                      metadata={"policy": policy})
            planned = CollaborativePlanner(
                peak_value_eur_per_kw=config.grid_peak_value_eur_per_kw).plan(context)
            normal = RuleBasedPlanner().plan(context)
            cost = project_cost(planned, config.hub, conditions, greenhouse)["totals"]
            normal_cost = project_cost(normal, config.hub, conditions, greenhouse)["totals"]
            growth = greenhouse.simulate_day(planned, conditions,
                                             config.hub.floor_area_m2).fruit_growth_kg_m2
            days.append({"day": offset + 1,
                         "cost_eur": round(cost["net_cost_eur"], 2),
                         "normal_cost_eur": round(normal_cost["net_cost_eur"], 2),
                         "growth_kg_m2": round(growth, 4)})
        return {
            "days": days,
            "cost_eur": round(sum(d["cost_eur"] for d in days), 2),
            "saving_eur": round(sum(d["normal_cost_eur"] - d["cost_eur"] for d in days), 2),
            "growth_kg_m2": round(sum(d["growth_kg_m2"] for d in days), 4),
            "basis": "seven simulated days like the chosen one, each planned a day ahead",
        }


__all__ = ["GOAL_METRICS", "WorkshopMixin", "clean_goals", "clean_import_caps", "clean_targets",
           "evaluate_goals", "participant_key", "use_visitor", "scenario_check", "work_metrics"]
