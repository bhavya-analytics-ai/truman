"""
tts_state.py — Shared last-spoke timestamp.

speak() in voice.py stamps this after every TTS playback.
realtime.py reads it to extend the echo-cooldown window into the
period right after a non-Realtime voice call (morning brief, reminders,
boot message). Zero-dependency module to avoid circular imports.
"""
import time

_last_spoke: float = 0.0


def mark_spoke() -> None:
    """Call immediately after TTS playback finishes."""
    global _last_spoke
    _last_spoke = time.time()


def last_spoke_at() -> float:
    """Epoch seconds of the last speak() call's end. 0.0 if never called."""
    return _last_spoke
