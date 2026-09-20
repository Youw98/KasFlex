# Using KasFlex

> **Simulation only.** KasFlex is not connected to greenhouse equipment. Real
> electricity and weather inputs are supported, but greenhouse-model outputs remain
> simulated and **not validated** until measured-data validation is completed.

## Pick the way you want to use it

### Downloaded application

Open https://github.com/Youw98/KasFlex/releases/latest and download:

- Windows: `KasFlex-windows.exe`
- macOS: `KasFlex-macos`
- Linux: `KasFlex-linux`

Windows users can double-click the executable. On macOS/Linux, run
`chmod +x <filename>` once first. The browser interface runs locally.

### Source checkout

```bash
git clone https://github.com/Youw98/KasFlex.git
cd KasFlex
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
kasflex doctor
kasflex ui
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

## First browser run

The main page is the team-demo workspace. It prepares the real historical demo day
and shows the day context before it asks for a plan.

1. Check the electricity-price, weather and grid cards.
2. Pick **Balanced**, **Lowest cost**, or **Grid relief**.
3. Set the battery reserve and any operating preferences.
4. Click **Build tomorrow's plan**.
5. Review the independently checked proposal.
6. Change individual suggestions back to normal control if needed; every change is
   re-verified.
7. Record the checked revision as the final day plan.

The first successful demo-data load is cached; later runs reuse it. Market/weather
inputs are real historical data, while greenhouse response, crop outcomes and asset
dispatch remain simulated.

## Direct ENTSO-E research-data workflow

```bash
export ENTSOE_API_KEY=...
kasflex fetch --date 2026-09-21
kasflex run --data-source cache --date 2026-09-21
```

The dates must match. `--data-source cache` is important because the bundled
scenario intentionally stays synthetic by default for reproducibility.

After the fetch succeeds, the run itself is offline-safe. Missing cache data causes
an error rather than a silent switch back to synthetic inputs.

## Browser interface

```bash
kasflex ui
```

The team-demo interface is `/`. The research interface remains available at
`/advanced` for direct technical use, but the demo does not navigate into it.
A stale `/grower` URL also opens the new demo rather than the previous interface.

Any human edit must be re-verified. With the checker disabled, the UI says **not
verified**, never accepted.

```bash
kasflex ui --anonymous --port 9000 --no-browser
```

> The server is localhost-only and has no authentication. Do not expose it to a
> network.

## Run one day

```bash
kasflex run
```

Prints the plan hour by hour with the planner's reasoning, the checker's verdict, and
the realised outcome. Use `--config` to point at a different scenario.

Run the same day unverified, to see the difference:

```bash
kasflex run --planner naive --no-checker
kasflex run --planner naive
```

The first proposes a constraint-blind plan and executes it. The second has the same
planner rejected by the checker until control falls back to the baseline.

## Run the experiment matrix

```bash
kasflex experiment --days 3
```

Runs every condition across every day unattended and writes one JSON record per run
to `results/runs.jsonl`, then prints the headline table. This is the command an
external researcher runs.

## Use the data-driven planner

```bash
kasflex run --planner learned
```

It fits a demand model to the greenhouse's past operation, predicts tomorrow, and
searches for the cheapest feasible schedule. Everything is offline and deterministic.

Score the forecaster on its own:

```python
from kasflex.adapters.greenhouse import SurrogateGreenhouse
from kasflex.data.synthetic import synthetic_history
from kasflex.forecast import (
    RidgeForecaster, SeasonalNaiveForecaster, build_history, rolling_origin_backtest,
)

weather = synthetic_history(150, seed=5, floor_area_m2=50_000)
history = build_history(weather.days, SurrogateGreenhouse(), 50_000)

for model in (SeasonalNaiveForecaster(), RidgeForecaster()):
    print(rolling_origin_backtest(history, model, min_train_days=21).summary())
```

```
seasonal-naive   MAE    831.2 kW ( 47.1% of mean)   skill vs naive +0.000   n=129
ridge            MAE    342.7 kW ( 19.4% of mean)   skill vs naive +0.588   n=129
```

Check it found the physics rather than an artifact:

```python
model = RidgeForecaster(); model.fit(history, upto=100)
print(list(model.coefficients())[:3])   # degree_hours and outdoor_temp_c should lead
```

Build a history from **real** data instead of synthetic weather by passing any
objects with `date`, `forecast` and `actual` condition series to `build_history`.

Trade robustness against cost with the storage reserve:

```python
from kasflex.controllers.scheduler import LearnedPlanner
planner = LearnedPlanner(history=history[:100])
planner.scheduler.safety_margin = 0.45   # default; 0.0 plans to the exact limit
```

## Verify a plan by hand

```bash
kasflex verify --plan my_plan.json
```

Exit code 0 if accepted, 1 if rejected, 2 if the file is not a plan. Rejections name
the constraint, the hour, the actual value and the feasible bound.

## Validate the greenhouse model against measured data

```bash
kasflex validate --write-doc docs/VALIDATION.md
```

Compares KasFlex's greenhouse model to the [Autonomous Greenhouse Challenge
2nd edition](https://doi.org/10.4121/uuid:88d22c60-21b3-4ea8-90db-20249a5be2a7)
measured series. When the dataset is not on disk the command explains where
to get it, how to lay it out, and stops with exit code 2 — nothing is
downloaded silently. Once the dataset is present, `--write-doc` updates the
deviation table in [`docs/VALIDATION.md`](VALIDATION.md) in place, between
machine markers, so history carries the measurement. Every KasFlex result
is stamped `greenhouse_validated: false` until this table exists.

## Run it automatically every day

The daily job fetches whatever the cache is missing, plans the next day, and
appends one record to `results/daily.jsonl`.

```bash
export ENTSOE_API_KEY=...            # register at https://transparency.entsoe.eu/
kasflex fetch --date 2026-09-08      # download and cache one day
kasflex run --data-source cache --date 2026-09-08
kasflex daily                        # fetch if needed, plan tomorrow, record it
```

Then schedule it. `deploy/` has a cron file, a systemd timer and a GitHub Actions
workflow; see [deploy/README.md](../deploy/README.md). Time it for **after 13:00
CET** — that is when Dutch day-ahead prices for tomorrow publish, and before that
they do not exist.

Four properties make it safe to leave running:

| | |
|---|---|
| **Cache-first** | A day already cached is never re-fetched. Re-running is free. |
| **Offline-safe** | Network down but the day is cached? The run proceeds. `--offline` forces it. |
| **Idempotent** | Same day, same result. Safe to retry after a failure. |
| **Provenance** | Every series records source, licence, retrieval date and SHA-256. |

Check what you have without touching the network:

```bash
kasflex fetch --offline --days 7
```

A record with `"actuals_available": false` was scored against the forecast, because
the weather archive had not caught up with the day yet. Re-run that date afterwards
for a genuine out-of-sample score.

### What is configured, not fetched

The **TTF gas price** has no free public API, so it lives in the scenario file as
`gas_price_eur_kwh`. Update it when the market moves materially.

### One caveat before you trust a schedule

The HTTP calls have not been exercised against the live services — the environment
this was built in blocks them. Parsing, caching, retry and everything downstream are
covered by tests against recorded responses. **Run `kasflex fetch --date <yesterday>`
once by hand and look at the output before scheduling anything.**

## See the data provenance

```bash
kasflex datasets
kasflex datasets --markdown     # the table in docs/DATA.md
```

## Turn on the real greenhouse model

GreenLight-Gym2 runs in its own environment, deliberately — it is AGPL-3.0 and pins
`numpy<2` (see [DECISIONS.md](DECISIONS.md) ADR-0001 and ADR-0002).

```bash
python3 -m venv .venv-greenlight
./.venv-greenlight/bin/pip install -r workers/greenlight/requirements.txt
kasflex run --greenhouse greenlight
```

Or point `KASFLEX_GREENLIGHT_PYTHON` at any interpreter that has `gl-gym` installed.
**Do not install `gl-gym` into the main environment** — `kasflex doctor` will warn
you if you have.

## Turn on the grid check (phase 2)

```bash
pip install -e ".[grid]"
```

```python
from kasflex.adapters.grid import check_feeder

# Three greenhouses on one MV feeder, all lighting at once.
simultaneous = [[5000.0, 5000.0, 5000.0] if h == 17 else [100.0] * 3 for h in range(24)]
print(check_feeder(simultaneous).violations)
```

## Write a scenario

Copy `configs/scenario_westland_winter.yaml` and edit. Unknown keys are rejected
rather than ignored, so a misspelled limit fails loudly instead of silently changing
every result.

The congestion window is the interesting knob:

```yaml
hub:
  contract:
    import_limit_kw: 6000
    export_limit_kw: 4000
    congestion_windows:
      17: [3000, 1000]     # hour 17: reduced import and export
```

## Use a language model

```bash
pip install -e ".[llm]"
export ANTHROPIC_API_KEY=...
```

```python
from kasflex.controllers.llm import LlmPlanner, TraceStore, anthropic_call_fn

planner = LlmPlanner(
    model="claude-opus-5",
    call_fn=anthropic_call_fn(),
    traces=TraceStore("traces/planner.jsonl"),
)
```

Every call is recorded. To replay a recorded run with no API access at all, drop
`call_fn`:

```python
planner = LlmPlanner(model="claude-opus-5", traces=TraceStore("traces/planner.jsonl"))
```

It will raise rather than reach the network if a trace is missing.

## Add a safety check

Three lines and a test:

```python
from kasflex.checker.rules import CheckContext, check
from kasflex.checker.verdict import Severity, Violation

@check("battery.daily_cycles")
def _cycle_limit(ctx: CheckContext) -> list[Violation]:
    cycles = sum(iv.battery_charge_kw for iv in ctx.dispatch.intervals) / ctx.hub.battery.capacity_kwh
    if cycles <= 1.5:
        return []
    return [Violation(
        constraint="battery.daily_cycles", category="asset", severity=Severity.HARD,
        hour=None, actual=cycles, bound=1.5, unit="cycles/day",
        message="Cycling the battery this hard shortens its warranted life.",
    )]
```

It is now switchable, excludable and reported like every other check. The test suite
will fail until `tests/test_checker.py` names it — that is deliberate (R20).

## Add a planner

Implement `plan(context) -> Plan`. That is the whole interface:

```python
class MyPlanner:
    name = "mine"

    def plan(self, context):
        ...  # context.forecast, context.hub, context.previous_verdict
        return Plan(date=context.date, intervals=..., planner=self.name)
```

Register it in `kasflex.experiment.build_planner` to make it available from the CLI.

## Run the tests

```bash
make test          # or: pytest
make lint
make reproduce     # the matrix, from a clean state
```
