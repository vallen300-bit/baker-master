-- OCR_UNREADABLE_MARKER_1: terminal marker for un-OCR-able scanned docs.
--
-- The OCR re-extract drain (POST /api/documents/ocr-extract-missing,
-- OCR_REEXTRACT_MISSING_1, PR #294) selects candidates by blank full_text.
-- When Gemini vision returns the all-pages [[UNREADABLE]] guard (genuinely
-- image-only / blank scans it can never extract), the doc is reported in
-- failed[] but left blank -> the candidate query re-selects + re-bills it to
-- gemini-2.5-pro on every drain. The AH1 drain loop plateaued at remaining=287
-- while still spending. The drain is not idempotent.
--
-- Mechanism A (lead G0-approved 2026-06-06, bus #1945): a dedicated terminal
-- state. ocr_status='unreadable' marks the doc terminal so it drops out of the
-- candidate pool on a normal drain (zero re-bill), WITHOUT touching full_text
-- (so it never surfaces as a junk hit in /api/documents/search). A
-- ?include_unreadable=true force flag drops the exclusion so a future
-- better-OCR path can re-attempt the marked set.
--
-- Nullable; existing rows stay NULL (= eligible, unchanged behaviour). No
-- backfill — the next drain marks the 287 as it re-encounters them, then they
-- fall terminal. Partial index covers the force/re-attempt lookup of the
-- marked set (matches the research_proposals partial-index house pattern).

ALTER TABLE documents ADD COLUMN IF NOT EXISTS ocr_status TEXT;

CREATE INDEX IF NOT EXISTS idx_documents_ocr_status
  ON documents (ocr_status)
  WHERE ocr_status IS NOT NULL;
