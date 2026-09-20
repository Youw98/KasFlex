"""Turn a place name or postal address into a latitude/longitude pair.

The onboarding flow needs a location to feed the weather forecast, and greenhouses
come with two very different origins:

* A commercial site in a village has a street address, which a grower knows and can
  type. Sending a grower to look up their own coordinates is friction.
* A remote or research site is in the middle of nothing, and the only sensible thing
  the grower can give is a latitude/longitude pair from a map application. Trying to
  resolve *"our polder"* to a street address will fail and shouldn't have to.

This module handles the first case. The onboarding page also accepts raw
coordinates unchanged (nothing to do), so the two branches of the "where is your
greenhouse" question stay symmetrical.

Backend: `Open-Meteo`_'s free geocoding endpoint. Free, no key required,
`CC-BY 4.0`_. The transport is :func:`kasflex.data.sources.http_get`, so
retry/timeout behaviour is shared with the rest of the fetchers and tests inject
by monkeypatching the callable.

.. _Open-Meteo: https://open-meteo.com/en/docs/geocoding-api
.. _CC-BY 4.0: https://creativecommons.org/licenses/by/4.0/
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from kasflex.data.sources import FetchError, http_get

OPENMETEO_GEOCODING = "https://geocoding-api.open-meteo.com/v1/search"


@dataclass(frozen=True)
class GeocodedPlace:
    """One geocoded match, ready to store or show back to the grower for confirmation."""

    latitude: float
    longitude: float
    name: str
    """The resolved place name Open-Meteo returned. Usually the town or municipality."""
    country: str = ""
    admin: str = ""
    """The regional context (province, state) when the backend provides one. This is
    what disambiguates *Naaldwijk* in the Netherlands from anywhere else called the same.
    """


class GeocodingError(FetchError):
    """The address could not be resolved. The message is safe to show a grower."""


def parse_openmeteo_geocoding_json(raw: str, *, query: str = "") -> GeocodedPlace:
    """Parse Open-Meteo's geocoding response and return the best match.

    Open-Meteo returns a list ordered by score; we take the first. When the list is
    empty (or the ``results`` key is absent, which Open-Meteo does rather than
    returning an empty array), raise a :class:`GeocodingError` with a message the
    onboarding page can show the grower verbatim. Coordinates outside their real
    ranges are refused rather than passed along -- that would be a malformed
    upstream response, not a lookup miss.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GeocodingError(
            f"Geocoding did not return JSON. Response: {raw[:200]!r}"
        ) from exc
    if not isinstance(payload, dict):
        raise GeocodingError("Geocoding returned a value that is not an object.")
    results = payload.get("results") or []
    if not results:
        raise GeocodingError(
            f"No place matched {query!r}. Try a nearby town, a postcode, or enter "
            f"coordinates instead."
        )
    best = results[0]
    try:
        lat = float(best["latitude"])
        lon = float(best["longitude"])
    except (KeyError, TypeError, ValueError) as exc:
        raise GeocodingError(
            "Geocoding returned a result without usable coordinates."
        ) from exc
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        raise GeocodingError(
            f"Geocoding returned coordinates outside the world ({lat}, {lon})."
        )
    return GeocodedPlace(
        latitude=lat,
        longitude=lon,
        name=str(best.get("name") or query or ""),
        country=str(best.get("country") or ""),
        admin=str(best.get("admin1") or ""),
    )


def geocode(
    query: str,
    *,
    language: str = "en",
    http_get_fn: Callable[..., str] = http_get,
    **http_kwargs: Any,
) -> GeocodedPlace:
    """Look up an address or place name and return the best matching coordinates.

    Args:
        query: what the grower typed. A place name, a village and country, or a
            postal code all work; free-form addresses ("Middel Broekweg 27, Naaldwijk")
            work well enough for the onboarding use case.
        language: the response language, so the resolved name reads back in the
            grower's own language. Defaults to English.
        http_get_fn: the transport. Left at the default it uses
            :func:`kasflex.data.sources.http_get`; tests pass a fake.
        http_kwargs: forwarded to the transport (timeout, retries).

    Raises:
        GeocodingError: for an empty query, no match, or a malformed response.
    """
    query = (query or "").strip()
    if not query:
        raise GeocodingError("Enter a place name or address to look up.")
    params = {"name": query, "count": 5, "language": language, "format": "json"}
    raw = http_get_fn(OPENMETEO_GEOCODING, params, **http_kwargs)
    return parse_openmeteo_geocoding_json(raw, query=query)
