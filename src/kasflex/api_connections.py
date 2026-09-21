"""Local credential storage. API responses contain status, never secret values.

Two kinds of credential live here: the ENTSO-E token that fetches electricity
prices, and the key for whichever model vendor explains plans to the grower. Both
are written to one ``.env`` file beside the application, with file permissions
tightened, and neither is ever returned by the API -- the interface is told
*whether* a key is configured, never what it is.

Only keys named in :data:`ALLOWED` can be written. An allowlist rather than a
pattern match, because this function takes input from a web request and writes it
to a file that is later sourced into the environment.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from kasflex.llm_providers import PROVIDERS

ENTSOE_KEY = "ENTSOE_API_KEY"

TEMPLATE = """# KasFlex local API configuration. Never commit or share this file.
# Paste your personal ENTSO-E token here, or save it in Configuration > APIs.
# Prices endpoint: https://web-api.tp.entsoe.eu/api
ENTSOE_API_KEY=

# Open-Meteo public weather endpoints do not require a key:
# https://api.open-meteo.com/v1/forecast
# https://archive-api.open-meteo.com/v1/archive

# AI model keys are written below when you save one in Configuration > AI model.
"""

DATA_CONNECTIONS = (
    {"id": "entsoe", "name": "ENTSO-E", "purpose": "Dutch electricity prices",
     "endpoint": "https://web-api.tp.entsoe.eu/api", "requires_key": True,
     "env_var": ENTSOE_KEY, "kind": "data",
     "help_url": "https://transparency.entsoe.eu/"},
    {"id": "weather", "name": "Open-Meteo Forecast", "purpose": "Forecast weather",
     "endpoint": "https://api.open-meteo.com/v1/forecast", "requires_key": False,
     "env_var": "", "kind": "data", "help_url": "https://open-meteo.com/en/docs"},
    {"id": "reanalysis", "name": "Open-Meteo Historical Weather",
     "purpose": "Weather reanalysis for past days",
     "endpoint": "https://archive-api.open-meteo.com/v1/archive",
     "requires_key": False, "env_var": "", "kind": "data",
     "help_url": "https://open-meteo.com/en/docs/historical-weather-api"},
)


def _allowed() -> dict[str, str]:
    """Provider id -> environment variable, for everything that may be written."""
    allowed = {"entsoe": ENTSOE_KEY}
    for provider in PROVIDERS.values():
        if provider.env_var:
            allowed[provider.id] = provider.env_var
        if provider.base_url_env:
            allowed[f"{provider.id}:base_url"] = provider.base_url_env
    return allowed


ALLOWED = _allowed()


class ApiConnections:
    """Manage the credentials the local application is allowed to store."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(TEMPLATE, encoding="utf-8")
            self.path.chmod(0o600)
        self.load()

    def load(self) -> None:
        """Load only supported keys; inherited environment values take precedence."""
        writable = set(ALLOWED.values())
        for line in self.path.read_text(encoding="utf-8-sig").splitlines():
            key, sep, value = line.strip().partition("=")
            if not sep or key not in writable:
                continue
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
        """Which connections are configured. Never the values themselves."""
        connections = [
            {**entry, "configured": (not entry["env_var"]
                                     or bool(os.environ.get(entry["env_var"])))}
            for entry in DATA_CONNECTIONS
        ]
        models = [
            {"id": p.id, "name": p.name, "purpose": p.purpose, "kind": "model",
             "endpoint": p.endpoint, "requires_key": bool(p.env_var),
             "env_var": p.env_var, "local": p.local, "notes": p.notes,
             "models": list(p.models), "help_url": p.help_url,
             "base_url_env": p.base_url_env,
             "base_url": os.environ.get(p.base_url_env, "") if p.base_url_env else "",
             "configured": (not p.env_var or bool(os.environ.get(p.env_var)))}
            for p in PROVIDERS.values()
        ]
        return {"connections": connections, "models": models,
                "storage": "Local .env file", "secrets_returned": False}

    def save(self, provider: str, value: str, remove: bool = False) -> dict:
        """Write one credential to the local ``.env``.

        Raises:
            ValueError: for an unknown provider, or a value that could inject a
                second assignment into the file.
        """
        key = ALLOWED.get(provider)
        if key is None:
            raise ValueError("This provider does not accept an API key.")
        if not isinstance(value, str):
            raise ValueError("Enter a valid API key.")
        value = value.strip()
        if not remove and not value:
            raise ValueError("Enter a key to save. Use Remove key to disconnect.")
        is_url = provider.endswith(":base_url")
        if len(value) > 2048:
            raise ValueError("That value is too long.")
        # A newline would end the assignment and start another; a space or a control
        # character means this is not a key. URLs get the same treatment: they are
        # written to the same file and read back the same way.
        if any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError(
                f"The {'address' if is_url else 'API key'} must be one line with no spaces.")

        lines = self.path.read_text(encoding="utf-8-sig").splitlines()
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
