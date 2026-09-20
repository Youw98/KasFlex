"""The bundled validation must execute the simulator, not print NaN placeholders."""

import math

from kasflex.validation import validate_bundled_reference


def test_bundled_agc_reference_days_are_actually_simulated():
    report = validate_bundled_reference()

    assert report.days_compared == 3
    assert report.model == "surrogate-v1"
    assert report.status == "quantified-not-calibrated"
    assert all(math.isfinite(item.simulated) for item in report.deviations)
    assert report.aggregate["temperature_c"]["samples"] == 72
    assert report.aggregate["heating_kwh"]["samples"] == 3
    assert report.provenance["licence"] == "CC0-1.0"


def test_a_single_predeclared_day_can_be_replayed():
    report = validate_bundled_reference(days=("2020-05-27",))

    assert report.days_compared == 1
    assert {item.date for item in report.deviations} == {"2020-05-27"}
    assert report.aggregate["temperature_c"]["samples"] == 24
