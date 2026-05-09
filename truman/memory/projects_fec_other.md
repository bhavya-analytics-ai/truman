---
name: Projects — FEC-WHIN, ML Projects, and Research
description: FEC NGO platform, bootcamp ML projects, and personal research systems
type: project
---

## FEC-WHIN NGO Operations Platform (Production — Real Client)
**Client:** FEC-WHIN — community nonprofit, main branch (free), 29 other branches (future SaaS)

**Built (Google Apps Script web apps connected to Google Sheets master tracker):**
- **Intake Form** — case management, phone-based lookup, New/Update/Close/Reopen logic
- **Feedback Tracker** — anonymous, auto-translates Spanish → English via Google Translate API, resets after 6s
- **Inventory** — baby supplies tracking, auto-deducts on pickup, low stock email to Gabby with Amazon reorder button
- **Partnership Tracker** — org inquiry pipeline, auto-status "New"
- **General Sign-In** — visitor log, redirects Organization/Business to Partnership form
- **RSVP/Events** — QR code based event system (in progress)

**Critical rule:** Data rows start at row 4. NEVER delete rows — mark Closed.

**Pending:** Dashboard tab, Volunteer Tracker, Partners List, QR code generator fix for RSVP

**Stack:** Google Apps Script, Google Sheets, Google Drive, Google Translate API

---

## FEC SaaS v2 (Big Goal — In Planning)
FEC-WHIN has 30 branches total. Main branch = free (origin client). Other 29 = paying subscribers.

**Plan:**
- Rebuild FEC as proper multi-tenant SaaS (Supabase backend, replace Google Sheets)
- Proper web app with branch-level auth + super admin view across all 30 locations
- All existing tabs rebuilt: Intake, Feedback, Inventory, Sign-In, Events/RSVP, Partnerships
- Dashboard with live activity across all tabs, low stock alerts to manager
- QR code generator for RSVP, chatbot addon (branch-aware)
- Pricing: ~$99-200/month per branch = $2,900-5,800 MRR from FEC network alone
- Eventually expand to other nonprofits and community orgs

**Why:** $99-200/month × 29 branches = meaningful MRR. Chatbot as upsell.

---

## CNN from Scratch + YOLO (Bootcamp Sprint 2)
- CNN from scratch on Corona toilet + seat cover datasets
- Aspect ratio preserving resize with padding (224×224)
- Tested with/without augmentation — documented why augmentation hurt (small dataset)
- Streamlit GUI + FastAPI inference API
- YOLO detection + segmentation with LabelMe annotations
- **Stack:** Python, PyTorch, torchvision, Streamlit, FastAPI

---

## Revenue Leakage Detection System (Bootcamp)
9-level production ML system: Data ingestion → Feature engineering → Isolation Forest → Rule engine → XGBoost (MAE 12.82) vs PyTorch MLP (MAE 14.8, XGBoost wins) → SHAP explainability → KMeans clustering (3 leakage patterns) → Streamlit review UI → Stress test (recall 1.0, ~6.5% FP rate)
- **Stack:** Python, scikit-learn, XGBoost, PyTorch, SHAP, Streamlit

---

## Reflective Decision Intelligence (RDI) (Personal Research)
System for evaluating decision quality and cognitive risk — not outcomes, the structure of thinking itself.
- L1-L4.3 built: decision clarity classification, cognitive failure detection, adaptive follow-ups, reflection effect measurement, intervention attribution, measurement-aware probing
- Next: L5 RL-lite intervention policy learning from (state, question, effect) tuples
- **Stack:** Python, CLI, scikit-learn

---

## Human-AI Co-Creative Design System (Research)
Generative architectural design system where human judgment is structured learnable data.
- Diffusion model generates massing variants; human accept/reject decisions logged as structured data
- System adapts prompts and inference based on decisions
- L4: Explainability linking human decisions to system changes
- Next: Preference memory layer across runs
