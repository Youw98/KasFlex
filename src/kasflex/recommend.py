"""The AI goes first: compare the options for tomorrow and recommend one.

Before the grower chooses anything, KasFlex plans tomorrow four ways (balanced,
lowest cost, crop first, grid relief), scores each with the same dispatch model
the checker uses, and recommends one with reasons in numbers. The grower then
agrees, or chooses differently.

The recommendation is a short decision list over those simulated outcomes, not a
black box, so the reasons it prints are the reasons it chose:

1. crop first, when the cheapest plan leaves the crop clearly short of light;
2. grid relief, when it lowers the peak by a meaningful amount at a price below
   what a kW of peak is worth (the grid-relief objective guarantees the second);
3. lowest cost, when prices swing hard and cost-first saves noticeably more;
4. otherwise balanced.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from kasflex.controllers.base import PlanningContext
from kasflex.controllers.collaborative import CollaborativePlanner
from kasflex.controllers.rule_based import RuleBasedPlanner
from kasflex.controllers.scheduler import score_plan
from kasflex.energy.assets import EnergyHub
from kasflex.energy.dispatch import HourlyConditions

PRIORITIES = ("balanced", "cost", "crop", "grid")
#: Light shortfall that makes crop-first worth recommending [mol/m2/day].
LIGHT_SHORTFALL = 1.0
#: Peak reduction that makes grid relief worth recommending, as a share of the
#: contracted import capacity.
PEAK_SHARE = 0.04
#: Price swing (dearest / cheapest hour) that makes cost-first worth recommending.
PRICE_SWING = 2.5
#: Extra saving of cost-first over balanced that it must show, as a share.
COST_EDGE = 0.01


def _option(priority: str, plan, hub: EnergyHub, conditions) -> dict[str, Any]:
    score = score_plan(plan, hub, conditions)
    return {
        "priority": priority,
        "cost_eur": round(score.cost_eur, 2),
        "peak_import_kw": round(score.peak_import_kw, 1),
        "light_mol_m2": round(score.dli_mol_m2, 2),
        "switches": score.switches,
        "feasible": score.feasible,
    }


def recommend(
    hub: EnergyHub,
    conditions: Sequence[HourlyConditions],
    *,
    date: str,
    base_policy: dict[str, Any] | None = None,
    peak_value_eur_per_kw: float = 3.57,
    language: str = "en",
) -> dict[str, Any]:
    """Plan the day four ways and say which one KasFlex would choose, and why."""
    nl = language == "nl"
    base = dict(base_policy or {})
    conditions = tuple(conditions)
    context = PlanningContext(date=date, forecast=conditions, hub=hub)
    normal = _option("normal", RuleBasedPlanner().plan(context), hub, conditions)

    options: dict[str, dict[str, Any]] = {}
    for priority in PRIORITIES:
        planner = CollaborativePlanner(peak_value_eur_per_kw=peak_value_eur_per_kw)
        plan = planner.plan(PlanningContext(
            date=date, forecast=conditions, hub=hub,
            metadata={"policy": {**base, "priority": priority}}))
        options[priority] = _option(priority, plan, hub, conditions)

    prices = [c.power_price_eur_kwh for c in conditions]
    cheapest, dearest = min(prices), max(prices)
    swing = dearest / cheapest if cheapest > 0.005 else float("inf")
    target = hub.crop.dli_target_mol_m2
    light_short = target - options["cost"]["light_mol_m2"]
    peak_drop = options["cost"]["peak_import_kw"] - options["grid"]["peak_import_kw"]
    cost_edge = options["balanced"]["cost_eur"] - options["cost"]["cost_eur"]
    reasons: list[str] = []

    if light_short > LIGHT_SHORTFALL:
        choice = "crop"
        reasons.append(
            f"Het goedkoopste plan geeft {options['cost']['light_mol_m2']:.1f} mol/m² licht, "
            f"{light_short:.1f} onder de lichtbehoefte van {target:.1f}." if nl else
            f"The cheapest plan gives {options['cost']['light_mol_m2']:.1f} mol/m² of light, "
            f"{light_short:.1f} below the crop's {target:.1f}.")
    elif peak_drop >= PEAK_SHARE * hub.contract.import_limit_kw:
        choice = "grid"
        extra = options["grid"]["cost_eur"] - options["cost"]["cost_eur"]
        reasons.append(
            f"Net ontlasten verlaagt de piek met {peak_drop:,.0f} kW voor €{extra:,.0f} "
            f"extra; een kW minder piek is €{peak_value_eur_per_kw:.2f} waard." if nl else
            f"Grid relief lowers the peak by {peak_drop:,.0f} kW for €{extra:,.0f} more; "
            f"one kW less peak is worth €{peak_value_eur_per_kw:.2f}.")
    elif swing >= PRICE_SWING and cost_edge >= COST_EDGE * options["balanced"]["cost_eur"]:
        choice = "cost"
        reasons.append(
            f"De stroomprijs schommelt van {cheapest * 100:.1f} tot {dearest * 100:.1f} ct/kWh; "
            f"kosten eerst bespaart €{cost_edge:,.0f} meer dan in balans." if nl else
            f"Power prices swing from {cheapest * 100:.1f} to {dearest * 100:.1f} ct/kWh; "
            f"cost first saves €{cost_edge:,.0f} more than balanced.")
    else:
        choice = "balanced"
        reasons.append(
            "Geen van de andere keuzes levert morgen duidelijk meer op; in balans weegt "
            "kosten, net en gewas samen." if nl else
            "None of the other choices clearly pays off tomorrow; balanced weighs cost, "
            "grid and crop together.")

    chosen = options[choice]
    saving = normal["cost_eur"] - chosen["cost_eur"]
    reasons.append(
        f"Verwachte kosten €{chosen['cost_eur']:,.0f}, €{abs(saving):,.0f} "
        f"{'lager' if saving >= 0 else 'hoger'} dan de normale regeling." if nl else
        f"Expected cost €{chosen['cost_eur']:,.0f}, €{abs(saving):,.0f} "
        f"{'below' if saving >= 0 else 'above'} normal control.")

    night = [c.outdoor_temp_c for c in conditions if c.hour in (0, 1, 2, 3, 4, 5, 22, 23)]
    reserve = 55.0 if night and min(night) < 0 else 45.0
    if reserve > 45:
        reasons.append(
            f"Vannacht vriest het ({min(night):.0f} °C): ik houd {reserve:.0f}% reserve in "
            "batterij en buffer." if nl else
            f"It freezes tonight ({min(night):.0f} °C): I keep {reserve:.0f}% reserve in "
            "battery and buffer.")

    policy = {
        "priority": choice,
        "battery_reserve_pct": max(reserve, float(base.get("battery_reserve_pct", 0) or 0)),
        "prefer_stored_heat": base.get("prefer_stored_heat", True) is not False,
        "avoid_chp_night": base.get("avoid_chp_night") is True,
    }
    return {
        "priority": choice,
        "policy": policy,
        "reasons": reasons,
        "options": [options[p] for p in PRIORITIES],
        "normal": normal,
        "model": "kasflex-recommender-v1",
    }


__all__ = ["PRIORITIES", "recommend"]
