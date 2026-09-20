"""Immutable review snapshots and transactional, revision-bound human decisions."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class ReviewConflict(ValueError):
    """A stale, unknown, or unverified revision cannot be decided on."""


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class ReviewStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, snapshot TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS revisions (
                    run_id TEXT NOT NULL REFERENCES runs(run_id), revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL, plan_hash TEXT NOT NULL, result TEXT NOT NULL,
                    PRIMARY KEY (run_id, revision)
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    run_id TEXT NOT NULL, revision INTEGER NOT NULL, created_at TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY (run_id, revision),
                    FOREIGN KEY (run_id, revision) REFERENCES revisions(run_id, revision)
                );
            """)
            for table in ("runs", "revisions", "decisions"):
                for operation in ("UPDATE", "DELETE"):
                    db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{operation} "
                               f"BEFORE {operation} ON {table} BEGIN "
                               "SELECT RAISE(ABORT, 'review history is append-only'); END")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    @staticmethod
    def _latest(db, run_id: str):
        row = db.execute("SELECT * FROM revisions WHERE run_id=? "
                         "ORDER BY revision DESC LIMIT 1", (run_id,)).fetchone()
        if row is None:
            raise ReviewConflict("This plan is not saved. Generate a new plan first.")
        return row

    @staticmethod
    def _check_reference(row, reference: dict) -> None:
        if (reference.get("revision") != row["revision"]
                or reference.get("plan_hash") != row["plan_hash"]):
            raise ReviewConflict("This plan revision has changed. Reload the latest saved review.")

    @staticmethod
    def _insert_revision(db, run_id: str, revision: int, snapshot: dict, result: dict) -> dict:
        digest = hashlib.sha256(_json({"snapshot": snapshot, "plan": result["plan"]})
                                .encode()).hexdigest()
        stored = {**result, "run_id": run_id, "revision": revision, "plan_hash": digest}
        db.execute("INSERT INTO revisions VALUES (?, ?, ?, ?, ?)",
                   (run_id, revision, datetime.now(UTC).isoformat(), digest, _json(stored)))
        return stored

    def create(self, snapshot: dict, result: dict) -> dict:
        run_id = uuid.uuid4().hex
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO runs VALUES (?, ?, ?)",
                       (run_id, datetime.now(UTC).isoformat(), _json(snapshot)))
            return self._insert_revision(db, run_id, 1, snapshot, result)

    def current(self, reference: dict) -> tuple[dict, dict]:
        with self._connect() as db:
            row = self._latest(db, reference.get("run_id", ""))
            self._check_reference(row, reference)
            snapshot = db.execute("SELECT snapshot FROM runs WHERE run_id=?",
                                  (row["run_id"],)).fetchone()[0]
            return json.loads(snapshot), json.loads(row["result"])

    def revise(self, reference: dict, result: dict) -> dict:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._latest(db, reference.get("run_id", ""))
            self._check_reference(row, reference)
            snapshot = db.execute("SELECT snapshot FROM runs WHERE run_id=?",
                                  (row["run_id"],)).fetchone()[0]
            return self._insert_revision(db, row["run_id"], row["revision"] + 1,
                                         json.loads(snapshot), result)

    def decide(self, reference: dict, decision: dict) -> dict:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._latest(db, reference.get("run_id", ""))
            self._check_reference(row, reference)
            verdict = json.loads(row["result"])
            if decision["decision"] == "approve" and not (
                    verdict["checker_enabled"] and verdict["accepted"]):
                raise ReviewConflict("This revision has not passed verification "
                                     "and cannot be approved.")
            existing = db.execute("SELECT payload FROM decisions WHERE run_id=? AND revision=?",
                                  (row["run_id"], row["revision"])).fetchone()
            if existing:
                saved = json.loads(existing[0])
                if saved["decision"] != decision["decision"]:
                    raise ReviewConflict("This revision already has a decision. "
                                         "Re-verify a new revision to change it.")
                return {**saved, "duplicate": True}
            payload = {**decision, "run_id": row["run_id"], "revision": row["revision"],
                       "plan_hash": row["plan_hash"], "timestamp": datetime.now(UTC).isoformat()}
            db.execute("INSERT INTO decisions VALUES (?, ?, ?, ?)",
                       (row["run_id"], row["revision"], payload["timestamp"], _json(payload)))
            return {**payload, "duplicate": False}

    def history(self, limit: int = 30) -> list[dict]:
        with self._connect() as db:
            rows = db.execute("""
                SELECT r.run_id, r.created_at, v.revision, v.result, d.payload
                FROM runs r JOIN revisions v ON v.run_id=r.run_id
                LEFT JOIN decisions d ON d.run_id=v.run_id AND d.revision=v.revision
                WHERE v.revision=(SELECT MAX(revision) FROM revisions WHERE run_id=r.run_id)
                ORDER BY r.created_at DESC LIMIT ?
            """, (max(1, min(limit, 100)),)).fetchall()
        return [{"run_id": r["run_id"], "created_at": r["created_at"],
                 "result": json.loads(r["result"]),
                 "decision": json.loads(r["payload"]) if r["payload"] else None} for r in rows]

    def get(self, run_id: str) -> dict:
        with self._connect() as db:
            row = self._latest(db, run_id)
            decision = db.execute("SELECT payload FROM decisions WHERE run_id=? AND revision=?",
                                  (run_id, row["revision"])).fetchone()
            return {"result": json.loads(row["result"]),
                    "decision": json.loads(decision[0]) if decision else None}
