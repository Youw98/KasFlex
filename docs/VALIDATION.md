# Validation against measured data (stage 1)

> **Status: calibrated, tested on held-out days and confirmed on a second
> compartment; still not acceptable for operational use.** After calibration,
> GreenLight's heat is close from December to April, but still about 2.5 times too
> high in May. CO₂, lamp electricity and indoor temperature are close. KasFlex remains research software and every plan remains
> **not validated for operational use**.

KasFlex refuses to create a validation result unless a real greenhouse simulator
replay ran. A missing replay, missing GreenLight worker, malformed file, or non-finite
number is a hard failure; it does not become a table full of NaN values.

## Validation reference

The reference is the **Autonomous Greenhouse Challenge, Second Edition (2019)**,
DOI `10.4121/uuid:88d22c60-21b3-4ea8-90db-20249a5be2a7`, CC0.

All six compartments are the same 96 m² Bleiswijk glasshouse with the same lamps,
screens and weather station; only who ran them differs. The data come from the
official 4TU archive (`AutonomousGreenhouseChallenge_edition2.7z`, MD5
`2a0c7f3332881caef54ca8f4dc60c9a3` as published by 4TU, checksum verified on
2 October 2026). The calibration is fitted on the **AICU** compartment and confirmed
on the grower-operated **Reference** compartment; the table below is AICU's held-out
days. Do not mix any compartment with the 5 ha commercial demonstration scenario.

## Four things earlier runs got wrong

The first published run (twelve Reference days, September 2026) reported heat 389%,
CO₂ 78% and electricity 11% mean absolute relative error. Two causes were
measurement mapping, not greenhouse physics, and are now fixed. Two more were
found on 2 October 2026 while looking for the spring heat error:

1. **Heat was compared with the wrong quantity.** AGC2 does not meter heat. The
   ReadMe defines `Heat_cons` as pipe heat release,
   `(t_rail − t_air) × 2.1 + (t_grow − t_air) × 0.62` W/m². The replay compared that
   with GreenLight's *boiler input*. The worker now applies the same formula to the
   simulated pipe temperatures, and boiler input stays a diagnostic.
2. **Every LED was replayed at full power.** The LEDs are dimmable per channel
   (`int_blue/red/farred/white_vip`) and only run while the HPS is on. The replay
   used the HPS on/off state for all 142.5 W/m². It now uses 81 W/m² × HPS state plus
   each LED channel at its recorded intensity, which is how the dataset computes
   electricity.
3. **The soil started cold every day.** Each replayed day is a fresh GreenLight run,
   and gl-gym starts the top soil at 16.5 °C and the deep layers colder. In spring
   the model spent a large part of the day warming the ground. The replay now starts
   the floor at the mean measured air temperature of the previous seven days (never
   the replayed day's own) and the soil on a steady profile below it.
4. **Idle pipes were counted as heating.** The AGC2 pipe sensors read 0 while a
   circuit is off, so `Heat_cons` only counts running circuits. GreenLight's pipes
   warm up with the greenhouse by day and give that heat back in the evening, and the
   worker counted it. It now counts pipe heat only while the boiler valve is open.

## Calibration

GreenLight's defaults describe a different greenhouse. Seven construction
parameters were set for an AGC2 compartment, fitted on even ISO weeks of AICU,
tested on odd weeks and confirmed on Reference. The score weighs daily heat, daily
CO₂ and hourly indoor temperature. The details are in [CALIBRATION.md](CALIBRATION.md).

| Parameter | gl-gym default | AGC2 | Why |
|---|---:|---:|---|
| `etaLampCool` | 0.63 | 0 | gl-gym assumes water-cooled LEDs that carry 63% of lamp power away. AGC2 has HPS plus uncooled LEDs. **Physical, not fitted.** |
| `aCov` (per 144 m² floor) | 216.6 m² | 216.6 m² | Fitted; the largest value tried. |
| `aRoof` (per 144 m² floor) | 52.2 m² | 17.4 m² | Fitted. The default is 36% of floor area. |
| `cLeakage` | 3e-5 | 2e-5 | Fitted. |
| `tauRfNir` | 0.57 | 0.85 | Fitted, at the edge of the values tried. |
| `kThScr` | 5e-4 | 1e-3 | Fitted. |
| `tauThScrFir` | 0.15 | 0.5 | Fitted, at the edge of the values tried. |

Held-out result on the 80 AICU test days (the table below). "Before" is the
calibration published earlier on 2 October, with the cold soil and the idle-pipe
heat; the other two columns use the corrected replay.

| Quantity | gl-gym defaults | Before | Now | Simulated ÷ measured |
|---|---:|---:|---:|---:|
| Heat, MAE per day | 58.4 kWh | 21.7 kWh | 13.7 kWh | 1.09 |
| CO₂, MAE per day | 3.62 kg | 1.36 kg | 1.23 kg | 1.04 |
| Lamp electricity, MAE per day | 6.7 kWh | 6.7 kWh | 6.7 kWh | 1.05 |
| Indoor temperature, MAE per hour | 1.35 K | 1.55 K | 1.42 K | – |
| Indoor temperature, midday bias (11–15 h) | −1.1 K | +1.5 K | +1.3 K | – |

Heat per month on the same days, kWh per day:

| | Dec | Jan | Feb | Mar | Apr | May |
|---|---:|---:|---:|---:|---:|---:|
| Measured | 45 | 47 | 55 | 46 | 17 | 14 |
| Before | 43 | 55 | 60 | 61 | 41 | 57 |
| Now | 33 | 48 | 54 | 49 | 19 | 35 |

All 160 Reference days, never used for fitting:

| Quantity | gl-gym defaults | Before | Now |
|---|---:|---:|---:|
| Heat, MAE per day | 53.4 kWh | 24.2 kWh | 27.0 kWh |
| CO₂, MAE per day | 4.41 kg | 1.88 kg | 1.89 kg |
| Indoor temperature, MAE per hour | 1.68 K | 1.12 K | 1.02 K |

On Reference, heat is worse than before: May is lower (60 against 78 kWh, measured
36) but January is further under (58, was 68, against a measured 104). Reference's grower
heated much harder in January than AICU did, at similar temperatures, which no single
set of construction parameters reproduces.

The heat MARE (about 60%) is dominated by spring days on which almost no heat was
used: a 15 kWh error on a 5 kWh day is 300%. MAE and the total ratio are the more
informative numbers for heat.

## Canonical local layout

```text
data/cache/agc2/
├── MANIFEST.json
├── measured/
│   └── YYYY-MM-DD.csv
├── replay/
│   └── YYYY-MM-DD.json
└── weather/BleiswijkAGC2/YYYY.csv
```

The measured CSV contains daily totals: `heating_kwh,electricity_kwh,co2_kg`.
The replay JSON holds the plan, 24 hourly conditions, the GreenLight weather
scenario, the replayed setpoints and actuator positions, and
`greenlight_calibration`. Only controls and external conditions derived from the
same measured AGC day belong in a replay. If the source mapping is uncertain, stop
and document it instead of guessing.

## Run the comparison

Extract the CC0 archive under `data/raw/agc2/extracted` (one folder per compartment
plus `Weather/Weather.csv`), create the separate GreenLight environment, then:

```bash
kasflex prepare-agc2 --sample-days 12                 # Reference, 12 heat quantiles
kasflex prepare-agc2 --all-days --compartment AICU    # any compartment, every day
kasflex validate --cache-dir data/cache --greenhouse greenlight \
  --result-json results/validation-agc2.json --write-doc docs/VALIDATION.md
```

To redo the calibration (about twenty minutes on four cores), prepare AICU and
Reference into two caches, then:

```bash
./.venv-greenlight/bin/python workers/greenlight/calibrate_agc2.py \
  --cache-dir data/cache --confirm-cache-dir data/cache-reference \
  --out results/calibration-agc2.json
```

For development tests only, `--greenhouse surrogate` exercises the same replay and
report pipeline. It is not a substitute for the GreenLight comparison.

The committed `results/validation-agc2.json` proves that a measured comparison ran
and turns the grower demo's badge from **pending** to **measured validation**. It
does not claim the model passed a calibration threshold.

## Deviation table

<!-- kasflex:validation:start -->
Generated 2026-10-02T12:35:46+00:00 from Autonomous Greenhouse Challenge, Second Edition — AICU compartment at `data/cache/agc2`.

Days compared: 80

## Aggregate error

| Quantity | Days | MAE | Mean absolute relative error |
|---|---:|---:|---:|
| co2_kg | 80 | 1.23 kg | 26.6% |
| electricity_kwh | 80 | 6.69 kWh | 8.5% |
| heating_kwh | 80 | 13.71 kWh | 59.0% |

## Per-day deviation

| Day | Quantity | Measured | Simulated | Error | Rel. error |
|---|---|---:|---:|---:|---:|
| 2019-12-16 | heating_kwh | 76.15 kWh | 12.69 kWh | -63.46 kWh | -83.3% |
| 2019-12-16 | electricity_kwh | 81.10 kWh | 207.85 kWh | +126.76 kWh | +156.3% |
| 2019-12-16 | co2_kg | 0.53 kg | 1.90 kg | +1.37 kg | +261.0% |
| 2019-12-17 | heating_kwh | 30.21 kWh | 6.50 kWh | -23.70 kWh | -78.5% |
| 2019-12-17 | electricity_kwh | 50.18 kWh | 110.62 kWh | +60.44 kWh | +120.5% |
| 2019-12-17 | co2_kg | 0.53 kg | 1.36 kg | +0.83 kg | +157.3% |
| 2019-12-18 | heating_kwh | 30.48 kWh | 30.90 kWh | +0.42 kWh | +1.4% |
| 2019-12-18 | electricity_kwh | 80.35 kWh | 187.53 kWh | +107.18 kWh | +133.4% |
| 2019-12-18 | co2_kg | 1.10 kg | 2.29 kg | +1.19 kg | +108.0% |
| 2019-12-19 | heating_kwh | 3.18 kWh | 1.30 kWh | -1.88 kWh | -59.1% |
| 2019-12-19 | electricity_kwh | 134.78 kWh | 146.19 kWh | +11.40 kWh | +8.5% |
| 2019-12-19 | co2_kg | 1.90 kg | 3.22 kg | +1.32 kg | +69.4% |
| 2019-12-20 | heating_kwh | 15.27 kWh | 10.77 kWh | -4.50 kWh | -29.5% |
| 2019-12-20 | electricity_kwh | 180.23 kWh | 185.99 kWh | +5.76 kWh | +3.2% |
| 2019-12-20 | co2_kg | 2.98 kg | 3.92 kg | +0.94 kg | +31.4% |
| 2019-12-21 | heating_kwh | 65.87 kWh | 67.53 kWh | +1.66 kWh | +2.5% |
| 2019-12-21 | electricity_kwh | 166.06 kWh | 168.83 kWh | +2.77 kWh | +1.7% |
| 2019-12-21 | co2_kg | 1.51 kg | 2.27 kg | +0.76 kg | +50.2% |
| 2019-12-22 | heating_kwh | 48.85 kWh | 45.10 kWh | -3.75 kWh | -7.7% |
| 2019-12-22 | electricity_kwh | 159.08 kWh | 161.83 kWh | +2.75 kWh | +1.7% |
| 2019-12-22 | co2_kg | 2.16 kg | 1.99 kg | -0.17 kg | -7.7% |
| 2019-12-30 | heating_kwh | 70.90 kWh | 77.83 kWh | +6.93 kWh | +9.8% |
| 2019-12-30 | electricity_kwh | 192.19 kWh | 229.17 kWh | +36.98 kWh | +19.2% |
| 2019-12-30 | co2_kg | 4.49 kg | 5.23 kg | +0.74 kg | +16.6% |
| 2019-12-31 | heating_kwh | 62.98 kWh | 44.37 kWh | -18.61 kWh | -29.6% |
| 2019-12-31 | electricity_kwh | 214.76 kWh | 217.52 kWh | +2.76 kWh | +1.3% |
| 2019-12-31 | co2_kg | 3.68 kg | 4.08 kg | +0.40 kg | +10.9% |
| 2020-01-01 | heating_kwh | 85.42 kWh | 55.83 kWh | -29.60 kWh | -34.6% |
| 2020-01-01 | electricity_kwh | 228.80 kWh | 230.31 kWh | +1.51 kWh | +0.7% |
| 2020-01-01 | co2_kg | 3.81 kg | 3.13 kg | -0.68 kg | -17.8% |
| 2020-01-02 | heating_kwh | 94.88 kWh | 60.95 kWh | -33.93 kWh | -35.8% |
| 2020-01-02 | electricity_kwh | 228.80 kWh | 230.31 kWh | +1.51 kWh | +0.7% |
| 2020-01-02 | co2_kg | 3.87 kg | 3.15 kg | -0.72 kg | -18.6% |
| 2020-01-03 | heating_kwh | 76.75 kWh | 55.83 kWh | -20.92 kWh | -27.3% |
| 2020-01-03 | electricity_kwh | 226.51 kWh | 228.03 kWh | +1.52 kWh | +0.7% |
| 2020-01-03 | co2_kg | 5.09 kg | 3.99 kg | -1.10 kg | -21.6% |
| 2020-01-04 | heating_kwh | 55.51 kWh | 65.53 kWh | +10.02 kWh | +18.0% |
| 2020-01-04 | electricity_kwh | 226.51 kWh | 230.31 kWh | +3.80 kWh | +1.7% |
| 2020-01-04 | co2_kg | 5.89 kg | 4.70 kg | -1.19 kg | -20.3% |
| 2020-01-05 | heating_kwh | 52.06 kWh | 46.34 kWh | -5.73 kWh | -11.0% |
| 2020-01-05 | electricity_kwh | 227.66 kWh | 230.31 kWh | +2.66 kWh | +1.2% |
| 2020-01-05 | co2_kg | 4.95 kg | 4.49 kg | -0.46 kg | -9.3% |
| 2020-01-13 | heating_kwh | 40.89 kWh | 43.57 kWh | +2.68 kWh | +6.6% |
| 2020-01-13 | electricity_kwh | 214.36 kWh | 220.66 kWh | +6.30 kWh | +2.9% |
| 2020-01-13 | co2_kg | 5.27 kg | 4.91 kg | -0.36 kg | -6.8% |
| 2020-01-14 | heating_kwh | 34.33 kWh | 35.73 kWh | +1.40 kWh | +4.1% |
| 2020-01-14 | electricity_kwh | 223.96 kWh | 225.68 kWh | +1.72 kWh | +0.8% |
| 2020-01-14 | co2_kg | 7.49 kg | 8.66 kg | +1.16 kg | +15.5% |
| 2020-01-15 | heating_kwh | 28.10 kWh | 31.37 kWh | +3.26 kWh | +11.6% |
| 2020-01-15 | electricity_kwh | 223.96 kWh | 228.72 kWh | +4.76 kWh | +2.1% |
| 2020-01-15 | co2_kg | 6.99 kg | 7.87 kg | +0.88 kg | +12.7% |
| 2020-01-17 | heating_kwh | 31.29 kWh | 39.86 kWh | +8.57 kWh | +27.4% |
| 2020-01-17 | electricity_kwh | 215.60 kWh | 222.64 kWh | +7.04 kWh | +3.3% |
| 2020-01-17 | co2_kg | 6.70 kg | 7.43 kg | +0.73 kg | +10.9% |
| 2020-01-18 | heating_kwh | 64.93 kWh | 100.83 kWh | +35.90 kWh | +55.3% |
| 2020-01-18 | electricity_kwh | 131.66 kWh | 134.38 kWh | +2.72 kWh | +2.1% |
| 2020-01-18 | co2_kg | 3.72 kg | 4.03 kg | +0.31 kg | +8.4% |
| 2020-01-19 | heating_kwh | 40.24 kWh | 35.79 kWh | -4.45 kWh | -11.1% |
| 2020-01-19 | electricity_kwh | 226.72 kWh | 228.04 kWh | +1.32 kWh | +0.6% |
| 2020-01-19 | co2_kg | 5.61 kg | 5.10 kg | -0.50 kg | -9.0% |
| 2020-01-27 | heating_kwh | 23.87 kWh | 30.86 kWh | +6.98 kWh | +29.3% |
| 2020-01-27 | electricity_kwh | 195.98 kWh | 221.72 kWh | +25.74 kWh | +13.1% |
| 2020-01-27 | co2_kg | 5.97 kg | 4.56 kg | -1.41 kg | -23.6% |
| 2020-01-28 | heating_kwh | 48.46 kWh | 61.29 kWh | +12.83 kWh | +26.5% |
| 2020-01-28 | electricity_kwh | 234.04 kWh | 236.79 kWh | +2.75 kWh | +1.2% |
| 2020-01-28 | co2_kg | 5.65 kg | 4.99 kg | -0.66 kg | -11.7% |
| 2020-01-29 | heating_kwh | 32.13 kWh | 53.19 kWh | +21.06 kWh | +65.6% |
| 2020-01-29 | electricity_kwh | 234.04 kWh | 237.93 kWh | +3.89 kWh | +1.7% |
| 2020-01-29 | co2_kg | 6.60 kg | 6.25 kg | -0.34 kg | -5.2% |
| 2020-01-30 | heating_kwh | 22.40 kWh | 28.22 kWh | +5.82 kWh | +26.0% |
| 2020-01-30 | electricity_kwh | 236.14 kWh | 238.89 kWh | +2.74 kWh | +1.2% |
| 2020-01-30 | co2_kg | 6.79 kg | 5.06 kg | -1.72 kg | -25.4% |
| 2020-01-31 | heating_kwh | 24.94 kWh | 23.39 kWh | -1.56 kWh | -6.2% |
| 2020-01-31 | electricity_kwh | 234.82 kWh | 238.71 kWh | +3.89 kWh | +1.7% |
| 2020-01-31 | co2_kg | 7.69 kg | 5.48 kg | -2.21 kg | -28.7% |
| 2020-02-01 | heating_kwh | 9.70 kWh | 19.51 kWh | +9.82 kWh | +101.3% |
| 2020-02-01 | electricity_kwh | 249.39 kWh | 251.98 kWh | +2.58 kWh | +1.0% |
| 2020-02-01 | co2_kg | 8.67 kg | 6.66 kg | -2.01 kg | -23.2% |
| 2020-02-02 | heating_kwh | 31.69 kWh | 24.99 kWh | -6.70 kWh | -21.1% |
| 2020-02-02 | electricity_kwh | 241.38 kWh | 242.85 kWh | +1.47 kWh | +0.6% |
| 2020-02-02 | co2_kg | 6.14 kg | 4.56 kg | -1.59 kg | -25.8% |
| 2020-02-10 | heating_kwh | 30.66 kWh | 46.23 kWh | +15.57 kWh | +50.8% |
| 2020-02-10 | electricity_kwh | 244.82 kWh | 246.27 kWh | +1.46 kWh | +0.6% |
| 2020-02-10 | co2_kg | 7.71 kg | 6.86 kg | -0.84 kg | -10.9% |
| 2020-02-11 | heating_kwh | 58.92 kWh | 102.60 kWh | +43.68 kWh | +74.1% |
| 2020-02-11 | electricity_kwh | 243.67 kWh | 246.27 kWh | +2.60 kWh | +1.1% |
| 2020-02-11 | co2_kg | 7.98 kg | 7.17 kg | -0.81 kg | -10.2% |
| 2020-02-12 | heating_kwh | 49.34 kWh | 82.81 kWh | +33.46 kWh | +67.8% |
| 2020-02-12 | electricity_kwh | 243.67 kWh | 246.27 kWh | +2.60 kWh | +1.1% |
| 2020-02-12 | co2_kg | 7.24 kg | 6.46 kg | -0.79 kg | -10.9% |
| 2020-02-13 | heating_kwh | 55.04 kWh | 31.58 kWh | -23.46 kWh | -42.6% |
| 2020-02-13 | electricity_kwh | 244.82 kWh | 246.27 kWh | +1.46 kWh | +0.6% |
| 2020-02-13 | co2_kg | 5.30 kg | 4.08 kg | -1.22 kg | -22.9% |
| 2020-02-14 | heating_kwh | 19.31 kWh | 28.14 kWh | +8.82 kWh | +45.7% |
| 2020-02-14 | electricity_kwh | 243.67 kWh | 246.27 kWh | +2.60 kWh | +1.1% |
| 2020-02-14 | co2_kg | 6.10 kg | 5.41 kg | -0.69 kg | -11.3% |
| 2020-02-15 | heating_kwh | 8.06 kWh | 13.10 kWh | +5.04 kWh | +62.4% |
| 2020-02-15 | electricity_kwh | 243.67 kWh | 246.27 kWh | +2.60 kWh | +1.1% |
| 2020-02-15 | co2_kg | 7.26 kg | 5.00 kg | -2.26 kg | -31.1% |
| 2020-02-16 | heating_kwh | 16.87 kWh | 25.51 kWh | +8.64 kWh | +51.2% |
| 2020-02-16 | electricity_kwh | 244.82 kWh | 246.27 kWh | +1.46 kWh | +0.6% |
| 2020-02-16 | co2_kg | 10.82 kg | 6.02 kg | -4.80 kg | -44.3% |
| 2020-02-24 | heating_kwh | 91.66 kWh | 67.45 kWh | -24.21 kWh | -26.4% |
| 2020-02-24 | electricity_kwh | 196.53 kWh | 198.02 kWh | +1.49 kWh | +0.8% |
| 2020-02-24 | co2_kg | 4.11 kg | 3.63 kg | -0.47 kg | -11.5% |
| 2020-02-26 | heating_kwh | 119.60 kWh | 93.60 kWh | -26.00 kWh | -21.7% |
| 2020-02-26 | electricity_kwh | 196.91 kWh | 198.40 kWh | +1.49 kWh | +0.8% |
| 2020-02-26 | co2_kg | 5.01 kg | 4.53 kg | -0.48 kg | -9.6% |
| 2020-02-27 | heating_kwh | 129.05 kWh | 76.29 kWh | -52.76 kWh | -40.9% |
| 2020-02-27 | electricity_kwh | 196.91 kWh | 198.40 kWh | +1.49 kWh | +0.8% |
| 2020-02-27 | co2_kg | 3.42 kg | 3.28 kg | -0.14 kg | -4.1% |
| 2020-02-28 | heating_kwh | 98.78 kWh | 79.70 kWh | -19.09 kWh | -19.3% |
| 2020-02-28 | electricity_kwh | 195.00 kWh | 197.63 kWh | +2.63 kWh | +1.4% |
| 2020-02-28 | co2_kg | 4.34 kg | 4.46 kg | +0.12 kg | +2.8% |
| 2020-02-29 | heating_kwh | 55.77 kWh | 68.36 kWh | +12.59 kWh | +22.6% |
| 2020-02-29 | electricity_kwh | 194.04 kWh | 196.67 kWh | +2.63 kWh | +1.4% |
| 2020-02-29 | co2_kg | 6.06 kg | 5.59 kg | -0.47 kg | -7.8% |
| 2020-03-01 | heating_kwh | 43.58 kWh | 60.61 kWh | +17.02 kWh | +39.1% |
| 2020-03-01 | electricity_kwh | 196.20 kWh | 198.86 kWh | +2.66 kWh | +1.4% |
| 2020-03-01 | co2_kg | 6.28 kg | 5.66 kg | -0.61 kg | -9.8% |
| 2020-03-09 | heating_kwh | 37.49 kWh | 38.80 kWh | +1.31 kWh | +3.5% |
| 2020-03-09 | electricity_kwh | 223.08 kWh | 225.75 kWh | +2.67 kWh | +1.2% |
| 2020-03-09 | co2_kg | 6.59 kg | 6.44 kg | -0.16 kg | -2.4% |
| 2020-03-10 | heating_kwh | 47.50 kWh | 30.14 kWh | -17.36 kWh | -36.5% |
| 2020-03-10 | electricity_kwh | 223.08 kWh | 225.75 kWh | +2.67 kWh | +1.2% |
| 2020-03-10 | co2_kg | 6.53 kg | 4.77 kg | -1.76 kg | -27.0% |
| 2020-03-11 | heating_kwh | 17.79 kWh | 20.40 kWh | +2.61 kWh | +14.7% |
| 2020-03-11 | electricity_kwh | 171.60 kWh | 177.86 kWh | +6.26 kWh | +3.7% |
| 2020-03-11 | co2_kg | 7.50 kg | 7.30 kg | -0.21 kg | -2.8% |
| 2020-03-12 | heating_kwh | 38.58 kWh | 49.76 kWh | +11.18 kWh | +29.0% |
| 2020-03-12 | electricity_kwh | 156.73 kWh | 164.18 kWh | +7.46 kWh | +4.8% |
| 2020-03-12 | co2_kg | 8.29 kg | 8.58 kg | +0.29 kg | +3.5% |
| 2020-03-13 | heating_kwh | 53.88 kWh | 64.47 kWh | +10.59 kWh | +19.6% |
| 2020-03-13 | electricity_kwh | 163.59 kWh | 164.18 kWh | +0.59 kWh | +0.4% |
| 2020-03-13 | co2_kg | 5.89 kg | 5.35 kg | -0.54 kg | -9.2% |
| 2020-03-14 | heating_kwh | 34.98 kWh | 25.38 kWh | -9.60 kWh | -27.4% |
| 2020-03-14 | electricity_kwh | 178.46 kWh | 177.86 kWh | -0.60 kWh | -0.3% |
| 2020-03-14 | co2_kg | 6.00 kg | 5.48 kg | -0.51 kg | -8.6% |
| 2020-03-15 | heating_kwh | 30.80 kWh | 22.56 kWh | -8.24 kWh | -26.8% |
| 2020-03-15 | electricity_kwh | 223.08 kWh | 225.75 kWh | +2.67 kWh | +1.2% |
| 2020-03-15 | co2_kg | 6.25 kg | 5.37 kg | -0.88 kg | -14.1% |
| 2020-03-23 | heating_kwh | 70.78 kWh | 81.94 kWh | +11.16 kWh | +15.8% |
| 2020-03-23 | electricity_kwh | 106.39 kWh | 109.46 kWh | +3.06 kWh | +2.9% |
| 2020-03-23 | co2_kg | 7.20 kg | 8.21 kg | +1.02 kg | +14.1% |
| 2020-03-24 | heating_kwh | 57.19 kWh | 52.21 kWh | -4.98 kWh | -8.7% |
| 2020-03-24 | electricity_kwh | 107.54 kWh | 109.46 kWh | +1.92 kWh | +1.8% |
| 2020-03-24 | co2_kg | 7.17 kg | 8.11 kg | +0.94 kg | +13.1% |
| 2020-03-25 | heating_kwh | 55.22 kWh | 51.16 kWh | -4.06 kWh | -7.4% |
| 2020-03-25 | electricity_kwh | 107.54 kWh | 110.60 kWh | +3.06 kWh | +2.8% |
| 2020-03-25 | co2_kg | 6.55 kg | 8.23 kg | +1.68 kg | +25.6% |
| 2020-03-26 | heating_kwh | 71.02 kWh | 104.96 kWh | +33.94 kWh | +47.8% |
| 2020-03-26 | electricity_kwh | 0.00 kWh | 3.42 kWh | +3.42 kWh | n/a |
| 2020-03-26 | co2_kg | 4.49 kg | 6.34 kg | +1.85 kg | +41.1% |
| 2020-03-27 | heating_kwh | 37.74 kWh | 35.17 kWh | -2.58 kWh | -6.8% |
| 2020-03-27 | electricity_kwh | 108.68 kWh | 110.60 kWh | +1.92 kWh | +1.8% |
| 2020-03-27 | co2_kg | 6.63 kg | 7.98 kg | +1.35 kg | +20.3% |
| 2020-03-28 | heating_kwh | 49.74 kWh | 54.73 kWh | +4.98 kWh | +10.0% |
| 2020-03-28 | electricity_kwh | 72.20 kWh | 75.24 kWh | +3.04 kWh | +4.2% |
| 2020-03-28 | co2_kg | 6.83 kg | 8.00 kg | +1.17 kg | +17.1% |
| 2020-04-06 | heating_kwh | 14.37 kWh | 24.45 kWh | +10.09 kWh | +70.2% |
| 2020-04-06 | electricity_kwh | 66.12 kWh | 68.05 kWh | +1.93 kWh | +2.9% |
| 2020-04-06 | co2_kg | 8.20 kg | 8.99 kg | +0.78 kg | +9.6% |
| 2020-04-07 | heating_kwh | 14.20 kWh | 16.86 kWh | +2.66 kWh | +18.7% |
| 2020-04-07 | electricity_kwh | 78.65 kWh | 80.60 kWh | +1.95 kWh | +2.5% |
| 2020-04-07 | co2_kg | 9.72 kg | 10.93 kg | +1.21 kg | +12.5% |
| 2020-04-08 | heating_kwh | 7.43 kWh | 10.31 kWh | +2.88 kWh | +38.7% |
| 2020-04-08 | electricity_kwh | 79.55 kWh | 81.50 kWh | +1.95 kWh | +2.5% |
| 2020-04-08 | co2_kg | 7.63 kg | 12.57 kg | +4.93 kg | +64.6% |
| 2020-04-10 | heating_kwh | 17.66 kWh | 19.48 kWh | +1.83 kWh | +10.3% |
| 2020-04-10 | electricity_kwh | 79.55 kWh | 81.50 kWh | +1.95 kWh | +2.5% |
| 2020-04-10 | co2_kg | 9.37 kg | 9.26 kg | -0.11 kg | -1.2% |
| 2020-04-11 | heating_kwh | 14.00 kWh | 14.13 kWh | +0.13 kWh | +0.9% |
| 2020-04-11 | electricity_kwh | 79.55 kWh | 81.50 kWh | +1.95 kWh | +2.5% |
| 2020-04-11 | co2_kg | 10.02 kg | 10.43 kg | +0.40 kg | +4.0% |
| 2020-04-12 | heating_kwh | 10.96 kWh | 14.37 kWh | +3.41 kWh | +31.1% |
| 2020-04-12 | electricity_kwh | 79.55 kWh | 82.64 kWh | +3.09 kWh | +3.9% |
| 2020-04-12 | co2_kg | 8.70 kg | 9.20 kg | +0.50 kg | +5.8% |
| 2020-04-20 | heating_kwh | 24.49 kWh | 22.04 kWh | -2.44 kWh | -10.0% |
| 2020-04-20 | electricity_kwh | 78.65 kWh | 81.74 kWh | +3.09 kWh | +3.9% |
| 2020-04-20 | co2_kg | 12.09 kg | 10.94 kg | -1.15 kg | -9.5% |
| 2020-04-21 | heating_kwh | 13.46 kWh | 14.92 kWh | +1.46 kWh | +10.9% |
| 2020-04-21 | electricity_kwh | 78.65 kWh | 81.74 kWh | +3.09 kWh | +3.9% |
| 2020-04-21 | co2_kg | 12.74 kg | 11.29 kg | -1.45 kg | -11.4% |
| 2020-04-22 | heating_kwh | 10.54 kWh | 13.87 kWh | +3.33 kWh | +31.6% |
| 2020-04-22 | electricity_kwh | 79.42 kWh | 81.38 kWh | +1.95 kWh | +2.5% |
| 2020-04-22 | co2_kg | 12.65 kg | 12.50 kg | -0.15 kg | -1.1% |
| 2020-04-23 | heating_kwh | 9.73 kWh | 12.65 kWh | +2.92 kWh | +30.1% |
| 2020-04-23 | electricity_kwh | 68.70 kWh | 71.84 kWh | +3.13 kWh | +4.6% |
| 2020-04-23 | co2_kg | 10.46 kg | 12.65 kg | +2.18 kg | +20.9% |
| 2020-04-24 | heating_kwh | 15.58 kWh | 20.14 kWh | +4.57 kWh | +29.3% |
| 2020-04-24 | electricity_kwh | 58.76 kWh | 60.80 kWh | +2.04 kWh | +3.5% |
| 2020-04-24 | co2_kg | 10.03 kg | 8.44 kg | -1.59 kg | -15.9% |
| 2020-04-25 | heating_kwh | 35.49 kWh | 42.73 kWh | +7.25 kWh | +20.4% |
| 2020-04-25 | electricity_kwh | 58.76 kWh | 60.80 kWh | +2.04 kWh | +3.5% |
| 2020-04-25 | co2_kg | 3.64 kg | 4.64 kg | +1.00 kg | +27.6% |
| 2020-04-26 | heating_kwh | 28.60 kWh | 26.65 kWh | -1.95 kWh | -6.8% |
| 2020-04-26 | electricity_kwh | 53.34 kWh | 56.53 kWh | +3.20 kWh | +6.0% |
| 2020-04-26 | co2_kg | 5.55 kg | 7.10 kg | +1.55 kg | +28.0% |
| 2020-05-04 | heating_kwh | 5.25 kWh | 29.67 kWh | +24.42 kWh | +465.4% |
| 2020-05-04 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-04 | co2_kg | 4.16 kg | 6.36 kg | +2.19 kg | +52.7% |
| 2020-05-05 | heating_kwh | 27.15 kWh | 31.29 kWh | +4.14 kWh | +15.2% |
| 2020-05-05 | electricity_kwh | 46.10 kWh | 48.19 kWh | +2.09 kWh | +4.5% |
| 2020-05-05 | co2_kg | 10.28 kg | 9.54 kg | -0.74 kg | -7.2% |
| 2020-05-06 | heating_kwh | 23.42 kWh | 27.58 kWh | +4.16 kWh | +17.7% |
| 2020-05-06 | electricity_kwh | 47.91 kWh | 47.71 kWh | -0.20 kWh | -0.4% |
| 2020-05-06 | co2_kg | 9.48 kg | 10.28 kg | +0.80 kg | +8.4% |
| 2020-05-07 | heating_kwh | 26.82 kWh | 45.37 kWh | +18.55 kWh | +69.2% |
| 2020-05-07 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-07 | co2_kg | 5.49 kg | 9.79 kg | +4.30 kg | +78.4% |
| 2020-05-08 | heating_kwh | 16.18 kWh | 35.49 kWh | +19.30 kWh | +119.3% |
| 2020-05-08 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-08 | co2_kg | 5.26 kg | 9.79 kg | +4.53 kg | +86.0% |
| 2020-05-09 | heating_kwh | 11.33 kWh | 29.85 kWh | +18.52 kWh | +163.5% |
| 2020-05-09 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-09 | co2_kg | 8.16 kg | 10.91 kg | +2.76 kg | +33.8% |
| 2020-05-10 | heating_kwh | 25.26 kWh | 51.80 kWh | +26.54 kWh | +105.0% |
| 2020-05-10 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-10 | co2_kg | 4.60 kg | 4.86 kg | +0.27 kg | +5.8% |
| 2020-05-18 | heating_kwh | 9.90 kWh | 37.96 kWh | +28.05 kWh | +283.2% |
| 2020-05-18 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-18 | co2_kg | 7.92 kg | 9.82 kg | +1.90 kg | +24.0% |
| 2020-05-19 | heating_kwh | 7.16 kWh | 30.13 kWh | +22.97 kWh | +320.8% |
| 2020-05-19 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-19 | co2_kg | 6.45 kg | 9.67 kg | +3.22 kg | +50.0% |
| 2020-05-20 | heating_kwh | 6.26 kWh | 24.56 kWh | +18.30 kWh | +292.1% |
| 2020-05-20 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-20 | co2_kg | 5.51 kg | 10.16 kg | +4.65 kg | +84.5% |
| 2020-05-21 | heating_kwh | 4.47 kWh | 22.14 kWh | +17.67 kWh | +395.1% |
| 2020-05-21 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-21 | co2_kg | 5.93 kg | 9.24 kg | +3.31 kg | +55.9% |
| 2020-05-22 | heating_kwh | 0.00 kWh | 7.72 kWh | +7.72 kWh | n/a |
| 2020-05-22 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-22 | co2_kg | 1.76 kg | 1.70 kg | -0.07 kg | -3.8% |
| 2020-05-23 | heating_kwh | 9.89 kWh | 34.53 kWh | +24.65 kWh | +249.3% |
| 2020-05-23 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-23 | co2_kg | 2.65 kg | 2.83 kg | +0.18 kg | +6.7% |
| 2020-05-24 | heating_kwh | 26.76 kWh | 84.95 kWh | +58.19 kWh | +217.4% |
| 2020-05-24 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-24 | co2_kg | 0.75 kg | 0.53 kg | -0.22 kg | -29.2% |
<!-- kasflex:validation:end -->

## Interpretation

| Column | Meaning |
|---|---|
| Measured | AGC value: pipe heat by the dataset's formula, lamp electricity, CO₂ dosed |
| Simulated | GreenLight replay of the same day with the AGC2 calibration |
| Error | simulated − measured |
| Rel. error | error divided by measured value |

A large error is still a valid finding. A missing or non-finite simulated value is
not.

What is still wrong:

- **May heat.** April is now close (19 against 17 kWh/day), but May is still about
  2.5 times too high (35 against 14). On May nights the measured greenhouse floats
  about 0.8 K above its heating setpoint with the pipes mostly off, while the model
  drifts to the setpoint and heats. The model also runs about 1.3 K warm at midday.
  [CALIBRATION.md](CALIBRATION.md) says what was checked.
- **Electricity is not an independent check.** Measured lamp state drives the replay,
  so it mainly checks lamp power and integration.
- **Reference heat in January** is about 45% low; see above.

## Code

- `src/kasflex/validation.py` — measured data, canonical replay, finite-value gate,
  report and browser validation status.
- `src/kasflex/validation_agc2.py` — CSV conversion, compartment choice, day
  selection, unit conversion, lamp and weather conversion, replay mapping and
  `AGC2_CALIBRATION`.
- `workers/greenlight/worker.py` — isolated GreenLight-Gym2 model process, named
  calibration parameters and the AGC heat formula.
- `workers/greenlight/calibrate_agc2.py` — the fit/test harness.

GreenLight-Gym2 is AGPL-3.0-or-later and remains isolated in its own environment.
Process isolation is a technical boundary, **not legal confirmation**; public
promotion still requires the WUR licensing check noted in the project brief.
