# BRIEF: BACKFILL-COMPLETION-1 — Document Backfill Re-run + Email Attachment Backfill

**Author:** AI Head (baker-ai-dev) via Cowork
**Date:** 2026-03-10
**Priority:** HIGH
**Estimated cost:** ~$20-40 Haiku (Dropbox re-run) + ~$3-5 Haiku (email attachments)
**Estimated time:** ~2-4 hours (rate-limited by 12s/file Dropbox + 2s/classify)
**Run location:** LOCAL ONLY — do NOT run on Render (OOM history, PM-OOM-1)

---

## Context

Session 17 shipped SPECIALIST-UPGRADE-1A+1B — full document storage, classification pipeline, and email attachment handling. A Dropbox backfill was started but the terminal restarted mid-run. Logs were lost.

**Current state:**
| Table | Count | Notes |
|-------|-------|-------|
| `documents` | 384 | 300 Dropbox + 84 email |
| `document_extractions` | 674 | Classification + structured extraction |
| `baker_insights` | 0 | Wired but no specialist runs since deploy |
| Unclassified docs | 14 | Have full_text but NULL document_type |

**Gap:** The Dropbox backfill processed only 384 of ~4,553 files (8.4%). Many were legitimately deduped/skipped, but we lost the logs to confirm. The email attachment backfill script exists (`scripts/backfill_email_attachments.py`) but was never run.

---

## Task 1: Dropbox Backfill Re-run (with logging)

### What to do

1. `git pull origin main` — ensure latest
2. Run dry-run first to see the full scope:
   ```bash
   python scripts/backfill_documents.py --dry-run --all 2>&1 | tee backfill_dryrun.txt
   ```
3. Count the dry-run output — how many files would be processed vs already stored?
4. Run the real backfill with verbose logging:
   ```bash
   python scripts/backfill_documents.py --all 2>&1 | tee backfill_full_log.txt
   ```
5. After completion, report these counts:
   - Total files listed from Dropbox `/Baker-Feed/`
   - Skipped (already stored — hash match)
   - Skipped (empty extraction / too short)
   - Stored (new documents)
   - Classified
   - Errors
   - Circuit breaker stops (if any)

### Important notes
- The script uses `existing_hashes` dedup (line 82-91) — already-stored docs are skipped cheaply
- Rate limit: 12s between downloads, 2s between API calls (built in)
- Circuit breaker will stop extraction if daily cost exceeds €15 — this is fine, docs are still stored, classification can continue next day with `--extract-only`
- If circuit breaker fires, DON'T override it. Just note where it stopped.

### Expected outcome
Most of the ~4,553 files should be deduped (already stored). Net new documents: probably 50-200. Haiku cost for classification: ~$0.03/doc.

---

## Task 2: Classify Remaining 14 Unclassified Documents

```bash
python scripts/backfill_documents.py --extract-only 2>&1 | tee extract_only_log.txt
```

This runs the Haiku classify + extract pipeline on the 14 docs that have `full_text` but NULL `classified_at`. Cost: ~$0.42.

---

## Task 3: Email Attachment Backfill

### What exists
- `scripts/backfill_email_attachments.py` — **already built by Code 300, Session 17**
- Parses `=== ATTACHMENTS ===` section from `email_messages.full_body`
- Splits by `--- Attachment: filename.ext ---` headers
- Stores each attachment as a standalone document with `source_path = 'email:{msg_id}/{filename}'`
- Queues Haiku classification + extraction
- Dedup by SHA-256 hash

### Current numbers
- 188 total emails in `email_messages`
- 40 emails contain `=== ATTACHMENTS ===` sections
- 84 email attachment documents already stored (from live trigger)
- Unknown how many additional attachments exist in the 40 historical emails

### What to do

1. Dry-run first:
   ```bash
   python scripts/backfill_email_attachments.py --dry-run --all 2>&1 | tee email_att_dryrun.txt
   ```
2. Review the count — how many new attachments vs already stored?
3. Run for real:
   ```bash
   python scripts/backfill_email_attachments.py --all 2>&1 | tee email_att_log.txt
   ```
4. Report counts: stored, skipped (dedup), classified, errors

### Expected outcome
With only 40 emails having attachments and 84 already stored, net new documents will be small (probably 0-30). Haiku cost: < $1.

---

## Task 4: Verify Auto-Insight Extraction

After backfills complete, run one specialist query through Baker Scan (dashboard or API) and verify:
1. `_maybe_store_insight()` fires (check logs for "Storing insight" or similar)
2. `baker_insights` table gets at least 1 row:
   ```sql
   SELECT * FROM baker_insights ORDER BY created_at DESC LIMIT 5;
   ```
3. If 0 rows after a specialist run, investigate `capability_runner.py` lines 554-634

---

## Task 5: Commit & Push

After all tasks:
1. **Do NOT commit the log files** (backfill_*.txt) — they're local artifacts
2. If any code fixes were needed, commit those with descriptive messages
3. Push to main
4. Update this memory file with final counts:
   ```
   /Users/dimitry/.claude/projects/-Users-dimitry-Desktop-baker-code/memory/MEMORY.md
   ```
   Update the "Current State" section with:
   - Final document count
   - Final email attachment count
   - Backfill gap explanation (dedup vs skip vs error)
   - baker_insights status (populated or still empty + why)

---

## Files Reference

| File | Purpose |
|------|---------|
| `scripts/backfill_documents.py` | Dropbox → documents table (exists) |
| `scripts/backfill_email_attachments.py` | Email attachments → documents table (exists) |
| `tools/document_pipeline.py` | Haiku classify + extract pipeline (exists) |
| `orchestrator/capability_runner.py` | Auto-insight extraction (exists, lines 554-634) |
| `memory/store_back.py` | `store_document_full()` method (exists, line 227) |

---

## Success Criteria

- [ ] Dropbox backfill re-run complete with logged counts
- [ ] Gap explained (dedup/skip/error breakdown)
- [ ] 14 unclassified docs classified
- [ ] Email attachment backfill run
- [ ] `baker_insights` has at least 1 row (or root cause identified)
- [ ] Code 300 memory updated with final state
- [ ] No code pushed to main unless fixes were needed
