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
import os
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
@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "truman", "mac": "connected" if _mac_ws else "disconnected"})


@app.route("/state")
def state_endpoint():
    return jsonify({"state": get_state()})


@app.route("/")
def index():
    return ORB_HTML


@app.route("/dashboard")
def dashboard():
    return DASHBOARD_HTML


@app.route("/logs")
def logs_page():
    try:
        from truman.storage import db
        turns = db.recent_turns(50)
        rows = "".join(
            f'<div class="row {"user" if t["role"]=="user" else "bot"}">'
            f'<span class="who">{"Om" if t["role"]=="user" else "Truman"}</span>'
            f'<span class="ts">{(t.get("ts") or "")[:16]}</span>'
            f'<span class="txt">{t["content"][:300]}</span></div>'
            for t in turns
        )
        return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Truman Logs</title>
<style>
body{{background:#0a0a0f;color:#e8e8f0;font-family:monospace;padding:16px;font-size:13px;}}
h2{{color:#a78bfa;margin-bottom:16px;}}
.row{{padding:8px 0;border-bottom:1px solid #1a1a2e;display:flex;gap:10px;flex-wrap:wrap;}}
.who{{color:#4f46e5;min-width:50px;font-weight:bold;}}
.who.bot{{color:#a78bfa;}}
.ts{{color:#444460;font-size:11px;min-width:100px;}}
.txt{{color:#c8c8e0;flex:1;}}
.user .who{{color:#4f46e5;}}
a{{color:#a78bfa;text-decoration:none;}}
</style></head><body>
<h2>TRUMAN LOGS</h2>
<a href="/dashboard">← dashboard</a>&nbsp;&nbsp;<a href="/health">health</a>
<br><br>{rows or "<p style='color:#444'>no turns yet</p>"}
</body></html>"""
    except Exception as e:
        return f"<pre>error: {e}</pre>", 500


@app.route("/api/chat", methods=["POST"])
def api_chat():
    from flask import request
    import concurrent.futures
    data = request.get_json(silent=True) or {}
    user_input = (data.get("message") or "").strip()
    if not user_input:
        return jsonify({"error": "empty message"}), 400
    try:
        from truman.text.agent import run as agent_run
        from truman.storage import db as _db

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(agent_run, user_input)
            try:
                result = future.result(timeout=45)
            except concurrent.futures.TimeoutError:
                return jsonify({"error": "response timed out — try again"}), 504

        # log to SQLite
        try:
            sid = _db.start_session() if not hasattr(api_chat, '_sid') else api_chat._sid
            api_chat._sid = sid
            _db.log_turn(sid, "user", user_input)
            _db.log_turn(sid, "assistant", result["response"])
        except Exception:
            pass

        mac_status = "connected" if _mac_ws else "disconnected"
        return jsonify({
            "response":   result["response"],
            "model":      result["model"],
            "pool":       result["pool"],
            "tool_calls": result["tool_calls"],
            "mood":       result["mood"],
            "warnings":   result.get("warnings", []),
            "mac":        mac_status,
        })
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/history")
def api_history():
    """Return last 30 turns from SQLite for dashboard page-load restore."""
    try:
        from truman.storage import db
        turns = db.recent_turns(30)
        return jsonify({"turns": turns})
    except Exception as e:
        return jsonify({"turns": [], "error": str(e)})


# ── File Upload ───────────────────────────────────────────────────────────────
TEXT_EXTS = {".py",".js",".ts",".html",".css",".json",".md",".txt",".csv",".xml",".yaml",".yml",".sh",".env"}
IMAGE_EXTS = {".png",".jpg",".jpeg",".gif",".webp",".bmp",".tiff"}

def _extract_text(filename: str, data: bytes) -> str:
    import io
    ext = os.path.splitext(filename)[1].lower()
    if ext in TEXT_EXTS:
        return data.decode("utf-8", errors="replace")
    if ext == ".pdf":
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            return "\n".join(p.extract_text() or "" for p in pdf.pages)
    if ext in (".docx",):
        from docx import Document
        return "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)
    if ext in (".xlsx",):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        rows = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                rows.append("\t".join("" if v is None else str(v) for v in row))
        return "\n".join(rows)
    if ext in (".pptx",):
        from pptx import Presentation
        lines = []
        for slide in Presentation(io.BytesIO(data)).slides:
            for shape in slide.shapes:
                if shape.has_text_frame:
                    lines.append(shape.text_frame.text)
        return "\n".join(lines)
    if ext in IMAGE_EXTS:
        return "__IMAGE__"   # signal to handler to use vision model
    return data.decode("utf-8", errors="replace")


@app.route("/api/upload", methods=["POST"])
def api_upload():
    from flask import request
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "no file"}), 400
    data = f.read()
    ext  = os.path.splitext(f.filename)[1].lower()
    try:
        text = _extract_text(f.filename, data)
    except Exception as e:
        return jsonify({"error": f"parse failed: {e}"}), 500

    if text == "__IMAGE__":
        # send to NVIDIA vision model
        try:
            import base64
            from langchain_openai import ChatOpenAI
            from truman.core.config import NVIDIA_API_KEY, NVIDIA_BASE_URL
            b64 = base64.b64encode(data).decode()
            mime = "image/png" if ext == ".png" else "image/jpeg"
            llm = ChatOpenAI(model="nvidia/llama-4-maverick-17b-128e-instruct",
                             api_key=NVIDIA_API_KEY, base_url=NVIDIA_BASE_URL)
            resp = llm.invoke([{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    {"type": "text", "text": "Describe this image in detail. Extract any text, data, or key info visible."}
                ]
            }])
            text = resp.content
        except Exception as e:
            return jsonify({"error": f"vision failed: {e}"}), 500

    # trim to 8000 chars to avoid token flood
    if len(text) > 8000:
        text = text[:8000] + "\n\n[...truncated]"

    return jsonify({"filename": f.filename, "text": text})


# ── Mac Bridge WebSocket (Railway side) ──────────────────────────────────────
BRIDGE_SECRET = os.environ.get("BRIDGE_SECRET", "truman-bridge-secret")
_mac_ws = None
_mac_ws_lock = threading.Lock()
_pending: dict = {}   # id → asyncio.Event (not needed — flask-sock is sync)
_pending_results: dict = {}


@sock.route("/mac-bridge")
def mac_bridge_ws(ws):
    """Accepts persistent connection from the Mac Bridge daemon."""
    global _mac_ws
    secret = ws.environ.get("HTTP_X_BRIDGE_SECRET", "")
    if secret != BRIDGE_SECRET:
        ws.close()
        return
    with _mac_ws_lock:
        _mac_ws = ws
    print("[Bridge] Mac connected.")
    try:
        while True:
            raw = ws.receive()
            if raw is None:
                break
            try:
                msg = json.loads(raw)
                req_id = msg.get("id", "")
                if req_id in _pending:
                    _pending_results[req_id] = msg
                    _pending.pop(req_id)
            except Exception:
                pass
    finally:
        with _mac_ws_lock:
            if _mac_ws is ws:
                _mac_ws = None
        print("[Bridge] Mac disconnected.")


def mac_request(action: str, payload: dict, timeout: float = 15.0) -> dict:
    """Send a request to the Mac Bridge and wait for response."""
    import uuid, time as _time
    with _mac_ws_lock:
        ws = _mac_ws
    if not ws:
        return {"ok": False, "error": "Mac bridge not connected — laptop may be asleep."}
    req_id = str(uuid.uuid4())[:8]
    _pending[req_id] = True
    try:
        ws.send(json.dumps({"id": req_id, "action": action, **payload}))
    except Exception as e:
        _pending.pop(req_id, None)
        return {"ok": False, "error": str(e)}
    deadline = _time.time() + timeout
    while _time.time() < deadline:
        if req_id in _pending_results:
            return _pending_results.pop(req_id)
        _time.sleep(0.1)
    _pending.pop(req_id, None)
    return {"ok": False, "error": "Mac bridge timed out."}


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

    # Auto-start Realtime session on Railway (no hotkey available in cloud).
    # If the session was just closing (_session_active briefly True while finalizer runs),
    # wait up to 3s for it to fully close before starting a new one.
    if realtime._session_active:
        # session appears active — could be live OR mid-shutdown.
        # Give it up to 3s to settle; if still active after, assume live (reuse it).
        import time as _t
        deadline = _t.time() + 3.0
        while realtime._session_active and _t.time() < deadline:
            _t.sleep(0.1)
    if not realtime._session_active:
        realtime.start_session()

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
                elif isinstance(frame, dict):
                    ws.send(json.dumps(frame))   # transcript / control messages
                else:
                    ws.send(frame)               # binary audio
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


def run(port: int = 5001, open_browser: bool = True):
    """Start orb server in background thread. Non-blocking."""
    t = threading.Thread(target=_serve, args=(port,), daemon=True)
    t.start()
    if open_browser:
        threading.Timer(1.5, _open_browser).start()


def start():
    run()


def stop():
    pass   # daemon thread dies with the process


def _serve(port: int = 5001):
    import logging
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)
    host = "0.0.0.0" if os.environ.get("RAILWAY_ENVIRONMENT") else "127.0.0.1"
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)


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

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Truman</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0a0a0f; color: #e8e8f0; font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', sans-serif; height: 100dvh; display: flex; flex-direction: column; overflow: hidden; }

  /* Header */
  .header { padding: 14px 18px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #1a1a2e; background: #0d0d1a; }
  .header h1 { font-size: 17px; font-weight: 600; letter-spacing: 0.05em; color: #a78bfa; }
  .mac-dot { width: 8px; height: 8px; border-radius: 50%; background: #ef4444; transition: background 0.3s; }
  .mac-dot.on { background: #22c55e; }
  .hdr-btn { background: none; border: 1px solid #2a2a4a; border-radius: 8px; color: #7c7caa; font-size: 11px; padding: 4px 10px; cursor: pointer; }
  .hdr-btn:hover { border-color: #4f46e5; color: #a78bfa; }
  .session-bar { padding: 6px 14px; background: #0a0a12; border-bottom: 1px solid #1a1a2e; display: flex; gap: 6px; overflow-x: auto; }
  .session-tab { background: #16162a; border: 1px solid #2a2a4a; border-radius: 8px; color: #7c7caa; font-size: 11px; padding: 4px 12px; cursor: pointer; white-space: nowrap; }
  .session-tab.active { border-color: #4f46e5; color: #a78bfa; background: #1a1a3a; }
  .session-tab:hover { border-color: #4f46e5; }

  /* Messages */
  .messages { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; scroll-behavior: smooth; }
  .messages::-webkit-scrollbar { width: 0; }

  .msg { max-width: 88%; display: flex; flex-direction: column; gap: 4px; }
  .msg.user { align-self: flex-end; align-items: flex-end; }
  .msg.truman { align-self: flex-start; }

  .bubble { padding: 10px 14px; border-radius: 16px; font-size: 15px; line-height: 1.5; }
  .msg.user .bubble { background: #4f46e5; color: #fff; border-bottom-right-radius: 4px; }
  .msg.truman .bubble { background: #16162a; color: #e8e8f0; border-bottom-left-radius: 4px; border: 1px solid #1e1e3a; }

  .meta { font-size: 11px; color: #555570; display: flex; gap: 6px; flex-wrap: wrap; }
  .msg.user .meta { justify-content: flex-end; }
  .badge { background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 6px; padding: 1px 6px; font-size: 10px; color: #7c7caa; }
  .badge.pool-coding { color: #34d399; border-color: #065f46; }
  .badge.pool-design { color: #60a5fa; border-color: #1e3a5f; }
  .badge.pool-creative { color: #f472b6; border-color: #5f1e3a; }
  .badge.pool-general { color: #a78bfa; border-color: #3a1e5f; }
  .badge.tool { color: #fbbf24; border-color: #5f4a1e; }

  /* Status indicator */
  .status-line { align-self: flex-start; font-size: 13px; color: #7c7caa; padding: 6px 4px; display: flex; align-items: center; gap: 8px; }
  .status-line .bar { width: 3px; height: 16px; border-radius: 2px; background: #4f46e5; animation: statusPulse 1s infinite; }
  .status-text { animation: statusFade 2s infinite; }
  @keyframes statusPulse { 0%,100% { opacity: 1; transform: scaleY(1); } 50% { opacity: 0.4; transform: scaleY(0.6); } }
  @keyframes statusFade { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }

  /* Input area */
  .input-area { padding: 12px 14px; border-top: 1px solid #1a1a2e; background: #0d0d1a; display: flex; gap: 10px; align-items: flex-end; }
  textarea { flex: 1; background: #16162a; border: 1px solid #2a2a4a; border-radius: 14px; padding: 10px 14px; color: #e8e8f0; font-size: 15px; resize: none; outline: none; max-height: 120px; line-height: 1.4; font-family: inherit; }
  textarea::placeholder { color: #44445a; }
  textarea:focus { border-color: #4f46e5; }

  .btn { width: 42px; height: 42px; border-radius: 50%; border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0; transition: all 0.2s; }
  .send-btn { background: #4f46e5; }
  .send-btn:hover { background: #4338ca; }
  .send-btn:active { transform: scale(0.93); }
  .voice-btn { background: #16162a; border: 1px solid #2a2a4a; }
  .voice-btn.listening { background: #7c3aed; border-color: #7c3aed; animation: pulse 1.5s infinite; }
  @keyframes pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(124,58,237,0.4); } 50% { box-shadow: 0 0 0 8px rgba(124,58,237,0); } }

  svg { pointer-events: none; }
</style>
</head>
<body>

<div class="header">
  <h1>TRUMAN</h1>
  <div style="display:flex;align-items:center;gap:8px;">
    <button class="hdr-btn" onclick="newSession()">+ new</button>
    <button class="hdr-btn" onclick="clearChat()">clear</button>
    <span style="font-size:11px;color:#555570;" id="mac-status">mac offline</span>
    <div class="mac-dot" id="mac-dot"></div>
  </div>
</div>

<div class="session-bar" id="session-bar"></div>

<div class="messages" id="messages">
  <div class="msg truman">
    <div class="bubble">yo. what's up?</div>
  </div>
</div>

<div class="input-area">
  <textarea id="input" placeholder="say something..." rows="1"></textarea>
  <input type="file" id="file-input" style="display:none" accept=".py,.js,.ts,.html,.css,.json,.md,.txt,.csv,.xml,.yaml,.yml,.sh,.pdf,.docx,.xlsx,.pptx,.png,.jpg,.jpeg,.gif,.webp,.bmp">
  <button class="btn voice-btn" id="upload-btn" title="upload file" onclick="document.getElementById('file-input').click()">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>
    </svg>
  </button>
  <button class="btn voice-btn" id="voice-btn" title="tap to talk">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
      <path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v4M8 23h8"/>
    </svg>
  </button>
  <button class="btn send-btn" id="send-btn" onclick="send()">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5">
      <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
    </svg>
  </button>
</div>

<script>
const messages   = document.getElementById('messages');
const input      = document.getElementById('input');
const sendBtn    = document.getElementById('send-btn');
const voiceBtn   = document.getElementById('voice-btn');
const macDot     = document.getElementById('mac-dot');
const macStatus  = document.getElementById('mac-status');
const sessionBar = document.getElementById('session-bar');

// ── Session management ──────────────────────────────────────────────────────
let sessions = [{id: Date.now(), label: 'chat 1', msgs: []}];
let currentSession = 0;

function renderSessionBar() {
  sessionBar.innerHTML = '';
  sessions.forEach((s, i) => {
    const tab = document.createElement('div');
    tab.className = 'session-tab' + (i === currentSession ? ' active' : '');
    tab.textContent = s.label;
    tab.onclick = () => switchSession(i);
    sessionBar.appendChild(tab);
  });
}

function switchSession(i) {
  // save current messages
  sessions[currentSession].msgs = messages.innerHTML;
  currentSession = i;
  messages.innerHTML = sessions[i].msgs || '<div class="msg truman"><div class="bubble">yo. what\\'s up?</div></div>';
  renderSessionBar();
}

function newSession() {
  sessions[currentSession].msgs = messages.innerHTML;
  const n = sessions.length + 1;
  sessions.push({id: Date.now(), label: `chat ${n}`, msgs: ''});
  currentSession = sessions.length - 1;
  messages.innerHTML = '<div class="msg truman"><div class="bubble">yo. what\\'s up?</div></div>';
  renderSessionBar();
}

function clearChat() {
  messages.innerHTML = '<div class="msg truman"><div class="bubble">yo. what\\'s up?</div></div>';
  sessions[currentSession].msgs = '';
}

renderSessionBar();

// ── Mac status polling ──────────────────────────────────────────────────────
async function checkMac() {
  try {
    const r = await fetch('/health');
    const d = await r.json();
    const on = d.mac === 'connected';
    macDot.className = 'mac-dot' + (on ? ' on' : '');
    macStatus.textContent = on ? 'mac online' : 'mac offline';
  } catch(e) {}
}
checkMac();
setInterval(checkMac, 10000);

// ── Load history from SQLite ────────────────────────────────────────────────
async function loadHistory() {
  try {
    const r = await fetch('/api/history');
    const d = await r.json();
    if (d.turns && d.turns.length) {
      messages.innerHTML = '';
      d.turns.forEach(t => {
        addMsg(t.role === 'user' ? 'user' : 'truman', t.content, null);
      });
    }
  } catch(e) {}
}
loadHistory();

// ── Auto-resize textarea ────────────────────────────────────────────────────
input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 120) + 'px';
});

input.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});

sendBtn.addEventListener('click', send);

// ── Chat ────────────────────────────────────────────────────────────────────
function addMsg(role, text, meta) {
  const div = document.createElement('div');
  div.className = 'msg ' + role;

  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = text;
  div.appendChild(bubble);

  if (meta) {
    const m = document.createElement('div');
    m.className = 'meta';
    if (meta.model && meta.model !== 'none') {
      const b = document.createElement('span');
      b.className = 'badge';
      b.textContent = meta.model.split('/').pop().replace(':free','');
      m.appendChild(b);
    }
    if (meta.pool) {
      const b = document.createElement('span');
      b.className = 'badge pool-' + meta.pool;
      b.textContent = meta.pool;
      m.appendChild(b);
    }
    if (meta.tool_calls && meta.tool_calls.length) {
      meta.tool_calls.forEach(tc => {
        const b = document.createElement('span');
        b.className = 'badge tool';
        b.textContent = '⚙ ' + (tc.name || tc);
        m.appendChild(b);
      });
    }
    div.appendChild(m);
  }

  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
  return div;
}

const statusPhrases = [
  'thinking...', 'on it...', 'processing...', 'working on it...'
];
const toolPhrases = {
  web_search: 'searching the web...', get_weather: 'checking weather...',
  remember: 'saving to memory...', recall: 'checking memory...',
  search_history: 'digging through history...', recent_conversations: 'pulling past conversations...',
  read_mac_file: 'reading your file...', list_mac_dir: 'browsing your folders...',
  search_mac_files: 'searching your mac...', write_mac_file: 'saving to your mac...',
  set_reminder: 'setting reminder...', list_reminders: 'checking reminders...',
};

function addStatus() {
  const div = document.createElement('div');
  div.className = 'status-line';
  div.innerHTML = '<div class="bar"></div><span class="status-text">thinking...</span>';
  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;

  let i = 0;
  const span = div.querySelector('.status-text');
  const interval = setInterval(() => {
    i = (i + 1) % statusPhrases.length;
    span.textContent = statusPhrases[i];
  }, 1800);
  div._interval = interval;
  div.setTool = (tool) => { span.textContent = toolPhrases[tool] || tool + '...'; };
  div.remove = () => { clearInterval(interval); div.parentNode && div.parentNode.removeChild(div); };
  return div;
}

async function send() {
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  input.style.height = 'auto';

  addMsg('user', text, null);
  const status = addStatus();

  // animate tool names while waiting
  const toolCycle = ['web_search','recall','search_history','remember'];
  let ti = 0;
  const toolInterval = setInterval(() => { status.setTool(toolCycle[ti++ % toolCycle.length]); }, 3000);

  try {
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: text})
    });
    const d = await r.json();
    clearInterval(toolInterval);
    status.remove();
    if (d.error) { addMsg('truman', 'error: ' + d.error, null); return; }
    const respText = (d.response || '').trim();
    if (!respText) { addMsg('truman', '(no response — try again)', null); return; }
    addMsg('truman', respText, {model: d.model || 'deepseek-v3.2', pool: d.pool || 'general', tool_calls: d.tool_calls});
    // update mac dot
    macDot.className = 'mac-dot' + (d.mac === 'connected' ? ' on' : '');
    macStatus.textContent = d.mac === 'connected' ? 'mac online' : 'mac offline';
  } catch(e) {
    clearInterval(toolInterval);
    status.remove();
    addMsg('truman', 'connection error — check railway is up', null);
  }
}

// ── File Upload ─────────────────────────────────────────────────────────────
document.getElementById('file-input').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  e.target.value = '';
  const status = addStatus();
  status.querySelector('.status-text').textContent = `reading ${file.name}...`;
  try {
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch('/api/upload', {method:'POST', body: fd});
    const d = await r.json();
    status.remove();
    if (d.error) { addMsg('truman', 'upload error: ' + d.error, null); return; }
    // send extracted content to chat
    const prompt = `[File: ${d.filename}]\n\n${d.text}`;
    input.value = prompt;
    send();
  } catch(e) {
    status.remove();
    addMsg('truman', 'upload failed', null);
  }
});

// ── Voice — /audio WebSocket → OpenAI Realtime (ash voice) ────────────────
let audioWs = null, audioCtx = null, micStream = null, processor = null;
let isVoiceActive = false;
let reconnecting = false;

// How far ahead to schedule audio — bigger = fewer gaps on variable-latency Railway proxy
const PLAYBACK_BUFFER_SEC = 0.20;  // 200ms jitter buffer

async function startVoice() {
  if (isVoiceActive || reconnecting) return;
  try {
    // Let AudioContext pick native sample rate (Safari iOS may not support forced 48kHz)
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    await audioCtx.resume();
    const nativeRate = audioCtx.sampleRate;  // e.g. 48000 on Chrome, 44100 on some Safari
    const downsampleRatio = nativeRate / 24000;  // exact ratio for correct pitch

    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, sampleRate: nativeRate }
    });
    const wsUrl = (location.protocol==='https:'?'wss':'ws') + '://' + location.host + '/audio';
    audioWs = new WebSocket(wsUrl);
    audioWs.binaryType = 'arraybuffer';

    audioWs.onopen = () => {
      isVoiceActive = true;
      voiceBtn.classList.add('listening');
      voiceBtn.title = 'tap to disconnect';
      const src = audioCtx.createMediaStreamSource(micStream);
      // 4096 frames @ native rate → chunk every ~85ms — good balance of latency vs CPU
      processor = audioCtx.createScriptProcessor(4096, 1, 1);
      processor.onaudioprocess = ev => {
        if (!audioWs || audioWs.readyState !== 1) return;
        const f32 = ev.inputBuffer.getChannelData(0);
        // Downsample to 24kHz using 2-tap average (anti-aliasing) instead of naive skip
        const outLen = Math.floor(f32.length / downsampleRatio);
        const out = new Int16Array(outLen);
        const step = downsampleRatio;
        for (let i = 0; i < outLen; i++) {
          const pos = i * step;
          const lo = Math.floor(pos), hi = Math.min(lo + 1, f32.length - 1);
          const frac = pos - lo;
          const sample = f32[lo] * (1 - frac) + f32[hi] * frac;  // linear interpolation
          out[i] = Math.max(-32768, Math.min(32767, sample * 32768));
        }
        audioWs.send(out.buffer);
      };
      src.connect(processor); processor.connect(audioCtx.destination);
    };

    // Playback: schedule ahead by PLAYBACK_BUFFER_SEC to absorb Railway jitter
    let nextPlay = 0;
    audioWs.onmessage = e => {
      if (typeof e.data === 'string') {
        try {
          const m = JSON.parse(e.data);
          if (m.type === 'flush') nextPlay = 0;
          if (m.type === 'evicted') { stopVoice(); return; }
          if (m.type === 'transcript') {
            // Voice turn completed — show in chat just like text chat
            const role = m.role === 'user' ? 'user' : 'truman';
            addMsg(role, m.text, role === 'truman' ? {model: 'realtime/ash', pool: 'voice'} : null);
          }
        } catch(err) {}
        return;
      }
      const i16 = new Int16Array(e.data);
      const f32 = new Float32Array(i16.length);
      for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / 32768;
      const buf = audioCtx.createBuffer(1, f32.length, 24000);
      buf.copyToChannel(f32, 0);
      const node = audioCtx.createBufferSource();
      node.buffer = buf;
      node.connect(audioCtx.destination);
      const now = audioCtx.currentTime;
      // Reset ahead of now if we've fallen behind (e.g. after flush or long gap)
      if (nextPlay < now + 0.01) nextPlay = now + PLAYBACK_BUFFER_SEC;
      node.start(nextPlay);
      nextPlay += buf.duration;
    };

    audioWs.onerror = () => {
      // onclose will fire right after — let it handle reconnect
    };
    audioWs.onclose = () => {
      if (!isVoiceActive) return;  // already cleaned up (user tapped stop)
      stopVoice();
      // Reconnect after brief delay — give Railway time to release the old socket
      reconnecting = true;
      setTimeout(() => { reconnecting = false; startVoice(); }, 2000);
    };

  } catch(e) {
    console.error('voice error', e);
    stopVoice();
  }
}

function stopVoice() {
  isVoiceActive = false;
  reconnecting = false;
  voiceBtn.classList.remove('listening');
  voiceBtn.title = 'tap to talk';
  if (processor) { try { processor.disconnect(); } catch(e) {} processor = null; }
  if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
  if (audioWs && audioWs.readyState < 2) { try { audioWs.close(); } catch(e) {} }
  audioWs = null;
  if (audioCtx) { try { audioCtx.close(); } catch(e) {} audioCtx = null; }
}

voiceBtn.addEventListener('click', () => { isVoiceActive ? stopVoice() : startVoice(); });
</script>
</body>
</html>
"""
