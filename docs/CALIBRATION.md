# GreenLight calibration for AGC2 compartments

This page records how the four GreenLight construction parameters in
`AGC2_CALIBRATION` (`src/kasflex/validation_agc2.py`) were chosen, and how well they
do on days they were not fitted on. The full record, including every grid point and
every held-out day, is `results/calibration-agc2.json`.

## Data

- **Dataset:** Autonomous Greenhouse Challenge, Second Edition (2019), CC0,
  DOI `10.4121/uuid:88d22c60-21b3-4ea8-90db-20249a5be2a7`.
- **Compartment:** AICU. All six compartments are the same 96 m² glasshouse with the
  same lamps, screens and weather station.
- **Source:** the official 4TU archive could not be reached from the environment
  that did this work. The files came from a public GitHub copy of the same CC0 data,
  [masoudgheisari92/greenhouse-temperature-prediction](https://github.com/masoudgheisari92/greenhouse-temperature-prediction)
  at commit `205db94`: `AICU/GreenhouseClimate.csv`, `AICU/Resources.csv`, `Weather.csv`.
  That copy has only AICU, not Reference. The archive checksum is therefore **not
  verified** (`archive_checksum_verified: false` in the manifest). Re-run on the
  official archive before relying on these numbers.
- **Days:** 158 complete days, 16 December 2019 to 29 May 2020.

## What is compared

| Quantity | Measured (AGC2) | Simulated |
|---|---|---|
| Heat | `Heat_cons`, defined in the ReadMe as `(t_rail − t_air) × 2.1 + (t_grow − t_air) × 0.62` W/m² | the same formula on GreenLight's pipe and air temperatures |
| CO₂ | `CO2_cons` | CO₂ dosed by the replayed controller |
| Electricity | `ElecHigh + ElecLow`, computed from HPS state and LED channel intensities | lamp power × replayed lamp fraction |

Measured setpoints and actuator positions (heating and CO₂ setpoints, lamps, both
screens, vents) drive the model at 15-minute resolution. Measured heat and CO₂
consumption are never fed back as controls.

## Method

1. **Fixed on physical grounds, not fitted:** `etaLampCool = 0`. gl-gym's default
   (0.63) models water-cooled LEDs that remove 63% of lamp power from the greenhouse.
   AGC2 lit with 81 W/m² HPS and uncooled LEDs.
2. **Split:** days in even ISO weeks fit (78 days), days in odd ISO weeks test
   (80 days). Whole weeks, so a test day is never the day after a fit day with the
   same weather.
3. **Grid:** `aCov` ∈ {156, 180, 216.6}, `aRoof` ∈ {7.2, 17.4, 52.2},
   `cLeakage` ∈ {1e-5, 3e-5, 1e-4}. The ranges run from roof glass only to gl-gym's
   free-standing house (`aCov`, per 144 m² model floor), from 5% to gl-gym's 36% of
   floor area (`aRoof`), and a factor of three either side of the default leakage.
4. **Score:** heat MAE / 50 kWh + CO₂ MAE / 3 kg on the fit days, which weighs a
   typical daily heat error and CO₂ error equally. Lowest score wins.
5. **Test:** the winner, the defaults and the lamp fix alone are run on the test
   days.

## Result

Best on the fit days: `aCov = 156`, `aRoof = 17.4`, `cLeakage = 1e-5`. The top of
the grid is flat (the next four candidates score within 10%), so these values
should not be read as precise.

Held-out test days (80):

| Configuration | Heat MAE | Heat sim ÷ meas | CO₂ MAE | CO₂ sim ÷ meas | Electricity MAE |
|---|---:|---:|---:|---:|---:|
| gl-gym defaults | 93.1 kWh | 3.49 | 3.59 kg | 1.57 | 6.7 kWh |
| lamp cooling off only | 39.1 kWh | 2.00 | 3.62 kg | 1.57 | 6.7 kWh |
| calibrated | 21.6 kWh | 1.39 | 1.31 kg | 1.00 | 6.7 kWh |

Fit-day errors for the calibrated set (heat 18.4 kWh, CO₂ 0.80 kg) are close to the
test-day errors, so the grid is not overfitting.

## What it does not fix

Heat is close in winter and wrong in spring. Mean pipe heat per held-out day:

| Month | Measured | Simulated |
|---|---:|---:|
| 2019-12 | 44.9 kWh | 40.1 kWh |
| 2020-01 | 47.3 kWh | 56.4 kWh |
| 2020-02 | 55.3 kWh | 56.0 kWh |
| 2020-03 | 46.2 kWh | 58.5 kWh |
| 2020-04 | 16.7 kWh | 40.1 kWh |
| 2020-05 | 14.3 kWh | 55.5 kWh |

On sunny spring days the model runs about 10 °C too warm at midday with the
measured vent opening, then heats more than the real compartment at night. A smaller
vent area helps winter heat and hurts spring daytime temperature. The next step is
to fit on indoor temperature as well, and to free the screen and cover radiation
parameters (`kThScr`, `tauThScrFir`, `epsRfFir`). None of that changes the status:
**not validated for operational use**.

## Reproduce

```bash
kasflex prepare-agc2 --source <extracted> --all-days --compartment AICU
./.venv-greenlight/bin/python workers/greenlight/calibrate_agc2.py \
  --cache-dir data/cache --out results/calibration-agc2.json
```
