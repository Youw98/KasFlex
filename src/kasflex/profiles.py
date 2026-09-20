"""Saved greenhouse setups, so nobody is asked the same questions twice.

A grower configures their site once. Everything after that -- a new laptop, a
reinstall, the demonstration machine at a field day -- should start from what they
already told us, not from an empty form. Profiles are that memory.

Two storage routes, deliberately:

* **On this computer**, under the application's own directory, listed at startup.
* **In a file**, which the grower can copy to a USB stick or email to an advisor.

The file is plain JSON with a version marker. It is data a person might open and
read, so it is formatted for reading, and loading one validates every field rather
than trusting it -- a profile from a stranger's USB stick is untrusted input like
any other.
"""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROFILE_VERSION = 1
FILE_MARKER = "kasflex.profile"
MAX_PROFILE_BYTES = 256 * 1024
"""A setup is a few kilobytes. Anything larger is a mistake or an attack."""

SAFE_KEYS = {
    "name", "date", "language", "planner", "data_source", "winter", "seed", "brief",
    "latitude", "longitude", "entsoe_zone", "gas_price_eur_kwh", "history_days",
    "llm_provider", "llm_model", "llm_base_url", "greenhouse",
}
"""Scenario fields a profile may carry. Paths and secrets are deliberately absent:
a profile must never move an API key or a filesystem location between machines."""

SAFE_KEY_PREFIXES = ("hub.", "checker.")
"""Dotted override paths a profile may carry, matching the UI's override format."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def slugify(name: str) -> str:
    """A filename-safe stem that still resembles what the grower typed."""
    normalised = unicodedata.normalize("NFKD", name)
    ascii_only = normalised.encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return slug[:48] or "profile"


def _is_allowed(key: str) -> bool:
    return key in SAFE_KEYS or any(key.startswith(p) for p in SAFE_KEY_PREFIXES)


def sanitise_settings(raw: Any) -> dict[str, Any]:
    """Keep only recognised, JSON-safe settings.

    Raises:
        ValueError: if the payload is not a mapping at all.
    """
    if not isinstance(raw, dict):
        raise ValueError("A profile's settings must be a set of named values.")
    out: dict[str, Any] = {}
    for key, value in raw.items():
        key = str(key)
        if not _is_allowed(key):
            continue
        if value is None or isinstance(value, (str, int, float, bool)):
            out[key] = value
    return out


@dataclass
class Profile:
    """One saved greenhouse setup."""

    profile_id: str
    name: str
    created_at: str
    updated_at: str
    settings: dict[str, Any] = field(default_factory=dict)
    equipment: dict[str, bool] = field(default_factory=dict)
    language: str = "en"
    notes: str = ""
    version: int = PROFILE_VERSION

    def to_file_payload(self) -> dict[str, Any]:
        return {"marker": FILE_MARKER, **asdict(self)}

    @classmethod
    def from_payload(cls, payload: Any, *, require_marker: bool = True) -> Profile:
        """Build a profile from untrusted JSON.

        Raises:
            ValueError: if the payload is not a KasFlex profile, or is unreadable.
        """
        if not isinstance(payload, dict):
            raise ValueError("That file is not a KasFlex setup.")
        if require_marker and payload.get("marker") != FILE_MARKER:
            raise ValueError(
                "That file is not a KasFlex setup. Choose the .json file you "
                "exported from KasFlex.")
        version = payload.get("version", PROFILE_VERSION)
        if not isinstance(version, int) or version > PROFILE_VERSION:
            raise ValueError(
                f"That setup was saved by a newer version of KasFlex "
                f"(format {version}). Update KasFlex and try again.")
        name = str(payload.get("name", "")).strip()[:80]
        if not name:
            raise ValueError("A setup needs a name.")
        now = _now()
        return cls(
            profile_id=str(payload.get("profile_id") or uuid.uuid4().hex)[:64],
            name=name,
            created_at=str(payload.get("created_at") or now)[:40],
            # Preserved, not refreshed: this is the list's sort key, and reading a
            # profile is not using it. ProfileStore.save bumps it, so an import --
            # which saves -- still surfaces at the top.
            updated_at=str(payload.get("updated_at") or now)[:40],
            settings=sanitise_settings(payload.get("settings") or {}),
            equipment={str(k): bool(v)
                       for k, v in (payload.get("equipment") or {}).items()},
            language=str(payload.get("language", "en"))[:8],
            notes=str(payload.get("notes", ""))[:2000],
            version=PROFILE_VERSION,
        )


class ProfileStore:
    """Profiles saved on this computer, one JSON file each."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, profile_id: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", profile_id)[:64]
        if not safe:
            raise ValueError("Invalid profile id.")
        return self.root / f"{safe}.json"

    def save(self, profile: Profile) -> Profile:
        profile.updated_at = _now()
        path = self._path(profile.profile_id)
        temporary = path.with_suffix(".tmp")
        try:
            temporary.write_text(
                json.dumps(profile.to_file_payload(), indent=2, ensure_ascii=False),
                encoding="utf-8")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return profile

    def create(self, name: str, settings: dict[str, Any], *,
               equipment: dict[str, bool] | None = None, language: str = "en",
               notes: str = "") -> Profile:
        name = (name or "").strip()[:80]
        if not name:
            raise ValueError("Give this setup a name so you can find it again.")
        now = _now()
        return self.save(Profile(
            profile_id=uuid.uuid4().hex, name=name, created_at=now, updated_at=now,
            settings=sanitise_settings(settings), equipment=equipment or {},
            language=language, notes=notes,
        ))

    def get(self, profile_id: str) -> Profile:
        path = self._path(profile_id)
        if not path.exists():
            raise KeyError(f"no saved setup {profile_id!r}")
        return Profile.from_payload(json.loads(path.read_text(encoding="utf-8")),
                                    require_marker=False)

    def list(self) -> list[Profile]:
        """Every readable profile, most recently used first.

        An unreadable file is skipped rather than raising: one corrupt profile
        must not stop the startup screen from listing the others.
        """
        found = []
        for path in self.root.glob("*.json"):
            try:
                found.append(Profile.from_payload(
                    json.loads(path.read_text(encoding="utf-8")), require_marker=False))
            except (ValueError, json.JSONDecodeError, OSError):
                continue
        return sorted(found, key=lambda p: p.updated_at, reverse=True)

    def delete(self, profile_id: str) -> None:
        self._path(profile_id).unlink(missing_ok=True)

    def import_text(self, text: str) -> Profile:
        """Load a profile a grower exported earlier.

        Raises:
            ValueError: if the text is too large, not JSON, or not a KasFlex setup.
        """
        if len(text.encode("utf-8")) > MAX_PROFILE_BYTES:
            raise ValueError("That file is too large to be a KasFlex setup.")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "That file could not be read. Choose the .json file you exported "
                "from KasFlex.") from exc
        return self.save(Profile.from_payload(payload))

    def export_text(self, profile_id: str) -> str:
        return json.dumps(self.get(profile_id).to_file_payload(),
                          indent=2, ensure_ascii=False)
