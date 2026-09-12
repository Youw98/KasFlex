# Where the numbers come from

Every default in [`kasflex/energy/assets.py`](../src/kasflex/energy/assets.py) is
listed here with its source, or marked **unsourced** where there is not one yet.

This table exists because these numbers propagate into every cost figure the
system produces. A value nobody can trace is a value nobody can defend, and
"unsourced" written down is worth more than a citation invented to fill a gap.

**Status key**

| | |
|---|---|
| ✅ | Matches a published figure |
| ⚠️ | Sourced, but KasFlex sits at the optimistic edge or outside the cited range |
| ❌ | **Unsourced.** A placeholder, kept only because the model needs a number |

Where KasFlex disagrees with a source, the number has been **left alone** and the
disagreement recorded. Changing values silently would invalidate every result
produced so far; the decision to change them is the project's, not this document's.

---

## Combined heat and power

Primary reference: **US EPA, *Catalog of CHP Technologies*, Section 2: Reciprocating
Internal Combustion Engines**, Table 2-2 "Gas Spark Ignition Engine CHP — Typical
Performance Parameters" (data compiled by ICF from vendor-supplied data).
[PDF](https://www.epa.gov/sites/default/files/2015-07/documents/catalog_of_chp_technologies_section_2._technology_characterization_-_reciprocating_internal_combustion_engines.pdf)

The relevant rows, since KasFlex's 1,500 kW unit falls between systems 3 and 4:

| | System 3 | System 4 |
|---|---|---|
| Baseload electric capacity | 1,121 kW | 3,326 kW |
| Electrical efficiency (HHV) | 36.8% | 40.4% |
| Total CHP efficiency | 78.4% | 78.3% |
| Power/heat ratio | 0.89 | 1.06 |

| Parameter | KasFlex | Source says | Status |
|---|---|---|---|
| `electrical_capacity_kw` | 1500.0 | Dutch greenhouse CHP units are "typically between 0.5 and 5 MW" | ✅ |
| `electrical_efficiency` | 0.40 | 36.8% at 1.1 MW, 40.4% at 3.3 MW (HHV). Interpolating to 1.5 MW gives ≈37.5% | ⚠️ **~2.5 points optimistic.** 0.40 is the figure for a unit twice this size |
| `heat_to_power_ratio` | 1.2 | Power/heat 0.89 at 1.1 MW → heat/power ≈ **1.12**; 1.06 at 3.3 MW → ≈0.94 | ⚠️ Slightly high; ≈1.1 would match the cited unit |
| `min_load_frac` | 0.50 | EPA characterises part-load behaviour down to 50% load and notes gas engines degrade less than turbines there | ✅ |
| `co2_kg_per_kwh_e` | 0.45 | Derived: 0.185–0.205 kg CO₂/kWh gas ÷ 0.40 electrical efficiency = **0.46–0.51 kg/kWh_e** | ✅ Consistent, at the low edge |
| `min_run_hours` / `min_down_hours` | 2 / 2 | — | ❌ Unsourced. Plausible for a gas engine but not taken from a specification |
| `ramp_kw_per_hour` | 1500.0 | — | ❌ Unsourced. Equals full capacity, i.e. effectively unconstrained ramping |

Dutch sector context: CHP diffused from ~1,000 MWe (2003) to over 3,000 MWe (2009)
in Dutch greenhouse horticulture, and units are heat-demand-driven so heat is
rarely dumped. Sources:
[Greenhouse Canada](https://www.greenhousecanada.com/special-series-world-report-1-cogeneration-in-the-netherlands-20013/),
[DutchGreenhouses](https://dutchgreenhouses.com/sustainability/chp),
and van der Velden & Smit, *Combined heat and power in Dutch greenhouses: a case
study of technology diffusion*, **Energy Policy** (2015),
[ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0301421515300847).

CO₂ emission factor for natural gas:
[Carbon Independent](https://www.carbonindependent.org/15.html) (0.185 kg/kWh, UK)
and [Climatiq / UK BEIS](https://www.climatiq.io/data/emission-factor/9279dd25-8940-4cbb-a695-b82dee5a9bce).

---

## Boiler

| Parameter | KasFlex | Source says | Status |
|---|---|---|---|
| `efficiency` | 0.90 | Condensing boilers exceed **90% on the higher heating value**; greenhouse condensing unit heaters are sold at 93%. Non-condensing units cap at 80–83% | ✅ Correct for a condensing boiler, and conservative |
| `thermal_capacity_kw` | 8000.0 | — | ❌ Unsourced. Sized to cover peak demand of the default 5 ha greenhouse |
| `ramp_kw_per_hour` | 8000.0 | — | ❌ Unsourced. Effectively unconstrained |

Sources: [Wikipedia — Condensing boiler](https://en.wikipedia.org/wiki/Condensing_boiler),
[Greenhouse Management](https://www.greenhousemag.com/article/tech-solutions-condensing-boilers-and-heaters/),
[UMass Amherst CAFE](https://www.umass.edu/agriculture-food-environment/greenhouse-floriculture/fact-sheets/upgrading-greenhouse-heating-system).

---

## Battery

| Parameter | KasFlex | Source says | Status |
|---|---|---|---|
| `c_rate_max` | 0.5 | "Battery energy storage with a 2-hour duration corresponds to a maximum C-rate of 0.5 for grid-scale applications" | ✅ |
| `capacity_kwh` / `max_charge_kw` | 2000 / 1000 | 2000 ÷ 1000 = **2-hour duration**, internally consistent with the C-rate above | ✅ |
| `charge_efficiency` × `discharge_efficiency` | 0.95 × 0.95 = **90.3% round trip** | Cell level reaches 97%, but **system level** measures 72.8% on a 6 MW/7.5 MWh installation and 85% average falling to 65% at low power | ⚠️ **Optimistic.** This is a cell-level figure used where a system-level one belongs; it ignores inverter and auxiliary losses. A system-level 0.92 × 0.92 (≈85%) would be defensible |
| `soc_min_frac` / `soc_max_frac` | 0.10 / 0.90 | 80% usable window is conventional for cycle life, though some vendors rate 100% DoD | ✅ Conservative |
| `soc_init_frac` | 0.50 | — | ❌ Unsourced. A modelling convention, not a measurement |

Sources: [ScienceDirect — utility-scale Li-ion ageing and energy performance](https://www.sciencedirect.com/science/article/pii/S2352152X23006291),
[ScienceDirect — grid-connected BESS efficiency analysis](https://www.sciencedirect.com/science/article/abs/pii/S2214785318318947),
[OSTI — stationary Li-ion energy efficiency evaluation](https://www.osti.gov/servlets/purl/1409737).

---

## Heat buffer

| Parameter | KasFlex | Source says | Status |
|---|---|---|---|
| `capacity_kwh` | 8000.0 | Dutch practice is **300 m³ per hectare**. For the default 5 ha that is 1,500 m³. Over a realistic ΔT of 25 °C (85 °C → 60 °C) that stores ≈**43,600 kWh** | ⚠️ **KasFlex's buffer is roughly five times smaller than Dutch practice.** This materially understates how much load-shifting a real greenhouse can do, and therefore understates the value of flexibility |
| `standing_loss_frac_per_hour` | 0.005 | Tanks are insulated with ≥200 mm mineral wool to a U-value below 0.3 W/m²K, but no per-hour loss figure was found | ❌ **Unsourced.** Derivable from the U-value and tank geometry; not yet done |
| `level_min_frac` / `level_max_frac` | 0.05 / 0.95 | — | ❌ Unsourced |

Arithmetic for the capacity row: 1,500 m³ × 25 K × 1.163 kWh·m⁻³·K⁻¹ ≈ 43,600 kWh.

Sources: [Hortinergy — water buffer tank design](https://www.hortinergy.com/water-buffer-tank-design/)
(300 m³/ha, and the 85 °C → 60 °C example),
[VB Greenhouses — heat buffer tanks](https://vb-greenhouses.com/greenhouses/heat-buffer-tanks)
(insulation and U-value).

---

## Crop limits

| Parameter | KasFlex | Source says | Status |
|---|---|---|---|
| `temp_min_c` | 15.0 | Absolute tolerable minimum **12 °C**; night optimum 16–18 °C | ✅ Sits sensibly between the two |
| `temp_max_c` | 34.0 | Absolute tolerable maximum **32 °C**; keep day extremes below 30–32 °C to protect pollen and fruit set | ⚠️ **2 °C above the cited tolerable maximum.** The checker would currently permit temperatures the literature treats as damaging |
| `dli_target_mol_m2` | 10.0 | Total DLI optimum for tomato is **20–30 mol·m⁻²·d⁻¹**. KasFlex's figure is the *supplemental* portion, so it is not directly comparable — winter natural light inside a Dutch greenhouse is roughly 3–7 mol·m⁻²·d⁻¹, implying a supplemental need well above 10 to reach the optimum | ⚠️ Defensible only for a partially lit crop. State the assumption when reporting |
| `dli_tolerance_mol_m2` | 3.0 | — | ❌ Unsourced |
| `rh_max_pct` | 85.0 | — | ❌ Unsourced. Consistent with common practice but no citation obtained |
| `co2_min_ppm` / `co2_max_ppm` | 300 / 1600 | CO₂ enrichment can raise production by up to 25%; typical dosing targets sit well above ambient | ⚠️ Range is plausible but the specific bounds are unsourced |

Sources: [DryGair — ideal conditions for greenhouse tomatoes](https://drygair.com/blog/what-are-the-ideal-conditions-for-greenhouse-tomatoes/),
Shamshiri et al., *Review of optimum temperature, humidity, and vapour pressure
deficit for microclimate evaluation and control in greenhouse cultivation of
tomato* (2018), [USDA ARS PDF](https://www.ars.usda.gov/ARSUserFiles/57795/Shamshiri2018%20-%20review%20optimum%20microclimate%20greenhouse.pdf),
[Frontiers — DLI and CO₂ effects on tomato](https://www.frontiersin.org/journals/plant-science/articles/10.3389/fpls.2021.615853/full),
[DutchGreenhouses — CO₂ enrichment](https://dutchgreenhouses.com/climate/co2-enrichment).

---

## Lighting

| Parameter | KasFlex | Source says | Status |
|---|---|---|---|
| `lamp_ppfd_umol_m2_s` | 185.0 | Overhead supplemental lighting typically **200–250 µmol·m⁻²·s⁻¹**; a 600 W HPS installation is reported delivering **175 µmol·m⁻²·s⁻¹** over a 16 h photoperiod | ✅ Within the reported spread, at the lower end |
| `lamp_power_w_m2` | 110.0 | Not directly stated in the sources found. Consistent with the 600 W HPS / 175 µmol figure at conventional fixture spacing, but that is an inference, not a citation | ⚠️ Inferred, not sourced |

Sources: [Agronomy — LEDs as supplementary lighting for tomato at different latitudes](https://doi.org/10.3390/agronomy11050835),
[Frontiers — supplemental LED meta-analysis for truss tomato](https://www.frontiersin.org/journals/plant-science/articles/10.3389/fpls.2021.596927/full),
[Plants — LED and HPS supplementary light](https://doi.org/10.3390/plants10040810).

---

## Photovoltaics

| Parameter | KasFlex | Source says | Status |
|---|---|---|---|
| `performance_ratio` | 0.85 | 0.75–0.85 is the conventional design range for a well-ventilated array | ⚠️ At the optimistic end; widely used but no primary citation obtained here |
| `peak_kw` | 500.0 | — | ❌ Unsourced. A scenario choice, not a measurement |

---

## Grid connection

| Parameter | KasFlex | Source says | Status |
|---|---|---|---|
| `import_limit_kw` | 6000.0 | — | ❌ **Unsourced.** Chosen so the connection can carry the full lamp field (5 ha × 110 W/m² = 5,500 kW) plus base load, which is a modelling decision, not a surveyed contract |
| `export_limit_kw` | 4000.0 | — | ❌ Unsourced |
| `base_load_kw` | 150.0 | — | ❌ Unsourced |

Real connection sizes depend on the individual contract with the DSO and on whether
a non-firm (ATO) agreement applies. Netbeheer Nederland publishes regional
congestion status but not per-connection capacity:
[capaciteitskaart.netbeheernederland.nl](https://capaciteitskaart.netbeheernederland.nl/).

---

## Summary of discrepancies

Six values where KasFlex and the literature disagree, in rough order of how much
they would move a result:

1. **Heat buffer ≈5× too small** (8 MWh vs ≈44 MWh for 5 ha). Understates
   load-shifting capacity, and therefore understates the value of flexibility —
   which is the thing the project is trying to measure.
2. **Battery round-trip 90% is a cell-level figure** where a system-level one
   (≈72–85%) belongs. Flatters every arbitrage result.
3. **CHP electrical efficiency 40%** is the value for a unit twice the modelled
   size; ≈37.5% fits 1.5 MW.
4. **Crop maximum 34 °C** exceeds the 32 °C the literature treats as the tolerable
   limit, so the checker permits conditions that damage fruit set.
5. **CHP heat-to-power 1.2** against ≈1.1 for the cited unit.
6. **Supplemental DLI target 10 mol·m⁻²·d⁻¹** is only coherent for a partially lit
   crop; it should be stated as such wherever results are reported.

Fifteen further parameters are unsourced placeholders. Most are modelling
conventions with little leverage on results (initial states, ramp rates set to
full capacity), but the **grid connection limits** and the **buffer standing loss**
do affect outcomes and deserve real sources.

---

## How to extend this

When you change a default, add or update its row here in the same commit. A number
that changes without its justification changing is how a model quietly stops
meaning what its documentation says it means.

Preferred source order: a peer-reviewed paper, then a government or agency
technical catalogue (the EPA catalogue above is a good example), then a
manufacturer datasheet, then a trade publication. A vendor marketing page is a
last resort and should be marked ⚠️.
