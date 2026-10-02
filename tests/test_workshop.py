"""The workshop: scenarios, study versions, AI-first advice, reasons that are
remembered, the grower's own targets, the grid contract as a hard rule, chat and
the explanation graph.

The scenario tests carry the study's weight: a flawed scenario is only useful if
the AI really gets it wrong without the participant's reason, and really gets it
right with it. Both halves are checked here on the built-in scenarios.
"""

from __future__ import annotations

import dataclasses
import json
import re

import pytest

from kasflex.assistant import answer
from kasflex.config import ConfigError, ScenarioConfig
from kasflex.controllers.scheduler import score_plan
from kasflex.energy.assets import ContractLimits, EnergyHub
from kasflex.energy.contracts import CONTRACT_TYPES, contract_limits, describe
from kasflex.factors import explain_factors
from kasflex.intent import flat_plan
from kasflex.memory import GrowerMemory
from kasflex.reasons import apply_effects, interpret
from kasflex.recommend import PRIORITIES, recommend
from kasflex.resources import static_dir
from kasflex.scenarios import BUILTIN, Scenario, ScenarioStore, scenario_day
from kasflex.ui.server import ApiError, UiServer
from kasflex.ui.workshop_api import clean_goals, evaluate_goals, scenario_check, work_metrics
from kasflex.workshop import VERSIONS, WorkshopStore

CONFIG = "configs/scenario_westland_winter.yaml"


@pytest.fixture(scope="module")
def ui(tmp_path_factory) -> UiServer:
    server = UiServer(config_path=CONFIG)
    home = tmp_path_factory.mktemp("workshop-state")
    server.memory = GrowerMemory(home / "memory.sqlite")
    server.workshop = WorkshopStore(home / "workshop.json")
    return server


def _scenario(scenario_id: str, language: str = "en") -> dict:
    return {"planner": "collaborative", "data_source": "scenario", "scenario_id": scenario_id,
            "language": language}


def _ref(run: dict) -> dict:
    return {"run_id": run["run_id"], "revision": run["revision"], "plan_hash": run["plan_hash"]}


# --- grid contracts -------------------------------------------------------------


def test_every_dutch_contract_type_has_both_languages():
    assert set(CONTRACT_TYPES) == {"firm", "cbc", "time_block", "duration", "non_firm"}
    for key in CONTRACT_TYPES:
        en, nl = describe(key, "en"), describe(key, "nl")
        assert en["name"] and nl["name"] and en["name"] != nl["name"]


def test_contract_types_shape_the_hourly_limits():
    base = ContractLimits(import_limit_kw=6000, export_limit_kw=4000,
                          congestion_windows={17: (3000, 4000)})
    firm = contract_limits(base, "firm")
    assert all(firm.limits_at(h)[0] == 6000 for h in range(24))
    assert contract_limits(base, "cbc").limits_at(17)[0] == 3000
    block = contract_limits(base, "time_block")
    assert block.limits_at(3)[0] == 6000 and block.limits_at(18)[0] < 6000
    duration = contract_limits(base, "duration")
    assert sum(duration.limits_at(h)[0] < 6000 for h in range(24)) <= 0.15 * 24 + 1
    non_firm = contract_limits(base, "non_firm")
    assert min(non_firm.limits_at(h)[0] for h in range(24)) < 6000
    with pytest.raises(ValueError):
        contract_limits(base, "nonsense")


def test_config_rejects_an_unknown_contract_type():
    data = ScenarioConfig().to_dict() if hasattr(ScenarioConfig, "to_dict") else {}
    with pytest.raises(ConfigError):
        ScenarioConfig.from_dict({**data, "grid_contract_type": "nonsense"})


# --- scenarios --------------------------------------------------------------------


def test_builtin_scenarios_are_two_good_and_two_flawed():
    kinds = sorted(s.kind for s in BUILTIN)
    assert kinds == ["flawed", "flawed", "good", "good"]
    for scenario in BUILTIN:
        scenario.validate()
        for key in ("title", "framing", "debrief"):
            assert scenario.text(key, "en") and scenario.text(key, "nl")
        if scenario.kind == "flawed":
            assert scenario.flaw["type"]


def test_scenario_validation_catches_bad_input():
    good = BUILTIN[0].to_dict()
    with pytest.raises(ValueError):
        Scenario.from_dict({**good, "prices_eur_kwh": [0.1] * 23})
    with pytest.raises(ValueError):
        Scenario.from_dict({**good, "id": "Bad Id!"})
    with pytest.raises(ValueError):
        Scenario.from_dict({**good, "kind": "flawed", "flaw": {"type": ""}})
    with pytest.raises(ValueError):
        Scenario.from_dict({**good, "hub": {"boiler_kw": -5}})


def test_store_saves_overrides_and_restores_builtins(tmp_path):
    store = ScenarioStore(tmp_path)
    original = store.get("evening-peak")
    edited = {**original.to_dict(), "title": {"en": "Edited", "nl": "Aangepast"}}
    store.save(edited)
    assert store.get("evening-peak").text("title", "en") == "Edited"
    assert store.get("evening-peak").builtin is False
    assert store.delete("evening-peak")
    assert store.get("evening-peak").builtin is True
    assert not store.delete("evening-peak")  # built-ins cannot be deleted
    store.save({**original.to_dict(), "id": "my-day"})
    assert {s.id for s in store.all()} >= {"my-day", "evening-peak"}


def test_a_broken_scenario_file_does_not_take_the_workshop_down(tmp_path):
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    assert len(ScenarioStore(tmp_path).all()) == len(BUILTIN)


def test_scenario_day_uses_the_scenarios_prices_and_temperatures():
    scenario = BUILTIN[0]
    day = scenario_day(scenario, floor_area_m2=50_000, gas_price_eur_kwh=0.035)
    assert [c.power_price_eur_kwh for c in day.forecast] == scenario.prices_eur_kwh
    assert [c.outdoor_temp_c for c in day.forecast] == scenario.temperatures_c


def test_a_forecast_miss_makes_only_the_real_night_colder():
    scenario = Scenario.from_dict({**BUILTIN[0].to_dict(), "id": "cold-night", "kind": "flawed",
                                   "flaw": {"type": "forecast_miss", "night_temp_drop_c": 6}})
    day = scenario_day(scenario, floor_area_m2=50_000, gas_price_eur_kwh=0.035)
    assert day.actual[2].outdoor_temp_c == pytest.approx(day.forecast[2].outdoor_temp_c - 6)
    assert day.actual[12].outdoor_temp_c == day.forecast[12].outdoor_temp_c


@pytest.mark.parametrize("scenario_id,reason,dimension", [
    ("chp-maintenance", "CHP maintenance from 8 to 14", "work"),
    ("grid-notice", "grid operator: at most 1.5 MW between 16 and 20", "goal"),
])
def test_flawed_scenarios_trap_the_ai_until_the_grower_says_why(ui, scenario_id, reason,
                                                                dimension):
    run = ui.run(_scenario(scenario_id), {"priority": "balanced"})
    assert run["scenario"]["kind"] == "flawed"
    assert not run["scenario"]["check"]["ok"], "the AI should fall into the trap on its own"

    reply = ui.deliberate({**_ref(run), "dimension": dimension, "response": "disagree",
                           "reason": reason})
    alternative = reply["alternative"]
    assert alternative["accepted"]
    assert alternative["scenario"]["check"]["ok"], reply["counter_response"]
    assert reply["remembered_id"]


def test_good_scenarios_have_no_trap(ui):
    for scenario_id in ("evening-peak", "spring-sun"):
        run = ui.run(_scenario(scenario_id), {"priority": "balanced"})
        assert run["accepted"]
        assert run["scenario"]["check"]["ok"]


def test_the_trap_is_not_in_the_payload_before_approval(ui):
    context = ui.day_context(_scenario("grid-notice"))
    assert context["scenario"]["framing_text"]
    for hidden in ("debrief", "debrief_text", "flaw"):
        assert hidden not in context["scenario"]


def test_scenario_check_reports_maintenance_hours():
    scenario = next(s for s in BUILTIN if s.flaw.get("type") == "hidden_maintenance")
    rows = [{"hour": h, "chp_running": h == 9, "grid_import_kw": 0} for h in range(24)]
    check = scenario_check(scenario, rows, {}, 0.0, "en")
    assert not check["ok"] and check["problem_hours"] == [9] and check["debrief"]


# --- study versions -----------------------------------------------------------------


def test_workshop_state_round_trips_and_rejects_unknown_versions(tmp_path):
    store = WorkshopStore(tmp_path / "w.json")
    assert store.get().version in VERSIONS
    store.set(version="manual", scenario_id="grid-notice", lock_scenario=True)
    state = WorkshopStore(tmp_path / "w.json").get()
    assert (state.version, state.scenario_id, state.lock_scenario) == (
        "manual", "grid-notice", True)
    store.set(version="ai")  # other fields kept
    assert store.get().scenario_id == "grid-notice"
    with pytest.raises(ValueError):
        store.set(version="robot")


def test_set_workshop_refuses_an_unknown_scenario(ui):
    with pytest.raises(ApiError):
        ui.set_workshop({"scenario_id": "does-not-exist"})
    status = ui.set_workshop({"version": "ai"})
    assert status["version"] == "ai"
    assert set(status["builtin_ids"]) == {s.id for s in BUILTIN}


def test_runs_report_the_version_they_were_made_in(ui):
    ui.set_workshop({"version": "manual"})
    run = ui.run({"planner": "collaborative", "data_source": "synthetic"}, {})
    assert run["version"] == "manual"
    ui.set_workshop({"version": "collab"})


# --- AI goes first ------------------------------------------------------------------


def test_recommendation_compares_every_priority_and_gives_numbers(ui):
    advice = ui.recommendation({"overrides": _scenario("chp-maintenance"), "policy": {}})
    assert advice["priority"] in PRIORITIES
    assert {o["priority"] for o in advice["options"]} == set(PRIORITIES)
    assert advice["reasons"] and any("€" in r for r in advice["reasons"])
    assert advice["policy"]["priority"] == advice["priority"]


def test_recommender_picks_crop_when_the_cheap_plan_starves_the_crop(conditions):
    hub = EnergyHub()
    hub = dataclasses.replace(hub, crop=dataclasses.replace(hub.crop, dli_target_mol_m2=40.0))
    advice = recommend(hub, conditions, date="2023-01-15")
    assert advice["priority"] == "crop"


# --- reasons and memory ---------------------------------------------------------------


@pytest.mark.parametrize("text,key", [
    ("WKK onderhoud van 8 tot 14 uur", "avoid_chp_hours"),
    ("CHP mechanic 8-14", "avoid_chp_hours"),
    ("only two staff tomorrow", "switch_penalty_eur"),
    ("vorst vannacht, -6 graden", "night_temp_c"),
    ("netbeheerder: max 1,5 MW tussen 16 en 20 uur", "import_caps"),
])
def test_reasons_become_planning_effects(text, key):
    reading = interpret(text, "work", "nl")
    assert key in reading["effects"], reading
    assert reading["summary"]


def test_reason_details_are_read_correctly():
    chp = interpret("CHP maintenance 8-14", "work")["effects"]
    assert chp["avoid_chp_hours"] == list(range(8, 14))
    assert interpret("frost tonight -6 degrees", "crop")["effects"]["night_temp_c"] == -6
    caps = interpret("max 1.5 MW grid between 16 and 20", "goal")["effects"]["import_caps"]
    assert caps == {h: 1500.0 for h in range(16, 20)}
    assert interpret("frost warning", "crop")["applies"] == "cold"
    assert interpret("CHP maintenance 8-14", "work")["applies"] == "once"
    assert interpret("only two staff tomorrow", "work")["applies"] == "once"
    assert interpret("we always have few staff", "work")["applies"] == "always"
    assert interpret("CHP off at night, the neighbours complain", "work")["applies"] == "always"


def test_unknown_reasons_change_nothing_but_are_kept():
    reading = interpret("I just have a feeling", "money")
    assert reading["effects"] == {}
    assert reading["summary"]


def test_effects_merge_without_loosening_anything():
    policy = {"avoid_chp_hours": [1, 2], "battery_reserve_pct": 70, "import_caps": {17: 1000}}
    merged = apply_effects(policy, {"avoid_chp_hours": [2, 3], "battery_reserve_pct": 50,
                                    "import_caps": {17: 2000, 18: 1500}})
    assert merged["avoid_chp_hours"] == [1, 2, 3]
    assert merged["battery_reserve_pct"] == 70
    assert merged["import_caps"] == {17: 1000, 18: 1500}


def test_disagreeing_without_a_reason_is_refused(ui):
    run = ui.run({"planner": "collaborative", "data_source": "synthetic"}, {})
    for reason in ("", "  ", "x"):
        with pytest.raises(ApiError) as caught:
            ui.deliberate({**_ref(run), "dimension": "work", "response": "disagree",
                           "reason": reason})
        assert caught.value.status == 422


def test_a_standing_reason_is_applied_to_later_plans(ui):
    ui.forget_remembered({"everyone": True})
    run = ui.run({"planner": "collaborative", "data_source": "synthetic"}, {})
    reply = ui.deliberate({**_ref(run), "dimension": "work", "response": "disagree",
                           "reason": "we always have only two staff, keep it simple"})
    assert reply["remembered_id"]
    later = ui.run({"planner": "collaborative", "data_source": "synthetic"}, {})
    assert later["remembered_applied"], "a standing rule must come back next time"
    assert later["policy"].get("switch_penalty_eur", 0) > 0
    remembered = ui.list_remembered({})["remembered"]
    assert remembered[0]["said"] == "we always have only two staff, keep it simple"
    assert ui.forget_remembered({"everyone": True})["forgotten"] >= 1
    again = ui.run({"planner": "collaborative", "data_source": "synthetic"}, {})
    assert not again["remembered_applied"]


def test_a_one_off_reason_is_not_applied_automatically(ui):
    ui.forget_remembered({"everyone": True})
    run = ui.run({"planner": "collaborative", "data_source": "synthetic"}, {})
    ui.deliberate({**_ref(run), "dimension": "work", "response": "disagree",
                   "reason": "CHP maintenance 8-14"})
    later = ui.run({"planner": "collaborative", "data_source": "synthetic"}, {})
    assert not later["remembered_applied"]
    assert not later["policy"].get("avoid_chp_hours")
    ui.forget_remembered({"everyone": True})


def test_memory_can_be_switched_off_for_a_run(ui):
    ui.forget_remembered({"everyone": True})
    run = ui.run({"planner": "collaborative", "data_source": "synthetic"}, {})
    ui.deliberate({**_ref(run), "dimension": "work", "response": "disagree",
                   "reason": "we never have more than two staff"})
    later = ui.run({"planner": "collaborative", "data_source": "synthetic"}, {"use_memory": False})
    assert not later["remembered_applied"]
    ui.forget_remembered({"everyone": True})


# --- work, goals and the grid ------------------------------------------------------------


def test_switches_are_counted_and_cost_money_when_asked(hub, conditions):
    plan = flat_plan("2023-01-15", heat_source="boiler", lighting_level=1.0)
    alternating = dataclasses.replace(plan, intervals=tuple(
        dataclasses.replace(i, heat_source="chp" if i.hour % 2 else "boiler", chp_mode="heat_led"
                            if i.hour % 2 else "off") for i in plan.intervals))
    assert score_plan(plan, hub, conditions).switches == 0
    score = score_plan(alternating, hub, conditions)
    assert score.switches >= 20
    # The penalty only ranks plans that pass the hard limits; compare it on one.
    steady = dataclasses.replace(score_plan(plan, hub, conditions), feasible=True, violations=())
    busy = dataclasses.replace(steady, switches=10)
    assert busy.objective("balanced") == steady.objective("balanced")
    assert busy.objective("balanced", switch_penalty_eur=60.0) > steady.objective(
        "balanced", switch_penalty_eur=60.0)


def test_work_metrics_are_concrete():
    rows = [{"hour": h, "heat_source": "chp" if 8 <= h < 12 else "boiler", "battery": "idle",
             "chp_running": 8 <= h < 12 or h == 23, "chp_mode": "off", "lighting_level": 0}
            for h in range(24)]
    work = work_metrics(rows, rows)
    assert work["chp_hours"] == 5 and work["chp_night_hours"] == 1
    assert work["chp_starts"] == 2 and work["switches"] >= 2
    assert work["hours_changed_vs_normal"] == 0


def test_goals_need_a_name_and_known_metric_and_are_evaluated():
    goals = clean_goals([{"name": "Quiet", "metric": "switches", "op": "<=", "value": 4},
                         {"name": "", "metric": "switches", "value": 1},
                         {"name": "Bad", "metric": "secret", "value": 1}])
    assert [g["name"] for g in goals] == ["Quiet"]
    rows, targets = evaluate_goals(goals, {"budget_eur": 100.0, "max_import_kw": None},
                                   {"net_cost_eur": 120.0}, {"switches": 3})
    assert rows[0]["met"] is True
    assert targets == [{"key": "budget_eur", "value": 100.0, "actual": 120.0, "op": "<=",
                        "met": False}]


def test_a_grower_import_limit_is_a_hard_rule(ui):
    run = ui.run({"planner": "collaborative", "data_source": "synthetic"},
                 {"import_caps": {17: 1000, 18: 1000}})
    assert all(row["import_limit_kw"] <= 1000 for row in run["plan"] if row["hour"] in (17, 18))
    assert run["grid"]["within_contract"] is run["accepted"] or run["accepted"]
    if run["accepted"]:
        assert all(row["grid_import_kw"] <= 1000 + 1e-6 for row in run["plan"]
                   if row["hour"] in (17, 18))


def test_run_reports_work_grid_storage_and_targets(ui):
    run = ui.run({"planner": "collaborative", "data_source": "synthetic"},
                 {"targets": {"budget_eur": 1_000_000},
                  "goals": [{"name": "Few switches", "metric": "switches", "op": "<=",
                             "value": 50}]})
    assert set(run["work"]) >= {"switches", "chp_hours", "chp_night_hours"}
    assert run["grid"]["contract_type"] in CONTRACT_TYPES
    assert run["storage"]["battery_kwh"] > 0
    assert run["targets"][0]["met"] and run["goals"][0]["met"]
    row = run["plan"][12]
    assert {"battery_soc_kwh", "buffer_level_kwh", "grid_import_kw", "import_limit_kw"} <= set(row)


def test_week_outlook_estimates_seven_days(ui):
    week = ui.week_outlook({"overrides": {"data_source": "synthetic"}, "policy": {}})
    assert len(week["days"]) == 7
    assert week["cost_eur"] == pytest.approx(sum(d["cost_eur"] for d in week["days"]), abs=0.1)


# --- explanation graph and chat --------------------------------------------------------------


def test_factor_graph_ranks_what_the_plan_leans_on(hub, conditions):
    result = explain_factors(hub, conditions, date="2023-01-15", policy={"priority": "cost"})
    bars = result["bars"]
    assert {b["factor"] for b in bars} == {"price", "heat", "sun", "gas", "grid", "choices"}
    counts = [len(b["changed_hours"]) for b in bars]
    assert counts == sorted(counts, reverse=True)
    assert all(0 <= b["share"] <= 1 for b in bars)


def test_offline_assistant_answers_from_the_plan(ui):
    run = ui.run({"planner": "collaborative", "data_source": "synthetic"}, {})
    hour = answer("Why at 18:00?", run, language="en")
    assert "18:00" in hour and "ct/kWh" in hour
    assert "battery" in answer("What does the battery do?", run).lower()
    assert "WKK" in answer("Wanneer draait de WKK?", run, language="nl")
    assert "eerder" in answer("Wat onthoud je?", run, language="nl", remembered=["x"])
    assert answer("hello", {"plan": []}).startswith("Build a plan first")


def test_chat_falls_back_to_the_offline_assistant(ui):
    run = ui.run({"planner": "collaborative", "data_source": "synthetic",
                  "llm_provider": "ollama", "llm_base_url": "http://127.0.0.1:9"}, {})
    reply = ui.chat({**_ref(run), "question": "What does the battery do?"})
    assert reply["answer"]
    with pytest.raises(ApiError):
        ui.chat({**_ref(run), "question": "   "})


# --- pages ----------------------------------------------------------------------------------


def test_admin_page_is_served_and_wired():
    html = (static_dir() / "admin.html").read_text(encoding="utf-8")
    script = (static_dir() / "admin.js").read_text(encoding="utf-8")
    for button_id in re.findall(r'<button[^>]*\bid="([^"]+)"', html):
        assert f'$("{button_id}").addEventListener' in script, button_id
    for path in ("/api/workshop", "/api/scenarios", "/api/scenarios/delete", "/api/memory",
                 "/api/memory/forget"):
        assert f'"{path}' in script or f"`{path}" in script, path


def test_grower_page_uses_the_workshop_endpoints():
    script = (static_dir() / "demo.js").read_text(encoding="utf-8")
    for path in ("/api/recommend", "/api/explain-factors", "/api/chat", "/api/week-outlook",
                 "/api/workshop"):
        assert path in script, path
    assert "innerHTML" not in script, "the grower page builds every node; no HTML strings"


def test_both_languages_have_the_same_keys():
    en = json.loads((static_dir() / "demo.en.json").read_text(encoding="utf-8"))
    nl = json.loads((static_dir() / "demo.nl.json").read_text(encoding="utf-8"))
    assert set(en) == set(nl)


def test_an_infeasible_seed_is_repaired_with_the_chp(conditions):
    """A boiler too small for the night must not push the grower onto the fallback."""
    from kasflex.controllers.base import PlanningContext
    from kasflex.controllers.collaborative import _repair_seed
    from kasflex.controllers.rule_based import RuleBasedPlanner

    hub = EnergyHub()
    peak = max(c.heat_demand_kw for c in conditions)
    small = dataclasses.replace(hub, boiler=dataclasses.replace(
        hub.boiler, thermal_capacity_kw=peak * 0.8))
    context = PlanningContext(date="2023-01-15", forecast=conditions, hub=small)
    seed = RuleBasedPlanner().plan(context)
    repaired = _repair_seed(seed, context, ())
    short = {c.hour for c in conditions if c.heat_demand_kw > small.boiler.thermal_capacity_kw}
    if repaired is seed:
        pytest.skip("the CHP cannot cover this demand either; the seed is left as it was")
    assert all(iv.heat_source == "chp" for iv in repaired.intervals if iv.hour in short)
    assert score_plan(repaired, small, conditions).feasible
    # Hours the grower blocked stay untouched.
    blocked = _repair_seed(seed, context, tuple(short))
    assert blocked is seed


# --- documents for the chat, heating targets -------------------------------------------------


def test_documents_are_found_by_their_words_in_dutch_and_english(tmp_path):
    from kasflex.documents import DocumentStore, builtin_documents, search

    nl = search("Wat mag ik met een tijdsblokgebonden contract?", builtin_documents("nl"))
    assert nl and "Tijdsblokgebonden" in nl[0]["passage"]
    en = search("what does a time-block right allow", builtin_documents("en"))
    assert en and "Time-block" in en[0]["passage"]
    assert search("why does the CHP run at 18:00", builtin_documents("en")) == []

    store = DocumentStore(tmp_path)
    saved = store.save("Site notes", "Crew starts at 7.\n\nThe CHP is serviced every first Monday.")
    hits = search("When is the CHP serviced?", store.all("en"))
    assert hits[0]["title"] == "Site notes" and "first Monday" in hits[0]["passage"]
    with pytest.raises(ValueError):
        store.save("", "text")
    assert store.delete(saved.id) and not store.delete(saved.id)
    assert not store.delete("../../etc")


def test_chat_quotes_a_document_and_names_it(ui, tmp_path):
    from kasflex.documents import DocumentStore

    ui.documents = DocumentStore(tmp_path / "docs")
    ui.save_document({"title": "Site notes", "text": "The CHP is serviced every first Monday."})
    run = ui.run({"planner": "collaborative", "data_source": "synthetic",
                  "llm_provider": "ollama", "llm_base_url": "http://127.0.0.1:9"}, {})
    reply = ui.chat({**_ref(run), "question": "When is the CHP serviced?"})
    assert "first Monday" in reply["answer"]
    assert reply["sources"][0]["title"] == "Site notes"
    listed = ui.list_documents("en")["documents"]
    assert {d["title"] for d in listed} >= {"Grid contracts", "Site notes"}


def test_a_warmer_heating_target_costs_more_heat(ui):
    base = ui.run({"planner": "collaborative", "data_source": "synthetic"}, {})
    warm = ui.run({"planner": "collaborative", "data_source": "synthetic"},
                  {"targets": {"heat_day_c": 22, "heat_night_c": 19}})
    assert warm["metrics"]["net_cost_eur"] > base["metrics"]["net_cost_eur"]
    rows = {t["key"]: t for t in warm["targets"]}
    assert rows["heat_day_c"]["value"] == 22 and rows["heat_day_c"]["met"]
    reply = answer("Why lower the temperature this week?", warm, language="en")
    assert "22 °C" in reply and "19 °C" in reply


def test_heating_targets_are_kept_in_a_sane_range():
    from kasflex.ui.workshop_api import clean_targets

    cleaned = clean_targets({"heat_day_c": 80, "heat_night_c": "x"})
    assert cleaned["heat_day_c"] == 30.0 and cleaned["heat_night_c"] is None


def test_charts_never_put_two_scales_on_one_plot():
    """dataviz rule: price and temperature are small multiples, not a dual axis."""
    script = (static_dir() / "demo.js").read_text(encoding="utf-8")
    assert "line-temp" not in script and "tick temp" not in script
    css = (static_dir() / "demo.css").read_text(encoding="utf-8")
    for slot in ("--s-buffer", "--s-chp", "--s-boiler", "--s-lamps", "--s-battery", "--s-grid"):
        assert slot in css


# --- the settings lock ----------------------------------------------------------------------


def test_admin_password_unlocks_settings_and_wrong_ones_do_not(monkeypatch):
    from kasflex.admin_auth import AdminGate

    gate = AdminGate()
    assert gate.login("wrong") is None
    token = gate.login("admin99")
    assert token and gate.check(token) and not gate.check("made-up")
    gate.logout(token)
    assert not gate.check(token)
    monkeypatch.setenv("KASFLEX_ADMIN_PASSWORD", "another")
    assert gate.login("admin99") is None and gate.login("another")


def test_site_settings_change_the_base_and_survive_a_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("KASFLEX_HOME", str(tmp_path))
    server = UiServer(config_path=CONFIG)
    saved = server.save_site_settings({"values": {"grid_contract_type": "firm",
                                                  "hub.contract.import_limit_kw": 4500}})
    assert server.base.grid_contract_type == "firm"
    assert server.base.hub.contract.import_limit_kw == 4500
    assert {f["path"] for f in saved["fields"]} >= {"llm_provider", "grid_contract_type"}
    again = UiServer(config_path=CONFIG)
    assert again.base.hub.contract.import_limit_kw == 4500
    with pytest.raises(ApiError):
        server.save_site_settings({"values": {"checker.enabled": False}})
    with pytest.raises(ApiError):
        server.save_site_settings({"values": {"grid_contract_type": "nonsense"}})
    assert server.base.grid_contract_type == "firm"  # a refused save changes nothing
    server.save_site_settings({"values": {"grid_contract_type": "",
                                          "hub.contract.import_limit_kw": ""}})
    assert server.base.hub.contract.import_limit_kw == server.file_base.hub.contract.import_limit_kw


def test_settings_endpoints_are_locked_over_http(tmp_path, monkeypatch):
    import threading
    import urllib.error
    import urllib.request

    from kasflex.ui.server import serve

    monkeypatch.setenv("KASFLEX_HOME", str(tmp_path))
    server = serve(config_path=CONFIG, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = f"http://127.0.0.1:{server.server_address[1]}"

    def post(path, body, token=""):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-KasFlex-Admin"] = token
        request = urllib.request.Request(root + path, json.dumps(body).encode(), headers)
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())

    try:
        for path, body in (("/api/site-settings", {"values": {}}),
                           ("/api/workshop", {"version": "ai"}),
                           ("/api/scenarios/delete", {"scenario_id": "x"}),
                           ("/api/documents/save", {"title": "a", "text": "b"}),
                           ("/api/memory/forget", {"everyone": True}),
                           ("/api/memory", {"everyone": True})):
            with pytest.raises(urllib.error.HTTPError) as exc:
                post(path, body)
            assert exc.value.code == 401, path
        with pytest.raises(urllib.error.HTTPError) as exc:
            post("/api/admin/login", {"password": "nope"})
        assert exc.value.code == 401
        token = post("/api/admin/login", {"password": "admin99"})["token"]
        assert post("/api/workshop", {"version": "ai"}, token)["version"] == "ai"
        assert post("/api/site-settings", {"values": {"gas_price_eur_kwh": 0.04}}, token)
        post("/api/admin/logout", {}, token)
        with pytest.raises(urllib.error.HTTPError):
            post("/api/workshop", {"version": "ai"}, token)
        # What growers use stays open.
        assert post("/api/memory", {"overrides": {}})["remembered"] == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_grower_page_has_a_locked_settings_menu_and_no_open_model_switch():
    html = (static_dir() / "demo.html").read_text(encoding="utf-8")
    assert 'id="open-settings"' in html and 'id="settings-password"' in html
    assert 'type="password"' in html
    assert 'id="model-select"' not in html
    topbar = html.split("</header>")[0]
    assert 'id="input-mode"' not in topbar, "data mode belongs behind the lock"


# --- audit regressions (docs/audits/2026-10-01) -------------------------------------------


@pytest.fixture
def live(tmp_path, monkeypatch):
    import threading

    import yaml

    from kasflex.ui.server import serve

    scenario = yaml.safe_load(open(CONFIG, encoding="utf-8"))
    scenario["consent_version"] = "audit-v1"
    path = tmp_path / "study.yaml"
    path.write_text(yaml.safe_dump(scenario), encoding="utf-8")
    monkeypatch.setenv("KASFLEX_HOME", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    server = serve(config_path=str(path), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.root = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _call(server, path, body=None, token=""):
    import urllib.error
    import urllib.request

    headers = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        headers["X-KasFlex-Admin"] = token
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(urllib.request.Request(server.root + path, data, headers),
                                    timeout=30) as response:
            return response.status, json.loads(response.read() or b"{}"), response.headers
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}"), exc.headers


def _token(server):
    return _call(server, "/api/admin/login", {"password": "admin99"})[1]["token"]


def test_audit_f1_research_data_needs_the_password(live):
    """Other participants' words and the research bundle are not for participants."""
    for path in ("/api/preferences", "/api/export/fair", "/api/deliberations",
                 "/api/reliance", "/api/elicitations", "/api/conflicts",
                 "/api/conversation/x", "/api/reviews", "/api/reviews/x"):
        assert _call(live, path)[0] == 401, path
    token = _token(live)
    assert _call(live, "/api/preferences", token=token)[0] == 200
    assert _call(live, "/api/deliberations", token=token)[0] == 200


def test_audit_f2_a_request_cannot_redirect_the_ai_and_its_key(live):
    """The stored key goes wherever llm_base_url points: only the password may set it."""
    for field, value in (("llm_base_url", "http://127.0.0.1:9/steal"),
                         ("llm_provider", "openai"), ("llm_model", "x"),
                         ("hub.contract.import_limit_kw", 100)):
        status, _, _ = _call(live, "/api/run", {"overrides": {field: value}, "policy": {}})
        assert status == 401, field
    assert _call(live, "/api/models/test",
                 {"provider": "openai", "model": "x", "base_url": "http://127.0.0.1:9/"})[0] == 401
    # What the grower page itself sends still works without the password.
    status, run, _ = _call(live, "/api/run", {"overrides": {
        "planner": "collaborative", "data_source": "synthetic", "condition": "collab",
        "checker.enabled": True, "language": "nl"}, "policy": {}})
    assert status == 200 and run["accepted"] is not None


def test_audit_f3_only_the_participant_can_withdraw_or_change_their_consent(live):
    granted = _call(live, "/api/consent", {"participant_id": "P002", "version": "audit-v1",
                                           "scopes": {"research": True}})[1]
    key = granted["withdraw_key"]
    assert key
    # Someone else, guessing the pseudonym: refused.
    assert _call(live, "/api/consent/withdraw", {"participant_id": "P002"})[0] == 401
    assert _call(live, "/api/consent/withdraw",
                 {"participant_id": "P002", "withdraw_key": "guess"})[0] == 401
    assert _call(live, "/api/consent", {"participant_id": "P002", "version": "audit-v1",
                                        "scopes": {"research": True, "quotes": True}})[0] == 409
    # The participant, with their key: allowed; re-consenting keeps the same key.
    again = _call(live, "/api/consent", {"participant_id": "P002", "version": "audit-v1",
                                         "scopes": {"research": True}, "withdraw_key": key})
    assert again[0] == 200 and again[1]["withdraw_key"] == ""
    status, result, _ = _call(live, "/api/consent/withdraw",
                              {"participant_id": "P002", "withdraw_key": key})
    assert status == 200 and result["active"] is False
    # The researcher can always help.
    _call(live, "/api/consent", {"participant_id": "P003", "version": "audit-v1",
                                 "scopes": {"research": True}})
    assert _call(live, "/api/consent/withdraw", {"participant_id": "P003"},
                 token=_token(live))[0] == 200


def test_audit_f4_guessing_the_password_is_slowed_then_stopped(live):
    for _ in range(5):
        assert _call(live, "/api/admin/login", {"password": "wrong"})[0] == 401
    status, body, _ = _call(live, "/api/admin/login", {"password": "admin99"})
    assert status == 429 and "Too many" in body["error"]


def test_audit_f5_errors_and_headers_do_not_describe_the_installation(live):
    _, _, headers = _call(live, "/api/settings")
    assert "Python" not in headers.get("Server", "")
    status, body, _ = _call(live, "/api/run", {"overrides": {"seed": "not-a-number"},
                                               "policy": "not-a-dict"})
    assert status in (400, 422, 500)
    assert "traceback" not in body and "File \"" not in json.dumps(body)


def test_audit_a11y_controls_have_names_and_live_regions():
    html = (static_dir() / "demo.html").read_text(encoding="utf-8")
    for needle in ('id="goal-metric" aria-label=', 'id="goal-op" aria-label=',
                   'id="goal-value" type="number" step="any" inputmode="decimal" aria-label=',
                   'id="toast" class="toast" role="status"',
                   'id="error" class="error" role="alert"'):
        assert needle in html, needle
    script = (static_dir() / "demo.js").read_text(encoding="utf-8")
    assert 'setAttribute("aria-pressed"' in script and "prefers-reduced-motion" in script


# --- remembered reasons in similar situations, plain checker text, Word documents ---------


def test_a_one_off_reason_can_be_applied_again_by_choice(ui):
    ui.forget_remembered({"everyone": True})
    run = ui.run({"planner": "collaborative", "data_source": "synthetic"}, {})
    reply = ui.deliberate({**_ref(run), "dimension": "work", "response": "disagree",
                           "reason": "only two staff tomorrow"})
    pref_id = reply["remembered_id"]
    advice = ui.recommendation({"overrides": {"data_source": "synthetic"}, "policy": {}})
    offered = {item["pref_id"]: item for item in advice["remembered"]}
    assert pref_id in offered and offered[pref_id]["applied"] is False
    assert "similar" in offered[pref_id]
    later = ui.run({"planner": "collaborative", "data_source": "synthetic"},
                   {"reuse_memory": [pref_id]})
    assert later["policy"].get("switch_penalty_eur", 0) > 0
    assert later["remembered_applied"][0]["said"] == "only two staff tomorrow"
    ui.forget_remembered({"everyone": True})


def test_similar_situations_are_named_plainly():
    import types

    from kasflex.ui.workshop_api import similar_situation

    config = types.SimpleNamespace(date="2023-01-17", hub=EnergyHub())
    said_monday = types.SimpleNamespace(created_at="2023-01-16T08:00:00+00:00",
                                        scope={"effects": {}})
    assert similar_situation(said_monday, config, []) == "weekday"  # about Tuesday, again Tuesday
    cold = types.SimpleNamespace(created_at="2023-01-01T08:00:00+00:00",
                                 scope={"effects": {"night_temp_c": -6}})
    night = [types.SimpleNamespace(hour=2, outdoor_temp_c=-3.0)]
    assert similar_situation(cold, config, night) == "cold"


def test_checker_messages_are_plain_and_in_the_growers_language():
    from kasflex.checker.verdict import plain_message

    v = {"constraint": "grid.import_limit", "actual": 4100.4, "bound": 1500, "unit": "kW",
         "hour": 17, "message": "raw"}
    assert plain_message(v, "nl") == (
        "Om 17:00: 4.100 kW van het net, het contract staat 1.500 kW toe.")
    assert plain_message(v, "en").startswith("At 17:00: 4,100 kW from the grid")
    assert plain_message({"constraint": "unknown", "message": "raw"}, "nl") == "raw"


def test_run_violations_carry_plain_text(ui):
    run = ui.run({"planner": "collaborative", "data_source": "synthetic", "language": "nl"},
                 {"targets": {"max_import_kw": 300}})
    assert run["violations"], "a 0.3 MW cap must be refused"
    assert all(v["plain"] for v in run["violations"])


def _docx(paragraphs, extra=b""):
    import io
    import zipfile

    body = "".join(f'<w:p><w:r><w:t>{p}</w:t></w:r></w:p>' for p in paragraphs)
    xml = (extra + b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
           b'2006/main"><w:body>' + body.encode() + b"</w:body></w:document>")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def test_word_documents_become_chat_documents(ui, tmp_path):
    import base64

    from kasflex.documents import DocumentStore, docx_text, search

    assert docx_text(_docx(["Netcontract Westland", "Tijdsblok 22-07 uur volledig vermogen"])) \
        == "Netcontract Westland\n\nTijdsblok 22-07 uur volledig vermogen"
    with pytest.raises(ValueError):
        docx_text(b"not a zip")
    with pytest.raises(ValueError):  # entity expansion refused
        docx_text(_docx(["x"], extra=b'<!DOCTYPE d [<!ENTITY a "aaaa">]>'))

    ui.documents = DocumentStore(tmp_path / "docs")
    encoded = base64.b64encode(_docx(["De WKK krijgt onderhoud op de eerste maandag."])).decode()
    ui.save_document({"title": "Bedrijfsnotities", "filename": "notes.docx",
                      "file_base64": encoded})
    hits = search("Wanneer krijgt de WKK onderhoud?", ui.documents.all("nl"))
    assert hits[0]["title"] == "Bedrijfsnotities"
    with pytest.raises(ApiError):
        ui.save_document({"title": "x", "filename": "scan.pdf", "file_base64": encoded})


def test_the_browser_may_send_only_the_word_text_part():
    import io
    import zipfile

    from kasflex.documents import text_from_upload

    with zipfile.ZipFile(io.BytesIO(_docx(["Alleen de tekst"]))) as archive:
        xml = archive.read("word/document.xml").decode()
    assert text_from_upload("notes.docx", docx_xml=xml) == "Alleen de tekst"
    with pytest.raises(ValueError):
        text_from_upload("notes.docx", docx_xml="<!DOCTYPE x [<!ENTITY a 'b'>]><x/>")
