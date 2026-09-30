# Validation against measured data (stage 1)

> **Status: calibrated and tested on held-out days; still not acceptable for
> operational use.** After calibration, GreenLight's heat is within about 20% in
> winter, but still roughly three times too high in April–May. CO₂ and lamp
> electricity are close. KasFlex remains research software and every plan remains
> **not validated for operational use**.

KasFlex refuses to create a validation result unless a real greenhouse simulator
replay ran. A missing replay, missing GreenLight worker, malformed file, or non-finite
number is a hard failure; it does not become a table full of NaN values.

## Validation reference

The reference is the **Autonomous Greenhouse Challenge, Second Edition (2019)**,
DOI `10.4121/uuid:88d22c60-21b3-4ea8-90db-20249a5be2a7`, CC0.

All six compartments are the same 96 m² Bleiswijk glasshouse with the same lamps,
screens and weather station; only who ran them differs. The grower-operated
**Reference** compartment remains the preferred target. The table below uses the
**AICU** compartment instead, because the official 4TU archive could not be reached
when the calibration was done and a public copy of the same CC0 files exists for
AICU only. The manifest in the result records that source, and that the archive
checksum is **not** verified. Do not mix any compartment with the 5 ha commercial
demonstration scenario.

## Two things the first run got wrong

The first published run (twelve Reference days, September 2026) reported heat 389%,
CO₂ 78% and electricity 11% mean absolute relative error. Two causes were
measurement mapping, not greenhouse physics, and are now fixed:

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

## Calibration

GreenLight's defaults describe a different greenhouse. Four construction parameters
were set for an AGC2 compartment, fitted on even ISO weeks and tested on odd weeks.
The details are in [CALIBRATION.md](CALIBRATION.md).

| Parameter | gl-gym default | AGC2 | Why |
|---|---:|---:|---|
| `etaLampCool` | 0.63 | 0 | gl-gym assumes water-cooled LEDs that carry 63% of lamp power away. AGC2 has HPS plus uncooled LEDs. **Physical, not fitted.** |
| `aCov` (per 144 m² floor) | 216.6 m² | 156 m² | Roof glass only: the compartment shares its walls with heated neighbours. Fitted. |
| `aRoof` (per 144 m² floor) | 52.2 m² | 17.4 m² | Fitted. The default is 36% of floor area. |
| `cLeakage` | 3e-5 | 1e-5 | Fitted. |

Held-out result on the 80 test days (the table below):

| Quantity | gl-gym defaults | Calibrated | Simulated ÷ measured, calibrated |
|---|---:|---:|---:|
| Heat, MAE per day | 93.1 kWh | 21.6 kWh | 1.39 |
| CO₂, MAE per day | 3.59 kg | 1.31 kg | 1.00 |
| Lamp electricity, MAE per day | 6.7 kWh | 6.7 kWh | 1.05 |

The heat MARE (about 125%) is dominated by spring days on which almost no heat was
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

To redo the calibration (about three minutes on four cores):

```bash
./.venv-greenlight/bin/python workers/greenlight/calibrate_agc2.py \
  --cache-dir data/cache --out results/calibration-agc2.json
```

For development tests only, `--greenhouse surrogate` exercises the same replay and
report pipeline. It is not a substitute for the GreenLight comparison.

The committed `results/validation-agc2.json` proves that a measured comparison ran
and turns the grower demo's badge from **pending** to **measured validation**. It
does not claim the model passed a calibration threshold.

## Deviation table

<!-- kasflex:validation:start -->
Generated 2026-09-29T20:41:11+00:00 from Autonomous Greenhouse Challenge, Second Edition — AICU compartment at `data/cache/agc2`.

Days compared: 80

## Aggregate error

| Quantity | Days | MAE | Mean absolute relative error |
|---|---:|---:|---:|
| co2_kg | 80 | 1.31 kg | 27.5% |
| electricity_kwh | 80 | 6.69 kWh | 8.5% |
| heating_kwh | 80 | 21.63 kWh | 124.5% |

## Per-day deviation

| Day | Quantity | Measured | Simulated | Error | Rel. error |
|---|---|---:|---:|---:|---:|
| 2019-12-16 | heating_kwh | 76.15 kWh | 10.10 kWh | -66.05 kWh | -86.7% |
| 2019-12-16 | electricity_kwh | 81.10 kWh | 207.85 kWh | +126.76 kWh | +156.3% |
| 2019-12-16 | co2_kg | 0.53 kg | 1.84 kg | +1.32 kg | +250.3% |
| 2019-12-17 | heating_kwh | 30.21 kWh | 29.06 kWh | -1.14 kWh | -3.8% |
| 2019-12-17 | electricity_kwh | 50.18 kWh | 110.62 kWh | +60.44 kWh | +120.5% |
| 2019-12-17 | co2_kg | 0.53 kg | 1.29 kg | +0.76 kg | +144.2% |
| 2019-12-18 | heating_kwh | 30.48 kWh | 35.97 kWh | +5.49 kWh | +18.0% |
| 2019-12-18 | electricity_kwh | 80.35 kWh | 187.53 kWh | +107.18 kWh | +133.4% |
| 2019-12-18 | co2_kg | 1.10 kg | 2.26 kg | +1.16 kg | +105.4% |
| 2019-12-19 | heating_kwh | 3.18 kWh | 10.32 kWh | +7.13 kWh | +224.1% |
| 2019-12-19 | electricity_kwh | 134.78 kWh | 146.19 kWh | +11.40 kWh | +8.5% |
| 2019-12-19 | co2_kg | 1.90 kg | 3.08 kg | +1.18 kg | +61.7% |
| 2019-12-20 | heating_kwh | 15.27 kWh | 17.80 kWh | +2.53 kWh | +16.6% |
| 2019-12-20 | electricity_kwh | 180.23 kWh | 185.99 kWh | +5.76 kWh | +3.2% |
| 2019-12-20 | co2_kg | 2.98 kg | 3.53 kg | +0.55 kg | +18.6% |
| 2019-12-21 | heating_kwh | 65.87 kWh | 64.58 kWh | -1.29 kWh | -2.0% |
| 2019-12-21 | electricity_kwh | 166.06 kWh | 168.83 kWh | +2.77 kWh | +1.7% |
| 2019-12-21 | co2_kg | 1.51 kg | 2.15 kg | +0.64 kg | +42.4% |
| 2019-12-22 | heating_kwh | 48.85 kWh | 53.58 kWh | +4.74 kWh | +9.7% |
| 2019-12-22 | electricity_kwh | 159.08 kWh | 161.83 kWh | +2.75 kWh | +1.7% |
| 2019-12-22 | co2_kg | 2.16 kg | 1.87 kg | -0.29 kg | -13.6% |
| 2019-12-30 | heating_kwh | 70.90 kWh | 81.19 kWh | +10.28 kWh | +14.5% |
| 2019-12-30 | electricity_kwh | 192.19 kWh | 229.17 kWh | +36.98 kWh | +19.2% |
| 2019-12-30 | co2_kg | 4.49 kg | 4.96 kg | +0.47 kg | +10.5% |
| 2019-12-31 | heating_kwh | 62.98 kWh | 58.53 kWh | -4.45 kWh | -7.1% |
| 2019-12-31 | electricity_kwh | 214.76 kWh | 217.52 kWh | +2.76 kWh | +1.3% |
| 2019-12-31 | co2_kg | 3.68 kg | 4.16 kg | +0.48 kg | +13.0% |
| 2020-01-01 | heating_kwh | 85.42 kWh | 63.45 kWh | -21.98 kWh | -25.7% |
| 2020-01-01 | electricity_kwh | 228.80 kWh | 230.31 kWh | +1.51 kWh | +0.7% |
| 2020-01-01 | co2_kg | 3.81 kg | 3.11 kg | -0.69 kg | -18.2% |
| 2020-01-02 | heating_kwh | 94.88 kWh | 66.70 kWh | -28.18 kWh | -29.7% |
| 2020-01-02 | electricity_kwh | 228.80 kWh | 230.31 kWh | +1.51 kWh | +0.7% |
| 2020-01-02 | co2_kg | 3.87 kg | 3.02 kg | -0.85 kg | -22.0% |
| 2020-01-03 | heating_kwh | 76.75 kWh | 60.78 kWh | -15.97 kWh | -20.8% |
| 2020-01-03 | electricity_kwh | 226.51 kWh | 228.03 kWh | +1.52 kWh | +0.7% |
| 2020-01-03 | co2_kg | 5.09 kg | 3.72 kg | -1.37 kg | -27.0% |
| 2020-01-04 | heating_kwh | 55.51 kWh | 72.40 kWh | +16.89 kWh | +30.4% |
| 2020-01-04 | electricity_kwh | 226.51 kWh | 230.31 kWh | +3.80 kWh | +1.7% |
| 2020-01-04 | co2_kg | 5.89 kg | 4.29 kg | -1.60 kg | -27.1% |
| 2020-01-05 | heating_kwh | 52.06 kWh | 54.77 kWh | +2.71 kWh | +5.2% |
| 2020-01-05 | electricity_kwh | 227.66 kWh | 230.31 kWh | +2.66 kWh | +1.2% |
| 2020-01-05 | co2_kg | 4.95 kg | 4.11 kg | -0.84 kg | -16.9% |
| 2020-01-13 | heating_kwh | 40.89 kWh | 54.77 kWh | +13.88 kWh | +33.9% |
| 2020-01-13 | electricity_kwh | 214.36 kWh | 220.66 kWh | +6.30 kWh | +2.9% |
| 2020-01-13 | co2_kg | 5.27 kg | 4.57 kg | -0.70 kg | -13.3% |
| 2020-01-14 | heating_kwh | 34.33 kWh | 47.35 kWh | +13.02 kWh | +37.9% |
| 2020-01-14 | electricity_kwh | 223.96 kWh | 225.68 kWh | +1.72 kWh | +0.8% |
| 2020-01-14 | co2_kg | 7.49 kg | 7.60 kg | +0.10 kg | +1.3% |
| 2020-01-15 | heating_kwh | 28.10 kWh | 41.21 kWh | +13.11 kWh | +46.6% |
| 2020-01-15 | electricity_kwh | 223.96 kWh | 228.72 kWh | +4.76 kWh | +2.1% |
| 2020-01-15 | co2_kg | 6.99 kg | 6.85 kg | -0.14 kg | -1.9% |
| 2020-01-17 | heating_kwh | 31.29 kWh | 54.82 kWh | +23.54 kWh | +75.2% |
| 2020-01-17 | electricity_kwh | 215.60 kWh | 222.64 kWh | +7.04 kWh | +3.3% |
| 2020-01-17 | co2_kg | 6.70 kg | 6.68 kg | -0.02 kg | -0.2% |
| 2020-01-18 | heating_kwh | 64.93 kWh | 107.03 kWh | +42.10 kWh | +64.8% |
| 2020-01-18 | electricity_kwh | 131.66 kWh | 134.38 kWh | +2.72 kWh | +2.1% |
| 2020-01-18 | co2_kg | 3.72 kg | 3.73 kg | +0.01 kg | +0.2% |
| 2020-01-19 | heating_kwh | 40.24 kWh | 48.15 kWh | +7.91 kWh | +19.6% |
| 2020-01-19 | electricity_kwh | 226.72 kWh | 228.04 kWh | +1.32 kWh | +0.6% |
| 2020-01-19 | co2_kg | 5.61 kg | 5.17 kg | -0.44 kg | -7.8% |
| 2020-01-27 | heating_kwh | 23.87 kWh | 41.76 kWh | +17.89 kWh | +75.0% |
| 2020-01-27 | electricity_kwh | 195.98 kWh | 221.72 kWh | +25.74 kWh | +13.1% |
| 2020-01-27 | co2_kg | 5.97 kg | 4.21 kg | -1.76 kg | -29.5% |
| 2020-01-28 | heating_kwh | 48.46 kWh | 61.35 kWh | +12.90 kWh | +26.6% |
| 2020-01-28 | electricity_kwh | 234.04 kWh | 236.79 kWh | +2.75 kWh | +1.2% |
| 2020-01-28 | co2_kg | 5.65 kg | 4.41 kg | -1.25 kg | -22.0% |
| 2020-01-29 | heating_kwh | 32.13 kWh | 58.14 kWh | +26.01 kWh | +81.0% |
| 2020-01-29 | electricity_kwh | 234.04 kWh | 237.93 kWh | +3.89 kWh | +1.7% |
| 2020-01-29 | co2_kg | 6.60 kg | 5.55 kg | -1.04 kg | -15.8% |
| 2020-01-30 | heating_kwh | 22.40 kWh | 38.56 kWh | +16.16 kWh | +72.2% |
| 2020-01-30 | electricity_kwh | 236.14 kWh | 238.89 kWh | +2.74 kWh | +1.2% |
| 2020-01-30 | co2_kg | 6.79 kg | 4.73 kg | -2.05 kg | -30.3% |
| 2020-01-31 | heating_kwh | 24.94 kWh | 30.87 kWh | +5.92 kWh | +23.7% |
| 2020-01-31 | electricity_kwh | 234.82 kWh | 238.71 kWh | +3.89 kWh | +1.7% |
| 2020-01-31 | co2_kg | 7.69 kg | 5.02 kg | -2.67 kg | -34.7% |
| 2020-02-01 | heating_kwh | 9.70 kWh | 29.79 kWh | +20.09 kWh | +207.2% |
| 2020-02-01 | electricity_kwh | 249.39 kWh | 251.98 kWh | +2.58 kWh | +1.0% |
| 2020-02-01 | co2_kg | 8.67 kg | 6.46 kg | -2.21 kg | -25.5% |
| 2020-02-02 | heating_kwh | 31.69 kWh | 34.63 kWh | +2.94 kWh | +9.3% |
| 2020-02-02 | electricity_kwh | 241.38 kWh | 242.85 kWh | +1.47 kWh | +0.6% |
| 2020-02-02 | co2_kg | 6.14 kg | 4.25 kg | -1.90 kg | -30.9% |
| 2020-02-10 | heating_kwh | 30.66 kWh | 47.92 kWh | +17.25 kWh | +56.3% |
| 2020-02-10 | electricity_kwh | 244.82 kWh | 246.27 kWh | +1.46 kWh | +0.6% |
| 2020-02-10 | co2_kg | 7.71 kg | 6.36 kg | -1.35 kg | -17.5% |
| 2020-02-11 | heating_kwh | 58.92 kWh | 85.04 kWh | +26.12 kWh | +44.3% |
| 2020-02-11 | electricity_kwh | 243.67 kWh | 246.27 kWh | +2.60 kWh | +1.1% |
| 2020-02-11 | co2_kg | 7.98 kg | 6.46 kg | -1.52 kg | -19.1% |
| 2020-02-12 | heating_kwh | 49.34 kWh | 68.46 kWh | +19.12 kWh | +38.7% |
| 2020-02-12 | electricity_kwh | 243.67 kWh | 246.27 kWh | +2.60 kWh | +1.1% |
| 2020-02-12 | co2_kg | 7.24 kg | 5.72 kg | -1.53 kg | -21.1% |
| 2020-02-13 | heating_kwh | 55.04 kWh | 36.31 kWh | -18.73 kWh | -34.0% |
| 2020-02-13 | electricity_kwh | 244.82 kWh | 246.27 kWh | +1.46 kWh | +0.6% |
| 2020-02-13 | co2_kg | 5.30 kg | 3.84 kg | -1.45 kg | -27.4% |
| 2020-02-14 | heating_kwh | 19.31 kWh | 34.85 kWh | +15.54 kWh | +80.5% |
| 2020-02-14 | electricity_kwh | 243.67 kWh | 246.27 kWh | +2.60 kWh | +1.1% |
| 2020-02-14 | co2_kg | 6.10 kg | 5.14 kg | -0.96 kg | -15.8% |
| 2020-02-15 | heating_kwh | 8.06 kWh | 20.13 kWh | +12.07 kWh | +149.7% |
| 2020-02-15 | electricity_kwh | 243.67 kWh | 246.27 kWh | +2.60 kWh | +1.1% |
| 2020-02-15 | co2_kg | 7.26 kg | 4.47 kg | -2.80 kg | -38.5% |
| 2020-02-16 | heating_kwh | 16.87 kWh | 31.30 kWh | +14.43 kWh | +85.5% |
| 2020-02-16 | electricity_kwh | 244.82 kWh | 246.27 kWh | +1.46 kWh | +0.6% |
| 2020-02-16 | co2_kg | 10.82 kg | 5.52 kg | -5.30 kg | -49.0% |
| 2020-02-24 | heating_kwh | 91.66 kWh | 71.39 kWh | -20.27 kWh | -22.1% |
| 2020-02-24 | electricity_kwh | 196.53 kWh | 198.02 kWh | +1.49 kWh | +0.8% |
| 2020-02-24 | co2_kg | 4.11 kg | 3.39 kg | -0.71 kg | -17.4% |
| 2020-02-26 | heating_kwh | 119.60 kWh | 96.96 kWh | -22.64 kWh | -18.9% |
| 2020-02-26 | electricity_kwh | 196.91 kWh | 198.40 kWh | +1.49 kWh | +0.8% |
| 2020-02-26 | co2_kg | 5.01 kg | 4.41 kg | -0.59 kg | -11.9% |
| 2020-02-27 | heating_kwh | 129.05 kWh | 75.60 kWh | -53.44 kWh | -41.4% |
| 2020-02-27 | electricity_kwh | 196.91 kWh | 198.40 kWh | +1.49 kWh | +0.8% |
| 2020-02-27 | co2_kg | 3.42 kg | 3.16 kg | -0.26 kg | -7.7% |
| 2020-02-28 | heating_kwh | 98.78 kWh | 78.33 kWh | -20.46 kWh | -20.7% |
| 2020-02-28 | electricity_kwh | 195.00 kWh | 197.63 kWh | +2.63 kWh | +1.4% |
| 2020-02-28 | co2_kg | 4.34 kg | 4.18 kg | -0.15 kg | -3.5% |
| 2020-02-29 | heating_kwh | 55.77 kWh | 73.37 kWh | +17.60 kWh | +31.6% |
| 2020-02-29 | electricity_kwh | 194.04 kWh | 196.67 kWh | +2.63 kWh | +1.4% |
| 2020-02-29 | co2_kg | 6.06 kg | 4.99 kg | -1.07 kg | -17.7% |
| 2020-03-01 | heating_kwh | 43.58 kWh | 61.88 kWh | +18.29 kWh | +42.0% |
| 2020-03-01 | electricity_kwh | 196.20 kWh | 198.86 kWh | +2.66 kWh | +1.4% |
| 2020-03-01 | co2_kg | 6.28 kg | 5.25 kg | -1.02 kg | -16.3% |
| 2020-03-09 | heating_kwh | 37.49 kWh | 46.81 kWh | +9.32 kWh | +24.9% |
| 2020-03-09 | electricity_kwh | 223.08 kWh | 225.75 kWh | +2.67 kWh | +1.2% |
| 2020-03-09 | co2_kg | 6.59 kg | 6.24 kg | -0.35 kg | -5.4% |
| 2020-03-10 | heating_kwh | 47.50 kWh | 41.11 kWh | -6.39 kWh | -13.5% |
| 2020-03-10 | electricity_kwh | 223.08 kWh | 225.75 kWh | +2.67 kWh | +1.2% |
| 2020-03-10 | co2_kg | 6.53 kg | 4.29 kg | -2.25 kg | -34.4% |
| 2020-03-11 | heating_kwh | 17.79 kWh | 34.40 kWh | +16.61 kWh | +93.3% |
| 2020-03-11 | electricity_kwh | 171.60 kWh | 177.86 kWh | +6.26 kWh | +3.7% |
| 2020-03-11 | co2_kg | 7.50 kg | 7.03 kg | -0.47 kg | -6.2% |
| 2020-03-12 | heating_kwh | 38.58 kWh | 54.04 kWh | +15.45 kWh | +40.1% |
| 2020-03-12 | electricity_kwh | 156.73 kWh | 164.18 kWh | +7.46 kWh | +4.8% |
| 2020-03-12 | co2_kg | 8.29 kg | 7.86 kg | -0.43 kg | -5.2% |
| 2020-03-13 | heating_kwh | 53.88 kWh | 75.88 kWh | +22.00 kWh | +40.8% |
| 2020-03-13 | electricity_kwh | 163.59 kWh | 164.18 kWh | +0.59 kWh | +0.4% |
| 2020-03-13 | co2_kg | 5.89 kg | 4.51 kg | -1.38 kg | -23.5% |
| 2020-03-14 | heating_kwh | 34.98 kWh | 38.71 kWh | +3.73 kWh | +10.7% |
| 2020-03-14 | electricity_kwh | 178.46 kWh | 177.86 kWh | -0.60 kWh | -0.3% |
| 2020-03-14 | co2_kg | 6.00 kg | 5.40 kg | -0.59 kg | -9.9% |
| 2020-03-15 | heating_kwh | 30.80 kWh | 37.70 kWh | +6.90 kWh | +22.4% |
| 2020-03-15 | electricity_kwh | 223.08 kWh | 225.75 kWh | +2.67 kWh | +1.2% |
| 2020-03-15 | co2_kg | 6.25 kg | 5.19 kg | -1.07 kg | -17.0% |
| 2020-03-23 | heating_kwh | 70.78 kWh | 78.84 kWh | +8.06 kWh | +11.4% |
| 2020-03-23 | electricity_kwh | 106.39 kWh | 109.46 kWh | +3.06 kWh | +2.9% |
| 2020-03-23 | co2_kg | 7.20 kg | 7.83 kg | +0.63 kg | +8.8% |
| 2020-03-24 | heating_kwh | 57.19 kWh | 63.49 kWh | +6.29 kWh | +11.0% |
| 2020-03-24 | electricity_kwh | 107.54 kWh | 109.46 kWh | +1.92 kWh | +1.8% |
| 2020-03-24 | co2_kg | 7.17 kg | 7.76 kg | +0.59 kg | +8.3% |
| 2020-03-25 | heating_kwh | 55.22 kWh | 61.92 kWh | +6.70 kWh | +12.1% |
| 2020-03-25 | electricity_kwh | 107.54 kWh | 110.60 kWh | +3.06 kWh | +2.8% |
| 2020-03-25 | co2_kg | 6.55 kg | 8.10 kg | +1.55 kg | +23.6% |
| 2020-03-26 | heating_kwh | 71.02 kWh | 110.47 kWh | +39.46 kWh | +55.6% |
| 2020-03-26 | electricity_kwh | 0.00 kWh | 3.42 kWh | +3.42 kWh | n/a |
| 2020-03-26 | co2_kg | 4.49 kg | 6.37 kg | +1.88 kg | +41.7% |
| 2020-03-27 | heating_kwh | 37.74 kWh | 48.51 kWh | +10.77 kWh | +28.5% |
| 2020-03-27 | electricity_kwh | 108.68 kWh | 110.60 kWh | +1.92 kWh | +1.8% |
| 2020-03-27 | co2_kg | 6.63 kg | 7.61 kg | +0.98 kg | +14.8% |
| 2020-03-28 | heating_kwh | 49.74 kWh | 65.72 kWh | +15.97 kWh | +32.1% |
| 2020-03-28 | electricity_kwh | 72.20 kWh | 75.24 kWh | +3.04 kWh | +4.2% |
| 2020-03-28 | co2_kg | 6.83 kg | 7.68 kg | +0.85 kg | +12.5% |
| 2020-04-06 | heating_kwh | 14.37 kWh | 44.82 kWh | +30.45 kWh | +211.9% |
| 2020-04-06 | electricity_kwh | 66.12 kWh | 68.05 kWh | +1.93 kWh | +2.9% |
| 2020-04-06 | co2_kg | 8.20 kg | 8.74 kg | +0.53 kg | +6.5% |
| 2020-04-07 | heating_kwh | 14.20 kWh | 37.69 kWh | +23.49 kWh | +165.4% |
| 2020-04-07 | electricity_kwh | 78.65 kWh | 80.60 kWh | +1.95 kWh | +2.5% |
| 2020-04-07 | co2_kg | 9.72 kg | 10.73 kg | +1.01 kg | +10.4% |
| 2020-04-08 | heating_kwh | 7.43 kWh | 31.27 kWh | +23.84 kWh | +320.7% |
| 2020-04-08 | electricity_kwh | 79.55 kWh | 81.50 kWh | +1.95 kWh | +2.5% |
| 2020-04-08 | co2_kg | 7.63 kg | 12.57 kg | +4.93 kg | +64.6% |
| 2020-04-10 | heating_kwh | 17.66 kWh | 41.15 kWh | +23.49 kWh | +133.0% |
| 2020-04-10 | electricity_kwh | 79.55 kWh | 81.50 kWh | +1.95 kWh | +2.5% |
| 2020-04-10 | co2_kg | 9.37 kg | 9.33 kg | -0.04 kg | -0.4% |
| 2020-04-11 | heating_kwh | 14.00 kWh | 36.53 kWh | +22.53 kWh | +161.0% |
| 2020-04-11 | electricity_kwh | 79.55 kWh | 81.50 kWh | +1.95 kWh | +2.5% |
| 2020-04-11 | co2_kg | 10.02 kg | 10.16 kg | +0.14 kg | +1.4% |
| 2020-04-12 | heating_kwh | 10.96 kWh | 38.00 kWh | +27.04 kWh | +246.7% |
| 2020-04-12 | electricity_kwh | 79.55 kWh | 82.64 kWh | +3.09 kWh | +3.9% |
| 2020-04-12 | co2_kg | 8.70 kg | 9.11 kg | +0.41 kg | +4.7% |
| 2020-04-20 | heating_kwh | 24.49 kWh | 42.08 kWh | +17.59 kWh | +71.9% |
| 2020-04-20 | electricity_kwh | 78.65 kWh | 81.74 kWh | +3.09 kWh | +3.9% |
| 2020-04-20 | co2_kg | 12.09 kg | 10.46 kg | -1.63 kg | -13.5% |
| 2020-04-21 | heating_kwh | 13.46 kWh | 36.90 kWh | +23.44 kWh | +174.2% |
| 2020-04-21 | electricity_kwh | 78.65 kWh | 81.74 kWh | +3.09 kWh | +3.9% |
| 2020-04-21 | co2_kg | 12.74 kg | 10.76 kg | -1.98 kg | -15.5% |
| 2020-04-22 | heating_kwh | 10.54 kWh | 36.00 kWh | +25.45 kWh | +241.4% |
| 2020-04-22 | electricity_kwh | 79.42 kWh | 81.38 kWh | +1.95 kWh | +2.5% |
| 2020-04-22 | co2_kg | 12.65 kg | 11.89 kg | -0.76 kg | -6.0% |
| 2020-04-23 | heating_kwh | 9.73 kWh | 34.17 kWh | +24.44 kWh | +251.3% |
| 2020-04-23 | electricity_kwh | 68.70 kWh | 71.84 kWh | +3.13 kWh | +4.6% |
| 2020-04-23 | co2_kg | 10.46 kg | 12.49 kg | +2.03 kg | +19.4% |
| 2020-04-24 | heating_kwh | 15.58 kWh | 39.75 kWh | +24.17 kWh | +155.2% |
| 2020-04-24 | electricity_kwh | 58.76 kWh | 60.80 kWh | +2.04 kWh | +3.5% |
| 2020-04-24 | co2_kg | 10.03 kg | 8.17 kg | -1.86 kg | -18.6% |
| 2020-04-25 | heating_kwh | 35.49 kWh | 58.15 kWh | +22.66 kWh | +63.8% |
| 2020-04-25 | electricity_kwh | 58.76 kWh | 60.80 kWh | +2.04 kWh | +3.5% |
| 2020-04-25 | co2_kg | 3.64 kg | 4.70 kg | +1.07 kg | +29.3% |
| 2020-04-26 | heating_kwh | 28.60 kWh | 44.39 kWh | +15.79 kWh | +55.2% |
| 2020-04-26 | electricity_kwh | 53.34 kWh | 56.53 kWh | +3.20 kWh | +6.0% |
| 2020-04-26 | co2_kg | 5.55 kg | 6.87 kg | +1.33 kg | +23.9% |
| 2020-05-04 | heating_kwh | 5.25 kWh | 45.28 kWh | +40.03 kWh | +762.8% |
| 2020-05-04 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-04 | co2_kg | 4.16 kg | 6.42 kg | +2.26 kg | +54.2% |
| 2020-05-05 | heating_kwh | 27.15 kWh | 50.91 kWh | +23.75 kWh | +87.5% |
| 2020-05-05 | electricity_kwh | 46.10 kWh | 48.19 kWh | +2.09 kWh | +4.5% |
| 2020-05-05 | co2_kg | 10.28 kg | 9.30 kg | -0.98 kg | -9.5% |
| 2020-05-06 | heating_kwh | 23.42 kWh | 48.23 kWh | +24.80 kWh | +105.9% |
| 2020-05-06 | electricity_kwh | 47.91 kWh | 47.71 kWh | -0.20 kWh | -0.4% |
| 2020-05-06 | co2_kg | 9.48 kg | 10.07 kg | +0.59 kg | +6.2% |
| 2020-05-07 | heating_kwh | 26.82 kWh | 64.04 kWh | +37.22 kWh | +138.8% |
| 2020-05-07 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-07 | co2_kg | 5.49 kg | 9.62 kg | +4.13 kg | +75.2% |
| 2020-05-08 | heating_kwh | 16.18 kWh | 55.23 kWh | +39.05 kWh | +241.3% |
| 2020-05-08 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-08 | co2_kg | 5.26 kg | 9.95 kg | +4.68 kg | +89.0% |
| 2020-05-09 | heating_kwh | 11.33 kWh | 52.79 kWh | +41.46 kWh | +366.0% |
| 2020-05-09 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-09 | co2_kg | 8.16 kg | 10.75 kg | +2.59 kg | +31.8% |
| 2020-05-10 | heating_kwh | 25.26 kWh | 66.87 kWh | +41.60 kWh | +164.7% |
| 2020-05-10 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-10 | co2_kg | 4.60 kg | 4.87 kg | +0.27 kg | +5.9% |
| 2020-05-18 | heating_kwh | 9.90 kWh | 60.14 kWh | +50.24 kWh | +507.3% |
| 2020-05-18 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-18 | co2_kg | 7.92 kg | 9.57 kg | +1.65 kg | +20.8% |
| 2020-05-19 | heating_kwh | 7.16 kWh | 50.88 kWh | +43.72 kWh | +610.6% |
| 2020-05-19 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-19 | co2_kg | 6.45 kg | 9.61 kg | +3.16 kg | +49.0% |
| 2020-05-20 | heating_kwh | 6.26 kWh | 46.82 kWh | +40.55 kWh | +647.4% |
| 2020-05-20 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-20 | co2_kg | 5.51 kg | 10.24 kg | +4.73 kg | +85.9% |
| 2020-05-21 | heating_kwh | 4.47 kWh | 43.43 kWh | +38.96 kWh | +871.2% |
| 2020-05-21 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-21 | co2_kg | 5.93 kg | 9.24 kg | +3.32 kg | +55.9% |
| 2020-05-22 | heating_kwh | 0.00 kWh | 32.59 kWh | +32.59 kWh | n/a |
| 2020-05-22 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-22 | co2_kg | 1.76 kg | 1.63 kg | -0.14 kg | -7.8% |
| 2020-05-23 | heating_kwh | 9.89 kWh | 54.82 kWh | +44.93 kWh | +454.4% |
| 2020-05-23 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-23 | co2_kg | 2.65 kg | 2.72 kg | +0.07 kg | +2.5% |
| 2020-05-24 | heating_kwh | 26.76 kWh | 105.57 kWh | +78.81 kWh | +294.5% |
| 2020-05-24 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-24 | co2_kg | 0.75 kg | 0.53 kg | -0.22 kg | -29.3% |
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

- **Spring heat.** Per month on the held-out days, simulated vs measured pipe heat is
  close from December to February (40 vs 45, 56 vs 47, 56 vs 55 kWh/day) but not in
  April (40 vs 17) and May (56 vs 14). On spring days the model overheats by day
  (38 °C against a measured 28 °C at the same vent opening) and heats more at night.
  Ventilation capacity and night-time radiation pull the fit in opposite directions;
  four parameters cannot fix both. The next step is to fit on indoor temperature as
  well as heat, and to free the screen and cover radiation parameters.
- **Electricity is not an independent check.** Measured lamp state drives the replay,
  so it mainly checks lamp power and integration.
- **Reference is not re-run.** The calibration should be confirmed on the
  Reference compartment once the official archive is reachable.

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
