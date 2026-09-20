from __future__ import annotations

from kasflex.energy.assets import EnergyHub
from kasflex.energy.dispatch import HourlyConditions, dispatch_plan
from kasflex.energy.position import ProcurementContract, settle_position
from kasflex.intent import IntervalIntent, Plan


def _plan() -> Plan:
    intervals = tuple(
        IntervalIntent(
            hour=hour,
            lighting_level=0.0,
            heat_source="boiler",
            battery="idle",
            battery_power_kw=0.0,
            chp_mode="off",
            co2_source="liquid",
        )
        for hour in range(24)
    )
    return Plan(date="2026-09-20", planner="test", intervals=intervals)


def test_position_settlement_distinguishes_contract_and_deviation():
    hub = EnergyHub(base_load_kw=1000.0)
    conditions = tuple(
        HourlyConditions(hour=h, power_price_eur_kwh=0.12, gas_price_eur_kwh=0.03)
        for h in range(24)
    )
    dispatch = dispatch_plan(_plan(), hub, list(conditions))
    result = settle_position(
        dispatch,
        conditions,
        ProcurementContract(
            base_import_kw=800.0,
            contract_price_eur_kwh=0.08,
            short_spread_eur_kwh=0.01,
            long_spread_eur_kwh=0.01,
        ),
    )
    payload = result.to_dict()
    assert payload["summary"]["short_hours"] == 24
    assert payload["summary"]["long_hours"] == 0
    assert payload["summary"]["contracted_energy_kwh"] == 19200.0
    assert payload["summary"]["planned_net_energy_kwh"] > 19200.0
    assert payload["summary"]["settlement_eur"] > 0


def test_long_position_receives_spot_credit():
    hub = EnergyHub(base_load_kw=100.0)
    conditions = tuple(
        HourlyConditions(hour=h, power_price_eur_kwh=0.10, gas_price_eur_kwh=0.03)
        for h in range(24)
    )
    dispatch = dispatch_plan(_plan(), hub, list(conditions))
    result = settle_position(
        dispatch,
        conditions,
        ProcurementContract(base_import_kw=500.0, contract_price_eur_kwh=0.08),
    )
    assert result.long_hours == 24
    assert result.settlement_eur < 0
    assert result.net_direction == "long"
