"""Parse Open-Meteo geocoding responses and surface useful errors.

The HTTP call itself is not exercised here -- the build environment blocks
api.open-meteo.com, and the fetchers in ``kasflex.data.sources`` are already
under that regime. Everything from the response onwards is testable, and this
suite covers the traps: an empty result set, malformed JSON, obviously wrong
coordinates, and the plain happy path.
"""

from __future__ import annotations

import json

import pytest

from kasflex.data.geocode import (
    GeocodedPlace,
    GeocodingError,
    geocode,
    parse_openmeteo_geocoding_json,
)


def _payload(*results: dict) -> str:
    return json.dumps({"results": list(results), "generationtime_ms": 0.2})


def test_returns_the_best_match():
    raw = _payload(
        {"name": "Naaldwijk", "latitude": 51.994, "longitude": 4.207,
         "country": "Netherlands", "admin1": "South Holland"},
        {"name": "Naaldwijk", "latitude": 53.0, "longitude": 5.0,
         "country": "Netherlands"},
    )
    place = parse_openmeteo_geocoding_json(raw, query="Naaldwijk")
    assert isinstance(place, GeocodedPlace)
    assert place.name == "Naaldwijk"
    assert place.latitude == pytest.approx(51.994)
    assert place.longitude == pytest.approx(4.207)
    assert place.country == "Netherlands"
    assert place.admin == "South Holland"


def test_empty_results_are_explained_not_returned_as_null_island():
    """Open-Meteo returns {} when nothing matches. Silently defaulting to 0,0 would
    put every unrecognised query in the Gulf of Guinea; the message must instead
    tell the grower to try another form of the query.
    """
    with pytest.raises(GeocodingError, match="No place matched"):
        parse_openmeteo_geocoding_json("{}", query="qqq-does-not-exist")
    with pytest.raises(GeocodingError, match="No place matched"):
        parse_openmeteo_geocoding_json(_payload(), query="qqq-does-not-exist")


def test_a_non_json_response_is_named_as_such():
    """A 502 HTML page from a proxy is a common trap; the error message quotes the
    start of the response so an operator can see what actually came back."""
    with pytest.raises(GeocodingError, match="did not return JSON"):
        parse_openmeteo_geocoding_json("<html>503 Service Unavailable</html>")


def test_coordinates_off_the_planet_are_refused():
    """A backend returning lat=1000 is a bug we do not want to propagate into a
    weather request. Refuse it rather than clip: clipping silently coerces bad
    data into a plausible-looking site."""
    with pytest.raises(GeocodingError, match="outside the world"):
        parse_openmeteo_geocoding_json(
            _payload({"name": "Nowhere", "latitude": 1000.0, "longitude": 0.0}))


def test_a_result_without_coordinates_is_refused():
    with pytest.raises(GeocodingError, match="without usable coordinates"):
        parse_openmeteo_geocoding_json(_payload({"name": "Anywhere"}))


def test_geocode_rejects_empty_input():
    with pytest.raises(GeocodingError, match="Enter a place name"):
        geocode("")
    with pytest.raises(GeocodingError, match="Enter a place name"):
        geocode("   ")


def test_geocode_uses_the_injected_transport(monkeypatch):
    """The endpoint takes a callable so the UI server and the tests never make a
    real HTTP call; monkeypatching the transport is enough."""
    captured: dict = {}

    def fake_transport(url, params, **_):
        captured["url"] = url
        captured["params"] = dict(params)
        return _payload({"name": "Wageningen", "latitude": 51.97, "longitude": 5.66,
                         "country": "Netherlands"})

    place = geocode("Wageningen", http_get_fn=fake_transport, language="nl")
    assert place.name == "Wageningen"
    assert captured["params"]["name"] == "Wageningen"
    assert captured["params"]["language"] == "nl"
    assert "geocoding-api.open-meteo.com" in captured["url"]
