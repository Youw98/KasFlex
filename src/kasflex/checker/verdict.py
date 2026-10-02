"""Machine-readable checker output (R17).

A rejection must tell the planner enough to fix the plan without guessing: which
constraint, which interval, what it asked for, and what it may have instead. That
is exactly the four fields of :class:`Violation`, and it is what makes the revision
loop (R18) something better than resampling.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    """How much confidence the checker has that a violation is real.

    ``HARD`` violations are decided exactly from the plan and the asset limits --
    a contract breach or an out-of-bounds state of charge is arithmetic, not
    prediction. ``PROJECTED`` violations depend on a forward model of the
    greenhouse, so they inherit that model's error. Reporting the two separately
    keeps an honest line between what verification guarantees and what it merely
    expects, and stops a modelling artefact from being counted as a safety result.
    """

    HARD = "hard"
    PROJECTED = "projected"


@dataclass(frozen=True)
class Violation:
    """One violated constraint in one interval."""

    constraint: str
    """Stable identifier, e.g. ``"grid.import_limit"``. Safe to match on in analysis."""
    category: str
    """``"electrical"``, ``"asset"`` or ``"crop"`` -- the R14/R15/R16 grouping."""
    severity: Severity
    hour: int | None
    """Hour of the day, or ``None`` for a whole-day constraint such as the DLI."""
    actual: float
    bound: float
    unit: str
    message: str
    """Human-readable statement, shown to the approver and to the planner."""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["severity"] = self.severity.value
        return payload


@dataclass(frozen=True)
class Verdict:
    """The checker's decision on one plan."""

    accepted: bool
    violations: tuple[Violation, ...] = ()
    checks_run: tuple[str, ...] = ()
    checks_excluded: tuple[str, ...] = ()
    enabled: bool = True
    """False when the checker was switched off entirely (R19). Then ``accepted`` is
    True by construction and ``violations`` is empty -- the run is unverified."""
    plan_revision: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def hard_violations(self) -> tuple[Violation, ...]:
        return tuple(v for v in self.violations if v.severity is Severity.HARD)

    @property
    def projected_violations(self) -> tuple[Violation, ...]:
        return tuple(v for v in self.violations if v.severity is Severity.PROJECTED)

    def feedback(self, explain: bool = True, limit: int = 12) -> str:
        """Text handed back to the planner for its next revision.

        Args:
            explain: When False, return only that the plan was rejected, with no
                reasons. This is the R19 switch that separates the value of
                *verification* from the value of *explanation*: a planner that
                improves only when told why is a different finding from one that
                improves merely by being rejected.
            limit: Maximum number of violations to list.
        """
        if self.accepted:
            return "Plan accepted."
        if not explain:
            return "Plan rejected. No further information is available."
        lines = [f"Plan rejected: {len(self.violations)} constraint violation(s)."]
        for v in self.violations[:limit]:
            where = "whole day" if v.hour is None else f"hour {v.hour:02d}"
            lines.append(
                f"- [{v.category}/{v.constraint}] {where}: "
                f"{v.actual:.2f} {v.unit} against a limit of {v.bound:.2f} {v.unit}. {v.message}"
            )
        if len(self.violations) > limit:
            lines.append(f"- ... and {len(self.violations) - limit} more.")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "enabled": self.enabled,
            "plan_revision": self.plan_revision,
            "checks_run": list(self.checks_run),
            "checks_excluded": list(self.checks_excluded),
            "violations": [v.to_dict() for v in self.violations],
            "metadata": self.metadata,
        }

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


#: Each check in plain words, English and Dutch. ``{when}`` is "at 18:00" or
#: "over the day"; ``{actual}``/``{bound}`` carry their unit.
_PLAIN = {
    "grid.import_limit": (
        "{when}: {actual} from the grid, the contract allows {bound}.",
        "{when}: {actual} van het net, het contract staat {bound} toe.",
    ),
    "grid.export_limit": (
        "{when}: {actual} back to the grid, the contract allows {bound}.",
        "{when}: {actual} terug naar het net, het contract staat {bound} toe.",
    ),
    "battery.power_limit": (
        "{when}: the battery would run at {actual}; it can do {bound}.",
        "{when}: de batterij zou {actual} leveren; ze kan {bound}.",
    ),
    "battery.state_of_charge": (
        "{when}: the battery would be at {actual}; the safe limit is {bound}.",
        "{when}: de batterij zou op {actual} staan; de veilige grens is {bound}.",
    ),
    "buffer.level_bounds": (
        "{when}: the heat buffer would be at {actual}; its limit is {bound}.",
        "{when}: de warmtebuffer zou op {actual} staan; de grens is {bound}.",
    ),
    "chp.min_run_time": (
        "{when}: the CHP would run {actual}; it needs at least {bound} once started.",
        "{when}: de WKK zou {actual} draaien; eenmaal aan moet hij minstens {bound}.",
    ),
    "chp.min_down_time": (
        "{when}: the CHP would restart after {actual}; it needs {bound} off.",
        "{when}: de WKK zou na {actual} weer starten; hij moet {bound} uit blijven.",
    ),
    "chp.ramp_rate": (
        "{when}: the CHP would change by {actual}; it can change {bound}.",
        "{when}: de WKK zou {actual} veranderen; hij kan {bound}.",
    ),
    "crop.daily_light_integral": (
        "{when}: {actual} of light; the crop needs at least {bound}.",
        "{when}: {actual} licht; het gewas heeft minstens {bound} nodig.",
    ),
    "crop.temperature_band": (
        "{when}: {actual} in the greenhouse; the crop needs {bound}.",
        "{when}: {actual} in de kas; het gewas heeft {bound} nodig.",
    ),
    "crop.humidity": (
        "{when}: humidity {actual}; the limit is {bound}.",
        "{when}: luchtvochtigheid {actual}; de grens is {bound}.",
    ),
    "heat.demand_met": (
        "{when}: {actual} of heat short; the plan must cover {bound}.",
        "{when}: {actual} warmte tekort; het plan moet {bound} dekken.",
    ),
}


def plain_message(violation: dict[str, Any], language: str = "en") -> str:
    """A violation in the grower's words and language; the checker's own text otherwise."""
    templates = _PLAIN.get(str(violation.get("constraint", "")))
    if not templates:
        return str(violation.get("message", ""))
    nl = language == "nl"
    hour = violation.get("hour")
    when = ((f"Om {int(hour):02d}:00" if nl else f"At {int(hour):02d}:00") if hour is not None
            else ("Over de dag" if nl else "Over the day"))
    unit = str(violation.get("unit", "")).replace("mol/m2/day", "mol/m²").replace("degC", "°C")

    def amount(value: Any) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        text = f"{number:,.0f}" if abs(number) >= 100 else f"{number:,.1f}"
        if nl:
            text = text.replace(",", "·").replace(".", ",").replace("·", ".")
        return f"{text} {unit}".strip()

    return templates[1 if nl else 0].format(when=when, actual=amount(violation.get("actual")),
                                            bound=amount(violation.get("bound")))
