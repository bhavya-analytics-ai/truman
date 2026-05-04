"""
session_state.py — Sticky attachment context across turns.

Attachments are "sticky" for up to STICKY_TTL turns after upload.
The model keeps seeing the file/image without Om re-uploading it each turn.

Commands (detected in user_input):
  "look again"  / "re-read it" / "check again"  → reset TTL to full (re-pins the file)
  "drop file"   / "remove file" / "clear file"   → removes all sticky attachments for session
  "drop image"  / "clear image"                  → removes only image attachments

State stored in-process (no DB needed — Railway restarts are fine, session is ephemeral).
"""
from __future__ import annotations
import threading
import time

STICKY_TTL = 10   # turns an attachment stays active after upload

# ── In-process store ──────────────────────────────────────────────────────────
# session_id → list of {"attach_id": str, "mime": str, "filename": str, "turns_left": int}
_store: dict[str, list[dict]] = {}
_lock  = threading.Lock()


# ── Public API ────────────────────────────────────────────────────────────────

def register_attachments(session_id: str, attach_ids: list[str]) -> None:
    """
    Called at the start of a turn when new attach_ids arrive (fresh upload).
    Adds them to the sticky store with full TTL.
    Existing attachments keep their current TTL (not reset).
    """
    if not attach_ids:
        return
    with _lock:
        existing = {e["attach_id"] for e in _store.get(session_id, [])}
        for aid in attach_ids:
            if aid in existing:
                continue   # already tracked
            meta = _load_meta(aid)
            _store.setdefault(session_id, []).append({
                "attach_id": aid,
                "mime":      meta.get("mime", ""),
                "filename":  meta.get("filename", ""),
                "turns_left": STICKY_TTL,
            })


def get_sticky_ids(session_id: str) -> list[str]:
    """
    Return all currently active attach_ids for a session (TTL > 0).
    Does NOT decrement the counter — call tick_turn() after the LLM responds.
    """
    with _lock:
        entries = _store.get(session_id, [])
        return [e["attach_id"] for e in entries if e["turns_left"] > 0]


def tick_turn(session_id: str) -> None:
    """
    Decrement TTL for all attachments in the session by 1.
    Remove expired entries (TTL reaches 0).
    Call this AFTER a successful LLM response.
    """
    with _lock:
        entries = _store.get(session_id, [])
        alive = []
        for e in entries:
            e["turns_left"] -= 1
            if e["turns_left"] > 0:
                alive.append(e)
        if alive:
            _store[session_id] = alive
        elif session_id in _store:
            del _store[session_id]


def reset_ttl(session_id: str) -> None:
    """
    Reset TTL to full for all attachments in the session ("look again" command).
    """
    with _lock:
        for e in _store.get(session_id, []):
            e["turns_left"] = STICKY_TTL


def clear_attachments(session_id: str, kind: str = "all") -> int:
    """
    Remove sticky attachments for a session.
    kind: "all" | "image" | "file"
    Returns count removed.
    """
    with _lock:
        entries = _store.get(session_id, [])
        if kind == "all":
            removed = len(entries)
            _store.pop(session_id, None)
            return removed
        keep, drop = [], 0
        for e in entries:
            is_image = e["mime"].startswith("image/")
            if kind == "image" and is_image:
                drop += 1
            elif kind == "file" and not is_image:
                drop += 1
            else:
                keep.append(e)
        _store[session_id] = keep
        return drop


def get_session_summary(session_id: str) -> list[dict]:
    """
    Return a snapshot of active attachments for the dashboard context tray.
    Each item: {"attach_id", "filename", "mime", "turns_left"}
    """
    with _lock:
        return [dict(e) for e in _store.get(session_id, []) if e["turns_left"] > 0]


# ── Command detection ─────────────────────────────────────────────────────────

import re as _re

_LOOK_AGAIN_RE = _re.compile(
    r"\b(look again|re-?read it|re-?read the (file|doc|image|pdf|sheet)|check again|"
    r"go back to (the )?(file|image|doc|pdf)|analyze again|re-?analyze)\b",
    _re.I,
)

_DROP_FILE_RE = _re.compile(
    r"\b(drop|clear|remove|forget) (the )?(file|doc|document|pdf|sheet|excel|csv|word)\b",
    _re.I,
)

_DROP_IMAGE_RE = _re.compile(
    r"\b(drop|clear|remove|forget) (the )?(image|photo|pic|screenshot|picture)\b",
    _re.I,
)

_DROP_ALL_RE = _re.compile(
    r"\b(drop|clear|remove|forget) (all )?(attachment|file|image)s?\b",
    _re.I,
)


def process_commands(session_id: str, user_input: str) -> str | None:
    """
    Check user_input for sticky-attachment commands.
    Executes the command if found.
    Returns a short acknowledgement string if a command was processed, else None.
    """
    if _LOOK_AGAIN_RE.search(user_input):
        reset_ttl(session_id)
        return None   # silent — the re-send of attach_ids is the acknowledgement

    if _DROP_ALL_RE.search(user_input):
        n = clear_attachments(session_id, "all")
        return f"_(dropped {n} attachment{'s' if n != 1 else ''})_" if n else None

    if _DROP_FILE_RE.search(user_input):
        n = clear_attachments(session_id, "file")
        return f"_(dropped {n} file attachment{'s' if n != 1 else ''})_" if n else None

    if _DROP_IMAGE_RE.search(user_input):
        n = clear_attachments(session_id, "image")
        return f"_(dropped {n} image{'s' if n != 1 else ''})_" if n else None

    return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_meta(attach_id: str) -> dict:
    try:
        from truman.multimodal.loader import get_attachment_meta
        return get_attachment_meta(attach_id) or {}
    except Exception:
        return {}
