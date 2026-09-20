"""Optional stdio MCP adapter around the same functions used by UI and CLI."""

from __future__ import annotations

import json
import sys
from typing import Any

from kasflex.ui.server import UiServer

TOOLS = [
    {
        "name": "kasflex_day_context",
        "description": "Read prices, weather and grid limits for one configured day.",
        "inputSchema": {"type": "object", "properties": {"overrides": {"type": "object"}}},
    },
    {
        "name": "kasflex_plan",
        "description": "Calculate a simulated greenhouse day plan; never controls equipment.",
        "inputSchema": {"type": "object", "properties": {
            "overrides": {"type": "object"}, "policy": {"type": "object"}}},
    },
    {
        "name": "kasflex_parameters",
        "description": "List every operational parameter and its provenance.",
        "inputSchema": {"type": "object", "properties": {"overrides": {"type": "object"}}},
    },
]


def dispatch(ui: UiServer, request: dict[str, Any]) -> dict[str, Any]:
    request_id = request.get("id")
    method = request.get("method")
    if method == "initialize":
        result = {
            "protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
            "serverInfo": {"name": "kasflex", "version": "0.1.3a2"},
        }
    elif method == "notifications/initialized":
        return {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = request.get("params") or {}
        arguments = params.get("arguments") or {}
        name = params.get("name")
        if name == "kasflex_day_context":
            payload = ui.day_context(arguments.get("overrides") or {})
        elif name == "kasflex_plan":
            payload = ui.run(arguments.get("overrides") or {},
                             arguments.get("policy") or {}, persist=False)
        elif name == "kasflex_parameters":
            payload = ui.parameters(arguments.get("overrides") or {})
        else:
            return {"jsonrpc": "2.0", "id": request_id,
                    "error": {"code": -32602, "message": f"Unknown tool: {name}"}}
        result = {
            "content": [{"type": "text", "text": json.dumps(payload, default=str)}],
            "structuredContent": payload,
        }
    else:
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32601, "message": f"Unknown method: {method}"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main() -> None:
    ui = UiServer()
    for line in sys.stdin:
        try:
            reply = dispatch(ui, json.loads(line))
        except Exception as exc:  # noqa: BLE001 - protocol boundary
            reply = {"jsonrpc": "2.0", "id": None,
                     "error": {"code": -32603, "message": f"{type(exc).__name__}: {exc}"}}
        if reply:
            sys.stdout.write(json.dumps(reply, default=str) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
