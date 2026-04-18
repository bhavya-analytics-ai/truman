"""
orb.py — Truman's visual presence + browser audio bridge
Flask on :5001 serves:
  /         → orb UI (canvas animation)
  /state    → current visual state (polled by UI)
  /audio    → WebSocket carrying 24kHz int16 PCM both ways

The browser handles mic capture + speaker playback. getUserMedia(echoCancellation:true)
gives us production-grade AEC so Truman doesn't hear himself.

States: idle | listening | thinking | speaking
"""

import json
import subprocess
import sys
import threading
import webbrowser
from flask import Flask, jsonify
from flask_sock import Sock

ORB_URL = "http://localhost:5001"

# ── State constants ───────────────────────────────────────────────────────────
IDLE      = "idle"
LISTENING = "listening"
THINKING  = "thinking"
SPEAKING  = "speaking"

# ── Shared state ──────────────────────────────────────────────────────────────
_state      = IDLE
_state_lock = threading.Lock()

# ── Single-client audio guard ─────────────────────────────────────────────────
# Only ONE browser tab can own the audio stream at a time. If a second tab
# connects, it evicts the first. Without this, multiple tabs split the audio
# queue and you hear fragmented "2-3 bot" echo.
_active_ws          = None
_active_ws_stop_ev  = None
_active_ws_lock     = threading.Lock()

app  = Flask(__name__)
sock = Sock(app)


def set_state(state: str):
    global _state
    with _state_lock:
        _state = state


def get_state() -> str:
    with _state_lock:
        return _state


# ── Flask routes ──────────────────────────────────────────────────────────────
@app.route("/state")
def state_endpoint():
    return jsonify({"state": get_state()})


@app.route("/")
def index():
    return ORB_HTML


# ── Audio WebSocket ───────────────────────────────────────────────────────────
@sock.route("/audio")
def audio_ws(ws):
    """Bridge browser ⇄ realtime.py queues.

    Inbound  (browser binary frames, 24kHz int16 PCM) → realtime.mic_in
    Outbound (realtime.audio_out frames)              → browser binary frames
    A None sentinel on audio_out is translated to a JSON flush message.

    Single-client: when a new tab connects, the previous one is evicted so
    only ONE browser pulls from the audio queue. Prevents "multiple bots
    speaking" echo when old tabs linger across restarts.
    """
    from truman.voice import realtime  # deferred import to avoid circular dep

    global _active_ws, _active_ws_stop_ev
    stop_flag = threading.Event()

    # Evict any prior client before we take over the audio queue
    with _active_ws_lock:
        if _active_ws_stop_ev is not None:
            _active_ws_stop_ev.set()
            try:
                # Tell the old tab to shut itself (prevents auto-reconnect storm)
                _active_ws.send(json.dumps({"type": "evicted"}))
                _active_ws.close()
            except Exception:
                pass
        _active_ws         = ws
        _active_ws_stop_ev = stop_flag
        print("[Orb] Audio client connected (sole consumer)")

    def reader():
        # Browser → OpenAI
        try:
            while not stop_flag.is_set():
                data = ws.receive(timeout=1)
                if data is None:
                    continue
                if isinstance(data, (bytes, bytearray)):
                    try:
                        realtime.mic_in.put_nowait(bytes(data))
                    except Exception:
                        pass   # drop on backpressure
                # text frames (control messages) ignored for now
        except Exception:
            pass
        finally:
            stop_flag.set()

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    # OpenAI → Browser
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
        with _active_ws_lock:
            if _active_ws is ws:
                _active_ws         = None
                _active_ws_stop_ev = None


# ── Public API ────────────────────────────────────────────────────────────────
def _open_browser():
    """Open the orb UI in a NEW browser window and bring it to the front.
    Uses osascript on Mac so the window can't hide behind existing tabs/spaces."""
    try:
        if sys.platform == "darwin":
            # osascript: open URL in a brand-new Chrome/Safari/default window AND activate it
            script = f'''
            tell application "System Events"
                set frontApp to name of (first application process whose frontmost is true)
            end tell
            try
                tell application "Google Chrome"
                    activate
                    make new window
                    set URL of active tab of front window to "{ORB_URL}"
                end tell
            on error
                try
                    tell application "Safari"
                        activate
                        make new document with properties {{URL:"{ORB_URL}"}}
                    end tell
                on error
                    do shell script "open '{ORB_URL}'"
                end try
            end try
            '''
            subprocess.Popen(["osascript", "-e", script])
        else:
            webbrowser.open_new(ORB_URL)
        print(f"[Orb] Opened {ORB_URL} in new window")
    except Exception as e:
        print(f"[Orb] Could not auto-open browser ({e}). Visit {ORB_URL} manually.")


def run():
    """Start orb server in background thread and open browser. Non-blocking."""
    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    # give Flask a beat to bind the port before the browser tries to connect
    threading.Timer(1.5, _open_browser).start()


def start():
    run()


def stop():
    pass   # daemon thread dies with the process


def _serve():
    import logging
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)
    app.run(host="127.0.0.1", port=5001, debug=False, use_reloader=False, threaded=True)


# ── Orb HTML/JS ───────────────────────────────────────────────────────────────
ORB_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Truman</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: #08080c;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100vh;
    font-family: 'Courier New', monospace;
    overflow: hidden;
  }
  canvas { display: block; }
  #label {
    margin-top: 16px;
    font-size: 12px;
    letter-spacing: 4px;
    text-transform: uppercase;
    opacity: 0.5;
    transition: color 0.4s;
  }
  #mic-hint {
    position: absolute;
    bottom: 24px;
    font-size: 10px;
    letter-spacing: 2px;
    color: #666;
    opacity: 0.6;
  }
</style>
</head>
<body>
<canvas id="orb" width="300" height="300"></canvas>
<div id="label">IDLE</div>
<div id="mic-hint">click anywhere to enable audio</div>
<script>
const canvas = document.getElementById('orb');
const ctx    = canvas.getContext('2d');
const label  = document.getElementById('label');
const hint   = document.getElementById('mic-hint');
const W = canvas.width, H = canvas.height;
const cx = W / 2, cy = H / 2;

const COLORS = {
  idle:      [60,  120, 220],
  listening: [80,  200, 255],
  thinking:  [220, 160, 40],
  speaking:  [60,  220, 120],
};

const PARTICLES = Array.from({length: 60}, () => ({
  angle: Math.random() * Math.PI * 2,
  orbit: 100 + Math.random() * 50,
  speed: (0.008 + Math.random() * 0.017) * (Math.random() < 0.5 ? 1 : -1),
  size:  2 + Math.random() * 3,
  phase: Math.random() * Math.PI * 2,
}));

let state = 'idle';
let t = 0;

function rgb(c, a) {
  return a != null
    ? `rgba(${c[0]},${c[1]},${c[2]},${a})`
    : `rgb(${c[0]},${c[1]},${c[2]})`;
}

function drawGlow(color, radius) {
  for (let i = 4; i > 0; i--) {
    const r = radius + i * 14;
    const a = Math.max(0, 0.32 - i * 0.07);
    const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
    g.addColorStop(0, rgb(color, a));
    g.addColorStop(1, rgb(color, 0));
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fillStyle = g;
    ctx.fill();
  }
}

function draw() {
  t++;
  const color = COLORS[state] || COLORS.idle;

  let pulse, speedMul;
  if (state === 'idle')        { pulse = 1 + 0.06 * Math.sin(t * 0.03); speedMul = 1.0; }
  else if (state==='listening'){ pulse = 1 + 0.12 * Math.sin(t * 0.08); speedMul = 1.5; }
  else if (state==='thinking') { pulse = 1 + 0.05 * Math.sin(t * 0.05); speedMul = 2.5; }
  else                         { pulse = 1 + 0.18 * Math.abs(Math.sin(t * 0.12)); speedMul = 2.0; }

  const radius = Math.round(90 * pulse);

  ctx.clearRect(0, 0, W, H);
  drawGlow(color, radius);

  ctx.beginPath();
  ctx.arc(cx, cy, radius, 0, Math.PI * 2);
  ctx.fillStyle = rgb(color);
  ctx.fill();

  const inner = Math.max(10, radius - 30);
  const bright = color.map(c => Math.min(255, c + 80));
  ctx.beginPath();
  ctx.arc(cx, cy, inner, 0, Math.PI * 2);
  ctx.fillStyle = rgb(bright);
  ctx.fill();

  for (const p of PARTICLES) {
    p.angle += p.speed * speedMul;
    let orbit = p.orbit;
    if (state === 'thinking') orbit += 15 * Math.sin(t * 0.04 + p.phase);
    if (state === 'speaking') orbit += 10 * Math.sin(t * 0.15 + p.phase);

    const px = cx + orbit * Math.cos(p.angle);
    const py = cy + orbit * Math.sin(p.angle);
    const dist = Math.hypot(px - cx, py - cy);
    const alpha = Math.max(0.15, (220 - dist * 1.2) / 255);

    ctx.beginPath();
    ctx.arc(px, py, p.size, 0, Math.PI * 2);
    ctx.fillStyle = rgb(color, alpha);
    ctx.fill();
  }

  label.textContent = state.toUpperCase();
  label.style.color = rgb(color);

  requestAnimationFrame(draw);
}

// poll state every 200ms
async function pollState() {
  try {
    const r = await fetch('/state');
    const d = await r.json();
    state = d.state;
  } catch(e) {}
  setTimeout(pollState, 200);
}

// ── Audio: mic capture + speaker playback via WebSocket ────────────────────
let ws = null;
let micCtx = null;
let playCtx = null;
let micProc = null;
let micSrc = null;
let nextStart = 0;
let activeSources = [];
let audioStarted = false;
let evicted = false;   // set when server boots us because a newer tab took over

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

  micSrc  = micCtx.createMediaStreamSource(stream);
  // ScriptProcessor is deprecated but works; AudioWorklet is the upgrade path.
  micProc = micCtx.createScriptProcessor(4096, 1, 1);
  micSrc.connect(micProc);
  micProc.connect(micCtx.destination);

  micProc.onaudioprocess = (e) => {
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

  hint.textContent = 'mic live — Cmd+Option+T to talk';
}

function connectWS() {
  ws = new WebSocket(`ws://${location.host}/audio`);
  ws.binaryType = 'arraybuffer';

  ws.onmessage = (ev) => {
    // Control messages arrive as text (JSON)
    if (typeof ev.data === 'string') {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === 'flush')   flushPlayback();
        if (msg.type === 'evicted') {
          // another tab took over audio — stop and stay silent
          evicted = true;
          audioStarted = false;
          flushPlayback();
          try { ws.close(); } catch(e) {}
          hint.textContent = 'another Truman tab took over — close this one';
        }
      } catch(e) {}
      return;
    }
    // Binary: 24kHz int16 PCM
    const i16 = new Int16Array(ev.data);
    const f32 = new Float32Array(i16.length);
    for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / 32768;

    const buf = playCtx.createBuffer(1, f32.length, 24000);
    buf.copyToChannel(f32, 0);
    const src = playCtx.createBufferSource();
    src.buffer = buf;
    src.connect(playCtx.destination);

    const now = playCtx.currentTime;
    const t   = Math.max(now, nextStart);
    src.start(t);
    nextStart = t + buf.duration;

    activeSources.push(src);
    src.onended = () => {
      activeSources = activeSources.filter(s => s !== src);
    };
  };

  ws.onclose = () => {
    // Don't reconnect if we were evicted by another tab
    if (evicted) return;
    setTimeout(() => { if (audioStarted && !evicted) connectWS(); }, 800);
  };
  ws.onerror = () => { try { ws.close(); } catch(e) {} };
}

function flushPlayback() {
  for (const s of activeSources) { try { s.stop(); } catch(e) {} }
  activeSources = [];
  nextStart = playCtx ? playCtx.currentTime : 0;
}

// Browsers require a user gesture before AudioContext + mic.
document.addEventListener('click',  startAudio, { once: true });
document.addEventListener('keydown', startAudio, { once: true });

draw();
pollState();
</script>
</body>
</html>
"""
