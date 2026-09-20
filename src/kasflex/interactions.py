"""Append-only, pseudonymous records of grower-plan interactions."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FIELDS = (
    "session_id", "participant_id", "scenario_id", "plan_id", "model_id",
    "dimension", "initial_response", "ai_counter_response", "final_response",
    "time_to_first_response_s", "time_to_final_response_s", "expansions",
    "why_clicks", "edits", "reason", "confidence", "final_accepted",
    "outcome_shown", "outcome_better", "outcome_worse",
)


class InteractionLog:
    """SQLite log whose rows cannot be changed after insertion."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            columns = ", ".join(f"{field} TEXT NOT NULL" for field in FIELDS)
            db.execute(
                f"CREATE TABLE IF NOT EXISTS interactions "
                f"(event_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, {columns})"
            )
            for operation in ("UPDATE", "DELETE"):
                db.execute(
                    f"CREATE TRIGGER IF NOT EXISTS immutable_interactions_{operation} "
                    f"BEFORE {operation} ON interactions BEGIN "
                    "SELECT RAISE(ABORT, 'interaction history is append-only'); END"
                )

    def append(self, payload: dict[str, Any]) -> dict[str, Any]:
        event = {
            key: payload.get(key, [] if key in {"expansions", "why_clicks", "edits"} else None)
            for key in FIELDS
        }
        event_id = uuid.uuid4().hex
        created_at = datetime.now(UTC).isoformat()
        values = [
            json.dumps(value, sort_keys=True, ensure_ascii=False)
            if isinstance(value, (dict, list, bool)) or value is None else str(value)
            for value in event.values()
        ]
        placeholders = ",".join("?" for _ in FIELDS)
        with sqlite3.connect(self.path) as db:
            db.execute(
                f"INSERT INTO interactions VALUES (?, ?, {placeholders})",
                (event_id, created_at, *values),
            )
        return {"event_id": event_id, "created_at": created_at, **event}

    def export(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT * FROM interactions ORDER BY created_at").fetchall()
        out = []
        for row in rows:
            item = dict(row)
            for key in FIELDS:
                try:
                    item[key] = json.loads(item[key])
                except (json.JSONDecodeError, TypeError):
                    pass
            out.append(item)
        return out
