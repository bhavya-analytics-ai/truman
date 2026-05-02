"""
mac_banner.py — macOS native notification banner (Phase 12)

Fires a macOS Notification Center alert via osascript.
Silently does nothing on Railway (Linux) or if ENABLE_MAC_BANNER=0.
No new dependencies — osascript ships with macOS.

Usage:
    from truman.delivery.mac_banner import notify
    notify("Truman", "You've been quiet for 4 hours — everything ok?")
"""
import os
import sys
import subprocess


_ENABLE = os.getenv("ENABLE_MAC_BANNER", "1") == "1"


def notify(title: str, body: str, subtitle: str = "") -> bool:
    """
    Show a macOS native notification banner.

    Returns True if the banner fired, False if skipped or failed.
    Silently skipped on non-Mac platforms (Railway/Linux).
    """
    if not _ENABLE:
        return False
    if sys.platform != "darwin":
        return False  # Railway / Linux — skip silently

    try:
        # Escape double-quotes so osascript doesn't break
        title_s    = title.replace('"', '\\"')
        body_s     = body.replace('"', '\\"')
        subtitle_s = subtitle.replace('"', '\\"')

        subtitle_part = f' subtitle:"{subtitle_s}"' if subtitle_s else ""
        script = (
            f'display notification "{body_s}" '
            f'with title "{title_s}"{subtitle_part} '
            f'sound name "default"'
        )
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=5,
        )
        return True
    except Exception as e:
        print(f"[Banner] notify failed: {e}")
        return False
