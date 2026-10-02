from __future__ import annotations

import math
from datetime import date

import pytest

from kasflex.validation_agc2 import (
    AGC2_CALIBRATION,
    AGC2_LAMP_POWER_W_M2,
    REFERENCE_AREA_M2,
    _lamp_fraction,
    _measured_totals,
    excel_datetime,
    prepare_agc2,
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


def _day_rows(**columns):
    start = excel_datetime("43903")  # 2020-03-13 00:00
    from datetime import timedelta

    return [
        (start + timedelta(minutes=5 * i), {k: str(v) for k, v in columns.items()})
        for i in range(288)
    ]


def test_lamp_power_follows_each_dimmed_led_channel():
    """The LEDs were dimmable per channel. Treating the HPS state as the state of
    every lamp put all LEDs at full power and overstated electricity and heat."""
    rows = _day_rows(AssimLight=100, int_blue_vip=0, int_red_vip=500,
                     int_farred_vip=0, int_white_vip=1000)
    expected = (81.0 + 25.3 * 0.5 + 22.72) / AGC2_LAMP_POWER_W_M2
    assert _lamp_fraction(rows) == pytest.approx([expected] * 96)


def test_leds_are_off_when_the_hps_is_off_and_full_when_unrecorded():
    off = _day_rows(AssimLight=0, int_blue_vip=1000, int_red_vip=1000,
                    int_farred_vip=1000, int_white_vip=1000)
    assert _lamp_fraction(off) == pytest.approx([0.0] * 96)
    unknown = _day_rows(AssimLight=100, int_blue_vip="NaN", int_red_vip="",
                        int_farred_vip="NaN", int_white_vip="NaN")
    assert _lamp_fraction(unknown) == pytest.approx([1.0] * 96)


def test_unknown_compartment_is_refused(tmp_path):
    with pytest.raises(ValueError, match="unknown AGC2 compartment"):
        prepare_agc2(tmp_path, tmp_path, compartment="Greenhouse7")


def test_missing_compartment_files_name_the_compartment(tmp_path):
    with pytest.raises(FileNotFoundError, match="AICU"):
        prepare_agc2(tmp_path, tmp_path, compartment="AICU")


def test_calibration_keeps_lamp_heat_inside_the_greenhouse():
    """gl-gym's LED default removes 63% of lamp power by active cooling. AGC2
    lamps are HPS plus uncooled LEDs, so that heat must stay in the model."""
    assert AGC2_CALIBRATION["etaLampCool"] == 0.0
    assert set(AGC2_CALIBRATION) == {"etaLampCool", "aCov", "aRoof", "cLeakage", "tauRfNir",
                                     "kThScr", "tauThScrFir"}


def test_measured_indoor_temperature_is_kept_for_scoring_not_as_a_control(tmp_path):
    """The calibration compares simulated and measured indoor air temperature, so
    the replay carries it, but never among the controls that drive the model."""
    from kasflex.validation_agc2 import _replay_payload

    climate = _day_rows(Tair=21.5, Rhair=80, CO2air=600, t_heat_vip=18, co2_vip=800,
                        AssimLight=0, EnScr=0, BlackScr=0, VentLee=0, Ventwind=0,
                        int_blue_vip=0, int_red_vip=0, int_farred_vip=0, int_white_vip=0)
    weather = _day_rows(Iglob=0, Tout=5, Rhout=90, Windsp=2, Pyrgeo=-50)
    payload = _replay_payload(date(2020, 3, 13), climate, weather, tmp_path / "w" / "B")
    assert payload["measured_indoor"]["temperature_c"] == pytest.approx([21.5] * 24)
    assert "measured_indoor" not in payload["replay_controls"]
