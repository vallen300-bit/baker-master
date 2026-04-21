# BRIEF: STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1

**Status:** RATIFIED 2026-04-21 by Director (implicit: diagnostic accepted, proposal shipped)
**Source:** `briefs/_reports/B2_pipeline_diagnostic_20260421.md` (commit `1ac8ed0`)
**Estimated effort:** S — 1-4h implementation + review
**Assignee:** B1 (wrote the bridge; best context on payload shape + what Step 1+ should read)
**Reviewer:** B3 (familiar with both bridge + pipeline from recent reviews)
**Unblocks:** Cortex T3 Gate 1 (5-10 signals end-to-end through Steps 1-7)

---

## Why

Per B2's diagnostic:

- Steps 1/2/3/5 consumer code all `SELECT raw_content FROM signal_queue`. But `raw_content` is not a column in the live schema — the bridge writes body text into `payload->>'alert_body'`.
- Every Step 1 tick raises `UndefinedColumn`. Postgres rollback leaves the row at `status='processing'` because `claim_one_signal` had already committed that transition. Subsequent ticks only claim `status='pending'` rows — stranding 15 rows permanently.
- `kbl_cost_ledger` has zero rows (Ollama never reached). `kbl_log` has 15 ERROR entries with verbatim `column "raw_content" does not exist` — emit_log at `pipeline_tick.py:359-365` produced exact SQL on every failure.
- Step 1 docstring at line 430 anticipated this exact risk as a known follow-up that never shipped.

This is a schema-producer vs schema-consumer mismatch. Bridge and pipeline were built in parallel; the contract drifted. Fix is mechanical but load-bearing: without it, Gate 1 cannot close.

---

## Fix / Feature

### 1. Redirect all step readers to `payload->>'alert_body'`

All 4 step consumer files that read `raw_content`:
- `kbl/steps/step_1_*.py`
- `kbl/steps/step_2_*.py`
- `kbl/steps/step_3_*.py`
- `kbl/steps/step_5_*.py`

(B1: verify the exact set by grepping `SELECT raw_content` and `FROM signal_queue` before editing. B2's diagnostic confirmed 4 files; verify the 5th if any is missed.)

Change the SELECT column from `raw_content` to:

```sql
COALESCE(payload->>'alert_body', summary, '') AS raw_content
```

**Rationale for fallback order:**
1. `payload->>'alert_body'` — bridge's canonical body field (5388 existing alerts + all future)
2. `summary` — already populated on every signal_queue row; fallback for edge cases where payload is malformed
3. `''` — empty string rather than NULL, so downstream concatenation code doesn't blow up on legacy rows

**Alias as `raw_content`** so the rest of each step's code (which references `row['raw_content']` etc.) doesn't need refactoring. One-line change per file.

### 2. Fix test fixtures

Any test fixture inserting a `signal_queue` row for step-consumer tests currently likely uses a non-existent `raw_content` column or stuffs the body into the wrong field. Each of the 5 affected test modules (per B2's estimate) needs its fixture updated to insert body into `payload` as `{"alert_body": "...", ...}` — matching the bridge's actual shape.

Shared fixture helper recommended (if not already present): `tests/fixtures/signal_queue.py::insert_test_signal(body, matter=None, ...)` that builds the payload correctly. If no shared fixture exists, create one as part of this PR.

### 3. Bridge → Step-1 integration test (NEW — prevents this class of bug)

This is the test that would have caught the mismatch before it shipped. New test file: `tests/test_bridge_pipeline_integration.py`.

Scenario:
1. Insert a live-shape alert row via the bridge (use `alerts_to_signal.map_alert_to_signal` directly, not a hand-rolled signal_queue insert).
2. Call the pipeline tick once (whatever function `kbl_pipeline_tick` calls — likely `process_one_signal` or equivalent).
3. Assert: row advances past `stage=triage`, `triage_score IS NOT NULL`, no ERROR in kbl_log for this row.

**Uses existing `needs_live_pg` fixture** — runs against TEST_DATABASE_URL. Gates the pipeline contract at the boundary where the real drift happened.

### 4. Recovery UPDATE for the 15 stranded rows

After the code fix merges and deploys:
```sql
UPDATE signal_queue
SET status='pending', started_at=NULL, processed_at=NULL
WHERE status='processing' AND stage='triage' AND triage_score IS NULL
  AND id <= 15;
```

Run this ONCE, post-deploy. It's safe because:
- All 15 rows have NULL triage_score (no partial state to preserve).
- `started_at`/`processed_at` reset to NULL — pipeline_tick will re-claim and re-process them from scratch.
- `payload` + `summary` + `matter` + `hot_md_match` preserved (set by the bridge, not the pipeline).

**Who runs it:** AI Head, as a Tier B action, after Director's explicit "yes". Include the exact SQL in the ship report so Director can see before authorizing.

---

## Schema changes

**None.** This is a code-to-schema alignment fix, not a schema change.

(Do NOT add `raw_content` as a generated column — that would be a semantic contract move inverting the bridge's canonical payload shape.)

---

## Pre-merge verification (per B3's N3 lesson from Phase D)

Your ship report MUST include:
1. Grep output confirming all `SELECT raw_content` in `kbl/steps/` files are redirected (zero remaining).
2. Unit tests green (all affected step modules).
3. New bridge → Step-1 integration test green against TEST_DATABASE_URL.
4. Recovery-UPDATE SQL shown verbatim in the report — Director authorizes before AI Head runs it.
5. Diagnostic-logging preservation: `emit_log` at `pipeline_tick.py:359-365` is UNTOUCHED. B2 called out that the diagnostic-friendliness of surfacing the exact SQL on failure is "worth keeping." Confirm no changes to that block.

---

## Key constraints

- **Do not silently swallow errors.** Keep the `emit_log` pattern as-is. If a step finds a row with neither payload nor summary (shouldn't happen, but possible from legacy), log WARN and move on — don't crash the tick.
- **No schema changes.** Code fix only.
- **Fallback must not mask future schema drift.** If in the future a producer writes to a new column, we want the alignment error surfaced, not silently fallen-back-to-empty. The COALESCE is a safety net, not a cover-up — document this in a comment at each change site.
- **Recovery UPDATE is a one-shot.** Not a scheduler job, not a retry loop. Executed once, verified, logged.

---

## Out of scope

- Any Steps 4, 6, 7 work. B2 reported Steps 1/2/3/5 as the affected set (4 consumer files). Steps 4/6/7 may or may not exist; if they do and they hit the same schema, include them — but don't invent new Step 4/6/7 logic in this brief.
- Pipeline-tick redesign. Current claim-then-process pattern stays.
- Migration of the 5388 pre-existing `alerts` rows that never flowed through the bridge. Bridge watermark stays at its current position; historical sweep is a separate brief if ever needed.

---

## Verification (post-deploy)

After merge + deploy + recovery UPDATE:
1. Wait one pipeline tick cycle (~120s).
2. Check `signal_queue`:
   ```sql
   SELECT stage, status, COUNT(*) FROM signal_queue GROUP BY stage, status;
   ```
   Expect: rows advancing past `triage`; `status='completed'` or next-stage names appearing.
3. Check `kbl_cost_ledger`:
   ```sql
   SELECT COUNT(*) FROM kbl_cost_ledger;
   ```
   Expect: non-zero (Ollama now reached).
4. Check `kbl_log`:
   ```sql
   SELECT COUNT(*) FROM kbl_log WHERE severity='ERROR' AND component='pipeline_tick' AND created_at > NOW() - INTERVAL '10 minutes';
   ```
   Expect: zero new ERROR rows (15 historical stay for paper trail).

**Gate 1 closes** when ≥5-10 signals reach a terminal stage (target_vault_path + commit_sha populated, or however "end of Step 7" manifests in the schema).

---

## Day 2 teaching protocol

Once signals are flowing:
- AI Head generates pre-flagged Batch #2 as soon as 5-10 new signals land (Day-1 teaching continues — now with richer data per signal since triage_summary + enriched_summary populate).
- Director flags → AI Head refines stop-list + hot.md → re-commits.
- After 2-3 days of flow: AI Head drafts `BAKER_PRIORITY_CLASSIFIER_TUNE_1` (classifier-level matter-tagging fix) using accumulated dismissal data.
