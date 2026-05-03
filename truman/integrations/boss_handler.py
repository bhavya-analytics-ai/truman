"""
boss_handler.py — Phase 15: WhatsApp + Gmail + iMessage intake + Telegram approval flow.

Flow:
  WhatsApp   → iPhone Shortcut → POST /api/boss_message
  Gmail      → gmail_poller polling IMAP
  iMessage   → imessage_poller polling chat.db (Mac only)

  → Truman saves + drafts reply in Om's tone
  → Telegram fires: [✅ Approve] [✏️ Edit] [⏭ Skip]
  → Approve:
      - Gmail:    SMTP auto-send
      - WhatsApp: whatsapp-web.js bridge auto-send → falls back to shortcuts:// URL
      - iMessage: AppleScript auto-send
  → Edit: bot prompts Om to type new reply → re-drafts → re-sends for approval
  → Skip: marks handled silently

Kill switch: ENABLE_BOSS_FLOW=0 (default off — flip to 1 after setup)

iPhone Shortcut setup (Om does once, 2 min):
  1. Open Shortcuts app → New Shortcut
  2. Add action: "Receive from Share Sheet" (type: Text)
  3. Add action: "Get Contents of URL"
       URL: https://truman-production.up.railway.app/api/boss_message
       Method: POST
       Headers: Content-Type: application/json
       Body: {"from": "Contact Name", "text": "[Shortcut Input]", "source": "whatsapp"}
  4. Save as "Forward to Truman"
  Now: long-press any WhatsApp message → Share → Forward to Truman
"""

import os

_ENABLE = os.getenv("ENABLE_BOSS_FLOW", "0") == "1"

# Track messages waiting for an edit reply: msg_id → telegram chat_id
# telegram.py sets this when Om taps Edit, boss_handler reads it on next text
_pending_edits: dict = {}   # msg_id (int) → True


def handle_incoming(sender: str, text: str, source: str = "whatsapp", extra: dict = None) -> dict:
    """
    Called from POST /api/boss_message or directly from pollers.
    Saves message, drafts reply, pings Telegram with [Approve][Edit][Skip].
    Returns {"status": "ok"|"disabled", "msg_id": int, "draft": str}
    """
    if not _ENABLE:
        return {"status": "disabled"}

    from truman.storage import db
    from truman.delivery.telegram import send_message

    # 1. Save raw message
    msg_id = db.save_boss_message(source, sender, text, extra=extra or {})

    # 2. Draft reply using LLM in Om's tone
    draft = _draft_reply(sender, text)
    if draft and not draft.startswith("_("):
        db.set_boss_draft(msg_id, draft)

    # 3. Push to Telegram with approve/edit/skip buttons
    source_icon = {"whatsapp": "📱", "gmail": "📧", "imessage": "💬"}.get(source, "📨")
    preview = text[:400] + ("..." if len(text) > 400 else "")
    tg_text = (
        f"{source_icon} *{source.title()} — {sender}*\n"
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

    return {"status": "ok", "msg_id": msg_id, "draft": draft}


def execute_approval(msg_id: int) -> str:
    """
    Called when Om taps [✅ Approve].
    - Gmail:    SMTP auto-send
    - WhatsApp: whatsapp-web.js bridge auto-send → shortcut:// fallback → copy-paste fallback
    - iMessage: AppleScript auto-send
    """
    from truman.storage import db
    from truman.delivery.telegram import send_message

    msg = db.get_boss_message(msg_id)
    if not msg:
        send_message("_(message not found)_")
        return "_(message not found)_"
    db.set_boss_status(msg_id, "approved")
    draft = msg.get("draft_reply") or "(no draft saved)"
    source = msg.get("source", "")
    extra  = msg.get("extra", {})

    if source == "gmail":
        # ── Gmail: SMTP auto-send ──────────────────────────────────────────
        to_addr = extra.get("reply_to") or msg.get("sender", "")
        subject = extra.get("subject", "Re:")
        try:
            from truman.integrations.gmail_poller import send_reply
            ok = send_reply(to_addr, subject, draft)
            if ok:
                send_message(f"✅ *Email sent to {to_addr}*\n\n_{draft}_")
            else:
                send_message(f"⚠️ Email send failed — copy manually:\n\n`{draft}`")
        except Exception as e:
            send_message(f"⚠️ Email error ({e}) — copy manually:\n\n`{draft}`")

    elif source == "imessage":
        # ── iMessage: AppleScript auto-send ───────────────────────────────
        handle = extra.get("handle") or msg.get("sender", "")
        try:
            from truman.integrations.imessage_poller import send_imessage
            ok = send_imessage(handle, draft)
            if ok:
                send_message(f"✅ *iMessage sent to {handle}*\n\n`{draft}`")
                # Increment VIP count
                try:
                    from truman.storage import db as _db
                    _db.increment_vip_approval_count(handle)
                except Exception:
                    pass
            else:
                send_message(f"⚠️ iMessage send failed — copy manually:\n\n`{draft}`")
        except Exception as e:
            send_message(f"⚠️ iMessage error ({e}) — copy manually:\n\n`{draft}`")

    else:
        # ── WhatsApp: bridge → shortcut fallback → copy-paste fallback ────
        phone = extra.get("phone") or _extract_phone(msg.get("sender", ""))
        sent = False

        if phone:
            try:
                from truman.integrations.whatsapp_bridge import send_whatsapp, is_bridge_up
                if is_bridge_up():
                    sent = send_whatsapp(phone, draft)
                    if sent:
                        send_message(f"✅ *WhatsApp sent to {msg['sender']}*\n\n`{draft}`")
            except Exception as e:
                print(f"[Boss] WA bridge error: {e}")

        if not sent:
            # Fallback: iPhone Shortcut URL (1-tap send)
            # shortcuts://run-shortcut?name=Send+WA&input=<encoded>
            import urllib.parse
            payload  = urllib.parse.quote(f"{phone}|||{draft}" if phone else draft)
            shortcut_url = f"shortcuts://run-shortcut?name=Send%20WA&input={payload}"
            send_message(
                f"📱 *WhatsApp — tap to send:*\n\n`{draft}`\n\n"
                f"[Open Shortcut]({shortcut_url})\n"
                f"_(or copy-paste above into WhatsApp manually)_"
            )

    return draft


def execute_edit(msg_id: int) -> None:
    """
    Called when Om taps [✏️ Edit].
    Marks message as waiting for edit — Telegram poller will catch next text
    from Om and treat it as the new draft.
    """
    from truman.delivery.telegram import send_message
    _pending_edits[msg_id] = True
    send_message(
        f"✏️ *Type your edited reply now.*\n_(Your next message will replace the draft for msg #{msg_id})_"
    )


def apply_edit(msg_id: int, new_draft: str) -> None:
    """
    Called from telegram.py when Om sends a message while a pending edit exists.
    Saves new draft, re-sends Telegram approval with updated draft.
    """
    _pending_edits.pop(msg_id, None)
    from truman.storage import db
    from truman.delivery.telegram import send_message

    msg = db.get_boss_message(msg_id)
    if not msg:
        send_message("_(original message not found)_")
        return
    db.set_boss_draft(msg_id, new_draft)

    source_icon = {"whatsapp": "📱", "gmail": "📧", "imessage": "💬"}.get(msg["source"], "📨")
    tg_text = (
        f"{source_icon} *{msg['source'].title()} — {msg['sender']}* _(edited draft)_\n"
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
    """Called when Om taps [⏭ Skip]. Marks handled silently."""
    _pending_edits.pop(msg_id, None)
    from truman.storage import db
    db.set_boss_status(msg_id, "skipped")


def get_pending_edit_msg_id() -> int | None:
    """Returns the msg_id waiting for an edit reply, or None."""
    if _pending_edits:
        return next(iter(_pending_edits))
    return None


# ── LLM draft ────────────────────────────────────────────────────────────────

def _draft_reply(sender: str, text: str) -> str:
    """Draft a short reply in Om's tone using past approved drafts as style guide."""
    try:
        from truman.core.model_router import run_with_pool
        from langchain_core.messages import HumanMessage, SystemMessage
        from truman.storage import db

        # Pull Om's past approved replies as tone examples (Tone Mirror)
        examples = db.get_approved_boss_replies(limit=5)
        style_block = ""
        if examples:
            style_block = "\n\nOm's past replies (match this tone exactly):\n" + \
                          "\n".join(f'- "{r}"' for r in examples)

        system = (
            "You are drafting a reply for Om to send to his contact. "
            "Rules: max 2 sentences. lowercase. no greetings. direct. no filler words. "
            "Sound like a real person, not an AI."
            + style_block
        )
        user = f'{sender} sent Om:\n"{text}"\n\nWrite Om\'s reply (just the reply text, nothing else):'

        msgs = [SystemMessage(content=system), HumanMessage(content=user)]
        result = run_with_pool(msgs, pool="fast", user_message=text)
        return (result.get("content") or "").strip().strip('"').strip("'")
    except Exception as e:
        return f"_(draft error: {e})_"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_phone(sender: str) -> str | None:
    """Try to extract a phone number from a sender string."""
    import re
    m = re.search(r"\+?\d[\d\s\-().]{7,}\d", sender)
    return m.group(0).replace(" ", "").replace("-", "") if m else None
