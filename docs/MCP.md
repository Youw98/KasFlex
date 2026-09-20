# MCP integration

KasFlex provides an **optional** Model Context Protocol (MCP) integration for
hackathons and external agent frameworks. It is an adapter over the existing
KasFlex APIs, not a second simulator and not a dependency of the core package.

Install the extra:

```bash
pip install -e ".[mcp]"
```

Start the stdio server:

```bash
kasflex mcp
```

Available tools:

| Tool | Purpose |
|---|---|
| `get_day_context` | Price, weather, grid limits and provenance before planning |
| `plan_day` | Collaborative checked 24-hour plan with grower policy and commercial position |
| `verify_saved_plan` | Re-check a human/agent edit against the frozen scenario that produced the run |
| `run_experiment` | Execute a reproducible planner/checker matrix and return summary + CSV |

## Safety boundary

MCP does not bypass the KasFlex checker. An edited plan is still re-verified through
the same saved-run revision/hash mechanism used by the browser. The server is a
research integration surface only; it does not connect to greenhouse equipment,
SCADA, trading systems or live control.

## PowerAgent relationship

PowerAgent/PowerMCP is used as an architectural **pattern**, not as a dependency.
KasFlex owns its greenhouse-specific tools and keeps the agent protocol outside the
simulation internals. Check licences before reusing third-party code.
