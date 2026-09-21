"""Informed consent, and the erasure that has to follow withdrawal.

The system records a grower's own words, how confident they were, and occasions
when their judgement turned out worse than the planner's. That is personal data,
and the last part is the kind a person could reasonably not want kept. So consent
is asked for before any of it is written, not after.

Three principles shape the design, and each one rules out a shortcut:

**Consent gates recording, never use.** A grower who declines research can still
plan, review and approve; nothing is written to the research stores. Making the
tool unusable without consent would make the consent coerced, and a coerced yes
is not consent.

**Granular, because the asks differ.** Keeping a count of decisions is a smaller
request than keeping verbatim quotes. They are separate switches, and declining
one does not decline the other.

**Withdrawal erases.** The memory and reliance stores are append-only against
tampering, but erasure beats append-only: the triggers block UPDATE and leave
DELETE available precisely so this can work. A withdrawal that leaves the data in
place is not a withdrawal.

The consent *text* is not written here. Wording is an ethics-committee matter, so
this module stores a version identifier and refuses to treat consent given under
one version as consent under another.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCOPES: dict[str, str] = {
    "research": "Keep a record of my decisions so they can be studied.",
    "quotes": "Keep my own words, exactly as I write them.",
    "outcomes": "Compare what I decided against what actually happened.",
}
"""What can be asked for, separately. Keys are stored; the shown wording is the
ethics-approved text held elsewhere, keyed by consent version."""

REQUIRED_FOR_RESEARCH = ("research",)
"""Without this, nothing reaches the research stores at all."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ConsentError(RuntimeError):
    """An operation was attempted that the participant has not agreed to."""


@dataclass(frozen=True)
class Consent:
    """One participant's standing position on being studied."""

    consent_id: str
    participant_id: str
    created_at: str
    version: str
    scopes: dict[str, bool] = field(default_factory=dict)
    withdrawn_at: str = ""
    withdrawal_reason: str = ""
    erased_at: str = ""
    note: str = ""

    @property
    def active(self) -> bool:
        return not self.withdrawn_at

    def allows(self, scope: str) -> bool:
        """Whether this scope may be written to right now."""
        if not self.active:
            return False
        if not self.scopes.get("research"):
            return False
        return bool(self.scopes.get(scope, False)) if scope != "research" else True

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "active": self.active}


class ConsentLog:
    """Consent decisions, and the erasure that withdrawal triggers."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS consents (
                    consent_id TEXT PRIMARY KEY, participant_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, version TEXT NOT NULL,
                    scopes TEXT NOT NULL, note TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS consent_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    consent_id TEXT NOT NULL REFERENCES consents(consent_id),
                    at TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS consents_participant
                    ON consents(participant_id, created_at);
            """)
            db.execute("CREATE TRIGGER IF NOT EXISTS immutable_consents "
                       "BEFORE UPDATE ON consents BEGIN "
                       "SELECT RAISE(ABORT, 'consent records are append-only'); END")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def grant(self, participant_id: str, scopes: dict[str, bool], *,
              version: str, note: str = "") -> Consent:
        """Record a consent decision.

        A later grant supersedes an earlier one, including after a withdrawal --
        someone may change their mind in either direction.

        Raises:
            ValueError: on a missing participant id or version, or an unknown scope.
        """
        participant_id = (participant_id or "").strip()
        if not participant_id:
            raise ValueError("A consent record needs a participant identifier.")
        version = (version or "").strip()
        if not version:
            raise ValueError("A consent record needs the version of the text agreed to.")
        unknown = set(scopes) - set(SCOPES)
        if unknown:
            raise ValueError(f"Unknown consent scope(s): {sorted(unknown)}")

        clean = {name: bool(scopes.get(name, False)) for name in SCOPES}
        consent_id = uuid.uuid4().hex
        at = _now()
        with self._connect() as db:
            db.execute("INSERT INTO consents VALUES (?,?,?,?,?,?)",
                       (consent_id, participant_id, at, version,
                        json.dumps(clean, sort_keys=True), note))
            db.execute("INSERT INTO consent_events (consent_id, at, kind, detail) "
                       "VALUES (?,?,?,?)", (consent_id, at, "granted", version))
        return self.get(consent_id)

    def _build(self, db, row) -> Consent:
        events = db.execute("SELECT at, kind, detail FROM consent_events "
                            "WHERE consent_id=? ORDER BY event_id",
                            (row["consent_id"],)).fetchall()
        withdrawn = next((e for e in events if e["kind"] == "withdrawn"), None)
        erased = next((e for e in events if e["kind"] == "erased"), None)
        return Consent(
            consent_id=row["consent_id"], participant_id=row["participant_id"],
            created_at=row["created_at"], version=row["version"],
            scopes=json.loads(row["scopes"]), note=row["note"],
            withdrawn_at=withdrawn["at"] if withdrawn else "",
            withdrawal_reason=withdrawn["detail"] if withdrawn else "",
            erased_at=erased["at"] if erased else "",
        )

    def get(self, consent_id: str) -> Consent:
        with self._connect() as db:
            row = db.execute("SELECT * FROM consents WHERE consent_id=?",
                             (consent_id,)).fetchone()
            if row is None:
                raise KeyError(f"no consent record {consent_id!r}")
            return self._build(db, row)

    def current(self, participant_id: str) -> Consent | None:
        """The most recent decision for this participant, withdrawn or not."""
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM consents WHERE participant_id=? "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                ((participant_id or "").strip(),)).fetchone()
            return self._build(db, row) if row else None

    def allows(self, participant_id: str, scope: str) -> bool:
        """Whether this participant currently permits writing to ``scope``.

        Absence of a record is a no. Defaulting to permitted would mean data
        collected from someone who was never asked.
        """
        consent = self.current(participant_id)
        return bool(consent and consent.allows(scope))

    def needs_consent(self, participant_id: str, version: str) -> bool:
        """True when there is no live consent for this exact version of the text.

        Re-asking on a version change is the point: agreement to an earlier text is
        not agreement to a later one.
        """
        consent = self.current(participant_id)
        return not consent or not consent.active or consent.version != version

    def withdraw(self, participant_id: str, reason: str = "") -> Consent:
        """Withdraw consent. Call :meth:`erase` to remove the data itself.

        Raises:
            KeyError: if this participant has no consent record.
        """
        consent = self.current(participant_id)
        if consent is None:
            raise KeyError(f"no consent record for {participant_id!r}")
        with self._connect() as db:
            db.execute("INSERT INTO consent_events (consent_id, at, kind, detail) "
                       "VALUES (?,?,?,?)", (consent.consent_id, _now(), "withdrawn", reason))
        return self.get(consent.consent_id)

    def erase(self, participant_id: str, stores: list[Path | str]) -> dict[str, int]:
        """Delete this participant's research data from the given databases.

        The stores are append-only against tampering -- their triggers block UPDATE
        and deliberately leave DELETE available, so that this can work. Erasure has
        to beat immutability, or withdrawal means nothing.

        The consent record itself survives, marked erased: proof that someone asked
        to be removed is the one thing that must outlive the removal.

        Returns:
            Rows deleted per table.
        """
        consent = self.current(participant_id)
        if consent is None:
            raise KeyError(f"no consent record for {participant_id!r}")

        # Every table that can carry participant data, with the column naming them.
        targets = {
            "elicitations": "condition",
            "turns": "run_id",
            "conflicts": "run_id",
            "outcomes": "run_id",
        }
        deleted: dict[str, int] = {}
        for store in stores:
            store_path = Path(store)
            if not store_path.exists():
                continue
            with sqlite3.connect(store_path, timeout=15) as db:
                existing = {r[0] for r in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                for table, column in targets.items():
                    if table not in existing:
                        continue
                    cursor = db.execute(
                        f"DELETE FROM {table} WHERE {column} LIKE ?",  # noqa: S608
                        (f"%{participant_id}%",))
                    deleted[table] = deleted.get(table, 0) + cursor.rowcount

        with self._connect() as db:
            db.execute("INSERT INTO consent_events (consent_id, at, kind, detail) "
                       "VALUES (?,?,?,?)",
                       (consent.consent_id, _now(), "erased", json.dumps(deleted, sort_keys=True)))
        return deleted

    def participants(self) -> list[Consent]:
        """The latest decision for every participant, most recent first."""
        with self._connect() as db:
            rows = db.execute("""
                SELECT * FROM consents c WHERE c.created_at = (
                    SELECT MAX(created_at) FROM consents
                    WHERE participant_id = c.participant_id)
                ORDER BY c.created_at DESC
            """).fetchall()
            return [self._build(db, r) for r in rows]

    def summary(self) -> dict[str, Any]:
        people = self.participants()
        return {
            "participants": len(people),
            "active": sum(1 for c in people if c.active),
            "withdrawn": sum(1 for c in people if not c.active),
            "by_scope": {scope: sum(1 for c in people if c.allows(scope))
                         for scope in SCOPES},
            "scopes": dict(SCOPES),
        }
