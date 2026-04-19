# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (fresh terminal tab — sanity-check tab standing down)
**Task posted:** 2026-04-19 (late afternoon)
**Status:** OPEN — three queued reviews, run in order

---

## Task 0 (first, short — skip if you already ran it): B3 dropbox-mirror retirement sanity-check

B3 shipped at `9f7867f` while you were standing down. Report: `briefs/_reports/B3_dropbox_mirror_retire_20260419.md`.

If you already ran this sanity-check and filed `briefs/_reports/B2_dropbox_mirror_retire_sanity_20260419.md`, skip to Task 1. Otherwise:

- `ssh macmini 'launchctl list | grep brisen'` — expect exactly 3 agents (`baker.heartbeat`, `baker.poller`, `kbl.purge-dedupe`); `dropbox-mirror` absent.
- `ssh macmini 'ls -la ~/Library/LaunchAgents/com.brisen.kbl.dropbox-mirror*'` — expect one file ending `.retired-2026-04-19`.
- Confirm report's claims match (Inv 9 clean, `~/.kbl.env` untouched, purge-dedupe untouched).
- Verdict APPROVE or REDIRECT at `briefs/_reports/B2_dropbox_mirror_retire_sanity_20260419.md`. ~5 min.

---

## Task 1 (second): PR #17 re-review post-amend

B1 amended per your S1 REDIRECT. Same-branch amend, no new PR.

- Branch: `kbl-pipeline-dashboard-mvp`, head `43ef1d0`
- Change surface: `outputs/dashboard.py` + `outputs/static/app.js` + `tests/test_dashboard_kbl_endpoints.py`
- Specifics: `KBL_COST_DAILY_CAP_USD` → `KBL_COST_DAILY_CAP_EUR` (default `50.0`); JSON fields `*_usd` → `*_eur`; frontend `kblFmtMoney` outputs `€` prefix; test env-set + assertion keys updated.
- B1 reports 8/8 tests green.
- PR mergeable state: UNKNOWN at time of dispatch (CI may still be checking) — `gh pr view 17 --json mergeable` before flipping.

### Verdict focus (per your own review plan)

- Confirm the four fixes above match what you flagged.
- Confirm no *other* unintended changes in the amend diff (`git diff 1ce3ade..43ef1d0 -- outputs/dashboard.py outputs/static/app.js tests/test_dashboard_kbl_endpoints.py`).
- Confirm tests still cover the empty-state → `remaining_eur == 50.0` path.
- Confirm `€` symbol used consistently (no leftover `$` in any of the three files).
- CI green.

On APPROVE + MERGEABLE: AI Head auto-merges. File verdict at `briefs/_reports/B2_pr17_dashboard_rereview_20260419.md`. ~10 min per your earlier note.

---

## Task 2 (third): PR #18 KBL_PIPELINE_SCHEDULER_WIRING full PR review

- PR: https://github.com/vallen300-bit/baker-master/pull/18
- Branch: `kbl-pipeline-scheduler-wiring`, head `d7312e8`
- Status: OPEN, MERGEABLE
- B1 reports 86/86 green (20 pipeline_tick + 27 step7 + 45 step6). Env docs at §9.4 of KBL-B brief.

### Scope focus (standard PR review + your specific concerns from the brief-review)

1. **`_process_signal_remote` is a clean Steps 1-6 block** — confirm it does NOT call `step7_commit` under any path, AND that the dead `step7_commit` import (N1 from v1 review) is dropped from the module-level imports if added.
2. **`main()` rewrite** —
   - Circuit checks (anthropic + cost) run FIRST, then env gate, then claim (the order test #5 asserts).
   - KBL-A stub completely removed (no `classified-deferred` UPDATE anywhere).
   - `KBL_FLAGS_PIPELINE_ENABLED` defaults to `"false"` — paste the exact line B1 used.
3. **APScheduler registration** —
   - `id="kbl_pipeline_tick"`, `max_instances=1`, `coalesce=True`, `trigger="interval"`, `seconds=120`, `replace_existing=True`.
   - Scheduler registration is guarded by the same startup lifecycle as other `add_job` sites in the repo.
   - N4 (`IntervalTrigger(seconds=...)` vs kwarg consistency) — whichever pattern B1 picked, confirm it matches `embedded_scheduler.py` convention.
   - N6 (`KBL_PIPELINE_TICK_INTERVAL_SECONDS` ValueError guard) — if not hardened, flag but don't block.
4. **7 tests from §Scope.5** — all present, all green. Each test asserts what brief spec'd.
5. **CHANDA pre-push** —
   - Q1 (Loop Test): this PR doesn't touch Leg 1 (Gold reading), Leg 2 (ledger), Leg 3 (hot.md + ledger reading) — pure wiring. Pass.
   - Q2 (Wish Test): enables the compounding loop to actually run. Pass.
   - **Inv 9:** Render never calls Step 7 in this PR. Verify `_process_signal_remote` body + all code paths from `main()` stop at `awaiting_commit`. Mac Mini poller untouched.
   - Inv 10: no prompt self-modification.
6. **Tx-boundary contract preserved** — per-step `conn.commit()` on success + `conn.rollback()` on raise. No collapsed commits in `_process_signal_remote`.
7. **Env docs** — §9.4 of `briefs/_drafts/KBL_B_PIPELINE_CODE_BRIEF.md` documents `KBL_FLAGS_PIPELINE_ENABLED` + `KBL_PIPELINE_TICK_INTERVAL_SECONDS`. Default-closed called out.

### Specific landmine questions

- Does `main()` handle the case where `claim_one_signal` returns `None` without ever calling `_process_signal_remote`? (Brief expects early return.)
- If a step raises, does `main()` let the exception propagate (for APScheduler to log) or swallow it? Brief says propagate.
- Does the test `test_main_circuit_breaker_precedes_env_gate` actually assert ORDER (circuit runs before env check) and not just that both run?

### Verdict

APPROVE or REDIRECT with inline fixes. Small-surface fixes → B1 amends on same branch. File verdict at `briefs/_reports/B2_pr18_scheduler_wiring_review_20260419.md`. ~25-35 min.

On APPROVE + MERGEABLE: AI Head auto-merges. Shadow-mode flip unlocks.

---

## Working-tree reminder

Work in `~/bm-b2`. **Quit tab after all three reviews ship** — memory hygiene.

---

*Posted 2026-04-19 by AI Head. Two PR reviews; both shadow-mode blockers. Dashboard + scheduler both land, then you flip `KBL_FLAGS_PIPELINE_ENABLED=true` on Render and first signals flow.*
