"""
dispatch.py — Adapter layer bridging the canonical @tool definitions in
truman.tools.all_tools into the shapes the OpenAI Realtime API expects.

Realtime uses FLAT function-call schema (NOT the Chat Completions nested
form). Each entry has top-level keys: type, name, description, parameters.
Do NOT wrap name/description/parameters under an extra "function" key —
Realtime rejects that.
"""
from truman.tools.all_tools import TOOLS


def _by_name() -> dict:
    """Build the name→tool map fresh each call.

    MCP tools get appended to TOOLS at boot (after this module imports),
    so caching this at import time would miss them. Called per-dispatch —
    tiny list, dict comp is effectively free.
    """
    return {t.name: t for t in TOOLS}


def _strip_pydantic(obj):
    """Recursively strip pydantic-specific keys that OpenAI Realtime doesn't want."""
    drop = {"title", "$defs", "definitions"}
    if isinstance(obj, dict):
        return {k: _strip_pydantic(v) for k, v in obj.items() if k not in drop}
    if isinstance(obj, list):
        return [_strip_pydantic(x) for x in obj]
    return obj


def realtime_schemas() -> list[dict]:
    """Convert every @tool's args_schema into OpenAI Realtime function-call format.

    Output entries are flat:
      {"type": "function",
       "name": <str>,
       "description": <str>,
       "parameters": {"type": "object", "properties": {...}, "required": [...]}}

    Handles pydantic v1 (`schema()`) and v2 (`model_json_schema()`) transparently.
    Zero-arg tools yield empty properties + required.
    """
    schemas = []
    for t in TOOLS:
        if t.args_schema is None:
            params = {"type": "object", "properties": {}, "required": []}
        else:
            raw = (
                t.args_schema.model_json_schema()
                if hasattr(t.args_schema, "model_json_schema")
                else t.args_schema.schema()
            )
            raw = _strip_pydantic(raw)
            params = {
                "type": "object",
                "properties": raw.get("properties", {}),
                "required": raw.get("required", []),
            }
        schemas.append({
            "type": "function",
            "name": t.name,
            "description": t.description,
            "parameters": params,
        })
    return schemas


def dispatch(name: str, args: dict) -> str:
    """Invoke a canonical @tool by name. Returns the tool's string result, or a
    friendly error string if the tool is unknown or raises."""
    t = _by_name().get(name)
    if not t:
        return f"Unknown tool: {name}"
    try:
        return t.invoke(args or {})
    except Exception as e:
        return f"Tool error ({name}): {e}"
