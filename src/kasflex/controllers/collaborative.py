"""Collaborative daily planner for the grower-facing KasFlex demo.

This planner does not depend on synthetic training history. It starts from the
conventional rule-based schedule, improves it against the current day's forecast
and prices, and applies structured grower preferences supplied in the planning
context metadata.

The language-model layer remains optional: planning must still work during a team
demo with no model account configured.
"""

import dataclasses

from kasflex import intent
from kasflex.controllers import base, rule_based, scheduler

NIGHT_HOURS = (22, 23, 0, 1, 2, 3, 4, 5)


def _hours(raw: object) -> tuple[int, ...]:
    if not isinstance(raw, (list, tuple, set)):
        return ()
    out: list[int] = []
    for value in raw:
        try:
            hour = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= hour <= 23 and hour not in out:
            out.append(hour)
    return tuple(sorted(out))


def _policy(context: base.PlanningContext) -> dict[str, object]:
    raw = context.metadata.get("policy", {}) if context.metadata else {}
    if not isinstance(raw, dict):
        raw = {}

    priority = str(raw.get("priority", "balanced")).lower()
    if priority not in {"balanced", "cost", "grid", "crop"}:
        priority = "balanced"

    reserve = raw.get("battery_reserve_pct", 45)
    try:
        reserve_pct = max(0.0, min(80.0, float(reserve)))
    except (TypeError, ValueError):
        reserve_pct = 45.0

    forbidden = set(_hours(raw.get("avoid_chp_hours")))
    if raw.get("avoid_chp_night") is True:
        forbidden.update(NIGHT_HOURS)

    try:
        switch_penalty = max(0.0, min(500.0, float(raw.get("switch_penalty_eur", 0) or 0)))
    except (TypeError, ValueError):
        switch_penalty = 0.0

    return {
        "priority": priority,
        "battery_reserve_pct": reserve_pct,
        "avoid_chp_hours": tuple(sorted(forbidden)),
        "prefer_stored_heat": raw.get("prefer_stored_heat") is True,
        "switch_penalty_eur": switch_penalty,
    }


def _repair_seed(plan: intent.Plan, context: base.PlanningContext,
                 forbidden: tuple[int, ...]) -> intent.Plan:
    """Make a seed that cannot meet the heat demand feasible, if the CHP can help.

    The rule-based seed heats with the boiler. On a night colder than the boiler
    alone can handle, every hour above its capacity is a hard violation, the
    search has no feasible point to start from, and the grower gets the fallback
    plan. Running the CHP heat-led through those hours (the boiler tops up) is
    what a grower would do; it is only a starting point the search then improves.
    """
    hub = context.hub
    blocked = set(forbidden)
    cold = {c.hour for c in context.forecast
            if c.heat_demand_kw > hub.boiler.thermal_capacity_kw and c.hour not in blocked}
    if not cold or scheduler.score_plan(plan, hub, context.forecast).feasible:
        return plan
    # Extend each run to the CHP's minimum run time so the repair itself is valid.
    span = set(cold)
    for hour in sorted(cold):
        for extra in range(hub.chp.min_run_hours):
            if (hour + extra) < 24 and (hour + extra) not in blocked:
                span.add(hour + extra)
    repaired = dataclasses.replace(
        plan,
        intervals=tuple(
            dataclasses.replace(iv, heat_source="chp", chp_mode="heat_led")
            if iv.hour in span else iv
            for iv in plan.intervals),
    )
    if scheduler.score_plan(repaired, hub, context.forecast).feasible:
        return repaired
    return plan


def _apply_blackout(plan: intent.Plan, forbidden: tuple[int, ...]) -> intent.Plan:
    """Make the seed compatible with a CHP blackout before optimisation."""
    blocked = set(forbidden)
    if not blocked:
        return plan

    intervals = []
    for interval in plan.intervals:
        if interval.hour not in blocked:
            intervals.append(interval)
            continue

        changes: dict[str, object] = {"chp_mode": "off"}
        if interval.heat_source == "chp":
            changes["heat_source"] = "boiler"
        if interval.co2_source == "chp":
            changes["co2_source"] = "liquid"
        intervals.append(dataclasses.replace(interval, **changes))

    return dataclasses.replace(plan, intervals=tuple(intervals))


@dataclasses.dataclass
class CollaborativePlanner:
    """Optimise one day while keeping grower choices visible and enforceable."""

    name: str = "collaborative"
    peak_value_eur_per_kw: float = scheduler.GRID_PEAK_VALUE_EUR_PER_KW
    last_policy: dict[str, object] = dataclasses.field(default_factory=dict, init=False)
    last_diagnostics: dict[str, float | str] = dataclasses.field(
        default_factory=dict,
        init=False,
    )

    def plan(self, context: base.PlanningContext) -> intent.Plan:
        policy = _policy(context)
        self.last_policy = policy

        seed = rule_based.RuleBasedPlanner().plan(context)
        seed = _apply_blackout(seed, policy["avoid_chp_hours"])
        seed = _repair_seed(seed, context, tuple(policy["avoid_chp_hours"]))

        margin = float(policy["battery_reserve_pct"]) / 100.0
        forbidden = tuple(policy["avoid_chp_hours"])
        prefer_stored = bool(policy["prefer_stored_heat"])
        switch_penalty = float(policy["switch_penalty_eur"])

        # Grid relief starts from the cost-improved plan and may only lower its
        # peak, and only where each kW saved is worth what it costs to save it.
        cost_plan_peak: float | None = None
        if policy["priority"] == "grid":
            warmup = scheduler.OptimizingScheduler(
                safety_margin=margin,
                objective_mode="cost",
                forbidden_chp_hours=forbidden,
                prefer_stored_heat=prefer_stored,
                switch_penalty_eur=switch_penalty,
            )
            seed = warmup.optimise(seed, context.hub, context.forecast)
            cost_plan_peak = scheduler.score_plan(
                seed, context.hub, context.forecast, margin=warmup.margin_used
            ).peak_import_kw

        optimiser = scheduler.OptimizingScheduler(
            safety_margin=margin,
            objective_mode=str(policy["priority"]),
            forbidden_chp_hours=forbidden,
            prefer_stored_heat=prefer_stored,
            peak_value_eur_per_kw=self.peak_value_eur_per_kw,
            peak_cap_kw=cost_plan_peak,
            switch_penalty_eur=switch_penalty,
        )
        best = optimiser.optimise(seed, context.hub, context.forecast)
        # The search edits the rule-based seed field by field; without this every
        # hour would still carry the seed's reasoning, describing a plan the grower
        # is not actually approving (R22).
        best = scheduler._explain(best, context.forecast, optimiser.margin_used)

        self.last_diagnostics = {
            "priority": str(policy["priority"]),
            "evaluations": float(optimiser.evaluations),
            "seed_cost_eur": round(optimiser.start_cost_eur, 2),
            "planned_cost_eur": round(optimiser.final_cost_eur, 2),
            "battery_reserve_pct": float(policy["battery_reserve_pct"]),
            "avoided_chp_hours": float(len(tuple(policy["avoid_chp_hours"]))),
        }
        if cost_plan_peak is not None:
            self.last_diagnostics["peak_value_eur_per_kw"] = self.peak_value_eur_per_kw
            self.last_diagnostics["cost_plan_peak_kw"] = round(cost_plan_peak, 1)

        note = (
            f"KasFlex collaborative plan; priority={policy['priority']}; "
            f"battery reserve={float(policy['battery_reserve_pct']):.0f}%; "
            f"CHP blocked in {len(tuple(policy['avoid_chp_hours']))} hour(s)."
        )
        return dataclasses.replace(
            best,
            planner=self.name,
            brief=context.brief,
            revision=context.revision,
            notes=note,
            metadata={
                **best.metadata,
                "policy": policy,
                "diagnostics": self.last_diagnostics,
            },
        )
