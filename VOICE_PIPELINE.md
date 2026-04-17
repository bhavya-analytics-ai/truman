# Truman Voice Pipeline — Setup Cookbook

Step-by-step guide to bootstrap the same voice pipeline we built for Truman
into any new Python project. Sub-second latency, real barge-in, no echo loop.

**What this gets you:**
You press a hotkey, speak, the model responds in voice, you can interrupt
mid-sentence and it stops, no echo from the laptop speaker leaking back into
the mic.

**Out of scope (skipped on purpose):**
- Speaker verification (Resemblyzer / pyannote)
- Wake-word detection
- Lockdown / passphrase gate
- Mem0 long-term memory
- LangChain agent / tool dispatch (hook point shown, implementation is yours)

---

## Architecture at a glance

```
Browser tab (orb UI on :5001)
  ├─ getUserMedia({echoCancellation:true})   ← browser AEC handles echo
  ├─ AudioContext 48kHz Float32 → 24kHz Int16 PCM
  ├─ WebSocket → ws://localhost:5001/audio
  │
Flask + flask-sock (orb.py)
  ├─ /audio WS route
  ├─ mic_in  queue ← browser mic frames
  ├─ audio_out queue → browser playback
  │
realtime.py
  ├─ WebSocket → OpenAI Realtime API
  ├─ pulls from mic_in, sends input_audio_buffer.append
  ├─ on response.audio.delta → pushes to audio_out
  │
hotkey.py → Cmd+Shift+T toggles the session
```

Why browser audio: native `sounddevice` + software AEC (pyaec, speexdsp)
failed on Mac — echo loop and no real barge-in. Browser WebRTC has
production-grade AEC baked in. This pipeline fixed both problems.

---

## Step 1 — Install dependencies

```bash
pip install flask flask-sock websockets python-dotenv pynput
```

That's it. Five packages.

- `flask` + `flask-sock` — local server + WebSocket for browser audio
- `websockets` — async client to OpenAI Realtime API
- `python-dotenv` — read `.env`
- `pynput` — global hotkey (Cmd+Shift+T). Optional, skip if you don't want hotkey.

**macOS only:** `pynput` needs Accessibility permission. After first run:
System Settings → Privacy & Security → Accessibility → add your terminal /
Python.

---

## Step 2 — Environment variables

Create a `.env` file at your project root:

```
OPENAI_API_KEY=sk-proj-...
```

Get the key from https://platform.openai.com/api-keys. You need the Realtime
API enabled on your account (most paid accounts have it).

---

## Step 3 — Project layout

```
your-project/
├── .env
├── config.py
├── orb.py
├── realtime.py
├── hotkey.py
└── main.py
```

Five files. All Python. Create them in that order (dependency order).

---

## Step 4 — `config.py`

```python
import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# OpenAI Realtime API settings
REALTIME_MODEL = "gpt-4o-mini-realtime-preview"
REALTIME_VOICE = "ash"   # options: alloy, ash, ballad, coral, echo, sage, shimmer, verse

# System prompt — what your assistant is
SYSTEM_PROMPT = (
    "You are a helpful voice assistant. Keep responses short — "
    "1-2 sentences max unless the user explicitly asks for more. "
    "This is voice, not text. Don't monologue."
)
```

**Change:** pick a voice, tweak the system prompt. That's it.

---

## Step 5 — `orb.py` (browser server + audio bridge)

This is the Flask app. Serves the UI on `/`, state on `/state`, and the
audio WebSocket on `/audio`.

```python
"""
orb.py — browser-based audio bridge + visual state.
Flask on :5001. Browser tab handles mic + speaker via WebRTC.
"""
import json
import threading
import webbrowser
from flask import Flask, jsonify
from flask_sock import Sock

IDLE, LISTENING, THINKING, SPEAKING = "idle", "listening", "thinking", "speaking"

_state = IDLE
_state_lock = threading.Lock()

app  = Flask(__name__)
sock = Sock(app)


def set_state(s):
    global _state
    with _state_lock:
        _state = s


def get_state():
    with _state_lock:
        return _state


@app.route("/state")
def _state_endpoint():
    return jsonify({"state": get_state()})


@app.route("/")
def _index():
    return ORB_HTML


@sock.route("/audio")
def _audio_ws(ws):
    """Bridge browser ⇄ realtime.py queues."""
    import realtime
    stop_flag = threading.Event()

    def reader():
        try:
            while not stop_flag.is_set():
                data = ws.receive(timeout=1)
                if data is None:
                    continue
                if isinstance(data, (bytes, bytearray)):
                    try:
                        realtime.mic_in.put_nowait(bytes(data))
                    except Exception:
                        pass   # backpressure drop
        except Exception:
            pass
        finally:
            stop_flag.set()

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    try:
        while not stop_flag.is_set():
            try:
                frame = realtime.audio_out.get(timeout=0.1)
            except Exception:
                if not t.is_alive():
                    break
                continue
            try:
                if frame is None:
                    ws.send(json.dumps({"type": "flush"}))
                else:
                    ws.send(frame)
            except Exception:
                break
    finally:
        stop_flag.set()


def run():
    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    threading.Timer(1.2, lambda: webbrowser.open("http://localhost:5001")).start()


def _serve():
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.run(host="127.0.0.1", port=5001, debug=False, use_reloader=False, threaded=True)


# ── Browser HTML + JS ─────────────────────────────────────────────────────────
ORB_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Voice</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:#08080c; color:#888; display:flex; flex-direction:column;
         align-items:center; justify-content:center; height:100vh;
         font-family:'Courier New', monospace; }
  #orb { width:200px; height:200px; border-radius:50%;
         background:radial-gradient(circle, #4af 0%, #08080c 70%);
         transition: all 0.3s; }
  #label { margin-top:20px; letter-spacing:4px; font-size:12px; }
  #hint { position:absolute; bottom:24px; font-size:10px; color:#555; }
</style></head>
<body>
<div id="orb"></div>
<div id="label">IDLE</div>
<div id="hint">click anywhere to enable audio</div>
<script>
const orb = document.getElementById('orb');
const label = document.getElementById('label');
const hint = document.getElementById('hint');

const COLORS = {
  idle:'#4af', listening:'#5cf', thinking:'#fa4', speaking:'#4f8'
};

let state = 'idle';

async function pollState() {
  try {
    const r = await fetch('/state');
    const d = await r.json();
    state = d.state;
    label.textContent = state.toUpperCase();
    orb.style.background = `radial-gradient(circle, ${COLORS[state]} 0%, #08080c 70%)`;
  } catch(e) {}
  setTimeout(pollState, 200);
}

// ── Audio: mic capture + speaker playback ────────────────────────────────────
let ws = null, micCtx = null, playCtx = null;
let nextStart = 0, activeSources = [];
let audioStarted = false;

async function startAudio() {
  if (audioStarted) return;
  audioStarted = true;
  hint.textContent = 'connecting...';

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl:  true,
        channelCount:     1,
      }
    });
  } catch (err) {
    hint.textContent = 'mic denied: ' + err.message;
    audioStarted = false;
    return;
  }

  micCtx  = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 48000 });
  playCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
  nextStart = playCtx.currentTime;
  connectWS();

  const src  = micCtx.createMediaStreamSource(stream);
  const proc = micCtx.createScriptProcessor(4096, 1, 1);
  src.connect(proc);
  proc.connect(micCtx.destination);

  proc.onaudioprocess = (e) => {
    if (!ws || ws.readyState !== 1) return;
    const f32 = e.inputBuffer.getChannelData(0);
    // downsample 48k → 24k (drop every other sample)
    const i16 = new Int16Array(Math.floor(f32.length / 2));
    for (let i = 0, j = 0; j < i16.length; i += 2, j++) {
      const s = Math.max(-1, Math.min(1, f32[i]));
      i16[j] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    ws.send(i16.buffer);
  };

  hint.textContent = 'mic live';
}

function connectWS() {
  ws = new WebSocket(`ws://${location.host}/audio`);
  ws.binaryType = 'arraybuffer';

  ws.onmessage = (ev) => {
    if (typeof ev.data === 'string') {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === 'flush') flushPlayback();
      } catch(e) {}
      return;
    }
    const i16 = new Int16Array(ev.data);
    const f32 = new Float32Array(i16.length);
    for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / 32768;
    const buf = playCtx.createBuffer(1, f32.length, 24000);
    buf.copyToChannel(f32, 0);
    const s = playCtx.createBufferSource();
    s.buffer = buf;
    s.connect(playCtx.destination);
    const now = playCtx.currentTime;
    const t = Math.max(now, nextStart);
    s.start(t);
    nextStart = t + buf.duration;
    activeSources.push(s);
    s.onended = () => { activeSources = activeSources.filter(x => x !== s); };
  };

  ws.onclose = () => { setTimeout(() => { if (audioStarted) connectWS(); }, 800); };
  ws.onerror = () => { try { ws.close(); } catch(e) {} };
}

function flushPlayback() {
  for (const s of activeSources) { try { s.stop(); } catch(e) {} }
  activeSources = [];
  nextStart = playCtx ? playCtx.currentTime : 0;
}

document.addEventListener('click',  startAudio, { once: true });
document.addEventListener('keydown', startAudio, { once: true });

pollState();
</script>
</body></html>
"""
```

**What's happening here:**
- Browser JS: `getUserMedia({echoCancellation:true})` gives you WebRTC AEC. Mic captured at 48kHz, downsampled to 24kHz Int16, sent as binary over WebSocket.
- Playback: OpenAI audio (24kHz Int16) comes in, scheduled through `AudioBufferSourceNode` with `nextStart` tracking so frames play gapless.
- Flush: when the server sends `{"type":"flush"}` (barge-in), we stop all scheduled sources and reset `nextStart`. This is how interruption works.
- User gesture gate: browsers won't let you start mic or audio until the user clicks. That's what "click anywhere to enable audio" is for.

---

## Step 6 — `realtime.py` (OpenAI Realtime client)

```python
"""
realtime.py — OpenAI Realtime API client.
Two queues bridge browser audio (orb.py) to the OpenAI WebSocket.
"""
import asyncio
import base64
import json
import queue
import threading
import websockets

import orb
from config import OPENAI_API_KEY, REALTIME_MODEL, REALTIME_VOICE, SYSTEM_PROMPT

WS_URL = f"wss://api.openai.com/v1/realtime?model={REALTIME_MODEL}"
WS_HEADERS = {
    "Authorization": f"Bearer {OPENAI_API_KEY}",
    "OpenAI-Beta":   "realtime=v1",
}

# Audio bridge queues (shared with orb.py)
mic_in    = queue.Queue(maxsize=200)   # browser → OpenAI  (24kHz int16 bytes)
audio_out = queue.Queue(maxsize=200)   # OpenAI → browser  (24kHz int16 bytes; None = flush)

# Optional: define tool schemas + a dispatcher to give the model function-calling
TOOL_SCHEMAS = []   # add OpenAI tool specs here

def dispatch_tool(name, args):
    return f"Tool '{name}' not implemented."

# ── Internal state ────────────────────────────────────────────────────────────
_session_active  = False
_ws              = None
_event_loop      = None
_pending_calls   = {}
_user_transcript = ""
_asst_transcript = ""


def _drain_audio_out():
    while not audio_out.empty():
        try: audio_out.get_nowait()
        except queue.Empty: break


def _barge_in():
    """Drain queued audio and signal the browser to flush in-flight playback."""
    _drain_audio_out()
    try: audio_out.put_nowait(None)
    except queue.Full: pass


# ── Mic → OpenAI ──────────────────────────────────────────────────────────────
async def _mic_sender(ws):
    loop = asyncio.get_event_loop()
    while _session_active:
        try:
            frame = await loop.run_in_executor(None, lambda: mic_in.get(timeout=0.1))
        except queue.Empty:
            continue
        if frame is None:
            continue
        try:
            await ws.send(json.dumps({
                "type":  "input_audio_buffer.append",
                "audio": base64.b64encode(frame).decode(),
            }))
        except websockets.exceptions.ConnectionClosed:
            break


# ── OpenAI events ─────────────────────────────────────────────────────────────
async def _handle_events(ws):
    global _user_transcript, _asst_transcript, _pending_calls
    async for raw in ws:
        if not _session_active:
            break
        event = json.loads(raw)
        etype = event.get("type", "")

        if etype == "session.created":
            print("[Realtime] Connected. Listening...")
            orb.set_state(orb.LISTENING)

        elif etype == "input_audio_buffer.speech_started":
            _barge_in()
            orb.set_state(orb.LISTENING)

        elif etype == "input_audio_buffer.speech_stopped":
            orb.set_state(orb.THINKING)

        elif etype == "conversation.item.input_audio_transcription.completed":
            _user_transcript = event.get("transcript", "").strip()
            if _user_transcript:
                print(f"\nYou: {_user_transcript}")

        elif etype == "response.output_item.added":
            item = event.get("item", {})
            if item.get("type") == "function_call":
                cid = item.get("call_id", "")
                _pending_calls[cid] = {"name": item.get("name", ""), "args": ""}

        elif etype == "response.function_call_arguments.delta":
            cid = event.get("call_id", "")
            if cid in _pending_calls:
                _pending_calls[cid]["args"] += event.get("delta", "")

        elif etype == "response.function_call_arguments.done":
            cid  = event.get("call_id", "")
            call = _pending_calls.pop(cid, None)
            if call:
                try:    args = json.loads(event.get("arguments", "{}") or "{}")
                except: args = {}
                result = dispatch_tool(call["name"], args)
                await ws.send(json.dumps({
                    "type": "conversation.item.create",
                    "item": {"type": "function_call_output", "call_id": cid, "output": str(result)}
                }))
                await ws.send(json.dumps({"type": "response.create"}))

        elif etype == "response.audio.delta":
            audio = base64.b64decode(event["delta"])
            try: audio_out.put_nowait(audio)
            except queue.Full: pass
            orb.set_state(orb.SPEAKING)

        elif etype == "response.audio_transcript.delta":
            _asst_transcript += event.get("delta", "")

        elif etype == "response.done":
            if _asst_transcript:
                print(f"AI: {_asst_transcript.strip()}")
            _user_transcript = ""
            _asst_transcript = ""
            orb.set_state(orb.LISTENING)

        elif etype == "response.cancelled":
            _barge_in()
            orb.set_state(orb.LISTENING)

        elif etype == "error":
            print(f"[Realtime Error] {event.get('error', event)}")


# ── Session lifecycle ─────────────────────────────────────────────────────────
async def _run_session():
    global _ws, _session_active
    try:
        async with websockets.connect(WS_URL, additional_headers=WS_HEADERS) as ws:
            _ws = ws
            await ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "modalities":                ["audio", "text"],
                    "instructions":              SYSTEM_PROMPT,
                    "voice":                     REALTIME_VOICE,
                    "input_audio_format":        "pcm16",
                    "output_audio_format":       "pcm16",
                    "input_audio_transcription": {"model": "whisper-1"},
                    "turn_detection": {
                        "type":                "server_vad",
                        "threshold":           0.5,
                        "prefix_padding_ms":   300,
                        "silence_duration_ms": 700,
                    },
                    "tools":       TOOL_SCHEMAS,
                    "tool_choice": "auto",
                    "temperature": 0.7,
                }
            }))
            await asyncio.gather(_mic_sender(ws), _handle_events(ws))
    except websockets.exceptions.ConnectionClosed:
        print("[Realtime] Connection closed.")
    except Exception as e:
        print(f"[Realtime] Session error: {e}")
    finally:
        _ws = None
        _session_active = False
        _drain_audio_out()
        orb.set_state(orb.IDLE)


def start():
    """Call once at boot. Spins up an asyncio loop in a daemon thread."""
    global _event_loop
    _event_loop = asyncio.new_event_loop()
    threading.Thread(target=_event_loop.run_forever, daemon=True).start()
    print("[Realtime] Engine ready. Press Cmd+Shift+T to talk.")


def start_session():
    global _session_active
    if _session_active:
        return
    _session_active = True
    print("[Realtime] Session ON")
    asyncio.run_coroutine_threadsafe(_run_session(), _event_loop)


def end_session():
    global _session_active, _ws
    _session_active = False
    _barge_in()
    if _ws and _event_loop:
        asyncio.run_coroutine_threadsafe(_ws.close(), _event_loop)
    orb.set_state(orb.IDLE)
    print("[Realtime] Session OFF")


def toggle_session():
    if _session_active:
        end_session()
    else:
        start_session()
```

**Key things to know:**
- `mic_in` / `audio_out` queues are the ONLY handoff between the Flask thread (browser side) and the asyncio loop (OpenAI side). Keeps the two worlds decoupled.
- `_mic_sender` uses `loop.run_in_executor` to read the blocking queue without freezing the event loop.
- `_barge_in()` is called on `speech_started` and `response.cancelled`. It drains `audio_out` and pushes a `None` sentinel, which the `/audio` route converts to a JSON flush message. That's how interruption works end-to-end.
- VAD values — `threshold: 0.5`, `silence_duration_ms: 700` — are what we landed on after tuning. Higher threshold = less sensitive (fires only on loud clear speech). Longer silence = waits longer before ending a turn. Tune if needed.
- `TOOL_SCHEMAS` + `dispatch_tool` are the plug-in point for function calling. Leave empty for a pure voice chat.

---

## Step 7 — `hotkey.py` (optional — Cmd+Shift+T to toggle)

```python
"""
hotkey.py — Global Cmd+Shift+T listener.
Install: pip install pynput
macOS: grant Accessibility permission on first run.
"""
import threading
from pynput import keyboard

_MODS  = {keyboard.Key.cmd, keyboard.Key.shift}
_KEY_T = keyboard.KeyCode(char='t')

_pressed   = set()
_toggle_fn = None
_fired     = False


def _on_press(key):
    global _fired
    _pressed.add(key)
    if _KEY_T in _pressed and _MODS.issubset(_pressed) and not _fired:
        _fired = True
        if _toggle_fn:
            threading.Thread(target=_toggle_fn, daemon=True).start()


def _on_release(key):
    global _fired
    _pressed.discard(key)
    if key == _KEY_T:
        _fired = False


def start(toggle_fn):
    global _toggle_fn
    _toggle_fn = toggle_fn
    listener = keyboard.Listener(on_press=_on_press, on_release=_on_release)
    listener.daemon = True
    listener.start()
    print("[Hotkey] Cmd+Shift+T → toggle voice session")
```

Skip this file if you want to start the session programmatically (e.g. an
on-screen button). In that case, `realtime.start_session()` and
`realtime.end_session()` are your handles.

---

## Step 8 — `main.py`

```python
"""
main.py — boot everything.
"""
import time
import config   # noqa: F401 — loads .env first
import orb
import realtime
import hotkey


def main():
    orb.run()                           # 1. browser tab
    realtime.start()                    # 2. OpenAI event loop
    hotkey.start(realtime.toggle_session)  # 3. Cmd+Shift+T toggle

    print("Ready. Press Cmd+Shift+T to talk.")

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nShutting down.")
        realtime.end_session()
        import os
        os._exit(0)


if __name__ == "__main__":
    main()
```

---

## Step 9 — Run it

```bash
python main.py
```

What happens:
1. Terminal prints `Ready. Press Cmd+Shift+T to talk.`
2. Browser tab opens at `http://localhost:5001` showing the orb.
3. **Click anywhere in the tab** to enable audio. Browser asks for mic permission — grant it (one-time per origin).
4. **Press Cmd+Shift+T** to start a session. Terminal prints `[Realtime] Session ON` → `[Realtime] Connected. Listening...`.
5. Talk. Reply comes back in <1s.
6. Interrupt mid-sentence — it should stop and listen.
7. Press Cmd+Shift+T again to end the session.

---

## Step 10 — Troubleshooting

**Browser tab opens but orb never turns blue / no connection**
Check terminal — likely `OPENAI_API_KEY` missing or model name wrong. Confirm
your account has Realtime API access.

**"mic denied" in the hint line**
macOS blocked mic. System Settings → Privacy & Security → Microphone → allow
your browser.

**Hotkey doesn't fire**
macOS blocked pynput. System Settings → Privacy & Security → Accessibility →
add your terminal (or Python). Restart the terminal after.

**Echo loop / AI hears itself**
Browser AEC should handle this automatically. If it doesn't:
- Make sure you clicked into the tab to start the audio context (not just
  opened it)
- Try Chrome if you're on Safari — Safari's AEC is weaker
- Check `getUserMedia` constraints include `echoCancellation: true` (they do
  in the code above)

**AI cuts me off too fast / too slow**
Tune VAD in `realtime.py` `session.update`:
- `threshold` — 0.3 (hair-trigger) ↔ 0.9 (needs loud speech). Default 0.5.
- `silence_duration_ms` — how long you pause before a turn ends. Default 700.
  Raise to 1000+ if you keep getting cut off mid-thought.

**Latency feels slow**
- `gpt-4o-mini-realtime-preview` is fastest + cheapest.
  `gpt-4o-realtime-preview` is smarter but ~2× latency.
- Check your network — Realtime is chatty, wifi vs wired matters.

**Port 5001 already in use**
Change the port in `orb.py` `app.run(..., port=5001)`. The JS uses
`location.host`, so it'll follow automatically.

**Audio plays but has gaps / crackles**
The `nextStart` scheduler should prevent this. If it still happens, your
machine is dropping frames. Try bumping ScriptProcessor buffer from 4096 to
8192, or migrate to AudioWorklet (same shape, cleaner API).

---

## Cost ballpark

`gpt-4o-mini-realtime-preview` runs roughly **$0.15–0.25 per 10-minute
conversation** (audio in + audio out, chatty back-and-forth). Casual personal
use fits under $10/month easily. Heavy use can hit $20.

Check the exact pricing at https://openai.com/api/pricing/ — Realtime audio
is billed by the minute, separately for input vs output.

---

## Extending it

- **Tools / function calling** — add OpenAI tool specs to `TOOL_SCHEMAS` in
  `realtime.py` and implement `dispatch_tool(name, args)`. The
  `_handle_events` plumbing is already there.
- **Memory** — when you want persistence, bolt on Mem0, SQLite, whatever you
  want. Hook point: the `response.done` branch in `_handle_events`.
- **Visual state** — `orb.set_state(orb.LISTENING / THINKING / SPEAKING / IDLE)`
  is already called throughout. Style the orb div in `ORB_HTML` however you
  want.
- **Multiple voices / personalities** — swap `REALTIME_VOICE` and
  `SYSTEM_PROMPT` in `config.py`.

---

## Why this architecture (quick post-mortem)

Native `sounddevice` mic + speaker was our first attempt. Problems:
1. **Echo loop** — laptop mic picks up the speaker, sends assistant's own
   voice back as user input, model hears itself, spirals.
2. **No real barge-in** — muting the mic during playback blocks interruption
   entirely.

We tried software AEC libraries to subtract the speaker signal from the mic:
- `speexdsp-python` — won't build on Apple Silicon.
- `pyaec` — needs a time-aligned reference signal we couldn't supply cleanly.

Browser WebRTC solved it in one line: `echoCancellation: true` in
`getUserMedia`. Chrome/Safari ship with production-tuned AEC. No native deps,
no build pain, works out of the box.

The cost is that you need a browser tab running. For a voice assistant
that's almost always fine. For a headless-server use case you'd need to go
back to native and solve AEC another way (hardware echo cancellation, or
headphones so there's no echo to cancel).
