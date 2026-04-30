# CODE_3 — PENDING (review B1 PR #116 — CORTEX_AUTO_TRIGGER_DISPATCH_FIX_1)

**Status:** PENDING — dispatched 2026-04-30 by AI Head A (App)
**Type:** Second-pair-of-eyes review (NOT build)
**Priority:** CRITICAL
**Trigger-class:** Cross-capability state writes (B1 builder-conflict caveat → B3 substitutes for B1's normal review role)

## Task summary

Review PR #116 (B1's CORTEX_AUTO_TRIGGER_DISPATCH_FIX_1) BEFORE AI Head A merges.

PR: https://github.com/vallen300-bit/baker-master/pull/116
Brief: `briefs/BRIEF_CORTEX_AUTO_TRIGGER_DISPATCH_FIX_1.md`
B1 ship report: `briefs/_reports/B1_cortex_auto_trigger_dispatch_fix_20260430.md` (read first)

Companion vault PR (already merged): baker-vault PR #30 — slugs.yml v15→v16 movie_am underscore alias.

## What B1 changed

5 files / +541 / -103 baker-master + 1 line vault.

- Removed `maybe_dispatch` call from `kbl/bridge/alerts_to_signal.py` post-INSERT (was firing with raw classifier labels pre-Step-1).
- Added `dispatch_cortex_after_finalize(signal_id)` helper in `kbl/steps/step6_finalize.py`.
- Wired into all 6 `_process_signal*` finalize call sites in `kbl/pipeline_tick.py`.
- Idempotency: INSERT-IF-NOT-EXISTS in `baker_actions` keyed `(target_task_id, action_type LIKE 'cortex:dispatch:%')` per existing `cortex_pre_review_gate.record_decision()` pattern.

## Review focus areas

1. **Idempotency correctness** — verify the `cortex:dispatch:{signal_id}` row guard actually prevents double-dispatch under all 6 finalize paths. Race: signal_id committed twice (Step 6 retry) → second call must observe the prior row and skip.
2. **Regression coverage** — confirm no orphan `maybe_dispatch` calls remain. B1's grep proof should be in PR body; verify locally.
3. **Step 6 wiring completeness** — all 6 `_process_signal*` paths in `pipeline_tick.py` must call the new helper. Missing one path = silent dead-trigger for that signal type.
4. **Test plan** — pytest 107 passed / 2 skipped. Run pre-pytest re-checkout + verify the green count locally on b1 branch before signing off.
5. **Behavioral test** — does B1 cover the scenario where Step 6 runs but `primary_matter` is still raw (slug_registry.normalize miss, e.g. if alias still missing)? Should produce `cortex:gate:skip_no_config` audit row, not silent drop.

## Verdict

After review, paste-block back to AI Head A:
- **PASS** → AI Head A merges + spot-checks live `cortex_cycles` post-deploy.
- **REQUEST_CHANGES** → cite specific concerns; B1 patches; re-review.

## Dispatch

```
git checkout main && git pull --ff-only origin main
git fetch origin
git checkout origin/b1/cortex-auto-trigger-dispatch-fix
gh pr view 116 --web   # or read PR diff via gh pr diff 116
```

## Previous task (closed)

PR #108 (LOCK_KEY_900300_COLLISION_1) merged 2026-04-30 — initiative_engine renumbered to 900800.
