"""
save.py — fire-and-forget turn persistence + async eval.

chat() calls enqueue_save() and returns immediately. A single daemon thread
persists turns and runs eval in the background. Never blocks the reply.
"""
import queue
import threading
from typing import Any

_QUEUE: "queue.Queue[dict | None]" = queue.Queue()
_STARTED = False
_LOCK = threading.Lock()


def _persist_turn(turn: dict[str, Any]) -> None:
    """Write turn to DB + run async eval. Failures logged, never raised."""
    session_id = turn.get("session_id", "default")
    user_input = turn.get("user_input", "")
    response = turn.get("response", "")
    model = turn.get("model", "")
    pool = turn.get("pool", "general")
    session_int: int | None = None

    # Persist user + assistant turns
    try:
        import uuid as _uuid2
        from truman.storage import db
        # session_id from chat() is a string (e.g. "default") — resolve to int
        session_int = db.get_or_create_session(session_id)
        db.log_turn(session_int, "user", user_input)
        db.log_turn(session_int, "assistant", response)
        # Write a synthetic trace event so the activity panel shows this turn
        latency_ms = turn.get("latency_ms", 0)
        tool_calls = turn.get("tool_calls", [])
        tool_names = ", ".join(t["name"] for t in tool_calls) if tool_calls else ""
        summary = f'"{user_input[:60]}" → {model} {latency_ms}ms' + (f' [{tool_names}]' if tool_names else '')
        db.log_trace(
            session_id=session_id,
            turn_id=str(_uuid2.uuid4()),
            node="chat",
            status="end",
            summary=summary,
            duration_ms=latency_ms,
        )
    except Exception as e:
        print(f"[save] log_turn failed: {e}")

    # Async eval — log only, no retry blocking
    try:
        import uuid as _uuid
        from truman.brain.eval import evaluate
        result = evaluate(str(_uuid.uuid4()), user_input, response)
        score = result.get("score", "good")
        action = result.get("action", "accept")
        issues = result.get("issues", [])
        reason = result.get("reason", "")
        print(f"[EVAL bg] score={score}  issues={issues}")
        try:
            from truman.storage import db
            db.log_eval(
                turn_id=str(_uuid.uuid4()),
                session_id=session_int,
                model=model,
                pool=pool,
                score=score,
                issues=issues,
                reason=reason,
                action="accept_async",
            )
        except Exception:
            pass
    except Exception as e:
        print(f"[save] eval failed: {e}")


def _worker() -> None:
    while True:
        turn = _QUEUE.get()
        if turn is None:
            return
        try:
            _persist_turn(turn)
        except Exception as e:
            print(f"[save] worker error: {e}")
        finally:
            _QUEUE.task_done()


def _start_worker() -> None:
    global _STARTED
    with _LOCK:
        if _STARTED:
            return
        t = threading.Thread(target=_worker, daemon=True, name="truman-save")
        t.start()
        _STARTED = True


def enqueue_save(turn: dict[str, Any]) -> None:
    """Hand off completed turn for background persistence + eval."""
    _start_worker()
    _QUEUE.put(turn)
