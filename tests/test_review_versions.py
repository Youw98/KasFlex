"""Adversarial checks for durable, revision-bound server approvals."""
import copy
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from kasflex.ui.reviews import ReviewConflict
from kasflex.ui.server import UiServer


@pytest.fixture
def reviewer(tmp_path, monkeypatch):
    config = Path("configs/scenario_westland_winter.yaml").resolve()
    monkeypatch.chdir(tmp_path)
    return UiServer(config_path=str(config), anonymous=True)


def reference(result):
    return {k: result[k] for k in ("run_id", "revision", "plan_hash")}


def test_no_detached_or_forged_approvals(reviewer):
    with pytest.raises(ReviewConflict, match="not saved"):
        reviewer.decide({"decision": "approve"})
    saved = reviewer.run({})
    with pytest.raises(ReviewConflict, match="revision has changed"):
        reviewer.decide({**reference(saved), "plan_hash": "forged", "decision": "approve"})


def test_disabled_and_rejected_revisions_cannot_be_approved(reviewer):
    saved = reviewer.run({"checker.enabled": False})
    with pytest.raises(ReviewConflict, match="not passed verification"):
        reviewer.decide({**reference(saved), "decision": "approve"})
    edited = [{**r, "heat_source": "none"} for r in saved["plan"]]
    rejected = reviewer.verify({}, edited, reference(saved))
    assert rejected["accepted"] is False
    with pytest.raises(ReviewConflict, match="not passed verification"):
        reviewer.decide({**reference(rejected), "decision": "approve"})


def test_new_revision_invalidates_older_tabs_and_preserves_inputs(reviewer, monkeypatch):
    saved = reviewer.run({"gas_price_eur_kwh": 0.06})
    original = copy.deepcopy(saved["plan"])
    original[0]["power_price_eur_kwh"] = 999  # client-controlled display metadata

    def no_new_day(*args, **kwargs):
        raise AssertionError("Verification fetched a different day's inputs")

    monkeypatch.setattr("kasflex.ui.server._day_for", no_new_day)
    revised = reviewer.verify({"hub.contract.import_limit_kw": 20000},
                              original, reference(saved))
    assert revised["revision"] == 2
    assert revised["plan"][0]["power_price_eur_kwh"] == saved["plan"][0]["power_price_eur_kwh"]
    assert revised["configuration"] == saved["configuration"]
    with pytest.raises(ReviewConflict, match="revision has changed"):
        reviewer.decide({**reference(saved), "decision": "approve"})
    decision = reviewer.decide({**reference(revised), "decision": "approve"})
    assert decision["plan_hash"] == revised["plan_hash"]


def test_duplicate_decisions_are_idempotent_and_contradictions_rejected(reviewer):
    saved = reviewer.run({})
    request = {**reference(saved), "decision": "approve", "seconds_to_decide": 18}
    with ThreadPoolExecutor(max_workers=2) as pool:
        decisions = list(pool.map(reviewer.decide, [request, request]))
    assert sum(not d["duplicate"] for d in decisions) == 1
    assert all(d["seconds_to_decide"] is None for d in decisions)
    with pytest.raises(ReviewConflict, match="already has a decision"):
        reviewer.decide({**reference(saved), "decision": "reject"})


def test_decision_and_history_survive_restarting_server(reviewer):
    saved = reviewer.run({})
    reviewer.decide({**reference(saved), "decision": "approve"})
    reopened = UiServer(config_path=reviewer.config_path)
    stored = reopened.reviews.get(saved["run_id"])
    assert stored["result"] == saved
    assert stored["decision"]["decision"] == "approve"
    assert reopened.reviews.history()[0]["run_id"] == saved["run_id"]
    with sqlite3.connect(reopened.reviews.path) as db:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            db.execute("DELETE FROM revisions")
