"""How much this plan's cost could move, and how much of that we can defend.

The research question this serves is whether a grower's reliance on the planner
tracks the planner's actual reliability. That question cannot be asked of a system
that states every plan as flat fact, which is what KasFlex did before this module.

Two kinds of uncertainty, kept separate because growers act on them differently
and the literature says conflating them misleads:

**Aleatoric** -- irreducible. Tomorrow's weather is not yet decided, so tomorrow's
heat demand is not either. More data would not remove this. A grower hearing it
should think "fair enough, that is the weather".

**Epistemic** -- ours. This day may be unlike anything the system has planned
before, in which case its judgement is worth less than usual. More data *would*
remove this. A grower hearing it should think "be careful today".

The governing rule here is that **an invented confidence interval is worse than
none**. Every number carries a ``basis`` saying whether it was measured from data
or assumed from a configured default, and :meth:`PlanUncertainty.is_defensible`
is False when the basis is too thin to show a grower a range at all. The interface
is expected to honour that and say "I cannot tell you" rather than draw a band.
"""

from __future__ import annotations

import dataclasses
import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Any

#: Assumed 24-hour-ahead forecast error, used only when nothing has been measured.
#:
#: These are placeholders, not findings. They are deliberately wide, so that an
#: un-measured band errs towards "less certain than reality" rather than flattering
#: the planner. Replace them with a measured error as soon as a cache exists --
#: :func:`measured_forecast_error` does this automatically -- or with a cited
#: figure recorded in docs/PARAMETERS.md.
ASSUMED_TEMP_RMSE_C = 2.0
ASSUMED_IRRADIANCE_RMSE_W_M2 = 60.0

DEFAULT_SAMPLES = 24
"""Perturbations per estimate. Enough for a stable 10th/90th percentile, cheap
enough to run inside a request."""

MIN_DAYS_FOR_MEASURED_ERROR = 5
"""Below this, a 'measured' error is noise wearing a lab coat, so it stays assumed."""

MIN_DAYS_FOR_NOVELTY = 10
"""Below this there is no distribution to be unusual against, so epistemic
uncertainty is reported as unknown rather than as zero."""


@dataclass(frozen=True)
class ForecastError:
    """How wrong the weather forecast typically is, and how we know."""

    temp_rmse_c: float
    irradiance_rmse_w_m2: float
    basis: str = "assumed"
    """``measured`` from cached forecast-versus-actual pairs, or ``assumed``."""
    sample_days: int = 0
    source: str = ""

    @property
    def measured(self) -> bool:
        return self.basis == "measured"

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass(frozen=True)
class Novelty:
    """How unlike previously seen days this one is."""

    score: float = 0.0
    """Roughly a standard-deviation distance. 0 is typical, above 2 is unusual."""
    known: bool = False
    """False when there is no history to compare against."""
    sample_days: int = 0
    drivers: tuple[str, ...] = ()
    """Which features are unusual, most unusual first."""

    @property
    def band(self) -> str:
        """``typical`` | ``unusual`` | ``unlike anything seen`` | ``unknown``."""
        if not self.known:
            return "unknown"
        if self.score < 1.5:
            return "typical"
        return "unusual" if self.score < 3.0 else "unlike anything seen"

    def to_dict(self) -> dict[str, Any]:
        return {**dataclasses.asdict(self), "band": self.band}


@dataclass(frozen=True)
class CostBand:
    """A plausible range for the day's cost."""

    central_eur: float
    low_eur: float
    high_eur: float
    coverage: float = 0.8
    """Fraction of sampled outcomes inside the band."""

    @property
    def spread_eur(self) -> float:
        return self.high_eur - self.low_eur

    @property
    def relative_spread(self) -> float:
        """Spread as a fraction of the central estimate. 0 when cost is zero."""
        return self.spread_eur / abs(self.central_eur) if self.central_eur else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {**dataclasses.asdict(self), "spread_eur": self.spread_eur,
                "relative_spread": self.relative_spread}


@dataclass(frozen=True)
class PlanUncertainty:
    """Everything the interface needs to talk honestly about confidence."""

    cost: CostBand | None
    forecast_error: ForecastError
    novelty: Novelty
    hours_most_uncertain: tuple[int, ...] = ()
    caveats: tuple[str, ...] = field(default_factory=tuple)
    samples: int = 0

    @property
    def is_defensible(self) -> bool:
        """Whether a range may be shown at all.

        False when the band rests only on an assumed forecast error *and* there is
        no history to judge novelty against -- at that point the interval would be
        an artefact of two placeholder constants, and showing it would manufacture
        confidence rather than describe it.
        """
        return self.cost is not None and (self.forecast_error.measured or self.novelty.known)

    @property
    def confidence(self) -> str:
        """``high`` | ``medium`` | ``low`` | ``unknown``, for a grower-facing badge."""
        if not self.is_defensible or self.cost is None:
            return "unknown"
        if self.novelty.band == "unlike anything seen":
            return "low"
        spread = self.cost.relative_spread
        if spread < 0.08 and self.novelty.band == "typical":
            return "high"
        if spread < 0.20:
            return "medium"
        return "low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost": self.cost.to_dict() if self.cost else None,
            "forecast_error": self.forecast_error.to_dict(),
            "novelty": self.novelty.to_dict(),
            "hours_most_uncertain": list(self.hours_most_uncertain),
            "caveats": list(self.caveats),
            "samples": self.samples,
            "is_defensible": self.is_defensible,
            "confidence": self.confidence,
        }


# --------------------------------------------------------------------------
# Measuring what we can
# --------------------------------------------------------------------------


def measured_forecast_error(cache, latitude: float, longitude: float,
                            max_days: int = 60) -> ForecastError:
    """Compare cached forecasts against cached reanalysis for the same days.

    This is the honest version of the numbers at the top of this module: it is the
    error *this site's* forecasts actually had. Falls back to the assumed values
    when too few paired days exist to mean anything.
    """
    site = f"{latitude:.3f}_{longitude:.3f}"
    try:
        entries = cache.entries()
    except OSError:
        entries = {}

    dates = sorted(
        key.removeprefix("weather_forecast_").removesuffix(f"_{site}")
        for key in entries
        if key.startswith("weather_forecast_") and key.endswith(site)
    )[-max_days:]

    temp_errors: list[float] = []
    irradiance_errors: list[float] = []
    paired = 0
    for iso in dates:
        actual_key = f"weather_actual_{iso}_{site}"
        if actual_key not in entries:
            continue
        try:
            forecast = {int(r["hour"]): r for r in cache.get(f"weather_forecast_{iso}_{site}")}
            actual = {int(r["hour"]): r for r in cache.get(actual_key)}
        except (KeyError, ValueError, OSError):
            continue
        hours = set(forecast) & set(actual)
        if len(hours) < 24:
            continue
        paired += 1
        for hour in hours:
            temp_errors.append(float(forecast[hour]["outdoor_temp_c"])
                               - float(actual[hour]["outdoor_temp_c"]))
            irradiance_errors.append(float(forecast[hour]["irradiance_w_m2"])
                                     - float(actual[hour]["irradiance_w_m2"]))

    if paired < MIN_DAYS_FOR_MEASURED_ERROR or not temp_errors:
        return ForecastError(
            temp_rmse_c=ASSUMED_TEMP_RMSE_C,
            irradiance_rmse_w_m2=ASSUMED_IRRADIANCE_RMSE_W_M2,
            basis="assumed", sample_days=paired,
            source=f"module default; {paired} paired day(s) cached, "
                   f"{MIN_DAYS_FOR_MEASURED_ERROR} needed to measure",
        )

    rmse = lambda values: math.sqrt(sum(v * v for v in values) / len(values))  # noqa: E731
    return ForecastError(
        temp_rmse_c=round(rmse(temp_errors), 3),
        irradiance_rmse_w_m2=round(rmse(irradiance_errors), 1),
        basis="measured", sample_days=paired,
        source=f"cached Open-Meteo forecast vs reanalysis, {paired} day(s) at {site}",
    )


def day_novelty(conditions, history: list[dict[str, float]] | None) -> Novelty:
    """How far this day sits from the days already seen.

    ``history`` is a list of ``{"mean_temp_c", "mean_irradiance_w_m2",
    "mean_price_eur_kwh"}``. Returns an unknown novelty rather than a confident
    zero when there is not enough history to have an opinion.
    """
    if not history or len(history) < MIN_DAYS_FOR_NOVELTY:
        return Novelty(known=False, sample_days=len(history or []))

    today = {
        "mean_temp_c": statistics.fmean(c.outdoor_temp_c for c in conditions),
        "mean_irradiance_w_m2": statistics.fmean(c.irradiance_w_m2 for c in conditions),
        "mean_price_eur_kwh": statistics.fmean(c.power_price_eur_kwh for c in conditions),
    }
    labels = {"mean_temp_c": "temperature", "mean_irradiance_w_m2": "sunlight",
              "mean_price_eur_kwh": "electricity price"}

    scored: list[tuple[float, str]] = []
    for feature, value in today.items():
        past = [float(day[feature]) for day in history if feature in day]
        if len(past) < MIN_DAYS_FOR_NOVELTY:
            continue
        spread = statistics.pstdev(past)
        if spread <= 1e-9:
            continue
        scored.append((abs(value - statistics.fmean(past)) / spread, labels[feature]))

    if not scored:
        return Novelty(known=False, sample_days=len(history))

    scored.sort(reverse=True)
    return Novelty(
        score=round(scored[0][0], 2), known=True, sample_days=len(history),
        drivers=tuple(name for score, name in scored if score >= 1.5),
    )


# --------------------------------------------------------------------------
# Propagating it to cost
# --------------------------------------------------------------------------


def _perturb(conditions, error: ForecastError, rng: random.Random):
    """One plausible alternative weather realisation for the same day.

    The offset is correlated across the day plus an hourly component: a forecast
    that is too warm at breakfast is usually still too warm at lunch, and sampling
    each hour independently would cancel that out and understate the cost spread.
    """
    day_temp = rng.gauss(0, error.temp_rmse_c * 0.7)
    day_irradiance = rng.gauss(0, error.irradiance_rmse_w_m2 * 0.7)
    out = []
    for condition in conditions:
        temp = condition.outdoor_temp_c + day_temp + rng.gauss(0, error.temp_rmse_c * 0.5)
        irradiance = max(0.0, condition.irradiance_w_m2 + day_irradiance
                         + rng.gauss(0, error.irradiance_rmse_w_m2 * 0.5))
        out.append(dataclasses.replace(condition, outdoor_temp_c=temp,
                                       irradiance_w_m2=irradiance))
    return tuple(out)


def estimate(plan, hub, conditions, greenhouse, *, forecast_error: ForecastError,
             novelty: Novelty | None = None, samples: int = DEFAULT_SAMPLES,
             seed: int = 0) -> PlanUncertainty:
    """Resimulate this plan under plausible alternative weather.

    Deterministic for a given seed, because a confidence interval that moves when
    you reload the page is not a confidence interval.

    Returns a :class:`PlanUncertainty` whose ``cost`` is None if the simulation
    could not be run, rather than a fabricated band.
    """
    from kasflex.forecast.cost import project_cost  # noqa: PLC0415 - avoids a cycle

    novelty = novelty or Novelty()
    rng = random.Random(seed)
    costs: list[float] = []
    hourly: dict[int, list[float]] = {}

    for _ in range(max(2, samples)):
        try:
            projection = project_cost(plan, hub, _perturb(conditions, forecast_error, rng),
                                      greenhouse)
        except Exception:  # noqa: BLE001 - a failed sample must not fail the plan
            continue
        totals = projection.get("totals") or {}
        net = totals.get("net_cost_eur")
        if net is None or not math.isfinite(float(net)):
            continue
        costs.append(float(net))
        for row in projection.get("hourly") or []:
            hour = int(row.get("hour", -1))
            value = row.get("net_cost_eur")
            if hour >= 0 and value is not None and math.isfinite(float(value)):
                hourly.setdefault(hour, []).append(float(value))

    caveats: list[str] = []
    if not forecast_error.measured:
        caveats.append(
            "The size of the weather error is a configured assumption, not measured "
            "for this site. Download and cache more days to replace it.")
    if not novelty.known:
        caveats.append(
            "There is not enough history to judge whether this day is unusual.")
    caveats.append(
        "The greenhouse model itself is unvalidated; its error is not included here.")

    if len(costs) < 2:
        return PlanUncertainty(cost=None, forecast_error=forecast_error, novelty=novelty,
                               caveats=(*caveats, "The cost range could not be computed."),
                               samples=len(costs))

    costs.sort()
    percentile = lambda p: costs[min(len(costs) - 1, max(0, int(round(p * (len(costs) - 1)))))]  # noqa: E731
    band = CostBand(central_eur=round(statistics.median(costs), 2),
                    low_eur=round(percentile(0.10), 2),
                    high_eur=round(percentile(0.90), 2), coverage=0.8)

    spreads = sorted(((max(v) - min(v), hour) for hour, v in hourly.items() if len(v) > 1),
                     reverse=True)
    return PlanUncertainty(
        cost=band, forecast_error=forecast_error, novelty=novelty,
        hours_most_uncertain=tuple(hour for _, hour in spreads[:3]),
        caveats=tuple(caveats), samples=len(costs),
    )


# --------------------------------------------------------------------------
# Saying it in words
# --------------------------------------------------------------------------


def describe(uncertainty: PlanUncertainty, language: str = "en") -> dict[str, str]:
    """Plain-language sentences for the interface.

    Returns ``headline``, ``detail`` and ``why``. When the estimate is not
    defensible the headline says so outright -- the interface must not fall back
    to implying confidence it does not have.
    """
    from kasflex import i18n  # noqa: PLC0415 - avoids a cycle at import time

    dutch = i18n.normalise(language) == "nl"
    money = lambda v: i18n.format_money(v, language)  # noqa: E731

    if not uncertainty.is_defensible or uncertainty.cost is None:
        return {
            "headline": "Ik kan niet zeggen hoe zeker dit is."
                        if dutch else "I can't tell you how certain this is.",
            "detail": "Er zijn nog te weinig gegevens om een betrouwbare marge te "
                      "berekenen." if dutch else
                      "There isn't enough data yet to work out a reliable range.",
            "why": "; ".join(uncertainty.caveats),
        }

    band = uncertainty.cost
    if dutch:
        headline = f"Waarschijnlijk tussen {money(band.low_eur)} en {money(band.high_eur)}"
        detail = ("Dit hangt vooral af van hoe het weer morgen werkelijk uitpakt."
                  if uncertainty.novelty.band == "typical" else
                  "Deze dag lijkt weinig op eerdere dagen, dus wees extra voorzichtig.")
        if uncertainty.hours_most_uncertain:
            hours = ", ".join(i18n.format_hour(h, language)
                              for h in sorted(uncertainty.hours_most_uncertain))
            detail += f" Het minst zeker rond {hours}."
    else:
        headline = f"Likely between {money(band.low_eur)} and {money(band.high_eur)}"
        detail = ("This mostly depends on how the weather actually turns out."
                  if uncertainty.novelty.band == "typical" else
                  "This day is unlike the ones seen before, so treat it with extra care.")
        if uncertainty.hours_most_uncertain:
            hours = ", ".join(i18n.format_hour(h, language)
                              for h in sorted(uncertainty.hours_most_uncertain))
            detail += f" Least certain around {hours}."

    basis = (("gemeten op " if dutch else "measured over ")
             + f"{uncertainty.forecast_error.sample_days} "
             + ("dagen" if dutch else "days")) if uncertainty.forecast_error.measured else (
        "aangenomen foutmarge" if dutch else "assumed error margin")
    return {"headline": headline, "detail": detail,
            "why": f"{basis}; {uncertainty.samples} " +
                   ("simulaties" if dutch else "simulations")}


def history_from_conditions(days: list) -> list[dict[str, float]]:
    """Summarise past condition series into the shape :func:`day_novelty` wants."""
    out = []
    for conditions in days:
        if not conditions:
            continue
        out.append({
            "mean_temp_c": statistics.fmean(c.outdoor_temp_c for c in conditions),
            "mean_irradiance_w_m2": statistics.fmean(c.irradiance_w_m2 for c in conditions),
            "mean_price_eur_kwh": statistics.fmean(c.power_price_eur_kwh for c in conditions),
        })
    return out


__all__ = [
    "CostBand", "ForecastError", "Novelty", "PlanUncertainty",
    "day_novelty", "describe", "estimate", "history_from_conditions",
    "measured_forecast_error",
]
