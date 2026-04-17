"""
voice.py — Truman voice layer
Recording  : SpeechRecognition + Whisper
Speaking   : RealtimeTTS + Kokoro (streaming, no first-word cutoff)
"""

import os
import tempfile
import numpy as np
import speech_recognition as sr

from openai import OpenAI
from config import OPENAI_API_KEY

openai_client = OpenAI(api_key=OPENAI_API_KEY)

# ── SpeechRecognition setup ───────────────────────────────────────────────────
recognizer = sr.Recognizer()
recognizer.energy_threshold        = 300
recognizer.dynamic_energy_threshold = True
recognizer.pause_threshold         = 1.0


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


# ── Beep ──────────────────────────────────────────────────────────────────────
def ack_beep():
    try:
        import subprocess
        subprocess.Popen(["afplay", "/System/Library/Sounds/Tink.aiff"])
    except Exception:
        pass


# ── Speak ─────────────────────────────────────────────────────────────────────
def speak(text: str) -> bool:
    """Stream text through Kokoro. Returns False (no interrupt detection for now)."""
    if not text.strip():
        return False
    tts = _get_tts()
    tts.feed(text)
    tts.play()
    return False


def stop_speaking():
    if _tts_stream and _tts_stream.is_playing():
        _tts_stream.stop()


# ── Record ────────────────────────────────────────────────────────────────────
def record_audio(timeout=15, phrase_time_limit=20, classify_events=True) -> tuple[str | None, str | None]:
    """
    Listen for Om's voice.
    Returns (wav_path, event) — event is 'cough'/'double_clap' or None.
    Returns (None, None) on timeout.
    """
    from sound_classifier import classify

    with sr.Microphone(sample_rate=16000) as source:
        print("Listening...")
        recognizer.adjust_for_ambient_noise(source, duration=0.1)
        try:
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            raw   = audio.get_raw_data()

            if classify_events:
                event = classify(raw)
                if event:
                    return None, event

            ack_beep()

            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.write(audio.get_wav_data())
            tmp.close()
            return tmp.name, None

        except sr.WaitTimeoutError:
            return None, None


# Whisper hallucinates these phrases on silence/background noise — ignore them
_HALLUCINATIONS = [
    "thank you for watching", "please subscribe", "see you in the next video",
    "thanks for watching", "don't forget to subscribe", "like and subscribe",
    "you", "thank you.", "thanks.", "bye.", "goodbye.", "you.",
]

# ── Transcribe ────────────────────────────────────────────────────────────────
def transcribe(audio_path: str) -> str:
    with open(audio_path, "rb") as f:
        result = openai_client.audio.transcriptions.create(
            model="whisper-1", file=f
        )
    os.unlink(audio_path)
    text = result.text.strip()

    # drop known Whisper hallucinations
    if any(h in text.lower() for h in _HALLUCINATIONS):
        return ""

    return text
