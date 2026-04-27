"""
notifications.py — In-process push queue for server → browser notifications.
orb.py reads from this queue via SSE. Any module can push to it.
"""
import threading
import time

_queue: list[dict] = []
_lock  = threading.Lock()
_listeners: list = []   # SSE generator queues
_listeners_lock = threading.Lock()

import queue as _q_mod

def push(message: str, kind: str = "info"):
    """Push a notification to all listening SSE clients."""
    payload = {"message": message, "kind": kind, "ts": time.time()}
    with _listeners_lock:
        for q in _listeners:
            try:
                q.put_nowait(payload)
            except Exception:
                pass


def subscribe():
    """Return a queue that will receive pushed notifications. Call unsubscribe() when done."""
    q = _q_mod.Queue()
    with _listeners_lock:
        _listeners.append(q)
    return q


def unsubscribe(q):
    with _listeners_lock:
        try:
            _listeners.remove(q)
        except ValueError:
            pass
