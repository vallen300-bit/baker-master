---
status: PENDING
brief_id: ATTACHMENT_TWO_WRITE_PARITY_1
dispatch: ATTACHMENT_TWO_WRITE_PARITY_1
to: b3
from: lead
dispatched_by: lead
task_class: bug-fix + small-feature (Qdrant-half + shared helper)
harness_v2: applies
gate_plan: G0 codex (brief) → G1 lead (literal pytest) → G2 /security-review → G3 codex (code)
revision: v2 (G0 #1711 FAIL folded — corrected premise + helper contract + scope)
---

# B3 dispatch — ATTACHMENT_TWO_WRITE_PARITY_1 (v2)

## Context Contract (read before building)

- **Repo:** baker-master, working dir `~/bm-b3`. Test on py3.12 (`/opt/homebrew/bin/python3.12 -m pytest`).
- **Parent:** INGEST_RETRIEVAL_GAP (#285 merged `a7a0341`) + Phase-2 coverage audit `briefs/_reports/B1_INGEST_COVERAGE_AUDIT_PHASE2_20260603.md`. **Note: this v2 brief CORRECTS two overstatements in that audit** (codex G0 #1711) — read the corrections below, not just the audit.
- **The rule (load-bearing):** content is fully covered only if it reaches **both** stores:
  - **Postgres `documents`** (Documents UI + `GET /api/documents/search`) ← `store_document_full()` (`memory/store_back.py:432`)
  - **Qdrant `baker-documents`** (chat/Cortex RAG) ← chunk+embed+upsert.
  - Reference two-write: `triggers/dropbox_trigger.py` (~229-253). The now-fixed `/api/ingest` (#285) mirrors it.

## Corrected premise (what is ACTUALLY true — verified by lead + codex)

- **Gmail live attachments ALREADY become first-class `documents` rows.** `scripts/extract_gmail.py:710-727` calls `store_document_full(source_path="email:{mid}/{name}", ...)` + `queue_extraction` per attachment (SPECIALIST-UPGRADE-1B). Prod has 347 `source_path LIKE 'email:%'` docs, newest 2026-06-02. **So the Postgres half is DONE for Gmail.** The gap is the **Qdrant half** — these docs are not embedded into `baker-documents`, so they're absent from semantic RAG.
- **`scripts/backfill_email_attachments.py:127` is Postgres-only too** (no Qdrant) — same gap.
- **WhatsApp media:** verify current state (Phase 1 audit task) — likely inline-into-message body, may need both halves.
- **Legacy IMAP (Bluewin/Exchange) skip attachments entirely** — `triggers/bluewin_poller.py:44-67` + `triggers/exchange_poller.py:51-73` `_extract_body` return body text only, no attachment parts. **Extracting their attachments is OUT OF SCOPE here** (bigger effort) — flag as a follow-up, do not attempt.

## Critical implementation constraint (the foot-gun codex caught)

**Do NOT call `ingest_file(...)` at these sites.** `ingest_file` (`tools/ingest/pipeline.py:27`) takes a **filepath** and **re-extracts** from it (Step 1, ~line 72). At all attachment sites we have **already-extracted text**, not a durable file (Gmail writes attachment bytes to a temp file and **deletes it** in `_extract_text_from_bytes`'s `finally` at `scripts/extract_gmail.py:758` before the store block runs). Calling `ingest_file` would be a signature/contract bug (lessons #17/#86) and would double-extract.

**Instead: build a reusable text→Qdrant path.** Factor the post-extraction half of `ingest_file` (Step 4 chunk → Step 5 embed → Step 6 upsert → `log_ingestion`, `tools/ingest/pipeline.py:~134-180`) into a new function, e.g.:
```python
# tools/ingest/pipeline.py
def ingest_text(full_text, filename, source_path, collection="baker-documents",
                file_hash=None, project=None, role=None, skip_dedup=False):
    """Chunk + embed + upsert ALREADY-EXTRACTED text into Qdrant. No re-extraction.
    Mirrors ingest_file Steps 4-6. Returns IngestResult (chunk_count, point_ids)."""
```
Then a single shared promote helper used by every attachment site:
```python
# suggested: tools/ingest/attachments.py  (or alongside store_back)
def promote_attachment_text_to_document_and_qdrant(source_path, filename, full_text,
                                                   owner="shared", file_hash=None):
    """store_document_full (fail-loud) + ingest_text(baker-documents) + queue_extraction (best-effort).
    Idempotent (store_document_full dedups file_hash+content_hash; ingest_text honors dedup)."""
```

## Scope — what to build

**Phase 1 (audit + backfill Qdrant half):**
1. Confirm WA media current state (inline vs stored) — report on bus with file:line.
2. Add the Qdrant half to `scripts/backfill_email_attachments.py` (use the new helper).

**Phase 2 (live-path Qdrant half via the shared helper):**
1. Build `ingest_text(...)` + `promote_attachment_text_to_document_and_qdrant(...)`.
2. Replace the store-only block in `scripts/extract_gmail.py:710-727` with the helper (keeps Postgres write, ADDS Qdrant).
3. Apply the helper to `scripts/backfill_missed_attachments.py` (same gap).
4. WhatsApp media: after `extract_media_text` (in `triggers/waha_webhook.py`), call the helper for each media item (currently inline-into-body at `~953-975` + stored as parent WA message at `~983-994` — so full two-write). **Pass a durable `source_path` to the helper** — prefer `media_dropbox_path` (`~949-950`), with a deterministic `whatsapp:{msg_id}/...` fallback if the Dropbox upload returned no path. **Do NOT use the local filepath** — the `finally` block deletes it at `~959-963` (codex G0 nit).
5. **Keep parent inline text unchanged** (no regression to email/WA text search).

## Key Constraints

- All DB/API calls try/except **with `conn.rollback()`** in except.
- Helper writes must be **non-fatal** to parent-message ingest.
- **No re-extraction; no `ingest_file` at text-only sites.**
- No startup/backfill embedding storms (OOM lesson) — live path only; backfill is manual batch.
- Singleton accessor only (`SentinelStoreBack._get_global_instance()` / `SentinelRetriever._get_global_instance()`). CI guard `scripts/check_singletons.sh`.
- Reuse Voyage/Qdrant client setup from `ingest_file` — don't fork config.

## Verification / Done rubric (answer literally — not "tests pass")

1. **WA media audit verdict** (inline vs stored) with file:line.
2. **Gmail attachment now in Qdrant:** ingest a fixture/real Gmail attachment → confirm it lands in `baker-documents` (count/id) AND still has its `documents` row (no regression).
3. **Backfill Qdrant half:** a backfilled attachment appears in `baker-documents`.
4. **Idempotency:** re-processing the same attachment does not duplicate the `documents` row or the Qdrant points.
5. **No regression:** parent email/WA text still searchable.
6. `bash scripts/check_singletons.sh` = OK; literal `pytest` (py3.12) for new helper + each site.

## Files likely modified
- `tools/ingest/pipeline.py` — new `ingest_text(...)`.
- `tools/ingest/attachments.py` (new) — `promote_attachment_text_to_document_and_qdrant(...)`.
- `scripts/extract_gmail.py` (~710-727) — use helper.
- `scripts/backfill_email_attachments.py`, `scripts/backfill_missed_attachments.py` — use helper.
- `triggers/waha_webhook.py` — WA media promotion.
- `tests/test_attachment_two_write_parity.py` (new).

## Do NOT touch
- `outputs/dashboard.py` `/api/ingest` (#285) and `/api/documents/search` (Bug A = b1, separate).
- Bluewin/Exchange attachment EXTRACTION — out of scope (follow-up).
- Parent inline-text behavior.

## Gate plan (Harness V2)
- G0 codex (this v2) → G1 lead (literal pytest) → G2 /security-review (write-path, Lesson #52) → G3 codex → POST_DEPLOY_AC_VERDICT v1.

## Reply target
Bus-post findings + ship report to `lead`. Plain technical prose (NOT Director-facing register).
