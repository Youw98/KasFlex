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
        return state

    def set(self, *, version: str | None = None, scenario_id: str | None = None,
            lock_scenario: bool | None = None) -> WorkshopState:
        state = self.get()
        if version is not None:
            if version not in VERSIONS:
                raise ValueError(f"version must be one of {VERSIONS}")
            state.version = version
        if scenario_id is not None:
            state.scenario_id = scenario_id
        if lock_scenario is not None:
            state.lock_scenario = bool(lock_scenario)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(state), indent=2) + "\n", encoding="utf-8")
        return state


__all__ = ["VERSIONS", "WorkshopState", "WorkshopStore"]
