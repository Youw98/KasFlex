"""Optional Model Context Protocol server for KasFlex.

This is an integration surface, not a new dependency of the core. Install the
optional mcp extra when an agent framework needs to drive KasFlex. The tools call
the same UiServer methods as the browser, so MCP clients cannot bypass verification
or create a second implementation of the simulator.
"""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer

from kasflex.resources import default_config_path
from kasflex.ui.server import UiServer

mcp = MCPServer(
    "KasFlex",
    instructions=(
        "Greenhouse energy-planning simulator. Simulation only; greenhouse outputs "
        "are not validated for operational control. Prefer get_day_context before "
        "plan_day, and verify_saved_plan after any human/agent edit."
    ),
)


def _ui() -> UiServer:
    return UiServer(config_path=str(default_config_path()), anonymous=True)


@mcp.tool()
def get_day_context(data_source: str = "synthetic", date: str = "") -> dict[str, Any]:
    """Return price, weather, grid limits and provenance for one planning day."""
    overrides: dict[str, Any] = {"data_source": data_source}
    if date:
        overrides["date"] = date
    return _ui().day_context(overrides)


@mcp.tool()
def plan_day(
    priority: str = "balanced",
    data_source: str = "synthetic",
    date: str = "",
    battery_reserve_pct: float = 45.0,
    avoid_chp_night: bool = False,
    prefer_stored_heat: bool = True,
    brief: str = "",
) -> dict[str, Any]:
    """Create a checked 24-hour collaborative plan and its commercial position."""
    overrides: dict[str, Any] = {"planner": "collaborative", "data_source": data_source}
    if date:
        overrides["date"] = date
    return _ui().run(
        overrides,
        policy={
            "priority": priority,
            "battery_reserve_pct": battery_reserve_pct,
            "avoid_chp_night": avoid_chp_night,
            "prefer_stored_heat": prefer_stored_heat,
            "brief": brief,
        },
    )


@mcp.tool()
def verify_saved_plan(
    run_id: str,
    revision: int,
    plan_hash: str,
    plan: list[dict[str, Any]],
) -> dict[str, Any]:
    """Re-check an edited plan against the frozen scenario that produced it."""
    return _ui().verify(
        {},
        plan,
        reference={"run_id": run_id, "revision": revision, "plan_hash": plan_hash},
    )


@mcp.tool()
def run_experiment(
    days: int = 3,
    planners: list[str] | None = None,
    verified: bool = True,
    unverified: bool = False,
    feedback: bool = True,
) -> dict[str, Any]:
    """Run a reproducible experiment matrix and return its summary plus CSV."""
    modes = []
    if verified:
        modes.append("verified")
    if unverified:
        modes.append("unverified")
    return _ui().run_experiment_batch(
        {
            "days": days,
            "planners": planners or ["collaborative", "rule-based"],
            "checker_modes": modes or ["verified"],
            "feedback": feedback,
        }
    )


if __name__ == "__main__":
    mcp.run()
