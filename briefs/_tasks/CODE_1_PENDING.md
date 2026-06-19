---
status: PENDING
brief_id: AI_HOTEL_VOICE_FORM_SUPPLIER_1
to: b1
from: lead
dispatched_by: lead
dispatched_at: 2026-06-18
task_class: feature
harness_v2: applies
gate_plan: G1 self-test (pytest AC1-AC6) → G2 /security-review → G3 codex (bus codex) → AH1 merge → POST_DEPLOY_AC_VERDICT v1
supersedes: HEALTH_ENDPOINT_COLUMN_FIX_1 — VERIFIED MOOT (no `received_at` ref remains in outputs/dashboard.py; fix already landed). Dropped per bus #3338.
---

# BRIEF — AI_HOTEL_VOICE_FORM_SUPPLIER_1 — voice dictation → structured supplier-card draft

## Context
Director-ratified 2026-06-18. He wants the AI-Hotel field-capture dictation to produce a **typed
supplier record**, not just a free-text note. Design authority: codex-arch (AG-203) bus #3349
(ACCEPT-WITH-CHANGES) + lead. **Feature brief, not a rewrite** — extends the existing capture path.

**RACI:** accountable=lead, responsible=b1, design-consulted=codex-arch (#3349), gate=codex (G3).
**Estimated complexity:** Medium. **Prerequisites:** none (capture endpoint + tables already live).

## Problem
`POST /api/ai-hotel/capture` (outputs/dashboard.py L9383) turns dictated audio into a **verbatim
free-text note** (Gemini 2.5-flash via `_llm_call`, `thinking_budget=0`), then classifies it into a
dashboard section. There is no path from speech → a structured, reusable record.

## Current State (verified this session)
- Endpoint: `outputs/dashboard.py:9383` `ai_hotel_capture(images, audio, note)`.
- LLM helper (verified sig): `_llm_call(model, messages: list, max_tokens=2000, system=None,
  response_format=None, thinking_budget=None)` — `dashboard.py:42`. **No `response_schema` kwarg** →
  use `response_format="json"` + `thinking_budget=0`, then validate the JSON yourself (Pydantic/jsonschema).
- Cost logging: `log_api_cost(...)` — `orchestrator/cost_monitor.py:219` (call after each `_llm_call`).
- Existing tables: `ai_hotel_captures` (migration `20260615b_ai_hotel_captures.sql`) +
  `ai_hotel_capture_images` (migration `20260618_ai_hotel_capture_images.sql`). Raw insert at
  `dashboard.py:9578` / `9591`. **Do NOT duplicate base64 into the new table — link by capture_id.**

## Core architecture rule (non-negotiable — codex-arch)
**Structured extraction sits BESIDE raw capture, never replaces it.**
- Persist the raw capture (audio/transcript/note/photos) **before** extraction runs.
- A failed extraction must still leave the raw capture fully retrievable (fault-tolerant; loud log).
- A typed record exists **only after user review + explicit confirm**. Draft persistence OK; auto-confirm BANNED.
- v1 = **zero** send/payment/external side-effects (Clerk policy: reads allow / writes gated / money+sends hard-deny).

## Engineering Craft Gates
- **Diagnose:** N/A — net-new feature, no existing defect to reproduce.
- **Prototype:** N/A — design pre-decided by codex-arch #3349; uncertainty is in extraction *quality*,
  measured by the kill-criteria below (real-capture accuracy), not a throwaway UI prototype.
- **TDD/verification:** APPLIES. Public interface = `POST /api/ai-hotel/form-drafts`. Write ONE vertical
  behavior test first (AC4 supplier-card happy path through the route), then build. Mock the LLM at the
  `_llm_call` seam only — not internal helpers. AC1/AC6 (data-loss-on-failure) are the load-bearing tests.

## Scope — supplier-card v1 ONLY (invoice + letter OUT — later phases, gated on v1 quality)

### 1. Form-schema registry (git-versioned, NOT DB-authored)
- New module `orchestrator/ai_hotel_form_schemas.py` (or `config/ai_hotel_forms.json` + loader).
- Per-field: `key, type, required, enum/options, normalizer, validator, risk_level, prompt_hint`.
- **The extraction prompt is GENERATED from the schema** — schema must not live only in prompt prose.
- Supplier-card v1 fields: `company_name` (required); `contact_name`; `title`; `email`; `phone`;
  `website`; `booth_or_source`; `offering_summary`; `ai_hotel_category` (enum); `brisen_relevance`;
  `follow_up_action` (enum); `notes`.

### 2. Extraction endpoint
- `POST /api/ai-hotel/form-drafts`, `dependencies=[Depends(verify_api_key)]`. **First `grep -n
  "api/ai-hotel/form-drafts" outputs/dashboard.py`** to confirm no shadowing route. Reuse capture's
  media limits + auth + audio-type map.
- Flow: validate `form_type` (unknown → HTTP 400, **no rows**) → **raw capture insert (reuse existing
  INSERT pattern)** → audio transcript (reuse existing Gemini transcribe leg) → schema-driven extraction
  → **deterministic validators (the control plane, NOT the model schema)** → return draft.
- Output JSON: `capture_id, draft_id, form_type, schema_version, status="draft", values, field_meta,
  missing_required, validation_errors, warnings, transcript_preview`.
- Per-field `field_meta`: `confidence, evidence_span/source, normalized_value, needs_review`.
- **Hard rule:** absent field = `null`. No enrichment, no guessing, no inferred legal/payment facts.
- All DB/API calls in try/except with `conn.rollback()` in except (Lesson — pool poisoning).

### 3. Model substrate
- Gemini 2.5-flash, `_llm_call(..., response_format="json", thinking_budget=0)` + `log_api_cost(...)`.
  Validate returned JSON with Pydantic/jsonschema. **Do NOT use Claude tool-use** (reserved for later invoice/legal).

### 4. Persistence — ONE child table (NOT per-form tables)
- New migration `migrations/20260619_ai_hotel_form_records.sql` (NEW file — never edit applied migrations):
  `ai_hotel_form_records(id, capture_id FK → ai_hotel_captures(id), form_type, schema_version, status,
  extracted_json, corrected_json, field_meta_json, validation_errors_json, model, prompt_version,
  created_at, updated_at, reviewed_at)`.
- `status ∈ {draft, confirmed, discarded}`. Index `(form_type, status, created_at DESC)`.

### 5. Review-edit UI (capture page)
- Segmented selector: **Free note / Supplier card** (Invoice + Letter hidden until v1 proves out).
- After extraction: mobile review sheet — editable fields, missing-required highlighted, confidence chips,
  raw transcript/photos accordion. Bump `?v=N` cache-bust on any touched static asset (iOS PWA).
- Buttons: **Save supplier card** / **Keep as field note only** / **Retry extraction**.
- **Save disabled** until required fields reviewed or explicitly marked unknown. No sends/payments.

## Acceptance criteria (prove with pytest — NOT "by inspection", Lesson #8)
- AC1: raw capture survives an extraction failure (force `_llm_call` error → raw row + photos retrievable).
- AC2: no `confirmed` record is written before a review/confirm action.
- AC3: unknown `form_type` → 400, no rows written.
- AC4: supplier-card happy path — dictation → correct `company_name` + obviously-spoken fields.
- AC5: validators reject malformed email/phone (surfaced in `validation_errors`, not silently dropped).
- AC6: empty/invalid model JSON → draft-error response **with no data loss** (raw capture intact).

## Files Modified
- `outputs/dashboard.py` — new `/api/ai-hotel/form-drafts` endpoint + UI on capture page.
- `orchestrator/ai_hotel_form_schemas.py` — NEW schema registry.
- `migrations/20260619_ai_hotel_form_records.sql` — NEW migration.
- `tests/test_ai_hotel_form_drafts.py` — NEW (AC1–AC6).

## Do NOT Touch
- `ai_hotel_capture` existing endpoint semantics (raw path stays the safety net).
- Applied migrations `20260615b_*` / `20260618_*` (never edit applied migrations).
- Anything orthogonal to supplier-card v1 (no invoice/letter, no Clerk write-path).

## Done rubric
DONE = AC1–AC6 pytest green (paste tail) + `py_compile` clean on touched .py + capture flow exercised
live + codex G3 PASS + `POST_DEPLOY_AC_VERDICT v1` posted after Render deploy. Ship report answers EACH
AC explicitly. Compile-clean ≠ done.

## Kill criteria (stop + surface to lead)
- Any raw capture lost on extraction failure → immediate stop.
- Any confirmed record without a review click → immediate stop.
- Supplier-card required-field accuracy <80% across 10 real captures → stop + redesign.
- Required-field correction rate >40% after 10 captures → prompt/UI not good enough.
- p95 extraction latency >15s, or any money/send/legal path appears in v1 → reject scope.

## Gate plan
G1 pytest green (AC1–AC6) → G2 `/security-review` on diff → G3 codex (bus `lead`→`codex`, topic
`gate-request/prNNN`) → lead merge → b1 emits `POST_DEPLOY_AC_VERDICT v1`. Branch
`b1/ai-hotel-voice-form-supplier-1` → PR to baker-master `main`. Bus-post on ship + gate-request +
post-deploy per agent-bus-posting-contract. Reply target: lead.

## Verification SQL (post-deploy, after one real capture)
```sql
SELECT id, capture_id, form_type, status, schema_version, created_at
FROM ai_hotel_form_records ORDER BY created_at DESC LIMIT 5;
```
