# Provenance of every number

Every numerical parameter KasFlex ships with — battery size, CHP efficiency,
lamp density, crop bands — comes from somewhere. This page lists them all,
next to where they came from.

The six parameters that reach every cost figure the system produces (CHP,
heat buffer, battery, crop temperature ceiling) are corrected against
published sources, named in the sections below.
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
| `hub.floor_area_m2` | 50 000 m² | industry norm | A representative modern Dutch lit tomato greenhouse (Westland cluster). AGC validation runs at 96 m² instead — see [DECISIONS.md](../DECISIONS.md) ADR-0004. |
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

The system-level round-trip efficiency is 0.92 each way, 85% round trip
(sources: ScienceDirect, OSTI).

| Field | Value | Tag | Source / rationale |
|---|---|---|---|
| `hub.battery.capacity_kwh` | 2 000 kWh | industry norm | Representative Li-ion battery for a 5 ha lit site; small enough that time-of-use arbitrage has to earn it, large enough to move the peak. |
| `hub.battery.max_charge_kw` | 1 000 kW | industry norm | 0.5 C on capacity. Matches `c_rate_max` below. Corresponds to the conventional 2-hour grid-scale duration. |
| `hub.battery.max_discharge_kw` | 1 000 kW | industry norm | Same reasoning as charge. |
| `hub.battery.soc_min_frac` | 0.10 | documented | Standard vendor lower reserve on grid-scale Li-ion (Tesla Megapack, CATL EnerC, etc.); protects cycle life. |
| `hub.battery.soc_max_frac` | 0.90 | documented | Corresponding upper reserve. |
| `hub.battery.soc_init_frac` | 0.50 | industry norm | Midpoint start. Deterministic seed for reproducibility (R6). |
| `hub.battery.charge_efficiency` | 0.92 | documented | Published grid-scale Li-ion values. |
| `hub.battery.discharge_efficiency` | 0.92 | documented | Published grid-scale Li-ion values. |
| `hub.battery.c_rate_max` | 0.5 | documented | Matches the 2-hour grid-scale duration standard for utility Li-ion. |

## Combined heat and power (CHP)

CHP electrical efficiency, heat/power ratio and CO₂ factor come from the US EPA
CHP catalog; van der Velden & Smit, *Energy Policy* 2015; and Carbon Independent.

| Field | Value | Tag | Source / rationale |
|---|---|---|---|
| `hub.chp.electrical_capacity_kw` | 1 500 kWe | industry norm | Mid-size greenhouse gas engine (0.5–5 MW is the Dutch sector's typical range, per van der Velden & Smit). |
| `hub.chp.heat_to_power_ratio` | 1.1 | documented | Published source (EPA Table 2-2, interpolated to 1.5 MW). |
| `hub.chp.electrical_efficiency` | 0.375 | documented | Same source. |
| `hub.chp.min_load_frac` | 0.50 | industry norm | Below half load the engine's electrical efficiency and NOx behaviour deteriorate. |
| `hub.chp.min_run_hours` | 2 | industry norm | A gas engine reaches steady thermal state within about two hours; cycling faster costs efficiency and maintenance life. |
| `hub.chp.min_down_hours` | 2 | industry norm | Same reasoning applied to restart. |
| `hub.chp.ramp_kw_per_hour` | 1 500 kW/h | documented | A greenhouse gas engine reaches full load within minutes, so at one-hour resolution the ramp does not bind. Kept explicit because larger units and steam turbines do. |
| `hub.chp.co2_kg_per_kwh_e` | 0.50 kg/kWh_e | documented | Published source (natural-gas emission factor / electrical efficiency). |

## Boiler

| Field | Value | Tag | Source / rationale |
|---|---|---|---|
| `hub.boiler.thermal_capacity_kw` | 8 000 kW | documented | GreenLight-Gym2 reports a maximum heating power of 130 W/m²; a 5 ha site therefore needs about 6.5 MW on the coldest hour. 8 MW gives head-room; 4 MW would leave the checker reporting an unmeetable heat demand on any genuinely cold night. |
| `hub.boiler.efficiency` | 0.90 | industry norm | Typical seasonal efficiency of a modern greenhouse condensing gas boiler on higher-heating-value gas. |
| `hub.boiler.ramp_kw_per_hour` | 8 000 kW/h | documented | Boilers ramp fast enough that the hourly limit does not bind; kept explicit for symmetry with the CHP. |

## Heat buffer

Buffer capacity follows Hortinergy (~300 m³/ha in Dutch practice) and VB
Greenhouses on U-values.

| Field | Value | Tag | Source / rationale |
|---|---|---|---|
| `hub.buffer.capacity_kwh` | 43 600 kWh | documented | Published source (1 500 m³ for 5 ha × 25 K working swing). |
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

`temp_max_c` follows tomato pollen-viability literature (viability collapses above
roughly 30–32 °C).

| Field | Value | Tag | Source / rationale |
|---|---|---|---|
| `hub.crop.dli_target_mol_m2` | 10 mol/m² | industry norm | Supplemental daily light integral for a Dutch winter lit tomato crop; the sun provides most summer light and lamps top up the rest. |
| `hub.crop.dli_tolerance_mol_m2` | 3 mol/m² | industry norm | A tolerance wide enough that a valid winter plan is achievable; narrower windows reject every plan for a reason the planner cannot act on. |
| `hub.crop.temp_min_c` | 15 °C | documented | Lower bound for tomato vegetative development; below this fruit set drops sharply. |
| `hub.crop.temp_max_c` | 32 °C | documented | Published source (pollen viability collapses above roughly 30–32 °C). |
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
| `checker.fail_on_projected` | false | choice | Projected (climate-band) violations do not reject a plan by default; that would attribute the greenhouse model's error to the planner. See [DECISIONS.md](../DECISIONS.md) ADR-0007. |
| `history_days` (learned planner) | 60 | industry norm | Enough past days to fit the ridge demand model without the lag features exhausting the sample. |
| `STORED_HEAT_CREDIT_EUR_PER_KWH` (scheduler) | 0.005 EUR/kWh | choice | What one kWh of heat-buffer discharge is worth to a grower who ticks "prefer stored heat". A preference weight, not a price: about an eighth of boiler heat cost at the configured gas price, so it tips comparable plans towards the buffer without buying buffer use at any cost. |
| `grid_peak_value_eur_per_kw` (`GRID_PEAK_VALUE_EUR_PER_KW`) | 3.57 EUR/kW | documented | Liander 2026 transport tariff, medium voltage (MS, >136 kW): the kWmax charge of EUR 3.57 per kW per month on the month's highest import ([Liander tarieven 2026](https://www.liander.nl/grootzakelijk/tarieven)). The "grid relief" priority only buys a lower peak when it costs less than this per kW saved. Counting the whole monthly charge against one day assumes that day sets the month's peak, so it is an upper bound. Other network operators, or a congestion contract, need their own value. |
| `seed` | 0 | choice | Reproducibility (R6). Any integer is fine; 0 is the default so the same run reproduces. |
| `grid_contract_type` | `cbc` | choice | Which Dutch contract shapes the hourly import limit: `firm` (no windows), `cbc` (capacity limitation contract: the configured congestion windows), `time_block` (tijdsblokgebonden), `duration` (tijdsduurgebonden), `non_firm` (non-firm ATO). Types from ACM, [Codebesluit alternatieve transportrechten](https://www.acm.nl/nl/publicaties/codebesluit-alternatieve-transportrechten) (in force 1 April 2025) and ACM's non-firm ATO decision (possible since 31 January 2024). |
| `TIME_BLOCK_HOURS`, `TIME_BLOCK_FIRM_SHARE` (contracts) | full capacity 00–07, 10–15, 22–24; 50 % otherwise | guess | Example time blocks: transport is guaranteed at night and around midday, when regional grids have room. Real blocks are set per operator and per contract; a scenario should replace these with the actual offer. |
| `DURATION_CURTAILED_HOURS` (contracts) | 17–20, no import or export | guess | A duration right guarantees transport in at least 85 % of the hours of a year (ACM); in the other hours the operator may curtail fully. Three curtailed evening hours on the planned day (12.5 %) stay inside that if most days are not curtailed. Which hours, on which days, is up to TenneT; the CHP and battery have to carry the site then. |
| `NON_FIRM_PROFILE` (contracts) | 24 hourly shares, lowest 0.3 in the evening peak | guess | Illustrative: a non-firm ATO grants capacity only when the grid has room, so the evening peak gets least. No operator publishes a daily profile in advance. |
| `switch_penalty_eur` | 0 (60 when a grower says staff is short) | choice | Euros charged per equipment switch (heat source, CHP on/off, battery direction) so a "fewer people tomorrow" reason produces a steadier plan. 60 EUR is a preference weight, roughly an hour of a skilled worker's time with overhead; it tips comparable plans, it does not forbid switching. |
| `LIGHT_SHORTFALL` (recommend) | 1.0 mol/m²/day | choice | The recommender suggests "crop first" when the cheapest plan is more than this below the crop's light target: about 10 % of the 10 mol/m² default, more than the planner's day-to-day noise. |
| `PEAK_SHARE` (recommend) | 4 % of the import limit | choice | Grid relief is suggested when it lowers the peak by at least this much (240 kW on 6 MW); smaller drops are within forecast error. |
| `PRICE_SWING`, `COST_EDGE` (recommend) | 2.5×, 1 % | choice | "Lowest cost" is suggested when the dearest hour costs at least 2.5 times the cheapest and cost-first saves at least 1 % more than balanced. Otherwise "balanced". |
| Recommended reserve | 55 % on a night below 0 °C, else 45 % | choice | A frost night keeps more stored energy back. 45 % is the existing default battery reserve. |
| Heating targets (`heat_day_c`, `heat_night_c`) | model default 19.5 / 16.5 °C | choice | The grower's own setpoints replace the surrogate greenhouse's, so heat demand and cost follow them. Kept between 10–30 °C (day) and 8–28 °C (night). GreenLight runs its own climate control; there the target is reported as not applied. |
| Settings password | `admin99` (`KASFLEX_ADMIN_PASSWORD`) | choice | A placeholder agreed for the workshop; change it before any use outside a supervised session. Tokens last 8 hours. |
| Built-in workshop scenarios | 4 days, prices and temperatures set by hand | choice | Two good days and two with a deliberate error the planner cannot see (a grid operator's curtailment notice; a CHP maintenance visit). Shaped on Dutch winter and spring day-ahead patterns, not copied from a specific day, so every participant sees the same, explainable situation. Editable on the admin page. |

## GreenLight calibration for AGC2 compartments (validation replay only)

These replace gl-gym defaults in the measured AGC2 replay, not in the 5 ha planning
scenario. Fitted on even ISO weeks of AICU against heat, CO₂ and hourly indoor
temperature; tested on odd weeks and on the Reference compartment. Method and
held-out errors: [CALIBRATION.md](CALIBRATION.md).

| Field | Value | Tag | Source / rationale |
|---|---|---|---|
| `etaLampCool` | 0 (gl-gym 0.63) | documented | AGC2 ReadMe: 81 W/m² HPS plus Heliospectra LEDs, no active lamp cooling, so all lamp power heats the compartment. gl-gym's default is for water-cooled LEDs. |
| `aCov` | 216.6 m² per 144 m² floor (gl-gym 216.6) | fitted | Chosen from {140, 156, 180, 216.6}; at the edge of the range. |
| `aRoof` | 17.4 m² per 144 m² floor (gl-gym 52.2) | fitted | Chosen from {7.2, 12, 17.4, 26, 52.2}. The default is 36% of floor area. |
| `cLeakage` | 2e-5 (gl-gym 3e-5) | fitted | Chosen from {0.5, 1, 2, 3, 5} × 1e-5. |
| `tauRfNir` | 0.85 (gl-gym 0.57) | fitted | Chosen from {0.45, 0.57, 0.7, 0.85}; at the edge of the range. |
| `kThScr` | 1e-3 (gl-gym 5e-4) | fitted | Chosen from {1.25, 2.5, 5, 10, 20} × 1e-4. |
| `tauThScrFir` | 0.5 (gl-gym 0.15) | fitted | Chosen from {0.05, 0.15, 0.3, 0.5}; at the edge of the range. |
| AGC heat formula | `(t_rail − t_air) × 2.1 + (t_grow − t_air) × 0.62` W/m² | documented | AGC2 ReadMe, `Heat_cons`. Applied to simulated pipes so heat is compared like with like, and only while the simulated boiler valve is open, because the measured pipe sensors read 0 while a circuit is off. |
| Starting floor temperature | mean measured air temperature of the 7 days before | choice | A one-day replay otherwise starts the soil at gl-gym's 16.5 °C. Soil layers start on a straight line from the floor down to gl-gym's outdoor soil temperature. |
| AGC lamp power | 81 × HPS + 7.27 × blue + 25.3 × red + 6.23 × far-red + 22.72 × white W/m² | documented | AGC2 ReadMe, `ElecHigh`/`ElecLow`; LED intensities from `int_*_vip` (0–1000). |

"fitted" is a fourth tag used only here: chosen by a documented search against
measured data, with the held-out error published.

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
