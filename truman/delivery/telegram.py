"""
telegram.py — Truman's Telegram delivery channel (Phase 12)

One-way:  Truman → Om  (morning brief, goal nudges, idle alerts)
Two-way:  Om → Truman  (reply to bot → runs through agent → Truman replies on Telegram)

Phase 15B additions:
  - [✅ Approve] [✏️ Edit] [⏭ Skip] inline buttons for WhatsApp/Gmail/iMessage
  - /status  — shows system health (WA bridge, iMessage, Gmail poller, Railway)
  - /pause   — pauses Truman agent (TRUMAN_PAUSED=1)
  - /resume  — resumes Truman agent
  - /vip     — shows VIP approval counts

Setup (Om does once, 5 min):
  1. Telegram → @BotFather → /newbot → copy the token
  2. Message your new bot once so it can see your chat_id
  3. Add to .env:
       TELEGRAM_BOT_TOKEN=<token>
       TELEGRAM_CHAT_ID=<your chat id>
  4. ENABLE_TELEGRAM is already defaulted to 1 — no extra step
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
_pending_edit: dict = {}   # chat_id → msg_id waiting for edit reply


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
      Each inner list = one row.

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


# ── Control commands ──────────────────────────────────────────────────────────
def _handle_command(text: str):
    """Handle /commands from Om."""
    cmd = text.strip().lower().split()[0]

    if cmd == "/status":
        lines = ["*Truman System Status*\n"]

        # Agent paused?
        paused = os.environ.get("TRUMAN_PAUSED", "0") == "1"
        lines.append(f"🤖 Agent: {'⏸ PAUSED' if paused else '✅ running'}")

        # WhatsApp bridge
        try:
            from truman.integrations.whatsapp_bridge import bridge_state
            wa = bridge_state()
            icon = "✅" if wa == "CONNECTED" else ("📱" if wa == "QR_PENDING" else "❌")
            lines.append(f"{icon} WA bridge: {wa}")
        except Exception:
            lines.append("❌ WA bridge: not installed")

        # iMessage
        imsg_on = os.environ.get("ENABLE_IMESSAGE", "0") == "1"
        lines.append(f"{'✅' if imsg_on else '⏸'} iMessage poller: {'on' if imsg_on else 'off (ENABLE_IMESSAGE=0)'}")

        # Gmail poller
        gmail_on = os.environ.get("ENABLE_GMAIL_POLLING", "0") == "1"
        lines.append(f"{'✅' if gmail_on else '⏸'} Gmail poller: {'on' if gmail_on else 'off (ENABLE_GMAIL_POLLING=0)'}")

        # Boss flow
        boss_on = os.environ.get("ENABLE_BOSS_FLOW", "0") == "1"
        lines.append(f"{'✅' if boss_on else '⏸'} Boss flow: {'on' if boss_on else 'off (ENABLE_BOSS_FLOW=0)'}")

        # VIP threshold
        vip_t = os.environ.get("IMESSAGE_VIP_THRESHOLD", "0")
        lines.append(f"{'🤖' if vip_t != '0' else '⏸'} VIP auto-reply: threshold={vip_t} ({'enabled' if vip_t != '0' else 'disabled'})")

        # Pending edits
        if _pending_edit:
            lines.append(f"✏️ Pending edit for msg #{list(_pending_edit.values())[0]}")

        send_message("\n".join(lines))

    elif cmd == "/pause":
        os.environ["TRUMAN_PAUSED"] = "1"
        send_message("⏸ *Truman paused.* He won't respond to messages until you /resume.")

    elif cmd == "/resume":
        os.environ["TRUMAN_PAUSED"] = "0"
        send_message("▶️ *Truman resumed.* Back to normal.")

    elif cmd == "/vip":
        try:
            from truman.storage import db
            contacts = db.list_vip_contacts()
            if not contacts:
                send_message("No VIP contacts yet. Approvals build up over time.")
                return
            threshold = int(os.environ.get("IMESSAGE_VIP_THRESHOLD", "0"))
            lines = [f"*VIP Contacts* (threshold={threshold}):\n"]
            for c in contacts[:15]:
                status = "🤖 auto" if c["approval_count"] >= threshold > 0 else "👤 manual"
                lines.append(f"• {c['identifier']} — {c['approval_count']} approvals {status}")
            send_message("\n".join(lines))
        except Exception as e:
            send_message(f"_(vip error: {e})_")

    elif cmd == "/help":
        send_message(
            "*Truman commands:*\n\n"
            "/status — system health check\n"
            "/pause  — pause Truman's agent\n"
            "/resume — resume Truman\n"
            "/vip    — VIP auto-reply contacts\n"
            "/help   — this message\n\n"
            "_Any other message → routed to Truman as chat._"
        )

    else:
        # Unknown command — pass to agent
        return False

    return True


# ── Incoming message handlers ─────────────────────────────────────────────────
def _handle_text(text: str, agent_fn):
    """Om replied on Telegram → run through agent → send reply back on Telegram."""

    # Check for pending edit first
    if _pending_edit:
        chat_id = _CHAT_ID
        if chat_id in _pending_edit:
            msg_id = _pending_edit.pop(chat_id)
            try:
                from truman.integrations.boss_handler import apply_edit
                apply_edit(msg_id, text)
            except Exception as e:
                send_message(f"_(edit error: {e})_")
            return

    # Check for /commands
    if text.startswith("/"):
        handled = _handle_command(text)
        if handled:
            return

    # Check agent paused
    if os.environ.get("TRUMAN_PAUSED", "0") == "1":
        send_message("⏸ Truman is paused. Send /resume to wake him up.")
        return

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
        # Describe the image using the vision pool directly
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
    """Inline button click — acknowledge + dispatch action."""
    cb_id = cb.get("id", "")
    data  = cb.get("data", "")
    _api("answerCallbackQuery", callback_query_id=cb_id)

    if data.startswith("boss_approve:"):
        try:
            msg_id = int(data.split(":", 1)[1])
            from truman.integrations.boss_handler import execute_approval
            execute_approval(msg_id)
        except Exception as e:
            send_message(f"_(approve error: {e})_")

    elif data.startswith("boss_edit:"):
        try:
            msg_id = int(data.split(":", 1)[1])
            # Register pending edit: next text from Om will be the new draft
            _pending_edit[_CHAT_ID] = msg_id
            from truman.integrations.boss_handler import execute_edit
            execute_edit(msg_id)
        except Exception as e:
            send_message(f"_(edit error: {e})_")

    elif data.startswith("boss_skip:"):
        try:
            msg_id = int(data.split(":", 1)[1])
            # Clear any pending edit for this msg
            if _CHAT_ID in _pending_edit and _pending_edit[_CHAT_ID] == msg_id:
                _pending_edit.pop(_CHAT_ID, None)
            from truman.integrations.boss_handler import execute_skip
            execute_skip(msg_id)
            send_message("⏭ Skipped.")
        except Exception as e:
            send_message(f"_(skip error: {e})_")

    else:
        print(f"[Telegram] Unhandled callback: {data!r}")


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
