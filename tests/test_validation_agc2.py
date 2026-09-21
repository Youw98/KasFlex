from __future__ import annotations

import math
from datetime import date

import pytest

from kasflex.validation_agc2 import (
    REFERENCE_AREA_M2,
    _measured_totals,
    excel_datetime,
    select_days,
    sky_temperature_c,
)


def test_excel_serial_is_snapped_to_official_five_minute_grid():
    assert excel_datetime("43815.00347").isoformat() == "2019-12-16T00:05:00"


def test_official_resource_units_are_converted_to_compartment_totals():
    totals = _measured_totals({"Heat_cons": 3.6, "ElecHigh": 1.0, "ElecLow": 0.5, "CO2_cons": 0.01})
    assert totals == {
        "heating_kwh": pytest.approx(REFERENCE_AREA_M2),
        "electricity_kwh": pytest.approx(144.0),
        "co2_kg": pytest.approx(0.96),
    }


def test_day_sample_uses_heating_quantiles_not_cherry_picked_dates():
    days = [date(2020, 1, number) for number in range(1, 6)]
    resources = {day: {"Heat_cons": float(index)} for index, day in enumerate(days)}
    assert select_days(resources, reversed(days), 3) == [days[0], days[2], days[4]]


def test_sky_temperature_from_net_longwave_is_physical():
    sky = sky_temperature_c(outdoor_c=10.0, net_longwave_w_m2=-70.0)
    assert math.isfinite(sky)
    assert sky < 10.0
