# KasFlex

> **Verified greenhouse energy planning, with a human in the loop.**

KasFlex explores whether an AI can help a Dutch greenhouse shift energy use around grid congestion **without being allowed to violate the constraints that matter**.

It combines a planner, deterministic safety verification, greenhouse simulation, flexible energy assets, human review, and an auditable experiment harness.

> **Simulation only.** No greenhouse equipment is connected. Nothing here is
> validated for operational use, and no figure produced with the built-in surrogate
> greenhouse model may be published as a result. Every number is **apparatus, not findings**.
> The demo can use real Dutch market and weather inputs, but greenhouse climate,
> heat demand and crop outcomes are still simulated. Until measured-data validation
> is complete, those model-derived outcomes remain explicitly unvalidated.

## What works today

- One-click demo with **real historical Dutch day-ahead prices and weather inputs**
- Offline replay after those inputs have been cached
- ENTSO-E day-ahead price pipeline for normal runs
- Forecast weather kept separate from realised weather
- Rule-based, learned and LLM-backed planners
- Independent safety verification
- Human editing followed by mandatory re-verification
- Battery, CHP, boiler, heat-buffer, lighting and PV dispatch
- Grower-facing and researcher-facing interfaces
- Append-only review and disagreement records
- JSON-LD / CSV research export
- GreenLight-Gym2 integration through an isolated worker
- Checksummed provenance for downloaded series

The main scientific gap is still greenhouse-model validation against measured operation. See [`docs/VALIDATION.md`](docs/VALIDATION.md).

## Try it

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
kasflex ui
```

On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
kasflex ui
```

Then choose **“Just show me a demo first.”**

The demo prepares a historical Dutch replay using real day-ahead electricity prices and archived weather forecast data. Separate realised weather is used for evaluation when available. The series are cached locally with provenance and checksums, so the prepared demo can be replayed offline.

The word **demo** still matters: asset configuration and greenhouse response remain simulated.

## How it works

```text
             day-ahead prices
                    │
weather forecast ───┼──────┐
                    ▼      │
              ┌──────────┐ │
              │ planner  │ │
              └────┬─────┘ │
                   ▼       │
              proposed plan
                   │
                   ▼
            ┌──────────────┐
            │ safety check │
            └──────┬───────┘
                   │
          accepted / revised
                   │
                   ▼
          ┌─────────────────┐
          │ human review    │
          └────────┬────────┘
                   ▼
        simulated greenhouse day
```

The planner can schedule energy. It does not get to redefine the constraints.

## Real inputs versus simulated outcomes

| Layer | Meaning | Current status |
|---|---|---|
| Electricity price | Dutch day-ahead market input | real data supported |
| Weather forecast | information available at planning time | real data supported |
| Realised weather | what actually happened | separate real series supported |
| Asset dispatch | battery/CHP/boiler/buffer behavior | modelled |
| Greenhouse climate | temperature/RH/CO₂ response | simulated |
| Crop response | DLI/growth or GreenLight output | simulated |
| Human decision | approve/reject/edit/objection | directly observed |

This separation is deliberate. A planner must not be scored against future weather it was never supposed to know.

## Interfaces

### Grower interface

`/`

Designed around a few practical questions:

- What is KasFlex proposing?
- What changes compared with normal operation?
- Why?
- What is the expected cost difference?
- Is the crop still inside the allowed envelope?
- Do I agree?

### Research interface

`/advanced`

Shows the full instrument:

- all hourly intervals;
- checker verdicts and violations;
- planner comparisons;
- configuration;
- data provenance;
- metrics;
- human edits and re-verification.

When the checker is disabled, the UI says **not verified**, never “accepted”.

## Demo data

The grower-facing Demo button no longer means generated prices/weather.

KasFlex prepares and caches:

```text
data/cache/
├── entsoe_da_YYYY-MM-DD.*
├── weather_forecast_YYYY-MM-DD_LAT_LON.*
├── weather_actual_YYYY-MM-DD_LAT_LON.*    # when available
└── MANIFEST.json
```

The manifest records source, terms/licence, retrieval date, schema, row count and SHA-256 checksum.

Synthetic data remains available for tests and deliberate synthetic experiments. It is simply no longer what the normal Demo button means.

## Normal real-data operation

Set an ENTSO-E API key:

```bash
export ENTSOE_API_KEY=...
```

Fetch a day:

```bash
kasflex fetch --date 2026-09-21
```

Run from the cache:

```bash
kasflex run --config configs/scenario_westland_winter.yaml
```

Or run the daily job:

```bash
kasflex daily
```

KasFlex is cache-first. Once inputs have been acquired, planning does not need a live service.

## Greenhouse physics

KasFlex keeps greenhouse physics behind a narrow interface.

**Surrogate greenhouse** — fast and deterministic, useful for testing the complete application, but not scientifically validated.

**GreenLight-Gym2** — runs in a separate process/environment because of licence and NumPy-version constraints.

```bash
python3 -m venv .venv-greenlight
./.venv-greenlight/bin/pip install -r workers/greenlight/requirements.txt
kasflex run --greenhouse greenlight
```

The worker returns hourly heat demand, CO₂ demand, indoor temperature, RH, CO₂, DLI and crop-growth output.

Using GreenLight does not automatically make a scenario validated. The KasFlex configuration still has to be compared against measured greenhouse data.

## Validation

The repository contains the first AGC validation workflow:

```text
docs/VALIDATION.md
src/kasflex/validation.py
```

Run:

```bash
kasflex validate
```

once the documented AGC data are available locally.

The validation scale is the measured research compartment, not the 5 ha commercial scenario. A validation exercise should publish the deviation whether it is small or large.

## Planners

| Planner | Purpose |
|---|---|
| `rule-based` | conventional baseline |
| `learned` | demand forecasting + schedule optimisation |
| `naive` | simple / useful unsafe comparison |
| `llm` | language-model planner |
| `mpc` | extension point |

```bash
kasflex run --planner learned
kasflex experiment --days 3
```

Numbers produced with an unvalidated greenhouse model are **apparatus, not greenhouse-performance findings**.

## AI

The conversational layer is optional. KasFlex can work with hosted providers, OpenAI-compatible endpoints and Ollama/local models.

Planning, checking and human review do not require an LLM. Without one, you lose conversational explanation rather than the safety pipeline.

## Repository map

```text
configs/                 reproducible scenarios
data/cache/              checksummed downloaded series
docs/                    architecture, data, FAIR, validation and usage
src/kasflex/
├── adapters/            greenhouse and grid seams
├── checker/             deterministic verification
├── controllers/         planners
├── data/                acquisition, cache and provenance
├── energy/              assets and dispatch
├── forecast/            learned demand forecasting
└── ui/                  grower + research interfaces
workers/greenlight/      isolated GreenLight-Gym2 worker
tests/                   offline test suite
```

Useful documents:

- [`docs/GUIDE.md`](docs/GUIDE.md)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/DATA.md`](docs/DATA.md)
- [`docs/PROVENANCE.md`](docs/PROVENANCE.md)
- [`docs/VALIDATION.md`](docs/VALIDATION.md)
- [`docs/DECISIONS.md`](docs/DECISIONS.md)
- [`docs/USAGE.md`](docs/USAGE.md)

## Research safeguards

KasFlex deliberately refuses a few convenient shortcuts:

- forecast and realised weather are not interchangeable;
- missing real data does not silently become synthetic data;
- edited plans lose their old verdict until checked again;
- checker-disabled runs are **not verified**;
- cache corruption raises on checksum mismatch;
- clock-change days are refused instead of being squeezed into 24 incorrect intervals;
- external data carry provenance;
- greenhouse outcomes stay labelled unvalidated until validation has actually been run.

## Development

```bash
make test
make lint
```

Or:

```bash
pytest
```

Environment check:

```bash
kasflex doctor
```

Data registry:

```bash
kasflex datasets
```

## Licence

KasFlex core is [Apache-2.0](LICENSE).

`workers/greenlight/worker.py` is AGPL-3.0-or-later as part of the isolated GreenLight integration surface.

Third-party datasets/services retain their own terms. See [`docs/DATA.md`](docs/DATA.md).
