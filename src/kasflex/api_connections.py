"""Local credential storage. API responses contain status, never secret values."""
from __future__ import annotations

import json
import os
from pathlib import Path

TEMPLATE = """# KasFlex local API configuration. Never commit or share this file.
# Paste your personal ENTSO-E token here, or save it in Configuration > APIs.
# Prices endpoint: https://web-api.tp.entsoe.eu/api
ENTSOE_API_KEY=

# Open-Meteo public weather endpoints do not require a key:
# https://api.open-meteo.com/v1/forecast
# https://archive-api.open-meteo.com/v1/archive
"""


class ApiConnections:
    """Manage the credential supported by the live electricity connector."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(TEMPLATE, encoding="utf-8")
            self.path.chmod(0o600)
        self.load()

    def load(self) -> None:
        """Load only supported keys; inherited environment values take precedence."""
        for line in self.path.read_text(encoding="utf-8-sig").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key == "ENTSOE_API_KEY":
                value = value.strip()
                if value.startswith('"'):
                    try:
                        value = json.loads(value)
                    except (ValueError, TypeError):
                        continue
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                if isinstance(value, str) and value and not os.environ.get(key):
                    os.environ[key] = value

    def status(self) -> dict:
        return {"connections": [
            {"id": "entsoe", "name": "ENTSO-E", "purpose": "Dutch electricity prices",
             "endpoint": "https://web-api.tp.entsoe.eu/api", "requires_key": True,
             "configured": bool(os.environ.get("ENTSOE_API_KEY")),
             "help_url": "https://transparency.entsoe.eu/"},
            {"id": "weather", "name": "Open-Meteo Forecast", "purpose": "Forecast weather",
             "endpoint": "https://api.open-meteo.com/v1/forecast", "requires_key": False,
             "configured": True, "help_url": "https://open-meteo.com/en/docs"},
            {"id": "reanalysis", "name": "Open-Meteo Historical Weather",
             "purpose": "Weather reanalysis for past days",
             "endpoint": "https://archive-api.open-meteo.com/v1/archive",
             "requires_key": False, "configured": True,
             "help_url": "https://open-meteo.com/en/docs/historical-weather-api"},
        ], "storage": "Local .env file", "secrets_returned": False}

    def save(self, provider: str, value: str, remove: bool = False) -> dict:
        if provider != "entsoe":
            raise ValueError("This provider does not accept an API key.")
        if not isinstance(value, str):
            raise ValueError("Enter a valid API key.")
        value = value.strip()
        if not remove and not value:
            raise ValueError("Enter a key to save. Use Remove key to disconnect.")
        if len(value) > 2048 or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("The API key must be one line with no spaces.")
        key = "ENTSOE_API_KEY"
        lines = self.path.read_text(encoding="utf-8-sig").splitlines()
        # Preserve unrelated settings and comments; replace all copies of this key.
        lines = [line for line in lines if line.strip().partition("=")[0] != key]
        lines.append(f"{key}=" + ("" if remove else json.dumps(value)))
        temporary = self.path.with_name(self.path.name + ".tmp")
        try:
            temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
            temporary.chmod(0o600)
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
        if remove:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
        return self.status()
