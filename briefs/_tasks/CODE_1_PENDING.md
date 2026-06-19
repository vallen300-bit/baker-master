---
status: PENDING
brief_id: AI_HOTEL_FIELD_NOTES_CARD_SHELF_1
to: b1
from: lead
dispatched_by: lead
dispatched_at: 2026-06-19
task_class: feature
harness_v2: applies
gate_plan: G1 self-test (pytest AC1-AC5) → G2 /security-review → G3 codex (bus codex) → AH1 merge → POST_DEPLOY_AC_VERDICT v1
follows: AI_HOTEL_VOICE_FORM_1 (PR #380, merged 58f7e90) — this is its Phase-2 viewer.
---

# BRIEF — AI_HOTEL_FIELD_NOTES_CARD_SHELF_1 — show saved structured cards inside Field Notes

## Context
Director-ratified 2026-06-19. He captured a live site card (#380 shipped) and asked "where can I look at
it?" — there is no viewer. **His instinct + codex-arch #3367: fold saved structured cards into the EXISTING
AI-Hotel dashboard "Field Notes" section** — NOT a separate "Saved Cards" screen (avoids a second iPhone nav
destination; structured cards are a richer field note, not a separate product). Design authority: codex-arch #3367.

**RACI:** accountable=lead, responsible=b1, design=codex-arch (#3367), gate=codex (G3). **Complexity:** Low-Medium.

## Problem
`ai_hotel_form_records` rows (confirmed/draft cards) are saved but invisible — no read surface joins them to
the Field Notes feed. Director can't browse his trip cards on his phone.

## Current State (verified this session)
- Feed endpoint: `GET /api/ai-hotel/captures` — `outputs/dashboard.py:9664` `ai_hotel_captures(limit=100)`.
  Returns `{"captures":[...]}` newest-first, fail-soft empty list, RealDictCursor, child images joined N+1-safe.
- New table (live, from #380): `ai_hotel_form_records(id, capture_id FK, form_type, schema_version, status,
  extracted_json, corrected_json, field_meta_json, ...)`. `status ∈ {draft, confirmed, discarded}`.
- Field Notes UI lives in the AI-Hotel dashboard capture surface (`outputs/static/ai-hotel-capture.html`
  and/or `ai-hotel.html`) — **grep both for the Field Notes render block before editing.**

## Engineering Craft Gates
- **Diagnose:** N/A — additive read feature.
- **Prototype:** N/A — UX pre-decided by Director + codex-arch #3367.
- **TDD:** APPLIES. Public interface = the extended `GET /api/ai-hotel/captures`. Write one vertical test first
  (capture WITH a confirmed form_record → combined item carries a `form_record` object), then build.

## Scope (codex-arch #3367 shape)

### 1. Read endpoint — extend `GET /api/ai-hotel/captures` (do NOT add a second list route)
- LEFT JOIN `ai_hotel_form_records` on `capture_id`, returning the **latest non-discarded** form record per
  capture as an optional `form_record` object (null when none). One combined item per capture, newest first.
- Keep the existing fail-soft contract (errors → `{"captures": []}`; a bad/missing form record must NEVER break
  the raw capture listing — AC5). Keep the N+1-safe batch pattern (one extra query keyed by `capture_id = ANY(%s)`).
- **Do NOT duplicate image base64 into form records** — images stay sourced from captures/child table.
- Bound every query with LIMIT; all DB in try/except + `conn.rollback()` in except.

### 2. Field Notes UI (in the existing section)
- Each item newest-first with a **type chip**: `Free note` / `Site` / `Supplier` (from `form_record.form_type`, else Free note).
- **Site-card compact row:** location clue, `hospitality_fit`, `overall_score`, `next_action`, missing-research count
  (count of populated items in `unknowns_to_research`).
- **Tap → detail:** structured fields + raw evidence (photos / audio / transcript / note).
- **Filters:** `All` / `Site Cards` / `Suppliers` / `Free Notes`.
- **Detail actions:** Edit draft/confirmed fields, Export/Copy, Mark researched, Dismiss.
- Bump `?v=N` cache-bust on any touched static asset (iOS PWA). XSS-safe rendering — use `textContent` /
  `createTextNode`, never `innerHTML` with card data.

## Acceptance criteria (prove with pytest — NOT "by inspection")
- AC1: capture WITHOUT a form record still appears, typed `Free note`.
- AC2: a confirmed site card appears in Field Notes with the `Site` chip.
- AC3: card detail includes both structured fields AND raw evidence (photo/audio/transcript/note).
- AC4: filters correctly hide/show Site / Supplier / Free notes.
- AC5: a missing/invalid/discarded form record never breaks the raw capture listing (feed still returns captures).

## Files Modified
- `outputs/dashboard.py` — extend `ai_hotel_captures` GET with the form_record join.
- `outputs/static/ai-hotel-capture.html` (and/or `ai-hotel.html`) — Field Notes chips/filters/detail.
- `tests/test_ai_hotel_field_notes.py` — NEW (AC1–AC5).

## Do NOT Touch
- The POST form-drafts / confirm / discard endpoints (#380 — stable).
- `ai_hotel_form_records` / `ai_hotel_captures` schema (no migration needed; this is read-only).
- Applied migrations. Anything orthogonal to the Field Notes shelf.

## Done rubric
DONE = AC1–AC5 pytest green (paste tail) + `py_compile` clean + Field Notes exercised live on the deployed
dashboard (show a real saved card in the list + detail) + codex G3 PASS + `POST_DEPLOY_AC_VERDICT v1`. Ship
report answers EACH AC. Compile-clean ≠ done.

## Kill criteria
- Field Notes feed breaks (returns error / empty) when a form record is malformed → stop (AC5 is the guard).
- Any image base64 duplicated into form records → stop. Any write/mutation added to this read path → reject scope.

## Gate plan
G1 pytest → G2 `/security-review` → G3 codex (bus `lead`→`codex`, topic `gate-request/prNNN`) → lead merge →
b1 `POST_DEPLOY_AC_VERDICT v1`. Branch `b1/ai-hotel-field-notes-card-shelf-1` → PR to baker-master `main`.
Bus-post on ship + gate-request + post-deploy. Reply target: lead.

## Verification (post-deploy)
`GET /api/ai-hotel/captures` returns combined items; the confirmed site card id=5 (capture_id=17, Palo Alto)
appears with a `form_record` object + `Site` chip.
