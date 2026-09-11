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


def test_dot_env_is_never_served(server):
    for path in ("/.env", "/api/../.env"):
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(server.root + path, timeout=10)
        assert exc.value.code in (403, 404)
