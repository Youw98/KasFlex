# Operational parameters

This is the canonical human-readable register generated from `configs/parameter_sources.yaml`. Every operational number is machine-checked as sourced, an explicit assumption, or a software choice. Replace site assumptions with signed contracts, nameplates, or measurements before operational use.

Counts: assumption=49, choice=8, sourced=7.

| Parameter | Current value | Plausible range | Unit | Status | Source or rationale |
|---|---:|---|---|---|---|
| `hub.floor_area_m2` | 50000 | site-specific | m2 | assumption | Representative scale for a modern Dutch lit tomato site; replace with Tahir's actual area. |
| `hub.lamp_power_w_m2` | 110 | site-specific | W/m2 | assumption | Representative HPS-era installed power density; must be replaced for the actual fixture layout. |
| `hub.lamp_ppfd_umol_m2_s` | 185 | site-specific | umol/m2/s | assumption | Derived from 110 W/m2 at roughly 1.7 umol/J; fixture-specific measurement is preferred. |
| `hub.base_load_kw` | 150 | site-specific | kW | assumption | Placeholder for pumps, fans, screens and site auxiliaries; marked as a guess in PARAMETERS.md. |
| `hub.contract.import_limit_kw` | 6000 | site-specific | kW | assumption | Scenario contract sized above the default lamp field; replace with the signed connection agreement. |
| `hub.contract.export_limit_kw` | 4000 | [0, 10000] | kW | assumption | Scenario export ceiling; replace with the signed connection agreement. |
| `hub.contract.contracted_base_volume_kwh` | 42000 | [0, 150000] | kWh/day | assumption | Illustrative day-ahead base position; replace with Tahir's supplier nomination. |
| `hub.contract.contracted_price_eur_kwh` | 0.11 | [0.04, 0.3] | EUR/kWh | assumption | Illustrative fixed contract price; replace with the applicable supply contract. |
| `hub.contract.imbalance_spread_eur_kwh` | 0.015 | [0.0, 0.1] | EUR/kWh | assumption | Illustrative settlement spread, not a live imbalance tariff. |
| `hub.contract.congestion_windows` | {16: (3000.0, 1000.0), 17: (3000.0, 1000.0), 18: (3000.0, 1000.0), 19: (3000.0, 1000.0)} | site-specific | hour_to_[import_kw,export_kw] | assumption | Illustrative evening restriction, not a live DSO instruction. |
| `hub.battery.capacity_kwh` | 2000 | [0, 20000] | kWh | assumption | Representative two-hour battery for the 5 ha scenario; replace with the nameplate. |
| `hub.battery.max_charge_kw` | 1000 | site-specific | kW | assumption | 0.5 C scenario limit, consistent with a two-hour system. |
| `hub.battery.max_discharge_kw` | 1000 | site-specific | kW | assumption | 0.5 C scenario limit, consistent with a two-hour system. |
| `hub.battery.soc_min_frac` | 0.1 | site-specific | fraction | assumption | Conservative operating reserve; the supplier warranty must replace it. |
| `hub.battery.soc_max_frac` | 0.9 | site-specific | fraction | assumption | Conservative operating reserve; the supplier warranty must replace it. |
| `hub.battery.soc_init_frac` | 0.5 | site-specific | fraction | choice | Deterministic midpoint used to make scenario comparisons reproducible. |
| `hub.battery.charge_efficiency` | 0.92 | site-specific | fraction | sourced | [U.S. Department of Energy, Energy Storage Technology and Cost Characterization Report](https://www.energy.gov/sites/default/files/2019/07/f65/Storage%20Cost%20and%20Performance%20Characterization%20Report_Final.pdf) — Paired charge/discharge values give about 85% round-trip efficiency including system losses. |
| `hub.battery.discharge_efficiency` | 0.92 | site-specific | fraction | sourced | [U.S. Department of Energy, Energy Storage Technology and Cost Characterization Report](https://www.energy.gov/sites/default/files/2019/07/f65/Storage%20Cost%20and%20Performance%20Characterization%20Report_Final.pdf) — Paired charge/discharge values give about 85% round-trip efficiency including system losses. |
| `hub.battery.c_rate_max` | 0.5 | [0.25, 2.0] | 1/hour | assumption | Two-hour battery operating envelope; use the supplier's warranted C-rate in a real site profile. |
| `hub.chp.electrical_capacity_kw` | 1500 | [0, 10000] | kWe | assumption | Representative mid-size greenhouse gas engine; replace with the installation nameplate. |
| `hub.chp.heat_to_power_ratio` | 1.1 | site-specific | kWth/kWe | sourced | [US EPA Catalog of CHP Technologies, reciprocating engines](https://www.epa.gov/chp/catalog-chp-technologies) — Representative 1–2 MW natural-gas reciprocating engine. |
| `hub.chp.electrical_efficiency` | 0.375 | [0.3, 0.45] | fraction_HHV | sourced | [US EPA Catalog of CHP Technologies, reciprocating engines](https://www.epa.gov/chp/catalog-chp-technologies) — Representative HHV electrical efficiency at this engine scale. |
| `hub.chp.min_load_frac` | 0.5 | site-specific | fraction | assumption | Generic minimum stable load; replace with the engine supplier curve. |
| `hub.chp.min_run_hours` | 2 | site-specific | hour | assumption | Operational anti-cycling rule, not a physical measurement. |
| `hub.chp.min_down_hours` | 2 | site-specific | hour | assumption | Operational anti-cycling rule, not a physical measurement. |
| `hub.chp.ramp_kw_per_hour` | 1500 | site-specific | kW/hour | assumption | Non-binding hourly ramp for a fast-start gas engine; supplier data should replace it. |
| `hub.chp.co2_kg_per_kwh_e` | 0.5 | site-specific | kg/kWh_e | sourced | [Derived from natural-gas CO2 intensity divided by the registered CHP electrical efficiency](https://www.epa.gov/chp/catalog-chp-technologies) — Derived value; must move if fuel carbon intensity or electrical efficiency changes. |
| `hub.chp.initially_running` | False | site-specific | boolean | choice | Reproducible scenario initial state. |
| `hub.chp.hours_in_current_state` | 99 | site-specific | hour | choice | Makes the initial state unconstrained by a previous run/down interval. |
| `hub.boiler.thermal_capacity_kw` | 8000 | site-specific | kWth | assumption | Covers roughly 130 W/m2 plus margin at the 5 ha scenario scale; replace with nameplate data. |
| `hub.boiler.efficiency` | 0.9 | [0.8, 0.98] | fraction_HHV | assumption | Representative modern greenhouse boiler seasonal efficiency; measure or use supplier data. |
| `hub.boiler.ramp_kw_per_hour` | 8000.0 | site-specific | kW/hour | assumption | Non-binding hourly ramp assumption for a fast boiler. |
| `hub.buffer.capacity_kwh` | 43600 | [0, 200000] | kWhth | sourced | [Derived from 1,500 m3 water and a 25 K working temperature difference](https://www.hortinergy.com/knowledgebase/greenhouse-heating-system/) — Scenario derivation for about 300 m3/ha; replace with tank geometry and operating temperatures. |
| `hub.buffer.max_charge_kw` | 3000 | site-specific | kWth | assumption | Pipework and heat-exchanger placeholder. |
| `hub.buffer.max_discharge_kw` | 3000 | site-specific | kWth | assumption | Pipework and heat-exchanger placeholder. |
| `hub.buffer.level_min_frac` | 0.05 | site-specific | fraction | assumption | Practical dead-volume reserve. |
| `hub.buffer.level_max_frac` | 0.95 | site-specific | fraction | assumption | Expansion/headroom reserve. |
| `hub.buffer.level_init_frac` | 0.5 | site-specific | fraction | choice | Deterministic midpoint used for reproducible comparisons. |
| `hub.buffer.standing_loss_frac_per_hour` | 0.005 | site-specific | fraction/hour | assumption | Explicit guess pending tank U-value, geometry and temperature measurements. |
| `hub.pv.peak_kw` | 500 | site-specific | kWp | assumption | Illustrative PV plant; replace with inverter/nameplate data. |
| `hub.pv.performance_ratio` | 0.85 | [0.7, 0.9] | fraction | assumption | Representative system performance ratio; calculate from the actual array under IEC 61724 practice. |
| `hub.crop.dli_target_mol_m2` | 10.0 | [5, 30] | mol/m2/day | assumption | Supplemental-light scenario target, not a universal tomato optimum. |
| `hub.crop.dli_tolerance_mol_m2` | 3.0 | site-specific | mol/m2/day | assumption | Feasibility band chosen for the demonstration. |
| `hub.crop.temp_min_c` | 15.0 | [12, 20] | degC | assumption | Conservative generic tomato lower limit; Tahir must set cultivar and growth-stage limits. |
| `hub.crop.temp_max_c` | 32.0 | [26, 35] | degC | sourced | [Sato et al., high-temperature effects on tomato fruit set](https://doi.org/10.1093/jxb/53.371.1187) — Generic upper stress boundary, not a crop-control setpoint. |
| `hub.crop.rh_max_pct` | 85.0 | [75, 95] | percent | assumption | Generic disease-risk ceiling; cultivar, airflow and condensation conditions matter. |
| `hub.crop.co2_min_ppm` | 300.0 | site-specific | ppm | assumption | Lower enrichment-band guard near ambient concentration. |
| `hub.crop.co2_max_ppm` | 1600.0 | site-specific | ppm | assumption | Generic enrichment ceiling; site policy and ventilation should replace it. |
| `gas_price_eur_kwh` | 0.035 | site-specific | EUR/kWh_HHV | assumption | Manual scenario input because KasFlex has no licensed live TTF feed. |
| `dispatch.liquid_co2_eur_kg` | 0.3 | site-specific | EUR/kg | assumption | Delivered liquid CO2 placeholder; replace with the grower's contract. |
| `history_days` | 60 | site-specific | day | choice | Training-window choice, long enough for the current lag features. |
| `checker.max_revisions` | 3 | site-specific | count | choice | Experimental retry budget before baseline fallback. |
| `scenario.seed` | 0 | site-specific | integer | choice | Deterministic random seed for reproducible runs; it is not a physical measurement. |
| `scenario.latitude` | 51.99 | site-specific | decimal_degrees | assumption | Westland demonstration location; replace with Tahir's greenhouse coordinates. |
| `scenario.longitude` | 4.25 | site-specific | decimal_degrees | assumption | Westland demonstration location; replace with Tahir's greenhouse coordinates. |
| `surrogate.setpoint_day_c` | 19.5 | [17, 24] | degC | assumption | Simplified development-model setpoint; not read from a grower climate strategy. |
| `surrogate.setpoint_night_c` | 16.5 | [14, 20] | degC | assumption | Simplified development-model setpoint; not read from a grower climate strategy. |
| `surrogate.heat_loss_kw_per_m2_per_k` | 0.0062 | site-specific | kW/m2/K | assumption | Lumped cover-loss coefficient for a screened greenhouse; validation shows it needs calibration. |
| `surrogate.thermal_mass_kwh_per_m2_per_k` | 0.0085 | site-specific | kWh/m2/K | assumption | Lumped thermal mass selected for stable five-minute integration; not measured. |
| `surrogate.lamp_power_kw_per_m2` | 0.11 | site-specific | kW/m2 | assumption | Mirrors the default EnergyHub lamp power. |
| `surrogate.lamp_heat_fraction` | 0.85 | site-specific | fraction | assumption | Simplified sensible-heat fraction; fixture and radiation model dependent. |
| `surrogate.co2_uptake_kg_per_m2_per_hour_full_light` | 0.0012 | site-specific | kg/m2/hour | assumption | Linear uptake proxy; measured AGC2 error shows it is not calibrated. |
| `surrogate.vent_kw_per_m2_per_k` | 0.15 | site-specific | kW/m2/K | assumption | Proportional ventilation proxy used to prevent unrealistic solar overheating. |
| `surrogate.substeps_per_hour` | 12 | site-specific | count | choice | Five-minute numerical integration step. |

