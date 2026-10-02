# Parameter provenance

This is the canonical reviewer-facing parameter table for KasFlex.

**Rule:** every physical or economic value is either linked to a concrete source or
labelled **ASSUMPTION**. An assumption is a scenario choice, not a measured fact and
not a finding. Ranges are included where a single representative value is used in
the default 5 ha lit-tomato scenario.

The longer engineering notes remain in [PROVENANCE.md](PROVENANCE.md). Dataset
provenance is in [DATA.md](DATA.md).

| Parameter | Default value | Unit | Source | Plausible range / notes |
|---|---:|---|---|---|
| Greenhouse floor area | 50,000 | m² | **ASSUMPTION** | Representative commercial lit greenhouse; AGC validation uses 96 m². |
| Base electrical load | 150 | kW | **ASSUMPTION** | Pumps/fans/screens/packing; use site metering when available. Illustrative range 75–300 kW. |
| Lamp power density | 110 | W/m² | **ASSUMPTION** | Representative HPS-era lit tomato installation; roughly 100–120 W/m². |
| Lamp PPFD at full power | 185 | µmol/m²/s | **ASSUMPTION** | Consistent with ~1.7 µmol/J at 110 W/m²; LED installations differ materially. |
| Grid import contract | 6,000 | kW | **ASSUMPTION** | Sized to carry the lamp field plus base load. Replace with the grower's ATO/connection agreement. |
| Grid export contract | 4,000 | kW | **ASSUMPTION** | Scenario choice; may be lower or zero under a non-firm agreement. |
| Congestion window | 3,000 import / 1,000 export | kW | **ASSUMPTION** | 16:00–19:00 scenario stand-in; real signals must come from the DSO. |
| Contracted base electricity position | 1,800 | kW | **ASSUMPTION** | New procurement-layer demo input. Set from the grower's contracted portfolio. |
| Contracted electricity price | 0.085 | EUR/kWh | **ASSUMPTION** | Demonstrator forward/base price; replace with actual contract data. |
| Short-position settlement spread | 0.012 | EUR/kWh | **ASSUMPTION** | Illustrative transaction/imbalance spread added to spot for a short position. |
| Long-position settlement spread | 0.008 | EUR/kWh | **ASSUMPTION** | Illustrative spread deducted from spot for a long position. |
| Battery capacity | 2,000 | kWh | **ASSUMPTION** | Representative 2 MWh BESS for a 5 ha site; scenario range roughly 0–10 MWh. |
| Battery charge power | 1,000 | kW | **ASSUMPTION** | 0.5 C representative two-hour battery. |
| Battery discharge power | 1,000 | kW | **ASSUMPTION** | Same basis as charge power. |
| Battery minimum SOC | 10 | % | Manufacturer practice; see [PROVENANCE.md](PROVENANCE.md) | Operating reserve for cycle life. |
| Battery maximum SOC | 90 | % | Manufacturer practice; see [PROVENANCE.md](PROVENANCE.md) | Matching upper reserve. |
| Battery initial SOC | 50 | % | **ASSUMPTION** | Reproducible midpoint start. |
| Battery charge efficiency | 92 | % | Published grid-scale Li-ion values; see [PROVENANCE.md](PROVENANCE.md) | Paired with discharge efficiency; ~85% round trip. |
| Battery discharge efficiency | 92 | % | Published grid-scale Li-ion values; see [PROVENANCE.md](PROVENANCE.md) | Paired with charge efficiency. |
| Battery C-rate | 0.5 | 1/h | Utility-scale two-hour battery convention; see [PROVENANCE.md](PROVENANCE.md) | Maximum power is also limited by explicit kW ratings. |
| CHP electrical capacity | 1,500 | kWe | **ASSUMPTION** | Representative greenhouse engine; Dutch installations span roughly 0.5–5 MW. |
| CHP heat-to-power ratio | 1.1 | kWth/kWe | US EPA CHP catalogue; see [PROVENANCE.md](PROVENANCE.md) | Interpolated for a ~1.5 MW gas engine. |
| CHP electrical efficiency | 37.5 | % HHV | US EPA CHP catalogue; see [PROVENANCE.md](PROVENANCE.md) | Size-dependent. |
| CHP minimum load | 50 | % | **ASSUMPTION** | Representative practical turndown; confirm from engine datasheet. |
| CHP minimum run time | 2 | h | **ASSUMPTION** | Represents maintenance/thermal cycling preference at hourly resolution. |
| CHP minimum down time | 2 | h | **ASSUMPTION** | Same rationale as minimum run. |
| CHP ramp | 1,500 | kW/h | Gas-engine operating characteristics; see [PROVENANCE.md](PROVENANCE.md) | Effectively non-binding at one-hour resolution. |
| CHP CO₂ factor | 0.50 | kg/kWh_e | Natural-gas emission factor + electrical efficiency; see [PROVENANCE.md](PROVENANCE.md) | Used for recoverable flue-gas CO₂ accounting. |
| Boiler thermal capacity | 8,000 | kWth | GreenLight heating-power requirement; see [PROVENANCE.md](PROVENANCE.md) | 6.5 MW estimated peak plus headroom. |
| Boiler efficiency | 90 | % HHV | **ASSUMPTION** | Modern condensing greenhouse boiler; confirm from site/datasheet. |
| Heat-buffer capacity | 43,600 | kWhth | Dutch greenhouse buffer sizing references; see [PROVENANCE.md](PROVENANCE.md) | ~1,500 m³ × working temperature swing for 5 ha. |
| Heat-buffer charge power | 3,000 | kWth | **ASSUMPTION** | Sized to accept major heat sources concurrently. |
| Heat-buffer discharge power | 3,000 | kWth | **ASSUMPTION** | Sized to cover a large share of night heat demand. |
| Heat-buffer minimum level | 5 | % | **ASSUMPTION** | Practical dead volume. |
| Heat-buffer maximum level | 95 | % | **ASSUMPTION** | Head-space / operating reserve. |
| Heat-buffer standing loss | 0.5 | %/h | **ASSUMPTION** | Placeholder requiring manufacturer/site validation; sensitivity testing recommended. |
| PV peak power | 500 | kWp | **ASSUMPTION** | Modest PV contribution so it matters without dominating the scenario. |
| PV performance ratio | 0.85 | fraction | IEC 61724 performance-ratio concept; see [PROVENANCE.md](PROVENANCE.md) | Covers inverter/cable/soiling losses. |
| Supplemental-light target | 10 | mol/m²/day | **ASSUMPTION** | Winter lit-tomato scenario target; cultivar and strategy dependent. |
| Supplemental-light tolerance | ±3 | mol/m²/day | **ASSUMPTION** | Chosen so a feasible winter plan exists; sensitivity parameter. |
| Crop minimum temperature | 15 | °C | Tomato production literature; see [PROVENANCE.md](PROVENANCE.md) | Cultivar/stage dependent. |
| Crop maximum temperature | 32 | °C | Tomato pollen/fruit-set literature; see [PROVENANCE.md](PROVENANCE.md) | Upper safety envelope, not an optimal setpoint. |
| Maximum relative humidity | 85 | % | Botrytis-risk literature; see [PROVENANCE.md](PROVENANCE.md) | Operational threshold, not a universal optimum. |
| Minimum CO₂ | 300 | ppm | **ASSUMPTION** | Lower enrichment/control bound. |
| Maximum CO₂ | 1,600 | ppm | **ASSUMPTION** | Representative upper enrichment bound; site strategy differs. |
| Gas price | 0.035 | EUR/kWh HHV | **ASSUMPTION** | No live free TTF feed in KasFlex; configure for each study period. |
| Electricity day-ahead price | fetched | EUR/kWh | ENTSO-E day-ahead data | Converted from EUR/MWh and checksummed; see [DATA.md](DATA.md). |
| Weather forecast | fetched | °C, W/m² | Open-Meteo historical forecast archive | Forecast stays separate from realised weather. |
| Realised weather | fetched | °C, W/m² | Open-Meteo historical archive / validation sources | Used only for evaluation, never leaked into planning. |
| Weather-error RMSE (fallback) | 2.0 / 60 | °C / W/m² | **ASSUMPTION** | Only used until enough paired forecast/actual days exist; UI labels it assumed. |
| Uncertainty Monte Carlo samples | 24 | samples | **ASSUMPTION** | Computational trade-off for interactive use; deterministic seed. |
| Checker max revisions | 3 | attempts | **ASSUMPTION / experimental factor** | Study design choice rather than physical parameter. |
| Random seed | 0 | integer | Experimental convention | Reproducibility only. |

## What still needs replacing first

The highest-value assumptions to replace with site-specific or published values are:

1. contracted base volume and contract price;
2. base electrical load;
3. CHP turndown/minimum run rules;
4. heat-buffer standing loss;
5. gas price for the study period;
6. crop light target/tolerance for the selected cultivar and season.

## GreenLight parameters

Climate and crop-physics constants used by GreenLight are inherited from the
GreenLight/GreenLight-Gym2 worker and are not duplicated here. They retain their own
licensing and source provenance. KasFlex still treats the resulting greenhouse
outputs as **not validated** until the AGC measured-data comparison is actually run
and published in [VALIDATION.md](VALIDATION.md).
