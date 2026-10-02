"""Turn a grower's short reason for disagreeing into something the planner can use.

When a grower disagrees with part of a plan they must say why, in a few words:
"only two staff tomorrow", "CHP mechanic 8-14", "frost warning tonight". This
module reads such a reason, deterministically, and returns:

* ``effects``: changes to the planning policy, applied to the alternative plan
  straight away (avoid CHP in some hours, fewer equipment switches, plan for a
  colder night, ...);
* ``applies``: when the reason should be reused later. ``once`` is a one-off fact
  (a maintenance visit), shown as a reminder but never applied automatically;
  ``cold`` comes back on cold days; ``always`` is a standing rule (CHP noise at
  night, or any reason phrased as one: "always", "never", "from now on");
* ``summary``: one sentence telling the grower what KasFlex will do with it.

It recognises Dutch and English. Text it cannot map to an effect is still kept
and shown to the AI and to the grower next time; it just changes nothing in the
plan by itself. That is the honest fallback: no invented interpretation.

When an AI model is configured, :func:`read_with_model` gets a second chance at
text the rules miss. The model may only choose from the same effects, each value
is checked and clamped here (:func:`clean_effects`), and the summary the grower
sees is written from the checked effects, not by the model. The alternative plan
still goes through the deterministic checker like any other.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

NIGHT = [22, 23, 0, 1, 2, 3, 4, 5]
_HOUR_RANGE = re.compile(
    r"(?:van|from|tussen|between)?\s*(\d{1,2})(?:[:.]\d{2})?\s*(?:u|uur|h)?\s*"
    r"(?:-|–|—|tot|to|until|en|and|t/m)\s*(\d{1,2})(?:[:.]\d{2})?\s*(?:u|uur|h)?",
    re.IGNORECASE,
)
_POWER = re.compile(r"(\d+(?:[.,]\d+)?)\s*(mw|kw)\b", re.IGNORECASE)
_TEMP = re.compile(r"(-|−|min(?:us)?\s*)?\s*(\d{1,2})\s*(?:°|graden|degrees|deg)\s*c?",
                   re.IGNORECASE)

CHP_WORDS = ("chp", "wkk", "warmtekracht", "motor")
OFF_WORDS = ("off", "uit", "maintenance", "onderhoud", "monteur", "mechanic", "service",
             "repair", "reparatie", "defect", "kapot", "broken", "not", "niet", "geen",
             "no ", "avoid", "vermijd", "storing")
NOISE_WORDS = ("noise", "geluid", "neighbour", "neighbor", "buren", "lawaai")
STAFF_WORDS = ("staff", "personeel", "people", "mensen", "collega", "werknemers",
               "employees", "crew", "ploeg", "bezetting", "handen")
FEW_WORDS = ("few", "weinig", "only", "maar", "alleen", "short", "tekort", "minder",
             "two", "twee", " 2 ", " 3 ", "drie", "three", "ziek", "sick", "absent")
COLD_WORDS = ("frost", "vorst", "cold", "koud", "freez", "vries", "knmi", "code oranje",
              "code orange", "ijzel")
LIGHT_MORE = ("more light", "meer licht", "meer belichting", "too dark", "te donker",
              "light short", "lichttekort")
BUFFER_WORDS = ("buffer", "opgeslagen warmte", "stored heat", "warmteopslag")
GRID_WORDS = ("grid", " net ", "netbeheer", "liander", "stedin", "enexis", "tennet",
              "transport", "aansluiting", "afname", "import")
PEAK_WORDS = ("peak", "piek", "netcongestie", "congestion", "grid limit", "netbeheerder")
#: Words that make a reason a standing rule rather than a fact about tomorrow.
STANDING_WORDS = ("always", "altijd", "never", "nooit", "every day", "elke dag", "iedere dag",
                  "usually", "meestal", "normally", "normaal gesproken", "standaard",
                  "from now on", "voortaan", "in general", "in het algemeen", "every ",
                  "elke ", "iedere ")


def _contains(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def _hours(text: str) -> list[int]:
    hours: list[int] = []
    for start, end in _HOUR_RANGE.findall(text):
        a, b = int(start), int(end)
        if not (0 <= a <= 24 and 0 <= b <= 24) or a == b:
            continue
        span = range(a, b) if a < b else list(range(a, 24)) + list(range(0, b))
        hours.extend(h % 24 for h in span)
    return sorted(set(hours))


def _night_temperature(text: str) -> float | None:
    for sign, value in _TEMP.findall(text):
        number = float(value)
        return -number if sign else number
    return None


def interpret(reason: str, dimension: str = "", language: str = "en") -> dict[str, Any]:
    """Read a short reason. Never raises on odd text; unknown text has no effects."""
    text = " " + " ".join(str(reason or "").lower().split()) + " "
    effects: dict[str, Any] = {}
    applies = "once"
    said: list[str] = []
    nl = language == "nl"

    if _contains(text, CHP_WORDS):
        hours = _hours(text)
        if _contains(text, NOISE_WORDS) or "night" in text or "nacht" in text:
            effects["avoid_chp_hours"] = sorted(set(NIGHT) | set(hours))
            applies = "always"
            said.append("WKK 's nachts uit" if nl else "CHP off overnight")
        elif _contains(text, OFF_WORDS):
            effects["avoid_chp_hours"] = hours or list(range(24))
            span = (f"{hours[0]:02d}:00–{(hours[-1] + 1) % 24:02d}:00" if hours
                    else ("de hele dag" if nl else "all day"))
            said.append(f"WKK uit {span}" if nl else f"CHP off {span}")

    if _contains(text, STAFF_WORDS) and _contains(text, FEW_WORDS):
        effects["switch_penalty_eur"] = 60.0
        said.append("minder schakelingen, rustiger plan" if nl
                    else "fewer equipment switches, a steadier plan")

    if _contains(text, COLD_WORDS):
        temp = _night_temperature(text)
        effects["night_temp_c"] = temp if temp is not None and temp < 10 else -6.0
        effects["battery_reserve_pct"] = 60.0
        effects["prefer_stored_heat"] = False
        applies = "cold" if applies == "once" else applies
        said.append(f"rekenen met een nacht van {effects['night_temp_c']:.0f} °C en meer reserve"
                    if nl else
                    f"plan for a {effects['night_temp_c']:.0f} °C night and keep more reserve")

    if _contains(text, LIGHT_MORE) or (dimension == "crop" and "licht" in text):
        effects["priority"] = "crop"
        said.append("gewas eerst" if nl else "crop first")

    if _contains(text, BUFFER_WORDS) and not effects.get("night_temp_c"):
        effects["prefer_stored_heat"] = True
        said.append("opgeslagen warmte eerst" if nl else "stored heat first")

    power = _POWER.search(text)
    if power and (_contains(text, PEAK_WORDS) or _contains(text, GRID_WORDS)):
        kw = float(power.group(1).replace(",", ".")) * (1000 if power.group(2).lower() == "mw"
                                                         else 1)
        hours = _hours(text) or list(range(24))
        effects["import_caps"] = {hour: kw for hour in hours}
        span = (f"{hours[0]:02d}:00–{(hours[-1] + 1) % 24:02d}:00" if len(hours) < 24
                else ("de hele dag" if nl else "all day"))
        said.append(f"maximaal {kw / 1000:.1f} MW van het net {span}" if nl else
                    f"at most {kw / 1000:.1f} MW from the grid {span}")
    elif _contains(text, PEAK_WORDS):
        effects["priority"] = "grid"
        said.append("lagere netpiek" if nl else "lower grid peak")

    if said:
        summary = ("KasFlex past dit toe: " if nl else "KasFlex will apply: ") + "; ".join(said)
    else:
        summary = ("KasFlex onthoudt dit en neemt het mee in het gesprek, maar kan het nog niet "
                   "vertalen naar een planwijziging." if nl else
                   "KasFlex remembers this and uses it in the conversation, but cannot yet "
                   "turn it into a plan change.")
    if effects and _contains(text, STANDING_WORDS):
        # "We always have few staff" is a rule for every day, not a note about one.
        applies = "always"
    return {"effects": effects, "applies": applies if effects else "once", "summary": summary,
            "source": "rules"}


def apply_effects(policy: dict[str, Any], effects: dict[str, Any]) -> dict[str, Any]:
    """Merge effects into a policy. Hours add up; numbers take the stricter value."""
    merged = dict(policy)
    for key, value in effects.items():
        if key == "avoid_chp_hours":
            merged[key] = sorted(set(merged.get(key) or []) | {int(h) for h in value})
        elif key == "battery_reserve_pct":
            merged[key] = max(float(merged.get(key, 0) or 0), float(value))
        elif key == "night_temp_c":
            current = merged.get(key)
            merged[key] = float(value) if current is None else min(float(current), float(value))
        elif key == "import_caps":
            caps = {int(h): float(v) for h, v in (merged.get(key) or {}).items()}
            for hour, kw in value.items():
                caps[int(hour)] = min(caps.get(int(hour), float(kw)), float(kw))
            merged[key] = caps
        elif key == "switch_penalty_eur":
            merged[key] = max(float(merged.get(key, 0) or 0), float(value))
        else:
            merged[key] = value
    return merged


PRIORITIES = ("balanced", "cost", "crop", "grid")
APPLIES = ("once", "cold", "always")

#: What a model may ask for. Anything else in its reply is dropped.
MODEL_SYSTEM = """\
A grower disagreed with part of tomorrow's greenhouse energy plan and gave a short
reason. Translate the reason into planner settings, using ONLY these keys:

  "avoid_chp_hours": list of hours 0-23 when the CHP must stay off
  "switch_penalty_eur": 60 when the plan should switch equipment less (few staff)
  "night_temp_c": the night temperature to plan for, when the grower expects cold
  "battery_reserve_pct": battery reserve to keep, 0-95
  "prefer_stored_heat": true to use the heat buffer first, false to keep it full
  "priority": one of "balanced", "cost", "crop", "grid"
  "import_caps": {"hour": kW} upper limits on grid import for some hours

Return ONLY this JSON:
{"effects": {...}, "applies": "once" | "cold" | "always"}

"applies" is "always" for a standing rule, "cold" for something that holds on cold
days, otherwise "once". If the reason does not call for any of these settings,
return {"effects": {}, "applies": "once"}. Never invent a setting the grower did
not ask for."""


def _number(value: Any, low: float, high: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return min(high, max(low, number))


def _hour_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    hours = set()
    for item in value:
        hour = _number(item, -1, 24)
        if hour is not None and float(item) == int(hour) and 0 <= hour <= 23:
            hours.add(int(hour))
    return sorted(hours)


def clean_effects(raw: Any) -> dict[str, Any]:
    """Keep only known effects with values in range; drop everything else."""
    if not isinstance(raw, dict):
        return {}
    effects: dict[str, Any] = {}
    hours = _hour_list(raw.get("avoid_chp_hours"))
    if hours:
        effects["avoid_chp_hours"] = hours
    if "switch_penalty_eur" in raw:
        penalty = _number(raw["switch_penalty_eur"], 0, 200)
        if penalty:
            effects["switch_penalty_eur"] = penalty
    if "night_temp_c" in raw:
        temp = _number(raw["night_temp_c"], -25, 15)
        if temp is not None:
            effects["night_temp_c"] = temp
    if "battery_reserve_pct" in raw:
        reserve = _number(raw["battery_reserve_pct"], 0, 95)
        if reserve is not None:
            effects["battery_reserve_pct"] = reserve
    if isinstance(raw.get("prefer_stored_heat"), bool):
        effects["prefer_stored_heat"] = raw["prefer_stored_heat"]
    if raw.get("priority") in PRIORITIES:
        effects["priority"] = raw["priority"]
    caps = raw.get("import_caps")
    if isinstance(caps, dict):
        cleaned = {}
        for hour, kw in caps.items():
            hour_value = _number(hour, -1, 24)
            limit = _number(kw, 0, 1_000_000)
            if hour_value is not None and 0 <= hour_value <= 23 and limit:
                cleaned[int(hour_value)] = limit
        if cleaned:
            effects["import_caps"] = cleaned
    return effects


def _span(hours: list[int], nl: bool) -> str:
    if len(hours) >= 24:
        return "de hele dag" if nl else "all day"
    return ", ".join(f"{h:02d}:00" for h in hours) if len(hours) <= 3 else (
        f"{hours[0]:02d}:00–{(hours[-1] + 1) % 24:02d}:00")


def describe_effects(effects: dict[str, Any], language: str = "en") -> list[str]:
    """Say in words what the effects change, from the effects themselves."""
    nl = language == "nl"
    said: list[str] = []
    if effects.get("avoid_chp_hours"):
        span = _span(effects["avoid_chp_hours"], nl)
        said.append(f"WKK uit {span}" if nl else f"CHP off {span}")
    if effects.get("switch_penalty_eur"):
        said.append("minder schakelingen, rustiger plan" if nl
                    else "fewer equipment switches, a steadier plan")
    if "night_temp_c" in effects:
        said.append(f"rekenen met een nacht van {effects['night_temp_c']:.0f} °C" if nl
                    else f"plan for a {effects['night_temp_c']:.0f} °C night")
    if "battery_reserve_pct" in effects:
        said.append(f"{effects['battery_reserve_pct']:.0f}% batterijreserve" if nl
                    else f"keep {effects['battery_reserve_pct']:.0f}% battery reserve")
    if "prefer_stored_heat" in effects:
        said.append(("opgeslagen warmte eerst" if effects["prefer_stored_heat"]
                     else "warmtebuffer vol houden") if nl else
                    ("stored heat first" if effects["prefer_stored_heat"]
                     else "keep the heat buffer full"))
    if effects.get("priority"):
        names = {"en": {"balanced": "balanced", "cost": "lowest cost", "crop": "crop first",
                        "grid": "lower grid peak"},
                 "nl": {"balanced": "gebalanceerd", "cost": "laagste kosten",
                        "crop": "gewas eerst", "grid": "lagere netpiek"}}
        said.append(names["nl" if nl else "en"][effects["priority"]])
    if effects.get("import_caps"):
        caps = effects["import_caps"]
        hours = sorted(caps)
        kw = min(caps.values())
        said.append(f"maximaal {kw / 1000:.1f} MW van het net {_span(hours, nl)}" if nl else
                    f"at most {kw / 1000:.1f} MW from the grid {_span(hours, nl)}")
    return said


def read_with_model(reason: str, dimension: str, language: str,
                    call: Callable[[str, str], str]) -> dict[str, Any] | None:
    """Ask a model to read a reason the rules could not, within the same effects.

    ``call(system, prompt)`` returns the model's text. Returns a reading like
    :func:`interpret` with ``source`` set to ``"ai"``, or None when the model finds
    no effect or its reply cannot be used. The caller treats None as "the rules'
    reading stands"; errors from ``call`` itself are the caller's to handle.
    """
    from kasflex.conversation import _extract_json  # noqa: PLC0415

    prompt = (f"Language: {language}. Part of the plan: {dimension or 'general'}.\n"
              f"The grower's reason: {reason}")
    try:
        data = _extract_json(call(MODEL_SYSTEM, prompt))
    except ValueError:
        return None
    effects = clean_effects(data.get("effects"))
    if not effects:
        return None
    applies = data.get("applies") if data.get("applies") in APPLIES else "once"
    nl = language == "nl"
    summary = (("KasFlex (AI) leest dit als: " if nl else "KasFlex (AI) reads this as: ")
               + "; ".join(describe_effects(effects, language)))
    return {"effects": effects, "applies": applies, "summary": summary, "source": "ai"}


__all__ = ["apply_effects", "clean_effects", "describe_effects", "interpret", "read_with_model"]
