---
status: PENDING
brief_id: AI_HOTEL_VOICE_FORM_1
to: b1
from: lead
dispatched_by: lead
dispatched_at: 2026-06-19
task_class: feature
harness_v2: applies
gate_plan: G1 self-test (pytest AC-set) → G2 /security-review → G3 codex (bus codex) → AH1 merge → POST_DEPLOY_AC_VERDICT v1
supersedes: HEALTH_ENDPOINT_COLUMN_FIX_1 — VERIFIED MOOT (no `received_at` ref remains in outputs/dashboard.py). Dropped per bus #3338.
amends: AI_HOTEL_VOICE_FORM_SUPPLIER_1 (#3350) — Director GO'd a `site_visit` form via codex-arch #3351; now TWO forms on one shared substrate, site_visit FIRST.
---

# BRIEF — AI_HOTEL_VOICE_FORM_1 — voice dictation → structured form drafts (site_visit + supplier_card)

## Context
Director-ratified 2026-06-18/19. He wants AI-Hotel field-capture dictation to produce **typed records**,
not free-text notes. Design: codex-arch (AG-203) #3349 (substrate, ACCEPT-WITH-CHANGES) + #3351 (Director
GO on `site_visit`, prioritized for his **Santa Clara / NVIDIA site-scouting trip**). **Feature brief, not
a rewrite** — extends the existing capture path.

**RACI:** accountable=lead, responsible=b1, design=codex-arch (#3349/#3351), gate=codex (G3).
**Complexity:** Medium. Both forms share ONE endpoint + ONE table + ONE schema registry — the second form
is mostly a schema entry + auto-detect, so doing both is little more than doing one.

## PRIORITY (per codex-arch #3351 + lead)
1. **`site_visit.v1` ships FIRST** — Director's immediate trip-capture utility.
2. **`supplier_card.v1` is the fast-follow** schema on the same substrate (same PR if clean, else immediate next).
Build the shared substrate once; register both schemas; gate `supplier_card` behind `site_visit` only if time-boxed.

## Core architecture rule (non-negotiable — codex-arch)
**Structured extraction sits BESIDE raw capture, never replaces it.**
- Persist the raw capture (audio/transcript/note/photos) **before** extraction runs.
- A failed extraction must still leave the raw capture fully retrievable (fault-tolerant; loud log).
- A typed record exists **only after user review + explicit confirm**. Draft persistence OK; auto-confirm BANNED.
- **No invented facts** — addresses, ownership, zoning, price, parcel, demand stats, emails are NEVER guessed;
  absent → `null` and listed under the form's research/unknowns field.
- v1 = zero send/payment/external side-effects (Clerk policy: reads allow / writes gated / money+sends hard-deny).

## Current State (verified this session)
- Endpoint: `outputs/dashboard.py:9383` `ai_hotel_capture(images, audio, note)`. Transcribe leg L9451-9468.
- LLM helper (verified sig): `_llm_call(model, messages: list, max_tokens=2000, system=None,
  response_format=None, thinking_budget=None)` — `dashboard.py:42`. **No `response_schema` kwarg** →
  use `response_format="json"` + `thinking_budget=0`, then validate JSON yourself (Pydantic/jsonschema).
- Cost logging: `log_api_cost(...)` — `orchestrator/cost_monitor.py:219`.
- Existing tables: `ai_hotel_captures` (mig `20260615b_ai_hotel_captures.sql`) + `ai_hotel_capture_images`
  (mig `20260618_*`). Raw insert at `dashboard.py:9578/9591`. **Link new records by capture_id — never duplicate base64.**

## Engineering Craft Gates
- **Diagnose:** N/A — net-new feature.
- **Prototype:** N/A — design pre-decided (#3349/#3351); uncertainty is extraction *quality*, measured by kill-criteria.
- **TDD:** APPLIES. Public interface = `POST /api/ai-hotel/form-drafts`. Write ONE vertical behavior test
  first (messy-dictation → valid `site_visit` draft), then build. Mock the LLM at the `_llm_call` seam only.

## Shared substrate (build once)

### 1. Schema registry (git-versioned, NOT DB-authored)
- New module `orchestrator/ai_hotel_form_schemas.py`. Per-field: `key, type, required/critical, enum/options,
  normalizer, validator, risk_level, prompt_hint`. **The extraction prompt is GENERATED from the schema.**

### 2. Extraction endpoint
- `POST /api/ai-hotel/form-drafts`, `Depends(verify_api_key)`. **`grep -n "api/ai-hotel/form-drafts"
  outputs/dashboard.py`** first to confirm no shadow route. Reuse capture media limits + auth + audio map.
- Input: `images, audio, note, form_type (optional)`.
- Flow: resolve `form_type` (explicit, else **auto-detect**) → **raw capture insert (reuse existing INSERT)**
  → transcript (reuse Gemini leg) → schema-driven extraction → **deterministic validators (control plane)** → draft.
- Output: `capture_id, draft_id, form_type, schema_version, status="draft", values, field_meta,
  missing_critical, validation_errors, warnings, transcript_preview`.
- Per-field `field_meta`: `confidence, evidence_source ∈ {audio, photo, typed_note, inferred_low_confidence}, needs_review`.
- **Auto-detect:** if `form_type` absent, infer `site_visit` from words like site/building/location/parking/
  zoning/NVIDIA-proximity. Show "Detected: Site visit" before save. **User selection overrides auto-detect.**
- All DB/API calls in try/except with `conn.rollback()` in except.

### 3. Model substrate
- Gemini 2.5-flash `_llm_call(..., response_format="json", thinking_budget=0)` + `log_api_cost(...)`; validate
  JSON with Pydantic/jsonschema. **No Claude tool-use** (reserved for later invoice/legal).

### 4. Persistence — ONE generic child table (NOT per-form)
- New migration `migrations/20260619_ai_hotel_form_records.sql` (NEW file):
  `ai_hotel_form_records(id, capture_id FK→ai_hotel_captures(id), form_type, schema_version, status,
  extracted_json, corrected_json, field_meta_json, validation_errors_json, model, prompt_version,
  created_at, updated_at, reviewed_at)`. `status ∈ {draft, confirmed, discarded}`. Index `(form_type, status, created_at DESC)`.

### 5. Review-edit UI (capture page)
- Mode selector: **Free note / Site visit / Supplier card** (auto-detect allowed, shown before save).
- Mobile review sheet: editable fields, missing-critical highlighted, confidence chips, raw transcript/photos
  accordion. Bump `?v=N` cache-bust on touched static. Buttons: **Save [Site/Supplier] Card** / **Keep as
  field note only** / **Retry extraction**. Save disabled until critical fields reviewed or marked unknown. No sends/payments.

## FORM 1 (priority) — `site_visit.v1` fields
`site_label`(nullable) · `address_or_location_clue` · `geo_context`(city/neighborhood/proximity to NVIDIA/
airport/convention/campuses) · `current_property_type`(hotel/office/retail/industrial/vacant/unknown) ·
`site_condition` · `access_parking_visibility` · `surrounding_demand_drivers` · `ai_hotel_angle` ·
`hospitality_fit`(high/med/low + reason) · `conversion_complexity`(low/med/high/unknown + reason) ·
`red_flags_physical` · `red_flags_deal` · `unknowns_to_research`(owner/zoning/parcel/broker/price/comp/permits)
· `next_action`(research_owner/research_zoning/broker_outreach/revisit/reject/compare) · `overall_score`(1-5,
model-suggested, **MUST be editable**) · `evidence_refs`(photo ordinal/audio-phrase per field where possible).
Review-sheet groups: Location · Fit · Risks · Research · Score.

## FORM 2 (fast-follow) — `supplier_card.v1` fields
`company_name`(required) · `contact_name` · `title` · `email` · `phone` · `website` · `booth_or_source` ·
`offering_summary` · `ai_hotel_category`(enum) · `brisen_relevance` · `follow_up_action`(enum) · `notes`.

## Acceptance criteria (prove with pytest — NOT "by inspection", Lesson #8)
- AC1: messy dictation (no field order) → valid `site_visit` draft.
- AC2: unknown address/owner/zoning stay `null` AND appear in `unknowns_to_research` (no hallucination).
- AC3: extraction failure still saves the raw capture (force `_llm_call` error → raw row + photos retrievable).
- AC4: no `confirmed` record before a review/confirm action.
- AC5: auto-detect picks `site_visit` on a natural Santa Clara / NVIDIA / parking / building note.
- AC6: explicit user `form_type` overrides auto-detect.
- AC7: unknown `form_type` → 400, no rows.
- AC8: `supplier_card` happy path — dictation → correct `company_name` + spoken fields; validators reject bad email/phone.

## Files Modified
- `outputs/dashboard.py` — `/api/ai-hotel/form-drafts` endpoint + capture-page UI.
- `orchestrator/ai_hotel_form_schemas.py` — NEW (both schemas).
- `migrations/20260619_ai_hotel_form_records.sql` — NEW.
- `tests/test_ai_hotel_form_drafts.py` — NEW (AC1–AC8).

## Do NOT Touch
- `ai_hotel_capture` existing endpoint semantics (raw path stays the safety net).
- Applied migrations `20260615b_*` / `20260618_*`. Anything orthogonal to these two forms (no invoice/letter).

## Done rubric
DONE = AC1–AC8 pytest green (paste tail) + `py_compile` clean + capture flow exercised live + codex G3 PASS
+ `POST_DEPLOY_AC_VERDICT v1` posted. Ship report answers EACH AC. Compile-clean ≠ done.

## Kill criteria (stop + surface to lead)
- Any hallucinated address/owner/zoning/price presented as fact → immediate stop.
- Any raw capture lost on extraction failure → stop. Any confirmed card without review → stop.
- Critical-field correction rate >40% across 10 real captures → redesign prompt/UI.
- p95 extraction latency >15s, or any money/send/legal path appears in v1 → reject scope.

## Gate plan
G1 pytest green → G2 `/security-review` on diff → G3 codex (bus `lead`→`codex`, topic `gate-request/prNNN`)
→ lead merge → b1 emits `POST_DEPLOY_AC_VERDICT v1`. Branch `b1/ai-hotel-voice-form-1` → PR to baker-master
`main`. Bus-post on ship + gate-request + post-deploy. Reply target: lead.

## Verification SQL (post-deploy, after one real capture)
```sql
SELECT id, capture_id, form_type, schema_version, status, created_at
FROM ai_hotel_form_records ORDER BY created_at DESC LIMIT 5;
```
