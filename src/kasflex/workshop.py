"""Which study version and which scenario the grower page shows.

Three versions of the grower page, so a study can compare them on the same days:

* ``manual``: no AI. The grower sets the targets and the rule-based control
  carries them out, as greenhouse climate computers do today.
* ``ai``: the AI proposes a plan; the grower agrees or disagrees per part and
  must say why when disagreeing. No chat.
* ``collab``: everything in ``ai``, plus a chat to ask the AI questions and
  negotiate.

The facilitator sets the version and the active scenario on the admin screen;
the setting is a small JSON file so it survives a restart.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path

VERSIONS = ("manual", "ai", "collab")


@dataclass
class WorkshopState:
    version: str = "collab"
    scenario_id: str = ""
    """Empty means the offline showcase day."""
    lock_scenario: bool = False
    """When set, participants cannot switch to another day."""
    separate_visitors: bool = False
    """When set, each browser tab without a participant id gets its own remembered
    reasons, so one laptop can be shared by a workshop group."""
    issued_ids_only: bool = False
    """When set, only participant codes made on the admin page are accepted, so a
    participant cannot type someone else's id."""


class WorkshopStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def get(self) -> WorkshopState:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return WorkshopState()
        state = WorkshopState()
        if data.get("version") in VERSIONS:
            state.version = data["version"]
        state.scenario_id = str(data.get("scenario_id") or "")[:41]
        state.lock_scenario = data.get("lock_scenario") is True
        state.separate_visitors = data.get("separate_visitors") is True
        state.issued_ids_only = data.get("issued_ids_only") is True
        return state

    def set(self, *, version: str | None = None, scenario_id: str | None = None,
            lock_scenario: bool | None = None,
            separate_visitors: bool | None = None,
            issued_ids_only: bool | None = None) -> WorkshopState:
        state = self.get()
        if version is not None:
            if version not in VERSIONS:
                raise ValueError(f"version must be one of {VERSIONS}")
            state.version = version
        if scenario_id is not None:
            state.scenario_id = scenario_id
        if lock_scenario is not None:
            state.lock_scenario = bool(lock_scenario)
        if separate_visitors is not None:
            state.separate_visitors = bool(separate_visitors)
        if issued_ids_only is not None:
            state.issued_ids_only = bool(issued_ids_only)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(state), indent=2) + "\n", encoding="utf-8")
        return state


#: Letters and digits that cannot be mistaken for one another on a printed card.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
MAX_CODES = 500


class ParticipantCodes:
    """Participant codes the researcher hands out, one per person.

    Random rather than numbered: "P002" is easy to guess from "P001", a code like
    "P-7KQ4MX" is not. The codes are pseudonyms and are stored as plain text so the
    researcher can print them again.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def all(self) -> list[str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [str(c) for c in data.get("codes", []) if isinstance(c, str)]

    def has(self, code: str) -> bool:
        return code.strip().upper() in set(self.all())

    def make(self, count: int) -> list[str]:
        """Add ``count`` new codes and return all codes."""
        codes = self.all()
        count = max(0, min(int(count), MAX_CODES - len(codes)))
        taken = set(codes)
        while count:
            code = "P-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
            if code not in taken:
                taken.add(code)
                codes.append(code)
                count -= 1
        self._save(codes)
        return codes

    def clear(self) -> list[str]:
        self._save([])
        return []

    def _save(self, codes: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"codes": codes}, indent=2) + "\n", encoding="utf-8")


__all__ = ["CODE_ALPHABET", "VERSIONS", "ParticipantCodes", "WorkshopState", "WorkshopStore"]
