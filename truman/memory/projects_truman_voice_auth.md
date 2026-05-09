---
name: Truman Voice Auth Upgrade Plan
description: Resemblyzer can't distinguish Om from similar voices — plan to upgrade to pyannote.audio
type: project
---

Switch Truman's speaker verification from Resemblyzer to `pyannote.audio`.

**Why:** Resemblyzer scores both Om and his friend at 50-70% — no threshold can separate them reliably. pyannote.audio is purpose-built for speaker diarization/identification and handles similar voices much better.

**How to apply:** When Om asks to fix voice auth properly, replace `auth.py` encoder with pyannote speaker embedding model (`pyannote/speaker-diarization-3.1` or `pyannote/embedding`). Requires HuggingFace token (already in .env as HUGGINGFACE_TOKEN) and accepting pyannote model license on HF.

**Current workaround:** Passphrase-only auth — voice check removed, Truman asks security question every wake.
