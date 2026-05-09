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

    # Persist user + assistant turns
    try:
        from truman.storage import db
        db.log_turn(session_id, "user", user_input)
        db.log_turn(session_id, "assistant", response)
    except Exception as e:
        print(f"[save] log_turn failed: {e}")

    # Async eval — log only, no retry blocking
    try:
        from truman.brain.eval import evaluate_response
        score, action, issues, reason = evaluate_response(user_input, response, complex_msg=False)
        print(f"[EVAL bg] score={score}  issues={issues}")
        try:
            from truman.storage import db
            import uuid
            db.log_eval(
                turn_id=str(uuid.uuid4()),
                session_id=session_id,
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
