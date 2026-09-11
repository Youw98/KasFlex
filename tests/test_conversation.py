"""Explanation, preference extraction, compromise, and conflict arithmetic.

No network. ``call_fn`` is a plain function, which is the whole point of injecting
the transport: the grower-facing behaviour is testable without a vendor account.

The hostile cases matter most here. A model that returns prose where JSON was
asked for, or a rule wider than the objection, must produce a visible failure --
never a silent change to what the planner will do tomorrow.
"""

from __future__ import annotations

import json

import pytest

from kasflex import conversation as conv
from kasflex.memory import GrowerMemory


@pytest.fixture
def memory(tmp_path) -> GrowerMemory:
    return GrowerMemory(tmp_path / "grower.sqlite3")


@pytest.fixture
def plan() -> list[dict]:
    """A short day with one obvious talking point: the CHP running at 03:00."""
    return [
        {"hour": 0, "power_price_eur_kwh": 0.09, "heat_source": "boiler",
         "lighting_level": 1.0, "battery": "idle", "battery_power_kw": 0,
         "chp_mode": "off", "co2_source": "liquid", "reasoning": "cheap enough to light"},
        {"hour": 3, "power_price_eur_kwh": 0.07, "heat_source": "chp",
         "lighting_level": 0.0, "battery": "charge", "battery_power_kw": 206,
         "chp_mode": "heat_led", "co2_source": "chp", "reasoning": "gas beats power here"},
        {"hour": 12, "power_price_eur_kwh": 0.21, "heat_source": "buffer",
         "lighting_level": 0.0, "battery": "discharge", "battery_power_kw": 186,
         "chp_mode": "off", "co2_source": "liquid", "reasoning": "expensive, lean on storage"},
    ]


@pytest.fixture
def context(plan) -> conv.PlanContext:
    return conv.PlanContext(
        run_id="run-1", date="2026-09-12", plan=plan,
        metrics={"net_cost_eur": 10457.0, "temperature_band_hours": 22},
        language="en", data_source="cache",
    )


def scripted(*replies: str):
    """A call_fn that returns each reply in turn and records what it was sent."""
    sent: list[dict] = []
    queue = list(replies)

    def call(model: str, system: str, prompt: str) -> str:
        sent.append({"model": model, "system": system, "prompt": prompt})
        return queue.pop(0) if queue else ""

    call.sent = sent  # type: ignore[attr-defined]
    return call


# -- the digest and the brief ----------------------------------------------


def test_digest_lists_every_hour_with_its_price(plan):
    digest = conv.plan_digest(plan)
    assert "03 | 0.070 | chp" in digest
    assert "charge 206kW" in digest
    assert "idle" in digest and "idle 0kW" not in digest


def test_brief_states_whether_the_numbers_are_real(context):
    assert "real prices" in context.brief()
    context.data_source = "synthetic"
    assert "invented prices" in context.brief()


def test_brief_formats_money_for_the_language(plan):
    dutch = conv.PlanContext(run_id="r", date="d", plan=plan,
                             metrics={"net_cost_eur": 10457.0}, language="nl")
    assert "€ 10.457" in dutch.brief()


# -- explaining -------------------------------------------------------------


def test_ask_grounds_the_prompt_in_the_actual_plan(context, memory):
    call = scripted("Gas is cheaper than power overnight, so the CHP earns its keep.")
    explainer = conv.PlanExplainer(call, "test-model", memory)

    result = explainer.ask(context, "Why is the CHP on at three in the morning?", hour=3)

    assert "Gas is cheaper" in result["answer"]
    prompt = call.sent[0]["prompt"]
    assert "03 | 0.070 | chp" in prompt, "the model must see the row being asked about"
    assert "hour 03:00" in prompt
    assert "Why is the CHP on" in prompt


def test_ask_records_both_sides_of_the_exchange(context, memory):
    explainer = conv.PlanExplainer(scripted("Because gas is cheap."), "test-model", memory)
    explainer.ask(context, "Why the CHP?")

    turns = memory.turns("run-1")
    assert [t["role"] for t in turns] == ["grower", "assistant"]
    assert turns[1]["model"] == "test-model"


def test_a_second_question_can_see_the_first(context, memory):
    call = scripted("Because gas is cheap.", "Yes, and it also makes CO2 for the crop.")
    explainer = conv.PlanExplainer(call, "test-model", memory)
    explainer.ask(context, "Why the CHP?")
    explainer.ask(context, "Is that the only reason?")

    assert "Why the CHP?" in call.sent[1]["prompt"]
    assert "Because gas is cheap." in call.sent[1]["prompt"]


def test_known_preferences_reach_the_explainer(context, memory):
    memory.add_preference("Do not run the CHP overnight", "it jammed last February")
    call = scripted("You've told me before you'd rather it stayed off.")
    conv.PlanExplainer(call, "test-model", memory).ask(context, "Why the CHP?")

    assert "it jammed last February" in call.sent[0]["system"]


def test_dutch_context_asks_the_model_for_dutch(context, memory):
    context.language = "nl"
    call = scripted("De WKK draait omdat gas nu goedkoop is.")
    conv.PlanExplainer(call, "test-model", memory).ask(context, "Waarom draait de WKK?")

    assert "Nederlands" in call.sent[0]["system"]
    assert "WKK" in call.sent[0]["system"]


def test_empty_question_is_refused(context, memory):
    explainer = conv.PlanExplainer(scripted("unused"), "test-model", memory)
    with pytest.raises(ValueError, match="Ask a question"):
        explainer.ask(context, "   ")


def test_absurdly_long_question_is_refused(context, memory):
    explainer = conv.PlanExplainer(scripted("unused"), "test-model", memory)
    with pytest.raises(ValueError, match="shorten"):
        explainer.ask(context, "x" * (conv.MAX_QUESTION_CHARS + 1))


def test_refused_question_is_not_recorded(context, memory):
    explainer = conv.PlanExplainer(scripted("unused"), "test-model", memory)
    with pytest.raises(ValueError):
        explainer.ask(context, "")
    assert memory.turns("run-1") == []


def test_opening_questions_are_translated():
    explainer = conv.PlanExplainer(scripted(), "m")
    assert "Waarom" in " ".join(explainer.opening_questions("nl"))
    assert "Why" in " ".join(explainer.opening_questions("en"))


# -- turning an objection into a rule ---------------------------------------


def test_extract_preference_returns_something_confirmable():
    reply = json.dumps({
        "rule": "Do not run the CHP between 22:00 and 06:00",
        "strength": "strong",
        "scope": {"assets": ["chp"], "hours": [22, 23, 0, 1, 2, 3, 4, 5]},
        "confidence": 0.8,
        "restatement": "Shall I keep the CHP off overnight from now on?",
    })
    result = conv.extract_preference(scripted(reply), "m",
                                     "I don't trust the CHP at night, it jammed in February")

    assert result["rule"].startswith("Do not run the CHP")
    assert result["strength"] == "strong"
    assert result["scope"]["assets"] == ["chp"]
    assert result["confirmed"] is False, "an inferred rule must never bind on its own"
    assert "jammed in February" in result["reason"], "the grower's words are kept verbatim"


def test_extract_preference_survives_prose_around_the_json():
    reply = ('Sure! Here is the rule:\n```json\n'
             '{"rule": "Keep lights off after 20:00", "strength": "preference"}\n```\nHope that helps.')
    result = conv.extract_preference(scripted(reply), "m", "lights bother the neighbours")
    assert result["rule"] == "Keep lights off after 20:00"


def test_unparseable_reply_asks_the_grower_to_rephrase():
    with pytest.raises(ValueError, match="rephrase|instruction"):
        conv.extract_preference(scripted("I'm not sure what you mean."), "m", "no")


def test_missing_rule_is_refused():
    with pytest.raises(ValueError, match="usable rule"):
        conv.extract_preference(scripted(json.dumps({"strength": "strong"})), "m", "no CHP")


def test_invented_strength_falls_back_to_the_gentlest():
    reply = json.dumps({"rule": "Avoid the CHP", "strength": "utterly-forbidden"})
    result = conv.extract_preference(scripted(reply), "m", "I dislike it")
    assert result["strength"] == "preference"


def test_out_of_range_hours_are_dropped():
    reply = json.dumps({"rule": "No CHP at night",
                        "scope": {"hours": [22, 23, 0, 99, -4, "3", None]}})
    result = conv.extract_preference(scripted(reply), "m", "night noise")
    assert result["scope"]["hours"] == [0, 3, 22, 23]


def test_confidence_is_clamped():
    reply = json.dumps({"rule": "No CHP", "confidence": 7.5})
    assert conv.extract_preference(scripted(reply), "m", "x")["confidence"] == 1.0


def test_empty_objection_is_refused():
    with pytest.raises(ValueError, match="disagree with"):
        conv.extract_preference(scripted(), "m", "  ")


# -- compromise -------------------------------------------------------------


def test_compromise_is_a_real_third_position(context):
    reply = json.dumps({
        "found": True, "value": "chp from 06:00", "hours": [6, 7, 8],
        "explanation": "Running the CHP only after six keeps most of the saving.",
        "gives_up": "a little of the overnight saving",
        "keeps": "no CHP while you are asleep",
    })
    result = conv.propose_compromise(scripted(reply), "m", context=context, hour=3,
                                     field_name="heat_source", ai_value="chp",
                                     grower_value="boiler",
                                     grower_reason="I don't trust it overnight")
    assert result["found"] is True
    assert result["value"] == "chp from 06:00"
    assert result["hours"] == [6, 7, 8]


def test_compromise_may_honestly_report_none(context):
    reply = json.dumps({"found": False,
                        "explanation": "The CHP is either on or off at this hour."})
    result = conv.propose_compromise(scripted(reply), "m", context=context, hour=3,
                                     field_name="heat_source", ai_value="chp",
                                     grower_value="boiler")
    assert result["found"] is False
    assert "either on or off" in result["explanation"]


def test_unparseable_compromise_degrades_to_no_middle_way(context):
    result = conv.propose_compromise(scripted("I think maybe try something else?"), "m",
                                     context=context, hour=3, field_name="heat_source",
                                     ai_value="chp", grower_value="boiler")
    assert result["found"] is False
    assert result["explanation"]


def test_safety_block_is_stated_to_the_model(context):
    call = scripted(json.dumps({"found": False, "explanation": "no"}))
    conv.propose_compromise(call, "m", context=context, hour=3, field_name="heat_source",
                            ai_value="chp", grower_value="none", safety_blocked=True)
    assert "safety checker refuses" in call.sent[0]["prompt"]


def test_cost_difference_is_stated_in_the_growers_currency_format(context):
    context.language = "nl"
    call = scripted(json.dumps({"found": False, "explanation": "no"}))
    conv.propose_compromise(call, "m", context=context, hour=3, field_name="heat_source",
                            ai_value="chp", grower_value="boiler", cost_delta_eur=41.0)
    assert "€ 41" in call.sent[0]["prompt"]


# -- conflict detection (pure, no model) ------------------------------------


def test_no_edits_means_no_conflicts(plan):
    assert conv.detect_conflicts(plan, [dict(r) for r in plan]) == []


def test_a_changed_field_becomes_a_conflict(plan):
    edited = [dict(r) for r in plan]
    edited[1]["heat_source"] = "boiler"
    conflicts = conv.detect_conflicts(plan, edited)

    assert len(conflicts) == 1
    assert conflicts[0] == {
        "hour": 3, "field_name": "heat_source", "ai_value": "chp",
        "grower_value": "boiler", "ai_rationale": "gas beats power here",
    }


def test_several_changes_in_one_hour_are_reported_separately(plan):
    edited = [dict(r) for r in plan]
    edited[1]["heat_source"] = "boiler"
    edited[1]["chp_mode"] = "off"
    assert {c["field_name"] for c in conv.detect_conflicts(plan, edited)} == {
        "heat_source", "chp_mode"}


def test_float_noise_is_not_a_conflict(plan):
    edited = [dict(r) for r in plan]
    edited[0]["lighting_level"] = 1.0 + 1e-12
    assert conv.detect_conflicts(plan, edited) == []


def test_a_real_dimming_is_a_conflict(plan):
    edited = [dict(r) for r in plan]
    edited[0]["lighting_level"] = 0.6
    conflicts = conv.detect_conflicts(plan, edited)
    assert conflicts[0]["field_name"] == "lighting_level"


def test_conflicts_match_on_hour_not_position(plan):
    """Reordered rows must still compare like with like."""
    edited = [dict(r) for r in reversed(plan)]
    edited[0]["heat_source"] = "chp"  # hour 12, was buffer
    conflicts = conv.detect_conflicts(plan, edited)
    assert [c["hour"] for c in conflicts] == [12]


def test_recorded_conflicts_round_trip_into_memory(plan, memory):
    edited = [dict(r) for r in plan]
    edited[1]["heat_source"] = "boiler"
    for found in conv.detect_conflicts(plan, edited):
        memory.record_conflict(run_id="run-1", revision=1, **found)

    stored = memory.conflicts("run-1")
    assert len(stored) == 1
    assert stored[0].ai_value == "chp" and stored[0].grower_value == "boiler"
    assert stored[0].resolution == "open"
