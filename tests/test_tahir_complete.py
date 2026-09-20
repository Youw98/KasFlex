from __future__ import annotations

from kasflex.interactions import FIELDS, InteractionLog
from kasflex.mcp_server import dispatch
from kasflex.resources import static_dir
from kasflex.ui.server import UiServer


def test_main_view_has_four_dimension_review_and_external_locales():
    html = (static_dir() / "demo.html").read_text(encoding="utf-8")
    js = (static_dir() / "demo.js").read_text(encoding="utf-8")
    assert 'id="dimension-review"' in html
    assert all(f'id:"{name}"' in js for name in ("money", "crop", "grid", "work"))
    assert (static_dir() / "locales" / "nl.json").is_file()
    assert (static_dir() / "locales" / "en.json").is_file()


def test_run_includes_uncertainty_grid_position_and_model_metadata(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ui = UiServer(config_path=str(
        static_dir().parents[3] / "configs" / "scenario_westland_winter.yaml"))
    result = ui.run({"planner": "rule-based", "data_source": "synthetic"}, persist=False)
    assert result["grid_position"]["position"] in {"short", "long", "balanced"}
    assert result["uncertainty"]["cost"]["high_eur"] >= result["uncertainty"]["cost"]["low_eur"]
    assert result["model_execution"]["sampling"] == {
        "max_tokens": 8000, "temperature": None}


def test_dimension_review_records_all_required_research_fields(tmp_path):
    log = InteractionLog(tmp_path / "interactions.sqlite3")
    log.append({"session_id": "s", "dimension": "crop", "initial_response": "disagree"})
    row = log.export()[0]
    assert set(FIELDS) <= set(row)
    assert row["session_id"] == "s"
    assert row["edits"] == []


def test_mcp_is_optional_and_exposes_shared_tools(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ui = UiServer(config_path=str(
        static_dir().parents[3] / "configs" / "scenario_westland_winter.yaml"))
    response = dispatch(ui, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {tool["name"] for tool in response["result"]["tools"]}
    assert names == {"kasflex_day_context", "kasflex_plan", "kasflex_parameters"}


def test_experiment_matrix_is_bounded_and_crosses_checker_conditions(
        tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ui = UiServer(config_path=str(
        static_dir().parents[3] / "configs" / "scenario_westland_winter.yaml"))
    result = ui.run_experiment({
        "overrides": {"data_source": "synthetic"},
        "planners": ["rule-based"], "repetitions": 2, "checker": "both",
    })
    assert len(result["rows"]) == 4
    assert {row["checker_enabled"] for row in result["rows"]} == {False, True}
