# Validation against measured greenhouse data

> **Status: quantified, not calibrated and not ready for operational use.**
> KasFlex now runs the surrogate against measured Autonomous Greenhouse Challenge
> data. The errors are large enough that model-derived crop and climate figures must
> still be presented as simulation, not fact.

## Reproduce it

The repository contains a compact, checksummed Reference-compartment subset from
the [Autonomous Greenhouse Challenge, Second Edition](https://doi.org/10.4121/uuid:88d22c60-21b3-4ea8-90db-20249a5be2a7)
(CC0). It covers three days selected before comparison: cold/dark, bright spring,
and bright/warm. No validation-day result was used to tune the surrogate.

```bash
kasflex validate
kasflex validate --days 2020-01-25,2020-04-20
kasflex validate --json-out validation.json
```

The exact archive hash, compartment, floor area, day selection, units and
transformations are in `data/validation/agc2_reference_manifest.json`. The bundled
CSV files are deliberately small enough to keep this check reproducible in CI.

## Accuracy summary

Run on 2026-09-20 with `surrogate-v1` over 3 days and 72 hourly observations:

| Quantity | Samples | MAE | RMSE | MAPE |
|---|---:|---:|---:|---:|
| Heating | 3 days | 44.51 kWh | 55.61 kWh | 52.5% |
| Electricity | 3 days | 19.86 kWh | 25.80 kWh | 16.5% |
| CO2 use | 3 days | 4.95 kg | 6.52 kg | 55.8% |
| Indoor temperature | 72 hours | 4.59 °C | 4.93 °C | 19.1% |
| Relative humidity | 72 hours | 21.32 percentage points | 24.16 percentage points | 32.1% |
| Indoor CO2 | 72 hours | 232.51 ppm | 267.48 ppm | 42.3% |

These are out-of-sample error measurements, not calibration targets. In particular,
the model is about 4.5 °C too cold on average and substantially underestimates heat
and CO2 consumption. That is actionable evidence that calibration and broader-day
validation are still required.

## Day-level comparison

Values below are simulated minus measured; `n/a` is used where the measured value
is zero.

| Day | Quantity | Measured | Simulated | Error | Relative error |
|---|---|---:|---:|---:|---:|
| 2020-01-25 | Heating | 138.40 kWh | 56.49 kWh | -81.91 kWh | -59.2% |
| 2020-01-25 | Electricity | 230.40 kWh | 190.08 kWh | -40.32 kWh | -17.5% |
| 2020-01-25 | CO2 use | 2.33 kg | 2.07 kg | -0.26 kg | -11.1% |
| 2020-01-25 | Mean temperature | 22.39 °C | 18.14 °C | -4.25 °C | -19.0% |
| 2020-04-20 | Heating | 55.20 kWh | 4.53 kWh | -50.67 kWh | -91.8% |
| 2020-04-20 | Electricity | 124.80 kWh | 105.54 kWh | -19.26 kWh | -15.4% |
| 2020-04-20 | CO2 use | 12.73 kg | 2.20 kg | -10.53 kg | -82.7% |
| 2020-04-20 | Mean temperature | 23.53 °C | 19.24 °C | -4.28 °C | -18.2% |
| 2020-05-27 | Heating | 14.93 kWh | 15.89 kWh | +0.96 kWh | +6.4% |
| 2020-05-27 | Electricity | 0.00 kWh | 0.00 kWh | +0.00 kWh | n/a |
| 2020-05-27 | CO2 use | 5.51 kg | 1.45 kg | -4.06 kg | -73.7% |
| 2020-05-27 | Mean temperature | 24.31 °C | 19.36 °C | -4.95 °C | -20.4% |

## Interpretation and limits

- Passing the validation command means the comparison is reproducible; it does not
  mean the model is accurate.
- Three deliberately varied days make model error visible but are not enough for a
  scientific validation claim.
- The surrogate does not model the recorded screen and ventilation controls.
- `DayOutcome.validated` therefore remains `false` and the UI continues to show a
  simulation warning.
- The next gate is calibration on separate training days, followed by evaluation
  over the full growing period without changing parameters.

The implementation lives in `src/kasflex/validation.py`; its regression tests are
in `tests/test_validation_real.py`.
