# KasFlex — Apple-style workspace

The interface follows the supplied apple-design_SKILL.md: platform typography, quiet translucent navigation, clear hierarchy, immediate press feedback, reversible spring motion, and reduced-motion/transparency/contrast preferences. The requirements Markdown defines the research scope.

## Run locally

Requires Python 3.11 or later. From this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\kasflex.exe ui --anonymous
```

Open http://127.0.0.1:8765. Installation requires network access; the default synthetic scenario runs locally without API access. No frontend build step or remote fonts/images are required.

## Workspace structure

- **Overview:** daily cost, crop growth, hard violations, forecast prices, clickable hourly asset schedule, run configuration, and operator brief.
- **Plan & review:** checker feedback and human decisions alongside editable hourly intent. Each asset-schedule cell opens its hour here. Export the current plan and its configuration as JSON.
- **Experiments:** compare the three available local planners using cost bars and outcome tables.
- **Research notes:** model limitations, period/scale separation, forecast/actual separation, and oversight semantics.
- **Configuration:** a keyboard-accessible modal with grouped settings. Escape closes it and restores focus. New settings apply to the next run; an existing plan keeps its original scenario during verification and review.

The settings sheet uses a critically damped requestAnimationFrame spring. Opening/closing retargets from the current position and velocity. Reduced-motion preference uses a static transition. The UI also respects reduced transparency and increased contrast.

## Verification and limitations

Edited or rejected plans cannot be approved. Verification failures invalidate the displayed verdict. Re-verification clears stale crop/violation outcomes that the existing endpoint does not recompute. The desktop table and mobile schedule scroll horizontally where needed.

The supplied backend remains a research prototype. Default inputs are synthetic and the greenhouse model is an unvalidated surrogate. This redesign does not implement the complete requirements specification: the three-planner comparison is not the full verified/unverified AI and MPC experiment. Human approval records review of a plan that has already been simulated; it does not gate simulation execution. The research notes and permanent notice explain these boundaries.

## Validation

- 246 Python tests passed; 1 skipped with `python -X utf8 -m pytest`. Existing documentation tests require UTF-8 mode on Windows.
- Edge browser checks: all four views, settings and Escape/focus restoration, simulation, 24 chart points, 96 clickable asset cells, invalid edit rejection, corrected edit acceptance, approval logging, JSON export, three-planner comparison, and disabled approval with the checker off.
- All views checked at 390 px for horizontal page overflow. Desktop, mobile, and settings layouts visually reviewed. Reduced-motion sheet behavior checked. No JavaScript errors in the browser workflow.

UI source: `src/kasflex/ui/static/index.html`, `design.css`, and `app.js`. The Windows timezone dependency added in the earlier redesign is retained.

## MVP functionality update

See MVP-NEXT.md for the prioritized add/change/remove list and forecasting architecture. Configuration now has five sections, saves preferences locally, discards unsaved changes on close, exposes data mode/site/gas assumptions, and checks/downloads available real inputs. The browser can run cached external inputs without falling back to demo data. Full real-price acquisition needs an ENTSO-E token. A live Open-Meteo request succeeded; reliable future cost intervals and real-history training remain roadmap work.

## API configuration and saved reviews

Configuration now includes a sixth section, APIs. It lists the implemented ENTSO-E and Open-Meteo connectors, their endpoints and key requirements. ENTSO-E keys can be saved, replaced or removed in the interface and are kept in the local `.env` file. See API-SETUP.md. Browser checks cover key controls, clearing secret inputs, exclusion from localStorage and mobile layout. UI mutation checks use fixtures rather than overwriting user credentials; they do not validate a live ENTSO-E token.

History reopens saved simulated plans and review decisions. The local SQLite store at `results/reviews.sqlite3` retains immutable input snapshots, plan revisions and decisions. Approval is bound to the latest saved revision and plan hash; stale references and conflicting decisions are rejected. Editing and re-verifying creates a new revision with explicit checking enabled. Research timing is recorded only when the user opts in. This records review of simulated previews; it does not yet gate physical or simulation execution. Local results and credentials are excluded from the distribution archive.

## Daily cost projection

The Overview now separates a forecast-only cost projection from simulated outcome metrics. `forecast/cost.py` simulates the selected plan using forecast weather, then accounts for hourly electricity import, gas, liquid CO₂ and signed export revenue. The forecast is saved with the run revision, recalculated after edits and included in plan exports. Pending edits hide the old projection and export a null projection until re-verification. Older saved runs without a forecast do not invent one.

The price controls apply an absolute electricity-price change to both import and export and a percentage change to gas. They hold the schedule and energy volumes fixed, and preserve negative electricity prices. They are sensitivity scenarios, not confidence intervals, market predictions or new optimised plans. Taxes, tariffs, supplier fees, capital costs, maintenance and crop sales are excluded. Liquid CO₂ retains the dispatch model's fixed €0.30/kg assumption. Real-mode electricity inputs require downloaded published prices; a date beyond publication cannot produce a real-price estimate. Calibrated demand forecasts and future cost uncertainty still require site data and validation.

Tests reconcile components with dispatch, cover signed and varying hourly prices, compare sensitivity with full recalculation, confirm the selected plan is simulated, and prove that changed actual weather cannot leak into the forecast. Browser checks cover controls, invalid values, saved history and mobile layout.
