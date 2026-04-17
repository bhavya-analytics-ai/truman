# Graph Report - .  (2026-04-17)

## Corpus Check
- Corpus is ~17,419 words - fits in a single context window. You may not need a graph.

## Summary
- 266 nodes · 366 edges · 20 communities detected
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 13 edges (avg confidence: 0.79)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Roadmap & Voice Intro|Roadmap & Voice Intro]]
- [[_COMMUNITY_SQLite Helper API|SQLite Helper API]]
- [[_COMMUNITY_LangChain Agent & Mem0 Tools|LangChain Agent & Mem0 Tools]]
- [[_COMMUNITY_Realtime Event Loop|Realtime Event Loop]]
- [[_COMMUNITY_Orb Server & Browser Audio|Orb Server & Browser Audio]]
- [[_COMMUNITY_Gesture Control|Gesture Control]]
- [[_COMMUNITY_Realtime Tool Dispatcher|Realtime Tool Dispatcher]]
- [[_COMMUNITY_Proactive Initiation Loop|Proactive Initiation Loop]]
- [[_COMMUNITY_Architecture Rationale|Architecture Rationale]]
- [[_COMMUNITY_Ambient Sound Detection|Ambient Sound Detection]]
- [[_COMMUNITY_Launchd Reminder Scheduler|Launchd Reminder Scheduler]]
- [[_COMMUNITY_Nightly Reflection Pipeline|Nightly Reflection Pipeline]]
- [[_COMMUNITY_Wake Word Detection|Wake Word Detection]]
- [[_COMMUNITY_Voice Authentication|Voice Authentication]]
- [[_COMMUNITY_Main Orchestrator|Main Orchestrator]]
- [[_COMMUNITY_Global Hotkey Listener|Global Hotkey Listener]]
- [[_COMMUNITY_Standalone Utility Tools|Standalone Utility Tools]]
- [[_COMMUNITY_Config Module|Config Module]]
- [[_COMMUNITY_Memory Seeding|Memory Seeding]]
- [[_COMMUNITY_Security Q&A|Security Q&A]]

## God Nodes (most connected - your core abstractions)
1. `_conn()` - 17 edges
2. `_handle_events()` - 15 edges
3. `_now()` - 9 edges
4. `start_all()` - 9 edges
5. `reflect_on()` - 8 edges
6. `OpenAI Realtime session loop` - 8 edges
7. `realtime.py OpenAI Realtime client` - 8 edges
8. `classify()` - 7 edges
9. `claim_reminder()` - 7 edges
10. `_build_instructions()` - 7 edges

## Surprising Connections (you probably didn't know these)
- `speak()` --semantically_similar_to--> `realtime.py OpenAI Realtime client`  [INFERRED] [semantically similar]
  truman/voice.py → VOICE_PIPELINE.md
- `transcribe()` --semantically_similar_to--> `realtime.py OpenAI Realtime client`  [INFERRED] [semantically similar]
  truman/voice.py → VOICE_PIPELINE.md
- `Level 2 — Security & Awareness` --references--> `lockdown.trigger_lockdown()`  [EXTRACTED]
  BUILD_LOG.md → truman/lockdown.py
- `7 Sub-Agents roster` --references--> `web_search()`  [EXTRACTED]
  README.md → truman/tools.py
- `7 Sub-Agents roster` --references--> `get_weather()`  [EXTRACTED]
  README.md → truman/tools.py

## Hyperedges (group relationships)
- **Browser-Audio Realtime Pipeline** — orb_html_ui, orb_audio_ws, realtime_mic_in_queue, realtime_audio_out_queue, realtime_session, realtime_barge_in [EXTRACTED 0.95]
- **Dual-process Reminder Firing with Atomic Claim** — proactive_reminder_loop, scheduler_fire, db_claim_reminder, concept_double_fire_prevention [EXTRACTED 0.95]
- **Memory Maturity: SQLite Episodic + Mem0 + Nightly Reflection** — db_log_turn, db_session_summary, reflect_reflect_on, reflect_push_facts, agent_mem0_client, realtime_build_instructions [EXTRACTED 0.90]
- **Ambient sensing pipeline (mic→classify→trigger)** — ambient_monitor, sound_classifier_classify, ambient_trigger [EXTRACTED 0.90]
- **Realtime voice bridge queue architecture** — vp_orb_py, vp_realtime_py, vp_mic_in_queue, vp_audio_out_queue [EXTRACTED 0.95]
- **Gesture→lockdown→display sleep security flow** — gestures_closed_fist, lockdown_trigger, lockdown_run_screen, lockdown_pmset_displaysleep [EXTRACTED 0.90]

## Communities

### Community 0 - "Roadmap & Voice Intro"
Cohesion: 0.09
Nodes (26): Level 3 — Realtime Voice + Browser Audio, Level 4 — Persistence Layer, Level 5 — Memory Maturity, launchd reminder scheduler, SQLite episodic (WAL+FTS5), Vocalis reference repo, ack_beep(), _get_tts() (+18 more)

### Community 1 - "SQLite Helper API"
Cohesion: 0.15
Nodes (24): add_reminder(), _conn(), end_session(), get_due_reminders(), init(), last_session_summary(), list_reminders(), log_tool_call() (+16 more)

### Community 2 - "LangChain Agent & Mem0 Tools"
Cohesion: 0.11
Nodes (24): chat_history (in-session), list_reminders_tool(), Mem0 MemoryClient, mem_add(), mem_search(), List all upcoming reminders Om has set., Remove markdown formatting so TTS speaks clean natural text., Store something important about Om or his projects into long-term memory. (+16 more)

### Community 3 - "Realtime Event Loop"
Cohesion: 0.15
Nodes (22): _barge_in(), _clean(), _drain_audio_out(), Echo filter (recent_assistant), end_session(), Whisper hallucination filter, _handle_events(), _is_echo() (+14 more)

### Community 4 - "Orb Server & Browser Audio"
Cohesion: 0.13
Nodes (16): TRUMAN_SPEAKING flag, Browser-side echo cancellation, Global hotkey Cmd+Shift+T, Truman main() entrypoint, audio_ws(), Flask orb server (port 5001), get_state(), Orb HTML/JS (WebRTC mic + AEC) (+8 more)

### Community 5 - "Gesture Control"
Cohesion: 0.12
Nodes (14): Closed_Fist → lockdown, _gesture_loop(), Open_Palm → stop speaking, Truman Gesture Module — Level 3 MediaPipe GestureRecognizer (new Tasks API), on-, Stop gesture tracking and release camera., Start gesture tracking in background. Battery-safe — camera off when not called., start_gesture_mode(), stop_gesture_mode() (+6 more)

### Community 6 - "Realtime Tool Dispatcher"
Cohesion: 0.15
Nodes (10): set_reminder LangChain tool, add_reminder(), Persist a reminder. Returns the DB id., dispatch_tool (realtime tool router), macOS Reminders AppleScript, _parse_time(), realtime_tools.py — Tool definitions for OpenAI Realtime API function calling. I, Returns the absolute fire datetime, or None if unparseable.     Handles:       - (+2 more)

### Community 7 - "Proactive Initiation Loop"
Cohesion: 0.16
Nodes (15): Idle check-in, list_reminders(), Morning briefing (5-11am), proactive.py — Truman's proactive intelligence (Level 4) Three systems, all run, Returns list of {id, note, time} dicts (same shape as before — 'time' is datetim, Wire everything up. Call once from main.py after startup., Call this every time Om says something., Fires once per session if Truman starts between 5am and 11am.     Pulls time, da (+7 more)

### Community 8 - "Architecture Rationale"
Cohesion: 0.13
Nodes (15): Decision: LangChain+LangGraph framework, Decision: No fine-tuning, Decision: No RAG (Mem0 chosen), Level 1 — Truman Comes Alive, PWA / Electron / Menu bar roadmap, Gap: 31 isolated nodes, God Node: Truman (29 edges), Graph Report summary (102 nodes/139 edges) (+7 more)

### Community 9 - "Ambient Sound Detection"
Cohesion: 0.18
Nodes (10): _monitor(), start(), _trigger(), TRUMAN_SPEAKING flag (auth), Level 2 — Security & Awareness, CLAP_LABELS set, classify(), COUGH_LABELS set (+2 more)

### Community 10 - "Launchd Reminder Scheduler"
Cohesion: 0.23
Nodes (12): Atomic double-fire prevention pattern, claim_reminder(), Atomically mark a reminder fired. Returns True only if we claimed it.      Use t, SQLite persistence layer, In-process reminder loop, fire(), main(), _notify() (+4 more)

### Community 11 - "Nightly Reflection Pipeline"
Cohesion: 0.26
Nodes (11): session_summaries table, _call_llm(), _format_turns(), main(), Nightly reflection script, REFLECT_PROMPT (summary+facts JSON), _push_facts(), Return ids of ended sessions that have turns but no summary yet. (+3 more)

### Community 12 - "Wake Word Detection"
Cohesion: 0.22
Nodes (8): _listen_loop(), _load_model(), openWakeWord hey_jarvis Model, pause(), wakeword.py — Always-on wake word detection Uses openWakeWord with 'hey_jarvis', Release mic — call before record_audio() or speak()., Reclaim mic for wake word listening., resume()

### Community 13 - "Voice Authentication"
Cohesion: 0.24
Nodes (7): enroll_om(), Record a voice sample for enrollment., Record Om's voice across 3 rounds and average the embeddings for a solid voice p, Returns True if the audio matches Om's voice., record_sample(), verify_voice(), Voice Profile (om_voice.npy)

### Community 14 - "Main Orchestrator"
Cohesion: 0.29
Nodes (5): handle_ambient(), main.py — Truman core Realtime API voice loop + proactive system + orb UI + ambi, Called from ambient monitor thread when cough or clap is detected., set_state(), Orb visual state (idle/listening/thinking/speaking)

### Community 15 - "Global Hotkey Listener"
Cohesion: 0.4
Nodes (4): _on_press(), hotkey.py — Global hotkey listener for Truman Cmd+Shift+T → toggle realtime sess, Start the global hotkey listener.     toggle_fn is called each time Cmd+Shift+T, start()

### Community 16 - "Standalone Utility Tools"
Cohesion: 0.4
Nodes (5): 7 Sub-Agents roster, get_weather(), Get current weather for any location., Search the web for real-time information — news, prices, facts, anything current, web_search()

### Community 17 - "Config Module"
Cohesion: 1.0
Nodes (0): 

### Community 18 - "Memory Seeding"
Cohesion: 1.0
Nodes (0): 

### Community 19 - "Security Q&A"
Cohesion: 1.0
Nodes (1): SECURITY_QUESTION/ANSWERS

## Knowledge Gaps
- **90 isolated node(s):** `Record a voice sample for enrollment.`, `Record Om's voice across 3 rounds and average the embeddings for a solid voice p`, `Returns True if the audio matches Om's voice.`, `Returns 'cough', 'clap', or None.     raw_pcm: raw int16 PCM bytes`, `db.py — Truman's local persistence layer (SQLite, WAL mode).  Single file at `tr` (+85 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Config Module`** (1 nodes): `config.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Memory Seeding`** (1 nodes): `seed_memory.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Security Q&A`** (1 nodes): `SECURITY_QUESTION/ANSWERS`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `_handle_events()` connect `Realtime Event Loop` to `SQLite Helper API`, `LangChain Agent & Mem0 Tools`, `Realtime Tool Dispatcher`, `Proactive Initiation Loop`, `Main Orchestrator`?**
  _High betweenness centrality (0.153) - this node is a cross-community bridge._
- **Why does `Mem0 MemoryClient` connect `LangChain Agent & Mem0 Tools` to `Nightly Reflection Pipeline`, `Realtime Event Loop`?**
  _High betweenness centrality (0.087) - this node is a cross-community bridge._
- **Why does `set_state()` connect `Main Orchestrator` to `Realtime Event Loop`, `Orb Server & Browser Audio`?**
  _High betweenness centrality (0.060) - this node is a cross-community bridge._
- **What connects `Record a voice sample for enrollment.`, `Record Om's voice across 3 rounds and average the embeddings for a solid voice p`, `Returns True if the audio matches Om's voice.` to the rest of the system?**
  _90 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Roadmap & Voice Intro` be split into smaller, more focused modules?**
  _Cohesion score 0.09 - nodes in this community are weakly interconnected._
- **Should `LangChain Agent & Mem0 Tools` be split into smaller, more focused modules?**
  _Cohesion score 0.11 - nodes in this community are weakly interconnected._
- **Should `Orb Server & Browser Audio` be split into smaller, more focused modules?**
  _Cohesion score 0.13 - nodes in this community are weakly interconnected._