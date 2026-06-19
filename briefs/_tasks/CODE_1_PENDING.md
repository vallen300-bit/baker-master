---
status: PENDING
brief_id: AI_HOTEL_FIELD_NOTES_AND_AUDIO_1
to: b1
from: lead
dispatched_by: lead
dispatched_at: 2026-06-19
task_class: feature
harness_v2: applies
gate_plan: G1 self-test (pytest AC1-AC10) → G2 /security-review → G3 codex (bus codex) → AH1 merge → POST_DEPLOY_AC_VERDICT v1
follows: AI_HOTEL_VOICE_FORM_1 (PR #380, merged 58f7e90).
amends: AI_HOTEL_FIELD_NOTES_CARD_SHELF_1 (#3368) — Director smoke-test (#3369) found raw audio is NOT persisted; codex-arch says fold audio-evidence persistence into this shelf work (card detail is where audio shows). Now TWO work-packages, ONE PR.
---

# BRIEF — AI_HOTEL_FIELD_NOTES_AND_AUDIO_1 — persist raw audio + show saved cards in Field Notes

## Context
Director-ratified 2026-06-19. Two coupled gaps from his live smoke-test, both designed by codex-arch
(#3367 shelf + #3369 audio):
1. Saved structured cards are invisible — no viewer. Fold them into the **existing AI-Hotel Field Notes** section.
2. The recorder says "Recorded, 34 seconds" but the **raw audio is discarded after transcription** — Baker keeps
   transcript + photos + card, but NOT replayable audio. For site visits + counterparty conversations that's
   weaker than "recording" implies.

Bundled into ONE b1 PR because both touch the SAME endpoint (`GET /api/ai-hotel/captures`) and the SAME card-
detail UI — splitting would force a builder collision or a sequencing wait.

**RACI:** accountable=lead, responsible=b1, design=codex-arch (#3367/#3369), gate=codex (G3). **Complexity:** Medium.

## Current State (verified)
- Feed: `GET /api/ai-hotel/captures` — `outputs/dashboard.py:9664` (newest-first, fail-soft, N+1-safe child images).
- Capture insert + transcribe: structured POST `/api/ai-hotel/form-drafts` (`dashboard.py:9771`) persists raw
  capture in `ai_hotel_captures` FIRST (commit), THEN `_ai_hotel_transcribe()` (`dashboard.py:9740`), then folds
  transcript into `ai_hotel_captures.note_text` via UPDATE. **The audio binary is never stored.**
- Tables live: `ai_hotel_captures`, `ai_hotel_capture_images`, `ai_hotel_form_records`.
- UI: `outputs/static/ai-hotel-capture.html` (Field Notes render + recorder). `audioBlob` is browser-memory only
  until submit.

## Engineering Craft Gates
- **Diagnose:** N/A (additive). **Prototype:** N/A (UX pre-decided #3367/#3369).
- **TDD:** APPLIES. Two vertical tests first: (a) audio submit → `ai_hotel_capture_audio` row exists BEFORE
  transcription; (b) capture WITH confirmed form_record → combined item carries `form_record`. Then build.

---

## WORK-PACKAGE A — audio raw-evidence persistence (write path)

### A1. New migration `migrations/20260619b_ai_hotel_capture_audio.sql` (NEW file)
```
ai_hotel_capture_audio(
  id BIGSERIAL PK,
  capture_id BIGINT FK -> ai_hotel_captures(id) ON DELETE CASCADE,
  ordinal INT DEFAULT 0,
  audio_b64 TEXT NOT NULL,
  audio_media TEXT NOT NULL,
  duration_seconds INT NULL,
  transcript_text TEXT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
)
```
Index `(capture_id)`. Reuse the existing audio size cap; base64 like the image child table.

### A2. Store order (load-bearing — keep #380's fix intact)
- Persist the raw capture row, THEN the `ai_hotel_capture_audio` row, **BEFORE** transcription/extraction.
- A transcription failure must still leave BOTH the capture row AND the audio row (AC7). Wrap in try/except + rollback.
- After transcription succeeds, UPDATE both `ai_hotel_captures.note_text` AND `ai_hotel_capture_audio.transcript_text`.

### A3. UX copy (resolves Director's "where does the recording live?")
- After stop: **"Recorded locally — tap Extract/Send to save to Baker."**
- After save: **"Saved to Baker: audio + transcript + card."**

---

## WORK-PACKAGE B — Field Notes structured-card shelf (read/display, codex-arch #3367)

### B1. Extend `GET /api/ai-hotel/captures` (do NOT add a second list route)
- LEFT JOIN `ai_hotel_form_records` on `capture_id` → latest **non-discarded** record per capture as optional
  `form_record` object (null when none). One combined item per capture, newest-first. Keep fail-soft (`{"captures":[]}`).
- Add `audio[]` **metadata only** in list view: `{ordinal, audio_media, duration_seconds, has_transcript}` —
  **do NOT return large audio_b64 in the list** (AC10). Full `audio_b64` only via card-detail fetch.
- N+1-safe batch (`capture_id = ANY(%s)`). Never duplicate image/audio base64 into form records.

### B2. Field Notes UI (existing section)
- Type chip: `Free note` / `Site` / `Supplier`. Site-card compact row: location clue, `hospitality_fit`,
  `overall_score`, `next_action`, missing-research count.
- Tap → detail: structured fields + raw evidence (photos, **audio play/download control**, transcript, note).
  Detail shows "Audio: 34s" + transcript + play/download — audio control ONLY in detail, not list.
- Filters: `All` / `Site Cards` / `Suppliers` / `Free Notes`. Detail actions: Edit, Export/Copy, Mark researched, Dismiss.
- XSS-safe (`textContent`/`createTextNode`, never `innerHTML` with card data). Cache-bust `?v=N` on touched static.

## Acceptance criteria (pytest — NOT "by inspection")
- AC1: capture without a form record appears as `Free note`.
- AC2: a confirmed site card appears with the `Site` chip.
- AC3: card detail includes structured fields AND raw evidence (photo/audio/transcript/note).
- AC4: filters correctly hide/show Site / Supplier / Free notes.
- AC5: a missing/invalid/discarded form record never breaks the feed.
- AC6: audio submit creates capture row + `ai_hotel_capture_audio` row BEFORE transcription.
- AC7: transcription failure still leaves the capture row AND the audio row (no audio loss).
- AC8: successful transcription writes transcript to BOTH `note_text` and `audio.transcript_text`.
- AC9: site card links to capture_id and its detail can surface the associated audio.
- AC10: list view does NOT load large audio base64 for every card (metadata only).

## Files Modified
- `outputs/dashboard.py` — store audio child row; extend captures GET (form_record + audio metadata); detail audio fetch.
- `migrations/20260619b_ai_hotel_capture_audio.sql` — NEW.
- `outputs/static/ai-hotel-capture.html` — recorder copy + Field Notes chips/filters/detail + audio control.
- `tests/test_ai_hotel_field_notes.py` + `tests/test_ai_hotel_audio_persist.py` — NEW (AC1–AC10).

## Do NOT Touch
- POST form-drafts/confirm/discard semantics (#380). Applied migrations. `ai_hotel_form_records` schema.
- The #380 raw-save-before-transcription ordering — extend it, don't break it.

## Done rubric
DONE = AC1–AC10 pytest green (paste tail) + `py_compile` clean + live exercise on deployed dashboard (record
audio → save → see card in Field Notes with playable audio + transcript; real card id=5 Palo Alto shows with
Site chip) + codex G3 PASS + `POST_DEPLOY_AC_VERDICT v1`. Compile-clean ≠ done.

## Kill criteria
- Audio lost on transcription failure → stop (AC7 guard). Feed breaks on malformed record → stop (AC5).
- List view ships full audio base64 (payload blowup) → stop (AC10). Any image/audio base64 duplicated into
  form_records → stop. Any write added to the captures READ path beyond the documented audio store → reject.

## Gate plan
G1 pytest → G2 `/security-review` → G3 codex (bus `lead`→`codex`, topic `gate-request/prNNN`) → lead merge →
b1 `POST_DEPLOY_AC_VERDICT v1`. Branch `b1/ai-hotel-field-notes-and-audio-1` → PR to baker-master `main`.
Bus-post on ship + gate-request + post-deploy. Reply target: lead.
