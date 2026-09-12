"""The grower-facing endpoints, driven over real HTTP.

These run against a live server on a random port, because the things most likely
to break here are routing, JSON shapes and status codes rather than the logic
underneath -- and none of those are exercised by calling the methods directly.

No model is configured in these tests. That is the realistic first-run state, and
every endpoint that needs one must say so in words the grower can act on rather
than returning a stack trace.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from kasflex.ui.server import serve

CONFIG = Path("configs/scenario_westland_winter.yaml").resolve()


@pytest.fixture
def server(tmp_path, monkeypatch):
    """A server rooted in a temporary directory, with no model keys present."""
    for variable in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
                     "OPENAI_COMPATIBLE_API_KEY", "ENTSOE_API_KEY"):
        monkeypatch.setenv(variable, "")
    monkeypatch.chdir(tmp_path)
    instance = serve(config_path=str(CONFIG), port=0)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    instance.root = f"http://127.0.0.1:{instance.server_address[1]}"  # type: ignore[attr-defined]
    try:
        yield instance
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=2)


def get(server, path: str):
    with urllib.request.urlopen(server.root + path, timeout=10) as response:
        return json.loads(response.read().decode())


def get_raw(server, path: str) -> tuple[str, str]:
    with urllib.request.urlopen(server.root + path, timeout=10) as response:
        return response.read().decode(), response.headers.get("Content-Type", "")


def post(server, path: str, payload: dict):
    request = urllib.request.Request(
        server.root + path, json.dumps(payload).encode(),
        {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode())


def post_expecting(server, path: str, payload: dict, status: int) -> dict:
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(server, path, payload)
    assert exc.value.code == status
    return json.loads(exc.value.read().decode())


PLAN = [
    {"hour": 0, "power_price_eur_kwh": 0.09, "heat_source": "boiler",
     "lighting_level": 1.0, "battery": "idle", "battery_power_kw": 0,
     "chp_mode": "off", "co2_source": "liquid", "reasoning": "cheap"},
    {"hour": 3, "power_price_eur_kwh": 0.07, "heat_source": "chp",
     "lighting_level": 0.0, "battery": "charge", "battery_power_kw": 206,
     "chp_mode": "heat_led", "co2_source": "chp", "reasoning": "gas beats power"},
]


# -- language ---------------------------------------------------------------


def test_translations_come_back_for_both_languages(server):
    english = get(server, "/api/i18n?lang=en")
    dutch = get(server, "/api/i18n?lang=nl")

    assert english["language"] == "en"
    assert dutch["language"] == "nl"
    assert dutch["strings"]["common.save"] == "Opslaan"
    assert english["strings"]["common.save"] == "Save"
    assert {lang["code"] for lang in dutch["languages"]} == {"en", "nl"}


def test_unknown_language_falls_back_rather_than_failing(server):
    assert get(server, "/api/i18n?lang=fr")["language"] == "en"


def test_language_is_an_adjustable_setting(server):
    paths = {f["path"] for f in get(server, "/api/settings")["fields"]}
    assert {"language", "llm_provider", "llm_model"} <= paths


# -- models -----------------------------------------------------------------


def test_model_status_lists_providers_without_leaking_keys(server):
    status = get(server, "/api/models")
    ids = {p["id"] for p in status["providers"]}

    assert {"anthropic", "openai", "google", "ollama"} <= ids
    assert "api_key" not in json.dumps(status)
    ollama = next(p for p in status["providers"] if p["id"] == "ollama")
    assert ollama["local"] is True and ollama["requires_key"] is False


def test_testing_an_unknown_provider_is_refused(server):
    body = post_expecting(server, "/api/models/test",
                          {"provider": "made-up", "model": "x"}, 400)
    assert "listed AI services" in body["error"]


def test_testing_a_provider_with_no_key_reports_failure_not_a_crash(server):
    result = post(server, "/api/models/test",
                  {"provider": "anthropic", "model": "claude-opus-5"})
    assert result["ok"] is False
    assert "ANTHROPIC_API_KEY" in result["message"]


# -- asking why, with no model configured -----------------------------------


def test_asking_without_a_model_explains_how_to_fix_it(server):
    body = post_expecting(server, "/api/explain", {
        "run_id": "r1", "plan": PLAN, "metrics": {}, "question": "Why the CHP?",
    }, 400)
    assert "Settings" in body["error"]


def test_asking_in_dutch_without_a_model_answers_in_dutch(server):
    body = post_expecting(server, "/api/explain", {
        "run_id": "r1", "plan": PLAN, "metrics": {}, "question": "Waarom de WKK?",
        "overrides": {"language": "nl"},
    }, 400)
    assert "Instellingen" in body["error"]


def test_asking_about_no_plan_is_a_conflict_not_a_crash(server):
    post_expecting(server, "/api/explain",
                   {"run_id": "r1", "plan": [], "question": "Why?"}, 409)


def test_suggested_questions_need_no_model(server):
    dutch = post(server, "/api/suggested-questions", {"overrides": {"language": "nl"}})
    assert len(dutch["questions"]) == 4
    assert any("Waarom" in q for q in dutch["questions"])


# -- preferences ------------------------------------------------------------


def test_preferences_start_empty_and_can_be_added(server):
    assert get(server, "/api/preferences")["preferences"] == []

    created = post(server, "/api/preferences", {
        "rule": "Do not run the CHP between 22:00 and 06:00",
        "reason": "it jammed last February", "strength": "strong",
        "scope": {"assets": ["chp"]},
    })
    assert created["active"] is True
    assert created["reason"] == "it jammed last February"

    listed = get(server, "/api/preferences")
    assert len(listed["preferences"]) == 1
    assert listed["statistics"]["preferences_active"] == 1
    assert "absolute" in listed["strengths"]


def test_a_preference_without_a_rule_is_refused(server):
    body = post_expecting(server, "/api/preferences", {"rule": "  ", "reason": "x"}, 400)
    assert "rule" in body["error"]


def test_retiring_a_preference_keeps_it_on_record(server):
    created = post(server, "/api/preferences", {"rule": "No CHP overnight", "reason": "noise"})
    retired = post(server, "/api/preferences/change", {
        "pref_id": created["pref_id"], "action": "retire", "reason": "engine replaced"})

    assert retired["active"] is False
    assert retired["retired_reason"] == "engine replaced"
    assert get(server, "/api/preferences")["statistics"]["preferences_active"] == 0


def test_retiring_something_that_never_existed_is_a_404(server):
    post_expecting(server, "/api/preferences/change",
                   {"pref_id": "nope", "action": "retire"}, 404)


def test_an_unknown_preference_action_is_refused(server):
    created = post(server, "/api/preferences", {"rule": "No CHP", "reason": "x"})
    post_expecting(server, "/api/preferences/change",
                   {"pref_id": created["pref_id"], "action": "explode"}, 400)


def test_turning_an_objection_into_a_rule_needs_a_model(server):
    body = post_expecting(server, "/api/preferences/from-objection", {
        "run_id": "r1", "objection": "I don't trust the CHP at night"}, 400)
    assert "Settings" in body["error"]


# -- conflicts --------------------------------------------------------------


def test_edits_become_recorded_conflicts(server):
    edited = [dict(row) for row in PLAN]
    edited[1]["heat_source"] = "boiler"

    result = post(server, "/api/conflicts", {
        "run_id": "r1", "revision": 1, "original": PLAN, "edited": edited,
        "reason": "I don't trust it overnight"})

    assert result["count"] == 1
    conflict = result["conflicts"][0]
    assert conflict["hour"] == 3
    assert conflict["ai_value"] == "chp"
    assert conflict["grower_value"] == "boiler"
    assert conflict["resolution"] == "open"
    assert conflict["grower_reason"] == "I don't trust it overnight"


def test_identical_plans_record_no_conflict(server):
    result = post(server, "/api/conflicts", {
        "run_id": "r1", "original": PLAN, "edited": [dict(r) for r in PLAN]})
    assert result["count"] == 0


def test_comparing_nothing_is_a_conflict_status(server):
    post_expecting(server, "/api/conflicts", {"original": [], "edited": []}, 409)


def test_a_conflict_can_be_resolved_as_a_compromise(server):
    edited = [dict(row) for row in PLAN]
    edited[1]["heat_source"] = "boiler"
    conflict = post(server, "/api/conflicts", {
        "run_id": "r1", "original": PLAN, "edited": edited})["conflicts"][0]

    resolved = post(server, "/api/conflicts/resolve", {
        "conflict_id": conflict["conflict_id"], "resolution": "compromise",
        "resolved_value": "chp from 06:00"})

    assert resolved["resolution"] == "compromise"
    assert get(server, "/api/conflicts?run_id=r1")["statistics"]["conflicts_compromise"] == 1


def test_an_invalid_resolution_is_refused(server):
    edited = [dict(row) for row in PLAN]
    edited[1]["heat_source"] = "boiler"
    conflict = post(server, "/api/conflicts", {
        "run_id": "r1", "original": PLAN, "edited": edited})["conflicts"][0]
    post_expecting(server, "/api/conflicts/resolve", {
        "conflict_id": conflict["conflict_id"], "resolution": "sort-of"}, 400)


def test_resolving_an_unknown_conflict_is_a_404(server):
    post_expecting(server, "/api/conflicts/resolve",
                   {"conflict_id": "nope", "resolution": "ai_kept"}, 404)


def test_conflicts_are_filtered_by_run(server):
    edited = [dict(row) for row in PLAN]
    edited[1]["heat_source"] = "boiler"
    post(server, "/api/conflicts", {"run_id": "a", "original": PLAN, "edited": edited})
    post(server, "/api/conflicts", {"run_id": "b", "original": PLAN, "edited": edited})

    assert len(get(server, "/api/conflicts?run_id=a")["conflicts"]) == 1
    assert len(get(server, "/api/conflicts")["conflicts"]) == 2


# -- saved setups -----------------------------------------------------------


def test_a_setup_saves_lists_and_exports(server):
    saved = post(server, "/api/profiles", {
        "name": "Westland block 3", "language": "nl",
        "settings": {"hub.floor_area_m2": 50000, "language": "nl"},
        "equipment": {"chp": True, "battery": True}})

    assert saved["name"] == "Westland block 3"
    assert [p["name"] for p in get(server, "/api/profiles")["profiles"]] == ["Westland block 3"]

    exported, content_type = get_raw(server, f"/api/profiles/export/{saved['profile_id']}")
    assert "application/json" in content_type
    assert json.loads(exported)["marker"] == "kasflex.profile"


def test_an_unnamed_setup_is_refused(server):
    post_expecting(server, "/api/profiles", {"name": "", "settings": {}}, 400)


def test_a_setup_can_be_imported_from_a_file(server):
    saved = post(server, "/api/profiles", {"name": "Home", "settings": {"language": "nl"}})
    exported, _ = get_raw(server, f"/api/profiles/export/{saved['profile_id']}")

    imported = post(server, "/api/profiles/import", {"text": exported})
    assert imported["name"] == "Home"


def test_importing_a_foreign_file_says_so(server):
    body = post_expecting(server, "/api/profiles/import",
                          {"text": json.dumps({"something": "else"})}, 400)
    assert "not a KasFlex setup" in body["error"]


def test_a_setup_can_be_deleted(server):
    saved = post(server, "/api/profiles", {"name": "Temp", "settings": {}})
    remaining = post(server, "/api/profiles/delete", {"profile_id": saved["profile_id"]})
    assert remaining["profiles"] == []


def test_exporting_a_missing_setup_is_a_404(server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        get_raw(server, "/api/profiles/export/does-not-exist")
    assert exc.value.code == 404


# -- research export --------------------------------------------------------


def test_fair_bundle_is_self_describing(server):
    post(server, "/api/preferences", {"rule": "No CHP overnight", "reason": "it jammed"})
    bundle = get(server, "/api/export/fair")

    assert bundle["@context"]["@vocab"] == "https://schema.org/"
    assert bundle["dataset"]["dcterms:license"]["identifier"] == "CC-BY-4.0"
    assert bundle["kasflex:preferences"][0]["reason"] == "it jammed"
    assert bundle["kasflex:codebook"]["preference.reason"]["description"]
    assert bundle["kasflex:limitations"]
    assert bundle["kasflex:anonymised"] is True


def test_fair_bundle_can_be_requested_identifiable(server):
    assert get(server, "/api/export/fair?anonymous=0")["kasflex:anonymised"] is False


def test_conflicts_export_as_csv(server):
    edited = [dict(row) for row in PLAN]
    edited[1]["heat_source"] = "boiler"
    post(server, "/api/conflicts", {"run_id": "r1", "original": PLAN, "edited": edited})

    body, content_type = get_raw(server, "/api/export/fair?format=csv")
    assert "text/csv" in content_type
    lines = body.strip().splitlines()
    assert lines[0].startswith("conflict_id,")
    assert "boiler" in lines[1]


# -- the conversation transcript --------------------------------------------


def test_conversation_starts_empty(server):
    assert get(server, "/api/conversation/r1")["turns"] == []


# -- uncertainty ------------------------------------------------------------


def test_a_run_reports_its_own_uncertainty(server):
    result = post(server, "/api/run", {"overrides": {"planner": "rule-based"}})
    uncertainty = result["uncertainty"]

    assert uncertainty["forecast_error"]["basis"] in {"measured", "assumed"}
    assert uncertainty["novelty"]["band"] in {"typical", "unusual",
                                             "unlike anything seen", "unknown"}
    assert uncertainty["confidence"] in {"high", "medium", "low", "unknown"}
    assert uncertainty["words"]["headline"]
    assert any("unvalidated" in c for c in uncertainty["caveats"])


def test_an_indefensible_band_is_not_dressed_up_as_one(server):
    """With no cached weather the error is assumed; the words must admit it."""
    result = post(server, "/api/run", {"overrides": {"planner": "rule-based"}})
    uncertainty = result["uncertainty"]

    if not uncertainty["is_defensible"]:
        assert uncertainty["confidence"] == "unknown"
        assert "can't tell you" in uncertainty["words"]["headline"]


def test_uncertainty_words_follow_the_language(server):
    result = post(server, "/api/run", {"overrides": {"planner": "rule-based",
                                                     "language": "nl"}})
    headline = result["uncertainty"]["words"]["headline"]
    assert "Waarschijnlijk tussen" in headline or "niet zeggen" in headline


# -- reliance ---------------------------------------------------------------


def test_reliance_starts_empty_with_none_rates(server):
    metrics = get(server, "/api/reliance")
    assert metrics["elicitations"] == 0
    assert metrics["appropriate_reliance_rate"] is None
    assert metrics["rair"] is None


def test_an_opinion_is_recorded_before_any_suggestion(server):
    item = post(server, "/api/elicit", {
        "run_id": "r1", "question": "heat_source@03", "grower_choice": "boiler",
        "confidence": 4, "hour": 3, "condition": "uncertainty_shown"})

    assert item["grower_choice"] == "boiler"
    assert item["confidence"] == 4
    assert item["ai_choice"] == ""
    assert item["verdict"] == ""


def test_confidence_outside_the_scale_is_refused(server):
    body = post_expecting(server, "/api/elicit", {
        "run_id": "r1", "grower_choice": "boiler", "confidence": 9}, 400)
    assert "between 1 and 5" in body["error"]


def test_an_empty_opinion_is_refused(server):
    post_expecting(server, "/api/elicit",
                   {"run_id": "r1", "grower_choice": "", "confidence": 3}, 400)


def test_resolving_before_revealing_is_refused(server):
    item = post(server, "/api/elicit", {
        "run_id": "r1", "grower_choice": "boiler", "confidence": 3})
    body = post_expecting(server, "/api/elicit/step", {
        "elicitation_id": item["elicitation_id"], "action": "resolve",
        "final_choice": "boiler"}, 400)
    assert "nothing to have relied on" in body["error"]


def test_a_full_decision_classifies_as_over_reliance(server):
    item = post(server, "/api/elicit", {
        "run_id": "r1", "grower_choice": "boiler", "confidence": 5, "hour": 3})
    eid = item["elicitation_id"]

    post(server, "/api/elicit/step", {"elicitation_id": eid, "action": "reveal",
                                      "ai_choice": "chp", "ai_confidence": "medium"})
    post(server, "/api/elicit/step", {"elicitation_id": eid, "action": "resolve",
                                      "final_choice": "chp"})
    scored = post(server, "/api/elicit/step", {"elicitation_id": eid, "action": "score",
                                               "better_choice": "boiler"})

    assert scored["verdict"] == "over_reliance"
    assert scored["switched"] is True

    metrics = get(server, "/api/reliance")
    assert metrics["over_reliance"] == 1
    assert metrics["appropriate_reliance_rate"] == 0


def test_metrics_can_be_filtered_by_condition(server):
    for condition, final in (("shown", "chp"), ("hidden", "boiler")):
        item = post(server, "/api/elicit", {
            "run_id": "r1", "grower_choice": "boiler", "confidence": 3,
            "condition": condition})
        eid = item["elicitation_id"]
        post(server, "/api/elicit/step", {"elicitation_id": eid, "action": "reveal",
                                          "ai_choice": "chp"})
        post(server, "/api/elicit/step", {"elicitation_id": eid, "action": "resolve",
                                          "final_choice": final})
        post(server, "/api/elicit/step", {"elicitation_id": eid, "action": "score",
                                          "better_choice": "chp"})

    assert get(server, "/api/reliance?condition=shown")["appropriate_ai"] == 1
    assert get(server, "/api/reliance?condition=hidden")["under_reliance"] == 1


def test_an_unknown_step_is_refused(server):
    item = post(server, "/api/elicit", {
        "run_id": "r1", "grower_choice": "boiler", "confidence": 3})
    post_expecting(server, "/api/elicit/step", {
        "elicitation_id": item["elicitation_id"], "action": "teleport"}, 400)


def test_stepping_an_unknown_decision_is_a_404(server):
    post_expecting(server, "/api/elicit/step",
                   {"elicitation_id": "nope", "action": "reveal", "ai_choice": "chp"}, 404)


def test_elicitations_are_listed_per_run(server):
    post(server, "/api/elicit", {"run_id": "a", "grower_choice": "boiler", "confidence": 3})
    post(server, "/api/elicit", {"run_id": "b", "grower_choice": "chp", "confidence": 3})

    assert len(get(server, "/api/elicitations?run_id=a")["elicitations"]) == 1
    assert len(get(server, "/api/elicitations")["elicitations"]) == 2


def test_an_outcome_records_calibration(server):
    outcome = post(server, "/api/outcomes", {
        "run_id": "r1", "predicted_cost_eur": 10000, "actual_cost_eur": 10450,
        "ai_plan_cost_eur": 10200, "final_plan_cost_eur": 10450,
        "within_predicted_band": True})

    assert outcome["prediction_error_eur"] == 450
    assert outcome["ai_plan_was_better"] is True
    assert get(server, "/api/reliance")["band_coverage"] == 1.0


def test_an_outcome_needs_numbers(server):
    post_expecting(server, "/api/outcomes",
                   {"run_id": "r1", "predicted_cost_eur": "lots"}, 400)


def test_reliance_data_reaches_the_fair_bundle(server):
    item = post(server, "/api/elicit", {
        "run_id": "r1", "grower_choice": "boiler", "confidence": 2})
    eid = item["elicitation_id"]
    post(server, "/api/elicit/step", {"elicitation_id": eid, "action": "reveal",
                                      "ai_choice": "chp"})
    post(server, "/api/elicit/step", {"elicitation_id": eid, "action": "resolve",
                                      "final_choice": "chp"})
    post(server, "/api/elicit/step", {"elicitation_id": eid, "action": "score",
                                      "better_choice": "chp"})
    post(server, "/api/outcomes", {"run_id": "r1", "predicted_cost_eur": 1,
                                   "actual_cost_eur": 2})

    bundle = get(server, "/api/export/fair")
    assert bundle["kasflex:elicitations"][0]["verdict"] == "appropriate_ai"
    assert bundle["kasflex:outcomes"][0]["prediction_error_eur"] == 1
    assert bundle["kasflex:relianceMetrics"]["scored"] == 1
    assert bundle["kasflex:codebook"]["elicitation.confidence"]["description"]
    assert bundle["kasflex:codebook"]["metrics.rair"]["note"].startswith("None when")


def test_dot_env_is_never_served(server):
    for path in ("/.env", "/api/../.env"):
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(server.root + path, timeout=10)
        assert exc.value.code in (403, 404)
