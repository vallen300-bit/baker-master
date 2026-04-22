# B3 Review — PR #43 OBSERVABILITY_STEP7_PLUS_POLLER_DOC_1

**Reviewer:** Code Brisen #3
**Date:** 2026-04-22
**PR:** https://github.com/vallen300-bit/baker-master/pull/43
**Branch:** `observability-step7-plus-poller-doc-1`
**Head SHA:** `be5b714`
**Author:** B1
**Ship report:** `briefs/_reports/B1_observability_step7_plus_poller_doc_1_20260422.md`

---

## §verdict

**APPROVE PR #43.** All 8 focus items green. Full-suite regression delta reproduced locally with cmp-confirmed identical 16-failure set. Two observability gaps closed: Step 7 happy-path `emit_log` (mirrors PR #42's Step 5 pattern) + `pipeline_tick` docstring now cites the verified off-tree poller facts. Last review in today's wave — Cortex-launch surface clean post-merge.

---

## §focus-verdict

1. ✅ **7 emit_log bisection points (8 call sites) in `step7_commit.py`, all `INFO` with `_LOG_COMPONENT = "step7_commit"`.**
2. ✅ **`logger.info("step7 mock-mode...")` preserved alongside new shadow-mode `emit_log`.**
3. ✅ **ADD-ONLY in `step7_commit.py` — zero logic deletions.**
4. ✅ **Failure-path `emit_log("WARN", "commit", ...)` at `_mark_commit_failed` unchanged.**
5. ✅ **`pipeline_tick.py` docstring cites `/Users/dimitry/baker-pipeline/poller.py` + LaunchAgent `com.brisen.baker.poller` + 60s StartInterval — matches verified SSH facts.**
6. ✅ **3 new tests via `call_args_list` positional-arg inspection, exclusivity asserts.**
7. ✅ **Regression delta: +3 passed, 0 regressions, cmp-identical failure set.**
8. ✅ **Ship report carries full pytest with literal counts; "by inspection" absent.**

---

## §1 Step 7 emit_log sites

`grep -nE "^\s*emit_log\(" kbl/steps/step7_commit.py` → **9 total call sites** (1 pre-existing WARN at line 296 + 8 new INFO calls).

Bisection markers `[1]`-`[7]` (comments inline in source):

| Marker | file:line | Message prefix | Condition |
|--------|-----------|----------------|-----------|
| [1] | 579 | `step7 entry:` | Entry point, target_vault_path + primary_matter + stub_count |
| [2] | 606 | `vault lock acquired:` | Post-flock, lock_path + flock_timeout |
| [3] | 624 | `inv4 guard pass:` | After `_inv4_guard_target_path` succeeds |
| [4] | 644 | `files written:` | After atomic write, main + stubs + final_markdown_len |
| [5] | 670 | `commit created:` | After `_git_add_commit`, short-SHA + message |
| [6a] | 686 | `shadow-mode: skipping git push` | `BAKER_VAULT_DISABLE_PUSH=true` branch |
| [6b] | 702 | `git push success:` | `BAKER_VAULT_DISABLE_PUSH=false` post-push |
| [7] | 716 | `signal completed:` | After `_mark_completed`, terminal INFO |

- **`_LOG_COMPONENT = "step7_commit"`** declared at line 103 — matches PR #42's pattern for Step 5 (`"step5_opus"`). ✓
- **Signature compliance:** all 8 new calls use positional `emit_log("INFO", _LOG_COMPONENT, signal_id, msg)`. Verified against `kbl/logging.py:59-62` and `step5_opus.py` usage from PR #42. ✓

**Count note (informational):** dispatch brief claimed "7 sites." Literal count is 8 new calls because [6] has two sub-branches (shadow / push-success) that emit separate logs. Same accounting pattern as PR #42's [6] and [8b]. Not a code issue; more observability, not less.

## §2 `logger.info("mock-mode...")` preserved

`step7_commit.py:680-685`: the pre-existing `logger.info("step7 mock-mode: BAKER_VAULT_DISABLE_PUSH=true, skipping git push (signal_id=%s, sha=%s)", signal_id, commit_sha)` is UNCHANGED and still fires on the shadow-mode branch. Inline comment at line 678 acknowledges dual-logging is deliberate: stdout trace for ops via `logger.info`, kbl_log row via `emit_log`. Test #3 (`test_step7_shadow_mode_fires_info_not_warn`) verifies the emit_log side fires exactly once on `BAKER_VAULT_DISABLE_PUSH=true`; the logger.info side is out-of-scope for the mock test but unchanged in source. ✓

## §3 ADD-ONLY in `step7_commit.py`

`git diff $(merge-base)..pr43 -- kbl/steps/step7_commit.py | grep '^-' | grep -v '^---'` → zero lines.

Diff contains ONLY additions:
- 1 new module constant: `_LOG_COMPONENT = "step7_commit"` (line 103)
- 8 new `emit_log(...)` blocks with surrounding comments

**Zero changes to:**
- `_git_add_commit` (line 410)
- `_git_push_with_retry` (line 443)
- `_atomic_write` (line 352)
- `_inv4_guard_target_path` (line 454)
- `_append_or_replace_stub` (line 540)
- `_mark_completed` / its UPDATE statement
- Lock semantics (`acquire_vault_lock`, flock paths)
- `_git_pull_rebase` / `_git_hard_reset_one` / `_git_checkout_discard`
- `_fetch_signal_row` / `_fetch_unrealized_stubs`

Pure observability layer addition. ✓

## §4 Failure-path emit_log not regressed

`_mark_commit_failed` at `step7_commit.py:283-296` is **UNCHANGED** by this PR. It still emits `emit_log("WARN", "commit", signal_id, f"commit_failed: {reason}")` at line 296.

Failure entry points (all unchanged — not in diff):
- `VaultLockTimeoutError` → `_mark_commit_failed(conn, signal_id, str(e))` at line 725 → WARN
- `CommitError` → `_mark_commit_failed(...)` at line 728 → WARN
- generic `Exception` → `_mark_commit_failed(..., f"unexpected: {e}")` at line 731 → WARN

All three still fire on failure. ✓

**Component-tag inconsistency (flagged as N-nit only):** pre-existing WARN uses `component="commit"` while new INFO calls use `component="step7_commit"`. Queries filtering on `component='step7_commit'` will miss the failure events. This is a pre-existing split; out of scope for PR #43 (ADD-ONLY observability) but worth a future unification tidy. Non-gating.

## §5 `pipeline_tick.py` docstring fix

`git diff $(merge-base)..pr43 -- kbl/pipeline_tick.py` — 30 added, 10 deleted. **All deletions are docstring text being replaced; zero code changes.**

New docstring (lines 11-22) cites:
- `/Users/dimitry/baker-pipeline/poller.py` ✓
- LaunchAgent `com.brisen.baker.poller` ✓
- 60s `StartInterval` ✓
- Wrapper `~/baker-pipeline/poller-wrapper.sh` (bonus detail)
- Env source `~/.kbl.env` (bonus detail)
- Explicit "no `kbl/poller.py` module exists in this repo" correction of the stale reference

Shorter docstring at line 512 (`_process_signal_remote` summary) also updated to cite the off-tree path + LaunchAgent + "see module docstring for details" pointer.

Both docstring updates are fact-accurate per the dispatch brief's reference to AI Head's 11:33 UTC SSH verification. ✓

## §6 3 new tests

`tests/test_step7_commit.py:742-875`. Read each body:

| # | Test | Locks |
|---|------|-------|
| 1 | `test_step7_happy_path_logs_entry_with_target_path` | Entry INFO contains `target=wiki/ao/2026-04-19_observability.md` + `primary_matter='ao'` + `stub_count=0`. Component='step7_commit', signal_id=701. Zero WARN/ERROR on happy path. |
| 2 | `test_step7_happy_path_push_success_fires_info` | `BAKER_VAULT_DISABLE_PUSH=false` → `git push success:` INFO fires once with `sha=` + `branch=main`; shadow-mode INFO NOT emitted; `signal completed:` fires once. Exclusivity pinned. |
| 3 | `test_step7_shadow_mode_fires_info_not_warn` | `BAKER_VAULT_DISABLE_PUSH=true` (default) → `shadow-mode:` INFO fires once with `BAKER_VAULT_DISABLE_PUSH=true` + `sha=`; push-success INFO NOT emitted; zero WARN/ERROR; `signal completed:` still fires. Exclusivity pinned. |

All three use the `_info_messages(mock_emit_log)` helper to flatten `call_args_list` to message strings + positional-arg inspection. Exclusivity checks (`== []` on the wrong branch's message list) pin the push vs shadow branching. Non-trivial. ✓

**Focused run** per ship report: `tests/test_step7_commit.py` → `30 passed in 3.54s` (27 pre-existing + 3 new). Math matches B1's claim.

## §7 Full-suite regression delta

Reproduced locally in `/tmp/b3-venv` (Python 3.12):

```
main baseline:       16 failed / 815 passed / 21 skipped / 19 warnings  (12.25s)
pr43 head (be5b714): 16 failed / 818 passed / 21 skipped / 19 warnings  (13.98s)
Delta:               +3 passed, 0 regressions, 0 new errors, 0 new skips
```

**Failure-set identity check:** `cmp -s /tmp/b3-main7-failures.txt /tmp/b3-pr43-failures.txt` → exit 0 (IDENTICAL).

`+3 passed` matches exactly the 3 new tests. B1's ship-report math holds (`815 + 3 = 818`) and reproduces on my bench EXACTLY. ✓

## §8 Ship report — no "by inspection"

Ship report §test-results carries:
- Focused run: `30 passed in 3.54s` block.
- Full run: `16 failed, 818 passed, 21 skipped, 19 warnings in 11.73s`.
- Per-failure triage enumerating the 16 pre-existing failures (voyageai key, scan 401, storeback fixtures, clickup write-safety).

`grep -n "by inspection"` in ship report → zero matches. Phrase absent. `memory/feedback_no_ship_by_inspection.md` honored. ✓

---

## §non-gating

- **N1 — component-tag split for Step 7.** Pre-existing failure-path WARN at `step7_commit.py:296` uses `component="commit"`, while the 8 new happy-path INFO calls use `component="step7_commit"`. kbl_log queries filtering on `component='step7_commit'` will miss failure events. Pre-existing split; out of scope for PR #43 per brief (ADD-ONLY observability). Future tidy: unify the WARN to `"step7_commit"` (cheap; check downstream log consumers don't hard-code `"commit"`).

- **N2 — dispatch claim "7 sites" vs actual 8 emit_log calls.** Bisection point [6] has two sub-branches (shadow / push-success) that emit separate logs. Same accounting pattern observed on PR #42 ([6] and [8b]). Informational; no code issue.

- **N3 — dual logging at shadow-mode.** Pre-existing `logger.info("step7 mock-mode...")` at line 680 kept alongside new `emit_log(INFO, "shadow-mode: ...")` at line 686. Defensible (stdout trace for ops pager, kbl_log for joinability). Minor drift risk if one updates without the other; same N-nit I flagged on PR #42's cost-gate dual logging. Not gating.

---

## §regression-delta

```
$ wc -l /tmp/b3-main7-failures.txt /tmp/b3-pr43-failures.txt
      16 /tmp/b3-main7-failures.txt
      16 /tmp/b3-pr43-failures.txt

$ cmp -s /tmp/b3-main7-failures.txt /tmp/b3-pr43-failures.txt && echo IDENTICAL
IDENTICAL
```

Raw logs: `/tmp/b3-main7-pytest-full.log`, `/tmp/b3-pr43-pytest-full.log` (local).

---

## §post-merge

- Tier A auto-merge (squash) proceeds.
- Render redeploys pipeline_tick docstring correction (cosmetic, no runtime impact).
- Mac Mini's off-tree poller picks up signals at `awaiting_commit`; its existing `step7_commit.commit()` import now emits 8 INFO rows per successful Step 7 → `kbl_log` gains per-signal audit trail for deploys. First live trace lands on next `awaiting_commit` pickup.

**Cortex-launch surface post-PR-#43 merge:**

- ✅ Full crash-recovery coverage (PRs #38 + #39 + #41 — opus_failed retry, awaiting_* between-steps, *_running during-steps)
- ✅ YAML coercion hotfix live (PR #40)
- ✅ Step 5 observable (PR #42 — empty-draft bisection)
- ✅ Step 7 observable + poller docstring corrected (PR #43 — this PR)
- ✅ 13 previously-stuck signals draining via standing Tier A recovery (per dispatch note: 4 completed, 8 in flight, 0 re-failures at last snap)

Ready for Cortex T3 production cut.

**APPROVE PR #43.**

— B3
