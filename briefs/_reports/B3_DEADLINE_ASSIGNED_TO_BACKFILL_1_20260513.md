# Ship report — DEADLINE_ASSIGNED_TO_BACKFILL_1 (scheduled-tasks v1.5)

**Builder:** b3
**Brief:** `briefs/BRIEF_DEADLINE_ASSIGNED_TO_BACKFILL_1.md`
**Branch:** `b3/deadline-backfill-and-nits-1`
**Date:** 2026-05-13
**Status:** PR open, awaiting review.

---

## Scope shipped

**Scope A — `assigned_to` backfill**
- Part A1: `scripts/backfill_assigned_to.py` (NEW, ~360 LOC) — dry-run-default backfill with 4 safety rails (`--apply` flag + ratified-mapping file + 24h staleness + `BAKER_BACKFILL_DRY_RUN_ONLY=1` env kill-switch).
- Part A2: dry-run executed; output captured at `briefs/_reports/B3_backfill_assigned_to_20260513T064444Z.md`.
- Part A3: vault doc appended — `baker-vault:_ops/processes/deadline-system-contract-v1.md` v1.5 execution log.

**Scope B — PR #197 2nd-pass nits**
- Part B1 (MED1): `triggers/vault_scanner.py:1039` — replaced `now.time() < datetime.min.time().replace(hour=6)` with `now.hour < 6`. Refactor-safe, tz-agnostic.
- Part B2 (MED2): `triggers/vault_scanner.py:789` — parameterized `LIMIT 4` → `LIMIT %s` bound to `EMPTY_STREAK_THRESHOLD + 1`. One-shot guarantee preserved if threshold is bumped.
- Part B3 (LOW3): `triggers/vault_scanner.py:495` — truncated `dm_error_msg` to `[:500]` chars.
- **Part B4 (LOW4): REVERTED to no-DDL.** `migrations/20260513_scanner_run_log.sql` was merged + auto-deployed via 705de3f (PR #197) before `VAULT_SCANNER_ENABLED=false` kill-switch was set. Migration runner applies at startup regardless of the scheduler flag, so the file is treated as applied. Per brief pre-flight #3 + CLAUDE.md hard rule on applied-migration edits, B4 deferred to v2 (doc-only commit). The B3 app-layer truncation (500-char) is the operative protection.
- Part B5: tests T17 + T18 + T19 added (16 → 19).

---

## Hard ship gate verification

### 1. Literal pytest output (19/19 PASS)

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0 -- /Users/dimitry/bm-b3/.venv-b3/bin/python3.12
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b3
plugins: langsmith-0.7.33, anyio-4.13.0
collecting ... collected 19 items

tests/test_vault_scanner.py::test_1_empty_vault PASSED                   [  5%]
tests/test_vault_scanner.py::test_2_mohg_task_writes_today_and_sends_dm PASSED [ 10%]
tests/test_vault_scanner.py::test_3_malformed_frontmatter_skipped PASSED [ 15%]
tests/test_vault_scanner.py::test_4_overdue_critical_triggers_urgent_dm PASSED [ 21%]
tests/test_vault_scanner.py::test_5_rate_cap_blocks_second_consolidated_dm PASSED [ 26%]
tests/test_vault_scanner.py::test_6_marker_file_and_prune PASSED         [ 31%]
tests/test_vault_scanner.py::test_7_idempotent_double_call PASSED        [ 36%]
tests/test_vault_scanner.py::test_8_db_unavailable_degrades_gracefully PASSED [ 42%]
tests/test_vault_scanner.py::test_path_traversal_symlinked_desk_rejected PASSED [ 47%]
tests/test_vault_scanner.py::test_path_traversal_dotdot_desk_rejected PASSED [ 52%]
tests/test_vault_scanner.py::test_9_scanner_run_log_row_on_success PASSED [ 57%]
tests/test_vault_scanner.py::test_10_scanner_run_log_row_on_dm_failure PASSED [ 63%]
tests/test_vault_scanner.py::test_11_empty_streak_sentinel_one_shot PASSED [ 68%]
tests/test_vault_scanner.py::test_12_today_files_prune_90_day_retention PASSED [ 73%]
tests/test_vault_scanner.py::test_13_unassigned_bucket_in_dm PASSED      [ 78%]
tests/test_vault_scanner.py::test_14_recovery_prefix_then_cleared PASSED [ 84%]
tests/test_vault_scanner.py::test_17_startup_catchup_hour_gate PASSED    [ 89%]
tests/test_vault_scanner.py::test_18_empty_streak_limit_parameterized PASSED [ 94%]
tests/test_vault_scanner.py::test_19_dm_error_msg_truncated_to_500 PASSED [100%]

============================== 19 passed in 0.07s ==============================
```

### 2. `scripts/check_singletons.sh` PASS

```
OK: No singleton violations found.
```

### 3. Dry-run output

```
2026-05-13 08:44:44,281 DRY RUN complete: 69 total | M=0 A=0 U=69 → /tmp/backfill_assigned_to_proposal_20260513T064444Z.md
/tmp/backfill_assigned_to_proposal_20260513T064444Z.md
```

Output file preserved at `briefs/_reports/B3_backfill_assigned_to_20260513T064444Z.md` (full file with 69 unmapped rows).

### 4. Bucket counts: M=0, A=0, U=69

**Surfacing finding for AH1/Director.** All 69 candidate rows have `matter_slug` NULL — the desk-matter-map cannot help. Direct DB check (independent of script):

```
active total=72  matter_slug populated=3  assigned_to populated=3
  matter_slug=None                              count=69
  matter_slug='Financing Vienna & Baden-Baden'  count=1
  matter_slug='mo-vie-am'                       count=1
  matter_slug='Oskolkov-RG7'                    count=1
```

The 3 already-populated rows are excluded from the candidate set (`WHERE assigned_to IS NULL OR empty`), so they don't appear in the proposal.

**Implication:** matter_slug-driven backfill cannot raise assignment rate this run. The proposal surfaces the upstream-extraction gap explicitly. Director ratification path likely requires manual desk attribution per row, or deferring backfill until extractor improvements land. The scanner's synthetic `_unassigned` bucket (Amendment E) remains the operational safety net.

### 5. Part B4 reverted note

Per ship gate #5: Part B4 doc-comment was **reverted** — migration `20260513_scanner_run_log.sql` was applied to prod by Render auto-deploy of `705de3f` before the scheduler kill-switch went on. App-layer 500-char truncation (B3) is the operative protection. v2 doc-only commit is the path forward.

---

## Files changed (baker-master)

| File | Change | Notes |
|---|---|---|
| `triggers/vault_scanner.py` | mod (-4 / +5 LOC) | B1+B2+B3 (≤15 LOC budget) |
| `tests/test_vault_scanner.py` | mod (+84 LOC) | T17 + T18 + T19 |
| `scripts/backfill_assigned_to.py` | new (~360 LOC) | dry-run-default, 4 safety rails |
| `briefs/_reports/B3_backfill_assigned_to_20260513T064444Z.md` | new | dry-run output preservation |
| `briefs/_reports/B3_DEADLINE_ASSIGNED_TO_BACKFILL_1_20260513.md` | new | this report |
| `migrations/20260513_scanner_run_log.sql` | **NO CHANGE** | B4 reverted (applied-migration rule) |

## Files changed (baker-vault)

| File | Change | Notes |
|---|---|---|
| `_ops/processes/deadline-system-contract-v1.md` | append (+28 LOC) | v1.5 execution log section |

---

## Next steps (out of b3 scope)

- **Director ratification ask:** Director reads the proposal file at `briefs/_reports/B3_backfill_assigned_to_20260513T064444Z.md`. Bucket M is empty → no auto-apply rows. Bucket U=69 is the manual-review backlog. Director-ratification flow on this empty-M result needs an AH1 framing decision (manual per-row ratification path, or deferral until extractor improves).
- AH1 drives `--apply` step (if any) once ratification lands. b3 does not run `--apply` per brief.
- Render env-var flip back to `VAULT_SCANNER_ENABLED=true` is AH1's step after ratified apply (or after Director ratifies "defer apply, scanner runs with U bucket").

---

## Coordination

- `mandatory_2nd_pass: FALSE` per brief — Scope B fixes <50 LOC on already-2nd-pass-cleared code, Scope A script is local-runtime utility with no external surface.
- `/security-review` not required per brief §security_review (no new external surface, parameterized SQL throughout, dry-run-default + 4 safety rails on apply path).
- Bus-post to `lead` with topic `ship/DEADLINE_ASSIGNED_TO_BACKFILL_1` per brief §ship_report_to.
