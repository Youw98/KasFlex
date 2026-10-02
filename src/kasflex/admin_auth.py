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

import hashlib
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


#: Wrong passwords allowed within :data:`LOCKOUT_SECONDS` before logins pause.
MAX_FAILURES = 5
LOCKOUT_SECONDS = 300


class AdminGate:
    """Hands out tokens for the right password and checks them.

    After :data:`MAX_FAILURES` wrong passwords within :data:`LOCKOUT_SECONDS`, every
    login is refused until the window passes: a short password otherwise falls to
    a script in minutes, since the server answers requests in parallel.
    """

    def __init__(self) -> None:
        self._tokens: dict[str, float] = {}
        self._failures: list[float] = []

    def locked_out(self) -> bool:
        now = time.time()
        self._failures = [t for t in self._failures if now - t < LOCKOUT_SECONDS]
        return len(self._failures) >= MAX_FAILURES

    def login(self, password: str) -> str | None:
        if self.locked_out():
            return None
        if not hmac.compare_digest(str(password or "").encode(), admin_password().encode()):
            self._failures.append(time.time())
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


class ConsentKeys:
    """One withdrawal key per participant, handed out when they consent.

    Withdrawing consent erases a participant's data, so it must not be possible
    for one participant to do it for another by guessing a pseudonym like "P002".
    The key is shown once to the participant's browser and only its hash is kept.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _load(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _hash(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()

    def issue(self, participant: str) -> str:
        key = secrets.token_urlsafe(18)
        data = self._load()
        data[str(participant)] = self._hash(key)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return key

    def has(self, participant: str) -> bool:
        return str(participant) in self._load()

    def check(self, participant: str, key: str) -> bool:
        stored = self._load().get(str(participant))
        return bool(stored and key) and hmac.compare_digest(stored, self._hash(key))


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


__all__ = ["HEADER", "SITE_FIELDS", "AdminGate", "ConsentKeys", "SiteSettings",
           "admin_password"]
