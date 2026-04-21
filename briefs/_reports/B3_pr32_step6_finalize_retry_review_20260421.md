---
role: B3
kind: review
brief: step6_finalize_retry_column_fix
pr: https://github.com/vallen300-bit/baker-master/pull/32
branch: step6-finalize-retry-column-fix-1
base: main
commits: [6f47e97, 5694536]
ship_report: briefs/_reports/B2_step6_finalize_retry_column_fix_20260421.md
verdict: APPROVE
tier: A
date: 2026-04-21
tags: [step6-finalize, column-drift, self-heal, cortex-t3-gate1, review]
---

# B3 — review of PR #32 `STEP6_FINALIZE_RETRY_COLUMN_FIX_1`

**Verdict: APPROVE.** Tier A auto-merge greenlit. Zero blocking issues, zero gating nits. B2's variant-(a) option choice is correct; the inline self-heal is exactly symmetric with Step 7, and the JSONB/column-existence audit is tight.

---

## Focus items — 6/6 green

### 1. ✅ Inline self-heal pattern is symmetric with Step 7

Compared `step6_finalize.py:361-366` to `step7_commit.py:247-258` directly. Pattern match is exact:

| Concern | Step 7 `_mark_completed` | Step 6 `_fetch_signal_row` (this PR) |
|---|---|---|
| Cursor block | `with conn.cursor() as cur:` | `with conn.cursor() as cur:` |
| Defensive ALTER FIRST | `ADD COLUMN IF NOT EXISTS committed_at TIMESTAMPTZ` (line 253) + `... commit_sha TEXT` (line 257) | `ADD COLUMN IF NOT EXISTS finalize_retry_count INT NOT NULL DEFAULT 0` |
| SELECT/UPDATE SECOND | `UPDATE signal_queue SET ...` after the two ALTERs | `SELECT opus_draft_markdown, ... COALESCE(finalize_retry_count, 0) ...` after the ALTER |
| Same transaction | Yes — caller-owned tx | Yes — caller-owned tx |
| Cross-reference comment | "Matches Step 6's finalize_retry_count pattern" | "matches Step 7's inline `_mark_completed` pattern (lines 247-258)" |

Ordering correctness confirmed: ALTER runs first, SELECT runs second, both in the same cursor block inside the same enclosing transaction.

**DDL-in-transaction safety** (the concern B2 flagged as non-blocking): PostgreSQL treats `ALTER TABLE ADD COLUMN IF NOT EXISTS` as a fully transactional statement. If the caller rolls back after the ALTER has run, the column creation also rolls back — and the next call re-runs idempotently. `IF NOT EXISTS` makes the post-commit case a no-op. Lock cost: `ADD COLUMN ... DEFAULT <const>` on PG 11+ is a metadata-only operation (no table rewrite), so the `ACCESS EXCLUSIVE` lock is held for milliseconds on the first run, zero lock on every subsequent run (short-circuits on `IF NOT EXISTS`). Safe.

### 2. ✅ Belt-and-suspenders — cheap insurance, keep both

The pre-existing `ADD COLUMN IF NOT EXISTS` in `_increment_retry_count` (line 440) stays. That's the right call, and here's why I wouldn't consolidate to a single-source-of-truth:

- **Two entry points** into Step 6 touching `finalize_retry_count`: `_fetch_signal_row` (every call) and `_increment_retry_count` (failure-retry path only). Keeping the ALTER at both sites means **no single-site deletion or ordering change** can re-introduce the UndefinedColumn error.
- **Cost per redundant call after first commit: literally zero.** `IF NOT EXISTS` short-circuits to a metadata check. PG's system catalogs are already hot. Measured in microseconds.
- **Documentation value:** the inline ALTER tells the next engineer reading `_increment_retry_count` that this column isn't formally migrated. Deleting one copy and leaving the other would obscure that rationale at the site the engineer is most likely to read first.

Net: keep both. This is the same defensive-coding pattern as `COALESCE(col, 0)` on the SELECT itself — redundant when the column's default is already `0`, but it costs nothing and survives future schema-default changes. Keep both.

### 3. ✅ Option choice — variant (a) inline is the right trade-off

B2 chose variant (a) inline over (b) formal migration and (c) bootstrap DDL. Each option assessed:

- **(a) inline (shipped):** symmetric with Step 7, preserves the docstring-stated decision to keep `finalize_retry_count` out of the formal migration set (R3 coordination with Step 5), idempotent, one transaction, one line of SQL. ✓
- **(b) formal migration:** would require reversing the in-code rationale at `_increment_retry_count:432-437` ("the retry counter is not part of the Step 6 migration on purpose"). That's an architectural call, not a 45-min fix. Correct to reject here.
- **(c) bootstrap DDL (`_ensure_signal_queue_base` in `memory/store_back.py`):** this is the route that bit `hot_md_match` this morning. Live DB booted with `hot_md_match BOOLEAN` from bootstrap, migration file tried to add it as TEXT, migration was a silent no-op because `ADD COLUMN IF NOT EXISTS` only checks presence (not type). Adding `finalize_retry_count` to the same bootstrap tangle would reintroduce the same drift class. Correct to reject here.

**Long-term question (not blocking):** does the codebase need a proper migration layer (Alembic, flyway, or a home-rolled ordered-SQL runner)? Yes, arguably — four column-drift bugs in one day is a strong signal. But that's a Gate-2 conversation, not a PR #32 redline. The STEP_SCHEMA_CONFORMANCE_AUDIT_1 brief (see §STEP_SCHEMA_CONFORMANCE_AUDIT_1 below) is the right intermediate step: kill the drift class with lint rules first, then revisit the migration-layer question once we know where the audit gaps actually are.

### 4. ✅ Column-existence audit — B2's claim independently verified

Reproduced B2's audit using `mcp__baker__baker_raw_query` against live `information_schema.columns`:

**Every step-writer SET column exists in live schema** except the known target:

| Column | Live? | Referenced by |
|---|---|---|
| `commit_sha` | ✓ | step7 (SET + self-heal ALTER) |
| `committed_at` | ✓ | step7 (SET + self-heal ALTER) |
| `cross_link_hint` | ✓ | step4 SET |
| `extracted_entities` | ✓ | step3 SET |
| `final_markdown` | ✓ | step6 SET |
| `opus_draft_markdown` | ✓ | step5 SET |
| `primary_matter` | ✓ | step1 SET |
| `related_matters` | ✓ | step1 SET (JSONB, post-PR-31) |
| `resolved_thread_paths` | ✓ | step2 SET (JSONB) |
| `status` | ✓ | all steps |
| `step_5_decision` | ✓ | step4 SET |
| `target_vault_path` | ✓ | step6 SET |
| `triage_confidence` | ✓ | step1 SET |
| `triage_score` | ✓ | step1 SET |
| `triage_summary` | ✓ | step1 SET |
| `vedana` | ✓ | step1 SET |
| `started_at` | ✓ | pipeline_tick, recovery UPDATEs |
| **`finalize_retry_count`** | **✗** | step6 SELECT + SET (this PR's self-heal) |

Also confirmed SELECT-only columns all exist: `payload`, `summary`, `stage`, `matter`. No additional drift sites.

**B2's claim stands: `finalize_retry_count` is the sole remaining un-migrated column touched by step writers.**

Minor side-observation (not blocking): `hot_md_match` is still live as BOOLEAN per my query, not TEXT as the migration + bridge code assume. This is exactly B2's flagged "bug #2" from today's column-drift cluster and is not in scope for this PR. Per cluster summary: "Diagnosed (B2 report `e3a4ad8`); fix deferred by AI Head." Remains a separate fix, not a blocker for this PR — but worth re-raising to AI Head once Gate 1 closes, since hot_md_match is currently a silent-type-mismatch ticking clock. The bridge INSERT at `alerts_to_signal.py:497` passes a string into the BOOLEAN column and psycopg2 will either coerce-or-error depending on the value; needs own post-Gate-1 fix.

### 5. ✅ Regression tests — both paths exercised

Verified both tests exercise the intended paths:

**Test 1 — `test_fetch_signal_row_self_heals_missing_finalize_retry_count`:**
- Line 694-698: `ALTER TABLE signal_queue DROP COLUMN IF EXISTS finalize_retry_count` + explicit commit — guarantees drop lands before the test.
- Line 701-707: info_schema assertion that column is actually gone pre-test (not just assumed).
- Line 710-728: INSERT signal + UPDATE the Step 6-required columns (`opus_draft_markdown`, `step_5_decision`, `triage_score`, `triage_confidence`).
- Line 732: the test's fix point: `row = _fetch_signal_row(conn, signal_id)` — this is the call that raised `UndefinedColumn` pre-fix.
- Line 737-744: post-call info_schema assertion that column NOW exists with `data_type='integer'`.
- Line 747-751: returned row assertions: `retry_count == 0`, `triage_score == 55`, `triage_confidence ≈ 0.7`, `step_5_decision == "full_synthesis"`.

**Both the ALTER self-heal path AND the subsequent SELECT are exercised in one call.** The info_schema pre-assertion (column gone) plus post-assertion (column exists + type correct) means the test cannot trivially pass by the column already being present. Strong gate.

**Test 2 — `test_fetch_signal_row_idempotent_when_column_already_exists`:**
- Line 769-774: ensures column exists (ALTER IF NOT EXISTS — no-op if already present).
- Line 776-795: INSERT + pre-set `finalize_retry_count = 2`.
- Line 799-800: **two back-to-back `_fetch_signal_row` calls**. This is the idempotency gate.
- Line 803-805: both calls return `retry_count == 2` (proving ALTER IF NOT EXISTS didn't reset the value on the second call, and the SELECT completed without raising).

Second test is specifically designed to fail if a future dev drops the `IF NOT EXISTS` clause, since `ADD COLUMN finalize_retry_count` (without the guard) would raise `DuplicateColumn` on the second call. Good future-proofing.

**Fixture cleanup in correct FK order** (both tests):
```python
DELETE FROM kbl_cost_ledger WHERE signal_id = %s
DELETE FROM kbl_log WHERE signal_id = %s
DELETE FROM signal_queue WHERE id = %s
```
Child rows first (kbl_cost_ledger, kbl_log both FK to signal_queue), parent last. `conn.close()` reached via `finally` even on mid-test assertion failure.

Local smoke (py3.9 + fallback pytest): `tests/test_step6_finalize.py` → **39 passed, 2 skipped**. The 2 skipped are exactly the new live-PG gates; they SKIP cleanly when `needs_live_pg` can't resolve a URL. Works as designed.

### 6. ✅ No schema changes outside target column

`git diff main...HEAD -- migrations/` returns 0 lines. `git diff --stat main...HEAD` shows 3 files: step6_finalize.py (+16), test_step6_finalize.py (+188), ship report (+188). No migration file added. No other table touched. Per brief constraint.

The in-SQL ALTER is the only DDL change, it's scoped to a single column (`finalize_retry_count`), and it's idempotent (`IF NOT EXISTS`). Clean.

---

## Judgment on `STEP_SCHEMA_CONFORMANCE_AUDIT_1` scope expansion

**Recommendation: endorse the expanded scope.** Draft as a post-Gate-1 brief covering both classes.

Today's four column-drift bugs map cleanly onto two failure mechanisms:

| Class | Bugs today | Detection mechanism |
|---|---|---|
| **Shape drift** (column type right, driver-adapted param type wrong) | related_matters (JSONB column, `list` bound as text[]) | JSONB-shape round-trip test OR grep rule: `%s::jsonb` in SQL without paired `json.dumps` in same `cur.execute` |
| **Existence drift** (column referenced in SQL, column not in live schema) | raw_content (phantom), hot_md_match (type mismatch — BOOLEAN vs TEXT), finalize_retry_count (never migrated) | Boot-time audit: every `<col_name>` token in step SQL exists in live schema OR has a preceding `ADD COLUMN IF NOT EXISTS` in the same module |

Both classes share the same terminal symptom (row stranded at `status='processing'` forever) and the same root cause (`pipeline_tick.claim_one_signal` commits the claim before the step runs). So a single audit that kills both classes is the right level of abstraction.

B2's proposed scope:
- Part 1: JSONB-shape CI lint + per-writer round-trip gate (was the original `STEP_WRITERS_JSONB_SHAPE_AUDIT_1`).
- Part 2 (new): column-existence CI lint + boot-time conformance check.

Both parts land in ~50-100 lines of Python each. Cheap. Worth drafting as a single cohesive brief rather than two fragmented ones.

**Sequencing advice:** draft this brief AFTER Gate 1 closes. The current focus should be getting ≥5-10 signals to terminal stage to validate the pipeline end-to-end; inserting new audit infrastructure now risks adding noise to an already-busy day. Park the expanded brief for AI Head to hand off to B1/B2 tomorrow.

**Additional scope candidate for the same brief (optional, not required):** the `pipeline_tick.claim_one_signal` commit-before-step semantics is the root amplifier for both classes. A simple "reaper" background task that re-pends rows stuck at `status='processing'` past a threshold (e.g. 30 min with no step-result columns populated) would turn a permanent strand into a bounded delay. B2 called this out as side-observation N3 on the PR #31 ship report. Worth including as a section in STEP_SCHEMA_CONFORMANCE_AUDIT_1 or as an adjacent brief (`PIPELINE_TICK_STRANDED_ROW_REAPER_1`). Mild preference for the latter — different file, different concern, cleaner blast radius.

---

## Minor N-nits (non-blocking, for future refs)

**N1.** Module docstring for `kbl/steps/step6_finalize.py` could pick up a one-liner about `finalize_retry_count` being intentionally-inline-self-healed (not formally migrated) so a maintainer skimming the top-of-file doesn't have to read `_increment_retry_count`'s docstring to understand the pattern. Trivial; next bridge-tuning/step-touch brief can sweep it in.

**N2.** The two new tests share ~30 lines of boilerplate (connect → insert → update → `_fetch_signal_row` → cleanup). A future refactor could extract a `_seed_step6_ready_signal` helper alongside `insert_test_signal`. Not worth the churn today; raise if the step-writer audit brief adds more tests and the shared pattern grows past three call sites.

Neither nit is a blocker.

---

## Recommendation

**Tier A auto-merge OK.**

Post-merge sequence (standing Tier A per memory/actions_log.md):
1. Merge PR #32 to main.
2. Render auto-deploys (~3 min).
3. **Run recovery UPDATE** (Tier A standing auth) — B2's ship report §Recovery shape:
   ```sql
   UPDATE signal_queue
      SET status='awaiting_finalize', started_at=NULL
    WHERE stage IN ('finalize', 'opus')
      AND status='processing'
      AND final_markdown IS NULL
      AND opus_draft_markdown IS NOT NULL;
   ```
   Suggest verifying the exact `stage` value on affected rows via a pre-flight SELECT before the UPDATE — older ticks may have varied between `'finalize'`, `'opus'`, or left stage unchanged while flipping status. B2 flagged this; verify live.
4. Watch `signal_queue` for advancement to `stage='committed'` (Step 7 terminal) + `target_vault_path` + `commit_sha` populated.
5. Gate 1 closes when ≥5-10 signals reach terminal stage with both fields populated.

**Post-Gate-1 follow-ups to schedule:**
- `STEP_SCHEMA_CONFORMANCE_AUDIT_1` — expanded scope per B2's proposal, both shape + existence drift.
- `PIPELINE_TICK_STRANDED_ROW_REAPER_1` — optional, separate brief; time-bounded auto-recovery for claim-before-step stranding.
- `hot_md_match` BOOLEAN→TEXT fix — still open (B2's diagnostic from earlier today); re-raise once Gate 1 closes.

---

## Environment notes

- Review done on worktree `/tmp/bm-b3-pr32` against `origin/step6-finalize-retry-column-fix-1@5694536`.
- Live schema audit via `mcp__baker__baker_raw_query` against `information_schema.columns`.
- Local py3.9 + fallback pytest: 39 passed, 2 skipped (the 2 new live-PG gates, as designed).
- Worktree cleanup: `git worktree remove /tmp/bm-b3-pr32 --force` on tab close per §8.

Tab quitting per §8.

— B3
