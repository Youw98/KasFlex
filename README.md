# KasFlex

**An AI plans a day of greenhouse energy use. A safety checker verifies it. A person
approves it.**

Dutch greenhouses own exactly what the congested electricity grid needs — batteries,
CHP units, heat buffers, controllable lighting. An AI could plan when to use them.
But nobody lets an AI near a grid connection without a guarantee it won't do
something dangerous.

KasFlex builds that guarantee, and measures what it is worth.

> **Simulation only.** No greenhouse equipment is connected. Nothing here is
> validated for operational use, and no figure produced with the built-in surrogate
> greenhouse model may be published as a result.

4TU.NIRICT · WUR · TU Delft · TU/e · UT

---

## Try it

**No Python?** Download the application from
[releases](https://github.com/youw98/test/releases) — `KasFlex.exe` on Windows,
`KasFlex` on macOS and Linux — and double-click it. The interface opens in your
browser. Nothing to install.

**From source:**

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
kasflex experiment --days 3
```

No API key, no downloads, no network. Six seconds later:

```
condition               runs    cost EUR  violations   hard  fallback   peak kW
-------------------------------------------------------------------------------
rule-based                 3    11561.62        0.00      0      0.00      5718
learned                    3    10716.28        0.00      0      0.00      5650
ai-unverified              3    12582.90       65.67    197      0.00     10650
ai-verified                3    11561.62        0.00      0      1.00      5718
```

Read it two rows at a time:

- **`ai-unverified`** — a planner let loose with the checker off. 66 limit
  violations, and it costs *more* than doing nothing clever.
- **`ai-verified`** — the same planner with the checker on. Rejected until control
  falls back to the conventional baseline. Violations: zero.
- **`learned`** — forecasts tomorrow's heat demand from past operation, then
  optimises the schedule. About 7% cheaper than the baseline, no violations.

Those numbers are **apparatus, not findings**: the greenhouse model is not yet
validated. They show the measurement works, which is what this stage owes.

## The interface

```bash
kasflex ui
```

Two front doors onto the same engine.

**`/` — for growers.** One number, two signals, and the day told as five or six
phases instead of twenty-four rows. Plain language, Dutch or English, usable on a
phone. Instead of *approve* and *reject* it offers **this looks good** and **I have
concerns** — and a concern opens a box that asks what you would do instead, and
why.

**`/advanced` — for researchers.** The full instrument: every hour editable, the
checker verdict, planner comparison, all metrics. An edited plan cannot be approved
until it has been re-verified. With the checker switched off the verdict reads *not
verified*, never *accepted*.

![The interface](docs/ui.png)

## Talking to the planner

The grower interface can explain itself, and can learn.

**Ask why.** *"Why is the CHP on at three in the morning?"* — answered from the
actual plan and the actual prices, in the grower's language. If it cannot tell why,
it says so rather than guessing.

**Disagree, and be remembered.** Say *"I don't trust the CHP overnight, it jammed
last February"* and KasFlex proposes a standing instruction, shows it to you, and
keeps it only if you agree. Every later plan accounts for it, and says so when it
has to go against one.

**Find the middle.** Where grower and planner disagree, it looks for a third
position — *run the CHP only after six* — priced, so the compromise is a choice
rather than a guess. Where none exists, it says that too.

Everything is append-only: what was stated, when, why, and how each disagreement
ended. That record is the study's primary observation, and it exports as JSON-LD
with a codebook, or as a flat CSV.

## Which AI

| Service | Account | Where your data goes |
|---|---|---|
| Anthropic Claude, OpenAI, Google Gemini | yes | that vendor |
| **Ollama** | **no** | **nowhere — your own machine** |
| Any OpenAI-compatible endpoint | depends | wherever you point it |

Switching is a configuration change and nothing else. **KasFlex also runs with no
AI at all** — planning, checking and review do not need one; you lose the
conversation, and an objection you type is still recorded word for word.

## Run it every day

```bash
export ENTSOE_API_KEY=...
kasflex daily
```

Fetches day-ahead prices and weather, plans tomorrow, appends a record. Cache-first
and offline-safe. See [deploy/](deploy/README.md) for cron and systemd.

## Where the numbers come from

The asset defaults in `kasflex/energy/assets.py` reach every cost figure the
system produces, so each one is traceable to a published source or is marked as a
placeholder. Six were corrected against the literature; the originals are in the
git history.

**Combined heat and power** — US EPA, *Catalog of CHP Technologies*, Section 2:
[Reciprocating Internal Combustion Engines](https://www.epa.gov/sites/default/files/2015-07/documents/catalog_of_chp_technologies_section_2._technology_characterization_-_reciprocating_internal_combustion_engines.pdf),
Table 2-2. Gives 36.8% electrical efficiency (HHV) at 1,121 kWe and 40.4% at
3,326 kWe, with power/heat ratios of 0.89 and 1.06. Interpolated to the modelled
1.5 MW unit: **37.5% electrical, heat/power 1.1** — previously 40% and 1.2, which
were the figures for an engine twice the size. Dutch sector context, including the
0.5–5 MW typical unit size, from van der Velden & Smit, *Combined heat and power in
Dutch greenhouses: a case study of technology diffusion*, **Energy Policy** (2015)
([ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0301421515300847)),
[Greenhouse Canada](https://www.greenhousecanada.com/special-series-world-report-1-cogeneration-in-the-netherlands-20013/)
and [DutchGreenhouses](https://dutchgreenhouses.com/sustainability/chp).
The CO₂ figure of **0.50 kg/kWh<sub>e</sub>** is derived from a natural gas factor of
0.185–0.205 kg/kWh ([Carbon Independent](https://www.carbonindependent.org/15.html),
[UK BEIS via Climatiq](https://www.climatiq.io/data/emission-factor/9279dd25-8940-4cbb-a695-b82dee5a9bce))
divided by that electrical efficiency.

**Heat buffer** — Dutch practice is about **300 m³ per hectare**
([Hortinergy](https://www.hortinergy.com/water-buffer-tank-design/)), so 1,500 m³
for a 5 ha site; over a 25 K working swing that stores **43,600 kWh**. The previous
default of 8,000 kWh was roughly a fifth of that, which understated how far a
greenhouse can shift heat in time — and so understated the value of exactly the
flexibility this project measures. Tank insulation and U-value from
[VB Greenhouses](https://vb-greenhouses.com/greenhouses/heat-buffer-tanks).

**Battery** — round-trip efficiency is now **85% (0.92 each way), a system-level
figure** rather than the cell-level 90% used before, which ignored inverter and
auxiliary losses. Measured utility-scale systems average around 85%, falling
towards 65% at low power, and one 6 MW/7.5 MWh installation measured 72.8%
([ScienceDirect — ageing and energy performance](https://www.sciencedirect.com/science/article/pii/S2352152X23006291),
[grid-connected BESS efficiency](https://www.sciencedirect.com/science/article/abs/pii/S2214785318318947),
[OSTI](https://www.osti.gov/servlets/purl/1409737)). The 0.5 C-rate matches the
conventional 2-hour grid-scale duration.

**Crop limits** — the maximum is now **32 °C**, not 34 °C; above roughly 30–32 °C
tomato pollen viability and fruit set suffer, so the checker was previously passing
conditions the literature treats as damaging. Minimum of 15 °C sits between the
12 °C absolute tolerance and the 16–18 °C night optimum. Sources: Shamshiri et al.,
*Review of optimum temperature, humidity, and vapour pressure deficit for
microclimate evaluation and control in greenhouse cultivation of tomato* (2018)
([USDA ARS](https://www.ars.usda.gov/ARSUserFiles/57795/Shamshiri2018%20-%20review%20optimum%20microclimate%20greenhouse.pdf)),
[DryGair](https://drygair.com/blog/what-are-the-ideal-conditions-for-greenhouse-tomatoes/).

**Lighting** — 185 µmol·m⁻²·s⁻¹ sits at the lower end of the 200–250 reported for
overhead supplemental lighting, and is consistent with a 600 W HPS installation
delivering 175 µmol over a 16 h photoperiod
([Agronomy](https://doi.org/10.3390/agronomy11050835),
[Frontiers meta-analysis](https://www.frontiersin.org/journals/plant-science/articles/10.3389/fpls.2021.596927/full)).
Note the DLI target of 10 mol·m⁻²·d⁻¹ is the **supplemental** figure; the total
optimum for tomato is 20–30, so this describes a partially lit crop and results
quoting it must say so.

**Boiler** — 90% on the higher heating value, conservative for a condensing unit
([Condensing boiler](https://en.wikipedia.org/wiki/Condensing_boiler),
[UMass CAFE](https://www.umass.edu/agriculture-food-environment/greenhouse-floriculture/fact-sheets/upgrading-greenhouse-heating-system)).

**Still unsourced** — grid connection limits, base load, buffer standing loss, CHP
minimum run/down times, ramp rates, PV peak and performance ratio, humidity and
CO₂ bounds. Most are modelling conventions with little leverage on results; the
**connection limits** and **buffer standing loss** are the two that genuinely move
outcomes and deserve real sources.

## Documentation

| | |
|---|---|
| **[Guide](docs/GUIDE.md)** | **What it does in plain terms, then the same thing in depth** |
| [MVP plan](docs/MVP_PLAN.md) | Build order, requirement coverage, risks |
| [Architecture](docs/ARCHITECTURE.md) | How the pieces fit, and why |
| [Decisions](docs/DECISIONS.md) | Why things are the way they are |
| [Usage](docs/USAGE.md) | Every command |
| [Data](docs/DATA.md) | Datasets, DOIs, licences, provenance |
| [FAIR](docs/FAIR.md) | FAIR assessment, including the gaps |
| [Packaging](packaging/README.md) | Building the double-clickable application |

KasFlex does not implement greenhouse physics or power flow. It wraps
[GreenLight-Gym2](https://github.com/BartvLaatum/GreenLight-Gym2) and
[power-grid-model](https://github.com/PowerGridModel/power-grid-model), and adds the
energy hub, the safety checker, human approval and the experiment harness.

**One thing to know before you extend it:** GreenLight-Gym2 is AGPL-licensed and
pins an incompatible NumPy version, so it runs in a separate process under its own
virtual environment. `kasflex doctor` warns if you break that. See
[ADR-0001 and ADR-0002](docs/DECISIONS.md).

## Status

Tested end to end and runs entirely offline. The safety checker, the energy model,
the planners and the interface are built. Validating the greenhouse model against measured data is the
next step, and until it is done every number is marked unvalidated.

## Licence

[Apache-2.0](LICENSE). `workers/greenlight/worker.py` is AGPL-3.0-or-later,
inherited from `gl-gym` and isolated to that one file.
