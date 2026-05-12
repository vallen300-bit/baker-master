# BRIEF: DEADLINE_ASSIGNED_TO_BACKFILL_1 — desk attribution backfill + 4 PR #197 2nd-pass nits

## Context

Scheduled-tasks v1.5 — direct follow-up to v1 dispatch. Two bundled scopes:

**Scope A — `deadlines.assigned_to` backfill.** Brief 3 (HARD_DEADLINE_AUDIT_V1, b4) Q5 returned **P=2.9%** (2 out of 69 active deadlines have `assigned_to` populated). The `vault_scanner_daily` job from Brief 2 (APSCHEDULER_VAULT_SCANNER_V1, b3) uses `WHERE assigned_to = <desk>` to partition deadlines per desk; at 2.9% population, scanner would dump ~65 deadlines into the synthetic `_unassigned` bucket on day-one Director DM — functional but defeats the per-desk surface. Triggered by audit doc `baker-vault 32e42ec`; ratified by Director 2026-05-13 (this session).

**Scope B — PR #197 2nd-pass nits.** feature-dev:code-reviewer 2nd-pass returned PASS-WITH-NITS on PR #197 v0.1: 0 CRITICAL, 0 HIGH, 2 MEDIUM, 2 LOW. Per SKILL.md PASS-WITH-NITS = gate cleared; nits queued as fast-follow. Bundled here because they touch the same files (`triggers/vault_scanner.py`, `migrations/20260513_scanner_run_log.sql`, `tests/test_vault_scanner.py`).

**Deploy gate**: `VAULT_SCANNER_ENABLED=false` set on Render (commit anchor `31158996`, deploy `dep-d81rmlhkh4rs73bt354g`). Flip back to `true` only after this brief lands AND Director ratifies the bulk-UPDATE script output (Scope A Part 4 below).

## Estimated time: ~3h
## Complexity: Medium
## Prerequisites: PR #197 merged (✅ `705de3f`). Baker DB reachable. `baker-vault/_ops/agents/_desk-matter-map.yml` exists and current.

---

# SCOPE A — `assigned_to` backfill

## Part A1: New script `scripts/backfill_assigned_to.py`

**Purpose:** dry-run-by-default tool that proposes `deadlines.assigned_to` values from `matter_slug` via the canonical desk-matter map, surfaces unmapped rows for Director review, and (on `--apply` with Director-ratified mapping file) executes bulk UPDATE.

**Behavior:**

1. **Load canonical maps**:
   - `baker-vault/_ops/agents/_desk-matter-map.yml` → dict[desk → list of matter_slugs owned]
   - `baker-vault/slugs.yml` → canonical slugs + alias resolution (use the existing loader pattern from `kbl/slug_registry.py`)

2. **Query active deadlines without `assigned_to`**:
   ```sql
   SELECT id, description, due_date, priority, matter_slug, severity
   FROM deadlines
   WHERE status = 'active'
     AND (assigned_to IS NULL OR assigned_to = '')
   ORDER BY id
   LIMIT 500;
   ```
   (LIMIT 500 belt-and-suspenders; brief Q5 says total is 67 — safe.)

3. **Classify each row** into three buckets:
   - **Bucket M (Mapped)** — `matter_slug` is non-null AND resolves to canonical AND that canonical is owned by exactly one desk per the desk-matter map. Propose `assigned_to = <desk>`.
   - **Bucket A (Ambiguous)** — `matter_slug` resolves to canonical but the map shows >1 desk ownership. Propose nothing; surface in review queue.
   - **Bucket U (Unmapped)** — `matter_slug` is null OR doesn't resolve OR canonical not in desk-matter map. Propose nothing; surface in review queue.

4. **Dry-run output (default mode)**: write `/tmp/backfill_assigned_to_proposal_<UTC-ts>.md` with three sections (M / A / U) and one row per deadline. Each row: `id | description (truncated 80c) | matter_slug raw → canonical | proposed assigned_to | bucket-reason`. The M-section is the "auto-apply" set; the A and U sections are manual-review.

5. **Director review surface**: the dry-run output is opened in Cowork (Director reads); Director ratifies the M-section block as-is OR replies with adjustments. Director's response becomes the ratified-mapping file at `/tmp/backfill_assigned_to_ratified_<UTC-ts>.md` (same shape as proposal).

6. **`--apply` mode**: takes the ratified-mapping file path as argument. For each row in the file with a non-empty `proposed assigned_to`, run:
   ```sql
   UPDATE deadlines
   SET assigned_to = %s,
       updated_at = NOW()
   WHERE id = %s
     AND (assigned_to IS NULL OR assigned_to = '');
   ```
   (The second AND-clause is idempotency belt — re-running won't clobber rows already assigned in the meantime.)
   Log every UPDATE to stdout + a summary block at the end (rows affected, rows skipped).

7. **Safety rails**:
   - Default mode is DRY-RUN. `--apply` requires explicit flag.
   - `--apply` refuses to run if any row in the input file is missing `proposed assigned_to`.
   - `--apply` refuses to run if the mapping file is older than 24h (staleness guard).
   - `BAKER_BACKFILL_DRY_RUN_ONLY=1` env-var override blocks `--apply` entirely (kill switch).

**Imports / pattern**: mirror `scripts/run_kbl_eval.py` shape (existing baker-master tool). Use the canonical DB connection from `models/deadlines.py:get_conn()` + `put_conn()`. Wrap UPDATE in try/except with `conn.rollback()` on error (Python backend rule).

## Part A2: Execute the dry run + Director ratification surface

After Part A1 script lands:

1. Run `python3 scripts/backfill_assigned_to.py` (no args = dry run).
2. The output file path is printed; b3 pastes the file content into the ship report as a fenced block (truncate to first 100 rows if >100, with a "+N more" tail line).
3. Ship report ends with an explicit Director-ratification ask. AH1 will surface the proposal in chat for Director's M-section ratification (NOT B-code's job to chase Director).

**Do NOT** run `--apply` from b3. Director-ratification gate sits between dry-run and apply; AH1 drives the apply step after Director ratifies.

## Part A3: Update audit doc

Append a new section to `baker-vault/_ops/processes/deadline-system-contract-v1.md`:

```markdown
## v1.5 backfill — execution log (2026-05-13)

- Dry-run output: `/tmp/backfill_assigned_to_proposal_<UTC-ts>.md` (preserved at `briefs/_reports/B3_backfill_assigned_to_<ts>.md`)
- Bucket counts: M=<N>, A=<N>, U=<N>
- Director ratification: <commit-hash or "pending">
- Bulk UPDATE log: <commit-hash or "pending">
- Post-backfill rate: P=<new %> (X / 67 active populated)
```

b3 fills in the bucket counts + the dry-run preservation path. The ratification + bulk-UPDATE + post-rate fields stay placeholder until AH1 executes them.

---

# SCOPE B — PR #197 2nd-pass nits (4 fixes)

## Part B1 (MED 1): `startup_catchup` time comparison — fragility fix

**Current** (`triggers/vault_scanner.py:1039`):
```python
if now.time() >= datetime.min.time().replace(hour=6):
    ...
```

**Issue:** `now.time()` strips tzinfo from an aware datetime; works today but fragile to refactor that passes a naive `now`.

**Fix:**
```python
if now.hour < 6:
    return False
```

Replace the comparison with hour-only check. Simpler, refactor-safe, semantically identical for the current call sites.

## Part B2 (MED 2): `_empty_streak_count` LIMIT vs threshold constant

**Current** (`triggers/vault_scanner.py:787–791`, hardcoded):
```sql
SELECT ... LIMIT 4;
```
while `EMPTY_STREAK_THRESHOLD = 3` is a named module-level constant.

**Issue:** If `EMPTY_STREAK_THRESHOLD` is ever bumped (e.g., to 5 to reduce alert noise), the LIMIT silently caps the count too early — one-shot guarantee silently breaks.

**Fix:**
```python
cur.execute("""
    SELECT COUNT(*) AS empty_streak
    FROM scanner_run_log
    WHERE run_ts >= NOW() - INTERVAL '3 days'
      AND tasks_found = 0
      AND deadlines_found = 0
      AND error_count = 0
    LIMIT %s;
""", (EMPTY_STREAK_THRESHOLD + 1,))
```

Parameterize the LIMIT. Threshold + 1 because we need to detect "≥ threshold" — early-stop after threshold+1 rows is enough.

## Part B3 (LOW 3): `dm_error_msg` truncation

**Current** (`triggers/vault_scanner.py:493–496`):
```python
dm_error_msg = f"{type(e).__name__}: {e}"
return False, dm_error_msg
```

**Issue:** If `e` is a large exception (HTTP response body surfaced via Slack SDK), `dm_error_msg` in `scanner_run_log` could be unbounded. Schema is `TEXT` so no DB error, but observability dashboards get garbage.

**Fix:**
```python
dm_error_msg = f"{type(e).__name__}: {e}"[:500]
return False, dm_error_msg
```

Truncate at 500 chars (matches `notes` truncation pattern at line 1517).

## Part B4 (LOW 4): `dm_error_msg` column documentation

LOW 4 was "column unbounded TEXT." Covered by B3 truncation. **No DDL change** — adding a length constraint in a migration on an existing column would touch the migration-edit-applied lock pattern (Lesson #X: editing applied migrations forbidden without correction + lock refresh).

Instead, add an in-line comment in `migrations/20260513_scanner_run_log.sql` documenting the app-layer truncation:

```sql
-- dm_error_msg / notes are TEXT columns; app-layer truncates to 500c / 1000c
-- respectively before INSERT. See triggers/vault_scanner.py:_send_dm_with_capture
-- (B3 fix) and _record_run_log (notes truncation).
```

If this is a NEW migration (b3's v0.1 introduction), inline-edit the comment IS allowed; the migration hasn't been applied to prod yet because of the kill switch. Verify with `git log` + `applied_migrations.lock` before editing — if it shows applied, revert to "no change" and capture as a v2 doc-only commit instead.

## Part B5: Test plan additions

Add to `tests/test_vault_scanner.py`:

- **T17**: `startup_catchup` returns False at 05:59 UTC, returns True at 06:00 UTC (both naive and aware `now` inputs).
- **T18**: `_empty_streak_count` query uses parameterized LIMIT — manually bump `EMPTY_STREAK_THRESHOLD` in the test to 5; assert LIMIT bind value is 6.
- **T19**: `_send_dm_with_capture` truncates `dm_error_msg` to exactly 500 chars when exception has a 1000-char body.

Test count grows 16 → 19. Update hard ship gate.

---

## Files to modify / create

**baker-master:**
- `triggers/vault_scanner.py` — MED 1, MED 2, LOW 3 fixes (≤15 LOC delta)
- `migrations/20260513_scanner_run_log.sql` — LOW 4 in-line comment (only if migration not yet applied; verify first)
- `tests/test_vault_scanner.py` — add T17, T18, T19
- `scripts/backfill_assigned_to.py` — NEW (~150 LOC)
- `briefs/_reports/B3_DEADLINE_ASSIGNED_TO_BACKFILL_1_<date>.md` — ship report

**baker-vault:**
- `_ops/processes/deadline-system-contract-v1.md` — append v1.5 backfill section (Part A3)

**Do NOT touch:**
- `triggers/embedded_scheduler.py` — APScheduler registration unchanged
- `triggers/scheduler_lease.py` — singleton primitive unchanged
- Other migration files
- Existing scanner tests T1–T16 (only add T17–T19)

---

## Risks + past lessons applied

- **Lesson — applied-migration edit forbidden** (CLAUDE.md hard rule): Part B4's comment add is allowed ONLY if the migration is not yet applied to prod. Verify via `applied_migrations.lock` + `git log` before editing; if applied, revert to "no doc change in v1.5."
- **Lesson #7 — file:line citation verification**: every nit references a specific file:line. Open + verify before fix (line numbers in this brief reflect post-v0.1-fold; b3 may need to re-grep if intermediate work shifts them).
- **Lesson — bulk UPDATE safety**: backfill script is dry-run by default; `--apply` gated on ratified-mapping file + 24h staleness + env-var override. Three safety rails.
- **Lesson #25 — Render env-var silent loss**: AH1 will flip `VAULT_SCANNER_ENABLED=true` back after this brief ships AND ratified Apply runs — NOT b3's job to touch Render.

---

## Hard ship gate

1. Literal `pytest tests/test_vault_scanner.py -v` GREEN — all 19 tests pass (16 existing + 3 new). Output pasted in PR description.
2. `scripts/check_singletons.sh` PASS.
3. `python3 scripts/backfill_assigned_to.py` (no args) runs cleanly, produces a dry-run output file, prints the path. Literal output pasted in ship report (truncate to first 100 rows + "+N more" tail if >100).
4. Bucket counts (M / A / U) from the dry run included in ship report.
5. If Part B4 doc-comment add was reverted (migration applied), note explicitly in ship report.

---

## Out of scope (defer to v2)

- Executing the `--apply` bulk UPDATE — that's AH1's step, gated on Director ratification.
- Renaming `assigned_to` → `desk_slug` (more semantically accurate but breaks all callers — Cortex-era refactor work).
- Removing the `_unassigned` synthetic bucket from the scanner once backfill ships — useful safety net, keep it.
- Multi-desk ownership semantics (Bucket A handling) — manual review for now; structured tooling is v2.

---

## Director ratification anchor

Director "follow your recomends" 2026-05-13 (this session) — covering both Scope A (backfill brief per Brief 3 Q5 trigger) and Scope B (4 nits from PR #197 2nd-pass).

---

## Dispatch coordination

- Builder: **b3** (owns the vault_scanner.py codebase from Brief 2 + has fresh context on the audit doc + 2nd-pass nits).
- Branch: `b3/deadline-backfill-and-nits-1`.
- PR target: baker-master.
- No /security-review trigger (no new external surface; vault_scanner.py changes are quality fixes; backfill script is local-runtime DB write only, no new public endpoint).
- Mandatory 2nd-pass: **FALSE** — bundled fixes are <50 LOC executable changes + a new utility script. Reflects PASS-WITH-NITS gate cleared on the substantive scanner code already.
- Bus-post on completion: `ship/DEADLINE_ASSIGNED_TO_BACKFILL_1` to `lead`.
