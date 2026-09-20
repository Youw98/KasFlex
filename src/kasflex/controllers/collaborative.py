"""Collaborative daily planner for the grower-facing KasFlex demo.

This planner deliberately does not depend on synthetic training history. It starts
from the conventional rule-based schedule, improves it against the current day's
forecast and prices, and applies structured grower preferences supplied in the
PlanningContext metadata.

The language-model layer remains optional: planning must still work during a team
demo with no model account configured.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from kasflex.controllers.base import PlanningContext
from kasflex.controllers.rule_based import RuleBasedPlanner
from kasflex.controllers.scheduler import OptimizingScheduler
from kasflex.intent import Plan


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


def _policy(context: PlanningContext) -> dict[str, object]:
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


def _apply_blackout(plan: Plan, forbidden: tuple[int, ...]) -> Plan:
    """Make the seed compatible with a CHP blackout before optimisation."""
    blocked = set(forbidden)
    if not blocked:
        return plan
    intervals = []
    for iv in plan.intervals:
        if iv.hour not in blocked:
            intervals.append(iv)
            continue
        changes: dict[str, object] = {"chp_mode": "off"}
        if iv.heat_source == "chp":
            changes["heat_source"] = "boiler"
        if iv.co2_source == "chp":
            changes["co2_source"] = "liquid"
        intervals.append(replace(iv, **changes))
    return replace(plan, intervals=tuple(intervals))


@dataclass
class CollaborativePlanner:
    """Optimise one real day while keeping the grower's structured choices visible."""

    name: str = "collaborative"
    last_policy: dict[str, object] = field(default_factory=dict, init=False)
    last_diagnostics: dict[str, float | str] = field(default_factory=dict, init=False)

    def plan(self, context: PlanningContext) -> Plan:
        policy = _policy(context)
        self.last_policy = policy

        seed = RuleBasedPlanner().plan(context)
        seed = _apply_blackout(seed, policy["avoid_chp_hours"])

        scheduler = OptimizingScheduler(
            safety_margin=policy["battery_reserve_pct"] / 100.0,
            objective_mode=policy["priority"],
            forbidden_chp_hours=policy["avoid_chp_hours"],
            prefer_stored_heat=policy["prefer_stored_heat"],
        )
        best = scheduler.optimise(seed, context.hub, context.forecast)

        self.last_diagnostics = {
            "priority": policy["priority"],
            "evaluations": float(scheduler.evaluations),
            "seed_cost_eur": round(scheduler.start_cost_eur, 2),
            "planned_cost_eur": round(scheduler.final_cost_eur, 2),
            "battery_reserve_pct": policy["battery_reserve_pct"],
            "avoided_chp_hours": float(len(policy["avoid_chp_hours"])),
        }

        note = (
            f"KasFlex collaborative plan; priority={policy['priority']}; "
            f"battery reserve={policy['battery_reserve_pct']:.0f}%; "
            f"CHP blocked in {len(policy['avoid_chp_hours'])} hour(s)."
        )
        return replace(
            best,
            planner=self.name,
            brief=context.brief,
            revision=context.revision,
            notes=note,
            metadata={**best.metadata, "policy": policy, "diagnostics": self.last_diagnostics},
        )
