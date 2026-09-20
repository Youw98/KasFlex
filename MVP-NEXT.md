# KasFlex MVP: add, change, remove

Make the main workflow: **What will this greenhouse's energy cost tomorrow, what can I change, and how certain is the estimate?** Start with one Dutch greenhouse and one day ahead. Keep research experiments accessible one level deeper.

## What exists today

The energy model estimates costs from prices, weather-driven demand, gas assumptions, and hourly intent. ENTSO-E/Open-Meteo fetchers and caching already exist. The learned planner forecasts heat demand, not electricity prices or total cost; its history currently comes from synthetic weather and simulated greenhouse operation. Real input data does not validate the default surrogate greenhouse model.

## Add, in priority order

| Priority | Addition | Completion criterion |
|---|---|---|
| P0 | Complete real-data ingestion | Published Dutch prices, weather forecast vintages, site meter/asset history, and tariff/gas assumptions. Preserve source, issue time, retrieval time, timezone, units, and checksum. Never silently substitute demo data. |
| P0 | Credible next-day cost estimates | Use published prices where known and forecast demand from weather and measured site history. Show expected cost and a calibrated uncertainty range; explicitly identify unknown prices. |
| P0 | Site calibration | Compare simulated consumption with measured greenhouse data. Publish errors and replace synthetic training history before claiming a real-data-trained planner. |
| P0 | Cost breakdown | Separate grid purchases, gas, CO2, export revenue, and included contracted fees. Distinguish wholesale prices from the customer tariff. Components must reconcile to the total. |
| P0 | Versioned plans and approvals | Store plan ID, revision, input snapshot, checker verdict, and human decision together. The server must reject stale or unverified approvals. |
| P1 | Run history and reconciliation | Preserve each forecast; attach measured outcomes later without rewriting it. Show euro error, demand error, bias, and prediction-interval coverage. |
| P1 | Guided onboarding | Ask location, greenhouse size, crop targets, connected assets, initial battery/buffer states, and tariff. Save named configurations. |
| P1 | Honest savings comparison | Use identical input data, starting states, crop constraints, and low-level control for every planner. Show negative savings when optimization is worse. |
| P1 | Data health | Show stale/missing data, outages, credential status, and recovery actions. Cache safely and explicitly identify any imputation. |
| P2 | Longer horizons | Add seven-day estimates only after chronological backtesting. Separate published prices from price forecasts. Treat a 30-day view initially as a budget scenario. |

## Change

1. Put common choices in **Configuration → Basics** and research switches in **Advanced**. Explain units and assumptions in plain language.
2. Predict costs through the energy model, not by asking an LLM for a euro amount. Weather and site history predict demand; tariffs convert dispatched flows to money.
3. Separate published prices, predictions, reanalysis, and measured observations. Tomorrow's published price can be known while consumption remains uncertain.
4. Store timestamped variable-duration intervals. Preserve quarter-hour prices and negative values; handle 23/25-hour daylight-saving days. Hourly intent can remain, but costs must integrate actual interval durations.
5. Label results **Demo / Estimated / Evaluated**. Evaluation against weather reanalysis is not evaluation against a greenhouse meter.
6. Use one primary action per screen: configure, generate, inspect, record a decision, reconcile later. Put large metric tables and raw traces deeper.
7. Use rolling-origin backtests and simple baselines. Prefer a model that reliably improves demand/cost error over a more complicated model with no demonstrated benefit.

## Remove or defer

- Unconfigured language-model planners and unavailable MPC from the everyday selection path.
- Fleet coordination, national grid models, live trading, SCADA, and physical equipment control from the simulation MVP.
- Silent fabricated defaults: missing weather must not become zero, and manual gas assumptions must not be labeled live TTF prices.
- Unsupported confidence intervals, precise savings claims, and optimization claims without a baseline.
- File paths, trace controls, training seeds, and revision counts from basic setup.

## Forecasting implementation

1. Gather published prices, forecasts issued before the planning cutoff, measured site history, crop targets, initial asset state, and contract terms.
2. Establish previous-day/same-weekday demand baselines; then fit a weather/calendar regression on real history using chronological splits.
3. Simulate candidate intent plans with the same energy model and controller.
4. Sum interval imports × import tariff + gas × gas price + CO2 and explicit fees − exports × export tariff. Include battery wear only as a documented assumption.
5. Propagate weather, demand, and unknown-price scenarios through dispatch. Calibrate intervals on held-out days; do not invent an arbitrary ±10% range.
6. Save forecast issue time and model version, then compare with actual meter readings and final tariffs. Report euro MAE, bias, and interval coverage against a baseline.

## Implemented in this update

- Renamed the setup surface **Configuration** and organized it into Basics, Greenhouse, Energy system, Data sources, and Advanced.
- Added date picker, tomorrow shortcut, clearer planner choices, configuration summary, local preference saving, and cancel-without-saving behavior.
- Exposed data mode, coordinates, and the manual gas-price assumption. Existing plans retain their original settings during verification.
- Connected browser real-data mode to the cache. Missing data produces an actionable error instead of a synthetic run.
- Added availability checks with checksums/hour coverage and explicit downloads via the existing providers. Historical forecast downloads remain unavailable in the UI.
- Labeled demo output and forecast-only estimates. Gas assumption changes now affect demo costs.
- Rejected missing/non-finite weather and invalid cached-hour sequences.

## Verified and still missing

A live Open-Meteo call returned 24 hourly weather rows during this session. No ENTSO-E token is configured on this machine, so electricity acquisition and a complete live-price run could not be exercised. Configure `ENTSOE_API_KEY` in the server environment, restart, choose a date with published prices, then use **Data sources → Download for this day**. Do not put the token into the operator brief or source control.

The new cache path is tested with controlled fixtures. Predictive accuracy is not established. The learned planner still needs real training history, and this update does not add a calibrated future-price model or cost-confidence model.

## Sources checked

- [ENTSO-E token management](https://transparency.entsoe.eu/content/static_content/download?path=%2FStatic+content%2FAPI-Token-Management.pdf): registration and API access.
- [ENTSO-E SDAC](https://www.entsoe.eu/network_codes/cacm/implementation/sdac/): 15-minute market time units for delivery from 1 October 2025.
- [Open-Meteo forecast API](https://open-meteo.com/en/docs): forecast weather inputs.
- [Historical forecast documentation](https://open-meteo.com/en/docs/historical-forecast-api): the continuous archive stitches the first hours of runs. Use individual archived runs/issue times for a faithful day-ahead backtest.
