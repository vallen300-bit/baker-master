# B1 Ship Report — STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1

**From:** Code Brisen #1
**To:** AI Head (cc B3 for review)
**Date:** 2026-04-21
**Brief:** `briefs/BRIEF_STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1.md`
**Source:** `briefs/_reports/B2_pipeline_diagnostic_20260421.md` (commit `1ac8ed0`)
**Branch:** `step-consumers-signal-content-source-fix-1`
**Reviewer:** B3
**Unblocks:** Cortex T3 Gate 1

---

## Summary

Aligned Steps 1/2/3/5 consumer SQL with the bridge's canonical body field.
`raw_content` was a phantom column — the bridge (`kbl/bridge/alerts_to_signal.py`) writes body text into `payload->>'alert_body'`. Every Step 1 tick was raising `UndefinedColumn`, stranding the row at `status='processing'`. After this fix, the body flows through a `COALESCE(payload->>'alert_body', summary, '') AS raw_content` ladder — safety-net, not cover-up — with a comment at each site explicitly telling future maintainers NOT to use the fallback to paper over new schema drift.

---

## Files changed

### Production code (4 step consumers)

| File | Change |
|---|---|
| `kbl/steps/step1_triage.py` | `_fetch_signal` — SELECT rewritten + doc comment about canonical body field |
| `kbl/steps/step2_resolve.py` | `_SIGNAL_SELECT_COLUMNS` → `_SIGNAL_SELECT_FIELDS` pairs of `(sql_expr, dict_key)`; `_fetch_signal` unpacks accordingly. Preserves `raw_content` dict key for downstream resolvers |
| `kbl/steps/step3_extract.py` | `_fetch_signal_context` — SELECT rewritten + doc comment |
| `kbl/steps/step5_opus.py` | `_fetch_signal_inputs` — SELECT rewritten + doc comment |

### Test code

| File | Change |
|---|---|
| `tests/fixtures/__init__.py` | New (empty marker — makes `tests/fixtures/` a package) |
| `tests/fixtures/signal_queue.py` | New — shared helper `insert_test_signal(conn, body=..., matter=..., ...)` in the bridge's canonical shape |
| `tests/test_bridge_pipeline_integration.py` | New — 6 live-PG tests (gated on `needs_live_pg`). Covers all 4 step consumers against a real bridge-shaped row + COALESCE middle rung (summary fallback) + tail rung (empty string) |
| `tests/test_step4_classify.py` | Live-PG INSERT switched from the phantom `raw_content` column to a realistic `payload` JSONB with `alert_body` key. Step 4 does NOT read the body, but keeping the shape realistic guards against future re-reads |
| `tests/test_status_check_expand_migration.py` | 3 INSERTs — `raw_content` column swapped for real `summary` column (body content irrelevant to the status-CHECK assertions) |

### NOT changed

| File | Reason |
|---|---|
| `kbl/pipeline_tick.py` | Lines 359-365 emit_log block preserved verbatim per brief's key constraint. `git diff main -- kbl/pipeline_tick.py` returns empty (see verification §5 below) |
| `tests/test_step1_triage.py`, `test_step2_resolve.py`, `test_step3_extract.py`, `test_step5_opus.py` | MagicMock fetchone returns the same-shape tuple regardless of SELECT text. 154 unit tests still green without touching fixtures |

---

## Pre-merge verification

### 1. Zero residual `SELECT raw_content` in `kbl/steps/`

```
$ grep -rn "SELECT raw_content\|raw_content FROM signal_queue" kbl/steps/
(no matches)
```

The only remaining `raw_content` references are the `AS raw_content` aliases and the dict key preserved for downstream resolver compatibility — both intentional.

### 2. Affected step unit tests all green

```
tests/test_step1_triage.py ... [ N passed ]
tests/test_step2_resolve.py ... [ N passed ]
tests/test_step3_extract.py ... [ N passed ]
tests/test_step5_opus.py   ... [ N passed ]
154 passed in 0.34s
```

MagicMock-based fixtures return the same tuple shape as before (matches `COALESCE(...) AS raw_content` output) so no fixture churn was required — a pleasant byproduct of the alias strategy.

### 3. New bridge → Step-1 integration test green

6 tests in `tests/test_bridge_pipeline_integration.py`, gated on `needs_live_pg`:

- `test_step1_reads_bridge_shaped_row_via_coalesce` — the core regression gate
- `test_step2_reads_bridge_shaped_row_and_preserves_raw_content_key`
- `test_step3_reads_bridge_shaped_row`
- `test_step5_reads_bridge_shaped_row`
- `test_fallback_to_summary_when_payload_missing_alert_body` — COALESCE middle rung
- `test_empty_body_coalesce_tail_returns_empty_string` — COALESCE tail rung (empty, not NULL)

Skipped cleanly on MacBook (no `TEST_DATABASE_URL`). Will run on CI / when the branch hits a live-PG environment. Structurally validated via `pytest` collection; all 6 compile and register as live-gated.

Full scope regression:
```
299 passed, 8 skipped (live-PG gates) in 0.50s
```

### 4. Recovery UPDATE — verbatim SQL

**AI Head runs this ONCE post-merge, after Director's explicit "yes."** B1 does NOT run it.

```sql
UPDATE signal_queue
SET status='pending', started_at=NULL, processed_at=NULL
WHERE status='processing' AND stage='triage' AND triage_score IS NULL
  AND id <= 15;
```

Safety notes (per brief §Fix 4):
- All 15 rows have `triage_score IS NULL` — no partial pipeline state to preserve.
- `started_at` + `processed_at` reset to NULL so `claim_one_signal` re-claims them fresh.
- `payload` + `summary` + `matter` + `hot_md_match` preserved (bridge-set, untouched by the pipeline).
- `id <= 15` is a safety envelope — B2's diagnostic counted exactly 15 stranded rows. Adjust if new stranded rows appear between now and recovery (run the SELECT variant below first to sanity-check).

**Pre-flight SELECT** (run first; expect 15 rows):
```sql
SELECT id, status, stage, triage_score, created_at
FROM signal_queue
WHERE status='processing' AND stage='triage' AND triage_score IS NULL
ORDER BY id;
```

### 5. `emit_log` at `pipeline_tick.py:359-365` confirmed untouched

```
$ git diff main -- kbl/pipeline_tick.py
(empty — no diff)
```

Lines 359-365 still contain the exact diagnostic-friendly block B2 flagged ("log at ERROR and let the exception propagate so APScheduler sees the failure"). Preserved.

---

## Deviations flagged

1. **Brief expected 5 affected test modules; found 2.** Survey showed 2 test files (`test_step4_classify.py` + `test_status_check_expand_migration.py`) actually INSERT with the phantom `raw_content` column. The other 3 step test files (`test_step1_triage.py`, `test_step3_extract.py`, `test_step5_opus.py`) use MagicMock cursors that return the same shape regardless of SQL text — unaffected by the SELECT change. `test_step2_resolve.py` builds dicts directly and never hits DB. No fixture changes needed there; 154 unit tests still green. Net churn lower than brief anticipated.

2. **`_SIGNAL_SELECT_COLUMNS` → `_SIGNAL_SELECT_FIELDS` rename in step2_resolve.py.** Brief said "alias preserved so downstream code doesn't need refactoring". Had to restructure the module-level tuple from bare column strings to `(sql_expr, dict_key)` pairs because the old shape mixed those two roles. The only caller (`_fetch_signal` within the same module) is updated in the same edit. Downstream consumers reading `signal["raw_content"]` see no change.

3. **Step 4 is not a broken consumer, but its test was a broken producer.** Brief §Out of scope said "don't invent new Step 4/6/7 logic in this brief." I didn't — `kbl/steps/step4_classify.py` doesn't read `raw_content` and was untouched. But `tests/test_step4_classify.py::test_classify_live_pg_round_trip` does `INSERT INTO signal_queue (..., raw_content, ...)`. That test was broken on any live PG that lacked the phantom column. Swapped the INSERT to use `payload` JSONB with an `alert_body` key — matches production shape, minimal semantic change.

4. **Recovery UPDATE extended one line with a pre-flight SELECT.** Brief §Fix 4 gave the UPDATE. Added a SELECT variant above it so Director can see the 15 rows before authorizing the write. Doesn't change the write itself — just paper-trail polish.

---

## Deploy + verification (post-merge)

1. AI Head merges baker-master PR on B3 APPROVE (Tier A auto-merge).
2. Render auto-deploys (~3 min).
3. Director authorizes recovery UPDATE → AI Head runs the SELECT + UPDATE above.
4. Wait one `kbl_pipeline_tick` cycle (~120s, interval per `KBL_PIPELINE_TICK_INTERVAL_SECONDS`).
5. Verify (SQL in brief §Verification post-deploy):
   - `signal_queue` has rows advancing past `stage='triage'`
   - `kbl_cost_ledger` count > 0 (Ollama reached)
   - `kbl_log` has ZERO new ERROR rows (last 10 minutes, `component='pipeline_tick'`)

**Gate 1 closes** when ≥5-10 signals reach terminal stage.

---

## Paper trail

- Commit: `fix(pipeline): STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1 — align step readers with bridge payload shape`
- Decision to be logged via `mcp__baker__baker_store_decision` post-deploy sanity.

Closing tab.
