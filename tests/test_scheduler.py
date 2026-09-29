"""The optimising scheduler and the learned planner.

The load-bearing test here is :func:`test_scorer_agrees_with_the_checker`. The
scheduler re-derives the hard constraints rather than importing the checker, which
buys purity and costs a risk: the two could drift apart, and the scheduler would
then confidently produce plans that fail verification. That test is what keeps them
honest, and it is the one to fix first if it ever fails.
"""

from __future__ import annotations

import pytest

from kasflex.adapters.greenhouse import SurrogateGreenhouse
from kasflex.checker.rules import SafetyChecker
from kasflex.config import ScenarioConfig
from kasflex.controllers.base import PlanningContext
from kasflex.controllers.collaborative import CollaborativePlanner
from kasflex.controllers.rule_based import RuleBasedPlanner
from kasflex.controllers.scheduler import (
    LearnedPlanner,
    OptimizingScheduler,
    score_plan,
)
from kasflex.data.synthetic import synthetic_history
from kasflex.forecast.history import build_history

CONFIG = "configs/scenario_westland_winter.yaml"


@pytest.fixture(scope="module")
def setup():
    config = ScenarioConfig.from_yaml(CONFIG)
    hub = config.hub
    weather = synthetic_history(50, seed=11, floor_area_m2=hub.floor_area_m2)
    history = build_history(weather.days, SurrogateGreenhouse(), hub.floor_area_m2)
    return hub, history


def _context(hub, history, index):
    return PlanningContext(
        date=history[index].date, forecast=history[index].forecast, hub=hub
    )


# --- the scorer must not drift from the checker ----------------------------


@pytest.mark.parametrize("index", [30, 35, 40, 45])
def test_scorer_agrees_with_the_checker(setup, index):
    """Every plan the optimiser calls feasible must pass the real checker."""
    hub, history = setup
    conditions = history[index].forecast
    plan = LearnedPlanner(history=history[:index]).plan(_context(hub, history, index))

    score = score_plan(plan, hub, conditions)
    verdict = SafetyChecker(hub).verify(plan, conditions)
    assert score.feasible == verdict.accepted, (
        f"scheduler says feasible={score.feasible} but the checker says "
        f"accepted={verdict.accepted}; scorer found {score.violations}, checker "
        f"found {[v.constraint for v in verdict.hard_violations]}"
    )


def test_scorer_catches_a_deliberately_broken_plan(setup):
    hub, history = setup
    from kasflex.intent import flat_plan

    bad = flat_plan("d", heat_source="none", lighting_level=1.0,
                    battery="discharge", battery_power_kw=99_000.0)
    score = score_plan(bad, hub, history[30].forecast)
    assert not score.feasible
    assert any(v.startswith("battery.power_limit") for v in score.violations)


def test_scorer_rejects_a_nonsense_margin(setup):
    hub, history = setup
    with pytest.raises(ValueError, match="margin"):
        score_plan(RuleBasedPlanner().plan(_context(hub, history, 30)),
                   hub, history[30].forecast, margin=1.5)


# --- the search ------------------------------------------------------------


def test_optimiser_never_returns_something_worse(setup):
    hub, history = setup
    conditions = history[35].forecast
    seed = RuleBasedPlanner().plan(_context(hub, history, 35))
    improved = OptimizingScheduler().optimise(seed, hub, list(conditions))
    assert (
        score_plan(improved, hub, conditions).cost_eur
        <= score_plan(seed, hub, conditions).cost_eur + 1e-6
    )


def test_optimiser_actually_improves_on_the_seed(setup):
    hub, history = setup
    conditions = history[35].forecast
    seed = RuleBasedPlanner().plan(_context(hub, history, 35))
    scheduler = OptimizingScheduler()
    improved = scheduler.optimise(seed, hub, list(conditions))
    assert score_plan(improved, hub, conditions).cost_eur < score_plan(
        seed, hub, conditions
    ).cost_eur, "the search found nothing; it is not doing any work"
    assert scheduler.evaluations > 100


def test_optimiser_respects_its_evaluation_budget(setup):
    hub, history = setup
    scheduler = OptimizingScheduler(max_evaluations=50)
    seed = RuleBasedPlanner().plan(_context(hub, history, 35))
    scheduler.optimise(seed, hub, list(history[35].forecast))
    assert scheduler.evaluations <= 51


def test_optimiser_hands_back_an_infeasible_seed_untouched(setup):
    """With no valid ground to stand on, the caller's fallback must take over."""
    hub, history = setup
    from kasflex.intent import flat_plan

    bad = flat_plan("d", heat_source="none", lighting_level=0.0)
    scheduler = OptimizingScheduler()
    out = scheduler.optimise(bad, hub, list(history[30].forecast))
    assert out == bad
    assert scheduler.evaluations == 1


def test_margin_keeps_storage_away_from_its_limits(setup):
    """The whole point of the margin: fewer hours pinned against the bounds."""
    hub, history = setup
    conditions = history[35].forecast
    seed = RuleBasedPlanner().plan(_context(hub, history, 35))
    tight = OptimizingScheduler(safety_margin=0.0).optimise(seed, hub, list(conditions))
    roomy = OptimizingScheduler(safety_margin=0.45).optimise(seed, hub, list(conditions))
    edge_tight = score_plan(tight, hub, conditions, margin=0.45).margin_violations
    edge_roomy = score_plan(roomy, hub, conditions, margin=0.45).margin_violations
    assert edge_roomy <= edge_tight


# --- the planner -----------------------------------------------------------



def test_collaborative_planner_uses_structured_grower_policy(setup):
    hub, history = setup
    base = _context(hub, history, 35)
    planner = CollaborativePlanner()
    context = PlanningContext(
        date=base.date,
        forecast=base.forecast,
        hub=base.hub,
        metadata={"policy": {
            "priority": "balanced",
            "avoid_chp_night": True,
            "battery_reserve_pct": 45,
        }},
    )
    plan = planner.plan(context)
    for hour in (22, 23, 0, 1, 2, 3, 4, 5):
        assert plan.intervals[hour].chp_mode == "off"
        assert plan.intervals[hour].heat_source != "chp"
    assert planner.last_policy["priority"] == "balanced"


def test_grid_priority_does_not_raise_peak_import(setup):
    hub, history = setup
    base = _context(hub, history, 40)
    cost = CollaborativePlanner().plan(PlanningContext(
        date=base.date, forecast=base.forecast, hub=base.hub,
        metadata={"policy": {"priority": "cost", "battery_reserve_pct": 35}},
    ))
    grid = CollaborativePlanner().plan(PlanningContext(
        date=base.date, forecast=base.forecast, hub=base.hub,
        metadata={"policy": {"priority": "grid", "battery_reserve_pct": 35}},
    ))
    cost_score = score_plan(cost, hub, base.forecast)
    grid_score = score_plan(grid, hub, base.forecast)
    assert grid_score.peak_import_kw <= cost_score.peak_import_kw + 1e-6

def test_learned_planner_beats_the_rule_based_baseline(setup):
    hub, history = setup
    total_base = total_learned = 0.0
    for index in (30, 35, 40, 45):
        conditions = history[index].forecast
        context = _context(hub, history, index)
        total_base += score_plan(
            RuleBasedPlanner().plan(context), hub, conditions
        ).cost_eur
        total_learned += score_plan(
            LearnedPlanner(history=history[:index]).plan(context), hub, conditions
        ).cost_eur
    assert total_learned < total_base, (
        f"learned planner cost EUR {total_learned:,.0f} against the baseline's "
        f"EUR {total_base:,.0f}; it is not earning its complexity"
    )


def test_learned_planner_is_deterministic(setup):
    hub, history = setup
    context = _context(hub, history, 40)
    a = LearnedPlanner(history=history[:40]).plan(context)
    b = LearnedPlanner(history=history[:40]).plan(context)
    assert a.to_json() == b.to_json()


def test_learned_planner_plans_on_its_own_forecast(setup):
    """It must predict demand, not be handed it. Otherwise it is an oracle."""
    hub, history = setup
    planner = LearnedPlanner(history=history[:40])
    planner.plan(_context(hub, history, 40))
    given = [c.heat_demand_kw for c in history[40].forecast]
    predicted = list(planner.last_forecast_kw)
    assert len(predicted) == 24
    assert predicted != pytest.approx(given, rel=1e-6), (
        "the planner's demand matches the conditions it was handed exactly, so it "
        "is not forecasting anything"
    )


def test_oracle_mode_uses_the_supplied_demand(setup):
    hub, history = setup
    planner = LearnedPlanner(history=history[:40], use_forecast_demand=False)
    planner.plan(_context(hub, history, 40))
    given = [c.heat_demand_kw for c in history[40].forecast]
    assert list(planner.last_forecast_kw) == pytest.approx(given)


def test_planner_reports_what_the_search_did(setup):
    hub, history = setup
    planner = LearnedPlanner(history=history[:40])
    plan = planner.plan(_context(hub, history, 40))
    diagnostics = planner.last_diagnostics
    assert diagnostics["evaluations"] > 0
    assert diagnostics["saving_eur"] >= 0
    assert "forecast" in plan.notes.lower()
    assert plan.planner == "learned"


# --- the objective comparison ----------------------------------------------


def _score(**changes):
    from kasflex.controllers.scheduler import ScheduleScore

    fields = dict(cost_eur=1000.0, feasible=True, dli_mol_m2=10.0, violations=(),
                  margin_violations=0, peak_import_kw=4000.0,
                  buffer_discharge_kwh=0.0, crop_distance_mol_m2=0.0)
    fields.update(changes)
    return ScheduleScore(**fields)


def test_better_reads_every_objective_component():
    """_better used to stop at index 1. Every mode now carries cost or peak further
    down, and a comparison that never reaches them ignores them entirely."""
    from kasflex.controllers.scheduler import _better

    assert _better((0, 5.0, 100.0), (0, 5.0, 200.0))
    assert not _better((0, 5.0, 200.0), (0, 5.0, 100.0))
    assert not _better((0, 5.0, 100.0), (0, 5.0, 100.0)), "a tie is not progress"


def test_grid_relief_breaks_peak_ties_on_cost():
    """Grid relief puts peak first, but cost must decide between equal peaks."""
    from kasflex.controllers.scheduler import _better

    cheap = _score(cost_eur=100.0, peak_import_kw=4000.0).objective("grid")
    dear = _score(cost_eur=9999.0, peak_import_kw=4000.0).objective("grid")
    assert _better(cheap, dear)
    assert not _better(dear, cheap)


def test_grid_relief_never_buys_peak_with_the_safety_reserve():
    """Every priority must rank the grower's battery reserve first. Grid mode used
    to rank peak first, so a plan eating the reserve won on a 0.1 kW peak cut."""
    from kasflex.controllers.scheduler import _better

    safe = _score(margin_violations=0, peak_import_kw=4000.0).objective("grid")
    unsafe = _score(margin_violations=3, peak_import_kw=3999.9).objective("grid")
    assert _better(safe, unsafe)
    assert not _better(unsafe, safe)


@pytest.mark.parametrize("mode", ["balanced", "cost", "grid", "crop"])
def test_prefer_stored_heat_changes_the_ranking(mode):
    """The grower's "prefer stored heat" toggle used to be a trailing tie-breaker
    that _better never read, so it changed nothing in any mode."""
    from kasflex.controllers.scheduler import _better

    plain = _score(buffer_discharge_kwh=0.0)
    stored = _score(buffer_discharge_kwh=5000.0)
    assert _better(stored.objective(mode, prefer_stored_heat=True),
                   plain.objective(mode, prefer_stored_heat=True))
    assert not _better(stored.objective(mode), plain.objective(mode)), (
        "with the toggle off, buffer use alone must not change the ranking"
    )


def test_prefer_stored_heat_changes_a_real_plan(setup):
    """End to end: the toggle must never reduce buffer use, and on at least one of
    these seeded days it must find a plan that uses more stored heat."""
    hub, history = setup
    changed = False
    for index in (30, 35, 40, 45):
        base = _context(hub, history, index)
        used = {}
        for prefer in (False, True):
            plan = CollaborativePlanner().plan(PlanningContext(
                date=base.date, forecast=base.forecast, hub=hub,
                metadata={"policy": {"priority": "balanced", "battery_reserve_pct": 45,
                                     "prefer_stored_heat": prefer}},
            ))
            used[prefer] = score_plan(plan, hub, base.forecast).buffer_discharge_kwh
        assert used[True] >= used[False] - 1e-6
        changed = changed or used[True] > used[False] + 1e-6
    assert changed, "prefer_stored_heat changed no plan on any day"


def test_collaborative_reasoning_describes_the_optimised_plan(setup):
    """Each hour's "why" is what the grower reads before approving (R22). The
    collaborative planner used to keep the rule-based seed's text on hours the
    search had changed, so the explanation described a different plan."""
    hub, history = setup
    base = _context(hub, history, 35)
    plan = CollaborativePlanner().plan(PlanningContext(
        date=base.date, forecast=base.forecast, hub=hub,
        metadata={"policy": {"priority": "cost", "battery_reserve_pct": 35}},
    ))
    for interval in plan.intervals:
        text = interval.reasoning
        assert f"heat from {interval.heat_source}" in text, (interval.hour, text)
        if interval.battery != "idle":
            assert f"battery {interval.battery}" in text, (interval.hour, text)
        if interval.chp_mode != "off":
            assert "CHP" in text, (interval.hour, text)


# --- what one kW of peak is worth -------------------------------------------


def test_grid_relief_only_buys_peak_that_is_worth_its_price():
    """Grid relief used to rank peak strictly above cost, so it would pay EUR 100
    to shave 1 kW. It now pays at most the configured value per kW saved."""
    from kasflex.controllers.scheduler import GRID_PEAK_VALUE_EUR_PER_KW, _better

    assert GRID_PEAK_VALUE_EUR_PER_KW == pytest.approx(3.57)
    cost_plan = _score(cost_eur=1000.0, peak_import_kw=4000.0).objective("grid")
    dear_kw = _score(cost_eur=1100.0, peak_import_kw=3999.0).objective("grid")
    cheap_kw = _score(cost_eur=1100.0, peak_import_kw=3900.0).objective("grid")
    assert _better(cost_plan, dear_kw), "EUR 100 for 1 kW is not worth EUR 3.57/kW"
    assert _better(cheap_kw, cost_plan), "EUR 100 for 100 kW is worth EUR 3.57/kW"
    dear = {"peak_value_eur_per_kw": 200.0}
    assert _better(
        _score(cost_eur=1100.0, peak_import_kw=3999.0).objective("grid", **dear),
        _score(cost_eur=1000.0, peak_import_kw=4000.0).objective("grid", **dear),
    ), "the exchange rate must come from the caller"


def _grid_plan(hub, base, value):
    planner = CollaborativePlanner(peak_value_eur_per_kw=value)
    plan = planner.plan(PlanningContext(
        date=base.date, forecast=base.forecast, hub=hub,
        metadata={"policy": {"priority": "grid", "battery_reserve_pct": 35}},
    ))
    return planner, score_plan(plan, hub, base.forecast)


def test_grid_relief_spends_no_more_than_the_peak_is_worth(setup):
    """End to end on a day where relief is available: at the default value the
    planner cuts the peak and the extra cost stays under value x kW saved; at a
    near-zero value it keeps the cost-optimal plan."""
    hub, history = setup
    base = _context(hub, history, 23)
    cost_plan = score_plan(CollaborativePlanner().plan(PlanningContext(
        date=base.date, forecast=base.forecast, hub=hub,
        metadata={"policy": {"priority": "cost", "battery_reserve_pct": 35}},
    )), hub, base.forecast)

    planner, relieved = _grid_plan(hub, base, 3.57)
    saved_kw = cost_plan.peak_import_kw - relieved.peak_import_kw
    assert saved_kw > 1.0, "this day has cheap peak relief; the planner must take it"
    assert relieved.cost_eur - cost_plan.cost_eur <= 3.57 * saved_kw + 1e-6
    assert planner.last_diagnostics["peak_value_eur_per_kw"] == pytest.approx(3.57)
    assert planner.last_diagnostics["cost_plan_peak_kw"] == pytest.approx(
        cost_plan.peak_import_kw, abs=0.1)

    _, unpriced = _grid_plan(hub, base, 0.01)
    assert unpriced.peak_import_kw == pytest.approx(cost_plan.peak_import_kw)
    assert unpriced.cost_eur == pytest.approx(cost_plan.cost_eur)


def test_peak_cap_rejects_every_candidate_above_it(setup):
    """Crop-first will happily raise the peak for light; under a cap it may not."""
    hub, history = setup
    conditions = list(history[35].forecast)
    seed = RuleBasedPlanner().plan(_context(hub, history, 35))
    start = OptimizingScheduler(objective_mode="cost").optimise(seed, hub, conditions)
    cap = score_plan(start, hub, conditions).peak_import_kw

    free = OptimizingScheduler(objective_mode="crop", safety_margin=0.0)
    capped = OptimizingScheduler(objective_mode="crop", safety_margin=0.0, peak_cap_kw=cap)
    free_peak = score_plan(free.optimise(start, hub, conditions), hub, conditions).peak_import_kw
    capped_peak = score_plan(
        capped.optimise(start, hub, conditions), hub, conditions).peak_import_kw
    assert free_peak > cap + 1.0, "without a cap this search raises the peak"
    assert capped_peak <= cap + 1e-6


def test_scenario_value_reaches_the_planner():
    from kasflex.experiment import build_planner

    config = ScenarioConfig.from_yaml(CONFIG)
    assert config.grid_peak_value_eur_per_kw == pytest.approx(3.57)
    tuned = ScenarioConfig.from_dict(
        {"name": "t", "date": "2026-01-15", "grid_peak_value_eur_per_kw": 12.5})
    assert build_planner("collaborative", tuned).peak_value_eur_per_kw == 12.5
