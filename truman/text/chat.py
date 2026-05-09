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
from truman.text.agent import _call_llm_with_tools, _call_llm_with_tools_stream, _is_complex
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
    Real streaming variant. Yields events:
      {"type": "token",           "delta": str}
      {"type": "tool_call_start", "name": str, "args": dict}
      {"type": "tool_call_end",   "name": str, "result": str, "elapsed_ms": int}
      {"type": "process",         "pool": str, "model": str}   ← emitted first
      {"type": "done",            "model": str, "pool": str,
                                  "tool_calls": list, "latency_ms": int}
    """
    import time as _time
    from truman.core.model_router import detect_pool

    t0 = _time.time()
    user_input = (user_input or "").strip()
    if not user_input:
        yield {"type": "done", "model": "none", "pool": "general", "tool_calls": [], "latency_ms": 0}
        return

    messages = _build_messages(user_input, session_id)
    tool_map  = {t.name: t for t in TOOLS}
    chosen_pool = pool or detect_pool(user_input)

    # Emit process strip info immediately so UI knows pool + rough model
    from truman.text.agent import _POOL_CHAT_MODELS
    model_hint = _POOL_CHAT_MODELS.get(chosen_pool, [("llama70", "llama70")])[0][1]
    yield {"type": "process", "pool": chosen_pool, "model": model_hint}

    full_response: list[str] = []
    tool_calls: list = []
    model_label = "none"

    for event in _call_llm_with_tools_stream(
        messages, TOOLS, tool_map,
        complex_msg=_is_complex(user_input),
        pool=chosen_pool,
    ):
        if event["type"] == "token":
            full_response.append(event["delta"])
        elif event["type"] == "done":
            tool_calls  = event["tool_calls"]
            model_label = event["model"]
        yield event

    response  = "".join(full_response).strip()
    latency_ms = int((_time.time() - t0) * 1000)

    # Update in-memory history
    _HISTORY[session_id].append({"role": "user",      "content": user_input})
    _HISTORY[session_id].append({"role": "assistant",  "content": response})
    if len(_HISTORY[session_id]) > _HISTORY_WINDOW * 2:
        _HISTORY[session_id] = _HISTORY[session_id][-(_HISTORY_WINDOW * 2):]

    print(f"[CHAT stream] model={model_label}  pool={chosen_pool}  "
          f"total={latency_ms/1000:.1f}s  tools={len(tool_calls)}")

    enqueue_save({
        "session_id": session_id,
        "user_input": user_input,
        "response":   response,
        "model":      model_label,
        "pool":       chosen_pool,
        "tool_calls": tool_calls,
    })
