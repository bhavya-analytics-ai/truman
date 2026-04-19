"""
realtime_tools.py — Thin adapter.

Canonical tool implementations live in truman.tools.all_tools. Schema
conversion + dispatch live in truman.tools.dispatch. This file exists
only so that realtime.py's existing import surface (`TOOL_SCHEMAS`,
`dispatch_tool`) keeps working without changes.

No tool logic here. If you want to edit a tool, edit all_tools.py.
"""
from truman.tools.dispatch import realtime_schemas, dispatch


TOOL_SCHEMAS = realtime_schemas()


def dispatch_tool(name: str, args: dict) -> str:
    return dispatch(name, args)
