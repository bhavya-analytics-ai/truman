"""
chat.py — Claude-shape chat path. ONE LLM call per turn.

Replaces the 10-node LangGraph for the chat flow. Tools bound natively;
model decides when to use them. No regex tier router, no embedding step,
no mood classifier, no per-turn DB load.

Save + eval run in background — reply ships immediately.
"""
import time
from collections import defaultdict
from typing import Iterator

from truman.text.system_prompt import get_system_prompt
from truman.text.agent import _call_llm_with_tools, _is_complex
from truman.tools.all_tools import TOOLS
from truman.storage.save import enqueue_save

_HISTORY: dict[str, list[dict]] = defaultdict(list)
_HISTORY_WINDOW = 16


def _build_messages(user_input: str, session_id: str) -> list[dict]:
    msgs = [{"role": "system", "content": get_system_prompt()}]
    msgs.extend(_HISTORY[session_id][-_HISTORY_WINDOW:])
    msgs.append({"role": "user", "content": user_input})
    return msgs


def chat(user_input: str, session_id: str = "default", pool: str | None = None) -> dict:
    """
    Single-call chat. Returns {response, model, pool, tool_calls, latency_ms}.
    LLM has all native tools bound and decides when to fire them.
    """
    t0 = time.time()
    user_input = (user_input or "").strip()
    if not user_input:
        return {"response": "", "model": "none", "pool": "general", "tool_calls": [], "latency_ms": 0}

    messages = _build_messages(user_input, session_id)
    tool_map = {t.name: t for t in TOOLS}
    chosen_pool = pool or "general"

    raw, model_label, tool_calls = _call_llm_with_tools(
        messages, TOOLS, tool_map,
        complex_msg=_is_complex(user_input),
        pool=chosen_pool,
    )

    latency_ms = int((time.time() - t0) * 1000)
    response = (raw or "").strip()

    # Update in-memory history
    _HISTORY[session_id].append({"role": "user", "content": user_input})
    _HISTORY[session_id].append({"role": "assistant", "content": response})
    if len(_HISTORY[session_id]) > _HISTORY_WINDOW * 2:
        _HISTORY[session_id] = _HISTORY[session_id][-(_HISTORY_WINDOW * 2):]

    print(f"[CHAT] model={model_label}  pool={chosen_pool}  total={latency_ms/1000:.1f}s  tools={len(tool_calls)}")

    enqueue_save({
        "session_id": session_id,
        "user_input": user_input,
        "response": response,
        "model": model_label,
        "pool": chosen_pool,
        "tool_calls": tool_calls,
    })

    return {
        "response": response,
        "model": model_label,
        "pool": chosen_pool,
        "tool_calls": tool_calls,
        "latency_ms": latency_ms,
    }


def chat_stream(user_input: str, session_id: str = "default", pool: str | None = None) -> Iterator[dict]:
    """
    Streaming variant. Yields events:
      {"type": "token", "delta": "..."}
      {"type": "tool_call", "name": "...", "args": {...}}
      {"type": "done", "model": "...", "tool_calls": [...], "latency_ms": int}
    """
    result = chat(user_input, session_id=session_id, pool=pool)

    for tc in result["tool_calls"]:
        name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", str(tc))
        args = tc.get("args", {}) if isinstance(tc, dict) else {}
        yield {"type": "tool_call", "name": name, "args": args}

    for word in result["response"].split(" "):
        yield {"type": "token", "delta": word + " "}

    yield {
        "type": "done",
        "model": result["model"],
        "tool_calls": result["tool_calls"],
        "latency_ms": result["latency_ms"],
    }
