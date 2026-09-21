# Provenance of every number

Every numerical parameter KasFlex ships with — battery size, CHP efficiency,
lamp density, crop bands — comes from somewhere. This page lists them all,
next to where they came from.

The six parameters that reach every cost figure the system produces (CHP,
heat buffer, battery, crop temperature ceiling) are corrected against
published sources in [the README](../README.md#where-the-numbers-come-from).
This page carries the same table for those, and adds a row for every other
parameter the scenario configuration and asset defaults expose, so that
nothing is left as an unsourced default.

Three tags are used, and only three:

| tag | meaning |
|---|---|
| **documented** | copied from a specific source (a paper, a manufacturer sheet, a dataset, GL-Gym's own defaults). The source is named. |
| **industry norm** | widely-used representative figure for the Dutch lit tomato greenhouse the scenario is modelled on, not tied to one document. Kept explicit so a reviewer knows it is a scenario choice, not a measurement. |
| **guess** | an educated placeholder. Nobody has looked up a source yet. These are the values a validation exercise most needs to revisit. |

A parameter with no row in this file is a bug in this file, not permission
to invent one. When you add a new field, add a row here in the same commit.

Datasets themselves live in [DATA.md](DATA.md) with their DOIs and licences.
This file is about the values baked into `configs/scenario_westland_winter.yaml`
and the defaults in `src/kasflex/energy/assets.py`.

## Site scale

| Field | Value | Tag | Source / rationale |
|---|---|---|---|
| `hub.floor_area_m2` | 50 000 m² | industry norm | A representative modern Dutch lit tomato greenhouse (Westland cluster). AGC validation runs at 96 m² instead — see [DECISIONS.md](DECISIONS.md) ADR-0004. |
| `hub.base_load_kw` | 150 kW | guess | Site electrical load that is not lighting (pumps, fans, screens, packing hall). Order-of-magnitude estimate; a metering study would replace it. |
| `hub.lamp_power_w_m2` | 110 W/m² | industry norm | Typical installed supplemental-lighting density for a lit Dutch tomato greenhouse. HPS installations sit around 100–120 W/m²; LED retrofits go higher. |
| `hub.lamp_ppfd_umol_m2_s` | 185 μmol/m²/s | industry norm | Photosynthetic photon flux at full lamp power. Consistent with HPS efficacy around 1.7 μmol/J at 110 W/m². Would change materially under LED. |

## Grid connection

| Field | Value | Tag | Source / rationale |
|---|---|---|---|
| `hub.contract.import_limit_kw` | 6 000 kW | industry norm | Sized to carry the full lamp field of the default 5 ha site (5 500 kW at 110 W/m²) plus base load and margin. A connection smaller than the lamp load would make every fully-lit hour a violation. |
| `hub.contract.export_limit_kw` | 4 000 kW | industry norm | Feed-in caps are commonly lower than import. Non-firm ATO contracts sometimes push this to zero — expose that via the scenario file. |
| `hub.contract.congestion_windows` | 3 000 kW import / 1 000 kW export at 16–19h | industry norm | Represents a Liander evening-peak reduction typical of the Westland cluster. Real windows come from the Netbeheer Nederland capacity map (D10); this is a scenario stand-in until phase 2 wires the map in. |

## Battery

The system-level round-trip efficiency is cited in [the
README](../README.md#where-the-numbers-come-from) (0.92 each way; 85%
round-trip; sources: ScienceDirect, OSTI).

| Field | Value | Tag | Source / rationale |
|---|---|---|---|
| `hub.battery.capacity_kwh` | 2 000 kWh | industry norm | Representative Li-ion battery for a 5 ha lit site; small enough that time-of-use arbitrage has to earn it, large enough to move the peak. |
| `hub.battery.max_charge_kw` | 1 000 kW | industry norm | 0.5 C on capacity. Matches `c_rate_max` below. Corresponds to the conventional 2-hour grid-scale duration. |
| `hub.battery.max_discharge_kw` | 1 000 kW | industry norm | Same reasoning as charge. |
| `hub.battery.soc_min_frac` | 0.10 | documented | Standard vendor lower reserve on grid-scale Li-ion (Tesla Megapack, CATL EnerC, etc.); protects cycle life. |
| `hub.battery.soc_max_frac` | 0.90 | documented | Corresponding upper reserve. |
| `hub.battery.soc_init_frac` | 0.50 | industry norm | Midpoint start. Deterministic seed for reproducibility (R6). |
| `hub.battery.charge_efficiency` | 0.92 | documented | See README citations. |
| `hub.battery.discharge_efficiency` | 0.92 | documented | See README citations. |
| `hub.battery.c_rate_max` | 0.5 | documented | Matches the 2-hour grid-scale duration standard for utility Li-ion. |

## Combined heat and power (CHP)

CHP electrical efficiency, heat/power ratio and CO₂ factor are cited in
[the README](../README.md#where-the-numbers-come-from) (US EPA CHP catalog;
van der Velden & Smit, *Energy Policy* 2015; Carbon Independent).

| Field | Value | Tag | Source / rationale |
|---|---|---|---|
| `hub.chp.electrical_capacity_kw` | 1 500 kWe | industry norm | Mid-size greenhouse gas engine (0.5–5 MW is the Dutch sector's typical range, per van der Velden & Smit). |
| `hub.chp.heat_to_power_ratio` | 1.1 | documented | See README citations (EPA Table 2-2, interpolated to 1.5 MW). |
| `hub.chp.electrical_efficiency` | 0.375 | documented | Same source. |
| `hub.chp.min_load_frac` | 0.50 | industry norm | Below half load the engine's electrical efficiency and NOx behaviour deteriorate. |
| `hub.chp.min_run_hours` | 2 | industry norm | A gas engine reaches steady thermal state within about two hours; cycling faster costs efficiency and maintenance life. |
| `hub.chp.min_down_hours` | 2 | industry norm | Same reasoning applied to restart. |
| `hub.chp.ramp_kw_per_hour` | 1 500 kW/h | documented | A greenhouse gas engine reaches full load within minutes, so at one-hour resolution the ramp does not bind. Kept explicit because larger units and steam turbines do. |
| `hub.chp.co2_kg_per_kwh_e` | 0.50 kg/kWh_e | documented | See README (natural-gas emission factor / electrical efficiency). |

## Boiler

| Field | Value | Tag | Source / rationale |
|---|---|---|---|
| `hub.boiler.thermal_capacity_kw` | 8 000 kW | documented | GreenLight-Gym2 reports a maximum heating power of 130 W/m²; a 5 ha site therefore needs about 6.5 MW on the coldest hour. 8 MW gives head-room; 4 MW would leave the checker reporting an unmeetable heat demand on any genuinely cold night. |
| `hub.boiler.efficiency` | 0.90 | industry norm | Typical seasonal efficiency of a modern greenhouse condensing gas boiler on higher-heating-value gas. |
| `hub.boiler.ramp_kw_per_hour` | 8 000 kW/h | documented | Boilers ramp fast enough that the hourly limit does not bind; kept explicit for symmetry with the CHP. |

## Heat buffer

Buffer capacity is cited in [the
README](../README.md#where-the-numbers-come-from) (Hortinergy: ~300 m³/ha
Dutch practice; VB Greenhouses on U-values).

| Field | Value | Tag | Source / rationale |
|---|---|---|---|
| `hub.buffer.capacity_kwh` | 43 600 kWh | documented | See README citations (1 500 m³ for 5 ha × 25 K working swing). |
| `hub.buffer.max_charge_kw` | 3 000 kW | industry norm | Sized to accept CHP + boiler simultaneously when needed. |
| `hub.buffer.max_discharge_kw` | 3 000 kW | industry norm | Sized to cover a majority of night heat demand from the buffer alone. |
| `hub.buffer.level_min_frac` | 0.05 | industry norm | Practical dead volume in a stratified tank. |
| `hub.buffer.level_max_frac` | 0.95 | industry norm | Head-space for thermal expansion. |
| `hub.buffer.standing_loss_frac_per_hour` | 0.005 | guess | 0.5% per hour is a reasonable placeholder for a well-insulated large stratified tank; a manufacturer figure would replace it. |

## Photovoltaic

| Field | Value | Tag | Source / rationale |
|---|---|---|---|
| `hub.pv.peak_kw` | 500 kW | industry norm | Modest rooftop or field PV, chosen so it affects but does not dominate the mid-day balance for the default site. |
| `hub.pv.performance_ratio` | 0.85 | documented | Standard IEC-61724 performance ratio; captures inverter, cable and soiling losses relative to nameplate at STC. |

## Crop limits (all crop-specific and worth revisiting per cultivar)

`temp_max_c` is cited in [the
README](../README.md#where-the-numbers-come-from).

| Field | Value | Tag | Source / rationale |
|---|---|---|---|
| `hub.crop.dli_target_mol_m2` | 10 mol/m² | industry norm | Supplemental daily light integral for a Dutch winter lit tomato crop; the sun provides most summer light and lamps top up the rest. |
| `hub.crop.dli_tolerance_mol_m2` | 3 mol/m² | industry norm | A tolerance wide enough that a valid winter plan is achievable; narrower windows reject every plan for a reason the planner cannot act on. |
| `hub.crop.temp_min_c` | 15 °C | documented | Lower bound for tomato vegetative development; below this fruit set drops sharply. |
| `hub.crop.temp_max_c` | 32 °C | documented | See README (pollen viability collapses above roughly 30–32 °C). |
| `hub.crop.rh_max_pct` | 85% | documented | Above this, Botrytis risk rises steeply on tomato. |
| `hub.crop.co2_min_ppm` | 300 ppm | industry norm | Roughly atmospheric; the floor of the enrichment control band. |
| `hub.crop.co2_max_ppm` | 1 600 ppm | industry norm | A common upper enrichment target; above this the marginal photosynthesis gain flattens. |

## Prices

| Field | Value | Tag | Source / rationale |
|---|---|---|---|
| `gas_price_eur_kwh` | 0.035 EUR/kWh (HHV) | industry norm | TTF front-month settlement has no free public API, so this is a configured value rather than a fetch. Update it when the market moves materially. See [DATA.md](DATA.md). |
| `power_price_eur_kwh` | ENTSO-E day-ahead | documented | Fetched, checksummed, cached. See [DATA.md](DATA.md). |
| `irradiance_w_m2` | Open-Meteo forecast + KNMI actual | documented | Same pipeline. |

## Configuration knobs that are choices, not measurements

| Field | Value | Tag | Source / rationale |
|---|---|---|---|
| `checker.enabled` | true | choice | The whole point of the project is to measure what changes when this flips. |
| `checker.explain` | true | choice | Whether the checker's rejection is passed back to the planner as guidance. R19 keeps this switchable independently of `enabled` so verification and explanation can be measured apart. |
| `checker.max_revisions` | 3 | choice | How many times the planner is allowed to revise before the baseline takes over (R18). Small enough to be finite, large enough to test whether the planner learns from feedback. |
| `checker.fail_on_projected` | false | choice | Projected (climate-band) violations do not reject a plan by default; that would attribute the greenhouse model's error to the planner. See [DECISIONS.md](DECISIONS.md) ADR-0007. |
| `history_days` (learned planner) | 60 | industry norm | Enough past days to fit the ridge demand model without the lag features exhausting the sample. |
| `seed` | 0 | choice | Reproducibility (R6). Any integer is fine; 0 is the default so the same run reproduces. |

## Numbers that come from someone else's code, not this file

| Where | Source |
|---|---|
| Climate and crop physics constants (transpiration, photosynthesis, stomatal conductance, canopy energy balance) | [GreenLight-Gym2](https://github.com/BartvLaatum/GreenLight-Gym2), inherited from [GreenLight](https://github.com/davkat1/GreenLight). Isolated in `workers/greenlight/`. |
| Power-flow equations, MV feeder topology defaults | [power-grid-model](https://github.com/PowerGridModel/power-grid-model). |
| Ridge regression coefficients (learned planner) | Fitted at runtime from the greenhouse's past operation. Reproducible from the seed. |

## Guesses, listed

The rows tagged **guess** above, at the time of writing:

1. `hub.base_load_kw` (150 kW site load)
2. `hub.buffer.standing_loss_frac_per_hour` (0.005)

Two is few enough to enumerate. If it grows past a handful, this list —
not the table — is the thing to look at first.
