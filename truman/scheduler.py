#!/usr/bin/env python3
"""
scheduler.py — Standalone reminder scheduler for Truman.

Runs independently of the main Truman process. Fired by launchd every minute
(see com.om.truman-scheduler.plist). Reads due reminders from SQLite and fires
them via macOS notification + `say` TTS.

Uses db.claim_reminder() for atomic claim, so it never double-fires with
proactive.py's in-process reminder loop.

Notes on reach:
  - Survives Python process death, laptop sleep → wake, reboots.
  - launchd does NOT wake a sleeping Mac to run this. On wake, any missed
    reminders fire late (but they DO fire — they're not lost).
  - To wake the Mac at a specific time, use `pmset schedule wake` when adding
    the reminder. Not wired here yet.
  - If the Mac is fully powered off, reminders fire on next boot.
"""

import os
import subprocess
import sys

# ensure we can import db.py from this same directory
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import db  # noqa: E402


def _notify(note: str):
    """macOS notification banner. Shows even if Truman isn't running."""
    # escape double quotes for AppleScript
    safe = note.replace('"', '\\"')
    script = f'display notification "{safe}" with title "Truman" sound name "Glass"'
    try:
        subprocess.run(["osascript", "-e", script], check=False, timeout=5)
    except Exception as e:
        print(f"[scheduler] notification failed: {e}", file=sys.stderr)


def _speak(note: str):
    """Native macOS TTS — works offline, no ElevenLabs dependency."""
    try:
        subprocess.run(["say", note], check=False, timeout=30)
    except Exception as e:
        print(f"[scheduler] say failed: {e}", file=sys.stderr)


def fire(reminder: dict):
    # Claim first — only the process that claims it fires it.
    if not db.claim_reminder(reminder["id"]):
        return False
    text = f"Reminder: {reminder['note']}"
    _notify(reminder["note"])
    _speak(text)
    print(f"[scheduler] fired id={reminder['id']} note={reminder['note']!r}")
    return True


def main():
    db.init()
    due = db.get_due_reminders()
    if not due:
        return
    print(f"[scheduler] {len(due)} reminder(s) due")
    for r in due:
        fire(r)


if __name__ == "__main__":
    main()
