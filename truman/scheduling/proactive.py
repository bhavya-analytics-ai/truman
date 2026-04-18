"""
proactive.py — Truman's proactive intelligence (Level 4)
Three systems, all run in background threads:

1. morning_briefing  — fires once when Truman starts between 5am–11am
2. idle_checkin      — pings Om if he hasn't talked in X minutes
3. reminders         — Om sets time-based reminders by voice, Truman fires them

Reminders persist to SQLite (db.py), so they survive process death. A separate
`scheduler.py` process (launchd) also fires them when Truman isn't running.
Both use claim_reminder() — atomic, no double-fires.
"""

import time
import threading
import datetime

from truman.storage import db


# ── Shared state (set by main.py) ─────────────────────────────────────────────
_last_interaction = time.time()   # updated every time Om speaks


def record_interaction():
    """Call this every time Om says something."""
    global _last_interaction
    _last_interaction = time.time()


# ── 1. Morning Briefing ───────────────────────────────────────────────────────
def start_morning_briefing(speak_fn, agent_fn):
    """
    Fires once per session if Truman starts between 5am and 11am.
    Pulls time, day, and memory context for a short brief.
    """
    def _run():
        now = datetime.datetime.now()
        if not (5 <= now.hour < 11):
            return

        time.sleep(3)

        prompt = (
            f"It's {now.strftime('%A, %B %d')} at {now.strftime('%I:%M %p')}. "
            "Give Om a sharp morning briefing — what day it is, anything relevant from memory "
            "about what he's working on. Keep it under 3 sentences, casual, no fluff."
        )
        response = agent_fn(prompt, mood="")
        speak_fn(response)

    threading.Thread(target=_run, daemon=True).start()


# ── 2. Idle Check-in ──────────────────────────────────────────────────────────
def start_idle_checkin(speak_fn, agent_fn, idle_minutes=20):
    """
    If Om hasn't spoken in idle_minutes, Truman checks in.
    Resets after each check-in — won't spam.
    """
    def _run():
        while True:
            time.sleep(60)
            silent_for = (time.time() - _last_interaction) / 60
            if silent_for >= idle_minutes:
                record_interaction()
                prompt = (
                    f"Om has been quiet for about {idle_minutes} minutes. "
                    "Check in naturally — one short line, casual. Don't be dramatic about it."
                )
                response = agent_fn(prompt, mood="")
                speak_fn(response)

    threading.Thread(target=_run, daemon=True).start()


# ── 3. Reminders (SQLite-backed) ──────────────────────────────────────────────
def start_reminder_loop(speak_fn, agent_fn):
    """
    Background loop that fires due reminders via voice when Truman is running.
    Atomic claim against SQLite — won't double-fire with the standalone scheduler.
    """
    def _run():
        while True:
            time.sleep(30)
            try:
                due = db.get_due_reminders()
            except Exception as e:
                print(f"[Reminders] DB read failed: {e}")
                continue

            for r in due:
                if not db.claim_reminder(r["id"]):
                    continue   # scheduler beat us to it
                prompt = (
                    f"Fire this reminder for Om: '{r['note']}'. "
                    "Say it naturally, one sentence."
                )
                try:
                    response = agent_fn(prompt, mood="")
                    speak_fn(response)
                except Exception as e:
                    print(f"[Reminders] Fire failed for '{r['note']}': {e}")

    threading.Thread(target=_run, daemon=True).start()


def add_reminder(note: str, at: datetime.datetime) -> int:
    """Persist a reminder. Returns the DB id."""
    rid = db.add_reminder(note, at)
    print(f"[Reminder] Set: '{note}' at {at.strftime('%I:%M %p')} (id={rid})")
    return rid


def list_reminders() -> list:
    """Returns list of {id, note, time} dicts (same shape as before — 'time' is datetime)."""
    rows = db.list_reminders(include_fired=False)
    out = []
    for r in rows:
        try:
            t = datetime.datetime.fromisoformat(r["fire_at"])
        except Exception:
            continue
        out.append({"id": r["id"], "note": r["note"], "time": t})
    return out


# ── Start all three ───────────────────────────────────────────────────────────
def start_all(speak_fn, agent_fn, idle_minutes=20):
    """Wire everything up. Call once from main.py after startup."""
    start_morning_briefing(speak_fn, agent_fn)
    start_idle_checkin(speak_fn, agent_fn, idle_minutes=idle_minutes)
    start_reminder_loop(speak_fn, agent_fn)
    print(f"[Proactive] Morning briefing + idle check-in ({idle_minutes}min) + reminders active.")
