"""
email_digest.py — Truman morning brief via Resend (HTTP API, Railway-compatible).

Sends a beautiful HTML digest at 9am ET. Pulls live data from:
  - sleep_log (last 7 days)
  - goals table (active goals + stall detection)
  - user_prefs (quiet_start/end, brief hour)

Send via Resend HTTP API (Railway doesn't block HTTP; SMTP port 465 is blocked).
Kill switch: ENABLE_MORNING_EMAIL=1
Resend: https://resend.com — free 100 emails/day, one env var: RESEND_API_KEY
"""

import os
import datetime
import traceback
import urllib.request
import urllib.parse
import json as _json
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")

RESEND_API_KEY     = os.getenv("RESEND_API_KEY", "")
MORNING_EMAIL_FROM = os.getenv("MORNING_EMAIL_FROM", "Truman <brief@truman.resend.dev>")
MORNING_EMAIL_TO   = os.getenv("MORNING_EMAIL_TO",   "")


# ── HTML builder ──────────────────────────────────────────────────────────────

def _sleep_section(stats: list) -> str:
    if not stats:
        return """
        <div class="card">
          <div class="card-header">😴 SLEEP</div>
          <div class="card-body muted">No sleep logged yet — tell Truman "gonna sleep from X to Y"</div>
        </div>"""

    latest = stats[0]
    avg_min = sum(s["duration_min"] for s in stats) / len(stats)
    avg_h   = int(avg_min // 60)
    avg_m   = int(avg_min % 60)
    dur_h   = latest["duration_min"] // 60
    dur_m   = latest["duration_min"] % 60

    diff_min = latest["duration_min"] - avg_min
    diff_tag = ""
    if diff_min <= -30:
        diff_tag = f'<span class="badge red">-{abs(int(diff_min))}m vs avg ↓</span>'
    elif diff_min >= 30:
        diff_tag = f'<span class="badge green">+{int(diff_min)}m vs avg ↑</span>'

    return f"""
        <div class="card">
          <div class="card-header">😴 SLEEP</div>
          <div class="card-body">
            <div class="stat-big">{latest["sleep_start"]} → {latest["sleep_end"]}</div>
            <div class="stat-sub">{dur_h}h {dur_m}m {diff_tag}</div>
            <div class="divider"></div>
            <div class="stat-sub muted">7-day avg: {avg_h}h {avg_m}m &nbsp;·&nbsp; {len(stats)} entries</div>
          </div>
        </div>"""


def _goals_section(goals: list) -> str:
    if not goals:
        return """
        <div class="card">
          <div class="card-header">🎯 GOALS</div>
          <div class="card-body muted">No active goals — add one in Truman chat</div>
        </div>"""

    threshold = datetime.datetime.now() - datetime.timedelta(days=7)
    threshold_str = threshold.isoformat(timespec="seconds")
    rows = ""
    for g in goals[:5]:
        updated = (g.get("updated_at") or "")
        is_stale = updated and updated < threshold_str
        created  = g.get("created_at", "")[:10]
        icon = "⚠️" if is_stale else "▸"
        color = ' class="stale"' if is_stale else ""
        rows += f'<div class="goal-row"{color}>{icon} {g["title"]}</div>'

    return f"""
        <div class="card">
          <div class="card-header">🎯 GOALS</div>
          <div class="card-body">{rows}</div>
        </div>"""


def _focus_section(goals: list, sleep_stats: list) -> str:
    """Generate a brief focus suggestion from available data."""
    lines = []

    # stalled goal
    threshold_str = (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat()
    for g in goals[:5]:
        updated = g.get("updated_at", "") or ""
        if updated and updated < threshold_str:
            lines.append(f"<b>{g['title']}</b> hasn't moved in 7+ days.")
            break

    # low sleep warning
    if sleep_stats and sleep_stats[0]["duration_min"] < 300:
        lines.append("You're running on under 5h — pace yourself today.")

    if not lines:
        lines.append("No blockers. Ship something.")

    return f"""
        <div class="card focus-card">
          <div class="card-header">⚡ FOCUS</div>
          <div class="card-body">{"<br>".join(lines)}</div>
        </div>"""


def build_html(now: datetime.datetime = None) -> str:
    from truman.storage.db import get_sleep_stats, get_all_goals

    now     = now or datetime.datetime.now(_ET)
    day_str = now.strftime("%A, %B %d")
    time_str = now.strftime("%I:%M %p ET")

    try:
        sleep_stats = get_sleep_stats(7)
    except Exception:
        sleep_stats = []

    try:
        goals = get_all_goals()
        goals = [g for g in goals if g.get("status") == "active"]
    except Exception:
        goals = []

    sleep_html = _sleep_section(sleep_stats)
    goals_html = _goals_section(goals)
    focus_html = _focus_section(goals, sleep_stats)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Truman Brief</title>
<style>
  /* Inline-safe reset */
  * {{ margin:0; padding:0; box-sizing:border-box; }}
</style>
</head>
<body style="background:#0f172a; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; padding:0; margin:0;">

  <!-- Wrapper -->
  <div style="max-width:560px; margin:0 auto; padding:24px 16px;">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#1e293b,#0f172a); border:1px solid #334155;
                border-radius:16px 16px 0 0; padding:24px 28px; margin-bottom:0;">
      <div style="font-size:11px; color:#64748b; letter-spacing:2px; text-transform:uppercase; margin-bottom:6px;">
        TRUMAN BRIEF
      </div>
      <div style="font-size:24px; font-weight:700; color:#f1f5f9;">{day_str}</div>
      <div style="font-size:13px; color:#94a3b8; margin-top:4px;">{time_str}</div>
    </div>

    <!-- Sleep card -->
    <div style="background:#1e293b; border:1px solid #334155; border-top:none; padding:20px 28px;">
      <div style="font-size:11px; color:#64748b; letter-spacing:1.5px; text-transform:uppercase; margin-bottom:12px;">
        😴 &nbsp;SLEEP
      </div>
      {_sleep_card_inner(sleep_stats)}
    </div>

    <!-- Goals card -->
    <div style="background:#1e293b; border:1px solid #334155; border-top:none; padding:20px 28px;">
      <div style="font-size:11px; color:#64748b; letter-spacing:1.5px; text-transform:uppercase; margin-bottom:12px;">
        🎯 &nbsp;ACTIVE GOALS
      </div>
      {_goals_card_inner(goals)}
    </div>

    <!-- Focus card -->
    <div style="background:linear-gradient(135deg,#1e293b,#162032); border:1px solid #3b4f6b;
                border-top:none; border-radius:0 0 16px 16px; padding:20px 28px;">
      <div style="font-size:11px; color:#64748b; letter-spacing:1.5px; text-transform:uppercase; margin-bottom:12px;">
        ⚡ &nbsp;FOCUS
      </div>
      {_focus_card_inner(goals, sleep_stats)}
    </div>

    <!-- Footer -->
    <div style="text-align:center; padding:16px 0; font-size:12px; color:#475569;">
      <a href="https://truman-production.up.railway.app/dashboard"
         style="color:#3b82f6; text-decoration:none;">open dashboard</a>
      &nbsp;·&nbsp;
      <span>truman</span>
    </div>

  </div>
</body>
</html>"""


def _sleep_card_inner(stats: list) -> str:
    if not stats:
        return '<div style="color:#475569; font-size:14px;">No sleep logged yet</div>'

    latest  = stats[0]
    avg_min = sum(s["duration_min"] for s in stats) / len(stats)
    avg_h   = int(avg_min // 60)
    avg_m   = int(avg_min % 60)
    dur_h   = latest["duration_min"] // 60
    dur_m   = latest["duration_min"] % 60
    diff_min = latest["duration_min"] - avg_min

    if diff_min <= -30:
        diff_html = f'<span style="background:#450a0a;color:#f87171;padding:2px 8px;border-radius:6px;font-size:12px;margin-left:8px;">-{abs(int(diff_min))}m vs avg</span>'
    elif diff_min >= 30:
        diff_html = f'<span style="background:#052e16;color:#4ade80;padding:2px 8px;border-radius:6px;font-size:12px;margin-left:8px;">+{int(diff_min)}m vs avg</span>'
    else:
        diff_html = ""

    return f"""
    <div style="font-size:22px;font-weight:700;color:#f1f5f9;margin-bottom:4px;">
      {latest["sleep_start"]} → {latest["sleep_end"]}
    </div>
    <div style="font-size:15px;color:#94a3b8;margin-bottom:8px;">
      {dur_h}h {dur_m}m{diff_html}
    </div>
    <div style="border-top:1px solid #334155;padding-top:8px;font-size:13px;color:#64748b;">
      7-day avg: {avg_h}h {avg_m}m &nbsp;·&nbsp; {len(stats)} night{"s" if len(stats)!=1 else ""} logged
    </div>"""


def _goals_card_inner(goals: list) -> str:
    if not goals:
        return '<div style="color:#475569;font-size:14px;">No active goals</div>'

    threshold_str = (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat()
    rows = ""
    for g in goals[:5]:
        updated  = g.get("updated_at", "") or ""
        is_stale = updated and updated < threshold_str
        icon     = "⚠️" if is_stale else "▸"
        color    = "#f87171" if is_stale else "#94a3b8"
        rows += f'<div style="padding:5px 0;font-size:14px;color:{color};">{icon} {g["title"]}</div>'

    return rows


def _focus_card_inner(goals: list, sleep_stats: list) -> str:
    threshold_str = (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat()
    lines = []

    for g in goals[:5]:
        updated = g.get("updated_at", "") or ""
        if updated and updated < threshold_str:
            lines.append(f'<b style="color:#f1f5f9;">{g["title"]}</b> hasn\'t moved in 7+ days.')
            break

    if sleep_stats and sleep_stats[0]["duration_min"] < 300:
        lines.append("You\'re under 5h — pace yourself today.")

    if not lines:
        lines.append("No blockers. Ship something.")

    return "<br>".join(f'<div style="font-size:15px;color:#94a3b8;line-height:1.6;">{l}</div>' for l in lines)


# ── Send ──────────────────────────────────────────────────────────────────────

def send_morning_brief() -> bool:
    """Build + send the HTML email via Resend HTTP API. Returns True on success."""
    if os.getenv("ENABLE_MORNING_EMAIL", "1") != "1":
        return False

    _key  = RESEND_API_KEY or os.getenv("RESEND_API_KEY", "")
    _from = MORNING_EMAIL_FROM or os.getenv("MORNING_EMAIL_FROM", "")
    _to   = MORNING_EMAIL_TO   or os.getenv("MORNING_EMAIL_TO", "")

    if not _key:
        print("[Email] RESEND_API_KEY not set — skipping morning brief. "
              "Sign up at resend.com, get a free API key, add RESEND_API_KEY to Railway.")
        return False
    if not _to:
        print("[Email] MORNING_EMAIL_TO not set — skipping morning brief.")
        return False

    try:
        now     = datetime.datetime.now(_ET)
        html    = build_html(now)
        subject = f"Truman Brief — {now.strftime('%A, %b %d')}"

        payload = _json.dumps({
            "from":    _from or "Truman <brief@truman.resend.dev>",
            "to":      [_to],
            "subject": subject,
            "html":    html,
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data    = payload,
            headers = {
                "Authorization": f"Bearer {_key}",
                "Content-Type":  "application/json",
            },
            method  = "POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            data = _json.loads(body)
            print(f"[Email] Morning brief sent via Resend → id={data.get('id', '?')} to {_to}")
        return True

    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        print(f"[Email] Resend HTTP error {e.code}: {err_body}")
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"[Email] Send failed: {e}")
        traceback.print_exc()
        return False
