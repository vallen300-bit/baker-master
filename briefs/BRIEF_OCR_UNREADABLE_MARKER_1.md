# BRIEF: OCR_UNREADABLE_MARKER_1 — terminal marker for un-OCR-able docs

## Context
The OCR re-extract drain (`POST /api/documents/ocr-extract-missing`, OCR_REEXTRACT_MISSING_1, PR #294)
recovered ~290 of 577 blank scanned PDFs via Gemini vision. The remaining 287 fail with
`reason: "unreadable"` (the `[[UNREADABLE]]` guard — genuinely image-only/blank scans Gemini cannot
extract). **Bug:** these failures are NOT persisted as terminal, so the candidate query keeps
re-selecting the same 287 every drain — each run re-bills Gemini (gemini-2.5-pro vision) on docs that
will never succeed. The AH1 drain loop hit this: batches plateaued at remaining=287 while still
spending. The drain is not idempotent.

### Surface contract: N/A — backend-only change to the OCR endpoint + its candidate query; no clickable surface.

## Estimated time: ~30–45 min
## Complexity: Low
## Task class: reliability guard (idempotency fix)
## Harness-V2: applies — small brief; gate G1 lead pytest → light G2 → merge → POST_DEPLOY_AC.

---

## Problem
`POST /api/documents/ocr-extract-missing` selects candidates by blank/empty `full_text`. When Gemini
returns the unreadable guard, the doc is reported in `failed[]` but left blank → re-selected forever.

## Current State
You (b1) built this endpoint (PR #294). The candidate selection + the `reason: "unreadable"` failure
branch are yours. Confirm the exact candidate query + the failure-handling line before changing them.

## Implementation (b1 picks the cleanest mechanism at G0 — propose before building)
Persist a terminal "unreadable" marker so the doc drops out of the candidate pool but does NOT pollute
search. Preferred options (pick one, justify):
- **(A)** A dedicated state — e.g. `ocr_status = 'unreadable'` (new column or existing status field) +
  `AND (ocr_status IS DISTINCT FROM 'unreadable')` in the candidate query. Cleanest; keeps full_text untouched.
- **(B)** An attempt counter — `ocr_attempts` increments on each unreadable; candidate query excludes
  `ocr_attempts >= 2`. Allows a future re-try if a better OCR path lands.
Do NOT write a sentinel into `full_text` that would surface in `/api/documents/search` results.
Add an `--include-unreadable` / `force` flag so a future better-OCR path can re-attempt the marked set.

## Key Constraints
- Idempotent: a marked doc is never re-sent to Gemini on a normal drain.
- No search pollution: marked docs must not appear as junk hits in document search.
- Fault-tolerant: try/except + `conn.rollback()` on any DB write; every query LIMITed.
- If a new column is needed, add a migration (never edit an applied one).

## Acceptance Criteria
- **AC1** A doc that returns `unreadable` is marked terminal; a second drain does NOT re-attempt it.
- **AC2** `blank_count` / candidate query excludes marked docs; remaining stops counting the 287 dead.
- **AC3** Marked docs do not appear in `/api/documents/search` results.
- **AC4** A `force`/`--include-unreadable` path can still re-attempt the marked set on demand.
- **AC5** POST_DEPLOY_AC: run one live drain → it returns 0 candidates (or only genuinely-new blanks),
  no Gemini calls on the 287; confirm via response `attempted`/`failed` + a search spot-check.

## Files Modified (b1 — final at G0)
- The OCR endpoint file (candidate query + unreadable-failure branch).
- `migrations/` — new migration if a column is added.
- tests — unreadable-marks-terminal + excluded-from-candidates + force-reattempt.

## Do NOT Touch
- The successful-recovery path (UPDATE that preserves owner) — unchanged.
- Unrelated search/ingest surfaces.

## Gate plan
G1 lead literal pytest → light G2 → merge → POST_DEPLOY_AC_VERDICT v1 (one clean drain on prod).
