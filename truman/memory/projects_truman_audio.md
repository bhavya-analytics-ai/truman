---
name: Truman Audio Pipeline — Browser WebRTC
description: Truman routes audio through the browser (orb.py WebSocket) not native sounddevice; AEC is handled by getUserMedia
type: project
originSessionId: a4f8d161-d89f-43bf-8281-335f2d312238
---
Truman's audio I/O lives in the browser tab, not the Python process.

- Browser captures mic via `getUserMedia({echoCancellation, noiseSuppression, autoGainControl})` and plays back speaker audio through `AudioContext`.
- `orb.py` exposes a `/audio` flask-sock WebSocket; raw 24kHz int16 PCM bytes flow both directions.
- `realtime.py` has two module-level queues: `mic_in` (browser → OpenAI) and `audio_out` (OpenAI → browser). A `None` in `audio_out` is a flush sentinel translated to `{"type":"flush"}` JSON for the browser to kill in-flight playback.
- Tech: OpenAI Realtime API (`gpt-4o-mini-realtime-preview`, voice `ash`), VAD threshold 0.5, silence 700ms.

**Why:** Native `sounddevice` mic + speaker had echo loop (laptop mic picked up Truman's own voice) and no real barge-in (muting the mic during playback killed interruption). Tried `pyaec` and `speexdsp` for software AEC — speexdsp won't build on Mac, pyaec needs a time-aligned reference signal that couldn't be supplied cleanly. Browser WebRTC AEC is production-grade and free — validated 2026-04-16, barge-in + no echo both work.

**How to apply:** Don't suggest adding back native audio or software AEC. If echo/interruption bugs come up, fix at the browser layer (AudioWorklet upgrade, flush timing) or tune VAD. `sounddevice` and `pyaec` are no longer in the audio path — only `flask-sock` and `websockets` matter. Public API of `realtime.py` unchanged (`start`, `start_session`, `end_session`, `toggle_session`) so `main.py` and `hotkey.py` stay untouched.
