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
    if priority not in {"balanced", "cost", "grid"}:
        priority = "balanced"

    reserve = raw.get("battery_reserve_pct", 45)
    try:
        reserve_pct = max(0.0, min(80.0, float(reserve)))
    except (TypeError, ValueError):
        reserve_pct = 45.0

    forbidden = set(_hours(raw.get("avoid_chp_hours")))
    if raw.get("avoid_chp_night") is True:
        forbidden.update(NIGHT_HOURS)

    return {
        "priority": priority,
        "battery_reserve_pct": reserve_pct,
        "avoid_chp_hours": tuple(sorted(forbidden)),
        "prefer_stored_heat": raw.get("prefer_stored_heat") is True,
    }


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

        optimiser = scheduler.OptimizingScheduler(
            safety_margin=float(policy["battery_reserve_pct"]) / 100.0,
            objective_mode=str(policy["priority"]),
            forbidden_chp_hours=tuple(policy["avoid_chp_hours"]),
            prefer_stored_heat=bool(policy["prefer_stored_heat"]),
        )
        best = optimiser.optimise(seed, context.hub, context.forecast)

        self.last_diagnostics = {
            "priority": str(policy["priority"]),
            "evaluations": float(optimiser.evaluations),
            "seed_cost_eur": round(optimiser.start_cost_eur, 2),
            "planned_cost_eur": round(optimiser.final_cost_eur, 2),
            "battery_reserve_pct": float(policy["battery_reserve_pct"]),
            "avoided_chp_hours": float(len(tuple(policy["avoid_chp_hours"]))),
        }

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
