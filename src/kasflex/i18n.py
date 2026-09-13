"""English and Dutch, from one catalogue.

Dutch is not decoration here. The growers this is built for run glasshouses in the
Westland, and asking someone to make an operational decision in their second
language while also learning an unfamiliar system is how pilots fail. Language is
a configuration field, and it reaches three places:

* **The interface.** Every grower-facing string is a key, looked up at render time.
* **The model.** :func:`language_instruction` is appended to every system prompt,
  so explanations come back in the grower's language rather than being translated
  after the fact and losing the reasoning.
* **Formatting.** Dutch writes ``€ 1.234,50`` and ``13.00 uur``; English writes
  ``€1,234.50`` and ``13:00``. Getting this wrong makes a system feel foreign even
  when every word is right.

Keys are dotted and grouped by surface. A missing key returns the key itself rather
than raising: a half-translated screen is recoverable, a crash in front of a grower
is not. :func:`missing_keys` keeps that leniency honest by failing in the tests.
"""

from __future__ import annotations

from typing import Any

LANGUAGES: dict[str, dict[str, str]] = {
    "en": {"code": "en", "name": "English", "endonym": "English", "flag": "🇬🇧"},
    "nl": {"code": "nl", "name": "Dutch", "endonym": "Nederlands", "flag": "🇳🇱"},
}
DEFAULT_LANGUAGE = "en"

# Each entry is key -> {language code -> text}. Kept as one table rather than one
# file per language so a translator can see both columns and a reviewer can see
# at a glance which strings have drifted apart.
CATALOG: dict[str, dict[str, str]] = {
    # -- shell and navigation ------------------------------------------------
    "app.name": {"en": "KasFlex", "nl": "KasFlex"},
    "app.tagline": {"en": "Energy planning for your greenhouse",
                    "nl": "Energieplanning voor uw kas"},
    "nav.today": {"en": "Today's plan", "nl": "Plan van vandaag"},
    "nav.chat": {"en": "Ask why", "nl": "Vraag waarom"},
    "nav.preferences": {"en": "What I've told it", "nl": "Wat ik heb doorgegeven"},
    "nav.history": {"en": "Earlier plans", "nl": "Eerdere plannen"},
    "nav.settings": {"en": "Settings", "nl": "Instellingen"},
    "nav.research": {"en": "Research mode", "nl": "Onderzoeksmodus"},
    "common.back": {"en": "Back", "nl": "Terug"},
    "common.next": {"en": "Next", "nl": "Volgende"},
    "common.save": {"en": "Save", "nl": "Opslaan"},
    "common.cancel": {"en": "Cancel", "nl": "Annuleren"},
    "common.close": {"en": "Close", "nl": "Sluiten"},
    "common.loading": {"en": "One moment…", "nl": "Een moment…"},
    "common.error": {"en": "Something went wrong", "nl": "Er ging iets mis"},
    "common.retry": {"en": "Try again", "nl": "Opnieuw proberen"},
    "common.undo": {"en": "Undo", "nl": "Ongedaan maken"},
    "common.yes": {"en": "Yes", "nl": "Ja"},
    "common.no": {"en": "No", "nl": "Nee"},
    "common.hour": {"en": "Hour", "nl": "Uur"},
    "common.today": {"en": "Today", "nl": "Vandaag"},
    "common.tomorrow": {"en": "Tomorrow", "nl": "Morgen"},
    "common.optional": {"en": "optional", "nl": "optioneel"},

    # -- onboarding ----------------------------------------------------------
    "onboard.welcome.title": {"en": "Welcome to KasFlex",
                              "nl": "Welkom bij KasFlex"},
    "onboard.welcome.body": {
        "en": "KasFlex plans your greenhouse's energy for tomorrow and explains "
              "every choice. You stay in charge: nothing runs without your approval.",
        "nl": "KasFlex plant de energie van uw kas voor morgen en legt elke keuze "
              "uit. U houdt de regie: er gebeurt niets zonder uw goedkeuring."},
    "onboard.welcome.start": {"en": "Set up my greenhouse", "nl": "Mijn kas instellen"},
    "onboard.welcome.load": {"en": "Load a saved setup", "nl": "Opgeslagen instelling laden"},
    "onboard.welcome.demo": {"en": "Just show me a demo first",
                             "nl": "Laat eerst een demo zien"},
    "onboard.step": {"en": "Step {n} of {total}", "nl": "Stap {n} van {total}"},
    "onboard.language.title": {"en": "Which language do you prefer?",
                               "nl": "Welke taal heeft uw voorkeur?"},
    "onboard.language.body": {"en": "You can change this at any time in Settings.",
                              "nl": "U kunt dit altijd wijzigen bij Instellingen."},
    "onboard.site.title": {"en": "Tell us about your greenhouse",
                           "nl": "Vertel ons over uw kas"},
    "onboard.site.name": {"en": "What should we call it?", "nl": "Hoe zullen we het noemen?"},
    "onboard.site.name.hint": {"en": "For example: Home site, Block 3",
                               "nl": "Bijvoorbeeld: Thuislocatie, Blok 3"},
    "onboard.site.area": {"en": "How big is it?", "nl": "Hoe groot is het?"},
    "onboard.site.area.hint": {"en": "In hectares. A rough number is fine.",
                               "nl": "In hectare. Een schatting is prima."},
    "onboard.site.location": {"en": "Where is it?", "nl": "Waar staat het?"},
    "onboard.site.location.hint": {
        "en": "We use this for the weather forecast. Westland is filled in already.",
        "nl": "Dit gebruiken we voor de weersverwachting. Westland is al ingevuld."},
    "onboard.equipment.title": {"en": "What equipment do you have?",
                                "nl": "Welke installaties heeft u?"},
    "onboard.equipment.body": {
        "en": "Tick what applies. You can adjust the details later.",
        "nl": "Vink aan wat van toepassing is. Details kunt u later aanpassen."},
    "onboard.equipment.chp": {"en": "CHP (cogeneration)", "nl": "WKK (warmtekrachtkoppeling)"},
    "onboard.equipment.boiler": {"en": "Boiler", "nl": "Ketel"},
    "onboard.equipment.battery": {"en": "Battery storage", "nl": "Batterijopslag"},
    "onboard.equipment.buffer": {"en": "Heat buffer", "nl": "Warmtebuffer"},
    "onboard.equipment.lights": {"en": "Grow lights", "nl": "Groeilampen"},
    "onboard.equipment.pv": {"en": "Solar panels", "nl": "Zonnepanelen"},
    "onboard.ai.title": {"en": "Which AI should explain your plans?",
                         "nl": "Welke AI moet uw plannen uitleggen?"},
    "onboard.ai.body": {
        "en": "KasFlex works without one, but an AI can explain its choices and "
              "answer your questions. You can also run one on your own computer.",
        "nl": "KasFlex werkt ook zonder, maar een AI kan keuzes uitleggen en uw "
              "vragen beantwoorden. U kunt er ook één op uw eigen computer draaien."},
    "onboard.ai.skip": {"en": "Skip for now", "nl": "Voorlopig overslaan"},
    "onboard.ai.local.badge": {"en": "Stays on your computer",
                               "nl": "Blijft op uw computer"},
    "onboard.done.title": {"en": "You're set up", "nl": "U bent klaar"},
    "onboard.done.body": {
        "en": "We've saved this so you won't be asked again. Let's make your first plan.",
        "nl": "We hebben dit bewaard, dus dit wordt niet opnieuw gevraagd. "
              "Laten we uw eerste plan maken."},
    "onboard.done.cta": {"en": "Make my first plan", "nl": "Maak mijn eerste plan"},
    "onboard.profile.saved": {"en": "Setup saved as “{name}”",
                              "nl": "Instelling opgeslagen als “{name}”"},
    "onboard.profile.pick": {"en": "Which setup would you like to load?",
                             "nl": "Welke instelling wilt u laden?"},
    "onboard.profile.none": {"en": "No saved setups on this computer yet.",
                             "nl": "Nog geen opgeslagen instellingen op deze computer."},
    "onboard.profile.import": {"en": "Load from a file", "nl": "Laden uit een bestand"},
    "onboard.profile.export": {"en": "Save to a file", "nl": "Opslaan naar een bestand"},
    "onboard.profile.imported": {"en": "Setup loaded.", "nl": "Instelling geladen."},
    "onboard.profile.bad_file": {
        "en": "That file isn't a KasFlex setup. Pick the .json file you exported.",
        "nl": "Dat bestand is geen KasFlex-instelling. Kies het .json-bestand "
              "dat u heeft geëxporteerd."},

    # -- the plan ------------------------------------------------------------
    "plan.make": {"en": "Make tomorrow's plan", "nl": "Maak het plan voor morgen"},
    "plan.making": {"en": "Working out the best plan…",
                    "nl": "Bezig met het beste plan…"},
    "plan.empty.title": {"en": "No plan yet", "nl": "Nog geen plan"},
    "plan.empty.body": {"en": "Make a plan to see what tomorrow could cost.",
                        "nl": "Maak een plan om te zien wat morgen kan kosten."},
    "plan.headline.cost": {"en": "Tomorrow's energy bill", "nl": "Energierekening morgen"},
    "plan.headline.saving": {"en": "You save {amount} compared with doing nothing clever",
                             "nl": "U bespaart {amount} vergeleken met niets slims doen"},
    "plan.headline.crop": {"en": "Your crop", "nl": "Uw gewas"},
    "plan.crop.good": {"en": "Stays comfortable all day",
                       "nl": "Blijft de hele dag comfortabel"},
    "plan.crop.warning": {"en": "Gets a little cold at night",
                          "nl": "Wordt 's nachts wat koud"},
    "plan.crop.bad": {"en": "Would be outside safe limits",
                      "nl": "Zou buiten veilige grenzen komen"},
    "plan.safety.ok": {"en": "Checked and safe", "nl": "Gecontroleerd en veilig"},
    "plan.safety.bad": {"en": "The safety check found a problem",
                        "nl": "De veiligheidscontrole vond een probleem"},
    "plan.story.title": {"en": "What happens tomorrow", "nl": "Wat gebeurt er morgen"},
    "plan.details.show": {"en": "Show hour by hour", "nl": "Toon per uur"},
    "plan.details.hide": {"en": "Hide the details", "nl": "Verberg de details"},
    "plan.approve": {"en": "This looks good", "nl": "Dit ziet er goed uit"},
    "plan.concerns": {"en": "I have concerns", "nl": "Ik heb bedenkingen"},
    "plan.approved": {"en": "Approved. Thank you.", "nl": "Goedgekeurd. Dank u wel."},
    "plan.rejected": {"en": "Noted. Tell us what to change.",
                      "nl": "Genoteerd. Vertel ons wat er anders moet."},
    "plan.demo_notice": {
        "en": "This is a practice plan with made-up prices, so you can explore safely.",
        "nl": "Dit is een oefenplan met verzonnen prijzen, zodat u veilig kunt verkennen."},
    "plan.real_notice": {"en": "Using real electricity prices and the weather forecast.",
                         "nl": "Met echte stroomprijzen en de weersverwachting."},

    # -- how certain the plan is ---------------------------------------------
    "uncertain.label": {"en": "How certain is this?", "nl": "Hoe zeker is dit?"},
    "uncertain.high": {"en": "Fairly certain", "nl": "Redelijk zeker"},
    "uncertain.medium": {"en": "Reasonably certain", "nl": "Tamelijk zeker"},
    "uncertain.low": {"en": "Not very certain", "nl": "Niet erg zeker"},
    "uncertain.unknown": {"en": "Can't say yet", "nl": "Nog niet te zeggen"},
    "uncertain.why": {"en": "Why do you say that?", "nl": "Waarom zegt u dat?"},
    "uncertain.caveats": {"en": "What this range does not cover",
                          "nl": "Wat deze marge niet meeneemt"},

    # -- asking first (before the plan is shown) ------------------------------
    "elicit.title": {"en": "Before you see the plan", "nl": "Voordat u het plan ziet"},
    "elicit.why": {
        "en": "Your own view first. It helps us see where you and KasFlex agree, "
              "and it is not scored or shared.",
        "nl": "Eerst uw eigen beeld. Zo zien we waar u en KasFlex het eens zijn. "
              "Het wordt niet beoordeeld of gedeeld."},
    "elicit.heat.question": {"en": "How would you heat tomorrow?",
                             "nl": "Hoe zou u morgen verwarmen?"},
    "elicit.option.boiler": {"en": "Mostly the boiler", "nl": "Vooral de ketel"},
    "elicit.option.chp": {"en": "Mostly the CHP", "nl": "Vooral de WKK"},
    "elicit.option.mix": {"en": "A mix, depending on the hour",
                          "nl": "Een mix, afhankelijk van het uur"},
    "elicit.confidence": {"en": "How sure are you?", "nl": "Hoe zeker bent u?"},
    "elicit.confidence.1": {"en": "Guessing", "nl": "Gok"},
    "elicit.confidence.2": {"en": "Not very sure", "nl": "Niet erg zeker"},
    "elicit.confidence.3": {"en": "Reasonably sure", "nl": "Redelijk zeker"},
    "elicit.confidence.4": {"en": "Quite sure", "nl": "Vrij zeker"},
    "elicit.confidence.5": {"en": "Certain", "nl": "Zeker"},
    "elicit.submit": {"en": "Show me the plan", "nl": "Laat het plan zien"},
    "elicit.skip": {"en": "Just show the plan", "nl": "Laat gewoon het plan zien"},
    "elicit.agreed": {"en": "You and KasFlex agree on this.",
                      "nl": "U en KasFlex zijn het hierover eens."},
    "elicit.differed": {"en": "You said {yours}. KasFlex chose {theirs}.",
                        "nl": "U zei {yours}. KasFlex koos {theirs}."},

    # -- shell ---------------------------------------------------------------
    "app.subtitle": {"en": "Greenhouse energy planning",
                     "nl": "Energieplanning voor de kas"},
    "sim.mode": {"en": "SIMULATION MODE", "nl": "SIMULATIEMODUS"},
    "sim.note": {"en": "No physical equipment connected",
                 "nl": "Geen apparatuur aangesloten"},
    "nav.tomorrow": {"en": "Tomorrow", "nl": "Morgen"},
    "nav.plan": {"en": "Plan", "nl": "Plan"},
    "nav.goals": {"en": "Goals", "nl": "Doelen"},
    "nav.results": {"en": "Results", "nl": "Resultaten"},
    "nav.more": {"en": "More", "nl": "Meer"},
    "shell.plan_for": {"en": "Plan for tomorrow", "nl": "Plan voor morgen"},

    # -- Tomorrow ------------------------------------------------------------
    "tile.crop": {"en": "Crop", "nl": "Gewas"},
    "tile.climate": {"en": "Climate", "nl": "Klimaat"},
    "tile.cost": {"en": "Energy cost", "nl": "Energiekosten"},
    "tile.plan": {"en": "KasFlex plan", "nl": "KasFlex-plan"},
    "tile.crop.good": {"en": "Good", "nl": "Goed"},
    "tile.crop.good.note": {"en": "Plants are developing well",
                            "nl": "De planten ontwikkelen zich goed"},
    "tile.crop.watch": {"en": "Watch", "nl": "Let op"},
    "tile.crop.watch.note": {"en": "Conditions are tighter than usual",
                             "nl": "De omstandigheden zijn krapper dan normaal"},
    "tile.crop.risk": {"en": "At risk", "nl": "Risico"},
    "tile.crop.risk.note": {"en": "Would fall outside safe limits",
                            "nl": "Zou buiten de veilige grenzen vallen"},
    "tile.climate.ontarget": {"en": "On target", "nl": "Op koers"},
    "tile.climate.ontarget.note": {"en": "Temperature stays within range",
                                   "nl": "Temperatuur blijft binnen bereik"},
    "tile.climate.off": {"en": "Off target", "nl": "Buiten koers"},
    "tile.climate.off.note": {"en": "Some hours fall outside the band",
                              "nl": "Sommige uren vallen buiten de band"},
    "tile.cost.note": {"en": "Estimated for tomorrow", "nl": "Geschat voor morgen"},
    "tile.plan.ready": {"en": "Ready", "nl": "Klaar"},
    "tile.plan.none": {"en": "No changes", "nl": "Geen wijzigingen"},
    "tile.plan.notyet": {"en": "Not made yet", "nl": "Nog niet gemaakt"},
    "today.title": {"en": "KasFlex plan for tomorrow", "nl": "KasFlex-plan voor morgen"},
    "today.make": {"en": "Make tomorrow's plan", "nl": "Maak het plan voor morgen"},
    "today.saving": {"en": "Saves {amount} compared with your normal settings",
                     "nl": "Bespaart {amount} vergeleken met uw normale instellingen"},
    "today.nosaving": {"en": "About the same cost as your normal settings",
                       "nl": "Ongeveer dezelfde kosten als uw normale instellingen"},
    "btn.approve": {"en": "Approve plan", "nl": "Plan goedkeuren"},
    "btn.approve.note": {"en": "Use these actions for tomorrow.",
                         "nl": "Gebruik deze acties voor morgen."},
    "btn.review": {"en": "Review changes", "nl": "Wijzigingen bekijken"},
    "btn.normal": {"en": "Keep normal settings", "nl": "Normale instellingen houden"},
    "btn.concerns": {"en": "I have concerns", "nl": "Ik heb bedenkingen"},
    "btn.normal.confirm": {"en": "Use your normal greenhouse settings tomorrow?",
                           "nl": "Morgen uw normale kasinstellingen gebruiken?"},
    "btn.normal.yes": {"en": "Use normal settings", "nl": "Normale instellingen gebruiken"},
    "preview.title": {"en": "24-hour preview", "nl": "Voorbeeld van 24 uur"},
    "preview.lighting": {"en": "Lighting", "nl": "Belichting"},
    "preview.heating": {"en": "Heating", "nl": "Verwarming"},
    "preview.chp": {"en": "CHP", "nl": "WKK"},
    "approved.note": {"en": "Approved for tomorrow.", "nl": "Goedgekeurd voor morgen."},
    "normal.note": {"en": "Your normal settings will be used.",
                    "nl": "Uw normale instellingen worden gebruikt."},

    # -- Plan and edit -------------------------------------------------------
    "plan.heading": {"en": "Tomorrow's plan", "nl": "Het plan voor morgen"},
    "plan.pick": {"en": "Choose a change to look at it more closely.",
                  "nl": "Kies een wijziging om er beter naar te kijken."},
    "edit.heading": {"en": "Selected change", "nl": "Gekozen wijziging"},
    "edit.none": {"en": "Select a change on the left.", "nl": "Kies links een wijziging."},
    "edit.level": {"en": "Lighting level", "nl": "Lichtniveau"},
    "edit.hours": {"en": "Hours", "nl": "Uren"},
    "edit.impact": {"en": "Estimated saving tomorrow", "nl": "Geschatte besparing morgen"},
    "edit.reverified": {"en": "Re-checked. Crop and equipment limits are still met.",
                        "nl": "Opnieuw gecontroleerd. Gewas- en apparatuurgrenzen worden gehaald."},
    "edit.checking": {"en": "Checking your change…", "nl": "Uw wijziging wordt gecontroleerd…"},
    "edit.use_mine": {"en": "Use my choice", "nl": "Mijn keuze gebruiken"},
    "edit.restore": {"en": "Restore KasFlex choice", "nl": "KasFlex-keuze herstellen"},
    "edit.unsafe": {"en": "This choice cannot be used yet.",
                    "nl": "Deze keuze kan nog niet gebruikt worden."},
    "edit.details": {"en": "View details", "nl": "Details bekijken"},

    # -- Why -----------------------------------------------------------------
    "why.button": {"en": "Why?", "nl": "Waarom?"},
    "why.title": {"en": "Why does KasFlex suggest this?",
                  "nl": "Waarom stelt KasFlex dit voor?"},
    "why.gotit": {"en": "Got it", "nl": "Begrepen"},
    "why.ask_more": {"en": "Ask something else", "nl": "Iets anders vragen"},

    # -- Goals ---------------------------------------------------------------
    "goals.heading": {"en": "What should KasFlex prioritise?",
                      "nl": "Waar moet KasFlex voorrang aan geven?"},
    "goals.intro": {"en": "Tell KasFlex what matters most for your greenhouse. "
                          "You can change this at any time.",
                    "nl": "Vertel KasFlex wat het belangrijkst is voor uw kas. "
                          "U kunt dit altijd wijzigen."},
    "goals.crop_first": {"en": "Protect crop above everything",
                         "nl": "Gewas boven alles beschermen"},
    "goals.crop_first.note": {"en": "Keep the crop in ideal conditions, even if energy costs are high.",
                              "nl": "Houd het gewas in ideale omstandigheden, ook als de energie duur is."},
    "goals.balance": {"en": "Balance crop and energy cost",
                      "nl": "Gewas en energiekosten in balans"},
    "goals.balance.note": {"en": "Keep the crop healthy while actively managing energy costs.",
                           "nl": "Houd het gewas gezond en stuur tegelijk op de energiekosten."},
    "goals.cost_first": {"en": "Minimise energy cost", "nl": "Energiekosten zo laag mogelijk"},
    "goals.cost_first.note": {"en": "Focus on the lowest possible energy cost, while staying within crop limits.",
                              "nl": "Richt op de laagst mogelijke energiekosten, binnen de gewasgrenzen."},
    "goals.limits": {"en": "My crop limits", "nl": "Mijn gewasgrenzen"},
    "goals.temp": {"en": "Temperature", "nl": "Temperatuur"},
    "goals.light": {"en": "Minimum light", "nl": "Minimaal licht"},
    "goals.energy": {"en": "Energy preferences", "nl": "Energievoorkeuren"},
    "goals.avoid_expensive": {"en": "Avoid very expensive electricity",
                              "nl": "Vermijd zeer dure stroom"},
    "goals.prefer_stored": {"en": "Prefer using stored heat first",
                            "nl": "Gebruik liever eerst opgeslagen warmte"},
    "goals.brief": {"en": "My brief for tomorrow", "nl": "Mijn opdracht voor morgen"},
    "goals.brief.hint": {"en": "Tell KasFlex in plain language what you want to achieve. "
                               "This is optional.",
                         "nl": "Vertel KasFlex in gewone taal wat u wilt bereiken. "
                               "Dit is optioneel."},
    "goals.save": {"en": "Save preferences", "nl": "Voorkeuren opslaan"},
    "goals.saved": {"en": "Saved. These apply to your next plan.",
                    "nl": "Opgeslagen. Deze gelden voor uw volgende plan."},
    "goals.remembered": {"en": "What KasFlex remembers", "nl": "Wat KasFlex onthoudt"},

    # -- Results -------------------------------------------------------------
    "results.heading": {"en": "Results", "nl": "Resultaten"},
    "results.none": {"en": "No finished days yet. Results appear once a plan has run.",
                     "nl": "Nog geen afgeronde dagen. Resultaten verschijnen zodra een plan is gedraaid."},
    "results.from_current": {
        "en": "This is the plan you are looking at now, not a finished day.",
        "nl": "Dit is het plan dat u nu bekijkt, geen afgeronde dag."},
    "results.crop": {"en": "Crop outcome", "nl": "Gewasresultaat"},
    "results.temp": {"en": "Temperature target", "nl": "Temperatuurdoel"},
    "results.cost": {"en": "Energy cost", "nl": "Energiekosten"},
    "results.savings": {"en": "Savings", "nl": "Besparing"},
    "results.reached": {"en": "Reached", "nl": "Gehaald"},
    "results.missed": {"en": "Missed", "nl": "Niet gehaald"},
    "results.glance": {"en": "At a glance", "nl": "In één oogopslag"},
    "results.safety": {"en": "Safety problems", "nl": "Veiligheidsproblemen"},
    "results.changes": {"en": "Changes used", "nl": "Gebruikte wijzigingen"},
    "results.vs": {"en": "KasFlex compared with normal control",
                   "nl": "KasFlex vergeleken met normale regeling"},
    "results.vs.kasflex": {"en": "KasFlex plan", "nl": "KasFlex-plan"},
    "results.vs.normal": {"en": "Normal control", "nl": "Normale regeling"},
    "results.detailed": {"en": "View detailed report", "nl": "Uitgebreid rapport bekijken"},
    "results.detailed.note": {"en": "See full data, charts and decisions.",
                              "nl": "Bekijk alle gegevens, grafieken en beslissingen."},

    # -- More ----------------------------------------------------------------
    "more.heading": {"en": "More", "nl": "Meer"},
    "more.report": {"en": "Detailed report", "nl": "Uitgebreid rapport"},
    "more.assets": {"en": "Energy equipment", "nl": "Energie-installaties"},
    "more.compare": {"en": "Controller comparison", "nl": "Vergelijking regelaars"},
    "more.safety": {"en": "Safety checks", "nl": "Veiligheidscontroles"},
    "more.history": {"en": "Decision history", "nl": "Beslissingsgeschiedenis"},
    "more.ai": {"en": "AI model", "nl": "AI-model"},
    "more.data": {"en": "Prices and weather", "nl": "Prijzen en weer"},
    "more.setup": {"en": "Setup and experiments", "nl": "Instellingen en experimenten"},
    "more.about": {"en": "About KasFlex", "nl": "Over KasFlex"},

    # -- consent -------------------------------------------------------------
    "consent.title": {"en": "Taking part in the research",
                      "nl": "Deelnemen aan het onderzoek"},
    "consent.intro": {
        "en": "KasFlex is being studied by a university. You can use it either "
              "way: taking part is your choice, and saying no changes nothing "
              "about how it works for you.",
        "nl": "KasFlex wordt onderzocht door een universiteit. U kunt het hoe dan "
              "ook gebruiken: meedoen is uw keuze, en nee zeggen verandert niets "
              "aan hoe het voor u werkt."},
    "consent.what": {"en": "What would be kept", "nl": "Wat er bewaard zou worden"},
    "consent.scope.research": {"en": "My decisions", "nl": "Mijn beslissingen"},
    "consent.scope.quotes": {"en": "My own words", "nl": "Mijn eigen woorden"},
    "consent.scope.outcomes": {"en": "How it turned out", "nl": "Hoe het uitpakte"},
    "consent.voluntary": {
        "en": "You can stop at any time. If you do, everything kept about you is "
              "deleted -- only the record that you asked to be removed is kept.",
        "nl": "U kunt altijd stoppen. Als u dat doet wordt alles wat over u is "
              "bewaard verwijderd -- alleen de vastlegging dat u om verwijdering "
              "vroeg blijft bestaan."},
    "consent.agree": {"en": "Yes, I'll take part", "nl": "Ja, ik doe mee"},
    "consent.decline": {"en": "No thanks, just let me use KasFlex",
                        "nl": "Nee bedankt, ik wil KasFlex alleen gebruiken"},
    "consent.declined": {
        "en": "Nothing will be recorded. You can change your mind in More.",
        "nl": "Er wordt niets vastgelegd. U kunt bij Meer van gedachten veranderen."},
    "consent.who": {"en": "Taking part as", "nl": "Deelnemen als"},
    "consent.manage": {"en": "Research participation", "nl": "Deelname aan onderzoek"},
    "consent.withdraw": {"en": "Stop taking part and delete my data",
                         "nl": "Stoppen en mijn gegevens verwijderen"},
    "consent.withdrawn": {"en": "Stopped. Your data has been deleted.",
                          "nl": "Gestopt. Uw gegevens zijn verwijderd."},
    "consent.active": {"en": "You are taking part.", "nl": "U doet mee."},
    "consent.inactive": {"en": "You are not taking part.", "nl": "U doet niet mee."},

    # -- trust ---------------------------------------------------------------
    "trust.can_change": {"en": "You can change this.", "nl": "U kunt dit wijzigen."},
    "trust.will_check": {"en": "KasFlex checks your change before it is used.",
                         "nl": "KasFlex controleert uw wijziging voordat die wordt gebruikt."},
    "trust.normal_available": {"en": "Your normal settings remain available at any time.",
                               "nl": "Uw normale instellingen blijven altijd beschikbaar."},

    # -- parts of the day ----------------------------------------------------
    "day.morning": {"en": "in the morning", "nl": "in de ochtend"},
    "day.afternoon": {"en": "in the afternoon", "nl": "in de middag"},
    "day.evening": {"en": "this evening", "nl": "vanavond"},
    "day.night": {"en": "overnight", "nl": "'s nachts"},

    # -- what the plan changes, said as actions -------------------------------
    "actions.none": {
        "en": "Nothing needs to change. Your normal settings already suit tomorrow.",
        "nl": "Er hoeft niets te veranderen. Uw normale instellingen passen al bij morgen."},
    "actions.count": {"en": "{n} suggested changes to save energy while keeping your crop healthy.",
                      "nl": "{n} voorgestelde wijzigingen om energie te besparen en uw gewas gezond te houden."},
    "action.lighting.down": {"en": "Dim lighting to {percent}% {when}",
                             "nl": "Lampen naar {percent}% {when}"},
    "action.lighting.down.why": {"en": "Enough light for the crop, lower energy use.",
                                 "nl": "Genoeg licht voor het gewas, minder energie."},
    "action.lighting.off": {"en": "Turn the lighting off {when}",
                            "nl": "Zet de lampen uit {when}"},
    "action.lighting.up": {"en": "Raise lighting to {percent}% {when}",
                           "nl": "Lampen naar {percent}% {when}"},
    "action.lighting.up.why": {"en": "Electricity is cheap enough to give the crop more light.",
                               "nl": "Stroom is goedkoop genoeg om het gewas meer licht te geven."},
    "action.heat": {"en": "Heat with the {source} {when}", "nl": "Verwarm met de {source} {when}"},
    "action.heat.why": {"en": "The cheaper way to make heat at that time.",
                        "nl": "De goedkoopste manier om op dat moment warmte te maken."},
    "action.chp.on": {"en": "Run the CHP {when}", "nl": "Laat de WKK draaien {when}"},
    "action.chp.on.why": {"en": "Generate power when electricity is expensive.",
                          "nl": "Wek stroom op wanneer stroom duur is."},
    "action.chp.off": {"en": "Leave the CHP off {when}", "nl": "Laat de WKK uit {when}"},
    "action.chp.off.why": {"en": "Buying power costs less than running the engine then.",
                           "nl": "Stroom kopen is dan goedkoper dan de motor laten draaien."},
    "action.battery.charge": {"en": "Charge the battery {when}",
                              "nl": "Laad de batterij {when}"},
    "action.battery.charge.why": {"en": "Store power while it is cheap.",
                                  "nl": "Sla stroom op nu die goedkoop is."},
    "action.battery.discharge": {"en": "Use stored power {when}",
                                 "nl": "Gebruik opgeslagen stroom {when}"},
    "action.battery.discharge.why": {"en": "Avoid buying at the day's highest prices.",
                                     "nl": "Vermijd inkoop tegen de hoogste prijzen van de dag."},
    "status.safe": {"en": "Safe", "nl": "Veilig"},
    "status.good_for_crop": {"en": "Good for crop", "nl": "Goed voor het gewas"},
    "status.within_limits": {"en": "Within limits", "nl": "Binnen de grenzen"},

    # -- equipment in plain words --------------------------------------------
    "asset.chp": {"en": "CHP", "nl": "WKK"},
    "asset.boiler": {"en": "boiler", "nl": "ketel"},
    "asset.battery": {"en": "battery", "nl": "batterij"},
    "asset.buffer": {"en": "heat buffer", "nl": "warmtebuffer"},
    "asset.lights": {"en": "grow lights", "nl": "groeilampen"},
    "asset.grid": {"en": "the grid", "nl": "het net"},
    "action.charge": {"en": "storing power", "nl": "stroom opslaan"},
    "action.discharge": {"en": "using stored power", "nl": "opgeslagen stroom gebruiken"},
    "action.idle": {"en": "resting", "nl": "rust"},
    "term.price": {"en": "electricity price", "nl": "stroomprijs"},
    "term.cost": {"en": "cost", "nl": "kosten"},
    "term.temperature": {"en": "temperature", "nl": "temperatuur"},
    "term.sunlight": {"en": "sunlight", "nl": "zonlicht"},
    "term.battery_level": {"en": "battery level", "nl": "batterijniveau"},

    # -- conversation --------------------------------------------------------
    "chat.title": {"en": "Ask about this plan", "nl": "Vraag over dit plan"},
    "chat.intro": {
        "en": "Ask anything about tomorrow's plan. For example: why is the CHP on at night?",
        "nl": "Vraag gerust iets over het plan voor morgen. Bijvoorbeeld: waarom "
              "draait de WKK 's nachts?"},
    "chat.placeholder": {"en": "Type your question…", "nl": "Typ uw vraag…"},
    "chat.send": {"en": "Ask", "nl": "Vraag"},
    "chat.thinking": {"en": "Thinking…", "nl": "Aan het nadenken…"},
    "chat.suggest.why_chp": {"en": "Why run the CHP at night?",
                             "nl": "Waarom draait de WKK 's nachts?"},
    "chat.suggest.why_lights": {"en": "Why are the lights on so long?",
                                "nl": "Waarom staan de lampen zo lang aan?"},
    "chat.suggest.cheaper": {"en": "Could this be cheaper?", "nl": "Kan dit goedkoper?"},
    "chat.suggest.crop_safe": {"en": "Is my crop safe with this plan?",
                               "nl": "Is mijn gewas veilig met dit plan?"},
    "chat.no_model": {
        "en": "No AI is set up yet. Add one in Settings to ask questions.",
        "nl": "Er is nog geen AI ingesteld. Voeg er één toe bij Instellingen om "
              "vragen te stellen."},
    "chat.disagree": {"en": "I don't agree with this", "nl": "Hier ben ik het niet mee eens"},
    "chat.disagree.prompt": {
        "en": "Tell us what you'd do instead, and why. We'll remember it.",
        "nl": "Vertel wat u in plaats daarvan zou doen, en waarom. Wij onthouden het."},

    # -- preferences ---------------------------------------------------------
    "prefs.title": {"en": "What you've told KasFlex", "nl": "Wat u KasFlex heeft verteld"},
    "prefs.intro": {
        "en": "KasFlex remembers these and takes them into account every time it plans.",
        "nl": "KasFlex onthoudt deze en houdt er elke keer rekening mee bij het plannen."},
    "prefs.empty": {
        "en": "Nothing yet. When you disagree with a plan and say why, it appears here.",
        "nl": "Nog niets. Als u het oneens bent met een plan en uitlegt waarom, "
              "verschijnt dat hier."},
    "prefs.add": {"en": "Add something", "nl": "Iets toevoegen"},
    "prefs.rule": {"en": "What should it do?", "nl": "Wat moet het doen?"},
    "prefs.rule.hint": {"en": "For example: don't run the CHP between 10pm and 6am",
                        "nl": "Bijvoorbeeld: draai de WKK niet tussen 22 en 6 uur"},
    "prefs.reason": {"en": "Why does this matter to you?",
                     "nl": "Waarom is dit belangrijk voor u?"},
    "prefs.reason.hint": {"en": "Your reason helps it judge borderline cases",
                          "nl": "Uw reden helpt bij twijfelgevallen"},
    "prefs.strength": {"en": "How firm is this?", "nl": "Hoe strikt is dit?"},
    "prefs.strength.preference": {"en": "A preference — bend it if there's a good reason",
                                  "nl": "Een voorkeur — wijk af als daar reden voor is"},
    "prefs.strength.strong": {"en": "Important — only with a clear explanation",
                              "nl": "Belangrijk — alleen met duidelijke uitleg"},
    "prefs.strength.absolute": {"en": "Never do this", "nl": "Doe dit nooit"},
    "prefs.remove": {"en": "No longer applies", "nl": "Geldt niet meer"},
    "prefs.removed": {"en": "Removed. Earlier plans keep their record.",
                      "nl": "Verwijderd. Eerdere plannen behouden hun vastlegging."},
    "prefs.applied": {"en": "Followed {n} times", "nl": "{n} keer gevolgd"},
    "prefs.overridden": {"en": "Overruled {n} times", "nl": "{n} keer overruled"},
    "prefs.confirm.title": {"en": "Shall I remember this?", "nl": "Zal ik dit onthouden?"},
    "prefs.confirm.yes": {"en": "Yes, remember it", "nl": "Ja, onthoud het"},
    "prefs.confirm.no": {"en": "No, just this once", "nl": "Nee, alleen deze keer"},

    # -- conflict and compromise ---------------------------------------------
    "conflict.title": {"en": "You and KasFlex disagree here",
                       "nl": "U en KasFlex verschillen hier van mening"},
    "conflict.ai_chose": {"en": "KasFlex chose", "nl": "KasFlex koos"},
    "conflict.you_chose": {"en": "You chose", "nl": "U koos"},
    "conflict.because": {"en": "because", "nl": "omdat"},
    "conflict.costs_more": {"en": "Your choice costs {amount} more",
                            "nl": "Uw keuze kost {amount} meer"},
    "conflict.costs_less": {"en": "Your choice saves {amount}",
                            "nl": "Uw keuze bespaart {amount}"},
    "conflict.unsafe": {"en": "The safety check won't allow your choice",
                        "nl": "De veiligheidscontrole staat uw keuze niet toe"},
    "conflict.middle": {"en": "A middle way", "nl": "Een tussenweg"},
    "conflict.keep_mine": {"en": "Keep my choice", "nl": "Houd mijn keuze"},
    "conflict.accept_ai": {"en": "Go with KasFlex", "nl": "Ga met KasFlex mee"},
    "conflict.take_middle": {"en": "Take the middle way", "nl": "Neem de tussenweg"},
    "conflict.thinking": {"en": "Looking for a middle way…", "nl": "Zoeken naar een tussenweg…"},
    "conflict.none_found": {
        "en": "No middle way here — it's one or the other.",
        "nl": "Hier is geen tussenweg — het is het één of het ander."},

    # -- settings ------------------------------------------------------------
    "settings.language": {"en": "Language", "nl": "Taal"},
    "settings.ai": {"en": "AI model", "nl": "AI-model"},
    "settings.ai.provider": {"en": "Which service?", "nl": "Welke dienst?"},
    "settings.ai.model": {"en": "Which model?", "nl": "Welk model?"},
    "settings.ai.key": {"en": "Access key", "nl": "Toegangssleutel"},
    "settings.ai.test": {"en": "Test the connection", "nl": "Verbinding testen"},
    "settings.ai.ok": {"en": "Working", "nl": "Werkt"},
    "settings.ai.failed": {"en": "Not working", "nl": "Werkt niet"},
    "settings.data": {"en": "Prices and weather", "nl": "Prijzen en weer"},
    "settings.data.demo": {"en": "Practice mode — made-up numbers",
                           "nl": "Oefenmodus — verzonnen getallen"},
    "settings.data.real": {"en": "Real prices and weather",
                           "nl": "Echte prijzen en weer"},
    "settings.reset": {"en": "Start over", "nl": "Opnieuw beginnen"},
    "settings.mode.grower": {"en": "Simple", "nl": "Eenvoudig"},
    "settings.mode.research": {"en": "Detailed", "nl": "Uitgebreid"},
}


def normalise(language: str | None) -> str:
    """Map anything user-supplied onto a language we actually have."""
    if not language:
        return DEFAULT_LANGUAGE
    code = str(language).strip().lower().replace("_", "-").split("-")[0]
    return code if code in LANGUAGES else DEFAULT_LANGUAGE


def translate(key: str, language: str = DEFAULT_LANGUAGE, **fields: Any) -> str:
    """Look up one string. Unknown keys return the key, so a screen still renders."""
    entry = CATALOG.get(key)
    if entry is None:
        return key
    text = entry.get(normalise(language)) or entry.get(DEFAULT_LANGUAGE, key)
    if fields:
        try:
            return text.format(**fields)
        except (KeyError, IndexError):
            return text
    return text


def catalog_for(language: str = DEFAULT_LANGUAGE) -> dict[str, str]:
    """The whole catalogue flattened for one language, for the browser."""
    code = normalise(language)
    return {key: entry.get(code) or entry.get(DEFAULT_LANGUAGE, key)
            for key, entry in CATALOG.items()}


def missing_keys(language: str) -> list[str]:
    """Keys with no text in this language. The test suite requires this be empty."""
    code = normalise(language)
    return sorted(k for k, entry in CATALOG.items() if not entry.get(code))


def language_instruction(language: str) -> str:
    """The sentence appended to every system prompt.

    Translating a finished English explanation loses the reasoning and produces
    the stilted register that makes people distrust a machine. Asking the model to
    reason in Dutch from the start does not.
    """
    if normalise(language) != "nl":
        return ("Write for a working greenhouse grower in plain English. Short "
                "sentences. No jargon, no abbreviations the grower has not used "
                "themselves, and no numbers beyond what the point needs.")
    return ("Schrijf in het Nederlands, voor een praktiserende kweker. Gebruik korte "
            "zinnen en gewone taal, geen jargon. Gebruik Nederlandse vaktermen waar "
            "die bestaan: WKK (niet CHP), ketel, warmtebuffer, groeilampen, batterij. "
            "Spreek de kweker aan met 'u'. Noem alleen getallen die het punt dragen.")


def format_money(amount: float, language: str = DEFAULT_LANGUAGE) -> str:
    """``€1,234`` in English, ``€ 1.234`` in Dutch."""
    whole = f"{abs(amount):,.0f}"
    sign = "-" if amount < 0 else ""
    if normalise(language) == "nl":
        return f"{sign}€ {whole.replace(',', '.')}"
    return f"{sign}€{whole}"


def format_hour(hour: int, language: str = DEFAULT_LANGUAGE) -> str:
    """``13:00`` in English, ``13.00 uur`` in Dutch."""
    if normalise(language) == "nl":
        return f"{hour:02d}.00 uur"
    return f"{hour:02d}:00"


def format_range(start: int, end: int, language: str = DEFAULT_LANGUAGE) -> str:
    """An inclusive hour span, written the way each language writes it."""
    if normalise(language) == "nl":
        return f"van {start:02d}.00 tot {end:02d}.00 uur"
    return f"{start:02d}:00 to {end:02d}:00"


def language_options() -> list[dict[str, str]]:
    """For a language picker: every language, labelled in its own words."""
    return [dict(meta) for meta in LANGUAGES.values()]
