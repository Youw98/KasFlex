"""Fixed workshop scenarios: a set day, a story, and sometimes a trap.

A stakeholder workshop needs the same day in front of every participant, not a
random draw. Each scenario fixes the prices, the weather and the grid contract,
and tells the participant where they stand ("It's Monday morning...").

Two kinds:

* ``good``: the AI's plan is sensible and the participant can agree with it.
* ``flawed``: the story tells the participant something the planner never sees,
  such as a grid operator's curtailment notice or a CHP maintenance visit (or, in
  a custom scenario, a frost warning the forecast has not picked up). The AI's
  plan is wrong for that reason. The point is whether the participant notices,
  disagrees, and says why, so the AI can correct it.

The flaw is deliberate and honest: the participant is told the fact in the story;
only the planner is not. The ``debrief`` text says what the trap was, for the
facilitator.

Built-in scenarios are defined here. Custom ones, made on the admin screen, are
JSON files in ``results/scenarios`` and can override a built-in by id.
"""

from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

HOURS = 24
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,40}$")
KINDS = ("good", "flawed")
FLAW_TYPES = ("", "forecast_miss", "hidden_maintenance", "hidden_curtailment")
#: Scenario installation settings -> (path in the scenario config, lowest, highest).
HUB_FIELDS: dict[str, tuple[tuple[str, ...], float, float]] = {
    "boiler_kw": (("boiler", "thermal_capacity_kw"), 0.0, 50_000.0),
    "buffer_kwh": (("buffer", "capacity_kwh"), 0.0, 200_000.0),
    "battery_kwh": (("battery", "capacity_kwh"), 0.0, 50_000.0),
    "import_limit_kw": (("contract", "import_limit_kw"), 0.0, 50_000.0),
}
NIGHT_HOURS = (0, 1, 2, 3, 4, 5, 6, 7, 20, 21, 22, 23)


@dataclass
class Scenario:
    """One workshop day. Prices in EUR/kWh, temperatures in deg C, both hourly."""

    id: str
    kind: str
    title: dict[str, str]
    framing: dict[str, str]
    debrief: dict[str, str]
    date: str
    winter: bool = True
    seed: int = 0
    prices_eur_kwh: list[float] = field(default_factory=list)
    temperatures_c: list[float] = field(default_factory=list)
    irradiance_scale: float = 1.0
    grid_contract_type: str = "cbc"
    hub: dict[str, float] = field(default_factory=dict)
    """Installation changes for this day, by name: see :data:`HUB_FIELDS`."""
    flaw: dict[str, Any] = field(default_factory=dict)
    builtin: bool = False

    def text(self, key: str, language: str = "en") -> str:
        values = getattr(self, key)
        return values.get(language) or values.get("en", "")

    def validate(self) -> None:
        if not _ID.match(self.id):
            raise ValueError("scenario id: 2-41 lowercase letters, digits, - or _")
        if self.kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        for name in ("prices_eur_kwh", "temperatures_c"):
            values = getattr(self, name)
            if values and len(values) != HOURS:
                raise ValueError(f"{name} needs 24 hourly values, got {len(values)}")
        if any(not -0.5 <= p <= 5.0 for p in self.prices_eur_kwh):
            raise ValueError("prices must be between -0.50 and 5.00 EUR/kWh")
        if any(not -30 <= t <= 45 for t in self.temperatures_c):
            raise ValueError("temperatures must be between -30 and 45 deg C")
        if not 0 <= self.irradiance_scale <= 3:
            raise ValueError("irradiance_scale must be between 0 and 3")
        for name, value in self.hub.items():
            if name not in HUB_FIELDS:
                raise ValueError(f"unknown installation setting {name!r}")
            low, high = HUB_FIELDS[name][1:]
            if not low <= float(value) <= high:
                raise ValueError(f"{name} must be between {low:g} and {high:g}")
        flaw_type = str(self.flaw.get("type", ""))
        if flaw_type not in FLAW_TYPES:
            raise ValueError(f"flaw type must be one of {FLAW_TYPES}")
        if self.kind == "flawed" and not flaw_type:
            raise ValueError("a flawed scenario needs a flaw type")

    def to_dict(self, language: str | None = None) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        if language:
            data["title_text"] = self.text("title", language)
            data["framing_text"] = self.text("framing", language)
            data["debrief_text"] = self.text("debrief", language)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Scenario:
        known = {f.name for f in dataclasses.fields(cls)}
        values = {k: v for k, v in data.items() if k in known}
        for key in ("title", "framing", "debrief"):
            raw = values.get(key) or {}
            values[key] = {lang: str(text)[:2000] for lang, text in dict(raw).items()
                           if lang in ("en", "nl")}
        values["prices_eur_kwh"] = [float(v) for v in values.get("prices_eur_kwh") or []]
        values["temperatures_c"] = [float(v) for v in values.get("temperatures_c") or []]
        values["hub"] = {str(k): float(v) for k, v in dict(values.get("hub") or {}).items()}
        values["builtin"] = False
        scenario = cls(**values)
        scenario.validate()
        return scenario


def _ct(*values: float) -> list[float]:
    return [round(v / 100, 4) for v in values]


BUILTIN: tuple[Scenario, ...] = (
    Scenario(
        id="evening-peak", kind="good", date="2023-01-16", winter=True, seed=3,
        title={"en": "Evening price spike", "nl": "Prijspiek in de avond"},
        framing={
            "en": "It's Monday morning in January. You run a 5 ha lit tomato greenhouse in "
                  "the Westland. Tomorrow electricity is cheap at night and very expensive "
                  "between 17:00 and 20:00. KasFlex has made a plan for tomorrow.",
            "nl": "Het is maandagochtend in januari. U runt een belichte tomatenkas van 5 ha "
                  "in het Westland. Morgen is stroom 's nachts goedkoop en tussen 17:00 en "
                  "20:00 erg duur. KasFlex heeft een plan voor morgen gemaakt.",
        },
        debrief={
            "en": "A good plan: the lamps go off during the spike, the battery and the heat "
                  "buffer filled earlier by the CHP carry the evening, and nothing is bought "
                  "from the grid at the dearest hours.",
            "nl": "Een goed plan: de lampen gaan uit tijdens de piek, de batterij en de "
                  "warmtebuffer, eerder gevuld door de WKK, dragen de avond, en op de duurste "
                  "uren wordt niets van het net gekocht.",
        },
        prices_eur_kwh=_ct(6, 5.5, 5, 5, 5.5, 7, 10, 13, 14, 12, 10, 9,
                           9, 9.5, 11, 14, 19, 34, 38, 31, 18, 12, 9, 7),
        temperatures_c=[1, 0.5, 0, -0.5, -1, -1, -0.5, 0, 1, 2.5, 4, 5,
                        5.5, 6, 5.5, 4.5, 3, 2, 1.5, 1, 1, 0.5, 0.5, 0],
        grid_contract_type="cbc", builtin=True,
    ),
    Scenario(
        id="spring-sun", kind="good", date="2023-04-18", winter=False, seed=11,
        title={"en": "Sunny spring day", "nl": "Zonnige voorjaarsdag"},
        framing={
            "en": "It's Monday morning in April. Tomorrow will be sunny and mild. Solar "
                  "power pushes midday electricity prices close to zero. KasFlex has made "
                  "a plan for tomorrow.",
            "nl": "Het is maandagochtend in april. Morgen wordt het zonnig en zacht. "
                  "Zonnestroom drukt de stroomprijs rond het middaguur bijna naar nul. "
                  "KasFlex heeft een plan voor morgen gemaakt.",
        },
        debrief={
            "en": "A good plan: little supplemental light is needed, the battery fills on "
                  "cheap midday power and the boiler covers the small heat demand.",
            "nl": "Een goed plan: er is weinig extra licht nodig, de batterij laadt met "
                  "goedkope middagstroom en de ketel dekt de kleine warmtevraag.",
        },
        prices_eur_kwh=_ct(9, 8.5, 8, 8, 8.5, 9.5, 11, 12, 9, 5, 2, 0.5,
                           -0.5, 0, 1.5, 4, 8, 13, 16, 15, 12, 10.5, 10, 9.5),
        temperatures_c=[7, 6.5, 6, 5.5, 5.5, 6, 7.5, 9.5, 12, 14, 15.5, 17,
                        18, 18.5, 18.5, 18, 17, 15.5, 13.5, 11.5, 10, 9, 8, 7.5],
        irradiance_scale=1.2, grid_contract_type="time_block", builtin=True,
    ),
    Scenario(
        id="grid-notice", kind="flawed", date="2023-01-31", winter=True, seed=6,
        title={"en": "Grid operator notice", "nl": "Melding van de netbeheerder"},
        framing={
            "en": "It's Monday morning in January. This morning the grid operator emailed: "
                  "because of congestion you may take at most 1.5 MW from the grid tomorrow "
                  "between 16:00 and 20:00. Electricity is reasonably priced in the evening. "
                  "KasFlex has made a plan for tomorrow.",
            "nl": "Het is maandagochtend in januari. De netbeheerder mailde vanochtend: door "
                  "congestie mag u morgen tussen 16:00 en 20:00 maximaal 1,5 MW van het net "
                  "halen. Stroom is 's avonds redelijk geprijsd. KasFlex heeft een plan voor "
                  "morgen gemaakt.",
        },
        debrief={
            "en": "The trap: the email never reached the planner, which still plans with the "
                  "normal contract and takes more than 1.5 MW in the evening. A participant "
                  "who disagrees and names the hours and the limit gets a plan that keeps "
                  "to it.",
            "nl": "De valkuil: de mail heeft de planner nooit bereikt, die nog met het normale "
                  "contract plant en 's avonds meer dan 1,5 MW afneemt. Wie het oneens is en "
                  "de uren en de grens noemt, krijgt een plan dat zich eraan houdt.",
        },
        prices_eur_kwh=_ct(9, 8.5, 8, 8, 8.5, 10, 14, 19, 21, 18, 15, 13,
                           12, 12, 13, 14, 13, 12, 11.5, 11, 10, 9.5, 9, 9),
        temperatures_c=[2.5, 2, 2, 1.5, 1.5, 1.5, 2, 2.5, 3.5, 4.5, 5.5, 6,
                        6.5, 6.5, 6, 5, 4, 3.5, 3, 3, 2.5, 2.5, 2.5, 2.5],
        grid_contract_type="firm",
        flaw={"type": "hidden_curtailment", "hours": [16, 17, 18, 19], "import_kw": 1500.0},
        builtin=True,
    ),
    Scenario(
        id="chp-maintenance", kind="flawed", date="2023-01-24", winter=True, seed=8,
        title={"en": "CHP maintenance visit", "nl": "Onderhoud aan de WKK"},
        framing={
            "en": "It's Monday morning in January. The mechanic is coming tomorrow from "
                  "08:00 to 14:00 to service the CHP, so it has to stay off then. Power "
                  "prices are high all morning. KasFlex has made a plan for tomorrow.",
            "nl": "Het is maandagochtend in januari. Morgen komt de monteur van 08:00 tot "
                  "14:00 de WKK onderhouden, dus die moet dan uit blijven. De stroomprijs is "
                  "de hele ochtend hoog. KasFlex heeft een plan voor morgen gemaakt.",
        },
        debrief={
            "en": "The trap: nobody told the planner about the maintenance, and high "
                  "morning prices make the CHP attractive, so the plan runs it during the "
                  "visit. A participant who disagrees with 'fits how I work' and names the "
                  "hours gets a plan without the CHP then.",
            "nl": "De valkuil: niemand heeft de planner over het onderhoud verteld, en de "
                  "hoge ochtendprijzen maken de WKK aantrekkelijk, dus het plan laat hem "
                  "draaien tijdens het bezoek. Wie het oneens is bij 'past bij mijn "
                  "werkwijze' en de uren noemt, krijgt een plan zonder WKK op die uren.",
        },
        prices_eur_kwh=_ct(9, 8.5, 8, 8, 8.5, 11, 18, 26, 30, 31, 29, 27,
                           25, 24, 21, 18, 17, 19, 20, 17, 13, 11, 10, 9),
        temperatures_c=[0, -0.5, -1, -1.5, -1.5, -1, -0.5, 0, 1, 2, 3, 3.5,
                        4, 4, 3.5, 3, 2, 1.5, 1, 0.5, 0.5, 0, 0, 0],
        grid_contract_type="cbc",
        flaw={"type": "hidden_maintenance", "asset": "chp", "hours": list(range(8, 14))},
        builtin=True,
    ),
)


class ScenarioStore:
    """Built-in scenarios plus custom ones saved as JSON files."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def _custom(self) -> dict[str, Scenario]:
        found: dict[str, Scenario] = {}
        if not self.directory.is_dir():
            return found
        for path in sorted(self.directory.glob("*.json")):
            try:
                scenario = Scenario.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue  # a broken file must not take the workshop down
            found[scenario.id] = scenario
        return found

    def all(self) -> list[Scenario]:
        merged = {s.id: s for s in BUILTIN}
        merged.update(self._custom())
        return list(merged.values())

    def get(self, scenario_id: str) -> Scenario:
        for scenario in self.all():
            if scenario.id == scenario_id:
                return scenario
        raise KeyError(scenario_id)

    def save(self, data: dict[str, Any]) -> Scenario:
        scenario = Scenario.from_dict(data)
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / f"{scenario.id}.json").write_text(
            json.dumps(scenario.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return scenario

    def delete(self, scenario_id: str) -> bool:
        path = self.directory / f"{scenario_id}.json"
        if _ID.match(scenario_id) and path.is_file():
            path.unlink()
            return True
        return False


def scenario_day(scenario: Scenario, *, floor_area_m2: float, gas_price_eur_kwh: float):
    """The planning forecast and the realised day for one scenario.

    The forecast is what the planner sees. The actual is what the day turns out to
    be, which only differs for a ``forecast_miss`` flaw: the night is colder than
    forecast, by the amount the story warned about.
    """
    from kasflex.data.synthetic import synthetic_day  # noqa: PLC0415

    base = synthetic_day(scenario.date, seed=scenario.seed, floor_area_m2=floor_area_m2,
                         winter=scenario.winter, forecast_error=False)

    def shaped(rows, *, actual: bool):
        out = []
        for hour, row in enumerate(rows):
            changes: dict[str, Any] = {"gas_price_eur_kwh": gas_price_eur_kwh,
                                       "irradiance_w_m2": row.irradiance_w_m2
                                       * scenario.irradiance_scale}
            if scenario.prices_eur_kwh:
                changes["power_price_eur_kwh"] = scenario.prices_eur_kwh[hour]
                changes["feed_in_price_eur_kwh"] = None
            if scenario.temperatures_c:
                changes["outdoor_temp_c"] = scenario.temperatures_c[hour]
            if actual and scenario.flaw.get("type") == "forecast_miss" and hour in NIGHT_HOURS:
                drop = float(scenario.flaw.get("night_temp_drop_c", 8.0))
                changes["outdoor_temp_c"] = changes.get("outdoor_temp_c",
                                                        row.outdoor_temp_c) - drop
            out.append(dataclasses.replace(row, **changes))
        return tuple(out)

    return SimpleNamespace(
        forecast=shaped(base.forecast, actual=False),
        actual=shaped(base.forecast, actual=True),
        actuals_available=True,
        sources={"prices": "workshop scenario", "weather": "workshop scenario"},
    )


__all__ = ["BUILTIN", "Scenario", "ScenarioStore", "scenario_day"]
