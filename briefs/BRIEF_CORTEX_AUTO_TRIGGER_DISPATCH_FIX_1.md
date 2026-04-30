# BRIEF — CORTEX_AUTO_TRIGGER_DISPATCH_FIX_1

**Owner:** B-code (assigned: B1 — deep context from AUTO_TRIGGER_FAN_OUT_VERIFY_1)
**Author:** AI Head A (App)
**Drafted:** 2026-04-30
**Priority:** CRITICAL
**ETA:** 2026-05-01
**Roadmap item:** `cortex-auto-trigger-dispatch-fix` (V4 queued, NEW)

## Severity

**Auto-trigger has been silently dead for all 22 matters since multi-matter cost-gate shipped.** Director-manual + scan_intent paths still work; signal-triggered auto-fan-out has never reached canonical-slug gate posts. Zero `triggered_by='signal'` cycles for canonical `hagenauer-rg7` / `mo-vie-am` / `lilienmatt`. Source: B1 ship report `briefs/_reports/B1_auto_trigger_fan_out_verify_20260430.md` (PR #109 merged).

## Root cause (one sentence)

`kbl/bridge/alerts_to_signal.py:577` dispatches `maybe_dispatch(matter_slug=signal_row["matter"])` immediately post-INSERT — before Step 1 triage canonicalizes via `slug_registry.normalize()` and writes the canonical slug to `signal_queue.primary_matter` — so `triggers/cortex_pre_review_gate.py:matter_has_cortex_config()` always misses on raw PM-era labels (`Hagenauer`, `Oskolkov-RG7`, `movie_am`, etc.).

## Goal

Auto-trigger fan-out actually fires Cortex cycles for canonical matters that have a `wiki/matters/<slug>/cortex-config.md`.

## Spec — Option A from B1 ship report (Director-ratified, recommended path)

### Part 1 — move dispatch from bridge to Step 6 finalize

1. **Remove** the post-INSERT dispatch call in `kbl/bridge/alerts_to_signal.py:_dispatch_cortex_for_inserted` (around line 577). Bridge tick stops calling `maybe_dispatch`.
2. **Add** the dispatch call inside Step 6 finalize (`kbl/steps/step6_finalize.py` or wherever Step 6 commits the finalized row). Fire `maybe_dispatch(signal_id=row.id, matter_slug=row.primary_matter)` AFTER `primary_matter` is written + committed.
3. **Idempotency guard:** Step 6 may run multiple times on a row across retries. Guard the dispatch call so it fires only once per `signal_id`. Suggested: a `cortex_dispatched_at` timestamp column on `signal_queue`, or a row in `baker_actions` keyed `cortex:dispatch:{signal_id}` — pick whichever fits existing patterns. Document the choice in PR body.
4. **No-config matters still record:** if `matter_has_cortex_config(primary_matter) == False`, log `cortex:gate:skip_no_config` to `baker_actions` so we have a per-signal audit trail (matches existing convention).

### Part 2 — fix the `movie_am` underscore alias gap

`slug_registry` does not normalize `movie_am` (underscore) → `mo-vie-am`. Only `movie-am` (hyphen) is in the alias list per B1 finding.

Pick one approach (recommend (a) for minimal surface):

**(a)** Add `movie_am` to `mo-vie-am` aliases in `baker-vault/slugs.yml`. Vault change, separate commit on the `b1/` branch (yes, B1 may write to baker-vault for this slugs.yml edit — branch-isolation: cross-repo branch with same name).

**(b)** Make `slug_registry.normalize()` substitute `_` → `-` before lookup. Code change in baker-master.

Pick (a) — minimal surface. Document the choice in PR body.

## Test plan

1. **Unit test** — assert dispatch fires from Step 6, not bridge:
   - Inject synthetic `alerts` row → bridge tick INSERTs `signal_queue` row → assert `maybe_dispatch` NOT called yet.
   - Run Step 1 + Step 6 → assert `maybe_dispatch` called once with canonical `primary_matter`.
2. **Integration test** — synthetic signal flow:
   - Pick `lilienmatt` (had 26 signals in 14 d but 0 cycle).
   - Inject signal → bridge → Step 1 → Step 6 → verify `cortex_cycles` row appears with `triggered_by='signal'`, `matter_slug='lilienmatt'`.
   - Verify `baker_actions` has `cortex:gate:post` row for the signal.
3. **Regression** — assert no orphan `maybe_dispatch` calls remain in `kbl/bridge/`:
   ```
   grep -rn "maybe_dispatch" kbl/bridge/ orchestrator/ kbl/steps/
   ```
   should show only the new call site in `step6_finalize`.
4. **Pre-pytest re-checkout ritual** applies (shared worktree race).

## Done definition

- PR opened with full diff + grep proof + pytest output in PR body.
- Pytest green.
- B3 second-pair-of-eyes review BEFORE AI Head A merge (trigger-class: cross-capability state writes).
- Post-merge: AI Head A spot-checks live `cortex_cycles` after next bridge tick — confirm canonical-slug `triggered_by='signal'` rows appear within 30 min.
- Mark `cortex-auto-trigger-dispatch-fix` DONE in V4 YAML on green.

## Trigger-class

**Cross-capability state writes** (re-routes the entire signal-to-cycle dispatch pathway). B1 builds → B3 reviews → AI Head A merges. Second-pair-of-eyes per B1 situational review trigger 2026-04-24, builder-conflict caveat (B1 reviewing own work is the gap; B3 substitutes).

## Coordination

- B1 must finish PR #107 review FIRST (B4 BOOTSTRAP_V2_GOLD_SKIP_1 awaits B1's PASS).
- After PR #107 review, B1 starts this brief.
- B3 should finish current work (PR #108 already merged) and stand by for review of this brief's PR.

## Notes for B1

You found the bug; you fix it. Your verification work confirmed the gate code itself is correct — the only fix needed is moving the dispatch call. Keep it surgical: ~30 LOC move + idempotency guard + alias addition. Don't refactor the bridge or Step 6 broadly.
