"""
sync.py — Mac-master sync + daily backup.

Two jobs:
1. RAILWAY_SYNC_URL set → pull turns from Railway every 60s into local SQLite.
   This keeps your Mac as the master copy even when you chat from phone/other devices.
2. Daily 2am backup → ~/Desktop/friday/backups/truman-YYYY-MM-DD.json (keeps 30 days).

Start with: from truman.storage.sync import start_sync; start_sync()
Called from truman/main.py (local) only — not from main_cloud.py.
"""

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path


RAILWAY_SYNC_URL = os.getenv("RAILWAY_SYNC_URL", "").rstrip("/")
SYNC_INTERVAL    = int(os.getenv("SYNC_INTERVAL_S", "60"))
BACKUP_DIR       = Path.home() / "Desktop" / "friday" / "backups"


# ── Pull from Railway ─────────────────────────────────────────────────────────

def _pull_from_railway():
    """Download sessions+turns from Railway and merge into local SQLite."""
    if not RAILWAY_SYNC_URL:
        return
    try:
        import urllib.request, urllib.error
        # fetch all sessions
        url = f"{RAILWAY_SYNC_URL}/api/sessions"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        groups = data.get("groups", [])
        from truman.storage import db
        for group in groups:
            for s in group.get("sessions", []):
                bid = s.get("browser_id")
                if not bid:
                    continue
                label = s.get("label") or ""
                sid = db.get_or_create_session(bid, label)
                if label:
                    db.update_session_label(bid, label)
                if s.get("first_message"):
                    db.set_session_first_message(bid, s["first_message"])
                # fetch turns for this session
                turns_url = f"{RAILWAY_SYNC_URL}/api/history?session_id={bid}"
                with urllib.request.urlopen(turns_url, timeout=10) as tr:
                    tdata = json.loads(tr.read())
                existing = {(t["role"], t["content"]) for t in db.session_turns(bid)}
                for turn in tdata.get("turns", []):
                    key = (turn["role"], turn["content"])
                    if key not in existing:
                        db.log_turn(sid, turn["role"], turn["content"])
    except Exception as e:
        pass  # silent — no internet, Railway down, etc.


# ── Daily backup ──────────────────────────────────────────────────────────────

def _do_backup():
    """Dump all sessions+turns to a dated JSON file. Keep 30 days."""
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        from truman.storage import db
        sessions = db.get_sessions_by_day()
        out = []
        for s in sessions:
            bid = s.get("browser_id")
            turns = db.session_turns(bid) if bid else []
            out.append({**s, "turns": turns})
        date_str = datetime.now().strftime("%Y-%m-%d")
        path = BACKUP_DIR / f"truman-{date_str}.json"
        path.write_text(json.dumps(out, indent=2, default=str))
        # remove backups older than 30 days
        cutoff = time.time() - 30 * 86400
        for f in BACKUP_DIR.glob("truman-*.json"):
            if f.stat().st_mtime < cutoff:
                f.unlink()
    except Exception:
        pass


def _backup_loop():
    """Run backup once at 2am each day."""
    while True:
        now = datetime.now()
        # seconds until next 2am
        next_2am = now.replace(hour=2, minute=0, second=0, microsecond=0)
        if next_2am <= now:
            import datetime as _dt
            next_2am += _dt.timedelta(days=1)
        wait = (next_2am - now).total_seconds()
        time.sleep(wait)
        _do_backup()


def _sync_loop():
    while True:
        _pull_from_railway()
        time.sleep(SYNC_INTERVAL)


# ── Public API ────────────────────────────────────────────────────────────────

def start_sync():
    """Start background sync + backup threads. Call once from main.py."""
    # run backup now on start (catches missed runs after long downtime)
    threading.Thread(target=_do_backup, daemon=True).start()
    # then schedule daily
    threading.Thread(target=_backup_loop, daemon=True).start()
    # sync loop only if Railway URL configured
    if RAILWAY_SYNC_URL:
        threading.Thread(target=_sync_loop, daemon=True).start()
