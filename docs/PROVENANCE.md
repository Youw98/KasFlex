# Provenance of every operational number

Every number that materially affects the scenario, asset dispatch, safety retry
budget or surrogate model is registered below. The source of truth is
`configs/parameter_sources.yaml`; `kasflex parameters` joins it to the active
configuration and renders this table.

The registry is enforced, not advisory:

- `sourced` entries require a named source and URL;
- `assumption` entries are explicitly not measurements and should be replaced
  with Tahir's site data where available;
- `choice` entries are software or experiment settings, not physical claims;
- missing, unknown, or stale values fail validation and the test suite.

The list below is generated from the default Westland scenario. Run
`kasflex parameters --config your-site.yaml` to audit a different site, or
`kasflex parameters --json` for machine-readable output.

Operational parameters: 61 (7 sourced, 46 assumptions, 8 choices)

| Parameter | Current value | Unit | Status | Source or rationale |
|---|---:|---|---|---|
| `hub.floor_area_m2` | 50000 | m2 | assumption | Representative scale for a modern Dutch lit tomato site; replace with Tahir's actual area. |
| `hub.lamp_power_w_m2` | 110 | W/m2 | assumption | Representative HPS-era installed power density; must be replaced for the actual fixture layout. |
| `hub.lamp_ppfd_umol_m2_s` | 185 | umol/m2/s | assumption | Derived from 110 W/m2 at roughly 1.7 umol/J; fixture-specific measurement is preferred. |
| `hub.base_load_kw` | 150 | kW | assumption | Placeholder for pumps, fans, screens and site auxiliaries; marked as a guess in PROVENANCE.md. |
| `hub.contract.import_limit_kw` | 6000 | kW | assumption | Scenario contract sized above the default lamp field; replace with the signed connection agreement. |
| `hub.contract.export_limit_kw` | 4000 | kW | assumption | Scenario export ceiling; replace with the signed connection agreement. |
| `hub.contract.congestion_windows` | {16: (3000.0, 1000.0), 17: (3000.0, 1000.0), 18: (3000.0, 1000.0), 19: (3000.0, 1000.0)} | hour_to_[import_kw,export_kw] | assumption | Illustrative evening restriction, not a live DSO instruction. |
| `hub.battery.capacity_kwh` | 2000 | kWh | assumption | Representative two-hour battery for the 5 ha scenario; replace with the nameplate. |
| `hub.battery.max_charge_kw` | 1000 | kW | assumption | 0.5 C scenario limit, consistent with a two-hour system. |
| `hub.battery.max_discharge_kw` | 1000 | kW | assumption | 0.5 C scenario limit, consistent with a two-hour system. |
| `hub.battery.soc_min_frac` | 0.1 | fraction | assumption | Conservative operating reserve; the supplier warranty must replace it. |
| `hub.battery.soc_max_frac` | 0.9 | fraction | assumption | Conservative operating reserve; the supplier warranty must replace it. |
| `hub.battery.soc_init_frac` | 0.5 | fraction | choice | Deterministic midpoint used to make scenario comparisons reproducible. |
| `hub.battery.charge_efficiency` | 0.92 | fraction | sourced | [U.S. Department of Energy, Energy Storage Technology and Cost Characterization Report](https://www.energy.gov/sites/default/files/2019/07/f65/Storage%20Cost%20and%20Performance%20Characterization%20Report_Final.pdf) — Paired charge/discharge values give about 85% round-trip efficiency including system losses. |
| `hub.battery.discharge_efficiency` | 0.92 | fraction | sourced | [U.S. Department of Energy, Energy Storage Technology and Cost Characterization Report](https://www.energy.gov/sites/default/files/2019/07/f65/Storage%20Cost%20and%20Performance%20Characterization%20Report_Final.pdf) — Paired charge/discharge values give about 85% round-trip efficiency including system losses. |
| `hub.battery.c_rate_max` | 0.5 | 1/hour | assumption | Two-hour battery operating envelope; use the supplier's warranted C-rate in a real site profile. |
| `hub.chp.electrical_capacity_kw` | 1500 | kWe | assumption | Representative mid-size greenhouse gas engine; replace with the installation nameplate. |
| `hub.chp.heat_to_power_ratio` | 1.1 | kWth/kWe | sourced | [US EPA Catalog of CHP Technologies, reciprocating engines](https://www.epa.gov/chp/catalog-chp-technologies) — Representative 1–2 MW natural-gas reciprocating engine. |
| `hub.chp.electrical_efficiency` | 0.375 | fraction_HHV | sourced | [US EPA Catalog of CHP Technologies, reciprocating engines](https://www.epa.gov/chp/catalog-chp-technologies) — Representative HHV electrical efficiency at this engine scale. |
| `hub.chp.min_load_frac` | 0.5 | fraction | assumption | Generic minimum stable load; replace with the engine supplier curve. |
| `hub.chp.min_run_hours` | 2 | hour | assumption | Operational anti-cycling rule, not a physical measurement. |
| `hub.chp.min_down_hours` | 2 | hour | assumption | Operational anti-cycling rule, not a physical measurement. |
| `hub.chp.ramp_kw_per_hour` | 1500 | kW/hour | assumption | Non-binding hourly ramp for a fast-start gas engine; supplier data should replace it. |
| `hub.chp.co2_kg_per_kwh_e` | 0.5 | kg/kWh_e | sourced | [Derived from natural-gas CO2 intensity divided by the registered CHP electrical efficiency](https://www.epa.gov/chp/catalog-chp-technologies) — Derived value; must move if fuel carbon intensity or electrical efficiency changes. |
| `hub.chp.initially_running` | False | boolean | choice | Reproducible scenario initial state. |
| `hub.chp.hours_in_current_state` | 99 | hour | choice | Makes the initial state unconstrained by a previous run/down interval. |
| `hub.boiler.thermal_capacity_kw` | 8000 | kWth | assumption | Covers roughly 130 W/m2 plus margin at the 5 ha scenario scale; replace with nameplate data. |
| `hub.boiler.efficiency` | 0.9 | fraction_HHV | assumption | Representative modern greenhouse boiler seasonal efficiency; measure or use supplier data. |
| `hub.boiler.ramp_kw_per_hour` | 8000.0 | kW/hour | assumption | Non-binding hourly ramp assumption for a fast boiler. |
| `hub.buffer.capacity_kwh` | 43600 | kWhth | sourced | [Derived from 1,500 m3 water and a 25 K working temperature difference](https://www.hortinergy.com/knowledgebase/greenhouse-heating-system/) — Scenario derivation for about 300 m3/ha; replace with tank geometry and operating temperatures. |
| `hub.buffer.max_charge_kw` | 3000 | kWth | assumption | Pipework and heat-exchanger placeholder. |
| `hub.buffer.max_discharge_kw` | 3000 | kWth | assumption | Pipework and heat-exchanger placeholder. |
| `hub.buffer.level_min_frac` | 0.05 | fraction | assumption | Practical dead-volume reserve. |
| `hub.buffer.level_max_frac` | 0.95 | fraction | assumption | Expansion/headroom reserve. |
| `hub.buffer.level_init_frac` | 0.5 | fraction | choice | Deterministic midpoint used for reproducible comparisons. |
| `hub.buffer.standing_loss_frac_per_hour` | 0.005 | fraction/hour | assumption | Explicit guess pending tank U-value, geometry and temperature measurements. |
| `hub.pv.peak_kw` | 500 | kWp | assumption | Illustrative PV plant; replace with inverter/nameplate data. |
| `hub.pv.performance_ratio` | 0.85 | fraction | assumption | Representative system performance ratio; calculate from the actual array under IEC 61724 practice. |
| `hub.crop.dli_target_mol_m2` | 10.0 | mol/m2/day | assumption | Supplemental-light scenario target, not a universal tomato optimum. |
| `hub.crop.dli_tolerance_mol_m2` | 3.0 | mol/m2/day | assumption | Feasibility band chosen for the demonstration. |
| `hub.crop.temp_min_c` | 15.0 | degC | assumption | Conservative generic tomato lower limit; Tahir must set cultivar and growth-stage limits. |
| `hub.crop.temp_max_c` | 32.0 | degC | sourced | [Sato et al., high-temperature effects on tomato fruit set](https://doi.org/10.1093/jxb/53.371.1187) — Generic upper stress boundary, not a crop-control setpoint. |
| `hub.crop.rh_max_pct` | 85.0 | percent | assumption | Generic disease-risk ceiling; cultivar, airflow and condensation conditions matter. |
| `hub.crop.co2_min_ppm` | 300.0 | ppm | assumption | Lower enrichment-band guard near ambient concentration. |
| `hub.crop.co2_max_ppm` | 1600.0 | ppm | assumption | Generic enrichment ceiling; site policy and ventilation should replace it. |
| `gas_price_eur_kwh` | 0.035 | EUR/kWh_HHV | assumption | Manual scenario input because KasFlex has no licensed live TTF feed. |
| `dispatch.liquid_co2_eur_kg` | 0.3 | EUR/kg | assumption | Delivered liquid CO2 placeholder; replace with the grower's contract. |
| `history_days` | 60 | day | choice | Training-window choice, long enough for the current lag features. |
| `checker.max_revisions` | 3 | count | choice | Experimental retry budget before baseline fallback. |
| `scenario.seed` | 0 | integer | choice | Deterministic random seed for reproducible runs; it is not a physical measurement. |
| `scenario.latitude` | 51.99 | decimal_degrees | assumption | Westland demonstration location; replace with Tahir's greenhouse coordinates. |
| `scenario.longitude` | 4.25 | decimal_degrees | assumption | Westland demonstration location; replace with Tahir's greenhouse coordinates. |
| `surrogate.setpoint_day_c` | 19.5 | degC | assumption | Simplified development-model setpoint; not read from a grower climate strategy. |
| `surrogate.setpoint_night_c` | 16.5 | degC | assumption | Simplified development-model setpoint; not read from a grower climate strategy. |
| `surrogate.heat_loss_kw_per_m2_per_k` | 0.0062 | kW/m2/K | assumption | Lumped cover-loss coefficient for a screened greenhouse; validation shows it needs calibration. |
| `surrogate.thermal_mass_kwh_per_m2_per_k` | 0.0085 | kWh/m2/K | assumption | Lumped thermal mass selected for stable five-minute integration; not measured. |
| `surrogate.lamp_power_kw_per_m2` | 0.11 | kW/m2 | assumption | Mirrors the default EnergyHub lamp power. |
| `surrogate.lamp_heat_fraction` | 0.85 | fraction | assumption | Simplified sensible-heat fraction; fixture and radiation model dependent. |
| `surrogate.co2_uptake_kg_per_m2_per_hour_full_light` | 0.0012 | kg/m2/hour | assumption | Linear uptake proxy; measured AGC2 error shows it is not calibrated. |
| `surrogate.vent_kw_per_m2_per_k` | 0.15 | kW/m2/K | assumption | Proportional ventilation proxy used to prevent unrealistic solar overheating. |
| `surrogate.substeps_per_hour` | 12 | count | choice | Five-minute numerical integration step. |
