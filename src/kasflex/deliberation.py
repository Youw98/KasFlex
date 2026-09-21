"""Dimension-level deliberation records for the grower study.

The grower does not accept or reject one monolithic recommendation. They can react
separately to money, crop protection, grid interaction and practical fit. Each
interaction is written as a structured snapshot so repeated sessions can later be
analysed without reconstructing UI events from free-form logs.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DIMENSIONS = ("money", "crop", "grid", "work")
RESPONSES = ("agree", "unsure", "disagree")


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class DeliberationRecord:
    record_id: str
    created_at: str
    stage: str
    session_id: str
    participant_id: str
    scenario_id: str
    plan_id: str
    model_id: str
    dimension: str
    initial_response: str = ""
    ai_counter_response: str = ""
    final_response: str = ""
    time_to_first_response_s: float | None = None
    time_to_final_decision_s: float | None = None
    detail_expansions: int = 0
    why_clicks: int = 0
    edits_made: int = 0
    edit_parameters: str = "{}"
    free_text_reason: str = ""
    ai_confidence_shown: str = ""
    plan_accepted_finally: bool | None = None
    outcome_shown: bool = False
    outcome_better_or_worse_than_expected: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        try:
            payload["edit_parameters"] = json.loads(self.edit_parameters or "{}")
        except json.JSONDecodeError:
            payload["edit_parameters"] = {}
        return payload


class DeliberationLog:
    """Append-only study log. New stages create new rows; old evidence is untouched."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS deliberations (
                    record_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    participant_id TEXT NOT NULL DEFAULT '',
                    scenario_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    dimension TEXT NOT NULL,
                    initial_response TEXT NOT NULL DEFAULT '',
                    ai_counter_response TEXT NOT NULL DEFAULT '',
                    final_response TEXT NOT NULL DEFAULT '',
                    time_to_first_response_s REAL,
                    time_to_final_decision_s REAL,
                    detail_expansions INTEGER NOT NULL DEFAULT 0,
                    why_clicks INTEGER NOT NULL DEFAULT 0,
                    edits_made INTEGER NOT NULL DEFAULT 0,
                    edit_parameters TEXT NOT NULL DEFAULT '{}',
                    free_text_reason TEXT NOT NULL DEFAULT '',
                    ai_confidence_shown TEXT NOT NULL DEFAULT '',
                    plan_accepted_finally INTEGER,
                    outcome_shown INTEGER NOT NULL DEFAULT 0,
                    outcome_better_or_worse_than_expected TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS deliberations_session
                    ON deliberations(session_id, created_at);
                CREATE INDEX IF NOT EXISTS deliberations_plan
                    ON deliberations(plan_id, dimension, created_at);
                """
            )
            db.execute(
                "CREATE TRIGGER IF NOT EXISTS immutable_deliberations "
                "BEFORE UPDATE ON deliberations BEGIN "
                "SELECT RAISE(ABORT, 'deliberation log is append-only'); END"
            )

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    def record(
        self,
        *,
        stage: str,
        session_id: str,
        scenario_id: str,
        plan_id: str,
        model_id: str,
        dimension: str,
        participant_id: str = "",
        initial_response: str = "",
        ai_counter_response: str = "",
        final_response: str = "",
        time_to_first_response_s: float | None = None,
        time_to_final_decision_s: float | None = None,
        detail_expansions: int = 0,
        why_clicks: int = 0,
        edits_made: int = 0,
        edit_parameters: dict[str, Any] | None = None,
        free_text_reason: str = "",
        ai_confidence_shown: str = "",
        plan_accepted_finally: bool | None = None,
        outcome_shown: bool = False,
        outcome_better_or_worse_than_expected: str = "",
    ) -> DeliberationRecord:
        if dimension not in DIMENSIONS:
            raise ValueError(f"dimension must be one of {DIMENSIONS}")
        if initial_response and initial_response not in RESPONSES:
            raise ValueError(f"response must be one of {RESPONSES}")
        if final_response and final_response not in RESPONSES:
            raise ValueError(f"response must be one of {RESPONSES}")
        if not session_id:
            raise ValueError("session_id is required")
        if not plan_id:
            raise ValueError("plan_id is required")

        record = DeliberationRecord(
            record_id=uuid.uuid4().hex,
            created_at=_now(),
            stage=stage,
            session_id=session_id,
            participant_id=participant_id,
            scenario_id=scenario_id,
            plan_id=plan_id,
            model_id=model_id,
            dimension=dimension,
            initial_response=initial_response,
            ai_counter_response=ai_counter_response,
            final_response=final_response,
            time_to_first_response_s=time_to_first_response_s,
            time_to_final_decision_s=time_to_final_decision_s,
            detail_expansions=max(0, int(detail_expansions or 0)),
            why_clicks=max(0, int(why_clicks or 0)),
            edits_made=max(0, int(edits_made or 0)),
            edit_parameters=json.dumps(edit_parameters or {}, sort_keys=True),
            free_text_reason=free_text_reason[:2000],
            ai_confidence_shown=ai_confidence_shown[:80],
            plan_accepted_finally=plan_accepted_finally,
            outcome_shown=bool(outcome_shown),
            outcome_better_or_worse_than_expected=outcome_better_or_worse_than_expected[:80],
        )
        values = asdict(record)
        values["plan_accepted_finally"] = (
            None if record.plan_accepted_finally is None else int(record.plan_accepted_finally)
        )
        values["outcome_shown"] = int(record.outcome_shown)
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO deliberations (
                    record_id, created_at, stage, session_id, participant_id,
                    scenario_id, plan_id, model_id, dimension, initial_response,
                    ai_counter_response, final_response, time_to_first_response_s,
                    time_to_final_decision_s, detail_expansions, why_clicks,
                    edits_made, edit_parameters, free_text_reason,
                    ai_confidence_shown, plan_accepted_finally, outcome_shown,
                    outcome_better_or_worse_than_expected
                ) VALUES (
                    :record_id, :created_at, :stage, :session_id, :participant_id,
                    :scenario_id, :plan_id, :model_id, :dimension, :initial_response,
                    :ai_counter_response, :final_response, :time_to_first_response_s,
                    :time_to_final_decision_s, :detail_expansions, :why_clicks,
                    :edits_made, :edit_parameters, :free_text_reason,
                    :ai_confidence_shown, :plan_accepted_finally, :outcome_shown,
                    :outcome_better_or_worse_than_expected
                )
                """,
                values,
            )
        return record

    def records(self, session_id: str = "", limit: int = 5000) -> list[DeliberationRecord]:
        query = "SELECT * FROM deliberations"
        params: list[Any] = []
        if session_id:
            query += " WHERE session_id=?"
            params.append(session_id)
        query += " ORDER BY created_at, rowid LIMIT ?"
        params.append(limit)
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [
            DeliberationRecord(
                **{
                    **dict(row),
                    "plan_accepted_finally": (
                        None
                        if row["plan_accepted_finally"] is None
                        else bool(row["plan_accepted_finally"])
                    ),
                    "outcome_shown": bool(row["outcome_shown"]),
                }
            )
            for row in rows
        ]

    def export(self, session_id: str = "") -> list[dict[str, Any]]:
        return [record.to_dict() for record in self.records(session_id)]


__all__ = ["DIMENSIONS", "RESPONSES", "DeliberationLog", "DeliberationRecord"]
