import audioop
import threading
import time
import pyaudio
import queue

RATE = 16000
CHUNK = 1024
COUGH_THRESHOLD = 2500
CLAP_THRESHOLD = 6000
CLAP_DOUBLE_WINDOW = 0.6

_callback = None
_running = False
_last_clap_time = 0
_clap_count = 0
_in_event = False
_prev_rms = 0

# separate lightweight stream just for ambient — runs between voice captures
_ambient_buf = queue.Queue(maxsize=100)


def set_callback(fn):
    global _callback
    _callback = fn


def _trigger(event):
    if _callback:
        threading.Thread(target=_callback, args=(event,), daemon=True).start()


def _monitor():
    global _running, _last_clap_time, _clap_count, _in_event, _prev_rms

    p = pyaudio.PyAudio()

    while _running:
        from auth import TRUMAN_SPEAKING
        if TRUMAN_SPEAKING:
            time.sleep(0.1)
            continue

        # try to open stream — if mic is busy, wait and retry
        try:
            stream = p.open(format=pyaudio.paInt16, channels=1, rate=RATE,
                           input=True, frames_per_buffer=CHUNK)
        except Exception:
            time.sleep(0.5)
            continue

        try:
            while _running:
                from auth import TRUMAN_SPEAKING
                if TRUMAN_SPEAKING:
                    break

                data = stream.read(CHUNK, exception_on_overflow=False)
                rms = audioop.rms(data, 2)

                # clap — sudden spike above clap threshold
                if rms > CLAP_THRESHOLD and _prev_rms < CLAP_THRESHOLD / 2 and not _in_event:
                    _in_event = True
                    now = time.time()
                    if now - _last_clap_time < CLAP_DOUBLE_WINDOW:
                        _clap_count += 1
                    else:
                        _clap_count = 1
                    _last_clap_time = now
                    if _clap_count >= 2:
                        _trigger("double_clap")
                        _clap_count = 0

                # cough — sustained medium spike
                elif COUGH_THRESHOLD < rms < CLAP_THRESHOLD and not _in_event:
                    _in_event = True
                    _trigger("cough")

                elif rms < COUGH_THRESHOLD / 3:
                    _in_event = False

                _prev_rms = rms
                time.sleep(0.02)

        except Exception:
            pass
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass

        time.sleep(0.3)  # brief pause before reopening

    p.terminate()


def start():
    global _running
    _running = True
    threading.Thread(target=_monitor, daemon=True).start()


def stop():
    global _running
    _running = False
