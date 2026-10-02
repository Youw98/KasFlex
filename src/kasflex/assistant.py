"""Answers grower questions from the plan's own numbers, without a language model.

The chat panel uses a configured model (Claude, OpenAI, Gemini or a local Ollama
model) when there is one. When there is none, for instance on a workshop laptop
with no key and no internet, this module answers instead. It recognises what the
question is about and answers from the plan, the prices and the weather, so every
number it gives is one the plan really has. It never guesses: a question it does
not recognise gets a short summary and examples of what it can answer.
"""

from __future__ import annotations

import re
from typing import Any

_HOUR = re.compile(
    r"\b(?:om|at|rond|around|tussen|between)?\s*(\d{1,2})(?:[:.]00|\s*(?:uur|u|h)\b)")

TOPICS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("temperature", ("temperatu", "warmer", "colder", "kouder", "graden", "degrees",
                     "setpoint", "stooklijn", "verwarmingsdoel", "heating target", "°c")),
    ("battery", ("battery", "batterij", "accu", "charge", "laden", "ontladen")),
    ("chp", ("chp", "wkk", "warmtekracht", "motor")),
    ("lights", ("light", "licht", "lamp", "belicht", "assimilat")),
    ("grid", ("grid", "net ", "netwerk", "peak", "piek", "contract", "congest", "kw max")),
    ("heat", ("heat", "warmte", "buffer", "ketel", "boiler", "stoken")),
    ("cost", ("cost", "kost", "save", "bespa", "euro", "€", "price", "prijs", "duur", "cheap",
              "goedkoop")),
    ("weather", ("weather", "weer", "sun", "zon", "frost", "vorst", "cold", "koud")),
    ("remember", ("remember", "onthoud", "last time", "vorige keer", "eerder")),
)


def _topic(text: str) -> str:
    for name, words in TOPICS:
        if any(word in text for word in words):
            return name
    return ""


def _hours_text(hours: list[int]) -> str:
    if not hours:
        return "—"
    runs, start, prev = [], hours[0], hours[0]
    for hour in hours[1:] + [None]:
        if hour is not None and hour == prev + 1:
            prev = hour
            continue
        runs.append(f"{start:02d}:00–{(prev + 1) % 24:02d}:00")
        if hour is not None:
            start = prev = hour
    return ", ".join(runs)


def answer(question: str, run: dict[str, Any], *, language: str = "en",
           remembered: list[str] | None = None,
           passages: list[dict[str, Any]] | None = None) -> str:
    """One answer, two to four sentences, from the plan's numbers and documents.

    ``passages`` are document passages that match the question (see
    :mod:`kasflex.documents`). When the question is about something the plan does
    not cover, the best passage is the answer; otherwise it is added as a source.
    """
    reply = _from_plan(question, run, language=language, remembered=remembered)
    if not passages:
        return reply
    nl = language == "nl"
    best = passages[0]
    quote = f"{best['passage']}" if len(best["passage"]) < 420 else best["passage"][:400] + "…"
    if reply.startswith(("Kort:", "In short:")):
        return (f"Uit “{best['title']}”: {quote}" if nl else f"From “{best['title']}”: {quote}")
    return reply + (f"\n\nUit “{best['title']}”: {quote}" if nl else
                    f"\n\nFrom “{best['title']}”: {quote}")


def _from_plan(question: str, run: dict[str, Any], *, language: str = "en",
               remembered: list[str] | None = None) -> str:
    nl = language == "nl"
    text = " " + " ".join(str(question or "").lower().split()) + " "
    plan = run.get("plan") or []
    metrics = run.get("metrics") or {}
    if not plan:
        return ("Maak eerst een plan, dan kan ik erover vertellen." if nl else
                "Build a plan first, then I can tell you about it.")

    match = _HOUR.search(text)
    if match and 0 <= int(match.group(1)) <= 23 and ("waarom" in text or "why" in text
                                                     or "what" in text or "wat" in text):
        row = plan[int(match.group(1))]
        battery = (row["battery"] if row["battery"] == "idle"
                   else f"{row['battery']} {row['battery_power_kw']:.0f} kW")
        return ((f"Om {row['hour']:02d}:00 kost stroom {row['power_price_eur_kwh'] * 100:.1f} "
                 f"ct/kWh. Het plan: warmte uit {row['heat_source']}, lampen "
                 f"{row['lighting_level'] * 100:.0f}%, batterij {battery}, WKK "
                 f"{row['chp_mode']}. Reden: {row.get('reasoning', '')}.") if nl else
                (f"At {row['hour']:02d}:00 power costs {row['power_price_eur_kwh'] * 100:.1f} "
                 f"ct/kWh. The plan: heat from {row['heat_source']}, lamps "
                 f"{row['lighting_level'] * 100:.0f}%, battery {battery}, CHP "
                 f"{row['chp_mode']}. Reason: {row.get('reasoning', '')}."))

    topic = _topic(text)
    prices = [r["power_price_eur_kwh"] for r in plan]
    cheap = sorted(range(24), key=lambda h: prices[h])[:5]
    dear = sorted(range(24), key=lambda h: prices[h], reverse=True)[:5]

    if topic == "temperature":
        band = metrics.get("temperature_band_hours", 0)
        set_points = {t["key"]: t["value"] for t in run.get("targets") or []
                      if t.get("key") in ("heat_day_c", "heat_night_c") and t.get("met")}
        if set_points:
            def shown(key: str, standard: str) -> str:
                return f"{set_points[key]:g} °C" if key in set_points else standard

            day = shown("heat_day_c", "standaard" if nl else "standard")
            night = shown("heat_night_c", "standaard" if nl else "standard")
            return ((f"Het plan verwarmt naar uw doelen: {day} overdag, {night} 's nachts. "
                     "Elke graad warmer kost meer warmte, dus meer gas of WKK-uren; zet een lager "
                     "doel en plan opnieuw om het verschil in euro's te zien. De kas blijft "
                     f"{band:.0f} van de 24 uur binnen de temperatuurband.") if nl else
                    (f"The plan heats to your targets: {day} by day, {night} at night. "
                     "Every degree warmer takes more heat, so more gas or CHP hours; set a lower "
                     "target and rebuild to see the difference in euros. The greenhouse stays "
                     f"inside its temperature band {band:.0f} of 24 hours."))
        return ("KasFlex stelt de kastemperatuur niet zelf in; die blijft bij uw klimaatcomputer. "
                f"KasFlex kiest waar de warmte vandaan komt. In de simulatie blijft de kas "
                f"{band:.0f} van de 24 uur binnen de temperatuurband. U kunt een "
                "verwarmingsdoel instellen bij 'Uw eigen grenzen en doelen'." if nl else
                "KasFlex does not set the greenhouse temperature; your climate computer keeps "
                "that. KasFlex chooses where the heat comes from. In the simulation the "
                f"greenhouse stays inside its temperature band {band:.0f} of 24 hours. You can "
                "set a heating target under 'Your own targets and goals'.")
    if topic == "battery":
        charge = [r["hour"] for r in plan if r["battery"] == "charge"]
        discharge = [r["hour"] for r in plan if r["battery"] == "discharge"]
        return ((f"De batterij laadt {_hours_text(charge)} en levert {_hours_text(discharge)}. "
                 f"De goedkoopste uren zijn {_hours_text(sorted(cheap))}, de duurste "
                 f"{_hours_text(sorted(dear))}: goedkoop inkopen, duur niet.") if nl else
                (f"The battery charges {_hours_text(charge)} and discharges "
                 f"{_hours_text(discharge)}. The cheapest hours are {_hours_text(sorted(cheap))}, "
                 f"the dearest {_hours_text(sorted(dear))}: buy cheap, avoid dear."))
    if topic == "chp":
        running = [r["hour"] for r in plan if r["chp_mode"] != "off"]
        if not running:
            return ("De WKK draait morgen niet: stroom is nergens duur genoeg om gas om te zetten."
                    if nl else
                    "The CHP does not run tomorrow: power is nowhere dear enough to turn gas "
                    "into electricity.")
        return ((f"De WKK draait {_hours_text(running)}. Dan is stroom duur genoeg dat eigen "
                 "opwek goedkoper is dan inkopen, en de warmte gaat naar de kas of de buffer.")
                if nl else
                (f"The CHP runs {_hours_text(running)}. Power is dear enough then that making "
                 "it yourself beats buying it, and the heat goes to the greenhouse or the "
                 "buffer."))
    if topic == "lights":
        lit = [r["hour"] for r in plan if r["lighting_level"] > 0]
        dli = metrics.get("supplemental_dli_mol_m2", 0)
        return ((f"De lampen branden {_hours_text(lit)} en geven {dli:.1f} mol/m² extra licht. "
                 "Ze gaan uit in de duurste uren.") if nl else
                (f"The lamps are on {_hours_text(lit)} and add {dli:.1f} mol/m² of light. "
                 "They go off in the dearest hours."))
    if topic == "grid":
        peak = metrics.get("peak_import_kw", 0)
        limit = (run.get("grid") or {}).get("import_limit_kw") or 0
        tail = (f" De contractgrens is {limit / 1000:.1f} MW." if nl else
                f" The contract limit is {limit / 1000:.1f} MW.") if limit else ""
        return ((f"De hoogste afname van het net is {peak / 1000:.2f} MW.{tail} De controle "
                 "keurt geen plan goed dat over het contract gaat.") if nl else
                (f"The highest grid import is {peak / 1000:.2f} MW.{tail} The check never "
                 "approves a plan that breaks the contract."))
    if topic == "heat":
        sources: dict[str, int] = {}
        for row in plan:
            sources[row["heat_source"]] = sources.get(row["heat_source"], 0) + 1
        parts = ", ".join(f"{name} {count} h" for name, count in
                          sorted(sources.items(), key=lambda item: -item[1]))
        return ((f"Warmte per bron: {parts}. De buffer vangt warmte op als de WKK draait en "
                 "geeft die af in dure uren.") if nl else
                (f"Heat by source: {parts}. The buffer stores heat while the CHP runs and "
                 "gives it back in dear hours."))
    if topic == "cost":
        normal = run.get("normal_settings") or {}
        saving = float(normal.get("saving_eur", 0) or 0)
        return ((f"Het plan kost naar verwachting €{metrics.get('net_cost_eur', 0):,.0f}, "
                 f"€{abs(saving):,.0f} {'minder' if saving >= 0 else 'meer'} dan de normale "
                 f"regeling. Stroom is het goedkoopst {_hours_text(sorted(cheap))}.") if nl else
                (f"The plan should cost €{metrics.get('net_cost_eur', 0):,.0f}, "
                 f"€{abs(saving):,.0f} {'less' if saving >= 0 else 'more'} than normal "
                 f"control. Power is cheapest {_hours_text(sorted(cheap))}."))
    if topic == "weather":
        temps = [r.get("outdoor_temp_c", 0) for r in plan]
        return ((f"De verwachting die KasFlex gebruikt: {min(temps):.0f} tot {max(temps):.0f} °C. "
                 "Weet u iets wat de verwachting mist, zoals een vorstwaarschuwing? Zeg het bij "
                 "'Oneens', dan rekent KasFlex ermee.") if nl else
                (f"The forecast KasFlex uses: {min(temps):.0f} to {max(temps):.0f} °C. Do you "
                 "know something the forecast misses, like a frost warning? Say so under "
                 "'Disagree' and KasFlex will plan with it."))
    if topic == "remember":
        items = remembered or []
        if not items:
            return ("Ik heb nog niets van u onthouden." if nl else
                    "I have not remembered anything from you yet.")
        joined = "; ".join(f"'{item}'" for item in items[:5])
        return (f"Dit heeft u eerder gezegd: {joined}." if nl else
                f"You told me before: {joined}.")

    return ((f"Kort: het plan kost €{metrics.get('net_cost_eur', 0):,.0f} en geeft "
             f"{metrics.get('supplemental_dli_mol_m2', 0):.1f} mol/m² extra licht. U kunt "
             "vragen naar de batterij, de WKK, de lampen, de warmte, het net, de kosten of "
             "een uur (bijvoorbeeld 'waarom om 18 uur?').") if nl else
            (f"In short: the plan costs €{metrics.get('net_cost_eur', 0):,.0f} and adds "
             f"{metrics.get('supplemental_dli_mol_m2', 0):.1f} mol/m² of light. Ask about the "
             "battery, the CHP, the lamps, the heat, the grid, the cost or an hour "
             "(for example 'why at 18:00?')."))


__all__ = ["answer"]
