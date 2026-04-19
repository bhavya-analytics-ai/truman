"""
mcp_bridge.py — Bridge between Truman's @tool-based tool layer and
external MCP (Model Context Protocol) servers.

Architecture
  - One daemon thread owns a single asyncio event loop (lazy-started on
    first mount_server call).
  - Calls from Truman's threaded world (LangChain agent, Realtime
    dispatcher) marshal to the loop via asyncio.run_coroutine_threadsafe.
  - A single AsyncExitStack (held inside the loop thread) manages
    stdio_client + ClientSession lifecycles for every mounted server.
    Streams stay open for the life of the Truman process; subprocesses
    get cleaned up when the daemon thread dies with the interpreter.

JSON-schema → pydantic mapper
  Handles: string, integer, number, boolean, array, object, plus
  required vs optional (based on `required` list). Descriptions
  preserved.
  Does NOT handle: $ref, oneOf, anyOf, allOf, enum, nullable, nested
  object field schemas. That's good enough for the filesystem MCP
  server and most simple MCP servers. If you mount a complex MCP
  server (say a DB client with rich union types) and see LLM arg
  errors like "invalid arguments" or tools calling with wrong shapes,
  upgrade this mapper — likely by using `datamodel-code-generator` or
  `json-schema-to-pydantic` instead of this hand-rolled version.

Errors
  Any exception during tool invocation returns
    "MCP error ({prefixed_name}): {e}"
  as a regular string result — Truman never crashes from a misbehaving
  MCP server.
"""
import asyncio
import threading
from contextlib import AsyncExitStack
from typing import Any, Optional

from pydantic import Field, create_model
from langchain_core.tools import StructuredTool


# ── Event-loop thread (lazy, singleton) ───────────────────────────────────────
_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_thread: Optional[threading.Thread] = None
_loop_ready = threading.Event()
_stack: Optional[AsyncExitStack] = None
_sessions: dict = {}
_mount_lock = threading.Lock()


def _start_loop_once() -> None:
    """Spin up the MCP asyncio loop on first call. Idempotent."""
    global _loop, _loop_thread
    if _loop is not None:
        return

    def _run() -> None:
        global _loop
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        _loop_ready.set()
        _loop.run_forever()

    _loop_thread = threading.Thread(target=_run, daemon=True, name="mcp-loop")
    _loop_thread.start()
    _loop_ready.wait(timeout=5.0)
    if _loop is None:
        raise RuntimeError("MCP event loop failed to start within 5 seconds")


def _run_coro(coro, timeout: float = 30.0):
    """Submit a coroutine to the MCP loop from any thread; block until done."""
    _start_loop_once()
    fut = asyncio.run_coroutine_threadsafe(coro, _loop)
    return fut.result(timeout=timeout)


# ── Shared AsyncExitStack (lives inside the loop) ─────────────────────────────
async def _ensure_stack() -> AsyncExitStack:
    """Create the process-wide AsyncExitStack on first use.
    Must be called from INSIDE the loop thread (i.e. via _run_coro)."""
    global _stack
    if _stack is None:
        _stack = AsyncExitStack()
        await _stack.__aenter__()
    return _stack


# ── JSON Schema → pydantic mapper ─────────────────────────────────────────────
_TYPE_MAP: dict[str, Any] = {
    "string":  str,
    "integer": int,
    "number":  float,
    "boolean": bool,
    "array":   list,
    "object":  dict,
}


def _json_schema_to_pydantic(model_name: str, schema: dict):
    """Convert a JSON-schema object definition to a pydantic model usable
    as args_schema on a StructuredTool.

    Scope: primitives + array + object only. See module docstring for
    known limitations.
    """
    schema = schema or {}
    props: dict = schema.get("properties", {}) or {}
    required: set = set(schema.get("required", []) or [])
    fields: dict = {}

    for pname, pschema in props.items():
        pschema = pschema or {}
        ptype = _TYPE_MAP.get(pschema.get("type"), str)  # unknown types → str, safe default
        desc = pschema.get("description", "") or ""
        if pname in required:
            fields[pname] = (ptype, Field(..., description=desc))
        else:
            fields[pname] = (Optional[ptype], Field(default=None, description=desc))

    if not fields:
        # pydantic needs at least one field to build a model. Zero-arg MCP tools
        # get a synthetic placeholder that we strip before calling the server.
        return create_model(model_name, _unused=(Optional[str], None))

    return create_model(model_name, **fields)


# ── CallToolResult → string ───────────────────────────────────────────────────
def _extract_text(result) -> str:
    """Join text content blocks from a CallToolResult into a single string.
    Falls back to str(result) if no text blocks present."""
    blocks = getattr(result, "content", None) or []
    texts: list[str] = []
    for b in blocks:
        t = getattr(b, "text", None)
        if t is not None:
            texts.append(t)
            continue
        if isinstance(b, dict) and "text" in b:
            texts.append(b["text"])
    return "\n".join(texts) if texts else str(result)


# ── Mount API ─────────────────────────────────────────────────────────────────
def mount_server(server_id: str, command: str, args: list[str]) -> list[StructuredTool]:
    """Spawn an MCP server subprocess and wrap every tool it exposes as a
    LangChain StructuredTool.

    Tool names are prefixed: `{server_id}__{original_tool_name}` so mounts
    from different servers don't collide.

    Called once per server at Truman boot (from main.py). Returned tools
    are meant to be extended into truman.tools.all_tools.TOOLS by the caller.
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def _mount():
        stack = await _ensure_stack()
        params = StdioServerParameters(command=command, args=args)
        transport = await stack.enter_async_context(stdio_client(params))
        read, write = transport
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        list_result = await session.list_tools()
        _sessions[server_id] = session
        return list_result.tools

    with _mount_lock:
        mcp_tools = _run_coro(_mount(), timeout=60.0)

    return [_wrap_tool(server_id, mt) for mt in mcp_tools]


def _wrap_tool(server_id: str, mcp_tool) -> StructuredTool:
    """Turn one mcp.types.Tool into a LangChain StructuredTool."""
    original_name = mcp_tool.name
    prefixed = f"{server_id}__{original_name}"
    raw_schema = getattr(mcp_tool, "inputSchema", None) or {}
    args_model = _json_schema_to_pydantic(f"{prefixed}_args", raw_schema)
    description = (getattr(mcp_tool, "description", "") or f"MCP tool from {server_id}.")[:1024]

    def _call(**kwargs) -> str:
        # drop our synthetic placeholder and any None optionals — MCP servers
        # generally prefer absent keys over explicit null.
        kwargs = {k: v for k, v in kwargs.items() if k != "_unused" and v is not None}

        async def _invoke():
            session = _sessions.get(server_id)
            if session is None:
                raise RuntimeError(f"No live MCP session for '{server_id}'")
            return await session.call_tool(original_name, arguments=kwargs)

        try:
            result = _run_coro(_invoke(), timeout=60.0)
            return _extract_text(result)
        except Exception as e:
            return f"MCP error ({prefixed}): {e}"

    return StructuredTool.from_function(
        func=_call,
        name=prefixed,
        description=description,
        args_schema=args_model,
    )
