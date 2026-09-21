"""Explaining a plan, hearing the objection, and finding the middle.

The study asks whether a grower's judgement conflicts with the planner's, and
whether a compromise exists. That question cannot be answered by an approve/reject
button, because a button records *that* someone disagreed and never *why*. This
module is the part that asks why, and turns the answer into something the next
plan can use.

Four jobs, each a separate model call with its own contract:

:class:`PlanExplainer` answers a grower's question about a plan in their own
language, grounded in the plan and the prices rather than in generalities.

:func:`extract_preference` reads an objection and proposes a standing rule. The
grower confirms it before it binds -- an inferred preference that silently starts
steering plans would be worse than no memory at all.

:func:`propose_compromise` looks for a position between the grower's choice and
the planner's, priced and safety-checked. Where none exists it says so, which is
itself a finding.

Everything the model returns is **data, not instruction** (R12). Free text is
shown as text; structured replies are parsed, validated, and discarded if they do
not fit. A model that returns nonsense produces a visible failure, never a silent
change to a plan.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from kasflex import i18n
from kasflex.memory import STRENGTHS, GrowerMemory

MAX_QUESTION_CHARS = 2000
"""Long enough for any real question; short enough that a paste cannot run up a bill."""

EXPLAINER_SYSTEM = """\
You explain one day's energy plan to the person who runs the greenhouse.

They are an experienced grower and a beginner with software. They know their crop
and their equipment far better than you do. They do not know, and do not need to
know, what a state of charge or a day-ahead market is.

Ground every answer in the plan and the numbers you were given. If the plan runs
the CHP at 03:00, say what made that worth doing at 03:00 -- the actual price, the
actual heat demand. Never invent a number. If the plan does not explain itself and
you cannot tell why, say so plainly; a guess dressed as a reason is worse than an
admission.

Two or three sentences is usually right. Do not list, do not lecture, and do not
apologise. If the grower disagrees with you, take it seriously: they may be right,
and they are the one who carries the consequence.

You are explaining a simulation. Nothing you say controls equipment.
"""

PREFERENCE_SYSTEM = """\
You turn a grower's objection into one standing instruction for a planner.

Return ONLY this JSON:

{
  "rule": "one imperative sentence the planner can act on",
  "strength": "preference" | "strong" | "absolute",
  "scope": {"assets": ["chp"], "hours": [22, 23, 0, 1]},
  "confidence": 0.0 to 1.0,
  "restatement": "one sentence, in the grower's language, asking them to confirm"
}

The rule must be narrower than the objection, never wider. "I don't trust the CHP
at night" becomes an instruction about the CHP at night, not about the CHP.

Choose strength honestly. "absolute" is for safety and for things the grower says
never to do; most objections are a "preference". Over-binding a casual remark makes
the system rigid, and the grower will turn it off.

Include only the scope keys you are sure of. Omit "hours" entirely if the objection
was not about time. Use 0-23 for hours.

Set confidence below 0.5 if the objection is vague, or is about this one day rather
than a standing rule.
"""

COMPROMISE_SYSTEM = """\
You look for a middle position between what the planner chose and what the grower
wants, for one hour of one day.

Return ONLY this JSON:

{
  "found": true | false,
  "value": "the compromise setting, using the same vocabulary as the plan",
  "hours": [3, 4, 5],
  "explanation": "one or two sentences, in the grower's language",
  "gives_up": "what the grower loses compared with their own choice",
  "keeps": "what the grower keeps compared with the planner's choice"
}

A compromise is a real third position, not a restatement of either side. Narrowing
a window, lowering an intensity, or splitting a run are compromises. Agreeing with
one side is not.

Set "found": false when the choice is genuinely binary. Saying so is useful and
honest; inventing a middle that satisfies nobody is not.
"""


def _extract_json(text: str) -> dict[str, Any]:
    """Pull a JSON object out of a reply that may be wrapped in prose or fences."""
    for chunk in text.split("```"):
        candidate = chunk.removeprefix("json").strip()
        if candidate.startswith("{"):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError("the model did not return usable JSON")


def _clean_hours(raw: Any) -> list[int]:
    """Keep whole hours in range and drop everything else."""
    if not isinstance(raw, list):
        return []
    hours = []
    for value in raw:
        try:
            hour = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= hour <= 23 and hour not in hours:
            hours.append(hour)
    return sorted(hours)


def _clean_scope(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    scope: dict[str, Any] = {}
    hours = _clean_hours(raw.get("hours"))
    if hours:
        scope["hours"] = hours
    assets = raw.get("assets")
    if isinstance(assets, list):
        named = [str(a).strip().lower() for a in assets if str(a).strip()]
        if named:
            scope["assets"] = named[:8]
    return scope


#: Prompt vocabulary for the plan table, per language.
#:
#: Separate from the interface catalogue in :mod:`kasflex.i18n` on purpose: this
#: is compact machine-facing wording for a table cell, not a label a person reads,
#: and the two drift for good reasons.
_DIGEST_WORDS: dict[str, dict[str, str]] = {
    "en": {
        "header": "hour | price EUR/kWh | heat from | lights | battery | CHP | why",
        "boiler": "boiler", "chp": "chp", "buffer": "buffer", "none": "none",
        "idle": "idle", "charge": "charge", "discharge": "discharge",
        "off": "off", "heat_led": "heat-led", "max_export": "max export",
    },
    "nl": {
        "header": "uur | prijs EUR/kWh | warmte van | lampen | batterij | WKK | waarom",
        "boiler": "ketel", "chp": "wkk", "buffer": "buffer", "none": "geen",
        "idle": "rust", "charge": "laden", "discharge": "ontladen",
        "off": "uit", "heat_led": "warmtegestuurd", "max_export": "max. teruglevering",
    },
}


def plan_digest(plan: list[dict[str, Any]], language: str = "en",
                max_hours: int = 24) -> str:
    """One compact table of the plan, for a prompt.

    The full plan payload carries far more than an explanation needs and would
    crowd out the question itself. This keeps the columns a grower actually asks
    about.

    Written in the language the answer is wanted in. Handing a Dutch-tuned model an
    English table while instructing it to reply in Dutch is a mixed-language prompt,
    and the models that suffer most from it are precisely the ones chosen for their
    Dutch. The decimal separator follows suit, since a Dutch model reading "0.090"
    is reading a number written the way it was not trained to see it.
    """
    code = i18n.normalise(language)
    words = _DIGEST_WORDS[code]
    dutch = code == "nl"

    def term(value: Any) -> str:
        return words.get(str(value), str(value) if value is not None else "?")

    def number(value: float, places: int) -> str:
        text = f"{value:.{places}f}"
        return text.replace(".", ",") if dutch else text

    lines = [words["header"]]
    for row in plan[:max_hours]:
        battery = term(row.get("battery", "?"))
        if str(row.get("battery")) not in ("idle", "None", "?"):
            battery += f" {float(row.get('battery_power_kw', 0)):.0f}kW"
        lines.append(
            f"{int(row.get('hour', 0)):02d} | "
            f"{number(float(row.get('power_price_eur_kwh', 0)), 3)} | "
            f"{term(row.get('heat_source', '?'))} | "
            f"{number(float(row.get('lighting_level', 0)) * 100, 0)}% | "
            f"{battery} | "
            f"{term(row.get('chp_mode', '?'))} | "
            f"{row.get('reasoning', '')}"
        )
    return "\n".join(lines)


@dataclass
class PlanContext:
    """Everything an explanation is allowed to draw on."""

    run_id: str
    date: str
    plan: list[dict[str, Any]]
    metrics: dict[str, Any]
    language: str = "en"
    cost_forecast: dict[str, Any] | None = None
    weather_note: str = ""
    verdict_note: str = ""
    data_source: str = "synthetic"

    def brief(self) -> str:
        """The plan, written in the language the answer is wanted in."""
        language = i18n.normalise(self.language)
        dutch = language == "nl"
        cost = self.metrics.get("net_cost_eur")
        real = self.data_source in {"cache", "demo"}

        lines = [
            f"{'Geplande dag' if dutch else 'Date planned'}: {self.date}",
            ("Invoer: " + ("echte prijzen en weersverwachting" if real
                           else "demonstratiegegevens, verzonnen prijzen"))
            if dutch else
            ("Inputs: " + ("real prices and forecast weather" if real
                           else "demonstration data, invented prices")),
        ]
        if cost is not None:
            label = "Netto kosten hele dag" if dutch else "Whole-day net cost"
            lines.append(f"{label}: {i18n.format_money(float(cost), language)}")
        if self.metrics.get("temperature_band_hours") is not None:
            hours = self.metrics["temperature_band_hours"]
            lines.append(
                f"Uren binnen de comfortabele band van het gewas: {hours} van 24"
                if dutch else
                f"Hours inside the crop's comfortable band: {hours} of 24")
        if self.cost_forecast and self.cost_forecast.get("totals"):
            totals = self.cost_forecast["totals"]
            parts = [f"{k.replace('_', ' ')}: {i18n.format_money(float(v), language)}"
                     for k, v in totals.items() if isinstance(v, (int, float))]
            if parts:
                lines.append(("Kostenverdeling -- " if dutch else "Cost split -- ")
                             + "; ".join(parts))
        if self.weather_note:
            lines.append(f"{'Weer' if dutch else 'Weather'}: {self.weather_note}")
        if self.verdict_note:
            lines.append(f"{'Veiligheidscontrole' if dutch else 'Safety check'}: "
                         f"{self.verdict_note}")
        lines += ["", "Het plan, per uur:" if dutch else "The plan, hour by hour:",
                  plan_digest(self.plan, language)]
        return "\n".join(lines)


class PlanExplainer:
    """Answers a grower's questions about one plan, and remembers the exchange."""

    def __init__(self, call_fn: Callable[[str, str, str], str], model: str,
                 memory: GrowerMemory | None = None, max_history: int = 12):
        self.call_fn = call_fn
        self.model = model
        self.memory = memory
        self.max_history = max_history

    def _system(self, language: str) -> str:
        parts = [EXPLAINER_SYSTEM, i18n.language_instruction(language)]
        if self.memory is not None:
            block = self.memory.prompt_block()
            if block:
                parts.append(block)
        return "\n\n".join(parts)

    def ask(self, context: PlanContext, question: str, *, hour: int | None = None,
            record: bool = True) -> dict[str, Any]:
        """Answer one question about the plan.

        Raises:
            ValueError: on an empty or over-long question.
        """
        question = (question or "").strip()
        if not question:
            raise ValueError("Ask a question first.")
        if len(question) > MAX_QUESTION_CHARS:
            raise ValueError(
                f"That question is longer than {MAX_QUESTION_CHARS} characters. "
                f"Please shorten it.")

        history = ""
        if self.memory is not None:
            previous = self.memory.turns(context.run_id, limit=self.max_history)
            if previous:
                history = "\n".join(
                    f"{'Grower' if t['role'] == 'grower' else 'You'}: {t['text']}"
                    for t in previous[-self.max_history:])

        prompt_parts = [context.brief()]
        if history:
            prompt_parts += ["", "Earlier in this conversation:", history]
        if hour is not None:
            prompt_parts += ["", f"The grower is asking about hour {hour:02d}:00."]
        prompt_parts += ["", f"Grower's question: {question}"]

        if record and self.memory is not None:
            self.memory.add_turn(context.run_id, "grower", question, hour=hour)

        answer = self.call_fn(self.model, self._system(context.language),
                              "\n".join(prompt_parts)).strip()
        if record and self.memory is not None:
            self.memory.add_turn(context.run_id, "assistant", answer,
                                 model=self.model, hour=hour)
        return {"question": question, "answer": answer, "model": self.model,
                "hour": hour, "run_id": context.run_id}

    def opening_questions(self, language: str = "en") -> list[str]:
        """Suggested first questions, so a blank box is never the first thing seen."""
        return [i18n.translate(key, language) for key in
                ("chat.suggest.why_chp", "chat.suggest.why_lights",
                 "chat.suggest.cheaper", "chat.suggest.crop_safe")]


def extract_preference(call_fn: Callable[[str, str, str], str], model: str,
                       objection: str, *, language: str = "en",
                       plan_context: PlanContext | None = None,
                       hour: int | None = None) -> dict[str, Any]:
    """Propose a standing rule from an objection, for the grower to confirm.

    The returned ``confirmed`` is always False. Nothing here binds a future plan
    until a person has agreed to the wording.

    Raises:
        ValueError: if the objection is empty, or the model's reply cannot be parsed.
    """
    objection = (objection or "").strip()
    if not objection:
        raise ValueError("Tell us what you disagree with first.")

    prompt = []
    if plan_context is not None:
        prompt += [plan_context.brief(), ""]
    if hour is not None:
        prompt.append(f"This is about hour {hour:02d}:00.")
    prompt += [f"The grower said: {objection}",
               "", "Turn this into one standing instruction."]

    raw = call_fn(model, PREFERENCE_SYSTEM + "\n\n" + i18n.language_instruction(language),
                  "\n".join(prompt))
    try:
        data = _extract_json(raw)
    except ValueError as exc:
        raise ValueError(
            "The assistant could not turn that into a rule. Try saying it as an "
            "instruction, for example: do not run the CHP after 22:00."
        ) from exc

    rule = str(data.get("rule", "")).strip()
    if not rule:
        raise ValueError("The assistant did not produce a usable rule. Please rephrase.")
    strength = str(data.get("strength", "preference")).strip().lower()
    if strength not in STRENGTHS:
        strength = "preference"
    try:
        confidence = min(1.0, max(0.0, float(data.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5

    return {
        "rule": rule[:400],
        "reason": objection[:1000],
        "strength": strength,
        "scope": _clean_scope(data.get("scope")),
        "confidence": confidence,
        "restatement": str(data.get("restatement", "")).strip()[:400] or rule[:400],
        "source": "inferred",
        "confirmed": False,
    }


def propose_compromise(call_fn: Callable[[str, str, str], str], model: str, *,
                       context: PlanContext, hour: int, field_name: str,
                       ai_value: str, grower_value: str, grower_reason: str = "",
                       safety_blocked: bool = False,
                       cost_delta_eur: float = 0.0) -> dict[str, Any]:
    """Look for a third position between the grower and the planner.

    Returns a dict with ``found``. When False, the disagreement is genuinely
    binary and the interface should say so rather than inventing a middle.
    """
    language = i18n.normalise(context.language)
    lines = [
        context.brief(),
        "",
        f"Disagreement at hour {hour:02d}:00 about '{field_name}'.",
        f"The planner chose: {ai_value}",
        f"The grower wants: {grower_value}",
    ]
    if grower_reason:
        lines.append(f"The grower's reason: {grower_reason}")
    if safety_blocked:
        lines.append("The safety checker refuses the grower's choice outright, so any "
                     "compromise must move away from it far enough to pass.")
    if cost_delta_eur:
        lines.append(f"The grower's choice changes the day's cost by "
                     f"{i18n.format_money(cost_delta_eur, language)}.")
    lines += ["", "Is there a middle position?"]

    raw = call_fn(model, COMPROMISE_SYSTEM + "\n\n" + i18n.language_instruction(language),
                  "\n".join(lines))
    try:
        data = _extract_json(raw)
    except ValueError:
        return {"found": False, "explanation": i18n.translate("conflict.none_found", language),
                "hour": hour, "field_name": field_name}

    if not data.get("found"):
        return {
            "found": False,
            "explanation": str(data.get("explanation", "")).strip()
                           or i18n.translate("conflict.none_found", language),
            "hour": hour, "field_name": field_name,
        }
    return {
        "found": True,
        "value": str(data.get("value", "")).strip()[:200],
        "hours": _clean_hours(data.get("hours")) or [hour],
        "explanation": str(data.get("explanation", "")).strip()[:600],
        "gives_up": str(data.get("gives_up", "")).strip()[:300],
        "keeps": str(data.get("keeps", "")).strip()[:300],
        "hour": hour, "field_name": field_name,
    }


def detect_conflicts(original: list[dict[str, Any]], edited: list[dict[str, Any]],
                     fields: tuple[str, ...] = ("heat_source", "lighting_level", "battery",
                                                "battery_power_kw", "chp_mode", "co2_source"),
                     ) -> list[dict[str, Any]]:
    """Every field the grower changed, paired with what the planner had chosen.

    Pure and offline: this is arithmetic on two plans, not a model call. It runs
    before any compromise is sought, so the interface can show the disagreement
    even with no model configured.
    """
    by_hour = {int(row.get("hour", i)): row for i, row in enumerate(original)}
    out = []
    for index, row in enumerate(edited):
        hour = int(row.get("hour", index))
        before = by_hour.get(hour)
        if before is None:
            continue
        for field_name in fields:
            ai_value, grower_value = before.get(field_name), row.get(field_name)
            if ai_value is None or grower_value is None:
                continue
            if isinstance(ai_value, float) or isinstance(grower_value, float):
                if abs(float(ai_value) - float(grower_value)) < 1e-9:
                    continue
            elif ai_value == grower_value:
                continue
            out.append({
                "hour": hour, "field_name": field_name,
                "ai_value": str(ai_value), "grower_value": str(grower_value),
                "ai_rationale": str(before.get("reasoning", "")),
            })
    return out
