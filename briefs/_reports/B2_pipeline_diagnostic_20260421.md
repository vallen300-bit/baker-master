---
role: B2
kind: diagnostic
brief: pipeline_diagnostic
pr: n/a
head_sha: 36c15fb
verdict: DIAGNOSTIC_COMPLETE
date: 2026-04-21
tags: [cortex-t3, gate-1, signal_queue, step1_triage, schema-drift]
---

# B2 — Pipeline Diagnostic (stuck signal_queue rows)

**Scope reminder:** read-only. No fixes shipped. One recovery recommendation flagged at the end for AI Head to scope into a follow-up brief.

---

## Root cause

**Step 1 triage reads a `raw_content` column that does not exist in `signal_queue`.** Every tick raises `UndefinedColumn`, `_process_signal_remote` rolls back, row is stranded at `status='processing'` by the earlier `claim_one_signal` commit. Subsequent ticks only claim `status='pending'` rows, so stuck rows are never retried. This blocks Cortex T3 Gate 1 at Step 1 — Steps 2–7 never execute.

Classification per brief taxonomy: closest to **(c)** — "pipeline tick attempting Step 2+ but erroring" — though strictly it's **Step 1 erroring before any Ollama call**. The errors are NOT silent: `main()` emits them to `kbl_log` at ERROR before re-raising.

---

## Evidence

### 1. Live data shape — bridge writes `payload->>'alert_body'`, not `raw_content`

`signal_queue` has **35 columns**. `raw_content` is not one of them.

```sql
-- information_schema.columns for signal_queue (abridged; no raw_content)
id, created_at, source, signal_type, matter, summary, triage_score,
vedana, hot_md_match, payload (jsonb), priority, status, stage,
enriched_summary, result, wiki_page_path, card_id, ayoniso_alert,
ayoniso_type, processed_at, ttl_expires_at, primary_matter,
related_matters, triage_confidence, started_at, triage_summary,
resolved_thread_paths, extracted_entities, step_5_decision,
cross_link_hint, opus_draft_markdown, final_markdown,
target_vault_path, commit_sha, committed_at
```

Bridge inserts the body into `payload->>'alert_body'`:

- `kbl/bridge/alerts_to_signal.py:389-402` — `map_alert_to_signal()` packs `alert_body`, `alert_title`, etc. into the `payload` JSONB. Top-level `summary` column holds `alert.title`. No body is ever written to a top-level `raw_content` column.
- `kbl/bridge/alerts_to_signal.py:495-499` — `INSERT INTO signal_queue (source, signal_type, matter, primary_matter, summary, priority, status, stage, payload, hot_md_match)` — `raw_content` not in the column list.
- Live spot check on stuck rows: `payload->>'alert_body'` is populated on id=1 and id=15; no `raw_content` column exists to read from.

### 2. Step 1 reads a non-existent column

`kbl/steps/step1_triage.py:436` — `_fetch_signal()` executes:

```python
cur.execute(
    "SELECT raw_content FROM signal_queue WHERE id = %s",
    (signal_id,),
)
```

The step's own docstring anticipated this risk (line 430–432): *"Consumes `raw_content` per the evaluator assumption; if the column name differs in the live schema we'll see the failure at the SQL level and can adjust in a follow-up without touching the rest of the flow."* — that follow-up never shipped.

No migration in `migrations/` adds a `raw_content` column. The only references to `raw_content` for `signal_queue` are in test fixtures (`tests/test_status_check_expand_migration.py:275,295,313`), which insert synthetic rows that don't reflect the live producer schema.

### 3. kbl_log confirms — one ERROR per stuck row, verbatim message

```
component=pipeline_tick, level=ERROR, n=15 — one per signal_id 1..15
message: "unexpected exception in _process_signal_remote:
         column \"raw_content\" does not exist
         LINE 1: SELECT raw_content FROM signal_queue WHERE id = N"
timestamps: 2026-04-20 16:41:18 → 22:09:53 UTC (matches tick cadence)
```

`emit_log` in `kbl/pipeline_tick.py:359-365` is the source — the ERROR is the caller's catch-all around `_process_signal_remote`. Zero log entries for `ollama`, `triage`, or `circuit` components, so this is the first and only failure mode.

### 4. Why rows stay at `processing` forever

- `kbl/pipeline_tick.py:84-105` `claim_one_signal` does:
  1. `SELECT ... WHERE status='pending' FOR UPDATE SKIP LOCKED`
  2. `UPDATE ... SET status='processing', started_at=NOW()`
  3. **`conn.commit()`** — the claim is committed before any step runs.
- `_process_signal_remote` then calls `step1_triage.triage(signal_id, conn)`; `_fetch_signal` raises `UndefinedColumn`. The outer try/except (line 353-365 of `pipeline_tick.py`) rolls back + re-raises. Rollback only affects writes AFTER the commit — the `status='processing'` + `started_at` persist.
- Next tick's `claim_one_signal` filters on `status='pending'`. No stranded row is ever reclaimed.

### 5. No kbl_cost_ledger rows for any stuck signal

```sql
SELECT COUNT(*) FROM kbl_cost_ledger WHERE signal_id BETWEEN 1 AND 15;
-- 0
```

Confirms Ollama was never reached (the failure is before prompt build). Any future Ollama-availability work is downstream of this bug.

### 6. Blast radius — Steps 2, 3, 5 will hit the same column the moment Step 1 is unblocked

```
kbl/steps/step2_resolve.py:74         — "raw_content" in column list
kbl/steps/step3_extract.py:432-445    — SELECT raw_content, source, ...
kbl/steps/step5_opus.py:254,265,278   — SELECT raw_content, source, primary_matter, ...
```

Fixing `_fetch_signal` in Step 1 only unblocks the first hop. A complete fix must redirect all `SELECT raw_content` sites to the payload JSONB (e.g. `payload->>'alert_body'`, with `COALESCE` to `summary` for legacy producers). Otherwise Gate 1 moves from "stuck at Step 1" to "stuck at Step 2".

---

## Unblock effort estimate

**S (1–4h).** The fix is small but touches 4 step files + needs a recovery path:

- Edit `_fetch_signal` / equivalent readers in `step1_triage.py`, `step2_resolve.py`, `step3_extract.py`, `step5_opus.py` to read content from `payload` JSONB with explicit field precedence (e.g. `COALESCE(payload->>'alert_body', summary, '')`). Optionally include title via `(payload->>'alert_title') || '\n\n' || (payload->>'alert_body')` since Step 1's model prompt benefits from title context.
- Update unit tests (`tests/test_step1_triage.py`, `test_step2_resolve.py`, `test_step3_extract.py`, `test_step5_opus.py`) + the shared fixture in `test_status_check_expand_migration.py` to insert via the real producer shape (`payload`) instead of a `raw_content` column that doesn't exist.
- Add an end-to-end integration test that inserts via `bridge.map_alert_to_signal()` then runs Step 1 — this gap is exactly what let the drift ship unnoticed.
- **Recovery:** reset the 15 stranded rows: `UPDATE signal_queue SET status='pending', started_at=NULL WHERE stage='triage' AND status='processing' AND started_at IS NOT NULL AND triage_summary IS NULL;` after the fix deploys. Write-path — not a B2 action, but flag it so AI Head / Director authorization is captured.

Not XS because the fix spans 4 consumer files and 5 test modules, and because the recovery UPDATE is a Tier B authorized write. Not M because the per-site change is mechanical.

---

## Proposed next brief

**`STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1`** — redirect all `SELECT raw_content FROM signal_queue` sites (Steps 1/2/3/5) to read from `payload` JSONB (`alert_body` primary, `summary` fallback), update affected tests to insert via producer shape, add bridge→Step 1 integration test, and include a recovery UPDATE to reset 15 stranded rows to `status='pending'` for reprocessing.

Suggested sequencing inside that brief: (1) add failing integration test that bridges 1 alert and runs Step 1 end-to-end; (2) fix `_fetch_signal` in Step 1, watch test go green; (3) apply same pattern to Steps 2/3/5; (4) migrate test fixtures off `raw_content`; (5) ship recovery UPDATE with explicit Director auth logged in `actions_log.md`.

---

## Side observations (not blocking)

- **N1.** The Step 1 docstring flagged the `raw_content` assumption as a known risk ("we'll see the failure at the SQL level and can adjust in a follow-up"). The follow-up never happened; the assumption became a production blocker once the bridge started inserting rows on 2026-04-20 16:40. Suggest the fix brief capture this in `tasks/lessons.md` — lesson class: "anticipated risks in docstrings must ship with a tracking ticket, not just a comment."
- **N2.** The test fixture at `tests/test_status_check_expand_migration.py:275,295,313` inserts `raw_content` directly — a green test against a schema that doesn't exist in production. This is the second-order root cause of why drift shipped. Recommend the fix brief add a schema-conformance assertion (test inserts must use only columns present in `information_schema.columns` at fixture-DB boot).
- **N3.** Good news: the `emit_log` on catch-all in `pipeline_tick.py:359-365` made this diagnostic trivial — 15 ERROR rows, one per stuck signal, with the exact SQL. Silent-swallow case (c) was ruled out in minutes. This is the pattern to keep.
- **N4.** Recovery UPDATE is safe to run multiple times (idempotent on the `triage_summary IS NULL` guard). A single row that accidentally completed triage before the fix deploys won't be reset back to pending.

---

## Next cycle

Closing tab per standing instruction #9. AI Head owns: (a) writing `STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1` brief, (b) dispatching to B1 for implementation, (c) queuing me for the eventual review. Cortex T3 Gate 1 is S-effort away once that brief ships.
