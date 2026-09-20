"""Conditional daily cost projection, using forecast inputs only.

This is accounting for a fixed plan, not a calibrated probabilistic forecast.
Hourly prices remain signed, including payments for import at negative prices.
"""
from __future__ import annotations

from dataclasses import replace

from kasflex.energy.dispatch import dispatch_plan


def project_cost(plan, hub, forecast, greenhouse) -> dict:
    """Simulate this plan's forecast demand and reconcile each cost component.

    Actual weather is deliberately absent from the interface. Price sensitivity
    uses fixed dispatch volumes; it does not re-optimise or predict market prices.
    """
    outcome = greenhouse.simulate_day(plan, tuple(forecast), hub.floor_area_m2)
    conditions = [replace(c, heat_demand_kw=outcome.heat_demand_kw[i],
                          co2_demand_kg_h=outcome.co2_demand_kg_h[i])
                  for i, c in enumerate(forecast)]
    dispatch = dispatch_plan(plan, hub, conditions)
    hourly = []
    for iv, c in zip(dispatch.intervals, conditions, strict=True):
        hourly.append({
            "hour": iv.hour,
            "import_kwh": iv.grid_import_kw,
            "export_kwh": iv.grid_export_kw,
            "gas_kwh": iv.gas_input_kw,
            "electricity_import_eur": iv.grid_import_kw * c.power_price_eur_kwh,
            "gas_eur": iv.gas_input_kw * c.gas_price_eur_kwh,
            "export_revenue_eur": iv.grid_export_kw * c.export_price,
            "liquid_co2_eur": iv.co2_liquid_kg * 0.30,
            "net_cost_eur": iv.energy_cost_eur,
        })
    totals = {key: sum(row[key] for row in hourly) for key in hourly[0] if key != "hour"}
    return {"basis": "forecast-only", "method": "fixed-plan-dispatch",
            "model": outcome.model, "validated": outcome.validated,
            "totals": totals, "hourly": hourly,
            "excludes": ["taxes", "grid tariffs", "supplier fees", "capital costs",
                         "maintenance", "crop sales"],
            "assumptions": {"liquid_co2_eur_kg": 0.30,
                            "price_sensitivity": "Fixed volumes; equal electricity price shift "
                                                 "for import and export."}}
