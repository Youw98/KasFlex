"""Deliberation endpoints: remembered preferences, conflicts, compromises and the
part-by-part negotiation of a plan.

A mixin for :class:`kasflex.ui.server.UiServer`, like :mod:`kasflex.ui.workshop_api`.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from kasflex import i18n
from kasflex.conversation import (
    detect_conflicts,
    extract_preference,
    propose_compromise,
)
from kasflex.deliberation import DIMENSIONS, RESPONSES
from kasflex.llm_providers import (
    LlmError,
)
from kasflex.memory import STRENGTHS
from kasflex.reasons import apply_effects
from kasflex.reasons import interpret as interpret_reason
from kasflex.ui.common import (
    ApiError,
)
from kasflex.ui.workshop_api import (
    participant_key,
)


class DeliberationMixin:
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

    # -- dimension-level deliberation ----------------------------------------

    @staticmethod
    def _model_id(run: dict[str, Any]) -> str:
        model = run.get("model") or {}
        provider = str(model.get("provider") or "")
        name = str(model.get("model") or "")
        planner = str(model.get("planner") or run.get("planner") or "unknown")
        if provider and name:
            return f"{provider}:{name}"
        return planner

    @staticmethod
    def _counter_response(
        dimension: str,
        current: dict[str, Any],
        alternative: dict[str, Any],
        language: str,
    ) -> str:
        nl = i18n.normalise(language) == "nl"
        before = current.get("metrics") or {}
        after = alternative.get("metrics") or {}
        if dimension == "money":
            old = float(before.get("net_cost_eur", 0) or 0)
            new = float(after.get("net_cost_eur", 0) or 0)
            delta = new - old
            if nl:
                return (
                    f"U bent het niet eens over de kosten. Ik heb opnieuw gepland met kosten "
                    f"als eerste doel. De geschatte dagkosten gaan van €{old:,.0f} naar "
                    f"€{new:,.0f} ({delta:+,.0f}). Wilt u deze kostenvariant gebruiken?"
                )
            return (
                f"You disagree about the money. I rebuilt the plan with expected cost as "
                f"the first objective. Estimated daily cost moves from €{old:,.0f} to "
                f"€{new:,.0f} ({delta:+,.0f}). Use this cost-first alternative?"
            )
        if dimension == "crop":
            old_dli = float(before.get("supplemental_dli_mol_m2", before.get("dli_mol_m2", 0)) or 0)
            new_dli = float(after.get("supplemental_dli_mol_m2", after.get("dli_mol_m2", 0)) or 0)
            old_growth = float(before.get("fruit_growth_kg_m2", 0) or 0)
            new_growth = float(after.get("fruit_growth_kg_m2", 0) or 0)
            old_cost = float(before.get("net_cost_eur", 0) or 0)
            new_cost = float(after.get("net_cost_eur", 0) or 0)
            if nl:
                return (
                    f"U bent het niet eens over gewasbescherming. Ik heb de planning opnieuw "
                    f"gemaakt met gewasmarge vóór kosten. Aanvullend licht verandert van "
                    f"{old_dli:.1f} naar {new_dli:.1f} mol/m² en de gesimuleerde "
                    f"tomatengroei van {old_growth:.3f} naar {new_growth:.3f} kg/m²; de "
                    f"kosten veranderen met €{new_cost-old_cost:+,.0f}. Wilt u deze "
                    f"gewasvariant gebruiken?"
                )
            return (
                f"You disagree about crop protection. I rebuilt the plan with crop margin "
                f"ahead of cost. Supplemental light moves from {old_dli:.1f} to "
                f"{new_dli:.1f} mol/m² and simulated tomato growth from {old_growth:.3f} "
                f"to {new_growth:.3f} kg/m²; expected cost changes by "
                f"€{new_cost-old_cost:+,.0f}. Use this crop-first alternative?"
            )
        if dimension == "grid":
            old_peak = float(before.get("peak_import_kw", 0) or 0)
            new_peak = float(after.get("peak_import_kw", 0) or 0)
            if nl:
                return (
                    f"U bent het niet eens over het net. Ik heb opnieuw gepland met de "
                    f"importpiek als eerste doel. De piek verandert van {old_peak/1000:.2f} "
                    f"naar {new_peak/1000:.2f} MW. Wilt u deze netvariant gebruiken?"
                )
            return (
                f"You disagree about grid impact. I rebuilt the plan with peak import as "
                f"the first objective. The peak moves from {old_peak/1000:.2f} to "
                f"{new_peak/1000:.2f} MW. Use this grid-relief alternative?"
            )

        if nl:
            return (
                "U zegt dat het plan niet goed bij de praktijk past. Ik heb een variant "
                "gemaakt die de WKK 's nachts vermijdt en opgeslagen warmte eerst gebruikt. "
                "Wilt u deze praktische variant gebruiken?"
            )
        return (
            "You say the plan does not fit day-to-day practice. I made an alternative that "
            "avoids CHP overnight and prefers stored heat first. Use this practical variant?"
        )

    @staticmethod
    def _counter_from_reason(reason: str, reading: dict[str, Any], current: dict[str, Any],
                             alternative: dict[str, Any], language: str) -> str:
        nl = language == "nl"
        before = current.get("metrics") or {}
        after = alternative.get("metrics") or {}
        old = float(before.get("net_cost_eur", 0) or 0)
        new = float(after.get("net_cost_eur", 0) or 0)
        checked = alternative.get("accepted") and alternative.get("checker_enabled")
        verdict = (("De controle keurt dit plan goed." if checked else
                    "Let op: de controle keurt dit plan niet goed.") if nl else
                   ("The check accepts this plan." if checked else
                    "Note: the check does not accept this plan."))
        if nl:
            return (f"U zei: “{reason}”. {reading['summary']}. Het nieuwe plan kost "
                    f"€{new:,.0f} ({new - old:+,.0f}). {verdict} Ik onthoud wat u zei voor een "
                    f"volgende keer. Wilt u dit plan gebruiken?")
        return (f"You said: “{reason}”. {reading['summary']}. The new plan costs "
                f"€{new:,.0f} ({new - old:+,.0f}). {verdict} I will remember what you said for "
                f"next time. Use this plan?")

    def deliberate(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Respond to one grower opinion without silently replacing the whole plan."""

        dimension = str(payload.get("dimension") or "").lower()
        response = str(payload.get("response") or "").lower()
        if dimension not in DIMENSIONS:
            raise ApiError(f"dimension must be one of {DIMENSIONS}")
        if response not in RESPONSES:
            raise ApiError(f"response must be one of {RESPONSES}")

        snapshot, current = self.reviews.current(payload)
        overrides = dict(current.get("overrides") or {})
        language = i18n.normalise(str(overrides.get("language") or self.base.language))
        alternative = None
        remembered_id = ""
        reason_summary = ""

        if response == "agree":
            counter = (
                "Genoteerd. Dit onderdeel blijft zoals het is."
                if language == "nl"
                else "Noted. I will keep this dimension as it is."
            )
        elif response == "unsure":
            counter = (
                "Nog niets aangepast. Bekijk de reden en de onzekere uren voordat u kiest."
                if language == "nl"
                else "I have not changed anything yet. Review the reasoning and uncertain "
                     "hours before you decide."
            )
        else:
            # A disagreement without a reason teaches nothing: the grower knows something
            # the plan does not, and the reason is how KasFlex gets to know it too.
            reason = " ".join(str(payload.get("reason") or "").split())[:300]
            if len(reason) < 3:
                raise ApiError(
                    "Zeg in een paar woorden waarom u het oneens bent, dan kan KasFlex het "
                    "meenemen." if language == "nl" else
                    "Say in a few words why you disagree, so KasFlex can take it into account.",
                    422)
            reading = interpret_reason(reason, dimension, language)
            reason_summary = reading["summary"]
            policy = dict(current.get("policy") or {})
            if reading["effects"]:
                policy = apply_effects(policy, reading["effects"])
            elif dimension == "money":
                policy["priority"] = "cost"
            elif dimension == "crop":
                policy["priority"] = "crop"
                policy["battery_reserve_pct"] = max(
                    55.0, float(policy.get("battery_reserve_pct", 45) or 45)
                )
            elif dimension == "grid":
                policy["priority"] = "grid"
            elif dimension == "goal":
                unmet = next((g for g in current.get("goals") or [] if not g.get("met")), None)
                metric = (unmet or {}).get("metric", "")
                policy["priority"] = {"cost_eur": "cost", "peak_import_kw": "grid",
                                      "light_mol_m2": "crop"}.get(metric, "balanced")
                if metric == "switches":
                    policy["switch_penalty_eur"] = 60.0
            else:
                policy["priority"] = "balanced"
                policy["avoid_chp_night"] = True
                policy["prefer_stored_heat"] = True

            alt_overrides = {
                **overrides,
                "date": current.get("date", snapshot["config"]["date"]),
                "data_source": current.get("data_source", snapshot["config"]["data_source"]),
                "planner": "collaborative",
                "language": language,
            }
            alternative = self.run(alt_overrides, policy)
            if reading["effects"]:
                counter = self._counter_from_reason(reason, reading, current, alternative,
                                                    language)
            else:
                counter = (self._counter_response(dimension, current, alternative, language)
                           + " " + reading["summary"])
            remembered = self.memory.add_preference(
                reading["summary"], reason, strength="preference", source="disagreement",
                origin_run_id=str(current.get("run_id", "")),
                origin_revision=int(current.get("revision", 0) or 0),
                scope={"kind": "disagreement", "dimension": dimension,
                       "effects": reading["effects"], "applies": reading["applies"],
                       "participant": participant_key(overrides)},
            )
            remembered_id = remembered.pref_id

        counter_model = "collaborative-deterministic-v1"
        if response == "disagree":
            try:
                explainer, _ = self._explainer(overrides)
                system = (
                    "You are rewriting a factual greenhouse-energy counterproposal. "
                    "Do not add, remove or change any number, constraint, causal claim or "
                    "recommended action. Use plain grower language, at most three sentences. "
                    "Do not sound certain about unvalidated greenhouse outcomes."
                )
                prompt = (
                    f"Language: {language}. Rewrite this text without changing its facts:\n"
                    f"{counter}"
                )
                rewritten = explainer.call_fn(explainer.model, system, prompt).strip()
                if rewritten:
                    counter = rewritten
                    provider, model, *_ = self._model_settings(overrides)
                    counter_model = f"{provider}:{model}"
            except (ApiError, LlmError):
                # The demo must remain fully functional without any external model.
                pass

        participant = str(payload.get("participant_id") or "")
        session_id = str(payload.get("session_id") or "")
        recorded = False
        if session_id:
            may_record = not participant or self._may_record(
                {**overrides, "participant_id": participant}, "research"
            )
            if may_record:
                self.deliberation.record(
                    stage="initial",
                    session_id=session_id,
                    participant_id=participant,
                    scenario_id=str(snapshot["config"].get("name", "")),
                    plan_id=f"{current['run_id']}:{current['revision']}",
                    model_id=counter_model,
                    dimension=dimension,
                    initial_response=response,
                    ai_counter_response=counter,
                    time_to_first_response_s=payload.get("time_to_first_response_s"),
                    detail_expansions=int(payload.get("detail_expansions", 0) or 0),
                    why_clicks=int(payload.get("why_clicks", 0) or 0),
                    edits_made=int(payload.get("edits_made", 0) or 0),
                    edit_parameters=payload.get("edit_parameters") or {},
                    free_text_reason=str(payload.get("reason") or ""),
                    ai_confidence_shown=str(
                        (current.get("uncertainty") or {}).get("confidence", "")
                    ),
                )
                recorded = True

        return {
            "dimension": dimension,
            "response": response,
            "counter_response": counter,
            "counter_model": counter_model,
            "alternative": alternative,
            "remembered_id": remembered_id,
            "reason_summary": reason_summary,
            "recorded": recorded,
        }

    def finalise_deliberation(self, payload: dict[str, Any]) -> dict[str, Any]:
        dimension = str(payload.get("dimension") or "").lower()
        final_response = str(payload.get("final_response") or "").lower()
        if dimension not in DIMENSIONS or final_response not in RESPONSES:
            raise ApiError("invalid dimension or final response")

        snapshot, current = self.reviews.current(payload)
        participant = str(payload.get("participant_id") or "")
        session_id = str(payload.get("session_id") or "")
        overrides = dict(current.get("overrides") or {})
        recorded = False
        if session_id:
            may_record = not participant or self._may_record(
                {**overrides, "participant_id": participant}, "research"
            )
            if may_record:
                self.deliberation.record(
                    stage="final",
                    session_id=session_id,
                    participant_id=participant,
                    scenario_id=str(snapshot["config"].get("name", "")),
                    plan_id=f"{current['run_id']}:{current['revision']}",
                    model_id=str(payload.get("counter_model") or self._model_id(current)),
                    dimension=dimension,
                    initial_response=str(payload.get("initial_response") or ""),
                    ai_counter_response=str(payload.get("ai_counter_response") or ""),
                    final_response=final_response,
                    time_to_first_response_s=payload.get("time_to_first_response_s"),
                    time_to_final_decision_s=payload.get("time_to_final_decision_s"),
                    detail_expansions=int(payload.get("detail_expansions", 0) or 0),
                    why_clicks=int(payload.get("why_clicks", 0) or 0),
                    edits_made=int(payload.get("edits_made", 0) or 0),
                    edit_parameters=payload.get("edit_parameters") or {},
                    free_text_reason=str(payload.get("reason") or ""),
                    ai_confidence_shown=str(
                        (current.get("uncertainty") or {}).get("confidence", "")
                    ),
                    plan_accepted_finally=payload.get("plan_accepted_finally"),
                    outcome_shown=payload.get("outcome_shown") is True,
                    outcome_better_or_worse_than_expected=str(
                        payload.get("outcome_better_or_worse_than_expected") or ""
                    ),
                )
                recorded = True
        return {"recorded": recorded, "dimension": dimension, "final_response": final_response}

    def list_deliberations(self, session_id: str = "") -> dict[str, Any]:
        return {"records": self.deliberation.export(session_id)}
