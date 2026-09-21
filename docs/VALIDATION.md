# Validation against measured data (stage 1)

> **Status: measured replay completed; calibration is not acceptable for operational
> use.** The twelve-day GreenLight comparison below is real. Its large heat and CO₂
> errors are a finding, not a pass. KasFlex remains research software and every plan
> remains **not validated for operational use**.

KasFlex now refuses to create a validation result unless a real greenhouse simulator
replay ran. A missing replay, missing GreenLight worker, malformed file, or non-finite
number is a hard failure; it does not become a table full of NaN values.

## Validation reference

The reference is the **Autonomous Greenhouse Challenge, Second Edition (2019)**,
DOI `10.4121/uuid:88d22c60-21b3-4ea8-90db-20249a5be2a7`.

Use the grower-operated **Reference** compartment at the research-compartment scale
(96 m²). Do not mix this with the 5 ha commercial demonstration scenario.

The public dataset is CC0 and contains measured greenhouse climate, control/setpoint
information and resource consumption. The raw archive is not committed to KasFlex.

## Canonical local layout

```text
data/cache/agc2/
├── MANIFEST.json
├── measured/
│   └── YYYY-MM-DD.csv
└── replay/
    └── YYYY-MM-DD.json
```

The measured CSV contains daily totals, at minimum:

```text
heating_kwh,electricity_kwh,co2_kg
```

The replay JSON is deliberately explicit rather than hiding a raw-column mapping in
the validator:

```json
{
  "floor_area_m2": 96.0,
  "greenlight_scenario": {
    "location": "...",
    "growth_year": 2019,
    "start_day": 1
  },
  "plan": {
    "date": "YYYY-MM-DD",
    "planner": "measured-replay",
    "intervals": ["24 hourly KasFlex intent rows derived from measured controls"]
  },
  "conditions": ["24 hourly external-condition rows"]
}
```

Only controls and external conditions derived from the same measured AGC day belong
in that replay. If the source mapping is uncertain, stop and document it instead of
guessing.

## Run the comparison

Download and extract the CC0 4TU archive under `data/raw/agc2/extracted`, create the
separate GreenLight environment, then run:

```bash
kasflex prepare-agc2 --sample-days 12
```

The selected dates are fixed, evenly spaced quantiles of measured daily heat use
among complete days. They are not hand-picked. Use `--all-days` for every complete
day. Then run:

```bash
kasflex validate \
  --cache-dir data/cache \
  --greenhouse greenlight \
  --result-json results/validation-agc2.json \
  --write-doc docs/VALIDATION.md
```

For development tests only, `--greenhouse surrogate` exercises the same replay and
report pipeline. A surrogate result is not a substitute for the intended
GreenLight-vs-measurement comparison.

A successful command:

1. replays every canonical day through the selected greenhouse model;
2. compares heating, lighting electricity and CO₂ totals against measured values;
3. prints finite absolute and relative errors;
4. writes the table below; and
5. writes `results/validation-agc2.json`, which is the only file that can turn the
   grower demo's validation badge from **pending** to **measured validation**.

The committed JSON proves that a measured comparison ran; it does not claim the
model passed a calibration threshold.

## Deviation table

<!-- kasflex:validation:start -->
Generated 2026-09-21T00:20:15+00:00 from Autonomous Greenhouse Challenge, Second Edition — Reference compartment at `data/cache/agc2`.

Days compared: 12

## Aggregate error

| Quantity | Days | MAE | Mean absolute relative error |
|---|---:|---:|---:|
| co2_kg | 12 | 4.33 kg | 78.0% |
| electricity_kwh | 12 | 16.34 kWh | 11.4% |
| heating_kwh | 12 | 133.45 kWh | 389.0% |

## Per-day deviation

| Day | Quantity | Measured | Simulated | Error | Rel. error |
|---|---|---:|---:|---:|---:|
| 2019-12-22 | heating_kwh | 26.67 kWh | 162.50 kWh | +135.84 kWh | +509.4% |
| 2019-12-22 | electricity_kwh | 230.40 kWh | 246.27 kWh | +15.87 kWh | +6.9% |
| 2019-12-22 | co2_kg | 2.70 kg | 6.00 kg | +3.30 kg | +122.5% |
| 2019-12-28 | heating_kwh | 89.07 kWh | 237.55 kWh | +148.48 kWh | +166.7% |
| 2019-12-28 | electricity_kwh | 230.40 kWh | 246.27 kWh | +15.87 kWh | +6.9% |
| 2019-12-28 | co2_kg | 2.59 kg | 2.81 kg | +0.22 kg | +8.6% |
| 2020-01-10 | heating_kwh | 79.47 kWh | 259.41 kWh | +179.94 kWh | +226.4% |
| 2020-01-10 | electricity_kwh | 230.40 kWh | 246.27 kWh | +15.87 kWh | +6.9% |
| 2020-01-10 | co2_kg | 3.69 kg | 4.04 kg | +0.35 kg | +9.5% |
| 2020-01-28 | heating_kwh | 158.93 kWh | 288.52 kWh | +129.59 kWh | +81.5% |
| 2020-01-28 | electricity_kwh | 230.40 kWh | 246.27 kWh | +15.87 kWh | +6.9% |
| 2020-01-28 | co2_kg | 4.23 kg | 4.41 kg | +0.18 kg | +4.2% |
| 2020-02-01 | heating_kwh | 95.20 kWh | 270.89 kWh | +175.69 kWh | +184.5% |
| 2020-02-01 | electricity_kwh | 230.40 kWh | 246.27 kWh | +15.87 kWh | +6.9% |
| 2020-02-01 | co2_kg | 3.35 kg | 6.04 kg | +2.69 kg | +80.4% |
| 2020-02-17 | heating_kwh | 126.13 kWh | 273.19 kWh | +147.06 kWh | +116.6% |
| 2020-02-17 | electricity_kwh | 230.40 kWh | 246.27 kWh | +15.87 kWh | +6.9% |
| 2020-02-17 | co2_kg | 4.88 kg | 6.33 kg | +1.45 kg | +29.7% |
| 2020-02-18 | heating_kwh | 106.67 kWh | 265.79 kWh | +159.12 kWh | +149.2% |
| 2020-02-18 | electricity_kwh | 230.40 kWh | 246.27 kWh | +15.87 kWh | +6.9% |
| 2020-02-18 | co2_kg | 5.01 kg | 7.03 kg | +2.02 kg | +40.3% |
| 2020-04-14 | heating_kwh | 70.13 kWh | 233.18 kWh | +163.05 kWh | +232.5% |
| 2020-04-14 | electricity_kwh | 182.40 kWh | 238.29 kWh | +55.89 kWh | +30.6% |
| 2020-04-14 | co2_kg | 6.82 kg | 13.57 kg | +6.75 kg | +98.9% |
| 2020-04-15 | heating_kwh | 59.73 kWh | 168.88 kWh | +109.14 kWh | +182.7% |
| 2020-04-15 | electricity_kwh | 124.80 kWh | 153.92 kWh | +29.12 kWh | +23.3% |
| 2020-04-15 | co2_kg | 7.90 kg | 17.63 kg | +9.73 kg | +123.1% |
| 2020-04-23 | heating_kwh | 51.47 kWh | 115.19 kWh | +63.72 kWh | +123.8% |
| 2020-04-23 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-04-23 | co2_kg | 7.72 kg | 13.54 kg | +5.82 kg | +75.4% |
| 2020-04-27 | heating_kwh | 45.07 kWh | 149.47 kWh | +104.40 kWh | +231.7% |
| 2020-04-27 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-04-27 | co2_kg | 8.24 kg | 17.33 kg | +9.09 kg | +110.2% |
| 2020-05-22 | heating_kwh | 3.47 kWh | 88.85 kWh | +85.38 kWh | +2463.0% |
| 2020-05-22 | electricity_kwh | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-22 | co2_kg | 4.45 kg | 14.83 kg | +10.38 kg | +233.2% |
<!-- kasflex:validation:end -->

## Interpretation

For every day and quantity:

| Column | Meaning |
|---|---|
| Measured | Metered AGC Reference-compartment value |
| Simulated | Output from the selected KasFlex greenhouse replay |
| Error | simulated − measured |
| Rel. error | error divided by measured value |

A large error is still a valid finding. A missing or non-finite simulated value is
not.

This run shows that electricity accounting is relatively close (11.4% mean absolute
relative error), while heat (389.0%) and CO₂ (78.0%) are not. Therefore the current
GreenLight parameterisation must be calibrated before any operational claim. The
electricity result is also less independent: measured lamp state drives the replay,
so it primarily checks lamp power and integration rather than predicting control.

The first publishable validation result should report the per-day table plus
aggregate MAE / relative-error summaries over a heterogeneous set of days. It should
also state the exact GreenLight-Gym2 version and replay mapping used.

## Code

- `src/kasflex/validation.py` — measured data, canonical replay, finite-value gate,
  report and browser validation status.
- `src/kasflex/validation_agc2.py` — official CSV conversion, deterministic day
  selection, unit conversion, weather conversion and replay mapping.
- `workers/greenlight/worker.py` — isolated GreenLight-Gym2 model process.
- `kasflex validate --help` — executable validation entry point.

GreenLight-Gym2 is AGPL-3.0-or-later and remains isolated in its own environment.
Process isolation is a technical boundary, **not legal confirmation**; public
promotion still requires the WUR licensing check noted in the project brief.
