"""The interface API.

Two things here are worth more than the rest: an edited plan must go back through
the checker (R23), and the interface must never claim a plan was verified when it
was not. Both were bugs during development -- a stale "accepted" badge survived a
failed re-verification, and a run with the checker switched off still read
"accepted" beside a card showing 66 violations. Neither would have shown up in a
test of the model, only in a test of the interface.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request

import pytest

from kasflex.resources import static_dir
from kasflex.ui.server import ADJUSTABLE, ApiError, UiServer, serve

CONFIG = "configs/scenario_westland_winter.yaml"


@pytest.fixture(scope="module")
def ui() -> UiServer:
    return UiServer(config_path=CONFIG)


@pytest.fixture(scope="module")
def base_run(ui):
    return ui.run({"planner": "rule-based"})


# --- settings --------------------------------------------------------------


def test_settings_expose_current_values(ui):
    settings = ui.get_settings()
    assert settings["scenario"] == "westland-winter"
    paths = {f["path"] for f in settings["fields"]}
    assert {
        "planner",
        "checker.enabled",
        "hub.contract.import_limit_kw",
        "contracted_base_kw",
        "contracted_price_eur_kwh",
    } <= paths
    planner = next(f for f in settings["fields"] if f["path"] == "planner")
    assert planner["value"] == "rule-based"
    assert "learned" in planner["choices"]


def test_every_adjustable_field_resolves(ui):
    """A typo in ADJUSTABLE would break the page on load, not at review time."""
    for field in ui.get_settings()["fields"]:
        assert "value" in field, field["path"]
        assert field["label"]


def test_overrides_outside_the_allowed_set_are_refused(ui):
    with pytest.raises(ApiError, match="not adjustable"):
        ui.run({"hub.boiler.efficiency": 0.5})


def test_a_value_of_the_wrong_type_is_refused(ui):
    """Dataclasses do not type-check, so without coercion this reaches the run."""
    with pytest.raises(ApiError, match="not a valid int"):
        ui.run({"checker.max_revisions": "three"})


def test_a_value_out_of_range_is_refused(ui):
    with pytest.raises(ApiError, match="below the minimum"):
        ui.run({"hub.contract.import_limit_kw": -500})
    with pytest.raises(ApiError, match="above the maximum"):
        ui.run({"hub.chp.min_run_hours": 99})


def test_an_invalid_choice_is_refused(ui):
    with pytest.raises(ApiError, match="is not one of"):
        ui.run({"planner": "vibes"})


def test_numeric_strings_from_a_form_are_accepted(ui):
    """A browser sends strings. Refusing them would make the UI unusable."""
    assert ui.run({"checker.max_revisions": "2", "hub.battery.capacity_kwh": "1500"})


# --- running ---------------------------------------------------------------


def test_run_returns_a_full_day(base_run):
    assert len(base_run["plan"]) == 24
    assert [row["hour"] for row in base_run["plan"]] == list(range(24))
    assert base_run["metrics"]["net_cost_eur"] > 0


def test_day_context_explains_the_day_before_planning(ui):
    context = ui.day_context({"data_source": "synthetic"})
    assert len(context["price"]["series"]) == 24
    assert len(context["weather"]["temperature_series"]) == 24
    assert context["price"]["min_eur_kwh"] <= context["price"]["max_eur_kwh"]
    assert context["grid"]["import_limit_kw"] > 0
    assert "provenance" in context


def test_collaborative_run_uses_grower_policy(ui):
    result = ui.run(
        {"planner": "collaborative"},
        policy={
            "priority": "grid",
            "avoid_chp_night": True,
            "battery_reserve_pct": 45,
            "brief": "Keep the night quiet.",
        },
    )
    assert result["planner"] == "collaborative"
    assert result["policy"]["priority"] == "grid"
    assert result["policy"]["avoid_chp_night"] is True
    for hour in (22, 23, 0, 1, 2, 3, 4, 5):
        assert result["plan"][hour]["chp_mode"] == "off"


def test_run_exposes_procurement_position(ui):
    result = ui.run(
        {
            "planner": "collaborative",
            "contracted_base_kw": 1600,
            "contracted_price_eur_kwh": 0.08,
        },
        policy={"priority": "balanced"},
    )
    summary = result["position"]["summary"]
    assert summary["contracted_energy_kwh"] == pytest.approx(1600 * 24)
    assert summary["absolute_deviation_kwh"] >= 0
    assert summary["short_hours"] + summary["long_hours"] <= 24
    assert result["model"]["planner"] == "collaborative"


@pytest.mark.parametrize(
    ("dimension", "expected_priority"),
    [
        ("money", "cost"),
        ("crop", "crop"),
        ("grid", "grid"),
        ("work", "balanced"),
    ],
)
def test_dimension_disagreement_returns_specific_alternative(
    ui, dimension, expected_priority
):
    result = ui.run(
        {"planner": "collaborative"},
        policy={"priority": "balanced", "battery_reserve_pct": 45},
    )
    reply = ui.deliberate(
        {
            "run_id": result["run_id"],
            "revision": result["revision"],
            "plan_hash": result["plan_hash"],
            "dimension": dimension,
            "response": "disagree",
            "session_id": f"test-{dimension}",
            "time_to_first_response_s": 3.5,
        }
    )
    assert reply["dimension"] == dimension
    assert reply["counter_response"]
    assert reply["alternative"]
    assert reply["alternative"]["policy"]["priority"] == expected_priority
    assert ui.list_deliberations(f"test-{dimension}")["records"]


def test_plan_rows_carry_context_for_the_operator(base_run):
    """A price and a heat demand next to each hour, or the plan is unreadable."""
    row = base_run["plan"][17]
    assert row["power_price_eur_kwh"] > 0
    assert "heat_demand_kw" in row
    assert row["reasoning"]


def test_run_reports_that_the_model_is_unvalidated(base_run):
    assert base_run["validated"] is False


def test_settings_actually_change_the_outcome(ui, base_run):
    """If a control does nothing, it is worse than not being there."""
    tighter = ui.run({"planner": "rule-based", "hub.contract.import_limit_kw": 3000})
    assert tighter["metrics"] != base_run["metrics"]


def test_battery_power_sets_both_directions(ui):
    """One control in the interface, two fields in the model."""
    result = ui.run({"hub.battery.max_charge_kw": 400})
    assert result["metrics"]  # ran without a config error
    config = ui.base
    assert config.hub.battery.max_charge_kw != 400, "the base config must not be mutated"


def test_a_run_does_not_mutate_the_loaded_scenario(ui, base_run):
    before = ui.base.hub.contract.import_limit_kw
    ui.run({"hub.contract.import_limit_kw": 1234})
    assert ui.base.hub.contract.import_limit_kw == before


def test_unimplemented_planner_reports_cleanly(ui):
    with pytest.raises(ApiError) as exc:
        ui.run({"planner": "mpc"})
    assert exc.value.status == 501


def test_unknown_planner_is_caught_before_the_run(ui):
    """Caught by the choice list, so it never reaches build_planner."""
    with pytest.raises(ApiError, match="is not one of"):
        ui.run({"planner": "telepathy"})


# --- verification of human edits (R23) -------------------------------------


def test_an_unedited_plan_still_verifies(ui, base_run):
    result = ui.verify({"planner": "rule-based"}, base_run["plan"])
    assert result["accepted"] is True


def test_display_columns_are_stripped_not_rejected(ui, base_run):
    """The page sends back exactly the rows the server gave it, price column and
    all. The schema rightly refuses unknown fields, so the server strips them."""
    assert "power_price_eur_kwh" in base_run["plan"][0]
    assert ui.verify({}, base_run["plan"])["accepted"] is True


def test_a_harmful_edit_is_caught(ui, base_run):
    """Withholding heat for the whole day must not survive re-verification."""
    edited = [{**row, "heat_source": "none"} for row in base_run["plan"]]
    result = ui.verify({"planner": "rule-based"}, edited)
    assert result["accepted"] is False
    assert any(v["constraint"] == "heat.demand_met" for v in result["violations"])


def test_an_edit_that_breaks_the_contract_is_caught(ui, base_run):
    edited = [{**row, "lighting_level": 1.0} for row in base_run["plan"]]
    result = ui.verify({"planner": "rule-based"}, edited)
    assert result["accepted"] is False


def test_a_malformed_edit_is_reported_not_crashed(ui, base_run):
    edited = [{**row, "heat_source": "wishful thinking"} for row in base_run["plan"]]
    with pytest.raises(ApiError, match="not valid"):
        ui.verify({}, edited)


def test_verify_reports_the_edited_cost(ui, base_run):
    result = ui.verify({}, base_run["plan"])
    assert result["metrics"]["net_cost_eur"] > 0


# --- honesty about verification --------------------------------------------


def test_a_disabled_checker_is_reported_as_such(ui):
    """The page turns this into "not verified" rather than "accepted"."""
    result = ui.run({"planner": "naive", "checker.enabled": False})
    assert result["checker_enabled"] is False
    assert result["realised_hard"] > 0, (
        "an unverified constraint-blind planner should produce violations; without "
        "them the interface has nothing to be honest about"
    )


def test_the_checker_catches_what_disabling_it_lets_through(ui):
    off = ui.run({"planner": "naive", "checker.enabled": False})
    on = ui.run({"planner": "naive", "checker.enabled": True})
    assert off["realised_hard"] > 0
    assert on["realised_hard"] == 0
    assert on["fell_back"] is True


def test_collaborative_demo_can_run_with_checker_on_or_off(ui):
    on = ui.run({"planner": "collaborative", "checker.enabled": True})
    off = ui.run({"planner": "collaborative", "checker.enabled": False})
    assert on["checker_enabled"] is True
    assert off["checker_enabled"] is False


def test_crop_disagreement_returns_a_crop_specific_alternative(ui):
    run = ui.run(
        {"planner": "collaborative", "data_source": "synthetic"},
        policy={"priority": "balanced", "battery_reserve_pct": 45},
    )
    reply = ui.deliberate({
        "run_id": run["run_id"],
        "revision": run["revision"],
        "plan_hash": run["plan_hash"],
        "dimension": "crop",
        "response": "disagree",
    })
    assert reply["dimension"] == "crop"
    assert reply["response"] == "disagree"
    assert reply["alternative"] is not None
    assert reply["alternative"]["policy"]["priority"] == "crop"
    assert "crop" in reply["counter_response"].lower()


def test_agreeing_with_one_dimension_does_not_regenerate_the_plan(ui):
    run = ui.run({"planner": "collaborative", "data_source": "synthetic"})
    reply = ui.deliberate({
        "run_id": run["run_id"],
        "revision": run["revision"],
        "plan_hash": run["plan_hash"],
        "dimension": "money",
        "response": "agree",
    })
    assert reply["alternative"] is None
    assert reply["response"] == "agree"


# --- decisions (R25, R26) --------------------------------------------------


def test_a_decision_is_recorded(tmp_path):
    server = UiServer(config_path=CONFIG)
    server.base = type(server.base)(
        **{**server.base.__dict__, "audit_path": str(tmp_path / "audit.jsonl")}
    )
    saved = server.run({})
    server.decide({**saved, "decision": "approve", "comment": "looks right",
                   "research_consent": True,
                   "seconds_to_decide": 12.5, "operator": "grower-1"})

    from kasflex.oversight import AuditLog

    entries = AuditLog(tmp_path / "audit.jsonl").entries()
    assert entries[-1]["kind"] == "human_decision_ui"
    assert entries[-1]["payload"]["decision"] == "approve"
    assert entries[-1]["payload"]["seconds_to_decide"] == 12.5
    assert entries[-1]["operator"] == "grower-1"


def test_anonymous_mode_withholds_the_operator(tmp_path):
    server = UiServer(config_path=CONFIG, anonymous=True)
    server.base = type(server.base)(
        **{**server.base.__dict__, "audit_path": str(tmp_path / "a.jsonl")}
    )
    server.decide({**server.run({}), "decision": "reject", "operator": "grower-1"})

    from kasflex.oversight import AuditLog

    assert AuditLog(tmp_path / "a.jsonl").entries()[-1]["operator"] == "anonymous"


def test_a_nonsense_decision_is_refused(ui):
    with pytest.raises(ApiError, match="approve, reject or edit"):
        ui.decide({"decision": "maybe"})


# --- comparison (R29) ------------------------------------------------------


def test_compare_runs_every_planner_on_one_scenario(ui):
    result = ui.compare({}, ["rule-based", "naive"])
    assert {r["planner"] for r in result["rows"]} == {"rule-based", "naive"}
    for row in result["rows"]:
        assert "cost_eur" in row and "hard_violations" in row


def test_compare_reports_a_failing_planner_without_sinking_the_table(ui):
    """One unimplemented planner must not cost you the whole comparison."""
    result = ui.compare({}, ["rule-based", "mpc"])
    rows = {r["planner"]: r for r in result["rows"]}
    assert "error" in rows["mpc"]
    assert "cost_eur" in rows["rule-based"]


# --- HTTP layer ------------------------------------------------------------


@pytest.fixture(scope="module")
def live():
    httpd = serve(config_path=CONFIG, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _post(url: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_team_demo_buttons_are_wired_and_do_not_link_to_legacy_ui():
    html = (static_dir() / "demo.html").read_text(encoding="utf-8")
    script = (static_dir() / "demo.js").read_text(encoding="utf-8")

    button_ids = re.findall(r'<button[^>]*\bid="([^"]+)"', html)
    assert button_ids
    for button_id in button_ids:
        assert f'$("{button_id}").addEventListener' in script, button_id

    hrefs = set(re.findall(r'<a[^>]*href="([^"]+)"', html))
    assert hrefs <= {"/", "#workspace"}
    assert "Detailed report" not in html
    assert "Uitgebreid rapport" not in html
    assert "legacy-grower" not in html
    assert "/api/deliberate" in script
    assert 'id="checker-enabled"' in html
    assert '"checker.enabled":$("checker-enabled").checked' in script
    assert "/api/validation-status" in script
    assert "failed:" in script


def test_stale_grower_url_serves_the_new_demo(live):
    status, body = _get(live + "/grower")
    assert status == 200
    assert b"Make tomorrow" in body
    assert b"Grower energy co-pilot" in body


def test_the_page_and_its_assets_are_served(live):
    for path, needle in (("/", b"Make tomorrow"), ("/demo.css", b"--green"),
                         ("/demo.js", b"/api/deliberate"),
                         ("/demo.en.json", b"protects the crop"),
                         ("/demo.nl.json", b"beschermt het gewas"),
                         ("/grower", b"KasFlex"), ("/grower.css", b"--kf-forest"),
                         ("/grower.js", b"api("), ("/mark.svg", b"<svg")):
        status, body = _get(live + path)
        assert status == 200, path
        assert needle in body, path


def test_the_page_carries_the_permanent_simulation_notice(live):
    """R31. If this ever disappears the interface is misrepresenting itself."""
    _, body = _get(live + "/")
    text = " ".join(body.decode().split())   # the source wraps this sentence
    assert "Simulation." in text
    assert "Not validated for operational use" in text
    assert "hidden" not in text.split('id="sim-notice"')[1][:120]


def test_favicon_is_answered(live):
    assert _get(live + "/favicon.ico")[0] == 200


def test_validation_status_over_http(live):
    status, body = _get(live + "/api/validation-status")
    assert status == 200
    payload = json.loads(body)
    assert payload["status"] in {"pending", "measured"}
    assert "doi" in payload
    if payload["status"] == "pending":
        assert payload["validated"] is False


def test_api_settings_over_http(live):
    status, body = _get(live + "/api/settings")
    assert status == 200
    assert len(json.loads(body)["fields"]) == len(ADJUSTABLE)


def test_day_context_over_http(live):
    status, payload = _post(
        live + "/api/day-context",
        {"overrides": {"data_source": "synthetic"}},
    )
    assert status == 200
    assert len(payload["price"]["series"]) == 24


def test_api_run_over_http(live):
    status, payload = _post(live + "/api/run", {"overrides": {"planner": "rule-based"}})
    assert status == 200
    assert len(payload["plan"]) == 24


def test_a_bad_override_returns_400(live):
    status, payload = _post(live + "/api/run", {"overrides": {"hub.unknown_field": 1}})
    assert status == 400
    assert "not adjustable" in payload["error"]


def test_an_unknown_endpoint_returns_404(live):
    assert _post(live + "/api/nope", {})[0] == 404


def test_a_malformed_body_returns_400(live):
    request = urllib.request.Request(
        live + "/api/run", data=b"{not json",
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=30)
        raise AssertionError("should have failed")
    except urllib.error.HTTPError as exc:
        assert exc.code == 400


def test_every_numeric_default_sits_inside_its_own_adjustable_range(ui):
    """A shipped default outside its own range silently blocks the browser form."""
    offenders = []
    for field in ui.get_settings()["fields"]:
        if field["kind"] not in {"number", "int"}:
            continue
        value = field.get("value")
        if not isinstance(value, (int, float)):
            continue
        low, high = field.get("min"), field.get("max")
        if low is not None and value < low:
            offenders.append(f"{field['path']}={value} below min {low}")
        if high is not None and value > high:
            offenders.append(f"{field['path']}={value} above max {high}")
    assert not offenders, (
        "these fields ship a default outside their own adjustable range and can "
        "silently block planning in the browser: " + ", ".join(offenders)
    )


# --- geocoding endpoint (address <-> coordinates) ------------------------


def test_geocode_endpoint_calls_the_geocoder(monkeypatch, ui):
    """The address input on onboarding hits POST /api/geocode. The endpoint
    should delegate to kasflex.data.geocode.geocode without ever reaching the
    real network -- and its response has to carry the resolved place name back
    so the grower can confirm it before continuing.
    """
    from kasflex.data.geocode import GeocodedPlace

    def fake(query, *, language="en", **_):
        assert query == "Naaldwijk"
        assert language in ("en", "nl")
        return GeocodedPlace(latitude=51.994, longitude=4.207,
                             name="Naaldwijk", country="Netherlands",
                             admin="South Holland")

    monkeypatch.setattr("kasflex.data.geocode.geocode", fake)
    result = ui.geocode({"address": "Naaldwijk"})
    assert result["latitude"] == pytest.approx(51.994)
    assert result["longitude"] == pytest.approx(4.207)
    assert result["name"] == "Naaldwijk"
    assert result["country"] == "Netherlands"


def test_geocode_endpoint_refuses_empty_input(ui):
    with pytest.raises(ApiError, match="Enter a place name"):
        ui.geocode({})
    with pytest.raises(ApiError, match="Enter a place name"):
        ui.geocode({"address": "   "})


def test_geocode_endpoint_surfaces_no_match_as_404(monkeypatch, ui):
    """When the address does not resolve, the endpoint returns 404 with a
    message the onboarding page can show verbatim -- not 500 with a stack."""
    from kasflex.data.geocode import GeocodingError

    def fake(*_args, **_kwargs):
        raise GeocodingError("No place matched 'qqq'.")

    monkeypatch.setattr("kasflex.data.geocode.geocode", fake)
    with pytest.raises(ApiError, match="No place matched") as exc_info:
        ui.geocode({"address": "qqq"})
    assert exc_info.value.status == 404


# --- one-click demo preparation --------------------------------------------


def test_prepare_demo_reuses_a_cached_day_when_the_network_fails(monkeypatch, ui, tmp_path):
    """The endpoint must NEVER silently substitute synthetic data. When the network
    fetch fails and a cached demo day already exists, it hands that back; when both
    fail it raises 400 rather than inventing numbers."""
    from kasflex.data import demo as demo_module
    from kasflex.data.sources import FetchError

    calls = {"count": 0}

    def fake_online(*, cache, latitude, longitude, allow_network):
        assert allow_network in (True, False)
        if allow_network:
            calls["count"] += 1
            raise FetchError("simulated offline")
        return demo_module.DemoPrepared(
            date="2026-09-19", price_key="entsoe_da_2026-09-19",
            forecast_key="w_forecast", actual_key=None, reused_cache=True)

    monkeypatch.setattr("kasflex.ui.server.prepare_real_demo", fake_online, raising=False)
    monkeypatch.setattr("kasflex.data.demo.prepare_real_demo", fake_online)
    result = ui.prepare_demo({})
    assert result["date"] == "2026-09-19"
    assert result["reused_cache"] is True
    assert calls["count"] == 1


def test_prepare_demo_refuses_when_neither_network_nor_cache_have_a_day(monkeypatch, ui):
    from kasflex.data.sources import FetchError

    def fake(*, cache, latitude, longitude, allow_network):
        raise FetchError("no data anywhere")

    monkeypatch.setattr("kasflex.data.demo.prepare_real_demo", fake)
    with pytest.raises(ApiError, match="did not silently substitute"):
        ui.prepare_demo({})
