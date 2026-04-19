"""
realtime_tools.py — Thin adapter.

Canonical tool implementations live in truman.tools.all_tools. Schema
conversion + dispatch live in truman.tools.dispatch. This file exists
only so that realtime.py's existing import surface (`tool_schemas`,
`dispatch_tool`) keeps working without changes.

No tool logic here. If you want to edit a tool, edit all_tools.py.

NOTE: tool_schemas() is a FUNCTION, not a constant, so that MCP tools
mounted into TOOLS at boot (after this module imports) are included in
every new Realtime session's tool list. Call tool_schemas() at session-
start time, not at import.
"""
from truman.tools.dispatch import realtime_schemas, dispatch


def tool_schemas() -> list[dict]:
    """Current tool list in OpenAI Realtime flat function-call format.
    Recomputed each call so late-mounted MCP tools are included."""
    return realtime_schemas()


def dispatch_tool(name: str, args: dict) -> str:
    return dispatch(name, args)
