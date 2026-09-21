"""Commercial electricity position and spot-settlement model.

Greenhouse electricity procurement is not simply "hourly spot price × consumption".
A grower commonly enters the day with a contracted/base position. The difference
between that position and the realised/planned net grid position settles against
the spot market. That creates both price risk and volume risk.

This module is deliberately small and transparent: it does not model a full trading
book. It gives the demonstrator the minimum concepts a grower expects to see.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from kasflex.energy.dispatch import DispatchResult, HourlyConditions


@dataclass(frozen=True)
class ProcurementContract:
    """Simple base-load procurement position for one day."""

    base_import_kw: float = 1800.0
    contract_price_eur_kwh: float = 0.085
    short_spread_eur_kwh: float = 0.012
    long_spread_eur_kwh: float = 0.008

    def validate(self) -> None:
        for name, value in asdict(self).items():
            if float(value) < 0:
                raise ValueError(f"{name} must be non-negative")


@dataclass(frozen=True)
class HourPosition:
    hour: int
    contracted_kw: float
    planned_net_kw: float
    deviation_kw: float
    spot_price_eur_kwh: float
    settlement_price_eur_kwh: float
    contract_cost_eur: float
    settlement_eur: float
    total_position_cost_eur: float
    direction: str

    def to_dict(self) -> dict[str, float | int | str]:
        return asdict(self)


@dataclass(frozen=True)
class PositionResult:
    hours: tuple[HourPosition, ...]
    contracted_energy_kwh: float
    planned_net_energy_kwh: float
    absolute_deviation_kwh: float
    contract_cost_eur: float
    settlement_eur: float
    total_position_cost_eur: float
    export_energy_kwh: float
    export_revenue_eur: float
    short_hours: int
    long_hours: int

    @property
    def net_direction(self) -> str:
        delta = self.planned_net_energy_kwh - self.contracted_energy_kwh
        if abs(delta) < 1e-6:
            return "flat"
        return "short" if delta > 0 else "long"

    def to_dict(self) -> dict[str, object]:
        return {
            "summary": {
                "contracted_energy_kwh": round(self.contracted_energy_kwh, 2),
                "planned_net_energy_kwh": round(self.planned_net_energy_kwh, 2),
                "absolute_deviation_kwh": round(self.absolute_deviation_kwh, 2),
                "contract_cost_eur": round(self.contract_cost_eur, 2),
                "settlement_eur": round(self.settlement_eur, 2),
                "total_position_cost_eur": round(self.total_position_cost_eur, 2),
                "export_energy_kwh": round(self.export_energy_kwh, 2),
                "export_revenue_eur": round(self.export_revenue_eur, 2),
                "short_hours": self.short_hours,
                "long_hours": self.long_hours,
                "net_direction": self.net_direction,
            },
            "hours": [hour.to_dict() for hour in self.hours],
        }


def settle_position(
    dispatch: DispatchResult,
    conditions: tuple[HourlyConditions, ...] | list[HourlyConditions],
    contract: ProcurementContract,
) -> PositionResult:
    """Settle the deviation between a base position and planned net grid use.

    Positive deviation means the site is short and must buy the difference at
    spot plus a configured spread. Negative deviation means the site is long and
    sells the surplus at spot minus a spread. One-hour planning intervals make kW
    numerically equal to kWh per interval.
    """

    contract.validate()
    if len(dispatch.intervals) != len(conditions):
        raise ValueError("dispatch and market conditions must cover the same intervals")

    hours: list[HourPosition] = []
    contracted_energy = 0.0
    planned_net_energy = 0.0
    absolute_deviation = 0.0
    contract_cost = 0.0
    settlement_total = 0.0
    export_energy = 0.0
    export_revenue = 0.0
    short_hours = 0
    long_hours = 0

    for realised, market in zip(dispatch.intervals, conditions, strict=True):
        contracted = contract.base_import_kw
        planned_net = realised.grid_net_kw
        deviation = planned_net - contracted
        spot = market.power_price_eur_kwh

        if deviation > 1e-9:
            direction = "short"
            short_hours += 1
            settlement_price = spot + contract.short_spread_eur_kwh
        elif deviation < -1e-9:
            direction = "long"
            long_hours += 1
            settlement_price = spot - contract.long_spread_eur_kwh
        else:
            direction = "flat"
            settlement_price = spot

        base_cost = contracted * contract.contract_price_eur_kwh
        settlement = deviation * settlement_price
        total = base_cost + settlement

        contracted_energy += contracted
        planned_net_energy += planned_net
        absolute_deviation += abs(deviation)
        contract_cost += base_cost
        settlement_total += settlement
        export_energy += realised.grid_export_kw
        export_revenue += realised.grid_export_kw * market.export_price

        hours.append(
            HourPosition(
                hour=realised.hour,
                contracted_kw=round(contracted, 3),
                planned_net_kw=round(planned_net, 3),
                deviation_kw=round(deviation, 3),
                spot_price_eur_kwh=round(spot, 6),
                settlement_price_eur_kwh=round(settlement_price, 6),
                contract_cost_eur=round(base_cost, 2),
                settlement_eur=round(settlement, 2),
                total_position_cost_eur=round(total, 2),
                direction=direction,
            )
        )

    return PositionResult(
        hours=tuple(hours),
        contracted_energy_kwh=contracted_energy,
        planned_net_energy_kwh=planned_net_energy,
        absolute_deviation_kwh=absolute_deviation,
        contract_cost_eur=contract_cost,
        settlement_eur=settlement_total,
        total_position_cost_eur=contract_cost + settlement_total,
        export_energy_kwh=export_energy,
        export_revenue_eur=export_revenue,
        short_hours=short_hours,
        long_hours=long_hours,
    )


__all__ = ["HourPosition", "PositionResult", "ProcurementContract", "settle_position"]
