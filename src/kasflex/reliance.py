"""Measuring whether the grower relies on the planner when they should.

This is the study's instrument, and it is separate from :mod:`kasflex.memory` on
purpose. Memory holds what the grower *told* us. This holds what we *measured*.

Three things are recorded, in this order:

1. **Elicitation.** What the grower would do, and how sure they are, captured
   *before* the planner's answer is revealed. Showing the recommendation first
   anchors the answer and destroys the measurement, so the ordering is enforced by
   the schema: ``ai_choice`` cannot be written until ``grower_choice`` exists.

2. **Resolution.** What they actually went with once both were on the table.

3. **Outcome.** Which of the two would have been better, scored later against what
   the weather and prices actually did.

Only with all three can reliance be classified. The two-by-two is standard in the
literature (Schemmer et al.); the names below are theirs:

                        │ AI was right      │ AI was wrong
    ────────────────────┼───────────────────┼──────────────────────
     went with AI       │ appropriate       │ over-reliance
     kept own choice    │ under-reliance    │ appropriate

``RAIR`` and ``RSR`` are the rate-based versions: of the occasions where switching
to the planner *would* have helped, how often did the grower switch; and of the
occasions where holding firm would have helped, how often did they hold.

An unscored elicitation is never counted as either success or failure. A study
that treats "we do not know yet" as "the grower was wrong" is not measuring trust,
it is manufacturing it.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CONFIDENCE_MIN, CONFIDENCE_MAX = 1, 5
"""Self-reported confidence, 1 (guessing) to 5 (certain)."""

VERDICTS = ("appropriate_ai", "over_reliance", "under_reliance", "appropriate_self")


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class Elicitation:
    """One decision point, from prior opinion through to scored outcome."""

    elicitation_id: str
    run_id: str
    created_at: str
    question: str
    """What was asked, e.g. ``heat_source@03`` or ``day_overall``."""
    grower_choice: str
    confidence: int
    hour: int | None = None
    ai_choice: str = ""
    ai_confidence: str = ""
    """The planner's own stated confidence band, when one was shown."""
    revealed_at: str = ""
    final_choice: str = ""
    resolved_at: str = ""
    better_choice: str = ""
    """Which choice the outcome favoured. Empty until scored."""
    scored_at: str = ""
    condition: str = ""
    """Experiment condition this was collected under."""
    note: str = ""

    @property
    def disagreed(self) -> bool:
        """Whether grower and planner wanted different things."""
        return bool(self.ai_choice) and self.grower_choice != self.ai_choice

    @property
    def went_with_ai(self) -> bool | None:
        if not self.final_choice or not self.ai_choice:
            return None
        return self.final_choice == self.ai_choice

    @property
    def switched(self) -> bool | None:
        """Whether the planner changed their mind. None until resolved."""
        if not self.final_choice:
            return None
        return self.final_choice != self.grower_choice

    @property
    def verdict(self) -> str:
        """Reliance classification, or ``""`` while any piece is missing."""
        if not self.better_choice or not self.final_choice or not self.ai_choice:
            return ""
        if not self.disagreed:
            return ""          # no reliance decision was available to make
        ai_was_right = self.better_choice == self.ai_choice
        if self.went_with_ai:
            return "appropriate_ai" if ai_was_right else "over_reliance"
        return "under_reliance" if ai_was_right else "appropriate_self"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "disagreed": self.disagreed,
                "went_with_ai": self.went_with_ai, "switched": self.switched,
                "verdict": self.verdict}


@dataclass(frozen=True)
class Outcome:
    """What a day actually cost, against what was predicted."""

    outcome_id: str
    run_id: str
    created_at: str
    predicted_cost_eur: float
    actual_cost_eur: float
    ai_plan_cost_eur: float | None = None
    final_plan_cost_eur: float | None = None
    within_predicted_band: bool | None = None
    """Whether the realised cost fell inside the range shown to the grower."""
    note: str = ""

    @property
    def prediction_error_eur(self) -> float:
        return self.actual_cost_eur - self.predicted_cost_eur

    @property
    def ai_plan_was_better(self) -> bool | None:
        if self.ai_plan_cost_eur is None or self.final_plan_cost_eur is None:
            return None
        return self.ai_plan_cost_eur < self.final_plan_cost_eur

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self),
                "prediction_error_eur": self.prediction_error_eur,
                "ai_plan_was_better": self.ai_plan_was_better}


class RelianceLog:
    """Append-only elicitations and outcomes, in the grower memory database."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS elicitations (
                    elicitation_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, question TEXT NOT NULL,
                    grower_choice TEXT NOT NULL, confidence INTEGER NOT NULL,
                    hour INTEGER, condition TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS elicitation_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    elicitation_id TEXT NOT NULL REFERENCES elicitations(elicitation_id),
                    at TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS outcomes (
                    outcome_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, predicted_cost_eur REAL NOT NULL,
                    actual_cost_eur REAL NOT NULL, ai_plan_cost_eur REAL,
                    final_plan_cost_eur REAL, within_predicted_band INTEGER,
                    note TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS elicitations_run ON elicitations(run_id);
                CREATE INDEX IF NOT EXISTS outcomes_run ON outcomes(run_id);
            """)
            for table in ("elicitations", "outcomes"):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table} "
                           f"BEFORE UPDATE ON {table} BEGIN "
                           "SELECT RAISE(ABORT, 'reliance log is append-only'); END")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    # -- eliciting --------------------------------------------------------
    def elicit(self, *, run_id: str, question: str, grower_choice: str,
               confidence: int, hour: int | None = None, condition: str = "",
               note: str = "") -> Elicitation:
        """Record what the grower would do, before the planner's answer is shown.

        Raises:
            ValueError: on an empty choice or a confidence outside 1-5.
        """
        grower_choice = (grower_choice or "").strip()
        if not grower_choice:
            raise ValueError("Say what you would do before seeing the suggestion.")
        try:
            confidence = int(confidence)
        except (TypeError, ValueError) as exc:
            raise ValueError("Confidence must be a whole number from 1 to 5.") from exc
        if not CONFIDENCE_MIN <= confidence <= CONFIDENCE_MAX:
            raise ValueError(f"Confidence must be between {CONFIDENCE_MIN} "
                             f"and {CONFIDENCE_MAX}.")

        elicitation_id = uuid.uuid4().hex
        with self._connect() as db:
            db.execute("INSERT INTO elicitations VALUES (?,?,?,?,?,?,?,?,?)",
                       (elicitation_id, run_id, _now(), question, grower_choice,
                        confidence, hour, condition, note))
        return self.get(elicitation_id)

    def reveal(self, elicitation_id: str, ai_choice: str,
               ai_confidence: str = "") -> Elicitation:
        """Record the planner's answer, at the moment it was shown."""
        self.get(elicitation_id)
        self._event(elicitation_id, "revealed",
                    {"ai_choice": ai_choice, "ai_confidence": ai_confidence})
        return self.get(elicitation_id)

    def resolve(self, elicitation_id: str, final_choice: str,
                note: str = "") -> Elicitation:
        """Record what the grower settled on.

        Raises:
            ValueError: if the planner's answer was never revealed -- an
                unrevealed decision carries no reliance information.
        """
        current = self.get(elicitation_id)
        if not current.ai_choice:
            raise ValueError(
                "This decision has no recorded suggestion, so there is nothing to "
                "have relied on. Call reveal() before resolve().")
        self._event(elicitation_id, "resolved",
                    {"final_choice": final_choice, "note": note})
        return self.get(elicitation_id)

    def score(self, elicitation_id: str, better_choice: str,
              note: str = "") -> Elicitation:
        """Record which choice the outcome favoured."""
        self.get(elicitation_id)
        self._event(elicitation_id, "scored",
                    {"better_choice": better_choice, "note": note})
        return self.get(elicitation_id)

    def _event(self, elicitation_id: str, kind: str, payload: dict) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO elicitation_events (elicitation_id, at, kind, payload) "
                       "VALUES (?,?,?,?)",
                       (elicitation_id, _now(), kind, json.dumps(payload, sort_keys=True)))

    def _build(self, db, row) -> Elicitation:
        events = db.execute("SELECT at, kind, payload FROM elicitation_events "
                            "WHERE elicitation_id=? ORDER BY event_id",
                            (row["elicitation_id"],)).fetchall()
        fields: dict[str, Any] = {}
        for event in events:
            payload = json.loads(event["payload"])
            if event["kind"] == "revealed":
                fields["ai_choice"] = payload.get("ai_choice", "")
                fields["ai_confidence"] = payload.get("ai_confidence", "")
                fields["revealed_at"] = event["at"]
            elif event["kind"] == "resolved":
                fields["final_choice"] = payload.get("final_choice", "")
                fields["resolved_at"] = event["at"]
            elif event["kind"] == "scored":
                fields["better_choice"] = payload.get("better_choice", "")
                fields["scored_at"] = event["at"]
        return Elicitation(
            elicitation_id=row["elicitation_id"], run_id=row["run_id"],
            created_at=row["created_at"], question=row["question"],
            grower_choice=row["grower_choice"], confidence=row["confidence"],
            hour=row["hour"], condition=row["condition"], note=row["note"],
            ai_choice=fields.get("ai_choice", ""),
            ai_confidence=fields.get("ai_confidence", ""),
            revealed_at=fields.get("revealed_at", ""),
            final_choice=fields.get("final_choice", ""),
            resolved_at=fields.get("resolved_at", ""),
            better_choice=fields.get("better_choice", ""),
            scored_at=fields.get("scored_at", ""),
        )

    def get(self, elicitation_id: str) -> Elicitation:
        with self._connect() as db:
            row = db.execute("SELECT * FROM elicitations WHERE elicitation_id=?",
                             (elicitation_id,)).fetchone()
            if row is None:
                raise KeyError(f"no elicitation {elicitation_id!r}")
            return self._build(db, row)

    def elicitations(self, run_id: str = "", limit: int = 500) -> list[Elicitation]:
        query = "SELECT * FROM elicitations"
        params: tuple = ()
        if run_id:
            query += " WHERE run_id=?"
            params = (run_id,)
        query += " ORDER BY created_at LIMIT ?"
        with self._connect() as db:
            rows = db.execute(query, (*params, max(1, min(limit, 5000)))).fetchall()
            return [self._build(db, r) for r in rows]

    # -- outcomes ---------------------------------------------------------
    def record_outcome(self, *, run_id: str, predicted_cost_eur: float,
                       actual_cost_eur: float, ai_plan_cost_eur: float | None = None,
                       final_plan_cost_eur: float | None = None,
                       within_predicted_band: bool | None = None,
                       note: str = "") -> Outcome:
        outcome_id = uuid.uuid4().hex
        with self._connect() as db:
            db.execute("INSERT INTO outcomes VALUES (?,?,?,?,?,?,?,?,?)",
                       (outcome_id, run_id, _now(), float(predicted_cost_eur),
                        float(actual_cost_eur),
                        None if ai_plan_cost_eur is None else float(ai_plan_cost_eur),
                        None if final_plan_cost_eur is None else float(final_plan_cost_eur),
                        None if within_predicted_band is None else int(within_predicted_band),
                        note))
        return self.get_outcome(outcome_id)

    def _row_to_outcome(self, row) -> Outcome:
        return Outcome(
            outcome_id=row["outcome_id"], run_id=row["run_id"],
            created_at=row["created_at"],
            predicted_cost_eur=row["predicted_cost_eur"],
            actual_cost_eur=row["actual_cost_eur"],
            ai_plan_cost_eur=row["ai_plan_cost_eur"],
            final_plan_cost_eur=row["final_plan_cost_eur"],
            within_predicted_band=(None if row["within_predicted_band"] is None
                                   else bool(row["within_predicted_band"])),
            note=row["note"],
        )

    def get_outcome(self, outcome_id: str) -> Outcome:
        with self._connect() as db:
            row = db.execute("SELECT * FROM outcomes WHERE outcome_id=?",
                             (outcome_id,)).fetchone()
            if row is None:
                raise KeyError(f"no outcome {outcome_id!r}")
            return self._row_to_outcome(row)

    def outcomes(self, run_id: str = "", limit: int = 500) -> list[Outcome]:
        query = "SELECT * FROM outcomes"
        params: tuple = ()
        if run_id:
            query += " WHERE run_id=?"
            params = (run_id,)
        query += " ORDER BY created_at LIMIT ?"
        with self._connect() as db:
            return [self._row_to_outcome(r)
                    for r in db.execute(query, (*params, max(1, min(limit, 5000))))]

    # -- metrics ----------------------------------------------------------
    def metrics(self, condition: str = "") -> dict[str, Any]:
        """Reliance measures over every scored, disagreeing decision.

        Rates are None rather than zero when their denominator is empty: "no
        occasion arose" and "the grower failed every time" are different findings.
        """
        items = [e for e in self.elicitations()
                 if not condition or e.condition == condition]
        scored = [e for e in items if e.verdict]

        counts = dict.fromkeys(VERDICTS, 0)
        for item in scored:
            counts[item.verdict] += 1

        # RAIR: of the times switching would have helped, how often did they switch.
        rair_pool = [e for e in scored if e.better_choice == e.ai_choice]
        rsr_pool = [e for e in scored if e.better_choice == e.grower_choice]
        rair = (sum(1 for e in rair_pool if e.went_with_ai) / len(rair_pool)
                if rair_pool else None)
        rsr = (sum(1 for e in rsr_pool if not e.went_with_ai) / len(rsr_pool)
               if rsr_pool else None)

        resolved = [e for e in items if e.final_choice and e.ai_choice]
        disagreements = [e for e in resolved if e.disagreed]
        appropriate = counts["appropriate_ai"] + counts["appropriate_self"]

        confidences = [e.confidence for e in items]
        switch_by_confidence: dict[int, dict[str, int]] = {}
        for item in disagreements:
            bucket = switch_by_confidence.setdefault(
                item.confidence, {"switched": 0, "total": 0})
            bucket["total"] += 1
            if item.went_with_ai:
                bucket["switched"] += 1

        outcomes = self.outcomes()
        covered = [o.within_predicted_band for o in outcomes
                   if o.within_predicted_band is not None]

        return {
            "elicitations": len(items),
            "resolved": len(resolved),
            "scored": len(scored),
            "disagreements": len(disagreements),
            **counts,
            "appropriate_reliance_rate": appropriate / len(scored) if scored else None,
            "over_reliance_rate": counts["over_reliance"] / len(scored) if scored else None,
            "under_reliance_rate": counts["under_reliance"] / len(scored) if scored else None,
            "rair": rair,
            "rsr": rsr,
            "agreement_rate": (sum(1 for e in resolved if e.went_with_ai) / len(resolved)
                               if resolved else None),
            "switch_rate": (sum(1 for e in disagreements if e.went_with_ai)
                            / len(disagreements) if disagreements else None),
            "mean_confidence": sum(confidences) / len(confidences) if confidences else None,
            "switch_by_confidence": switch_by_confidence,
            "outcomes": len(outcomes),
            "band_coverage": sum(covered) / len(covered) if covered else None,
            "mean_absolute_prediction_error_eur": (
                sum(abs(o.prediction_error_eur) for o in outcomes) / len(outcomes)
                if outcomes else None),
        }

    def export(self) -> dict[str, Any]:
        return {
            "elicitations": [e.to_dict() for e in self.elicitations(limit=5000)],
            "outcomes": [o.to_dict() for o in self.outcomes(limit=5000)],
            "metrics": self.metrics(),
        }
