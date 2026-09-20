# Validation against measured data (stage 1)

> **Status: not yet run on the public AGC2 archive in this repository.** Until the
> machine-generated table below contains finite measured-vs-simulated deviations,
> every greenhouse result remains **not validated for operational use**.

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

Create the separate GreenLight environment first, then:

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

## Deviation table

<!-- kasflex:validation:start -->
_Not yet run. See “Run the comparison” above._
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

The first publishable validation result should report the per-day table plus
aggregate MAE / relative-error summaries over a heterogeneous set of days. It should
also state the exact GreenLight-Gym2 version and replay mapping used.

## Code

- `src/kasflex/validation.py` — measured data, canonical replay, finite-value gate,
  report and browser validation status.
- `workers/greenlight/worker.py` — isolated GreenLight-Gym2 model process.
- `kasflex validate --help` — executable validation entry point.

GreenLight-Gym2 is AGPL-3.0-or-later and remains isolated in its own environment.
Process isolation is a technical boundary, **not legal confirmation**; public
promotion still requires the WUR licensing check noted in the project brief.
