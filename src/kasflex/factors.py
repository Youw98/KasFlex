"""Which inputs shaped this plan, and how much: a what-if explanation.

For each factor, KasFlex plans the same day again with that factor taken away
(made flat, or set to a neutral value) and everything else unchanged, then counts
how many of the 24 hours come out differently and how much the cost moves. A
factor that changes many hours is one the plan leans on.

This is ablation, the same idea behind permutation importance and the "remove
one feature" view of SHAP values, applied to a planner instead of a regression.
It is exact for this planner and this day, not an approximation of a model, but
it does not add up across factors the way SHAP values do: two factors can explain
the same hour.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from statistics import fmean
from typing import Any

from kasflex.controllers.base import PlanningContext
from kasflex.controllers.collaborative import CollaborativePlanner
from kasflex.controllers.scheduler import score_plan
from kasflex.energy.assets import EnergyHub
from kasflex.energy.dispatch import HourlyConditions

FIELDS = ("heat_source", "lighting_level", "battery", "chp_mode")

LABELS = {
    "price": ("Price differences between hours", "Prijsverschillen tussen uren"),
    "heat": ("Heat demand through the day", "Warmtevraag over de dag"),
    "sun": ("Sunlight", "Zonlicht"),
    "gas": ("Gas price (20% higher)", "Gasprijs (20% hoger)"),
    "grid": ("Grid contract limits", "Grenzen van het netcontract"),
    "choices": ("Your choices and remembered reasons", "Uw keuzes en onthouden redenen"),
}


def _flatten(conditions: Sequence[HourlyConditions], attribute: str) -> tuple:
    mean = fmean(getattr(c, attribute) for c in conditions)
    return tuple(dataclasses.replace(c, **{attribute: mean}) for c in conditions)


def _plan(hub, conditions, date, policy, peak_value):
    planner = CollaborativePlanner(peak_value_eur_per_kw=peak_value)
    return planner.plan(PlanningContext(date=date, forecast=tuple(conditions), hub=hub,
                                        metadata={"policy": policy}))


def _changed_hours(a, b) -> list[int]:
    hours = []
    for x, y in zip(a.intervals, b.intervals, strict=True):
        if any(getattr(x, f) != getattr(y, f) for f in FIELDS):
            hours.append(x.hour)
    return hours


def explain_factors(
    hub: EnergyHub,
    conditions: Sequence[HourlyConditions],
    *,
    date: str,
    policy: dict[str, Any],
    peak_value_eur_per_kw: float = 3.57,
    language: str = "en",
) -> dict[str, Any]:
    """Return one bar per factor, largest first."""
    nl = language == "nl"
    conditions = tuple(conditions)
    reference = _plan(hub, conditions, date, policy, peak_value_eur_per_kw)
    reference_cost = score_plan(reference, hub, conditions).cost_eur

    neutral = {
        "price": (hub, _flatten(conditions, "power_price_eur_kwh"), policy),
        "heat": (hub, _flatten(conditions, "heat_demand_kw"), policy),
        "sun": (hub, _flatten(conditions, "irradiance_w_m2"), policy),
        "gas": (hub, tuple(dataclasses.replace(c, gas_price_eur_kwh=c.gas_price_eur_kwh * 1.2)
                           for c in conditions), policy),
        "grid": (dataclasses.replace(hub, contract=dataclasses.replace(
            hub.contract, congestion_windows={})), conditions, policy),
        "choices": (hub, conditions, {"priority": policy.get("priority", "balanced")}),
    }

    bars = []
    for key, (factor_hub, factor_conditions, factor_policy) in neutral.items():
        alternative = _plan(factor_hub, factor_conditions, date, factor_policy,
                            peak_value_eur_per_kw)
        hours = _changed_hours(reference, alternative)
        # Cost on the real day, so the number answers "what does this factor buy me".
        cost = score_plan(alternative, hub, conditions).cost_eur
        label = LABELS[key][1 if nl else 0]
        if hours:
            sentence = (f"Zonder dit zouden {len(hours)} van de 24 uur anders gepland zijn."
                        if nl else
                        f"Without it, {len(hours)} of the 24 hours would be planned differently.")
        else:
            sentence = ("Dit verandert morgen niets aan het plan." if nl else
                        "This does not change tomorrow's plan.")
        bars.append({
            "factor": key,
            "label": label,
            "changed_hours": hours,
            "share": round(len(hours) / 24, 3),
            "cost_effect_eur": round(cost - reference_cost, 2),
            "sentence": sentence,
        })
    bars.sort(key=lambda bar: (-len(bar["changed_hours"]), -abs(bar["cost_effect_eur"])))
    return {
        "priority": policy.get("priority", "balanced"),
        "bars": bars,
        "method": ("Elke factor wordt weggehaald en de dag opnieuw gepland; het aantal "
                   "veranderde uren laat zien hoe sterk het plan op die factor leunt." if nl else
                   "Each factor is taken away and the day planned again; the number of hours "
                   "that change shows how much the plan leans on that factor."),
    }


__all__ = ["explain_factors"]
