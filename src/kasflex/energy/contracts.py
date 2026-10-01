"""Dutch grid connection contracts, as the planner sees them.

A grower's grid limit is not a goal to trade off: it is what the connection
contract allows, and the checker enforces it. What differs between contracts is
*when* how much is allowed. Since 2024-2025 Dutch network operators offer more than
the classic firm right, and greenhouses on congested regional grids increasingly
sign one of the alternatives. This module turns each contract type into hourly
import/export limits (:class:`~kasflex.energy.assets.ContractLimits`).

The time windows in each preset are examples a scenario can override, not the
terms of any particular operator's offer.

Sources:

* ACM, *Codebesluit alternatieve transportrechten* (2024): time-block right
  (tijdsblokgebonden, regional grids) and duration right (tijdsduurgebonden,
  transport in at least 85% of the hours a year, TenneT high-voltage grid),
  in force from 1 April 2025.
  https://www.acm.nl/nl/publicaties/codebesluit-alternatieve-transportrechten
* ACM, non-firm ATO, possible since 31 January 2024: no guaranteed transport; the
  operator grants capacity when the grid has room.
* ACM, capacity limitation contract (capaciteitsbeperkingscontract, CBC): a firm
  right of which the grower gives up part in announced congestion hours, for a fee.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from kasflex.energy.assets import ContractLimits


@dataclass(frozen=True)
class ContractType:
    """One kind of grid contract, described for a grower."""

    key: str
    name_en: str
    name_nl: str
    summary_en: str
    summary_nl: str

    def name(self, language: str = "en") -> str:
        return self.name_nl if language == "nl" else self.name_en

    def summary(self, language: str = "en") -> str:
        return self.summary_nl if language == "nl" else self.summary_en


CONTRACT_TYPES: dict[str, ContractType] = {
    "firm": ContractType(
        "firm", "Firm transport right", "Vast transportrecht",
        "The contracted capacity is available every hour of the year.",
        "Het gecontracteerde vermogen is elk uur van het jaar beschikbaar.",
    ),
    "cbc": ContractType(
        "cbc", "Firm with capacity limitation (CBC)",
        "Vast met capaciteitsbeperking (CBC)",
        "Firm right, but in announced congestion hours the grower uses less, for a fee.",
        "Vast recht, maar in aangekondigde congestie-uren neemt de teler minder af, "
        "tegen een vergoeding.",
    ),
    "time_block": ContractType(
        "time_block", "Time-block right", "Tijdsblokgebonden transportrecht",
        "Full capacity only inside agreed time windows; a smaller firm part outside them. "
        "Lower tariff. Regional grids, since 1 April 2025.",
        "Volledig vermogen alleen binnen afgesproken tijdsvensters; daarbuiten een kleiner "
        "vast deel. Lager tarief. Regionale netten, sinds 1 april 2025.",
    ),
    "duration": ContractType(
        "duration", "Duration right (85%)", "Tijdsduurgebonden transportrecht (85%)",
        "Transport in at least 85% of the hours a year; the operator may curtail the "
        "rest, announced a day ahead. High-voltage (TenneT) connections.",
        "Transport in minstens 85% van de uren per jaar; de rest mag de netbeheerder "
        "beperken, een dag vooraf aangekondigd. Hoogspanning (TenneT).",
    ),
    "non_firm": ContractType(
        "non_firm", "Non-firm right", "Niet-vast transportrecht (non-firm)",
        "No guaranteed transport: the operator announces each day how much is available.",
        "Geen gegarandeerd transport: de netbeheerder meldt per dag hoeveel er kan.",
    ),
}

#: Hours the time-block preset grants full capacity: night and the solar midday,
#: the two periods regional grids in the Westland usually have room.
TIME_BLOCK_HOURS = (0, 1, 2, 3, 4, 5, 6, 10, 11, 12, 13, 14, 22, 23)
#: Share of the contracted capacity that stays firm outside the time blocks.
TIME_BLOCK_FIRM_SHARE = 0.5
#: Hours a duration-right connection is curtailed on this day (an evening peak).
DURATION_CURTAILED_HOURS = (17, 18, 19)
#: Share of capacity a non-firm connection gets in each hour (the day-ahead
#: announcement). Tight in the evening peak, generous at night.
NON_FIRM_PROFILE = (
    1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.9, 0.7, 0.6, 0.6, 0.7, 0.8,
    0.8, 0.8, 0.7, 0.6, 0.4, 0.3, 0.3, 0.4, 0.6, 0.8, 1.0, 1.0,
)


def contract_limits(base: ContractLimits, kind: str) -> ContractLimits:
    """Return the hourly limits a contract type implies, starting from ``base``.

    ``base.import_limit_kw`` and ``export_limit_kw`` are the contracted capacity.
    ``cbc`` keeps the scenario's own congestion windows; ``firm`` drops them.
    """
    if kind not in CONTRACT_TYPES:
        raise ValueError(f"unknown grid contract type {kind!r}; one of {sorted(CONTRACT_TYPES)}")
    imp, exp = base.import_limit_kw, base.export_limit_kw
    if kind == "cbc":
        return base
    if kind == "firm":
        return dataclasses.replace(base, congestion_windows={})
    if kind == "time_block":
        windows = {
            hour: (imp * TIME_BLOCK_FIRM_SHARE, exp * TIME_BLOCK_FIRM_SHARE)
            for hour in range(24) if hour not in TIME_BLOCK_HOURS
        }
        return dataclasses.replace(base, congestion_windows=windows)
    if kind == "duration":
        return dataclasses.replace(
            base, congestion_windows={hour: (0.0, 0.0) for hour in DURATION_CURTAILED_HOURS})
    windows = {
        hour: (imp * share, exp * share)
        for hour, share in enumerate(NON_FIRM_PROFILE) if share < 1.0
    }
    return dataclasses.replace(base, congestion_windows=windows)


def describe(kind: str, language: str = "en") -> dict[str, str]:
    contract = CONTRACT_TYPES[kind]
    return {"key": kind, "name": contract.name(language), "summary": contract.summary(language)}


__all__ = ["CONTRACT_TYPES", "ContractType", "contract_limits", "describe"]
