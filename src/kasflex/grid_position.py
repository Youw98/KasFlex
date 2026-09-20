"""Commercial grid-position accounting for one daily greenhouse plan."""

from __future__ import annotations

from typing import Any


def position(contract, cost_forecast: dict[str, Any]) -> dict[str, Any]:
    """Reconcile contracted volume, planned net offtake and spot settlement.

    This is planning support, not a live imbalance-market invoice.
    """
    totals = cost_forecast.get("totals") or {}
    hourly = cost_forecast.get("hourly") or []
    imported = float(totals.get("import_kwh", 0.0))
    exported = float(totals.get("export_kwh", 0.0))
    actual = imported - exported
    contracted = float(contract.contracted_base_volume_kwh)
    deviation = actual - contracted
    electricity_cost = sum(
        float(row.get("electricity_import_eur", 0.0))
        - float(row.get("export_revenue_eur", 0.0))
        for row in hourly
    )
    spot = electricity_cost / max(abs(actual), 1.0)
    settlement_price = spot + (contract.imbalance_spread_eur_kwh if deviation >= 0 else
                               -contract.imbalance_spread_eur_kwh)
    settlement = deviation * settlement_price
    return {
        "contracted_kwh": round(contracted, 2),
        "planned_net_kwh": round(actual, 2),
        "deviation_kwh": round(deviation, 2),
        "position": "short" if deviation > 1 else "long" if deviation < -1 else "balanced",
        "contract_price_eur_kwh": round(contract.contracted_price_eur_kwh, 5),
        "weighted_spot_eur_kwh": round(spot, 5),
        "settlement_price_eur_kwh": round(settlement_price, 5),
        "contracted_cost_eur": round(contracted * contract.contracted_price_eur_kwh, 2),
        "deviation_settlement_eur": round(settlement, 2),
        "price_risk_eur": round(contracted * (spot - contract.contracted_price_eur_kwh), 2),
        "volume_risk_eur": round(settlement, 2),
        "export_kwh": round(exported, 2),
        "export_revenue_eur": round(float(totals.get("export_revenue_eur", 0.0)), 2),
        "method": "planned fixed-volume settlement; illustrative, not supplier invoicing",
    }
