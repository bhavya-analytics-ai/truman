"""
boss_handler.py — Phase 15: WhatsApp (Adam) message intake + Telegram approval flow.

Flow:
  iPhone Shortcut forwards Adam's WhatsApp → POST /api/boss_message
  → Truman saves + drafts reply in Om's tone
  → Telegram fires: [✅ Approve] [⏭ Skip]
  → Om taps Approve → clean draft appears on Telegram ready to copy-paste into WhatsApp

Kill switch: ENABLE_BOSS_FLOW=0 (default off — flip to 1 after setting up iPhone Shortcut)

iPhone Shortcut setup (Om does once, 2 min):
  1. Open Shortcuts app → New Shortcut
  2. Add action: "Receive from Share Sheet" (type: Text)
  3. Add action: "Get Contents of URL"
       URL: https://truman-production.up.railway.app/api/boss_message
       Method: POST
       Headers: Content-Type: application/json
       Body: {"from": "Adam", "text": "[Shortcut Input]", "source": "whatsapp"}
  4. Save as "Forward to Truman"
  Now: long-press any WhatsApp message → Share → Forward to Truman
"""

import os

_ENABLE = os.getenv("ENABLE_BOSS_FLOW", "0") == "1"


def handle_incoming(sender: str, text: str, source: str = "whatsapp") -> dict:
    """
    Called from POST /api/boss_message.
    Saves message, drafts reply, pings Telegram.
    Returns {"status": "ok"|"disabled", "msg_id": int, "draft": str}
    """
    if not _ENABLE:
        return {"status": "disabled"}

    from truman.storage import db
    from truman.delivery.telegram import send_message

    # 1. Save raw message
    msg_id = db.save_boss_message(source, sender, text)

    # 2. Draft reply using LLM in Om's tone
    draft = _draft_reply(sender, text)
    if draft and not draft.startswith("_("):
        db.set_boss_draft(msg_id, draft)

    # 3. Push to Telegram with approve/skip buttons
    preview = text[:400] + ("..." if len(text) > 400 else "")
    tg_text = (
        f"📱 *{source.title()} — {sender}*\n"
        f"{'─' * 22}\n"
        f"{preview}\n"
        f"{'─' * 22}\n"
        f"*Draft reply:*\n`{draft or '(no draft)'}`"
    )
    buttons = [[
        {"text": "✅ Approve", "callback_data": f"boss_approve:{msg_id}"},
        {"text": "⏭ Skip",    "callback_data": f"boss_skip:{msg_id}"},
    ]]
    send_message(tg_text, buttons)

    return {"status": "ok", "msg_id": msg_id, "draft": draft}


def execute_approval(msg_id: int) -> str:
    """
    Called when Om taps [✅ Approve].
    - Gmail: sends reply via SMTP automatically
    - WhatsApp/other: shows clean draft on Telegram for copy-paste
    """
    from truman.storage import db
    from truman.delivery.telegram import send_message

    msg = db.get_boss_message(msg_id)
    if not msg:
        return "_(message not found)_"
    db.set_boss_status(msg_id, "approved")
    draft = msg.get("draft_reply") or "(no draft saved)"

    if msg.get("source") == "gmail":
        # Send email automatically via SMTP
        extra   = msg.get("extra", {})
        to_addr = extra.get("reply_to") or msg.get("sender", "")
        subject = extra.get("subject", "Re:")
        try:
            from truman.integrations.gmail_poller import send_reply
            ok = send_reply(to_addr, subject, draft)
            if ok:
                send_message(f"✅ *Email sent to {to_addr}*\n\n_{draft}_")
            else:
                send_message(f"⚠️ Send failed — copy manually:\n\n`{draft}`")
        except Exception as e:
            send_message(f"⚠️ Send error ({e}) — copy manually:\n\n`{draft}`")
    else:
        # WhatsApp / other: show draft for copy-paste
        send_message(
            f"✅ *Copy and paste this reply:*\n\n`{draft}`"
        )
    return draft


def execute_skip(msg_id: int):
    """Called when Om taps [⏭ Skip]. Just marks it handled."""
    from truman.storage import db
    db.set_boss_status(msg_id, "skipped")


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
