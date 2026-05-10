conda create -n truman python=3.11
conda activate truman


# TRUMAN - Personal AI Operating System
### Built by Om (Bhavya Pandya) | Powered by OpenAI Realtime API + Mem0 + SQLite + LangChain

---

## WHO IS TRUMAN

Truman is not a chatbot. Not an assistant. Not a tool.

He is Om's personal AI operating system — a brain extension that thinks, executes, monitors, builds, and operates alongside Om 24/7. He knows everything about Om's life, projects, clients, and goals. He never needs context re-explained. He just works.

Inspired by Friday from Iron Man — built from scratch, for Om specifically.

---

## TRUMAN'S VOICE & IDENTITY

- **OpenAI Realtime API** — sub-second voice-to-voice, native barge-in, browser-based audio with WebRTC AEC
- **Wake word** — say "Truman" and he activates (roadmap, Level 9)
- **Double clap** — alternative activation via YAMNet sound classification
- **Cough detection** — Truman reacts naturally without being prompted
- **Speaks any language** — Whisper-1 detects input language (via Realtime API's transcription), responds in kind via OpenAI voice `ash`
- **ElevenLabs** — used for boot lines and ambient-event responses (`voice.speak`)
- **Always calls Om by name** — never "user", never "Bhavya"
- **Morning briefing** — boots up and tells Om what happened + what's today

---

## CORE CAPABILITIES

### 1. Knowledge & Information
- Real-time weather on demand
- Trending news and world events
- Web search for anything, anytime
- Deep research on any topic

### 2. Forex Intelligence
- Full market scan across all 11 pairs (XAU, GBP, EUR, JPY crosses, etc.)
- Multi-timeframe summary — H1, M15, M5, M1
- Morning market email — Truman sends Om a full market brief every day
- Logic gap finder — reads Om's forex scanner code, finds missing logic, texts Om

### 3. Communication
- Send emails via Gmail API
- WhatsApp messaging via pywhatkit
- Send alerts to Om's phone when something needs attention

### 4. Document & Media
- PDF or book → convert to audio format automatically
- Move converted audio to iPhone and Mac via iCloud
- Set a reminder to play the audio at a specific time

### 5. Development & Code
- GitNexus integration — indexes codebase into knowledge graph, knows blast radius before touching any file
- Write code files from scratch
- Read and analyze existing code
- Execute Python in real time
- Push projects to GitHub — create repo, commit, push, done
- Build websites with Google Stitch premium 3D design + deploy to Netlify/Vercel

### 6. Browser Automation
- Open any website
- Login with Om's Google credentials automatically
- See multiple Gmail accounts — asks Om which one to use, then clicks it
- Navigate, fill forms, interact with pages like a human

### 7. Productivity
- Google Calendar — knows Om's full schedule
- Create Google Sheets from web search results
- Reminders at specific times — survive laptop sleep, process death, reboots
- Organize and manage files across devices

---

## VISUAL INTERFACE

### Orb UI
Truman's idle state — a glowing particle orb on screen (HTML canvas, served from Flask on :5001). Reacts to his voice, pulses when thinking, goes calm when idle. Not a terminal. A living presence. Also the audio I/O layer — browser captures mic and plays speaker through WebRTC, which is how AEC works without a pile of native deps.

### Face Mesh + Hand Gestures (MediaPipe)
- Camera tracks Om's face in real time — green wireframe mesh overlay
- Hand gesture control — wave to activate, specific gestures for specific commands
- Particles react to hand movement in real time

### Lockdown Visual
Unauthorized voice → 6-second fullscreen animation (aggressive nodes, matrix rain, flashing warning) → Mac screen locks via `pmset displaysleepnow`

---

## SECURITY & AWARENESS

### Voice Authentication
- Truman learns Om's voice print via Resemblyzer *(current; unreliable on similar voices — upgrading to pyannote.audio, see roadmap)*
- Every speaker is verified against Om's stored embedding
- Unknown voice → challenge protocol → birthdate verification → lockdown if wrong
- **Current workaround:** passphrase-only auth — voice check temporarily relaxed, security question asked at wake

### Ambient Awareness
Truman listens to the environment constantly:
- **Cough** → checks in naturally via agent (not hardcoded)
- **Double clap** → activates and asks what Om needs
- **Speaking flag** → ambient detection mutes while Truman is talking

---

## MEMORY ARCHITECTURE

**Layer 1 — System Prompt:** Truman's core identity, Om's profile, working style. Always loaded. Never changes.

**Layer 2 — Mem0 (facts):** Dynamic self-updating memory. Truman reads AND writes via `remember` / `recall` tools. Identity, preferences, project statuses, durable facts about Om. Multi-query injection on session start — 4 angles pulled, deduped, added to system prompt. Survives across ALL sessions.

**Layer 3 — SQLite (episodic + tasks):** Local file at `truman/truman.db`. WAL mode, FTS5 search over content. Tables:
- `sessions` — one row per Cmd+Shift+T session
- `turns` — every user + assistant utterance verbatim, full-text searchable
- `session_summaries` — populated by nightly reflection (roadmap)
- `reminders` — survives process death + laptop sleep, fired by a standalone scheduler
- `tool_calls` — every tool Truman has ever run, with args and results

**Layer 4 — Tools:** If Truman doesn't know something — he uses tools to find out, then writes it to Mem0 so he never has to look it up again.

---

## ARCHITECTURE

### The Voice Brain
```
Browser tab (orb UI on :5001)
  ↓  getUserMedia({echoCancellation: true})    ← browser WebRTC AEC
  ↓  48kHz → 24kHz Int16 PCM
  ↓  WebSocket binary frames
Flask + flask-sock (orb.py)
  ↓  mic_in  queue
  ↓  audio_out queue
realtime.py
  ↓  WebSocket → OpenAI Realtime API (gpt-4o-mini-realtime-preview)
  ↓  response.audio.delta → audio_out → browser plays (24kHz Int16)
  ↓  barge-in: drain queue + flush signal → browser stops in-flight playback
```

### Master Orchestrator
Truman — receives every command, decides which sub-agent handles it, coordinates execution, responds to Om.

### Sub-Agents *(roadmap — levels 7–10)*

| Agent | Responsibility |
|---|---|
| **Research Agent** | Weather, news, trending, web search, deep research |
| **Forex Agent** | Market scan, summary, email brief, logic gap analysis |
| **Comms Agent** | Gmail, WhatsApp, alerts |
| **Dev Agent** | Code writing, GitNexus, GitHub, Netlify/Vercel deploy |
| **Browser Agent** | Playwright automation, login, navigation, Google accounts |
| **Media Agent** | PDF → audio, iCloud transfer, reminders |
| **Productivity Agent** | Google Calendar, Google Sheets, scheduling |

### Tools (live today — 15 tools)
```
web_search          get_weather         remember            recall
set_reminder        list_reminders      search_history      recent_conversations
read_mac_file       list_mac_dir        search_mac_files    write_mac_file
list_models         set_model           pipeline_mode
```

### Tools (roadmap)
```
send_email          send_whatsapp       scan_forex
analyze_forex_code  execute_code        create_github_repo
push_to_github      deploy_to_vercel    create_google_sheet
browser_navigate    browser_login       browser_click
pdf_to_audio        move_to_icloud      send_alert
gitnexus_analyze    get_calendar
```

---

## TECH STACK

| Layer | Technology |
|---|---|
| **Voice Loop** | **OpenAI Realtime API (`gpt-4o-mini-realtime-preview`, voice `ash`)** |
| **Audio Capture / Playback** | **Browser WebRTC (`getUserMedia` with `echoCancellation`), AudioContext** |
| **Audio Bridge** | **Flask + flask-sock WebSocket on :5001** |
| **OpenAI Client** | **`websockets` (async)** |
| **Agent Framework (non-realtime paths)** | LangChain (keyword detection + direct tool execution — no bind_tools) |
| **Brain (text)** | NVIDIA NIM `deepseek-ai/deepseek-v3.2` primary → Groq `llama-3.3-70b-versatile` fallback |
| **Tracing** | LangSmith |
| **Facts Memory** | Mem0 (hosted platform) |
| **Episodic / Tasks Persistence** | **SQLite (WAL mode, FTS5)** |
| **Reminder Scheduler** | **launchd (`com.om.truman-scheduler.plist`) + standalone `scheduler.py`** |
| **Backend (future APIs)** | FastAPI |
| **Speech Transcription** | Whisper-1 (via Realtime API's `input_audio_transcription`) |
| **Ambient TTS** | ElevenLabs (boot line, cough/clap responses) |
| **Fallback TTS** | `say` (macOS built-in, offline, used by scheduler) |
| **Wake Word** *(roadmap)* | Custom trained (M.I.L.E.S approach) |
| **Sound Classification** | YAMNet — Google, 521 sound classes |
| **Voice Authentication** | Resemblyzer → upgrade path: pyannote.audio |
| **Face + Hand Tracking** *(roadmap)* | MediaPipe |
| **Hotkey** | pynput (Cmd+Shift+T toggles session) |
| **Code Intelligence** *(roadmap)* | GitNexus + Graphify (71.5x token reduction) |
| **Browser Automation** *(roadmap)* | Playwright |
| **SMS/WhatsApp** *(roadmap)* | pywhatkit |
| **Email** *(roadmap)* | Gmail API |
| **Forex Data** *(roadmap)* | OANDA API |
| **Version Control** *(roadmap)* | GitHub API |
| **Calendar** *(roadmap)* | Google Calendar API |
| **Spreadsheets** *(roadmap)* | Google Sheets API |
| **PDF Processing** *(roadmap)* | PyMuPDF |
| **File Transfer** *(roadmap)* | iCloud API |
| **Website Design** *(roadmap)* | Google Stitch |
| **Always-On Mac Service** | LaunchAgent (reminder scheduler live; full-process launch agent roadmap) |

---

## BUILD LEVELS

### ✅ Level 1 — Truman Comes Alive
Core voice loop. Originally: Whisper STT → LangChain + LangGraph agent → Kokoro/ElevenLabs TTS with GPT-4o-mini brain, Mem0 memory, LangSmith tracing, session conversation history, web search, weather. Truman was breathing.

*Replaced in Level 3 by the OpenAI Realtime API migration — same capabilities, sub-second latency, fewer moving parts.*

### ✅ Level 2 — Security & Awareness
Resemblyzer voice enrollment + verification. YAMNet sound classification for real cough and clap detection. Unknown voice → challenge → birthdate → lockdown. Pygame fullscreen lockdown visual (nodes, matrix rain, warning) → Mac screen lock. Cough/clap responses routed through agent for natural dynamic replies.

**Caveat:** Resemblyzer confuses Om with similar voices (50–70% overlap with friend's voice, no usable threshold). Currently in passphrase-only mode. Upgrade to `pyannote.audio` queued in Level 8.

### ✅ Level 3 — Realtime Voice + Browser Audio (shipped 2026-04)
Migrated the whole voice loop from Whisper→LangChain→Kokoro to **OpenAI Realtime API** (`gpt-4o-mini-realtime-preview`, voice `ash`). Sub-second response time, native VAD turn detection, model function calling built in.

Audio moved out of native `sounddevice` and into the **browser** (`orb.py` WebSocket on :5001). `getUserMedia({echoCancellation: noiseSuppression: autoGainControl: true})` gives production-grade AEC for free. The echo loop and broken barge-in (both fatal in the native pipeline) are gone — Truman can be interrupted mid-sentence and doesn't hear himself.

Dropped `sounddevice`, `pyaec`, `speexdsp`, native AEC attempts. Added `flask-sock`, `websockets`. VAD tuned to threshold 0.5 / silence 700ms.

### ✅ Level 4 — Persistence Layer (shipped 2026-04)
Added SQLite (`db.py`) for everything that used to live in Python memory. Every turn, every tool call, every session start/end now recorded to `truman/truman.db` (WAL mode, FTS5 search over content).

**Reminders moved from in-memory list to SQLite.** They now survive:
- Python process death ✅
- Laptop sleep → wake ✅
- Reboots ✅
- Mac fully off (fires on next boot) ✅

Built a standalone `scheduler.py` + launchd plist (`com.om.truman-scheduler.plist`) that fires every 60 seconds. Uses atomic `claim_reminder` so it never double-fires with Truman's in-process loop. Fallback voice via macOS `say` + notification banner when the main Truman process isn't running.

Fixed the `"2 minutes"` parser bug in `set_reminder` — now accepts both absolute (`3pm`, `9:30am`, `15:30`) and relative (`2 minutes`, `in 5 min`, `30s`, `1 hour`) time formats.

### 🚧 Level 5 — Memory Maturity
Make Truman remember yesterday, not just the last session.

- **Session-start context injection** — on `session.created`, pull `db.recent_turns(20)` + `db.last_session_summary()` and inject alongside the Mem0 facts. Fixes the "I don't recall that, we talked 2 minutes ago" bug from mid-session drops.
- **Nightly reflection loop** — launchd cron at 2am. Pulls yesterday's turns, summarizes to `session_summaries`, extracts durable facts and `memory.add()` them to Mem0. Flags contradictions for merge. Truman gets measurably smarter every day.
- **Whisper hallucination filter** — drop known phantom phrases (`"thank you for watching"`, `"おつかれさまでした"`) from user input so they don't poison the transcript log.
- **Transcript echo filter** — drop user transcripts that match recent assistant transcripts (isair/jarvis trick) as a backup safety net.

### 🚧 Level 6 — Proactive 2.0
Upgrade `proactive.py` from "fire once at 5am" to context-aware triggers.

- **Time-aware greeting** — replace the "Hey, what's up?" auto-greet with morning/evening/late-night variants, or remove entirely.
- **Brief vs. detailed response rules** — system prompt enforces: direct questions get direct answers, no deflection to "anything on your mind?" (fixing the pattern we caught Truman doing).
- **Accountability tone** — when accused of a mistake, acknowledge it and ask what happened. No corporate-speak filler like "I'm here to assist and support you."
- **Capability honesty rule** — hard system-prompt rule: never claim a capability you haven't verified. (Fixes the "yes I'll alert you even if your laptop is closed" lie.)
- **Watch loop** — checks calendar, email, file changes, time-of-day. Rules-driven: *"if 9am and no morning brief today, trigger"*, *"if Om's been quiet 3hrs, stay quiet"*.
- **Showcase/guest mode** — system prompt addition for demos. Truman introduces itself, asks visitor's name, references Om's projects from Mem0.

### 🚧 Level 7 — Agentic
Truman decides on his own to take multi-step actions.

- **Permission model** — clear rules for what Truman can do without asking (read file) vs. needs confirmation (send email, push code) vs. forbidden (touch .env, delete).
- **Reversibility + dry-run** — destructive actions get a "here's what I'll do, confirm?" gate.
- **Plan-execute-verify loop** — Truman breaks a request into steps, runs each, checks the result, adapts.
- Builds on Levels 5+6. Don't start here — the earlier tiers are the foundation.

### 🚧 Level 8 — Always-On Robustness
Fix the remaining holes in the "always there for Om" promise.

- **`pmset schedule wake`** — when a reminder is added, also schedule the Mac to wake at that time so reminders fire on time even from sleep (not just when the Mac happens to wake up).
- **Voice auth upgrade** — swap Resemblyzer for `pyannote.audio` (`pyannote/embedding`). HF token already in `.env`. Handles similar voices.
- **Cloud fallback** — a tiny Railway worker that fires push notifications when the Mac is fully off. Bridges the "laptop shut down" gap. Optional.
- **PWA** — add `manifest.json` + service worker so the orb installs as a standalone app. No browser tab. Eventually Electron or menu-bar.

### Level 9 — Orb UI 2.0 + Wake Word + MediaPipe
- Glowing particle orb already live (Level 3). Next: MediaPipe overlays, gesture-driven controls.
- Wake word detection — say "Truman" to activate (reference: M.I.L.E.S repo)
- MediaPipe face mesh overlay on camera feed
- Hand gesture control — wave to activate, gestures map to commands
- Particles react to hand movement in real time

### Level 10 — Morning Briefing + Calendar
- Google Calendar API integration — Truman knows Om's full schedule
- Auto morning briefing on startup: what happened since yesterday (from SQLite summaries, Level 5), schedule for today, pending tasks, forex pre-market summary
- Briefing delivered via voice

### Level 11 — Communication Tools
- Gmail API — send and read emails
- WhatsApp via pywhatkit — send messages, emojis, anything Om dictates
- Alert system — important events notify Om immediately

### Level 12 — Dev Tools + GitNexus + Graphify
- GitNexus — `npx gitnexus analyze` before touching any codebase, knows blast radius before any edit
- Graphify — indexes all projects (code, docs, PDFs, images, videos) into knowledge graph, 71.5x token reduction
- Write files, read files, execute Python live
- GitHub API — create repo, commit, push
- Build websites with Google Stitch for premium 3D design
- Deploy to Netlify/Vercel via CLI

### Level 13 — Forex Brain
- OANDA API — full market scan across 11 pairs, all timeframes
- Morning market email brief generated automatically
- Logic gap finder — reads Om's forex scanner, finds missing logic, texts him
- Integrates with existing ICT engine

### Level 14 — Browser Automation
- Playwright — open any website, login, navigate
- Google account selector — sees multiple accounts, asks Om which one
- Fill forms, click buttons, interact like a human

### Level 15 — Media & Productivity
- PDF/book → audio conversion (PyMuPDF + OpenAI TTS)
- Move audio to iPhone and Mac via iCloud
- Set reminders to play at specific times (leverages Level 4 reminder scheduler)
- Create Google Sheets from web search results

### Level 16 — Always On (full)
- LaunchAgent for the main Truman process — boots on Mac startup
- Runs silently in background, always listening
- No manual start ever needed
- (Reminder scheduler LaunchAgent already live from Level 4.)

### Level 17 — Mission 1: Truman Builds Sprint 6
First real mission. Truman uses GitNexus to understand MAYA's codebase, then uses his dev tools to upgrade it from RAG chatbot to full LangChain multi-agent system with tools. LangSmith traces prove he built it.

### Level 18 — Mission 2: FEC SaaS v2
Rebuild FEC-WHIN NGO ops platform as multi-tenant SaaS for 30 branches. Supabase backend, branch-level auth, super admin view, all 6 modules, chatbot addon. Google Stitch for UI design. $99-200/month per branch.

---

## REFERENCE REPOS
- **M.I.L.E.S** — wake word training, multi-tasking architecture: github.com/small-cactus/M.I.L.E.S
- **GitNexus** — codebase knowledge graph: github.com/abhigyanpatwari/GitNexus
- **Graphify** — multimodal knowledge graph, 71.5x token reduction: github.com/safishamsi/graphify
- **Vocalis** — browser-audio voice agent (architectural precedent for the WebRTC AEC approach in Level 3)

---

## RELATED DOCS
- **[VOICE_PIPELINE.md](./VOICE_PIPELINE.md)** — step-by-step cookbook for dropping Truman's voice pipeline into a new project (5 files, ~5 min setup)
- **BUILD_LOG.md** — ongoing implementation notes

---

## THE META FLEX

Truman (a multi-agent AI OS) built Sprint 6 (a multi-agent AI system).

When the professor asks how Om built it:
*"I built an AI operating system. Then I told him to build Sprint 6. He did. And I reviewed every decision he made."*

LangSmith traces prove it. Truman's voice demonstrates it live.

---

## WHAT MAKES TRUMAN DIFFERENT

| Feature | Siri | Alexa | ChatGPT | **Truman** |
|---|---|---|---|---|
| Knows Om's full life & projects | ❌ | ❌ | ❌ | ✅ |
| Builds real production code | ❌ | ❌ | ❌ | ✅ |
| Always ambient aware | ❌ | Partial | ❌ | ✅ |
| Voice authentication & security | ❌ | ❌ | ❌ | ✅ |
| Orb UI + face mesh + hand gestures | ❌ | ❌ | ❌ | ✅ |
| Wake word + clap + cough detection | ❌ | Partial | ❌ | ✅ |
| Morning briefing with real data | ❌ | Partial | ❌ | ✅ |
| LangSmith full tracing | ❌ | ❌ | ❌ | ✅ |
| Multi-agent architecture | ❌ | ❌ | ❌ | ✅ |
| Browser automation | ❌ | ❌ | ❌ | ✅ |
| Builds your business systems | ❌ | ❌ | ❌ | ✅ |
| Lockdown + security visual | ❌ | ❌ | ❌ | ✅ |
| GitNexus code intelligence | ❌ | ❌ | ❌ | ✅ |
| **Sub-second voice + true barge-in** | ❌ | ❌ | Partial | ✅ |
| **Persistent task execution (survives laptop sleep)** | Partial | ❌ | ❌ | ✅ |
| **Episodic memory + nightly self-reflection** | ❌ | ❌ | ❌ | ✅ *(Level 5)* |

---

*Truman is Om's partner. Built from scratch. Built to last.*
