"""
voice.py — Truman's non-realtime TTS
Used for boot message + any out-of-session speech.
The realtime voice loop lives in realtime.py and does NOT use this file.
"""

# ── Lazy TTS singleton ────────────────────────────────────────────────────────
_tts_stream = None


def _get_tts():
    global _tts_stream
    if _tts_stream is not None:
        return _tts_stream
    from RealtimeTTS import TextToAudioStream, KokoroEngine
    engine      = KokoroEngine(voice="af_sky", default_speed=1.05)
    _tts_stream = TextToAudioStream(engine, muted=False)
    print("[Truman] Voice: Kokoro af_sky")
    return _tts_stream


# ── Speak ─────────────────────────────────────────────────────────────────────
def speak(text: str) -> bool:
    """Stream text through Kokoro. Returns False (no interrupt detection)."""
    if not text.strip():
        return False
    tts = _get_tts()
    tts.feed(text)
    tts.play()
    return False


def stop_speaking():
    if _tts_stream and _tts_stream.is_playing():
        _tts_stream.stop()
