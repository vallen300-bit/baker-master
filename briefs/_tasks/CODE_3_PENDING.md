---
status: PENDING
brief_id: ATTACHMENT_TWO_WRITE_PARITY_1
dispatch: ATTACHMENT_TWO_WRITE_PARITY_1
to: b3
from: lead
dispatched_by: lead
task_class: bug-fix + small-feature (live-path write + backfill Qdrant half)
harness_v2: applies
gate_plan: G0 codex (brief) → G1 lead (literal pytest) → G2 /security-review → G3 codex (code)
---

# B3 dispatch — ATTACHMENT_TWO_WRITE_PARITY_1

## Context Contract (read before building)

- **Repo:** baker-master, working dir `~/bm-b3`. Test on py3.12 (`/opt/homebrew/bin/python3.12 -m pytest`); py3.9 can't import `outputs/dashboard.py` (PEP-604 chain).
- **Parent:** INGEST_RETRIEVAL_GAP_DIAGNOSE_FIX_1 (PR #285 merged `a7a0341`) + the Phase-2 coverage audit `briefs/_reports/B1_INGEST_COVERAGE_AUDIT_PHASE2_20260603.md`. **Read that report first — it is the spec source.**
- **The rule (load-bearing):** a source is fully covered only if its content reaches **both** stores in the form the consumers query:
  - **Postgres `documents`** (system of record the Documents UI + `GET /api/documents/search` read) ← `store_document_full()` (`memory/store_back.py:432`)
  - **Qdrant `baker-documents`** (semantic layer chat/Cortex RAG reads) ← `ingest_file()` (`tools/ingest/pipeline.py:27`)
  - Both halves must be paired. Reference implementation: `triggers/dropbox_trigger.py` (`store_document_full` + `ingest_file` + `queue_extraction`, ~lines 229-253 and 519-537). The now-fixed `/api/ingest` (PR #285, `outputs/dashboard.py` ~10500) mirrors it.

## Problem (two linked gaps, same root)

1. **Live attachments never become first-class `documents` rows.** Email attachments (extracted via `scripts/extract_gmail.py:extract_attachments_text`) and WhatsApp media (`triggers/waha_webhook.py`) have their text **inlined into the parent email/WA record** only. They are searchable as email/WA text but do NOT appear as standalone, classified, matter-tagged documents, and `store_document_full`'s dedup + `queue_extraction` classification never runs on them. The only promotion path today is the **manual batch** `scripts/backfill_email_attachments.py` — not the live path.
2. **The backfill skips the Qdrant half — CONFIRMED (was VERIFY).** `scripts/backfill_email_attachments.py:127` calls `store.store_document_full(...)` but the file contains **no** `ingest_file` / `baker-documents` Qdrant upsert (grep-confirmed by lead). So backfilled attachments are in the Documents tab + FTS but **absent from semantic search**.

## Scope — what to build

**Phase 1 — backfill Qdrant half (small, do first):**
- In `scripts/backfill_email_attachments.py`, after the successful `store_document_full` at line ~127, add the paired `ingest_file(...)` → Qdrant `baker-documents` upsert (mirror dropbox_trigger). Guard non-fatal (try/except + `logger.warning`). Idempotent — re-runs must not duplicate.

**Phase 2 — live-path promotion:**
- At the **live** attachment-extraction point feeding email (`triggers/email_trigger.py`; note legacy IMAP `exchange_poller`/`bluewin_poller` also feed mail — promote at the shared extraction point, not per-poller, if one exists) and WhatsApp (`triggers/waha_webhook.py`), for **each attachment**:
  1. Extract text via the existing extractors (`tools/ingest/extractors.py` / `scripts/extract_gmail.py`) — reuse, do not re-implement.
  2. `store_document_full(source_path=..., filename=..., file_hash=..., full_text=..., token_count=..., owner=...)` → Postgres `documents`. Pass a meaningful `source_path`/`filename` so the doc is attributable to its parent message (e.g. `email:<msg-id>:<attachment-name>`); `owner` per the existing path convention.
  3. `ingest_file(...)` → Qdrant `baker-documents`.
  4. `queue_extraction(document_id)` (`tools/document_pipeline.py:412`) for classification + matter-tagging — best-effort, non-fatal (try/except + `logger.warning`), matching dropbox_trigger.
- **Keep** the existing inline-into-parent behavior (do NOT regress email/WA text search) — this ADDS standalone-doc promotion alongside it.
- **Idempotency:** `store_document_full` dedups on file_hash + content_hash — re-processing the same attachment must collapse, not duplicate.
- **Fail-loud:** if the Postgres write returns no id, `logger.error` (the #285 lesson) — never silently succeed on a half-write.

## Key Constraints

- All DB/API calls wrapped in try/except **with `conn.rollback()`** in the except (PG pool poisoning pattern).
- Attachment promotion must be **non-fatal** to the parent-message ingest — a failed attachment write must not drop the email/WA message.
- **No backfill/embedding work on startup** (OOM lesson) — promotion runs on the live poll/webhook path, not at boot.
- Surgical edits; don't touch code orthogonal to attachment handling.
- Do NOT instantiate `SentinelRetriever()`/`SentinelStoreBack()` directly — use `_get_global_instance()` / the established accessor. CI guard: `bash scripts/check_singletons.sh`.
- No new external deps without flagging in the ship report.

## Verification / Done rubric (answer literally in the ship report — not "tests pass")

1. **Backfill Qdrant half:** show the added `ingest_file` call + a proof a backfilled attachment now lands in `baker-documents` (count/id).
2. **Live round-trip proven:** a real (or fixture) email with a PDF/docx attachment, ingested via the live trigger, produces (a) a standalone `documents` row, (b) retrievable via `GET /api/documents/search`, (c) present in Qdrant `baker-documents`. Show evidence (counts/ids), not "it should."
3. **No regression:** parent email/WA text still searchable via the email/WA surfaces.
4. **Idempotency:** re-ingesting the same attachment does not create a duplicate `documents` row.
5. `bash scripts/check_singletons.sh` = OK; literal `pytest` output (py3.12) for touched tests.

## Files likely modified
- `scripts/backfill_email_attachments.py` — add Qdrant `ingest_file` half.
- `triggers/email_trigger.py` (and/or shared extraction point) — live attachment promotion.
- `triggers/waha_webhook.py` — live WA media promotion.
- `tests/test_attachment_two_write_parity.py` (new) — round-trip + idempotency + no-regression guards.

## Do NOT touch
- `outputs/dashboard.py` `/api/ingest` handler — already fixed (#285).
- `/api/documents/search` read path — that's **Bug A**, a separate Tier-B decision.

## Gate plan (Harness V2)
- G0 codex brief review (lead dispatches before you start).
- G1 lead — literal pytest + diff review.
- G2 `/security-review` — write-path change, mandatory (Lesson #52).
- G3 codex — code correctness/architecture.
- POST_DEPLOY_AC_VERDICT v1 after merge (live attachment round-trip on prod).

## Out of scope
- **Bug A** (dead Qdrant read branch in `/api/documents/search`) — separate Tier-B product decision.
- **M365 ingestion** — gated on Azure creds; separate brief. But build the promotion as a reusable helper so the future M365 attachment path inherits it.

## Reply target
Bus-post all findings + ship report to `lead`. Plain technical prose (NOT Director-facing register — no `Bottom line:` / `Recommendation:` / `Bus:` closers).
