# B3 Completion Report — ATTACHMENT_TWO_WRITE_PARITY_1

- **Date:** 2026-06-03
- **Branch:** `b3/attachment-two-write-parity-1`
- **PR:** #286
- **Commit:** 1ef14da (feat) + 5d9621c (G3 #1725 revise)
- **Brief:** `briefs/_tasks/CODE_3_PENDING.md` (v2, G0 codex PASS-WITH-NIT #1715)
- **Gate plan:** G0 codex ✅ → G1 lead (literal pytest) → G2 /security-review ✅ CLEAR → G3 codex ❌ FAIL #1725 → **REVISED 5d9621c, re-shipping for G1→G2→G3**

## G3 #1725 revision (5d9621c)

Codex G3 FAIL: one real gap in `scripts/backfill_email_attachments.py`. It loaded
`existing_hashes` from `documents WHERE source_path LIKE 'email:%'` then `continue`d on
any already-present hash — *before* reaching the new `ingest_text` call (which sat inside
the post-store `if doc_id:` block). So the 347 already-stored Postgres-only `email:%` rows
— the exact population this task exists to embed — never reached Qdrant; only brand-new
attachments did.

**Fix:** decouple "documents row exists" from "Qdrant/ingestion_log exists."
- Circuit breaker moved to the top of each attachment iteration (covers the embed path).
- If the `documents` row already exists: skip `store_document_full` + `run_pipeline`, but
  **fall through** to the Qdrant half.
- `ingest_text` is now ALWAYS attempted (new + pre-existing rows); self-dedups on
  `(filename, file_hash)` in `ingestion_log`, so already-embedded rows are cheap no-ops and
  re-runs stay idempotent.
- Added `test_backfill_embeds_preexisting_documents_rows`: seeds `existing_hashes` with an
  attachment's hash, asserts `ingest_text` STILL fires (filename + source_path + hash) while
  `store_document_full` / `run_pipeline` do NOT. Fails on the old `continue` path.

Post-revision: **14/14 parity tests pass (py3.12)**, singletons OK, all touched files compile.

## Goal

Attachments are fully covered only if they reach BOTH stores: Postgres `documents`
(Documents UI + `/api/documents/search`) AND Qdrant `baker-documents` (semantic RAG).
Email live attachments already became first-class `documents` rows (SPECIALIST-UPGRADE-1B)
but were never embedded into Qdrant; WhatsApp media text was inline-into-parent only.
This PR adds the missing Qdrant half via a reusable text→Qdrant path + a shared promote helper.

## What shipped

| File | Change |
|---|---|
| `tools/ingest/pipeline.py` | New `ingest_text()` — chunk+embed+upsert ALREADY-extracted text, NO re-extraction. Refactored `_embed_and_upsert` to take `source_file`/`source_path` strings so the durable origin lands in the Qdrant payload. |
| `tools/ingest/attachments.py` (new) | `promote_attachment_text_to_document_and_qdrant()` — `store_document_full` + `ingest_text` + `queue_extraction`; idempotent, non-fatal (both halves wrapped, logged loud, never raised). |
| `scripts/extract_gmail.py` | Live email path promotes via the helper (keeps Postgres write, adds Qdrant). |
| `triggers/waha_webhook.py` | WA media text promoted with a DURABLE `source_path` (Dropbox path → `whatsapp:<id>/` fallback), never the deleted temp filepath. Parent inline text unchanged. |
| `scripts/backfill_email_attachments.py` | Adds `ingest_text` Qdrant embed; keeps the proven synchronous `run_pipeline` + circuit-breaker classify path. |
| `scripts/backfill_missed_attachments.py` | Covered transitively (delegates to `extract_attachments_text`). |
| `tests/test_attachment_two_write_parity.py` (new) | 13 tests. |

## Done-rubric answers (literal)

1. **WA media audit verdict:** media text is extracted (`extract_media_text`, `waha_webhook.py:955`), folded inline into `combined_body` (`:974`) and stored as the parent WA message (`store_whatsapp_message`, `:983-994`); the binary is uploaded to Dropbox (`:949`). It was **NOT** a first-class `documents` row and **NOT** in Qdrant → needed both halves. **Bluewin/Exchange attachment EXTRACTION remains OUT OF SCOPE** (`bluewin_poller.py:44-67` / `exchange_poller.py:51-73` return body text only) — flagged as follow-up, not attempted.
2. **Gmail attachment → Qdrant:** the live path now calls the helper, which runs `ingest_text` into `baker-documents` AND keeps the `documents` row. Covered by `test_ingest_text_*` + `test_promote_drives_both_halves_with_aligned_hash` (both halves, aligned hash) + source-level `test_gmail_live_path_uses_promote_helper`.
3. **Backfill Qdrant half:** `test_backfill_email_attachments_adds_qdrant_half` asserts `ingest_text` present + Postgres half preserved.
4. **Idempotency:** `test_ingest_text_idempotent_point_ids` (deterministic `make_point_id` → re-upsert overwrites). Postgres dedup via `content_hash` + `ON CONFLICT (file_hash)`. Qdrant dedup via `is_duplicate` short-circuit (`test_ingest_text_dedup_short_circuits`).
5. **No regression:** parent inline email/WA text untouched (`combined_body` / `store_whatsapp_message` retained — asserted in source check). Parent round-trip `test_ingest_retrieval_roundtrip.py` = 4 passed, 1 skipped.
6. **Singletons:** `bash scripts/check_singletons.sh` = OK. Literal pytest (py3.12) on new file = **13/13 pass**.

## Test results (py3.12)

- `tests/test_attachment_two_write_parity.py` — **14 passed** (was 13; +1 from G3 revision).
- `tests/test_ingest_retrieval_roundtrip.py` — 4 passed, 1 skipped (live PG).
- `bash scripts/check_singletons.sh` — OK.
- **G2 /security-review — CLEAR** (no findings; attacker inputs flow only into parameterized SQL + inert Qdrant data payloads).
- Pre-existing local failures in `test_gmail.py` / `test_extract_gmail_visibility.py` / `test_whatsapp_*` are missing-dep (`google.auth`) + live-PG/LID-DB-unreachable + cross-region latency flake — confirmed identical on clean `main` (clean main 10 fails vs branch 9; this PR adds zero).

## Deviation flagged (Mnilax surface-conflicts)

`backfill_email_attachments.py` calls `ingest_text` directly rather than the full promote helper. The script already does `store_document_full` + a synchronous, circuit-breaker-gated `run_pipeline` classify with its own `existing_hashes` dedup; the full helper would (a) redundantly re-store and (b) swap synchronous `run_pipeline` for async `queue_extraction` — a cost-safety/semantic change the brief didn't authorize. Adding `ingest_text` is the minimal "add the Qdrant half" with zero regression. Trivial to switch to the full helper if lead/codex prefers.

## Not exercised locally (fail-loud)

No true live ingestion smoke (no `VOYAGE_API_KEY`/Qdrant/PG creds in the b3 clone). Qdrant landing + idempotency are covered by mocked round-trip tests; live exercise happens on the next Gmail poll or a manual backfill. Recommend lead run `python scripts/backfill_email_attachments.py --limit N` on prod for end-to-end confirmation (POST_DEPLOY_AC).
