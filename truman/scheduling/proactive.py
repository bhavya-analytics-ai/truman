"""
proactive.py — Truman's proactive intelligence (Phase 10)

Four systems, all daemon threads:

1. morning_briefing  — voice + SSE push at 9am ET (once/day)
2. idle_checkin      — voice ping if no chat in N minutes (voice path)
3. proactive_push    — SSE-only triggers:
      a. 9am morning brief (if not already fired by voice)
      b. 4hr idle nudge (skips quiet hours 3am–8:50am ET)
      c. goal nudge (noon daily — stalled 7 days OR deadline <24hrs)
4. reminders         — Om sets time-based reminders, Truman fires them

Quiet hours:  03:00–08:50 ET  (Om's actual sleep window)
Sleep timing: auto-updated via log_sleep tool / update_pref tool

Reminders persist to SQLite — survive process death. claim_reminder() is
atomic so scheduler.py can also fire them with no double-fire risk.
"""

import os
import subprocess
import time
import threading
import datetime

from zoneinfo import ZoneInfo

from truman.storage import db

_ET = ZoneInfo("America/New_York")

# ── Shared state ──────────────────────────────────────────────────────────────
_last_interaction = time.time()   # updated every time Om speaks


def record_interaction():
    """Call this every time Om says something."""
    global _last_interaction
    _last_interaction = time.time()


# ── Quiet hours helper ────────────────────────────────────────────────────────

def _in_quiet_hours(now: datetime.datetime = None) -> bool:
    """True if now is inside Om's sleep window (quiet hours).

    Defaults: 3:00am–8:50am ET. Respects user_prefs keys
    'quiet_start' (e.g. '03:00') and 'quiet_end' (e.g. '08:50').
    """
    try:
        now = now or datetime.datetime.now(_ET)
        start_str = db.get_pref("quiet_start", "03:00")
        end_str   = db.get_pref("quiet_end",   "08:50")
        sh, sm = map(int, start_str.split(":"))
        eh, em = map(int, end_str.split(":"))
        start_min = sh * 60 + sm
        end_min   = eh * 60 + em
        now_min   = now.hour * 60 + now.minute
        if start_min <= end_min:   # same-day window (e.g. 03:00–08:50)
            return start_min <= now_min < end_min
        else:                      # overnight window (e.g. 23:00–07:00)
            return now_min >= start_min or now_min < end_min
    except Exception:
        # fallback: 3am–8:50am
        now = now or datetime.datetime.now(_ET)
        now_min = now.hour * 60 + now.minute
        return 180 <= now_min < 530


# ── 1. Morning Briefing (voice) ───────────────────────────────────────────────

def start_morning_briefing(speak_fn, agent_fn):
    """Fires once at startup if Truman starts between 9am and 11am ET.
    (Legacy voice path — the proactive_push thread handles the scheduled 9am fire.)
    """
    def _run():
        try:
            now = datetime.datetime.now(_ET)
            if not (9 <= now.hour < 11):
                return
            time.sleep(3)
            prompt = (
                f"It's {now.strftime('%A, %B %d')} at {now.strftime('%I:%M %p')} ET. "
                "Give Om a sharp morning briefing — what day it is, anything relevant from memory "
                "about what he's working on. Under 3 sentences, casual, no fluff."
            )
            result = agent_fn(prompt, mood="")
            speak_fn(result["response"] if isinstance(result, dict) else result)
        except Exception as e:
            print(f"[Proactive] morning briefing error: {e}")

    threading.Thread(target=_run, daemon=True).start()


# ── 2. Idle Check-in (voice) ─────────────────────────────────────────────────

def start_idle_checkin(speak_fn, agent_fn, idle_minutes=20):
    """Voice-only idle check. If Om hasn't spoken in idle_minutes, Truman checks in."""
    def _run():
        while True:
            try:
                time.sleep(60)
                silent_for = (time.time() - _last_interaction) / 60
                if silent_for >= idle_minutes and not _in_quiet_hours():
                    record_interaction()
                    prompt = (
                        f"Om has been quiet for about {idle_minutes} minutes. "
                        "Check in naturally — one short line, casual. Don't be dramatic."
                    )
                    result = agent_fn(prompt, mood="")
                    speak_fn(result["response"] if isinstance(result, dict) else result)
            except Exception as e:
                print(f"[Proactive] idle check error: {e}")

    threading.Thread(target=_run, daemon=True).start()


# ── 3. Proactive Push (SSE — the Phase 10 system) ────────────────────────────

def start_proactive_push(agent_fn):
    """
    60-second tick. Manages three SSE-based triggers:

    a. Morning brief  — 9:00–9:02am ET, once per day
    b. Idle nudge     — 4hr silence, skip quiet hours, once per 4hr window
    c. Goal nudge     — noon ET, once per day, only if stalled goals exist
    """
    if os.environ.get("ENABLE_PROACTIVE", "1") != "1":
        print("[Proactive] push disabled (ENABLE_PROACTIVE=0)")
        return

    _fired: dict[str, str] = {}   # key → date string when last fired

    def _today() -> str:
        return datetime.datetime.now(_ET).strftime("%Y-%m-%d")

    def _push(content: str):
        try:
            from truman.storage.notifications import push_proactive
            push_proactive(content)
        except Exception as e:
            print(f"[Proactive] push failed: {e}")

    def _llm(prompt: str) -> str:
        try:
            result = agent_fn(prompt, mood="")
            return result["response"] if isinstance(result, dict) else str(result)
        except Exception as e:
            return f"(proactive trigger failed: {e})"

    def _run():
        # track idle-nudge separately: last time we fired it
        last_idle_push = time.time()

        while True:
            try:
                time.sleep(60)
                now = datetime.datetime.now(_ET)
                today = _today()

                # ── a. Morning brief (default 9am, respects morning_brief_hour pref) ──
                brief_h = int(db.get_pref("morning_brief_hour_int", "9"))
                if (now.hour == brief_h and now.minute <= 2
                        and _fired.get("morning") != today):
                    _fired["morning"] = today
                    # Try HTML email first; fall back to SSE push
                    email_sent = False
                    if os.environ.get("ENABLE_MORNING_EMAIL", "1") == "1":
                        try:
                            from truman.voice.email_digest import send_morning_brief
                            email_sent = send_morning_brief()
                        except Exception as e:
                            print(f"[Proactive] email send error: {e}")
                    if not email_sent:
                        # fallback: SSE push to dashboard
                        prompt = (
                            f"It's {now.strftime('%A, %B %d')} at {now.strftime('%I:%M %p')} ET. "
                            "Give Om a quick morning brief — what day it is, top active goals "
                            "(pull from memory), and one thing he should focus on today. "
                            "3 sentences max, casual, no fluff."
                        )
                        _push(_llm(prompt))

                # ── b. Idle nudge — 4hr silence, skip quiet hours ─────────────
                idle_hrs = (time.time() - _last_interaction) / 3600
                time_since_idle_push = (time.time() - last_idle_push) / 3600
                if (idle_hrs >= 4
                        and not _in_quiet_hours(now)
                        and time_since_idle_push >= 4):
                    last_idle_push = time.time()
                    silent_h = int(idle_hrs)
                    prompt = (
                        f"Om hasn't been active for {silent_h} hours. "
                        "Send him a brief, casual nudge — one line. "
                        "Reference something from his active goals or last conversation if relevant. "
                        "Don't be dramatic."
                    )
                    _push(_llm(prompt))

                # ── c. Goal nudge at noon — stalled goals only ────────────────
                if (now.hour == 12 and now.minute <= 2
                        and _fired.get("goal_nudge") != today):
                    try:
                        goals = db.get_active_goals(limit=10)
                        stalled = []
                        threshold = datetime.datetime.now() - datetime.timedelta(days=7)
                        threshold_str = threshold.isoformat(timespec="seconds")
                        for g in goals:
                            updated = g.get("updated_at", "") or ""
                            deadline = _parse_deadline(g.get("description", "") or "")
                            is_stalled = updated < threshold_str
                            is_urgent = (deadline is not None and
                                        (deadline - datetime.datetime.now()).total_seconds() < 86400)
                            if is_stalled or is_urgent:
                                tag = " ⚠️ deadline <24h" if is_urgent else " (7 days no update)"
                                stalled.append(f"- {g['title']}{tag}")
                        if stalled:
                            _fired["goal_nudge"] = today
                            goal_lines = "\n".join(stalled[:3])
                            prompt = (
                                f"These goals haven't had progress in a while:\n{goal_lines}\n"
                                "Give Om a short, direct nudge (1–2 sentences). "
                                "Casual tone, no lecture."
                            )
                            _push(_llm(prompt))
                    except Exception as e:
                        print(f"[Proactive] goal nudge error: {e}")

            except Exception as e:
                print(f"[Proactive] push tick error: {e}")

    threading.Thread(target=_run, daemon=True).start()
    print("[Proactive] SSE push thread started (morning brief / idle 4hr / goal nudge).")


def _parse_deadline(description: str):
    """Try to extract a deadline datetime from a goal description string.
    Returns datetime or None. Simple heuristic — looks for ISO date."""
    import re
    m = re.search(r"deadline[:\s]+(\d{4}-\d{2}-\d{2})", description, re.I)
    if not m:
        return None
    try:
        return datetime.datetime.fromisoformat(m.group(1))
    except Exception:
        return None


# ── 4. Reminders (SQLite-backed) ──────────────────────────────────────────────

def start_reminder_loop(speak_fn, agent_fn):
    """
    Background loop that fires due reminders via voice when Truman is running.
    Atomic claim against SQLite — won't double-fire with the standalone scheduler.
    """
    def _run():
        while True:
            try:
                time.sleep(30)
                due = db.get_due_reminders()
            except Exception as e:
                print(f"[Reminders] DB read failed: {e}")
                continue

            for r in due:
                apple_id = r.get("apple_reminder_id")
                if not db.claim_reminder(r["id"]):
                    continue   # scheduler beat us to it
                prompt = (
                    f"Fire this reminder for Om: '{r['note']}'. "
                    "Say it naturally, one sentence."
                )
                try:
                    result = agent_fn(prompt, mood="")
                    speak_fn(result["response"] if isinstance(result, dict) else result)
                except Exception as e:
                    print(f"[Reminders] Fire failed for '{r['note']}': {e}")
                    continue
                if apple_id:
                    try:
                        script = (
                            'tell application "Reminders"\n'
                            f'  delete (first reminder whose id is "{apple_id}")\n'
                            'end tell'
                        )
                        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
                        print(f"[Reminders] Cleared Apple reminder {apple_id}")
                    except Exception as e:
                        print(f"[Reminders] Apple cleanup failed: {e}")

    threading.Thread(target=_run, daemon=True).start()


def add_reminder(note: str, at: datetime.datetime, apple_reminder_id: str | None = None) -> int:
    """Persist a reminder. Returns the DB id."""
    rid = db.add_reminder(note, at, apple_reminder_id=apple_reminder_id)
    apple_tag = f" | apple_id={apple_reminder_id}" if apple_reminder_id else ""
    print(f"[Reminder] Set: '{note}' at {at.strftime('%I:%M %p')} (id={rid}{apple_tag})")
    return rid


def list_reminders() -> list:
    """Returns list of {id, note, time} dicts."""
    rows = db.list_reminders(include_fired=False)
    out = []
    for r in rows:
        try:
            t = datetime.datetime.fromisoformat(r["fire_at"])
        except Exception:
            continue
        out.append({"id": r["id"], "note": r["note"], "time": t})
    return out


# ── Wire everything up ────────────────────────────────────────────────────────

def start_all(speak_fn, agent_fn, idle_minutes=20):
    """Call once from main.py after startup."""
    start_morning_briefing(speak_fn, agent_fn)
    start_idle_checkin(speak_fn, agent_fn, idle_minutes=idle_minutes)
    start_reminder_loop(speak_fn, agent_fn)
    start_proactive_push(agent_fn)
    print(f"[Proactive] All systems active — voice ({idle_minutes}min idle) + SSE push.")
