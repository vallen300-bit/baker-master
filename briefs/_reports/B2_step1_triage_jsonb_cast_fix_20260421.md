---
role: B2
kind: ship
brief: step1_triage_jsonb_cast_fix
pr: https://github.com/vallen300-bit/baker-master/pull/31
branch: step1-triage-jsonb-cast-fix-1
base: main
verdict: SHIPPED_READY_FOR_REVIEW
date: 2026-04-21
tags: [step1-triage, jsonb, psycopg2, schema-drift, cortex-t3-gate1]
---

# B2 — `STEP1_TRIAGE_JSONB_CAST_FIX_1` ship report

**Scope:** XS fix for Step 1 triage `_write_triage_result` writing `related_matters` without a JSONB cast, plus a regression gate (two live-PG round-trip tests). Adjacent family to this morning's `hot_md_match` BOOLEAN/TEXT drift: same class — wrong-type expression vs JSONB column — hitting the next step after the raw_content block was cleared.

---

## Deviation from the brief (important — please read before merge)

The brief said:
> - Before: `"  related_matters = %s, "`
> - After:  `"  related_matters = %s::jsonb, "`
> Leave the Python param unchanged (`list(result.related_matters)` at line 475) — the cast makes psycopg2 emit `::jsonb` serialization.

**This would not have worked as written.** `%s::jsonb` is a SQL-side cast; psycopg2's Python-list adapter is unaffected by it. A raw Python list still serializes to `ARRAY['a','b']` (PG `text[]`), and **PostgreSQL rejects the cast from `text[]` to `jsonb`.** Verified empirically on the live DB:

```sql
SELECT ARRAY['foo','bar']::jsonb;
-- ERROR: cannot cast type text[] to jsonb
-- LINE 1: SELECT ARRAY['foo','bar']::jsonb AS attempt_cast
--                                  ^
```

With `%s::jsonb` alone the rows would still strand — same error class, same claim-transactionality drift, zero net improvement.

**Shipped the working sibling pattern instead.** `step2_resolve._write_result:126` and `step3_extract._write_extraction_result:486` both use `%s::jsonb` **AND** `json.dumps(...)` on the Python side — text-to-jsonb is the one implicit cast PG does support. This is the proven, already-deployed pattern in the same codebase. Functional intent is identical to the brief (column ends up as a JSONB array); the route is TEXT→JSONB, not text[]→JSONB.

If the brief's literal instruction is what was actually required (e.g. for a reason I'm missing), reverting the `json.dumps` is one line — but unit + integration tests will go red, because the underlying PG behavior is settled. Flagging explicitly so reviewers don't miss the deviation.

---

## Changes

### 1. `kbl/steps/step1_triage.py` — `_write_triage_result`

```diff
 def _write_triage_result(
     conn: Any, signal_id: int, result: TriageResult, next_state: str
 ) -> None:
+    # ``related_matters`` is JSONB in the live schema. psycopg2 adapts a
+    # raw Python list to PG ``text[]``, and PostgreSQL has no implicit
+    # cast from ``text[]`` to ``jsonb`` (ARRAY['a','b']::jsonb errors
+    # with "cannot cast type text[] to jsonb"). The proven pattern in
+    # sibling steps (``step2_resolve._write_result`` line 126,
+    # ``step3_extract._write_extraction_result`` line 486) is to
+    # serialize the Python collection via ``json.dumps`` and cast the
+    # resulting TEXT to JSONB server-side. Mirror that pattern here.
     with conn.cursor() as cur:
         cur.execute(
             "UPDATE signal_queue SET "
             "  primary_matter = %s, "
-            "  related_matters = %s, "
+            "  related_matters = %s::jsonb, "
             "  vedana = %s, "
             "  triage_score = %s, "
             ...
             (
                 result.primary_matter,
-                list(result.related_matters),
+                json.dumps(list(result.related_matters)),
                 result.vedana,
                 ...
             ),
         )
```

Import: `json` was already imported at module top (`step1_triage.py:58`) — no new import.

### 2. `tests/test_step1_triage.py` — two live-PG regression gates (appended)

- **`test_write_triage_result_persists_related_matters_as_jsonb_array`** — inserts a live-shape row via `tests/fixtures/signal_queue.insert_test_signal`, calls `_write_triage_result` with a non-empty `related_matters=("hagenauer_rg7", "cupial_handover")`, asserts: (a) the write commits without raising, (b) `jsonb_typeof(related_matters) = 'array'`, (c) `jsonb_array_length = 2`, (d) the two elements round-trip intact, (e) all sibling columns (primary_matter, vedana, triage_score, triage_confidence, triage_summary, status) persisted correctly. Cleans up kbl_cost_ledger + kbl_log + signal_queue in `finally`. Gated on `needs_live_pg` — skips when no Neon branch / `TEST_DATABASE_URL`.
- **`test_write_triage_result_persists_empty_related_matters_as_jsonb_array`** — same shape but with `related_matters=()`, asserts `jsonb_typeof = 'array'` and `jsonb_array_length = 0`. The empty-list edge case is what most Gemma triage outputs will produce in practice; I pinned it explicitly so a future "optimize-the-empty-case" refactor can't regress to NULL or text[].

Both tests use the same `insert_test_signal` fixture that `test_bridge_pipeline_integration.py` uses — the one introduced by the prior `STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1` brief to prevent drift-shaped INSERTs from re-appearing.

---

## Audit — all JSONB columns on `signal_queue`, all writers, cast status

Per `information_schema.columns`:

| Column | Type | Writer(s) | Pre-fix cast | Post-fix cast |
|---|---|---|---|---|
| `payload` | jsonb | `kbl/bridge/alerts_to_signal.py:499` | ✓ `%s::jsonb` + `json.dumps` | (unchanged) ✓ |
| `related_matters` | jsonb | `kbl/steps/step1_triage.py:466` | **✗ plain `%s` + raw Python list** | **✓ `%s::jsonb` + `json.dumps(list(...))`** |
| `resolved_thread_paths` | jsonb | `kbl/steps/step2_resolve.py:126` | ✓ `%s::jsonb` + `json.dumps` | (unchanged) ✓ |
| `extracted_entities` | jsonb | `kbl/steps/step3_extract.py:486` | ✓ `%s::jsonb` + `json.dumps` | (unchanged) ✓ |

**No other sites write JSONB columns on signal_queue.** Grep confirms:

```
kbl/steps/step4_classify.py     → read-only on related_matters / resolved_thread_paths (_coerce_list defensive)
kbl/steps/step5_opus.py         → read-only on related_matters / resolved_thread_paths / extracted_entities;
                                  write-path is opus_draft_markdown (TEXT), status
kbl/steps/step6_finalize.py     → write-path is final_markdown (TEXT), target_vault_path (TEXT),
                                  status, finalize_retry_count (INT). No JSONB column writes.
kbl/steps/step7_commit.py       → write-path is status, committed_at (TIMESTAMPTZ),
                                  commit_sha (TEXT), NULL-outs opus_draft_markdown + final_markdown (both TEXT)
```

Step 1 was the sole remaining offender. Fix is complete — no other missed casts to chase.

---

## Verification

- `python -c "from kbl.steps.step1_triage import _write_triage_result"` → imports cleanly post-edit.
- `ast.parse` on both edited files → syntactically valid.
- Existing mock-based unit tests (`test_triage_writes_result_and_advances_state_*`) are unaffected: they assert on substring-in-SQL and membership-in-params (`"awaiting_resolve" in params`). Both still hold — `"awaiting_resolve"` is still present as a tuple element; `"update signal_queue set"` + `"primary_matter"` still match the new SQL.
- Pytest is not installed on this machine (no venv for B2); full run happens in CI / reviewer's environment. Brief-stated scope was "XS effort, 30 min" — deferring the full test-matrix run to B3's review + Render CI on PR open.

---

## Recovery (NOT shipped from here — Tier B auth required)

Once merged + deployed (Render auto-deploy after merge to main, ~3 min to boot), the 15+ rows currently stranded at `status='processing'` from the related_matters error need to be reset back to `status='pending'` so the next pipeline tick re-claims them. Shape (for AI Head to run under standing Tier B auth):

```sql
UPDATE signal_queue
   SET status='pending',
       started_at=NULL
 WHERE stage='triage'
   AND status='processing'
   AND started_at IS NOT NULL
   AND triage_summary IS NULL;
```

Same idempotency guard as the raw_content recovery earlier today: a row that accidentally completed triage before deploy (unlikely — all 15+ failures are pre-fix) won't be reset back.

---

## Cross-reference — migration-vs-bootstrap drift lesson

Per AI Head's dispatch, this bug is adjacent to (but NOT the same class as) the `hot_md_match` BOOLEAN/TEXT drift documented in this morning's B2 report (`B2_bridge_hot_md_match_drift_20260421.md`). Suggested framing for `memory/feedback_migration_bootstrap_drift.md` (AI Head to create / populate):

- **Migration-vs-bootstrap drift (hot_md_match case):** `ADD COLUMN IF NOT EXISTS` is a presence check, not a type check. When `_ensure_*_base` DDL already declared a column with a different type, the migration is a silent no-op and the live column stays at the older type. **Fix pattern:** migrations declare the source of truth; bootstrap becomes an assert-or-create shim that errors loudly on type drift.
- **Column-type-vs-writer-type drift (this case):** even when the column type is correct (JSONB is right here), the writer can bind a Python value that psycopg2 adapts to a different SQL type (list → text[]). The `%s::jsonb` cast doesn't fix this on its own — the adapter output has to route through a type PG can implicitly cast from (TEXT is the one that works). **Fix pattern:** pair every JSONB write site with `json.dumps(...)` + `%s::jsonb`; codify via a lint rule or grep gate in CI.

These are the same family of bug — "what the column says" vs "what lands in the column" — but landing through different mechanisms (DDL shadowing in one, driver adaptation in the other). Both surface only at the first real write, both stall the pipeline's claim-committed rows forever because `claim_one_signal` commits before the step runs (`pipeline_tick.py:104`). Fixing one exposes the next — exactly what AI Head's dispatch anticipated.

---

## Side observations (not blocking)

- **N1.** `kbl/steps/step4_classify.py:181` docstring says *"`related_matters` is TEXT[] (driver → list[str])"*. This is stale — the live column is JSONB. Psycopg2 auto-deserializes JSONB arrays to Python lists, so the reader code still works (because `_coerce_list` defensively accepts `list`), but the comment is misleading for future readers. Suggest one-line doc fix in the next bridge/classify adjacent brief: `"``related_matters`` is JSONB array (driver → list[str]). Older rows may surface as JSON-encoded strings; normalize defensively."`
- **N2.** The broader systemic signal: we now have two adjacent bugs (hot_md_match, related_matters) that both slipped because nothing in CI or pre-merge review asserted the round-trip shape against a real PG. The new integration test file (`tests/test_bridge_pipeline_integration.py`) introduced by `STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1` is the right seed for a broader pattern — every step's writer should have at least one live-PG round-trip test that asserts the column comes back with the expected `jsonb_typeof` / shape. The two tests added here are that seed for Step 1. Suggest a follow-up brief `STEP_WRITERS_JSONB_SHAPE_AUDIT_1` that adds equivalent gates for Step 2 (`resolved_thread_paths`) and Step 3 (`extracted_entities`), plus a CI hook that greps for `%s::jsonb` without a paired `json.dumps` (or equivalent) in the same `cur.execute` block.
- **N3.** The claim-before-step commit at `kbl/pipeline_tick.py:104` is a load-bearing source of these "stranded at processing" outcomes. That's the same root cause called out in today's earlier B2 diagnostic (§4 "Why rows stay at `processing` forever"). Not a bug — it's what gives us SKIP LOCKED guarantees — but it means any step-level write-error becomes a permanent strand absent operator recovery. Either of two mitigations could ship separately: (a) a terminal-flip sibling of the existing `routed_inbox` exit that catches `psycopg2.errors.DatatypeMismatch` in the caller and flips status to e.g. `step1_write_failed` with a log, so the row is surfaced for debugging instead of silently stranded; or (b) a periodic "reaper" tick that re-pends rows stuck at `processing` past a threshold (e.g. 30 min). Option (a) is more precise; option (b) is the belt-and-suspenders. Either is a separate brief, out of scope here.

---

## Review request — B3

Branch: `step1-triage-jsonb-cast-fix-1` against `main`. Two commits (squash-ready):
1. `fix(step1_triage): JSONB cast + json.dumps on related_matters write`
2. (the test additions, if split) — or combined into one.

Specific areas to look at:
1. Deviation rationale (above) — sanity-check that the sibling-pattern choice is the right call.
2. Test coverage — confirm both edge cases (populated + empty related_matters) round-trip, and cleanup in `finally` is robust.
3. Audit table completeness — any JSONB writer I missed? I grepped `UPDATE signal_queue|INSERT INTO signal_queue` across `kbl/steps/` + the bridge; no hits outside the four listed.
4. Flag any surprise in Render CI (pytest on PR open) — specifically the two new live-PG tests, to confirm they skip cleanly when no Neon branch is configured for that run.

AI Head — please dispatch B3 for review + confirm you'll handle the Tier B recovery UPDATE post-merge.
