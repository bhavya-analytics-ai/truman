"""
boss_handler.py — Phase 15: All-channel message intake + Telegram approval flow.

Handles messages from ANY contact via WhatsApp, iMessage, or Gmail.
Flow:
  WhatsApp   → whatsapp_bridge.js (Railway worker) → POST /api/boss_message
  iMessage   → iOS 'Receive Message' Shortcut Automation → POST /api/boss_message
  Gmail      → gmail_poller (5min IMAP poll) → handle_incoming()

  → Truman saves + drafts reply in Om's tone (per-contact style learning)
  → Auto-trivial check: if "got it" / "thanks" / social filler → auto-sends, no ask
  → Quiet-hours check: if 3am–8:50am (or meetings/Focus) → queues, sends after
  → Telegram: [✅ Approve] [✏️ Edit] [⏭ Skip]
  → Approve:
      WhatsApp  — whatsapp_bridge auto-send
      iMessage  — Pushcut webhook → iOS Shortcut auto-send (no Mac)
      Gmail     — SMTP auto-send
  → Edit: Om types new reply → re-sends for approval
  → Skip: marks handled silently

Kill switch: ENABLE_BOSS_FLOW=0 (default off — flip to 1 after setup)
"""

import os
import re

_ENABLE = os.getenv("ENABLE_BOSS_FLOW", "0") == "1"

# msg_id → True: waiting for Om to type a new draft via Telegram
_pending_edits: dict = {}

# ── Trivial message patterns (auto-send, no approval needed) ──────────────────

_TRIVIAL_RE = re.compile(
    r"^\s*(ok|okay|got it|gotcha|sure|sounds good|will do|noted|thanks|thank you|"
    r"thx|ty|no worries|np|no problem|lol|haha|👍|👋|😊|cool|great|perfect|nice|"
    r"see you|see ya|bye|later|alright|ight)\s*[!.?]?\s*$",
    re.I,
)

def _is_trivial(text: str) -> bool:
    """True if the incoming message needs only a short social reply."""
    return bool(_TRIVIAL_RE.match(text.strip())) and len(text.strip()) < 60


# ── Quiet hours check ────────────────────────────────────────────────────────

def _in_quiet_hours() -> bool:
    """Reuse proactive.py's quiet-hours logic (reads user_prefs)."""
    try:
        from truman.scheduling.proactive import _in_quiet_hours as _qh
        return _qh()
    except Exception:
        import datetime
        from zoneinfo import ZoneInfo
        now = datetime.datetime.now(ZoneInfo("America/New_York"))
        mins = now.hour * 60 + now.minute
        return 180 <= mins < 530   # 3:00am–8:50am ET fallback


# ── Core intake ──────────────────────────────────────────────────────────────

def handle_incoming(sender: str, text: str, source: str = "whatsapp", extra: dict = None) -> dict:
    """
    Called from POST /api/boss_message or directly from pollers.
    Saves message, drafts reply, runs auto-trivial + quiet-queue logic,
    then pings Telegram with [Approve][Edit][Skip].
    Returns {"status": "ok"|"disabled"|"queued"|"auto_sent", "msg_id": int, "draft": str}
    """
    if not _ENABLE:
        return {"status": "disabled"}

    from truman.storage import db
    from truman.delivery.telegram import send_message

    # 1. Save raw message
    msg_id = db.save_boss_message(source, sender, text, extra=extra or {})

    # 2. Draft reply — per-contact style learning (last 50 approved replies to this person)
    draft = _draft_reply(sender, text)
    if draft and not draft.startswith("_("):
        db.set_boss_draft(msg_id, draft)

    source_icon = {"whatsapp": "📱", "gmail": "📧", "imessage": "💬"}.get(source, "📨")

    # 3. Auto-trivial (Smart F): short social messages → auto-send, silent log
    if _is_trivial(text) and draft and not draft.startswith("_("):
        ok = _execute_send(source, sender, extra or {}, draft)
        if ok:
            db.set_boss_status(msg_id, "auto_approved")
            send_message(
                f"🤖 *Auto-replied to {sender}* ({source})\n"
                f"Their: _{text[:80]}_\n"
                f"Sent: `{draft}`"
            )
            return {"status": "auto_sent", "msg_id": msg_id, "draft": draft}
        # If send failed, fall through to normal approval flow

    # 4. Quiet queue (Smart C): hold during sleep hours, batch after
    if _in_quiet_hours():
        db.set_boss_status(msg_id, "queued")
        print(f"[Handler] Quiet hours — queued msg #{msg_id} from {sender}")
        return {"status": "queued", "msg_id": msg_id, "draft": draft}

    # 5. Normal Telegram approval flow
    _send_approval_request(msg_id, source_icon, source, sender, text, draft)
    return {"status": "ok", "msg_id": msg_id, "draft": draft}


def _send_approval_request(msg_id: int, icon: str, source: str, sender: str, text: str, draft: str):
    """Fire Telegram notification with Approve / Edit / Skip buttons."""
    from truman.delivery.telegram import send_message
    preview = text[:400] + ("..." if len(text) > 400 else "")
    tg_text = (
        f"{icon} *{source.title()} — {sender}*\n"
        f"{'─' * 22}\n"
        f"{preview}\n"
        f"{'─' * 22}\n"
        f"*Draft reply:*\n`{draft or '(no draft)'}`"
    )
    buttons = [[
        {"text": "✅ Approve", "callback_data": f"boss_approve:{msg_id}"},
        {"text": "✏️ Edit",   "callback_data": f"boss_edit:{msg_id}"},
        {"text": "⏭ Skip",   "callback_data": f"boss_skip:{msg_id}"},
    ]]
    send_message(tg_text, buttons)


# ── Quiet queue flusher (called from proactive 60s tick) ─────────────────────

def flush_quiet_queue():
    """
    Push any queued messages to Telegram now that quiet hours are over.
    Called from proactive.py's 60s tick.
    """
    if _in_quiet_hours():
        return
    try:
        from truman.storage import db
        queued = db.get_queued_boss_messages()
        if not queued:
            return
        for msg in queued:
            icon = {"whatsapp": "📱", "gmail": "📧", "imessage": "💬"}.get(msg["source"], "📨")
            db.set_boss_status(msg["id"], "pending")
            _send_approval_request(
                msg["id"], icon, msg["source"], msg["sender"],
                msg["text"], msg.get("draft_reply") or "(no draft)"
            )
        print(f"[Handler] Flushed {len(queued)} queued message(s) to Telegram.")
    except Exception as e:
        print(f"[Handler] Queue flush error: {e}")


# ── Approval execution ────────────────────────────────────────────────────────

def execute_approval(msg_id: int) -> str:
    """Called when Om taps [✅ Approve]."""
    from truman.storage import db
    from truman.delivery.telegram import send_message

    msg = db.get_boss_message(msg_id)
    if not msg:
        send_message("_(message not found)_")
        return "_(message not found)_"

    db.set_boss_status(msg_id, "approved")
    draft  = msg.get("draft_reply") or "(no draft saved)"
    source = msg.get("source", "")
    extra  = msg.get("extra", {})
    sender = msg.get("sender", "")

    ok = _execute_send(source, sender, extra, draft)

    if ok:
        send_message(f"✅ *Sent to {sender}* ({source})\n\n`{draft}`")
        # Increment VIP approval count for iMessage auto-reply tier
        if source == "imessage":
            handle = extra.get("handle") or sender
            try:
                db.increment_vip_approval_count(handle)
            except Exception:
                pass
    else:
        send_message(f"⚠️ Send failed — copy manually:\n\n`{draft}`")

    return draft


def _execute_send(source: str, sender: str, extra: dict, draft: str) -> bool:
    """Route the actual send to the right channel. Returns True on success."""
    if source == "gmail":
        to_addr = extra.get("reply_to") or sender
        subject = extra.get("subject", "Re:")
        try:
            from truman.integrations.gmail_poller import send_reply
            return send_reply(to_addr, subject, draft)
        except Exception as e:
            print(f"[Handler] Gmail send error: {e}")
            return False

    elif source == "imessage":
        handle = extra.get("handle") or sender
        try:
            from truman.integrations.imessage_poller import send_imessage
            return send_imessage(handle, draft)
        except Exception as e:
            print(f"[Handler] iMessage send error: {e}")
            return False

    else:  # whatsapp
        phone = extra.get("phone") or _extract_phone(sender)
        if not phone:
            return False
        try:
            from truman.integrations.whatsapp_bridge import send_whatsapp, is_bridge_up
            if is_bridge_up():
                return send_whatsapp(phone, draft)
        except Exception as e:
            print(f"[Handler] WhatsApp bridge error: {e}")
        return False


# ── Edit flow ────────────────────────────────────────────────────────────────

def execute_edit(msg_id: int) -> None:
    """Called when Om taps [✏️ Edit]. Next Telegram message = new draft."""
    from truman.delivery.telegram import send_message
    _pending_edits[msg_id] = True
    send_message(
        f"✏️ *Type your edited reply now.*\n"
        f"_(Next message replaces draft for msg #{msg_id})_"
    )


def apply_edit(msg_id: int, new_draft: str) -> None:
    """Save Om's typed edit and re-fire approval request."""
    _pending_edits.pop(msg_id, None)
    from truman.storage import db
    from truman.delivery.telegram import send_message

    msg = db.get_boss_message(msg_id)
    if not msg:
        send_message("_(original message not found)_")
        return
    db.set_boss_draft(msg_id, new_draft)

    icon = {"whatsapp": "📱", "gmail": "📧", "imessage": "💬"}.get(msg["source"], "📨")
    tg_text = (
        f"{icon} *{msg['source'].title()} — {msg['sender']}* _(edited draft)_\n"
        f"{'─' * 22}\n"
        f"{msg['text'][:300]}\n"
        f"{'─' * 22}\n"
        f"*Updated reply:*\n`{new_draft}`"
    )
    buttons = [[
        {"text": "✅ Approve", "callback_data": f"boss_approve:{msg_id}"},
        {"text": "✏️ Edit",   "callback_data": f"boss_edit:{msg_id}"},
        {"text": "⏭ Skip",   "callback_data": f"boss_skip:{msg_id}"},
    ]]
    send_message(tg_text, buttons)


def execute_skip(msg_id: int):
    """Om tapped [⏭ Skip] — mark handled silently."""
    _pending_edits.pop(msg_id, None)
    from truman.storage import db
    db.set_boss_status(msg_id, "skipped")


def get_pending_edit_msg_id() -> int | None:
    """Returns the msg_id waiting for an edit reply, or None."""
    if _pending_edits:
        return next(iter(_pending_edits))
    return None


# ── LLM draft — per-contact style learning (Smart A) ─────────────────────────

def _draft_reply(sender: str, text: str) -> str:
    """
    Draft a reply in Om's voice.
    Style learning: pulls last 50 approved replies TO THIS SPECIFIC SENDER first,
    falls back to last 10 general approved replies if not enough per-contact data.
    """
    try:
        from truman.core.model_router import run_with_pool
        from langchain_core.messages import HumanMessage, SystemMessage
        from truman.storage import db

        # Per-contact examples (Smart A)
        contact_examples = db.get_approved_boss_replies_for_sender(sender, limit=50)
        if len(contact_examples) >= 3:
            style_block = (
                f"\n\nOm's past replies to {sender} specifically (match this tone exactly):\n"
                + "\n".join(f'- "{r}"' for r in contact_examples[:10])
            )
        else:
            # Not enough per-contact data — use general tone
            general_examples = db.get_approved_boss_replies(limit=10)
            style_block = ""
            if general_examples:
                style_block = "\n\nOm's past replies (match this tone):\n" + \
                              "\n".join(f'- "{r}"' for r in general_examples)

        system = (
            "You are drafting a reply for Om to send to his contact. "
            "Rules: max 2 sentences. lowercase. no greetings. direct. no filler words. "
            "Sound like a real person texting, not an AI."
            + style_block
        )
        user = f'{sender} sent Om:\n"{text}"\n\nWrite Om\'s reply (just the reply text, nothing else):'

        msgs = [SystemMessage(content=system), HumanMessage(content=user)]
        result = run_with_pool(msgs, pool="fast", user_message=text)
        return (result.get("content") or "").strip().strip('"').strip("'")
    except Exception as e:
        return f"_(draft error: {e})_"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_phone(sender: str) -> str | None:
    """Try to extract a phone number from a sender string."""
    m = re.search(r"\+?\d[\d\s\-().]{7,}\d", sender)
    return m.group(0).replace(" ", "").replace("-", "") if m else None
