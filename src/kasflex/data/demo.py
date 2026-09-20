"""Prepare the one-click demo from real, traceable historical inputs."""

from __future__ import annotations

from dataclasses import dataclass

from kasflex.data.cache import DataCache
from kasflex.data.sources import (
    OPENMETEO_ARCHIVE_META,
    OPENMETEO_HISTORICAL_FORECAST_META,
    PUBLIC_DEMO_PRICE_META,
    FetchError,
    fetch_openmeteo,
    fetch_openmeteo_historical_forecast,
    fetch_public_demo_prices,
)


@dataclass(frozen=True)
class DemoPrepared:
    date: str
    price_key: str
    forecast_key: str
    actual_key: str | None
    reused_cache: bool


def _latest_cached_demo(cache: DataCache, latitude: float, longitude: float) -> str | None:
    site = f"{latitude:.3f}_{longitude:.3f}"
    dates = []
    for key, entry in cache.entries().items():
        if not key.startswith("entsoe_da_"):
            continue
        if entry.extra.get("kasflex_demo") is not True:
            continue
        day = key.removeprefix("entsoe_da_")
        if cache.has(f"weather_forecast_{day}_{site}"):
            dates.append(day)
    return max(dates) if dates else None


def prepare_real_demo(
    *,
    cache: DataCache | None = None,
    latitude: float,
    longitude: float,
    allow_network: bool = True,
) -> DemoPrepared:
    """Prepare or reuse a historical demo day with real external inputs."""
    cache = cache or DataCache()
    cached = _latest_cached_demo(cache, latitude, longitude)
    if cached:
        site = f"{latitude:.3f}_{longitude:.3f}"
        actual_key = f"weather_actual_{cached}_{site}"
        return DemoPrepared(
            date=cached,
            price_key=f"entsoe_da_{cached}",
            forecast_key=f"weather_forecast_{cached}_{site}",
            actual_key=actual_key if cache.has(actual_key) else None,
            reused_cache=True,
        )

    if not allow_network:
        raise FetchError("no prepared real-input demo is cached")

    day, prices = fetch_public_demo_prices()
    iso = day.isoformat()
    site = f"{latitude:.3f}_{longitude:.3f}"
    price_key = f"entsoe_da_{iso}"
    forecast_key = f"weather_forecast_{iso}_{site}"
    actual_key = f"weather_actual_{iso}_{site}"

    cache.put(
        price_key,
        prices,
        source=PUBLIC_DEMO_PRICE_META.source,
        licence=PUBLIC_DEMO_PRICE_META.licence,
        dataset_key=PUBLIC_DEMO_PRICE_META.dataset_key,
        notes="One-click demo: real ENTSO-E-derived Dutch day-ahead prices.",
        prefer_parquet=False,
    )
    manifest = cache._load_manifest()
    manifest[price_key]["extra"] = {
        **manifest[price_key].get("extra", {}),
        "kasflex_demo": True,
        "demo_role": "market_input",
    }
    cache._save_manifest(manifest)

    forecast = fetch_openmeteo_historical_forecast(
        day, latitude=latitude, longitude=longitude
    )
    cache.put(
        forecast_key,
        forecast,
        source=OPENMETEO_HISTORICAL_FORECAST_META.source,
        licence=OPENMETEO_HISTORICAL_FORECAST_META.licence,
        dataset_key=OPENMETEO_HISTORICAL_FORECAST_META.dataset_key,
        notes="Archived forecast shown to the demo planner.",
        prefer_parquet=False,
    )

    realised_key = None
    try:
        actual = fetch_openmeteo(
            day, latitude=latitude, longitude=longitude, archive=True
        )
    except FetchError:
        actual = None
    if actual:
        cache.put(
            actual_key,
            actual,
            source=OPENMETEO_ARCHIVE_META.source,
            licence=OPENMETEO_ARCHIVE_META.licence,
            dataset_key=OPENMETEO_ARCHIVE_META.dataset_key,
            notes="Realised weather used only for evaluation.",
            prefer_parquet=False,
        )
        realised_key = actual_key

    return DemoPrepared(
        date=iso,
        price_key=price_key,
        forecast_key=forecast_key,
        actual_key=realised_key,
        reused_cache=False,
    )
