---
brief_id: STATE_RECONCILER_2
brief: briefs/BRIEF_STATE_RECONCILER_2.md
target_repo: baker-vault
matter_slug: baker-internal
branch: b3/state-reconciler-2
pr: https://github.com/vallen300-bit/baker-vault/pull/98
head_sha: 9c8dc82
predecessor:
  brief: STATE_RECONCILER_1
  pr: https://github.com/vallen300-bit/baker-vault/pull/96
  merge_commit: e289ff4
  followup_pr: https://github.com/vallen300-bit/baker-vault/pull/97
  followup_merge_commit: 6ef117e
trigger_class: LOW
gate_chain_required:
  gate_1_ah2_static: REQUIRED
  gate_2_security_review: REQUIRED
  gate_3_picker_architect: NOT_REQUIRED
  gate_4_2nd_pass_code_reviewer: NOT_REQUIRED
tests: 54 passed (was 45; +9 added per brief; target ≥54)
loc_delta: +474 / -17 across 7 files
opened_at: 2026-05-18T14:33:00Z
bus_post_id: 441
---

# B3 ship report — STATE_RECONCILER_2

## What shipped

Three pre-itemized follow-ups from STATE_RECONCILER_1 round-1 gate-3 verdict
(bus #419 dispatch).

### F1 — schema_version regex re-application cleanup (gate-3 M2)

`_ops/reconciler/state_reconciler.py` `update_frontmatter()` — replaced the
second `UPDATED_FIELD_RE.sub(new_updated_line + "\nschema_version: v1", ...)`
that was re-running the regex against the literal output of the first
substitution with a direct string insert positioned after the new
`updated:` line. Output is byte-identical to the prior path.

**Files touched:** `_ops/reconciler/state_reconciler.py`
(replaced 4 lines of regex with 2 lines of string-slice insert).

### F2 — STATE_RECONCILER_SKIP=1 bypass audit trail (gate-3 M5)

`.githooks/state_reconciler_pre_commit.sh` — the bypass branch now appends
a structured JSON line to `_ops/agents/_scanner-state/reconciler-bypass-log.jsonl`
before returning 0. Schema per brief:

```json
{"ts":"<ISO-8601 UTC>","git_user":"<git config user.email>","branch":"<HEAD>","staged_decision_logs":[...],"commit_msg_excerpt":"N/A on commit-not-yet-created"}
```

`commit_msg_excerpt` is `N/A on commit-not-yet-created` because pre-commit
stage runs before the commit message is finalized.

The path is added to `.gitignore` (same ownership model as `reconciler-*.json`
sentinels — hook owns, never committed).

`_ops/reconciler/nightly_cron.sh` extended with a bypass surfacer: it reads
`reconciler-bypass-log.jsonl`, compares each entry's `ts` against the prior
heartbeat's `last_run_utc`, and bus-posts new entries to `lead` with topic
`bypass-detected/state-reconciler`. Zero new entries = silent (common case).

A `BAKER_RECONCILER_DRY_RUN=1` flag was added to the cron so the F2 test
harness can exercise the surfacer path without spinning up git remotes.

**Files touched:** `.githooks/state_reconciler_pre_commit.sh`,
`_ops/reconciler/nightly_cron.sh`, `.gitignore`.

### F3 — `reconcile_matter` post-write error path (gate-3 re-fire M)

`_ops/reconciler/state_reconciler.py` `reconcile_matter()` — wrapped
`_save_state` + `_append_skip_log` (after `_atomic_write(cortex_config, ...)`)
in `try/except OSError` so a write-side IO failure returns:

```python
{"slug": slug, "status": "error_io_postwrite", "error": str(e), "cortex_config_written": True}
```

Symmetric to the existing read-side `error_io_read`. Nightly cron now
detects `error_io_postwrite` specifically and emits a softer-toned bus-post
that flags the visible side-effect-already-landed + idempotent-next-fire
property — distinct from the generic `error_reconciler` alert.

**Files touched:** `_ops/reconciler/state_reconciler.py`,
`_ops/reconciler/nightly_cron.sh`.

## Tests

```
$ cd ~/baker-vault && python3 -m pytest tests/test_state_reconciler.py tests/test_state_reconciler_bypass.py
============================= test session starts ==============================
collected 54 items

tests/test_state_reconciler.py ......................................... [ 75%]
.........                                                                [ 92%]
tests/test_state_reconciler_bypass.py ....                               [100%]

============================== 54 passed in 0.93s ==============================
```

**Breakdown — 9 added per brief:**

`tests/test_state_reconciler.py` (was 45 → 50, +5):
- `TestFrontmatterUpdate::test_schema_version_inserted_when_absent_byte_identical_to_old_path` (F1)
- `TestFrontmatterUpdate::test_schema_version_inserted_only_once_on_repeated_runs` (F1)
- `TestReconcileMatter::test_postwrite_save_state_raises_returns_error_io_postwrite` (F3)
- `TestReconcileMatter::test_postwrite_append_skip_raises_returns_error_io_postwrite` (F3)
- `TestReconcileMatter::test_next_run_recovers_after_error_io_postwrite` (F3)

`tests/test_state_reconciler_bypass.py` (new file, 4 tests):
- `test_bypass_appends_jsonl_entry_with_required_fields` (F2)
- `test_bypass_jsonl_grows_append_only` (F2)
- `test_bypass_log_in_gitignore` (F2)
- `test_nightly_cron_bus_posts_on_bypass_since_last_fire` (F2)

## Acceptance criteria

1. F1 + F2 + F3 implemented per the contracts. ✅
2. All STATE_RECONCILER_1 tests still pass. Net count 54 (was 45). ✅
3. Live dry-run returns 8 noop_identical, 0 error_*. ✅
4. `STATE_RECONCILER_SKIP=1` smoke covered by `test_bypass_appends_jsonl_entry_with_required_fields` (real hook script invoked via subprocess against a tmp git repo). ✅
5. Bypass-log in `.gitignore` — verified via `git check-ignore` locally + pinned by `test_bypass_log_in_gitignore`. ✅
6. README updated: test count bumped to 50 + 4 / new file row added, bypass-audit-trail paragraph, error_io_postwrite row in troubleshooting table. ✅

## Notes for reviewers

- LOC delta is ~474 inserts / 17 deletions. Brief estimated ~45 LOC for the
  implementation diff; that target is roughly hit on the Python side
  (+33 / -17 in `state_reconciler.py`). The bulk of the delta is bash
  (cron +91, pre-commit hook +45) plus tests (+101 in `test_state_reconciler.py`
  plus the new 190-line `test_state_reconciler_bypass.py`). All inside
  already-reviewed reconciler internals; no new external surface.
- Pre-commit hook fallback for missing branch/user: an empty-repo case where
  `git rev-parse --abbrev-ref HEAD` prints `HEAD` to stdout and exits nonzero
  was producing `branch: "HEAD\nunknown"`. Hardened to use
  `if ! var=$(cmd) || [ -z "$var" ]; then var="unknown"; fi` pattern.
- `BAKER_RECONCILER_DRY_RUN=1` flag added to nightly_cron is test-only; not
  intended for production use. Skips git fetch / pull / reconciler invocation
  but still runs heartbeat + bypass-surfacer.

## Anchors

- Brief: `briefs/BRIEF_STATE_RECONCILER_2.md` (baker-master `46d2ab3`)
- Mailbox: `briefs/_tasks/CODE_3_PENDING.md` (claimed `343a481`)
- Bus dispatch: #439 (acked)
- Bus ship: #441
- Director auth: 2026-05-18 chat — "go" (drafts STATE_RECONCILER_2 follow-up)
