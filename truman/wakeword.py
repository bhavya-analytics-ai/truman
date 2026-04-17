"""
wakeword.py — Always-on wake word detection
Uses openWakeWord with 'hey_jarvis' model (swap to 'hey_truman' when trained).

pause() releases the mic before record_audio() grabs it.
resume() reclaims the mic for wake word listening.
"""

import threading
import numpy as np
import pyaudio
from openwakeword.model import Model

MODEL_NAME          = "hey_jarvis"
DETECTION_THRESHOLD = 0.5
CHUNK_SIZE          = 1280      # 80ms at 16kHz

_running = False
_paused  = threading.Event()   # set = paused (mic released)
_model   = None
_thread  = None


def _load_model():
    global _model
    if _model is None:
        _model = Model(wakeword_models=[MODEL_NAME], inference_framework="onnx")
    return _model


def _listen_loop(on_wake):
    global _running
    model = _load_model()
    p     = pyaudio.PyAudio()

    while _running:
        if _paused.is_set():
            import time; time.sleep(0.05)
            continue

        stream = p.open(
            rate=16000, channels=1, format=pyaudio.paInt16,
            input=True, frames_per_buffer=CHUNK_SIZE
        )
        try:
            while _running and not _paused.is_set():
                raw   = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                pcm   = np.frombuffer(raw, dtype=np.int16)
                score = model.predict(pcm).get(MODEL_NAME, 0)
                if score >= DETECTION_THRESHOLD:
                    print(f"[Truman] Wake word! (score {score:.2f})")
                    model.reset()
                    stream.stop_stream()
                    stream.close()
                    stream = None
                    _paused.set()   # release mic before callback
                    on_wake()
                    break
        finally:
            if stream:
                stream.stop_stream()
                stream.close()

    p.terminate()


def pause():
    """Release mic — call before record_audio() or speak()."""
    _paused.set()


def resume():
    """Reclaim mic for wake word listening."""
    _paused.clear()


def start(on_wake):
    global _thread, _running
    if _running:
        return
    _running = True
    _paused.clear()
    _thread = threading.Thread(target=_listen_loop, args=(on_wake,), daemon=True)
    _thread.start()


def stop():
    global _running
    _running = False
