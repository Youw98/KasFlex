"""What the plan changes, said as a handful of things rather than a day of hours.

A grower does not want to read twenty-four rows. They want to know what is being
done differently from normal, why, and what it is worth. So the unit shown to them
is an **action**: a contiguous stretch of hours where the plan departs from the
baseline, named in their own language.

The baseline is the rule-based planner -- "normal settings", the conventional
control a grower already has. That choice is what makes the comparison meaningful:
every action answers "instead of what?", and "keep normal settings" has something
concrete to fall back to.

Actions are derived, never authored by a model. Grouping is arithmetic over two
plans, and the wording comes from templates. A language model writing these would
put the one thing a grower must be able to rely on -- what the system is actually
going to do -- behind a text generator.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

from kasflex import i18n

#: Fields worth surfacing, in the order a grower cares about them, with the
#: template used to name a change and the reassurance shown beside it.
_TRACKED: tuple[tuple[str, str, str], ...] = (
    ("lighting_level", "lighting", "good_for_crop"),
    ("heat_source", "heat", "safe"),
    ("chp_mode", "chp", "within_limits"),
    ("battery", "battery", "within_limits"),
)

MAX_ACTIONS = 5
"""More than a handful stops being a summary. The rest stay in the detailed view."""


@dataclass(frozen=True)
class Action:
    """One departure from normal settings, in words a grower can act on."""

    action_id: str
    kind: str
    title: str
    why: str
    status: str
    """``safe`` | ``good_for_crop`` | ``within_limits`` -- the reassurance shown."""
    hours: tuple[int, ...]
    field_name: str
    baseline_value: str
    planned_value: str
    saving_eur: float | None = None

    @property
    def start(self) -> int:
        return min(self.hours)

    @property
    def end(self) -> int:
        return max(self.hours)

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "hours": list(self.hours),
                "start": self.start, "end": self.end}


def _runs(hours: list[int]) -> list[list[int]]:
    """Split sorted hours into contiguous stretches."""
    out: list[list[int]] = []
    for hour in sorted(hours):
        if out and hour == out[-1][-1] + 1:
            out[-1].append(hour)
        else:
            out.append([hour])
    return out


def _part_of_day(hours: list[int], language: str) -> str:
    """Morning, afternoon, evening or night, from the middle of the stretch."""
    middle = hours[len(hours) // 2]
    if 6 <= middle < 12:
        key = "day.morning"
    elif 12 <= middle < 18:
        key = "day.afternoon"
    elif 18 <= middle < 23:
        key = "day.evening"
    else:
        key = "day.night"
    return i18n.translate(key, language)


def _same(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) < 1e-9
    return left == right


def _describe(field_name: str, kind: str, rows: list[dict[str, Any]],
              baseline_rows: list[dict[str, Any]], hours: list[int],
              language: str) -> tuple[str, str] | None:
    """Title and reason for one change, or None when it is not worth showing."""
    when = _part_of_day(hours, language)
    planned = rows[0].get(field_name)
    before = baseline_rows[0].get(field_name)

    if field_name == "lighting_level":
        percent = round(float(planned) * 100)
        was = round(float(before) * 100)
        if percent == was:
            return None
        # "Dim lighting to 0%" is not how anyone says it.
        if percent == 0:
            return (i18n.translate("action.lighting.off", language, when=when),
                    i18n.translate("action.lighting.down.why", language))
        key = "action.lighting.down" if percent < was else "action.lighting.up"
        return (i18n.translate(key, language, percent=percent, when=when),
                i18n.translate(f"{key}.why", language))

    if field_name == "heat_source":
        if planned == before:
            return None
        return (i18n.translate("action.heat", language,
                               source=i18n.translate(f"asset.{planned}", language),
                               when=when),
                i18n.translate("action.heat.why", language))

    if field_name == "chp_mode":
        if planned == before:
            return None
        key = "action.chp.off" if planned == "off" else "action.chp.on"
        return (i18n.translate(key, language, when=when),
                i18n.translate(f"{key}.why", language))

    if field_name == "battery":
        if planned == before or planned == "idle":
            return None
        key = ("action.battery.charge" if planned == "charge"
               else "action.battery.discharge")
        return (i18n.translate(key, language, when=when),
                i18n.translate(f"{key}.why", language))

    return None


def derive_actions(plan: list[dict[str, Any]], baseline: list[dict[str, Any]], *,
                   language: str = "en", saving_eur: float | None = None,
                   max_actions: int = MAX_ACTIONS) -> list[Action]:
    """Name what this plan does differently from normal settings.

    Args:
        plan: The plan being proposed.
        baseline: The same day under normal settings.
        saving_eur: Whole-day saving, split across the actions found. Split rather
            than attributed: apportioning a joint saving to individual changes
            would imply a precision the simulation does not have.

    Returns:
        Up to ``max_actions`` actions, longest-running first. An empty list means
        the plan does nothing a grower would notice, which is worth saying plainly
        rather than dressing up.
    """
    language = i18n.normalise(language)
    by_hour = {int(row.get("hour", i)): row for i, row in enumerate(baseline)}

    found: list[Action] = []
    for field_name, kind, status in _TRACKED:
        differing = [
            int(row.get("hour", i)) for i, row in enumerate(plan)
            if int(row.get("hour", i)) in by_hour
            and not _same(row.get(field_name), by_hour[int(row.get("hour", i))].get(field_name))
        ]
        for stretch in _runs(differing):
            rows = [r for r in plan if int(r.get("hour", -1)) in stretch]
            base_rows = [by_hour[h] for h in stretch]
            described = _describe(field_name, kind, rows, base_rows, stretch, language)
            if described is None:
                continue
            title, why = described
            found.append(Action(
                action_id=hashlib.sha256(
                    f"{field_name}:{stretch[0]}:{stretch[-1]}".encode()).hexdigest()[:12],
                kind=kind, title=title, why=why, status=status,
                hours=tuple(stretch), field_name=field_name,
                baseline_value=str(base_rows[0].get(field_name)),
                planned_value=str(rows[0].get(field_name)),
            ))

    # Longest first: a change holding for six hours matters more to a grower than
    # one that holds for one, whatever the field.
    found.sort(key=lambda a: len(a.hours), reverse=True)
    found = found[:max_actions]

    # Two stretches of the same change in the same part of the day would
    # otherwise read as the same instruction twice. Only the clashing ones get a
    # clock time, so the common case stays plain.
    seen: dict[str, int] = {}
    for action in found:
        seen[action.title] = seen.get(action.title, 0) + 1
    if any(count > 1 for count in seen.values()):
        found = [
            action if seen[action.title] == 1 else
            Action(**{**asdict(action), "hours": action.hours,
                      "title": f"{action.title} "
                               f"({i18n.format_range(action.start, action.end, language)})"})
            for action in found
        ]

    if saving_eur is not None and found:
        share = round(float(saving_eur) / len(found), 2)
        found = [Action(**{**asdict(a), "hours": a.hours, "saving_eur": share})
                 for a in found]
    return found


def summarise(actions: list[Action], language: str = "en") -> str:
    """One sentence for the card heading."""
    language = i18n.normalise(language)
    if not actions:
        return i18n.translate("actions.none", language)
    return i18n.translate("actions.count", language, n=len(actions))
