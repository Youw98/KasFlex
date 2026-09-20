"""Reliance measurement: the two-by-two, the rates, and what stays uncounted.

The classification is the study's dependent variable, so each cell of the
two-by-two is pinned down explicitly. The other half of these tests is about
restraint: an unscored decision, or one where grower and planner agreed anyway,
carries no reliance information and must not be quietly counted as a success.
"""

from __future__ import annotations

import sqlite3

import pytest

from kasflex.reliance import RelianceLog


@pytest.fixture
def log(tmp_path) -> RelianceLog:
    return RelianceLog(tmp_path / "grower_memory.sqlite3")


def decision(log, *, grower, ai, final, better=None, confidence=3,
             run_id="run-1", condition="", question="heat_source@03"):
    """Walk one decision through elicit -> reveal -> resolve -> score."""
    item = log.elicit(run_id=run_id, question=question, grower_choice=grower,
                      confidence=confidence, hour=3, condition=condition)
    log.reveal(item.elicitation_id, ai)
    log.resolve(item.elicitation_id, final)
    if better is not None:
        log.score(item.elicitation_id, better)
    return log.get(item.elicitation_id)


# -- eliciting before revealing ---------------------------------------------


def test_an_opinion_is_captured_with_its_confidence(log):
    item = log.elicit(run_id="r1", question="heat_source@03",
                      grower_choice="boiler", confidence=4, hour=3)

    assert item.grower_choice == "boiler"
    assert item.confidence == 4
    assert item.ai_choice == "", "the suggestion must not exist yet"
    assert item.verdict == ""


def test_an_empty_opinion_is_refused(log):
    with pytest.raises(ValueError, match="what you would do"):
        log.elicit(run_id="r1", question="q", grower_choice="  ", confidence=3)


@pytest.mark.parametrize("confidence", [0, 6, -1, 99])
def test_confidence_outside_the_scale_is_refused(log, confidence):
    with pytest.raises(ValueError, match="between 1 and 5"):
        log.elicit(run_id="r1", question="q", grower_choice="boiler",
                   confidence=confidence)


def test_confidence_must_be_a_number(log):
    with pytest.raises(ValueError, match="whole number"):
        log.elicit(run_id="r1", question="q", grower_choice="boiler",
                   confidence="very sure")


def test_resolving_without_revealing_is_refused(log):
    """A decision taken without ever seeing the suggestion measures nothing."""
    item = log.elicit(run_id="r1", question="q", grower_choice="boiler", confidence=3)
    with pytest.raises(ValueError, match="nothing to have relied on"):
        log.resolve(item.elicitation_id, "boiler")


def test_the_record_cannot_be_rewritten(log):
    item = log.elicit(run_id="r1", question="q", grower_choice="boiler", confidence=2)
    with sqlite3.connect(log.path) as db, pytest.raises(sqlite3.IntegrityError,
                                                        match="append-only"):
        db.execute("UPDATE elicitations SET confidence=5 WHERE elicitation_id=?",
                   (item.elicitation_id,))


def test_reveal_and_resolve_are_timestamped_in_order(log):
    item = decision(log, grower="boiler", ai="chp", final="chp", better="chp")
    assert item.created_at <= item.revealed_at <= item.resolved_at <= item.scored_at


# -- the two-by-two ---------------------------------------------------------


def test_went_with_a_correct_suggestion_is_appropriate(log):
    item = decision(log, grower="boiler", ai="chp", final="chp", better="chp")
    assert item.verdict == "appropriate_ai"
    assert item.switched is True


def test_went_with_a_wrong_suggestion_is_over_reliance(log):
    item = decision(log, grower="boiler", ai="chp", final="chp", better="boiler")
    assert item.verdict == "over_reliance"


def test_ignored_a_correct_suggestion_is_under_reliance(log):
    item = decision(log, grower="boiler", ai="chp", final="boiler", better="chp")
    assert item.verdict == "under_reliance"
    assert item.switched is False


def test_ignored_a_wrong_suggestion_is_appropriate(log):
    item = decision(log, grower="boiler", ai="chp", final="boiler", better="boiler")
    assert item.verdict == "appropriate_self"


# -- what must stay uncounted -----------------------------------------------


def test_an_unscored_decision_has_no_verdict(log):
    item = decision(log, grower="boiler", ai="chp", final="chp")
    assert item.better_choice == ""
    assert item.verdict == "", "not yet known is not the same as wrong"


def test_agreement_carries_no_reliance_information(log):
    item = decision(log, grower="chp", ai="chp", final="chp", better="chp")
    assert item.disagreed is False
    assert item.verdict == "", "there was no reliance decision to make"


def test_metrics_ignore_agreements_and_unscored_items(log):
    decision(log, grower="chp", ai="chp", final="chp", better="chp")      # agreed
    decision(log, grower="boiler", ai="chp", final="chp")                  # unscored
    decision(log, grower="boiler", ai="chp", final="chp", better="chp")    # counts

    metrics = log.metrics()
    assert metrics["elicitations"] == 3
    assert metrics["scored"] == 1
    assert metrics["appropriate_ai"] == 1


# -- rates ------------------------------------------------------------------


def test_empty_rates_are_none_not_zero(log):
    metrics = log.metrics()
    assert metrics["appropriate_reliance_rate"] is None
    assert metrics["rair"] is None
    assert metrics["rsr"] is None
    assert metrics["elicitations"] == 0


def test_appropriate_reliance_rate_counts_both_appropriate_cells(log):
    decision(log, grower="boiler", ai="chp", final="chp", better="chp")       # appropriate_ai
    decision(log, grower="boiler", ai="chp", final="boiler", better="boiler")  # appropriate_self
    decision(log, grower="boiler", ai="chp", final="chp", better="boiler")     # over
    decision(log, grower="boiler", ai="chp", final="boiler", better="chp")     # under

    metrics = log.metrics()
    assert metrics["scored"] == 4
    assert metrics["appropriate_reliance_rate"] == pytest.approx(0.5)
    assert metrics["over_reliance_rate"] == pytest.approx(0.25)
    assert metrics["under_reliance_rate"] == pytest.approx(0.25)


def test_rair_is_switching_when_switching_would_have_helped(log):
    # Three occasions where the planner was right; the grower switched on two.
    decision(log, grower="boiler", ai="chp", final="chp", better="chp")
    decision(log, grower="boiler", ai="chp", final="chp", better="chp")
    decision(log, grower="boiler", ai="chp", final="boiler", better="chp")

    assert log.metrics()["rair"] == pytest.approx(2 / 3)


def test_rsr_is_holding_firm_when_holding_firm_would_have_helped(log):
    decision(log, grower="boiler", ai="chp", final="boiler", better="boiler")
    decision(log, grower="boiler", ai="chp", final="chp", better="boiler")

    assert log.metrics()["rsr"] == pytest.approx(0.5)


def test_rair_is_none_when_the_planner_was_never_right(log):
    decision(log, grower="boiler", ai="chp", final="boiler", better="boiler")
    metrics = log.metrics()

    assert metrics["rair"] is None, "no occasion arose, which is not a failure"
    assert metrics["rsr"] == pytest.approx(1.0)


def test_agreement_rate_counts_every_resolved_decision(log):
    decision(log, grower="chp", ai="chp", final="chp")        # agreed
    decision(log, grower="boiler", ai="chp", final="boiler")  # kept own

    assert log.metrics()["agreement_rate"] == pytest.approx(0.5)


def test_switch_rate_looks_only_at_disagreements(log):
    decision(log, grower="chp", ai="chp", final="chp")        # agreed, excluded
    decision(log, grower="boiler", ai="chp", final="chp")     # switched
    decision(log, grower="boiler", ai="chp", final="boiler")  # held

    assert log.metrics()["switch_rate"] == pytest.approx(0.5)


# -- confidence, which is RQ1 -----------------------------------------------


def test_switching_is_broken_down_by_stated_confidence(log):
    decision(log, grower="boiler", ai="chp", final="chp", confidence=1)
    decision(log, grower="boiler", ai="chp", final="chp", confidence=1)
    decision(log, grower="boiler", ai="chp", final="boiler", confidence=5)

    buckets = log.metrics()["switch_by_confidence"]
    assert buckets[1] == {"switched": 2, "total": 2}
    assert buckets[5] == {"switched": 0, "total": 1}


def test_mean_confidence_is_reported(log):
    decision(log, grower="boiler", ai="chp", final="chp", confidence=2)
    decision(log, grower="boiler", ai="chp", final="chp", confidence=4)

    assert log.metrics()["mean_confidence"] == pytest.approx(3.0)


def test_metrics_can_be_filtered_to_one_condition(log):
    decision(log, grower="boiler", ai="chp", final="chp", better="chp",
             condition="uncertainty_shown")
    decision(log, grower="boiler", ai="chp", final="boiler", better="chp",
             condition="uncertainty_hidden")

    shown = log.metrics("uncertainty_shown")
    hidden = log.metrics("uncertainty_hidden")
    assert shown["appropriate_ai"] == 1 and shown["under_reliance"] == 0
    assert hidden["under_reliance"] == 1 and hidden["appropriate_ai"] == 0


# -- outcomes ---------------------------------------------------------------


def test_an_outcome_records_the_prediction_error(log):
    outcome = log.record_outcome(run_id="r1", predicted_cost_eur=10000,
                                 actual_cost_eur=10450, within_predicted_band=True)

    assert outcome.prediction_error_eur == pytest.approx(450)
    assert outcome.within_predicted_band is True


def test_an_outcome_says_which_plan_would_have_been_cheaper(log):
    outcome = log.record_outcome(run_id="r1", predicted_cost_eur=10000,
                                 actual_cost_eur=10450, ai_plan_cost_eur=10200,
                                 final_plan_cost_eur=10450)
    assert outcome.ai_plan_was_better is True


def test_comparison_is_unknown_when_only_one_plan_was_costed(log):
    outcome = log.record_outcome(run_id="r1", predicted_cost_eur=10000,
                                 actual_cost_eur=10450, ai_plan_cost_eur=10200)
    assert outcome.ai_plan_was_better is None


def test_band_coverage_is_the_share_of_days_inside_the_range(log):
    log.record_outcome(run_id="a", predicted_cost_eur=1, actual_cost_eur=1,
                       within_predicted_band=True)
    log.record_outcome(run_id="b", predicted_cost_eur=1, actual_cost_eur=9,
                       within_predicted_band=False)
    log.record_outcome(run_id="c", predicted_cost_eur=1, actual_cost_eur=1,
                       within_predicted_band=True)

    metrics = log.metrics()
    assert metrics["band_coverage"] == pytest.approx(2 / 3)
    assert metrics["mean_absolute_prediction_error_eur"] == pytest.approx(8 / 3)


def test_outcomes_cannot_be_rewritten(log):
    outcome = log.record_outcome(run_id="r1", predicted_cost_eur=1, actual_cost_eur=2)
    with sqlite3.connect(log.path) as db, pytest.raises(sqlite3.IntegrityError,
                                                        match="append-only"):
        db.execute("UPDATE outcomes SET actual_cost_eur=999 WHERE outcome_id=?",
                   (outcome.outcome_id,))


# -- persistence and export -------------------------------------------------


def test_reopening_the_file_sees_prior_measurements(tmp_path):
    path = tmp_path / "grower_memory.sqlite3"
    decision(RelianceLog(path), grower="boiler", ai="chp", final="chp", better="chp")

    assert RelianceLog(path).metrics()["appropriate_ai"] == 1


def test_export_is_json_safe_and_carries_the_verdicts(log):
    import json

    decision(log, grower="boiler", ai="chp", final="chp", better="chp")
    log.record_outcome(run_id="run-1", predicted_cost_eur=1, actual_cost_eur=2)
    payload = json.loads(json.dumps(log.export()))

    assert payload["elicitations"][0]["verdict"] == "appropriate_ai"
    assert payload["elicitations"][0]["confidence"] == 3
    assert payload["outcomes"][0]["prediction_error_eur"] == pytest.approx(1)
    assert payload["metrics"]["scored"] == 1


def test_elicitations_are_scoped_by_run(log):
    decision(log, grower="boiler", ai="chp", final="chp", run_id="a")
    decision(log, grower="boiler", ai="chp", final="chp", run_id="b")

    assert len(log.elicitations("a")) == 1
    assert len(log.elicitations()) == 2


def test_a_missing_elicitation_raises(log):
    with pytest.raises(KeyError):
        log.get("nope")
