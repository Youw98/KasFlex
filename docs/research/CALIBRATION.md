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
   `cLeakage` ∈ {0.5, 1, 2, 3, 5} × 1e-5, `tauRfNir` ∈ {0.45, 0.57, 0.7, 0.85},
   `kThScr` ∈ {1.25, 2.5, 5, 10, 20} × 1e-4, `tauThScrFir` ∈ {0.05, 0.15, 0.3, 0.5}.
4. **Search:** a coordinate search, two passes, starting from the calibration
   published earlier on 2 October: each parameter in turn takes its best value with
   the others held. 43 distinct configurations were run.
5. **Score:** heat MAE / 50 kWh + CO₂ MAE / 3 kg + hourly temperature MAE / 2 K on
   the fit days. Temperature is in the score so that a fit cannot buy lower heat with
   a greenhouse that runs too warm, which is what the previous fit did.
6. **Test:** gl-gym defaults, the lamp fix alone, the earlier calibration and the
   new one, on the AICU test days and on every Reference day.

`epsRfFir` (roof FIR emissivity) was considered and left out: in gl-gym 0.3.2 the
parameter is defined but no model equation reads it.

## Two replay errors found first

Looking hour by hour at a May day showed two errors in how a day is replayed, not in
GreenLight's physics. Both are fixed, and the fit below was run after them.

- **The soil started cold every day.** Each replayed day is a new GreenLight run.
  gl-gym starts the top soil layer at 16.5 °C and the deeper layers colder still, so
  a May day spent much of its heat warming the ground: simulating the five days
  before each May day first brought May's mean heat down from 61 to 38 kWh. The replay now starts
  the floor at the mean measured air temperature of the seven days before (only
  earlier days, never the replayed day itself; `floor_temperature` in
  `validation_agc2.py`) and the five soil layers on a straight line from there down
  to gl-gym's outdoor soil temperature, which is the steady state of those layers.
  An earlier note said a warm start changed heat by only 3 kWh; that test most
  likely warmed the air, pipes and floor but left the soil layers at their defaults.
- **Idle pipes were counted as heating.** The AGC2 pipe sensors read exactly 0 while
  a circuit is off (of about 47,700 readings, 27,652 are 0 and only 128 lie between 0
  and air temperature + 3 K), so `Heat_cons` only counts heat from running circuits.
  GreenLight's pipes warm with the greenhouse by day and release that heat in the
  evening with the boiler off, and the worker counted it: about 10 W/m² for several
  hours on a sunny spring evening. The worker now counts pipe heat only while the
  boiler valve is open (`CIRCUIT_ON` in `workers/greenlight/worker.py`).

## Result

Best on the fit days: `aCov = 216.6`, `aRoof = 17.4`, `cLeakage = 2e-5`,
`tauRfNir = 0.85`, `kThScr = 1e-3`, `tauThScrFir = 0.5`. With the replay fixed, the
cover and screen no longer need to be implausibly tight: `aCov` is gl-gym's own value
and the screen is leakier than gl-gym's default rather than four times tighter.
`aCov`, `tauRfNir` and `tauThScrFir` sit at the edge of the values tried, and the top
of the search is flat (the next four configurations score within 1.2%), so read them
as a fit, not as measured properties.

Held-out AICU days (80), all with the corrected replay:

| Configuration | Heat MAE | Heat sim ÷ meas | CO₂ MAE | Temp MAE | Midday temp bias |
|---|---:|---:|---:|---:|---:|
| gl-gym defaults | 58.4 kWh | 2.56 | 3.62 kg | 1.35 K | −1.1 K |
| lamp cooling off only | 14.1 kWh | 1.10 | 3.65 kg | 1.20 K | −0.1 K |
| earlier calibration | 16.7 kWh | 0.65 | 1.36 kg | 1.98 K | +2.5 K |
| calibrated | 13.7 kWh | 1.09 | 1.23 kg | 1.42 K | +1.3 K |

Reference, all 160 days, not fitted:

| Configuration | Heat MAE | Heat sim ÷ meas | CO₂ MAE | Temp MAE | Midday temp bias |
|---|---:|---:|---:|---:|---:|
| gl-gym defaults | 53.4 kWh | 1.71 | 4.41 kg | 1.68 K | −1.7 K |
| lamp cooling off only | 24.1 kWh | 0.95 | 4.43 kg | 1.13 K | −0.5 K |
| earlier calibration | 34.8 kWh | 0.58 | 1.89 kg | 1.28 K | +1.6 K |
| calibrated | 27.0 kWh | 0.80 | 1.89 kg | 1.02 K | +0.9 K |

Before the replay fixes, the published calibration scored 21.7 kWh heat MAE and
1.55 K on the AICU test days and 24.2 kWh and 1.12 K on Reference. So heat on the
held-out AICU days improved by a third and temperature slightly on both
compartments, but Reference heat got a little worse (below).

Worth knowing for whoever refits: with the replay fixed, switching off lamp cooling
alone does as well as the fit on heat and temperature. What the fitted parameters
add is mainly CO₂, presumably because vent and leakage area set how much dosed CO₂
escapes.

Fit-day errors (heat 12.1 kWh, temp 1.44 K) are close to the test-day errors, so it
is not overfitting.

## What it does not fix

Mean pipe heat per held-out AICU day:

| Month | Measured | Before the fixes | Now |
|---|---:|---:|---:|
| 2019-12 | 44.9 kWh | 43.5 kWh | 33.0 kWh |
| 2020-01 | 47.3 kWh | 55.1 kWh | 48.0 kWh |
| 2020-02 | 55.3 kWh | 60.1 kWh | 54.3 kWh |
| 2020-03 | 46.2 kWh | 60.9 kWh | 49.4 kWh |
| 2020-04 | 16.7 kWh | 40.8 kWh | 19.4 kWh |
| 2020-05 | 14.3 kWh | 57.4 kWh | 35.2 kWh |

- **May is still about 2.5 times too high.** Averaged over late-spring nights, the
  measured greenhouse stays about 0.8 K above its heating setpoint with the pipes
  mostly off; the model drifts down to the setpoint and heats. The model also runs
  about 1.3 K warm at midday on the held-out days. Thicker floor mass (0.1 m instead
  of 0.02 m) took about 5 kWh more off May in a quick test but is not in the fit.
  Likely candidates are heat stored in the crop and substrate, which GreenLight
  models thinly, and the night-time loss through the closed screens.
- **Reference January is about 45% low** (58 against 104 kWh/day). Reference's grower
  used about twice AICU's heat in January at similar indoor temperatures; one set of
  construction parameters cannot follow both.

None of this changes the status: **not validated for operational use**.

## Reproduce

```bash
kasflex prepare-agc2 --source <extracted> --cache-dir data/cache --all-days --compartment AICU
kasflex prepare-agc2 --source <extracted> --cache-dir data/cache-reference --all-days \
  --compartment Reference
./.venv-greenlight/bin/python workers/greenlight/calibrate_agc2.py \
  --cache-dir data/cache --confirm-cache-dir data/cache-reference \
  --out results/calibration-agc2.json
```
