# GreenLight calibration for AGC2 compartments

This page records how the GreenLight construction parameters in
`AGC2_CALIBRATION` (`src/kasflex/validation_agc2.py`) were chosen, and how well they
do on days they were not fitted on. The full record, including every grid point and
every held-out day, is `results/calibration-agc2.json`.

## Data

- **Dataset:** Autonomous Greenhouse Challenge, Second Edition (2019), CC0,
  DOI `10.4121/uuid:88d22c60-21b3-4ea8-90db-20249a5be2a7`.
- **Source:** the official 4TU archive, `AutonomousGreenhouseChallenge_edition2.7z`.
  Its MD5 matched 4TU's published `2a0c7f3332881caef54ca8f4dc60c9a3` on
  2 October 2026, and the manifest records `archive_checksum_verified: true`. (An
  earlier calibration used a public GitHub copy of AICU only, because 4TU could not
  be reached then; it is superseded.)
- **Fit and held-out test:** AICU, 158 complete days, 16 December 2019 to 29 May 2020.
- **Confirmation:** Reference (the grower-operated compartment), all 160 complete
  days, never used for fitting. All six compartments are the same 96 m² glasshouse
  with the same lamps, screens and weather station.

## What is compared

| Quantity | Measured (AGC2) | Simulated |
|---|---|---|
| Heat | `Heat_cons`, defined in the ReadMe as `(t_rail − t_air) × 2.1 + (t_grow − t_air) × 0.62` W/m² | the same formula on GreenLight's pipe and air temperatures |
| CO₂ | `CO2_cons` | CO₂ dosed by the replayed controller |
| Electricity | `ElecHigh + ElecLow`, computed from HPS state and LED channel intensities | lamp power × replayed lamp fraction |
| Indoor temperature | hourly mean of `Tair` | GreenLight's air temperature, hourly |

Measured setpoints and actuator positions (heating and CO₂ setpoints, lamps, both
screens, vents) drive the model at 15-minute resolution. Measured heat, CO₂ and
indoor temperature are never fed back as controls; the replay file keeps indoor
temperature under `measured_indoor`, apart from the controls.

## Method

1. **Fixed on physical grounds, not fitted:** `etaLampCool = 0`. gl-gym's default
   (0.63) models water-cooled LEDs that remove 63% of lamp power from the greenhouse.
   AGC2 lit with 81 W/m² HPS and uncooled LEDs.
2. **Split:** days in even ISO weeks fit (78 days), days in odd ISO weeks test
   (80 days). Whole weeks, so a test day is never the day after a fit day with the
   same weather.
3. **Parameters and values tried** (`CANDIDATES` in the harness): `aCov` ∈ {140,
   156, 180, 216.6} (per 144 m² model floor), `aRoof` ∈ {7.2, 12, 17.4, 26, 52.2},
   `cLeakage` ∈ {0.5, 1, 2, 3} × 1e-5, `tauRfNir` ∈ {0.45, 0.57, 0.7, 0.85},
   `kThScr` ∈ {1.25, 2.5, 5, 10, 20} × 1e-4, `tauThScrFir` ∈ {0.05, 0.15, 0.3, 0.5}.
4. **Search:** a coordinate search, two passes, starting from the previous
   calibration with gl-gym defaults for the new parameters: each parameter in turn
   takes its best value with the others held. 38 distinct configurations were run.
5. **Score:** heat MAE / 50 kWh + CO₂ MAE / 3 kg + hourly temperature MAE / 2 K on
   the fit days. Temperature is in the score so that a fit cannot buy lower heat with
   a greenhouse that runs too warm, which is what the previous fit did.
6. **Test:** gl-gym defaults, the lamp fix alone, the previous calibration and the
   new one, on the AICU test days and on every Reference day.

`epsRfFir` (roof FIR emissivity) was considered and left out: in gl-gym 0.3.2 the
parameter is defined but no model equation reads it.

## Result

Best on the fit days: `aCov = 180`, `aRoof = 17.4`, `cLeakage = 2e-5`,
`tauRfNir = 0.85`, `kThScr = 1.25e-4`, `tauThScrFir = 0.05`. The top of the search
is flat (the next four configurations score within 1%), and three values sit at the
edge of the range tried. Read them as a fit, not as measured properties of the glass
and screen: they most likely compensate for something the model lacks (below).

Held-out AICU days (80):

| Configuration | Heat MAE | Heat sim ÷ meas | CO₂ MAE | Temp MAE | Midday temp bias |
|---|---:|---:|---:|---:|---:|
| gl-gym defaults | 93.1 kWh | 3.49 | 3.59 kg | 1.76 K | −1.5 K |
| lamp cooling off only | 39.1 kWh | 2.00 | 3.62 kg | 1.28 K | −0.7 K |
| previous (4 parameters) | 21.6 kWh | 1.39 | 1.31 kg | 1.89 K | +2.9 K |
| calibrated | 21.7 kWh | 1.43 | 1.36 kg | 1.55 K | +1.5 K |

Reference, all 160 days, not fitted:

| Configuration | Heat MAE | Heat sim ÷ meas | CO₂ MAE | Temp MAE | Midday temp bias |
|---|---:|---:|---:|---:|---:|
| gl-gym defaults | 86.4 kWh | 2.15 | 4.38 kg | 2.35 K | −2.2 K |
| previous (4 parameters) | 25.0 kWh | 0.94 | 1.84 kg | 1.42 K | +2.2 K |
| calibrated | 24.2 kWh | 1.06 | 1.88 kg | 1.12 K | +0.9 K |

So the new fit keeps heat and CO₂ where they were, halves the midday overheating,
and is better on the compartment it never saw. Fit-day errors (heat 19.7 kWh, temp
1.48 K) are close to the test-day errors, so it is not overfitting.

## What it does not fix

Spring heat is still about three to four times too high. Mean pipe heat per held-out
AICU day:

| Month | Measured | Previous | Calibrated |
|---|---:|---:|---:|
| 2019-12 | 44.9 kWh | 40.1 kWh | 43.5 kWh |
| 2020-01 | 47.3 kWh | 56.4 kWh | 55.1 kWh |
| 2020-02 | 55.3 kWh | 56.0 kWh | 60.1 kWh |
| 2020-03 | 46.2 kWh | 58.5 kWh | 60.9 kWh |
| 2020-04 | 16.7 kWh | 40.1 kWh | 40.8 kWh |
| 2020-05 | 14.3 kWh | 55.5 kWh | 57.4 kWh |

What was checked:

- **Not the daytime temperature any more.** With the new fit the simulated midday
  temperature is within about 1.5 K, yet the spring heat gap did not shrink. On a
  typical May day (12 May) the simulated air temperature follows the measured one
  within a few degrees all day; the extra heat is used at night and in the early
  morning, at the measured heating setpoint of 18 °C, with the screen closed.
- **Not the cold start.** Each day starts from gl-gym's default state for soil,
  lamps and screens (16.5 °C). Starting those at the measured air temperature
  changed heat by about 3 kWh per day (12 May: 76.8 → 73.5 kWh; measured 37.1).
- **Not the construction parameters in reach.** Three of the six sit at the edge of
  their range and the search is flat at the top.

The remaining gap is therefore most likely structural: how the replayed controller
turns the heating setpoint into pipe temperature at night, or the night-time heat
loss through the closed screen, rather than a value to fit. The next step is to
compare simulated and measured pipe temperature (`t_rail`, `t_grow`) hour by hour on
spring nights. None of this changes the status: **not validated for operational
use**.

## Reproduce

```bash
kasflex prepare-agc2 --source <extracted> --cache-dir data/cache --all-days --compartment AICU
kasflex prepare-agc2 --source <extracted> --cache-dir data/cache-reference --all-days \
  --compartment Reference
./.venv-greenlight/bin/python workers/greenlight/calibrate_agc2.py \
  --cache-dir data/cache --confirm-cache-dir data/cache-reference \
  --out results/calibration-agc2.json
```
