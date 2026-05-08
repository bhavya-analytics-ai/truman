"""runtime.py — TRUMAN's awareness of where he's running.

Single source of truth for environment detection.
Used by self_awareness.py to inject runtime context into every LLM call.
"""
import os
from typing import Literal


def is_railway() -> bool:
    """True if running on Railway (env var set by Railway runtime)."""
    return bool(os.environ.get("RAILWAY_ENVIRONMENT"))


def is_local() -> bool:
    """True if NOT on Railway (Mac/dev environment)."""
    return not is_railway()


def db_location() -> str:
    """Where the SQLite DB lives in this runtime."""
    if os.path.isdir("/data"):
        return "/data/truman.db"
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "truman.db",
    )


def mac_bridge_status() -> Literal["connected", "offline", "unknown"]:
    """Whether the Mac bridge WebSocket is currently connected."""
    try:
        from truman.voice import orb
        return "connected" if getattr(orb, "_mac_ws", None) else "offline"
    except Exception:
        return "unknown"


def runtime_summary() -> dict:
    """One-shot snapshot of runtime context for self_awareness."""
    return {
        "location":   "railway" if is_railway() else "local",
        "db_path":    db_location(),
        "mac_bridge": mac_bridge_status(),
    }
