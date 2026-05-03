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


# ── Incoming message handlers ─────────────────────────────────────────────────
def _handle_text(text: str, agent_fn):
    """Om replied on Telegram → run through agent → send reply back on Telegram."""
    try:
        result = agent_fn(text, mood="", session_id="telegram")
        response = result["response"] if isinstance(result, dict) else str(result)
        send_message(response)
        try:
            from truman.storage.notifications import push_turn
            push_turn("user",      text,     "telegram")
            push_turn("assistant", response, "telegram")
        except Exception:
            pass
    except Exception as e:
        send_message(f"_(error: {e})_")


def _download_tg_file(file_id: str) -> bytes | None:
    """Download a file from Telegram by file_id. Returns bytes or None."""
    try:
        info = _api("getFile", file_id=file_id)
        file_path = (info.get("result") or {}).get("file_path", "")
        if not file_path:
            return None
        url = f"https://api.telegram.org/file/bot{_TOKEN}/{file_path}"
        r = requests.get(url, timeout=20)
        return r.content if r.status_code == 200 else None
    except Exception as e:
        print(f"[Telegram] File download failed: {e}")
        return None


def _handle_photo(photo_list: list, caption: str, agent_fn):
    """Largest photo → vision pool → reply on Telegram."""
    if os.environ.get("ENABLE_TG_MEDIA", "1") != "1":
        send_message("_(media support disabled)_")
        return
    try:
        import base64
        # largest size is last in the list
        file_id = photo_list[-1]["file_id"]
        data = _download_tg_file(file_id)
        if not data:
            send_message("_(couldn't download that photo)_")
            return
        b64 = base64.b64encode(data).decode()
        prompt = caption or "what's in this image? describe it."
        # use vision pool via agent
        vision_prompt = (
            f"[Image attached as base64 PNG — analyze it]\n"
            f"User request: {prompt}\n"
            f"Image data (base64): {b64[:200]}...[truncated for routing, full image attached]"
        )
        # Simpler: describe the image using the vision pool directly
        try:
            from truman.core.model_router import run_with_pool
            from langchain_core.messages import HumanMessage
            msg = HumanMessage(content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ])
            result = run_with_pool([msg], pool="vision", user_message=prompt)
            response = result["content"]
        except Exception as e:
            response = f"_(vision error: {e})_"
        send_message(response[:4096])
        try:
            from truman.storage.notifications import push_turn
            push_turn("user",      f"[photo] {caption}" if caption else "[photo]", "telegram")
            push_turn("assistant", response, "telegram")
        except Exception:
            pass
    except Exception as e:
        send_message(f"_(photo error: {e})_")


def _handle_document(doc: dict, caption: str, agent_fn):
    """Doc/PDF → extract text → run through agent → reply on Telegram."""
    if os.environ.get("ENABLE_TG_MEDIA", "1") != "1":
        send_message("_(media support disabled)_")
        return
    try:
        import io
        file_id   = doc.get("file_id", "")
        mime_type = doc.get("mime_type", "")
        file_name = doc.get("file_name", "file")
        data = _download_tg_file(file_id)
        if not data:
            send_message("_(couldn't download that file)_")
            return
        # extract text based on mime type
        text = ""
        if "pdf" in mime_type:
            try:
                import pdfplumber
                with pdfplumber.open(io.BytesIO(data)) as pdf:
                    text = "\n".join(p.extract_text() or "" for p in pdf.pages)
            except Exception:
                text = data.decode("utf-8", errors="replace")
        elif "text" in mime_type or file_name.endswith((".txt", ".md", ".py", ".js", ".json", ".csv")):
            text = data.decode("utf-8", errors="replace")
        else:
            text = data.decode("utf-8", errors="replace")

        if not text.strip():
            send_message("_(couldn't extract text from that file)_")
            return

        prompt = f"{caption or 'summarize this document'}:\n\n{text[:8000]}"
        result = agent_fn(prompt, mood="", session_id="telegram")
        response = result["response"] if isinstance(result, dict) else str(result)
        send_message(response[:4096])
        try:
            from truman.storage.notifications import push_turn
            push_turn("user",      f"[doc: {file_name}] {caption}" if caption else f"[doc: {file_name}]", "telegram")
            push_turn("assistant", response, "telegram")
        except Exception:
            pass
    except Exception as e:
        send_message(f"_(doc error: {e})_")


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
                            allowed_updates=["message", "callback_query", "channel_post"])
                updates = resp.get("result") or []
                for u in updates:
                    _last_update_id = u["update_id"]

                    # Incoming message
                    msg     = u.get("message") or {}
                    chat_id = str((msg.get("chat") or {}).get("id", ""))
                    if chat_id != str(_CHAT_ID):
                        continue

                    caption = (msg.get("caption") or "").strip()
                    text    = (msg.get("text") or "").strip()
                    photo   = msg.get("photo")     # list of sizes or None
                    doc     = msg.get("document")  # dict or None

                    if text:
                        threading.Thread(
                            target=_handle_text, args=(text, agent_fn), daemon=True
                        ).start()
                    elif photo:
                        threading.Thread(
                            target=_handle_photo, args=(photo, caption, agent_fn), daemon=True
                        ).start()
                    elif doc:
                        threading.Thread(
                            target=_handle_document, args=(doc, caption, agent_fn), daemon=True
                        ).start()

                    # Inline button callback
                    cb = u.get("callback_query") or {}
                    if cb:
                        _handle_callback(cb)

            except Exception as e:
                print(f"[Telegram] Poll error: {e}")
                time.sleep(5)

    threading.Thread(target=_run, daemon=True, name="telegram-poller").start()
