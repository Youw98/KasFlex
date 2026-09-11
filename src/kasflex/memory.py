"""What the grower has taught the system, and where they disagreed with it.

Three append-only stores behind one SQLite file:

**Preferences** are standing instructions in the grower's own words -- "never run
the CHP overnight, it jammed last February". They are stated once and never
edited; retiring one appends an event rather than deleting a row, so a result
computed months ago can still be explained by the preferences in force that day.

**Conflicts** record where the planner and the grower chose differently on the same
hour, and how it ended. This is the study's primary observation: not whether the
grower clicked approve, but *where* human and machine judgement diverge and
whether a middle position existed.

**Conversation turns** are the transcript of the grower asking why. A rejection
with a reason is worth more than a rejection, and the reason only ever arrives in
prose.

Every record carries provenance -- when, which run, which revision, and whether it
came from the grower directly or was inferred from what they said (FAIR R1). The
schema is stable and exported verbatim by :mod:`kasflex.fair`.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STRENGTHS = ("preference", "strong", "absolute")
"""How hard a preference binds.

``preference`` is a nudge the planner may overrule for a good reason; ``strong``
requires it to say why in the plan; ``absolute`` is never overruled -- the planner
treats it as a constraint and reports infeasibility rather than crossing it.
"""

RESOLUTIONS = ("open", "grower_kept", "ai_kept", "compromise")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True)
class Preference:
    """One standing instruction from the grower."""

    pref_id: str
    created_at: str
    rule: str
    """One imperative sentence the planner can act on."""
    reason: str
    """The grower's own words. Never paraphrased away -- it is the research datum."""
    strength: str = "preference"
    scope: dict[str, Any] = field(default_factory=dict)
    """Optional narrowing: ``{"assets": ["chp"], "hours": [22, 23, 0], "months": [12, 1]}``."""
    source: str = "grower"
    """``grower`` when stated outright, ``inferred`` when drawn from a conversation."""
    origin_run_id: str = ""
    origin_revision: int = 0
    confirmed: bool = True
    """False for an inferred preference the grower has not yet confirmed."""
    retired_at: str = ""
    retired_reason: str = ""
    applied_count: int = 0
    overridden_count: int = 0

    @property
    def active(self) -> bool:
        return not self.retired_at

    def to_dict(self) -> dict[str, Any]:
        """Including ``active``, which ``dataclasses.asdict`` drops as a property.

        Callers serialising this for an interface need the derived field; without
        it a retired preference is indistinguishable from a live one.
        """
        return {**asdict(self), "active": self.active}

    def prompt_line(self) -> str:
        bits = [f"- [{self.strength}] {self.rule}"]
        if self.reason:
            bits.append(f'(grower said: "{self.reason}")')
        if self.scope.get("hours"):
            hours = self.scope["hours"]
            bits.append(f"[hours {min(hours)}-{max(hours)}]")
        if self.scope.get("assets"):
            bits.append(f"[{', '.join(self.scope['assets'])}]")
        return " ".join(bits)


@dataclass(frozen=True)
class Conflict:
    """One hour where the grower's choice differed from the planner's."""

    conflict_id: str
    created_at: str
    run_id: str
    revision: int
    hour: int
    field_name: str
    ai_value: str
    grower_value: str
    ai_rationale: str = ""
    grower_reason: str = ""
    resolution: str = "open"
    resolved_value: str = ""
    cost_delta_eur: float = 0.0
    """Positive means the grower's choice costs more than the planner's."""
    safety_blocked: bool = False
    """True when the checker refused the grower's choice outright."""
    resolved_at: str = ""


class GrowerMemory:
    """Append-only store of preferences, conflicts and conversation."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS preferences (
                    pref_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    rule TEXT NOT NULL, reason TEXT NOT NULL, strength TEXT NOT NULL,
                    scope TEXT NOT NULL, source TEXT NOT NULL,
                    origin_run_id TEXT NOT NULL DEFAULT '',
                    origin_revision INTEGER NOT NULL DEFAULT 0,
                    confirmed INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS preference_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pref_id TEXT NOT NULL REFERENCES preferences(pref_id),
                    at TEXT NOT NULL, event TEXT NOT NULL, detail TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS conflicts (
                    conflict_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    run_id TEXT NOT NULL, revision INTEGER NOT NULL, hour INTEGER NOT NULL,
                    field_name TEXT NOT NULL, ai_value TEXT NOT NULL,
                    grower_value TEXT NOT NULL, ai_rationale TEXT NOT NULL DEFAULT '',
                    grower_reason TEXT NOT NULL DEFAULT '',
                    cost_delta_eur REAL NOT NULL DEFAULT 0,
                    safety_blocked INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS conflict_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conflict_id TEXT NOT NULL REFERENCES conflicts(conflict_id),
                    at TEXT NOT NULL, resolution TEXT NOT NULL,
                    resolved_value TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS turns (
                    turn_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL, at TEXT NOT NULL, role TEXT NOT NULL,
                    text TEXT NOT NULL, model TEXT NOT NULL DEFAULT '',
                    hour INTEGER, meta TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS turns_run ON turns(run_id, turn_id);
                CREATE INDEX IF NOT EXISTS conflicts_run ON conflicts(run_id);
            """)
            for table in ("preferences", "conflicts", "turns"):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table} "
                           f"BEFORE UPDATE ON {table} BEGIN "
                           "SELECT RAISE(ABORT, 'grower memory is append-only'); END")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    # -- preferences ------------------------------------------------------
    def add_preference(self, rule: str, reason: str, *, strength: str = "preference",
                       scope: dict | None = None, source: str = "grower",
                       origin_run_id: str = "", origin_revision: int = 0,
                       confirmed: bool = True) -> Preference:
        """Record a standing instruction.

        Raises:
            ValueError: on an empty rule or an unknown strength.
        """
        rule = rule.strip()
        if not rule:
            raise ValueError("A preference needs a rule the planner can act on.")
        if strength not in STRENGTHS:
            raise ValueError(f"strength must be one of {STRENGTHS}, got {strength!r}")
        pref_id = uuid.uuid4().hex
        at = _now()
        with self._connect() as db:
            db.execute("INSERT INTO preferences VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (pref_id, at, rule, reason.strip(), strength, _json(scope or {}),
                        source, origin_run_id, origin_revision, int(confirmed)))
            db.execute("INSERT INTO preference_events (pref_id, at, event, detail) "
                       "VALUES (?,?,?,?)", (pref_id, at, "created", source))
        return self.get_preference(pref_id)

    def _row_to_preference(self, db, row) -> Preference:
        events = db.execute("SELECT at, event, detail FROM preference_events "
                            "WHERE pref_id=? ORDER BY event_id", (row["pref_id"],)).fetchall()
        retired = next((e for e in reversed(events) if e["event"] == "retired"), None)
        revived = next((e for e in reversed(events) if e["event"] == "revived"), None)
        if retired and revived and revived["at"] > retired["at"]:
            retired = None
        return Preference(
            pref_id=row["pref_id"], created_at=row["created_at"], rule=row["rule"],
            reason=row["reason"], strength=row["strength"], scope=json.loads(row["scope"]),
            source=row["source"], origin_run_id=row["origin_run_id"],
            origin_revision=row["origin_revision"],
            confirmed=bool(row["confirmed"]) or any(e["event"] == "confirmed" for e in events),
            retired_at=retired["at"] if retired else "",
            retired_reason=retired["detail"] if retired else "",
            applied_count=sum(1 for e in events if e["event"] == "applied"),
            overridden_count=sum(1 for e in events if e["event"] == "overridden"),
        )

    def get_preference(self, pref_id: str) -> Preference:
        with self._connect() as db:
            row = db.execute("SELECT * FROM preferences WHERE pref_id=?", (pref_id,)).fetchone()
            if row is None:
                raise KeyError(f"no preference {pref_id!r}")
            return self._row_to_preference(db, row)

    def preferences(self, *, active_only: bool = True,
                    include_unconfirmed: bool = False) -> list[Preference]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM preferences ORDER BY created_at DESC").fetchall()
            out = [self._row_to_preference(db, r) for r in rows]
        if active_only:
            out = [p for p in out if p.active]
        if not include_unconfirmed:
            out = [p for p in out if p.confirmed]
        return out

    def retire_preference(self, pref_id: str, reason: str = "") -> Preference:
        self.get_preference(pref_id)
        with self._connect() as db:
            db.execute("INSERT INTO preference_events (pref_id, at, event, detail) "
                       "VALUES (?,?,?,?)", (pref_id, _now(), "retired", reason))
        return self.get_preference(pref_id)

    def confirm_preference(self, pref_id: str) -> Preference:
        """Promote an inferred preference once the grower has agreed to it."""
        self.get_preference(pref_id)
        with self._connect() as db:
            db.execute("INSERT INTO preference_events (pref_id, at, event, detail) "
                       "VALUES (?,?,?,?)", (pref_id, _now(), "confirmed", ""))
        return self.get_preference(pref_id)

    def note_preference_use(self, pref_id: str, *, honoured: bool, detail: str = "") -> None:
        """Record that a plan respected or overrode a preference."""
        with self._connect() as db:
            db.execute("INSERT INTO preference_events (pref_id, at, event, detail) "
                       "VALUES (?,?,?,?)",
                       (pref_id, _now(), "applied" if honoured else "overridden", detail))

    def prompt_block(self) -> str:
        """The active preferences, rendered for a planner or explainer prompt."""
        active = self.preferences()
        if not active:
            return ""
        absolute = [p for p in active if p.strength == "absolute"]
        others = [p for p in active if p.strength != "absolute"]
        lines = ["What this grower has told you before -- honour it unless safety forbids:"]
        lines += [p.prompt_line() for p in absolute + others]
        lines.append(
            "If you must go against one of these, say so plainly in that hour's reasoning "
            "and explain what forced it. Never cross an [absolute] instruction."
        )
        return "\n".join(lines)

    # -- conflicts --------------------------------------------------------
    def record_conflict(self, *, run_id: str, revision: int, hour: int, field_name: str,
                        ai_value: str, grower_value: str, ai_rationale: str = "",
                        grower_reason: str = "", cost_delta_eur: float = 0.0,
                        safety_blocked: bool = False) -> Conflict:
        conflict_id = uuid.uuid4().hex
        at = _now()
        with self._connect() as db:
            db.execute("INSERT INTO conflicts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (conflict_id, at, run_id, revision, hour, field_name,
                        str(ai_value), str(grower_value), ai_rationale, grower_reason,
                        float(cost_delta_eur), int(safety_blocked)))
        return self.get_conflict(conflict_id)

    def _row_to_conflict(self, db, row) -> Conflict:
        event = db.execute("SELECT * FROM conflict_events WHERE conflict_id=? "
                           "ORDER BY event_id DESC LIMIT 1", (row["conflict_id"],)).fetchone()
        return Conflict(
            conflict_id=row["conflict_id"], created_at=row["created_at"], run_id=row["run_id"],
            revision=row["revision"], hour=row["hour"], field_name=row["field_name"],
            ai_value=row["ai_value"], grower_value=row["grower_value"],
            ai_rationale=row["ai_rationale"], grower_reason=row["grower_reason"],
            cost_delta_eur=row["cost_delta_eur"], safety_blocked=bool(row["safety_blocked"]),
            resolution=event["resolution"] if event else "open",
            resolved_value=event["resolved_value"] if event else "",
            resolved_at=event["at"] if event else "",
        )

    def get_conflict(self, conflict_id: str) -> Conflict:
        with self._connect() as db:
            row = db.execute("SELECT * FROM conflicts WHERE conflict_id=?",
                             (conflict_id,)).fetchone()
            if row is None:
                raise KeyError(f"no conflict {conflict_id!r}")
            return self._row_to_conflict(db, row)

    def resolve_conflict(self, conflict_id: str, resolution: str,
                         resolved_value: str = "", note: str = "") -> Conflict:
        if resolution not in RESOLUTIONS:
            raise ValueError(f"resolution must be one of {RESOLUTIONS}")
        self.get_conflict(conflict_id)
        with self._connect() as db:
            db.execute("INSERT INTO conflict_events (conflict_id, at, resolution, "
                       "resolved_value, note) VALUES (?,?,?,?,?)",
                       (conflict_id, _now(), resolution, str(resolved_value), note))
        return self.get_conflict(conflict_id)

    def conflicts(self, run_id: str = "", limit: int = 200) -> list[Conflict]:
        query = "SELECT * FROM conflicts"
        params: tuple = ()
        if run_id:
            query += " WHERE run_id=?"
            params = (run_id,)
        query += " ORDER BY created_at DESC LIMIT ?"
        with self._connect() as db:
            rows = db.execute(query, (*params, max(1, min(limit, 1000)))).fetchall()
            return [self._row_to_conflict(db, r) for r in rows]

    # -- conversation -----------------------------------------------------
    def add_turn(self, run_id: str, role: str, text: str, *, model: str = "",
                 hour: int | None = None, meta: dict | None = None) -> dict:
        if role not in ("grower", "assistant", "system"):
            raise ValueError("role must be grower, assistant or system")
        at = _now()
        with self._connect() as db:
            cur = db.execute("INSERT INTO turns (run_id, at, role, text, model, hour, meta) "
                             "VALUES (?,?,?,?,?,?,?)",
                             (run_id, at, role, text, model, hour, _json(meta or {})))
            return {"turn_id": cur.lastrowid, "run_id": run_id, "at": at,
                    "role": role, "text": text, "model": model, "hour": hour,
                    "meta": meta or {}}

    def turns(self, run_id: str, limit: int = 100) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM turns WHERE run_id=? ORDER BY turn_id LIMIT ?",
                              (run_id, max(1, min(limit, 500)))).fetchall()
        return [{"turn_id": r["turn_id"], "at": r["at"], "role": r["role"], "text": r["text"],
                 "model": r["model"], "hour": r["hour"], "meta": json.loads(r["meta"])}
                for r in rows]

    # -- research summary -------------------------------------------------
    def statistics(self) -> dict[str, Any]:
        """Headline numbers for the study, cheap enough to call on every page load."""
        with self._connect() as db:
            prefs = db.execute("SELECT COUNT(*) FROM preferences").fetchone()[0]
            retired = db.execute("SELECT COUNT(DISTINCT pref_id) FROM preference_events "
                                 "WHERE event='retired'").fetchone()[0]
            applied = db.execute("SELECT COUNT(*) FROM preference_events "
                                 "WHERE event='applied'").fetchone()[0]
            overridden = db.execute("SELECT COUNT(*) FROM preference_events "
                                    "WHERE event='overridden'").fetchone()[0]
            total_conflicts = db.execute("SELECT COUNT(*) FROM conflicts").fetchone()[0]
            resolutions = dict(db.execute("""
                SELECT resolution, COUNT(*) FROM (
                  SELECT c.conflict_id, COALESCE((
                    SELECT resolution FROM conflict_events e WHERE e.conflict_id=c.conflict_id
                    ORDER BY event_id DESC LIMIT 1), 'open') AS resolution
                  FROM conflicts c
                ) GROUP BY resolution""").fetchall())
            turns = db.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
            questions = db.execute("SELECT COUNT(*) FROM turns WHERE role='grower'").fetchone()[0]
        compromises = resolutions.get("compromise", 0)
        decided = total_conflicts - resolutions.get("open", 0)
        return {
            "preferences_total": prefs, "preferences_active": prefs - retired,
            "preferences_applied": applied, "preferences_overridden": overridden,
            "conflicts_total": total_conflicts, "conflicts_open": resolutions.get("open", 0),
            "conflicts_grower_kept": resolutions.get("grower_kept", 0),
            "conflicts_ai_kept": resolutions.get("ai_kept", 0),
            "conflicts_compromise": compromises,
            "compromise_rate": compromises / decided if decided else None,
            "conversation_turns": turns, "grower_questions": questions,
        }

    def export(self) -> dict[str, Any]:
        """Everything, as plain dictionaries, for the FAIR export."""
        with self._connect() as db:
            turn_rows = db.execute("SELECT * FROM turns ORDER BY turn_id").fetchall()
            events = db.execute("SELECT * FROM preference_events ORDER BY event_id").fetchall()
        return {
            "preferences": [p.to_dict() for p in
                            self.preferences(active_only=False, include_unconfirmed=True)],
            "preference_events": [dict(r) for r in events],
            "conflicts": [asdict(c) for c in self.conflicts(limit=1000)],
            "conversation": [{"turn_id": r["turn_id"], "run_id": r["run_id"], "at": r["at"],
                              "role": r["role"], "text": r["text"], "model": r["model"],
                              "hour": r["hour"], "meta": json.loads(r["meta"])}
                             for r in turn_rows],
            "statistics": self.statistics(),
        }
