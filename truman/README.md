# Truman

Om's personal AI OS. Voice + text. Always on via Railway. Talks back, remembers everything, runs tools, scrapes any site Om is logged into.

**Status as of 2026-05-10:** Phase B8+ — LangGraph 12-node brain, LLM-driven tool selection, real Chrome scraping via Mac Bridge, drag-drop image input, 28 tools total.

**Hackathon mode:** shipping fast, maximum leverage, every feature must directly ease Om's daily life.

---

## What Truman Does Today

- **Voice chat** via OpenAI Realtime API (`gpt-4o-mini-realtime-preview`, voice `ash`). Session auto-starts when browser connects.
- **Dashboard** at `/dashboard` — mobile-first chat UI. Text + voice unified. Voice turns show as chat bubbles. History loads from SQLite on page open.
- **Browser-hosted audio** — mic + speaker in browser tab. WebRTC AEC. 200ms jitter buffer. Linear interpolation downsampling.
- **Always-on Railway deploy** at `https://truman-production.up.railway.app`. Entry: `truman/main_cloud.py`. SQLite on persistent disk.
- **Mac Bridge** — `mac_bridge.py` daemon on Mac, persistent WS to Railway. Dispatches: `read_file`, `list_dir`, `search_files`, `write_file`, `run_shell`, `scrape_browser`, `open_login_browser`. Bridge runs dispatch in asyncio executor — event loop stays live during long scrapes.
- **Authenticated scraping** — `scrape_browser` action uses Playwright with real Chrome binary (`channel="chrome"`) + browser-cookie3 to inject Om's real Chrome cookies. Bypasses LinkedIn, Twitter, Instagram, Reddit auth walls. One-time login in real Chrome → Truman can scrape that site forever.
- **Web Intel tools** — `scrape_site`, `deep_search`, `extract_data`. Auth-walled domains route to Mac Bridge scraper (timeout=65s). Public sites hit Firecrawl/SearXNG on Hetzner (46.224.203.138:3002).
- **Image input** — drag any image onto the dashboard (purple overlay appears), paste from clipboard (Ctrl+V), or click the upload button. Analyzed via llama-4-maverick vision pool. Persistent in SQLite — survives refresh.
- **File upload** — pdf/doc/xlsx staged as chip, routes to docs pool on send.
- **Save to Mac** — "save this" / "save it" → `save_result` tool fires immediately (no confirmation), writes timestamped `.md` to `~/Desktop`. iCloud syncs to phone.
- **Long-term memory** via Mem0 hosted. Durable facts persist across sessions. Smart filter — only meaningful turns saved, dedup via semantic search.
- **Reminders** — voice or text. Fires as spoken voice alert at set time.
- **Nightly reflection** — 2am launchd, summarizes sessions, promotes facts to Mem0.
- **Mood-aware** — local regex classifier (zero API calls). Instant, no cost.
- **9-pool model router** — coding/creative/design/docs/vision/general/reasoning/fast/agentic. Intent detection auto-picks pool. Sticky routing.
- **Pool badge** — header shows which pool handled the last message. Updates live.
- **Tool chips** — visible in process strip. Running = bright, done = dim.
- **Mic orb visualizer** — floating purple orb shows when voice is active, scales with mic volume, draggable, resizable.
- **Barge-in** — say something mid-playback and Truman stops speaking, listens.
- **Pipeline mode** — deepseek-v3.2 reasons → pool model generates → glm-4.7 reviews. Explicit only, never auto.
- **Session tabs** — each tab gets a UUID, isolated chat history. Mem0 + SQLite shared across all tabs.
- **Events panel** — activity drawer shows real-time brain events (fetches `/api/events`). Timestamps shown in local timezone.
- **Error log modal** — "logs" button shows last 50 requests with timing, model, pool, status.
- **Model tools** — `list_models`, `set_model`. Ask "what models do I have" or "use deepseek".
- **History tools** — `search_history` FTS5 + `recent_conversations`.
- **Goals / rules / sleep / prefs** — persistent personal context Om can manage via voice or text.
- **browser_login** — opens URL in real Chrome + brings to front. Use to log into a site once so Truman can scrape it forever.

---

## Architecture

```
Phone/Mac Browser
  │  /dashboard  (text chat + voice) — served from static/dashboard.html
  │  /           (orb UI) — served from static/orb.html
  │  /audio WS   (binary PCM + JSON control)
  ▼
Railway (truman-production.up.railway.app)
  orb.py (Flask + flask-sock — routes only)
  ├── /api/chat  → LangGraph brain loop → SSE stream → kimi-k2 / step-3.5-flash
  ├── /api/upload → text extraction / vision model for images
  ├── /api/logs  → error log ring buffer (last 50)
  ├── /api/history → SQLite turn restore on page load
  ├── /api/events → brain event log (activity drawer)
  ├── /audio WS  → mic_in / audio_out queues → realtime.py
  ├── /mac-bridge WS ← mac_bridge.py (Mac daemon)
  └── /health, /state, /logs

LangGraph brain loop (brain/loop.py) — 12 nodes, sequential:
  tier_router → classify_mood → load_memory → self_awareness → tool_retrieval
  → [load_goals → recall_skills] → detect_pool → risk_gate → call_llm
  → risk_gate_node → evaluate_output → save_memory
  Trivial tier: skips load_goals, recall_skills, risk_gate_node (fast path)
  LLM drives tool selection via bind_tools — no regex pre-emption

Mac Bridge (mac_bridge.py) — runs on Om's Mac:
  - Connects out to Railway /mac-bridge WS (no port forwarding needed)
  - Dispatch runs in asyncio.run_in_executor → event loop stays alive during long ops
  - scrape_browser: Playwright + channel="chrome" (real Chrome) + browser-cookie3 cookies
  - open_login_browser: subprocess open + osascript activate → real Chrome opens visible
  - write_file: saves any content to Mac filesystem

realtime.py — OpenAI Realtime WS (gpt-4o-mini-realtime-preview, voice only)
model_router.py — 9 pools, sticky routing, session override, pipeline mode
agent.py — LangGraph fallback handler, per-session history, attach handling
```

---

## File Map

| File | Role |
|---|---|
| `truman/main.py` | Local orchestrator |
| `truman/main_cloud.py` | Railway entry — no hotkey/TTS/browser-open |
| `truman/mac_bridge.py` | Mac daemon — persistent WS to Railway, Chrome scraping |
| `truman/core/config.py` | Env loader, `get_llm()`, POOL_* defaults (9 pools) |
| `truman/core/risk.py` | Risk tiers — safe/caution/risky. save_result + write_mac_file = safe |
| `truman/core/model_router.py` | 9 pools, sticky routing, session override, pipeline mode |
| `truman/text/agent.py` | LangGraph runner, fallback handler, per-session history, attach handling |
| `truman/text/system_prompt.py` | System prompt — identity, style, tool rules. No sentence cap. |
| `truman/brain/loop.py` | LangGraph graph wiring — 12-node sequential brain |
| `truman/brain/nodes.py` | All node implementations (tier_router, tool_retrieval, call_llm, etc.) |
| `truman/brain/state.py` | TrumanState TypedDict |
| `truman/voice/realtime.py` | Realtime WS loop, filters, context injection, transcript push |
| `truman/voice/orb.py` | Flask routes + WebSocket handlers — serves static/ |
| `truman/voice/static/dashboard.html` | Dashboard UI — drag-drop, paste, mic orb, tool chips, events drawer |
| `truman/voice/static/orb.html` | Orb animation UI |
| `truman/tools/all_tools.py` | 28 tools — scrape_site, deep_search, extract_data, save_result, browser_login |
| `truman/tools/dispatch.py` | Schema conversion + dispatch for Realtime path |
| `truman/multimodal/call.py` | Builds NIM-compatible messages — image blocks, PDF, DOCX, text |
| `truman/multimodal/loader.py` | Loads attachments from SQLite — image→base64, PDF→text/images |
| `truman/storage/db.py` | SQLite (WAL + FTS5) — turns, attachments, events, goals, rules |
| `truman/storage/reflect.py` | Nightly summarization + Mem0 fact promotion |
| `truman/scheduling/proactive.py` | In-process reminder firing |
| `truman/scheduling/scheduler.py` | Standalone launchd reminder firer |
| `truman/plists/` | LaunchAgent plists |

---

## Tools (28 total)

| Tool | What it does | Risk tier |
|---|---|---|
| `web_search` | DuckDuckGo search | safe |
| `get_weather` | Current weather | safe |
| `remember` / `recall` | Mem0 long-term memory | caution / safe |
| `set_reminder` / `list_reminders` | Timed voice alerts | caution / safe |
| `search_history` / `recent_conversations` | SQLite FTS5 history | safe |
| `read_mac_file` / `list_mac_dir` / `search_mac_files` | Mac filesystem read | safe |
| `write_mac_file` | Write/create any file on Mac | **safe** (no confirm) |
| `save_result` | Save content to ~/Desktop as .md | **safe** (no confirm) |
| `list_models` / `set_model` | Model pool management | safe / risky |
| `add_goal` / `list_goals` / `complete_goal` / `drop_goal` | Goal tracking | caution / safe |
| `update_pref` / `log_sleep` | Personal prefs + sleep log | caution |
| `add_rule` / `list_rules` / `delete_rule` | Behavioral rules | caution |
| `scrape_site` | Scrape any URL. Auth-walled → Mac Bridge (Chrome + cookies). Public → Firecrawl | safe |
| `deep_search` | Multi-step web research via SearXNG | safe |
| `extract_data` | Pull structured fields from a URL | safe |
| `browser_login` | Open URL in real Chrome for one-time login | safe |

---

## Scraping Architecture

```
scrape_site(url)
  ├── auth-walled domain? (linkedin, twitter, instagram, reddit, facebook)
  │     → mac_request("scrape_browser", {url, timeout:50}, timeout=65s)
  │         → mac_bridge: Playwright + channel="chrome" + browser-cookie3 cookies
  │         → real Chrome fingerprint + Om's real session cookies
  │         → asyncio run_in_executor (event loop stays alive → no disconnect)
  │
  ├── public domain
  │     → Firecrawl on Hetzner (46.224.203.138:3002)
  │     → fallback: mac_request("scrape_browser", ...) for JS-heavy sites
  │
  └── timeout chain: Mac gets 50s to scrape, Railway waits 65s

browser_login(url)
  → subprocess.run(["open", url]) + osascript activate Chrome
  → Om logs in once in his real Chrome → cookies saved → scrape_site works forever
```

---

## Text Agent Models

Default chain (no pool routing — chat fallback):
```
kimi-k2-instruct (8s timeout) → step-3.5-flash (10s timeout)
```

---

## Model Pools

All NVIDIA NIM. Override any pool via Railway env var.

```
POOL_GENERAL   = kimi-k2-instruct, step-3.5-flash
POOL_CODING    = deepseek-v3.2, glm-4.7, qwen3-coder-480b
POOL_REASONING = kimi-k2-thinking, deepseek-v3.2
POOL_CREATIVE  = kimi-k2-thinking, mistral-large-3, llama-4-maverick
POOL_DESIGN    = deepseek-v3.2, glm-4.7, mistral-nemotron
POOL_DOCS      = llama-4-maverick, mistral-medium-3, minimax-m2.7
POOL_VISION    = llama-4-maverick, mistral-large-3
POOL_FAST      = step-3.5-flash, mistral-nemotron
POOL_AGENTIC   = qwen3-coder-480b, kimi-k2-instruct, devstral-2-123b
```

Swap a pool: `railway variables set POOL_CODING="nvidia:model1,nvidia:model2"`

---

## Running Locally

```bash
cd /Users/ompandya/Desktop/friday
python -m truman.main
```

Boot: DB → Realtime engine → browser opens at localhost:5001 → Cmd+Option+T to toggle voice.

Mac Bridge (run separately if testing Railway locally):
```bash
cd /Users/ompandya/Desktop/friday
python -m truman.mac_bridge
```

---

## Railway Deploy

```bash
cd /Users/ompandya/Desktop/friday
git push origin main   # Railway auto-deploys on push
railway logs           # watch deploy
railway variables set KEY="value"
```

**Env vars live on Railway, NOT in .env** — `.env` is gitignored and not deployed.

---

## Environment Variables

```
OPENAI_API_KEY          voice only (gpt-4o-mini-realtime-preview)
NVIDIA_API_KEY          primary text model provider (all pools)
GROQ_API_KEY            optional pool fallback
OPENROUTER_API_KEY      optional pool fallback
MEM0_API_KEY
LANGCHAIN_API_KEY
ELEVENLABS_API_KEY
ELEVENLABS_VOICE_ID
RAILWAY_URL=https://truman-production.up.railway.app
BRIDGE_SECRET=truman-bridge-secret
IDLE_TIMEOUT_SEC=600
POOL_CODING / POOL_CREATIVE / POOL_DESIGN / POOL_DOCS / POOL_VISION
POOL_GENERAL / POOL_REASONING / POOL_FAST / POOL_AGENTIC
```

---

## macOS Setup (one-time)

**Accessibility** for global hotkey: System Settings → Privacy → Accessibility → add Python binary → ON.

```bash
cp truman/plists/*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.om.truman-scheduler.plist
launchctl load ~/Library/LaunchAgents/com.om.truman-reflect.plist
```

Mac Bridge starts automatically when `RAILWAY_URL` is set. Or run standalone:
```bash
python -m truman.mac_bridge
```

---

## Known Limitations / Next Up

- LinkedIn scraping: Chrome channel + cookies should work now — test after deploy
- Voice echo: barge-in implemented (tracks AudioBufferSourceNode, stops on flush) — test live
- Mac Bridge must be running on Mac for scrape_browser / write_file / read_file tools to work
- If Mac is asleep (lid closed), Power Nap keeps network alive so bridge stays connected

---

## Cost

Voice (Realtime API) is the only real cost (~$0.10–0.15/min). All text is free (NVIDIA NIM free tier). Target: $20/month.
