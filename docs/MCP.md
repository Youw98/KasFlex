# Optional MCP adapter

KasFlex works without MCP. The optional `kasflex-mcp` stdio command exposes
three read-only, simulation-only tools backed by the same Python functions as
the UI and CLI:

- `kasflex_day_context` reads the configured day;
- `kasflex_plan` calculates a plan without saving a review or controlling equipment;
- `kasflex_parameters` returns the complete provenance register.

The adapter adds no dependency and is deliberately not a network server.
