"""
imessage_poller.py — Truman's iMessage intake (Phase 15B)

Mac-only: reads ~/Library/Messages/chat.db every 60s.
Smart triage: only forwards messages worth Om's attention.
AppleScript send: auto-sends approved drafts back via Messages app.

Kill switch: ENABLE_IMESSAGE=0 (default off — flip to 1 to activate)
VIP auto-reply: IMESSAGE_VIP_THRESHOLD=0 (0=always ask, N=auto-reply after N approvals)

Triage rules (message is forwarded if ANY true):
  - Sender is in Om's contacts (has a real name, not just a number)
  - Contains a question (?)
  - Contains urgent keywords: urgent, asap, deadline, important, call me, help
  - Sender already has ≥1 prior conversation in boss_messages
  Group chats: summarized once/day, not forwarded individually.

VIP auto-reply:
  - IMESSAGE_VIP_THRESHOLD > 0: after that many approvals for a contact, auto-send
    the LLM draft without asking Om. Daily digest at 11pm lists what was auto-sent.
"""

import os
import re
import sqlite3
import subprocess
import threading
import time
import datetime
from pathlib import Path

_ENABLE        = os.getenv("ENABLE_IMESSAGE", "0") == "1"
_VIP_THRESHOLD = int(os.getenv("IMESSAGE_VIP_THRESHOLD", "0"))
_PUSHCUT_URL   = os.getenv("PUSHCUT_URL", "")        # Pushcut webhook → iOS "Send iMessage" shortcut
_DB_PATH       = Path.home() / "Library" / "Messages" / "chat.db"
_POLL_SECS     = 60

# Track which message ROWIDs we've already processed (resets on restart — use DB watermark)
_seen_rowids: set = set()
_started = False
_lock    = threading.Lock()

_URGENT_KW = re.compile(
    r"\b(urgent|asap|deadline|important|call me|help|emergency|need you|please respond)\b",
    re.I,
)


# ── Send paths ───────────────────────────────────────────────────────────────

def send_imessage_pushcut(handle: str, text: str) -> bool:
    """
    Send iMessage via Pushcut webhook → triggers 'Send iMessage' Shortcut on Om's iPhone.
    Railway-compatible: no Mac needed. Requires PUSHCUT_URL in env.
    Pushcut input format: "handle|||text"
    """
    if not _PUSHCUT_URL or not handle or not text:
        return False
    try:
        import requests
        r = requests.post(
            _PUSHCUT_URL,
            json={"input": f"{handle}|||{text}"},
            timeout=10,
        )
        ok = r.status_code == 200
        if not ok:
            print(f"[iMessage] Pushcut webhook returned {r.status_code}: {r.text[:100]}")
        return ok
    except Exception as e:
        print(f"[iMessage] Pushcut send error: {e}")
        return False


def send_imessage(handle: str, text: str) -> bool:
    """
    Send an iMessage. Tries Pushcut first (Railway-compatible), then AppleScript (Mac only).
    handle — phone (+12223334444) or email (foo@bar.com)
    """
    if not handle or not text:
        return False
    # Primary: Pushcut (works on Railway, no Mac required)
    if _PUSHCUT_URL:
        ok = send_imessage_pushcut(handle, text)
        if ok:
            return True
        print("[iMessage] Pushcut failed — trying AppleScript fallback")
    # Fallback: AppleScript (Mac only)
    safe_text = text.replace('"', '\\"')
    script = f'''
tell application "Messages"
    set targetService to 1st account whose service type = iMessage
    set targetBuddy to participant "{handle}" of targetService
    send "{safe_text}" to targetBuddy
end tell
'''
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, timeout=15, text=True
        )
        if result.returncode != 0:
            print(f"[iMessage] AppleScript error: {result.stderr.strip()}")
            return False
        return True
    except Exception as e:
        print(f"[iMessage] AppleScript send error: {e}")
        return False


# ── Triage ────────────────────────────────────────────────────────────────────

def _is_important(sender: str, text: str, is_group: bool) -> bool:
    """Returns True if this message deserves Om's attention."""
    if is_group:
        return False   # group chats → daily summary only (not yet built)
    if not text or len(text.strip()) < 3:
        return False
    # Urgent keywords always forward
    if _URGENT_KW.search(text):
        return True
    # Contains a question
    if "?" in text:
        return True
    # Named contact (has letters, not just digits)
    if sender and re.search(r"[a-zA-Z]", sender):
        return True
    return False


# ── VIP lookup ────────────────────────────────────────────────────────────────

def _get_vip_approval_count(identifier: str) -> int:
    """How many times Om has approved a reply to this contact."""
    try:
        from truman.storage import db
        return db.get_vip_approval_count(identifier)
    except Exception:
        return 0


def _increment_vip_count(identifier: str):
    try:
        from truman.storage import db
        db.increment_vip_approval_count(identifier)
    except Exception:
        pass


# ── Core poll ────────────────────────────────────────────────────────────────

def _poll_once():
    """Read new messages from chat.db and forward important ones."""
    global _seen_rowids
    if not _DB_PATH.exists():
        print("[iMessage] chat.db not found — are you on Mac with Messages?")
        return

    try:
        # Read-only open (WAL mode safe for concurrent Messages app access)
        con = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True, timeout=5)
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        # Get messages from last 5 minutes that we haven't seen
        since = time.time() - (5 * 60)
        # iMessage stores date as nanoseconds since 2001-01-01
        APPLE_EPOCH_OFFSET = 978307200   # 2001-01-01 in Unix time
        apple_since = int((since - APPLE_EPOCH_OFFSET) * 1e9)

        rows = cur.execute("""
            SELECT
                m.ROWID,
                m.text,
                m.is_from_me,
                m.date,
                COALESCE(h.id, '') AS handle_id,
                COALESCE(h.uncanonicalized_id, h.id, '') AS display_handle,
                c.chat_identifier,
                c.display_name,
                c.style   -- 43=group, 45=individual
            FROM message m
            LEFT JOIN handle h ON h.ROWID = m.handle_id
            LEFT JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            LEFT JOIN chat c ON c.ROWID = cmj.chat_id
            WHERE m.is_from_me = 0
              AND m.date > ?
              AND m.text IS NOT NULL
              AND m.text != ''
            ORDER BY m.date ASC
        """, (apple_since,)).fetchall()

        con.close()

        for row in rows:
            rowid = row["ROWID"]
            if rowid in _seen_rowids:
                continue
            _seen_rowids.add(rowid)

            text         = (row["text"] or "").strip()
            handle_id    = row["handle_id"]        # +12223334444 or email
            display_name = row["display_name"] or ""   # group name if any
            chat_id      = row["chat_identifier"] or handle_id
            is_group     = row["style"] == 43
            # Sender display: use group name or handle
            sender_label = display_name if is_group else handle_id

            if not text:
                continue

            if not _is_important(sender_label, text, is_group):
                continue

            # VIP auto-reply check
            approval_count = _get_vip_approval_count(handle_id)
            if _VIP_THRESHOLD > 0 and approval_count >= _VIP_THRESHOLD:
                _auto_reply(handle_id, sender_label, text)
            else:
                _forward_to_boss_handler(handle_id, sender_label, text)

    except Exception as e:
        print(f"[iMessage] poll error: {e}")


def _forward_to_boss_handler(handle: str, label: str, text: str):
    """Send to boss_handler → Truman drafts → Telegram [Approve][Edit][Skip]."""
    try:
        from truman.integrations.boss_handler import handle_incoming
        handle_incoming(label or handle, text, source="imessage", extra={"handle": handle})
    except Exception as e:
        print(f"[iMessage] forward error: {e}")


def _auto_reply(handle: str, label: str, text: str):
    """VIP auto-reply: draft + send without asking Om."""
    try:
        from truman.integrations.boss_handler import _draft_reply
        draft = _draft_reply(label or handle, text)
        if not draft or draft.startswith("_("):
            # Draft failed — fall back to asking
            _forward_to_boss_handler(handle, label, text)
            return
        ok = send_imessage(handle, draft)
        if ok:
            # Log it
            from truman.storage import db
            msg_id = db.save_boss_message("imessage", label or handle, text, extra={"handle": handle, "auto_reply": True})
            db.set_boss_draft(msg_id, draft)
            db.set_boss_status(msg_id, "auto_approved")
            _increment_vip_count(handle)
            print(f"[iMessage] VIP auto-replied to {handle}: {draft[:60]}")
            # Notify Om silently via Telegram
            try:
                from truman.delivery.telegram import send_message
                send_message(
                    f"🤖 *Auto-replied to {label or handle}*\n"
                    f"Their message: _{text[:100]}_\n"
                    f"My reply: `{draft}`"
                )
            except Exception:
                pass
        else:
            # Send failed — fall back to asking
            _forward_to_boss_handler(handle, label, text)
    except Exception as e:
        print(f"[iMessage] auto_reply error: {e}")
        _forward_to_boss_handler(handle, label, text)


# ── Start daemon ──────────────────────────────────────────────────────────────

def start():
    """Start the iMessage poller daemon. Call from proactive.start_all()."""
    global _started
    with _lock:
        if _started:
            return
        if not _ENABLE:
            print("[iMessage] poller disabled (ENABLE_IMESSAGE=0)")
            return
        if not _DB_PATH.exists():
            print(f"[iMessage] chat.db not found at {_DB_PATH} — skipping.")
            return
        _started = True

    def _run():
        print(f"[iMessage] Poller started (poll every {_POLL_SECS}s, VIP threshold={_VIP_THRESHOLD}).")
        while True:
            try:
                _poll_once()
            except Exception as e:
                print(f"[iMessage] loop error: {e}")
            time.sleep(_POLL_SECS)

    threading.Thread(target=_run, daemon=True, name="imessage-poller").start()
