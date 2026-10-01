"""The settings lock and the site settings it guards.

Growers use the planning screen; the researcher changes how the site is set up
(AI service and model, API keys, grid contract, installation, the workshop). Those
changes sit behind a password so a participant cannot switch the AI or the study
version mid-session. The password is checked on the server, never only in the
page: the page asks for it, the server hands out a short-lived token, and every
settings request must carry that token.

The default password is ``admin99``. Set ``KASFLEX_ADMIN_PASSWORD`` to change it.
This is a lock against accidental or curious changes on a local workshop laptop,
not protection against someone with access to the computer itself.

Site settings are a small, validated subset of the adjustable fields, saved as
JSON and applied on top of the scenario file every time the server starts.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

DEFAULT_PASSWORD = "admin99"
TOKEN_SECONDS = 8 * 3600
HEADER = "X-KasFlex-Admin"

#: The fields the settings menu may change, by their path in the scenario config.
SITE_FIELDS: tuple[str, ...] = (
    "llm_provider",
    "llm_model",
    "llm_base_url",
    "grid_contract_type",
    "hub.contract.import_limit_kw",
    "hub.contract.export_limit_kw",
    "hub.battery.capacity_kwh",
    "hub.chp.electrical_capacity_kw",
    "gas_price_eur_kwh",
    "grid_peak_value_eur_per_kw",
)


def admin_password() -> str:
    return os.environ.get("KASFLEX_ADMIN_PASSWORD") or DEFAULT_PASSWORD


class AdminGate:
    """Hands out tokens for the right password and checks them."""

    def __init__(self) -> None:
        self._tokens: dict[str, float] = {}

    def login(self, password: str) -> str | None:
        if not hmac.compare_digest(str(password or "").encode(), admin_password().encode()):
            return None
        now = time.time()
        self._tokens = {t: exp for t, exp in self._tokens.items() if exp > now}
        token = secrets.token_urlsafe(24)
        self._tokens[token] = now + TOKEN_SECONDS
        return token

    def check(self, token: str | None) -> bool:
        expiry = self._tokens.get(str(token or ""))
        if expiry is None:
            return False
        if expiry < time.time():
            self._tokens.pop(str(token), None)
            return False
        return True

    def logout(self, token: str | None) -> None:
        self._tokens.pop(str(token or ""), None)


class SiteSettings:
    """The saved values for :data:`SITE_FIELDS`."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def get(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {k: v for k, v in data.items() if k in SITE_FIELDS} if isinstance(data, dict) else {}

    def save(self, values: dict[str, Any]) -> dict[str, Any]:
        merged = self.get()
        for key, value in values.items():
            if key not in SITE_FIELDS:
                raise ValueError(f"{key} cannot be changed from the settings menu.")
            if value in (None, ""):
                merged.pop(key, None)
            else:
                merged[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
        return merged


__all__ = ["HEADER", "SITE_FIELDS", "AdminGate", "SiteSettings", "admin_password"]
