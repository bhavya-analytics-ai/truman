"""
telegram.py — Truman's Telegram delivery channel (Phase 12)

One-way:  Truman → Om  (morning brief, goal nudges, idle alerts)
Two-way:  Om → Truman  (reply to bot → runs through agent → Truman replies on Telegram)

Setup (Om does once, 5 min):
  1. Telegram → @BotFather → /newbot → copy the token
  2. Message your new bot once so it can see your chat_id
  3. Add to .env:
       TELEGRAM_BOT_TOKEN=<token>
       TELEGRAM_CHAT_ID=<your chat id>
  4. ENABLE_TELEGRAM is already defaulted to 1 — no extra step

Buttons wired now (Phase 15 will hook them):
  send_message(text, buttons=[[{"text": "View Goals", "callback_data": "view_goals"}]])
"""
import os
import sys
import time
import threading

import requests

# ── Config (read at import time — config.py already loaded .env) ──────────────
_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
_ENABLE  = os.getenv("ENABLE_TELEGRAM", "1") == "1"
_BASE    = f"https://api.telegram.org/bot{_TOKEN}"

_last_update_id = 0
_poller_started = False
_poller_lock    = threading.Lock()


# ── Low-level API call ────────────────────────────────────────────────────────
def _api(method: str, timeout: int = 10, **kwargs) -> dict:
    """POST to Telegram Bot API. Returns parsed JSON or {}. Never raises."""
    if not _TOKEN:
        return {}
    try:
        r = requests.post(f"{_BASE}/{method}", json=kwargs, timeout=timeout)
        return r.json()
    except Exception as e:
        print(f"[Telegram] API error ({method}): {e}")
        return {}


# ── Public send ───────────────────────────────────────────────────────────────
def send_message(text: str, buttons: list = None) -> bool:
    """
    Send a message to Om's Telegram.

    buttons format (inline keyboard):
      [[{"text": "View Goals", "callback_data": "view_goals"},
        {"text": "Dismiss",    "callback_data": "dismiss"}]]
      Each inner list = one row. Wired now; Phase 15 hooks the callbacks.

    Returns True if Telegram confirmed ok=True.
    """
    if not _ENABLE or not _TOKEN or not _CHAT_ID:
        return False
    payload: dict = {
        "chat_id":    _CHAT_ID,
        "text":       text[:4096],  # Telegram limit
        "parse_mode": "Markdown",
    }
    if buttons:
        payload["reply_markup"] = {
            "inline_keyboard": [
                [{"text": b["text"], "callback_data": b["callback_data"]} for b in row]
                for row in buttons
            ]
        }
    resp = _api("sendMessage", **payload)
    ok = resp.get("ok", False)
    if not ok:
        print(f"[Telegram] sendMessage failed: {resp.get('description', resp)}")
    return ok


# ── Incoming message handler ──────────────────────────────────────────────────
def _handle_text(text: str, agent_fn):
    """Om replied on Telegram → run through agent → send reply back on Telegram."""
    try:
        result = agent_fn(text, mood="", session_id="telegram")
        response = result["response"] if isinstance(result, dict) else str(result)
        send_message(response)
        # Also push to dashboard via SSE so it syncs to all devices
        try:
            from truman.storage.notifications import push_turn
            push_turn("user",      text,     "telegram")
            push_turn("assistant", response, "telegram")
        except Exception:
            pass
    except Exception as e:
        send_message(f"_(error: {e})_")


def _handle_callback(cb: dict):
    """Inline button click — acknowledge it (removes spinner). Phase 15 adds logic."""
    cb_id = cb.get("id", "")
    data  = cb.get("data", "")
    _api("answerCallbackQuery", callback_query_id=cb_id)
    print(f"[Telegram] Button callback: {data!r}")
    # Phase 15 will wire view_goals, approve, edit, skip, etc. here


# ── Update poller ─────────────────────────────────────────────────────────────
def start_poller(agent_fn):
    """
    Start the Telegram long-poll daemon. Call once from main.py / main_cloud.py.
    Idempotent — won't start a second poller if already running.
    """
    global _poller_started
    with _poller_lock:
        if _poller_started:
            return
        if not _ENABLE or not _TOKEN or not _CHAT_ID:
            print("[Telegram] poller skipped — TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set.")
            return
        _poller_started = True

    def _run():
        global _last_update_id
        print("[Telegram] Poller started. Waiting for messages from Om...")
        while True:
            try:
                resp = _api("getUpdates", timeout=35,
                            offset=_last_update_id + 1,
                            allowed_updates=["message", "callback_query"])
                updates = resp.get("result") or []
                for u in updates:
                    _last_update_id = u["update_id"]

                    # Incoming text message
                    msg     = u.get("message") or {}
                    text    = (msg.get("text") or "").strip()
                    chat_id = str((msg.get("chat") or {}).get("id", ""))
                    if text and chat_id == str(_CHAT_ID):
                        threading.Thread(
                            target=_handle_text,
                            args=(text, agent_fn),
                            daemon=True,
                        ).start()

                    # Inline button callback
                    cb = u.get("callback_query") or {}
                    if cb:
                        _handle_callback(cb)

            except Exception as e:
                print(f"[Telegram] Poll error: {e}")
                time.sleep(5)

    threading.Thread(target=_run, daemon=True, name="telegram-poller").start()
