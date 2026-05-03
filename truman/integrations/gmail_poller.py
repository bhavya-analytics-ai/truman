"""
gmail_poller.py — Phase 15: Gmail triage + reply via IMAP/SMTP.

Polls inbox every 15 min. For important emails:
  → drafts reply in Om's tone
  → fires Telegram: [✅ Reply] [⏭ Skip]
  → Om taps Reply → SMTP sends the draft from Om's Gmail

Kill switch: ENABLE_GMAIL_POLLING=0 (default off)
Requires:
  GMAIL_ADDRESS      = your Gmail (or falls back to MORNING_EMAIL_FROM)
  GMAIL_APP_PASSWORD = already in .env from Phase 11 morning brief

Important detection: subject/sender keyword match — customise via GMAIL_IMPORTANT_KEYWORDS env var.
"""

import imaplib
import email
import os
import smtplib
import time
import threading
from email.header import decode_header as _decode_header
from email.mime.text import MIMEText

_ENABLE   = os.getenv("ENABLE_GMAIL_POLLING", "0") == "1"
_ADDRESS  = os.getenv("GMAIL_ADDRESS", os.getenv("MORNING_EMAIL_FROM", ""))
_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
_INTERVAL = int(os.getenv("GMAIL_POLL_INTERVAL_S", "900"))  # 15 min default

_KEYWORDS = [kw.strip().lower() for kw in os.getenv(
    "GMAIL_IMPORTANT_KEYWORDS",
    "interview,application,offer,urgent,action required,deadline,follow up,follow-up,"
    "rejected,accepted,invitation,schedule,hiring,opportunity,congratulations,decision"
).split(",") if kw.strip()]

_seen_ids: set = set()
_lock = threading.Lock()
_started = False


# ── IMAP helpers ──────────────────────────────────────────────────────────────

def _decode_str(raw) -> str:
    if isinstance(raw, str):
        return raw
    parts = _decode_header(raw)
    out = []
    for chunk, enc in parts:
        if isinstance(chunk, bytes):
            out.append(chunk.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(str(chunk))
    return " ".join(out)


def _is_important(subject: str, sender: str) -> bool:
    target = (subject + " " + sender).lower()
    return any(kw in target for kw in _KEYWORDS)


def _extract_body(msg_obj) -> str:
    """Extract plain text body from email.Message object."""
    body = ""
    if msg_obj.is_multipart():
        for part in msg_obj.walk():
            ct = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if ct == "text/plain" and "attachment" not in disp:
                try:
                    body = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                    break
                except Exception:
                    pass
    else:
        try:
            body = msg_obj.get_payload(decode=True).decode(
                msg_obj.get_content_charset() or "utf-8", errors="replace"
            )
        except Exception:
            pass
    return body[:3000]


def _poll_once():
    if not _ADDRESS or not _PASSWORD:
        return
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(_ADDRESS, _PASSWORD)
        mail.select("INBOX")

        _, data = mail.search(None, "UNSEEN")
        ids = data[0].split() if data and data[0] else []

        for uid in ids[-20:]:   # cap at 20 per poll
            uid_str = uid.decode() if isinstance(uid, bytes) else str(uid)
            with _lock:
                if uid_str in _seen_ids:
                    continue
                _seen_ids.add(uid_str)

            # Fetch full message
            _, msg_data = mail.fetch(uid, "(RFC822)")
            if not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            msg_obj = email.message_from_bytes(raw)

            subject     = _decode_str(msg_obj.get("Subject", "(no subject)")).strip()
            sender      = _decode_str(msg_obj.get("From", "unknown")).strip()
            reply_to    = _decode_str(msg_obj.get("Reply-To", sender)).strip()
            body        = _extract_body(msg_obj)

            if not _is_important(subject, sender):
                continue

            _handle_important_email(uid_str, sender, reply_to, subject, body)

        mail.logout()
    except Exception as e:
        print(f"[Gmail] Poll error: {e}")


def _handle_important_email(uid: str, sender: str, reply_to: str, subject: str, body: str):
    """Save to DB, draft reply, push Telegram with approve/skip buttons."""
    try:
        from truman.storage import db
        from truman.delivery.telegram import send_message

        # Save as boss_message with source='gmail'
        text = f"Subject: {subject}\n\n{body}"
        msg_id = db.save_boss_message("gmail", sender, text,
                                       extra={"reply_to": reply_to, "uid": uid, "subject": subject})

        # Draft reply
        draft = _draft_reply(sender, subject, body)
        if draft and not draft.startswith("_("):
            db.set_boss_draft(msg_id, draft)

        # Telegram notification
        name = sender.split("<")[0].strip().strip('"') or sender
        preview = body[:300].replace("\n", " ") + ("..." if len(body) > 300 else "")
        tg_text = (
            f"📧 *Gmail — {name}*\n"
            f"*{subject[:70]}*\n"
            f"{'─' * 22}\n"
            f"{preview}\n"
            f"{'─' * 22}\n"
            f"*Draft reply:*\n`{draft or '(no draft)'}`"
        )
        buttons = [[
            {"text": "✅ Reply",  "callback_data": f"boss_approve:{msg_id}"},
            {"text": "⏭ Skip",   "callback_data": f"boss_skip:{msg_id}"},
        ]]
        send_message(tg_text, buttons)
    except Exception as e:
        print(f"[Gmail] handle error: {e}")


def send_reply(to_addr: str, subject: str, body: str) -> bool:
    """Send a reply via Gmail SMTP. Returns True on success."""
    try:
        msg = MIMEText(body, "plain")
        msg["Subject"] = f"Re: {subject}" if not subject.lower().startswith("re:") else subject
        msg["From"]    = _ADDRESS
        msg["To"]      = to_addr
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(_ADDRESS, _PASSWORD)
            s.sendmail(_ADDRESS, [to_addr], msg.as_string())
        return True
    except Exception as e:
        print(f"[Gmail] SMTP send error: {e}")
        return False


# ── LLM draft ────────────────────────────────────────────────────────────────

def _draft_reply(sender: str, subject: str, body: str) -> str:
    try:
        from truman.core.model_router import run_with_pool
        from langchain_core.messages import HumanMessage, SystemMessage
        from truman.storage import db

        examples = db.get_approved_boss_replies(limit=5)
        style_block = ""
        if examples:
            style_block = "\n\nOm's past approved replies (match this tone):\n" + \
                          "\n".join(f'- "{r}"' for r in examples)

        system = (
            "You are drafting an email reply for Om. "
            "Keep it SHORT (2-4 sentences max). Professional but natural. "
            "No greetings like 'Dear'. Start directly. No sign-off needed."
            + style_block
        )
        user = (
            f"Email from {sender}\nSubject: {subject}\n\n"
            f"Body:\n{body[:1500]}\n\n"
            f"Write Om's reply (just the reply text, nothing else):"
        )
        msgs = [SystemMessage(content=system), HumanMessage(content=user)]
        result = run_with_pool(msgs, pool="fast", user_message=body)
        return (result.get("content") or "").strip()
    except Exception as e:
        return f"_(draft error: {e})_"


# ── Background polling ────────────────────────────────────────────────────────

def _poll_loop():
    while True:
        _poll_once()
        time.sleep(_INTERVAL)


def start():
    """Start background Gmail polling. Call once from proactive.py. Idempotent."""
    global _started
    if not _ENABLE:
        return
    if not _ADDRESS or not _PASSWORD:
        print("[Gmail] GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set — polling skipped.")
        return
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_poll_loop, daemon=True, name="gmail-poller").start()
    print(f"[Gmail] Polling inbox every {_INTERVAL}s → Telegram drafts + replies.")
