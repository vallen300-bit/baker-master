# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (fresh terminal tab post-PR-#17-ship)
**Task posted:** 2026-04-19 (late afternoon)
**Status:** OPEN — two tasks queued, run in order

---

## Task 1 (first): PR #17 same-branch AMEND — cost-cap env + currency fix

B2 REDIRECT at `briefs/_reports/B2_pr17_dashboard_review_20260419.md`. One S1, all other audit items clean. ~15 lines across 3 files, one amend commit on branch `kbl-pipeline-dashboard-mvp`.

### What's broken

Dashboard cost widget reads `KBL_COST_DAILY_CAP_USD` (invented env name, default `$15`) — but canonical env is `KBL_COST_DAILY_CAP_EUR` (default `€50`, enforced in `kbl/cost_gate.py:46-47`). Render has `_EUR` set; `_USD` is unset → falls back to $15. Director would see "$12.40 of $15 used, $2.60 remaining" when actual is "€12.40 of €50, €37.60 remaining" — **83% displayed, 25% actual**. Safety-critical misinformation.

Also: `cost_usd` column in `kbl_cost_ledger` holds EUR values ("EUR-treated-as-USD" per `kbl/cost_gate.py:140-147`), so every `$` prefix in the frontend is mis-labeling EUR numbers.

### Exact changes (from B2's review)

**`outputs/dashboard.py`** (cost-rollup endpoint):

```python
try:
    cap_eur = float(os.getenv("KBL_COST_DAILY_CAP_EUR", "50.0"))
except (TypeError, ValueError):
    cap_eur = 50.0
...
return {
    "rollup": rows,
    "day_total_eur": day_total,
    "cap_eur": cap_eur,
    "remaining_eur": max(0.0, cap_eur - day_total),
}
```

**`outputs/static/app.js`**:

```javascript
function kblFmtMoney(n) {
    if (n === null || n === undefined) return '€0.00';
    var v = Number(n);
    if (!isFinite(v)) return '€0.00';
    return '€' + v.toFixed(2);
}
// inside _loadKBLCost:
var dayTotal = Number(data.day_total_eur || 0);
var cap = Number(data.cap_eur || 0);
var remaining = Number(data.remaining_eur || 0);
```

**`tests/test_dashboard_kbl_endpoints.py`**:

- `monkeypatch.setenv("KBL_COST_DAILY_CAP_EUR", "50.0")` (was `_USD`)
- Assertions: `body["cap_eur"] == 50.0`, `body["day_total_eur"]`, `body["remaining_eur"]`, `body["remaining_eur"] == 50.0` (empty-state test)

### Delivery

- One amend commit on same branch `kbl-pipeline-dashboard-mvp`. No new PR.
- Push force-with-lease to the branch (or simple push if no rebase collision).
- All 8 tests stay green.
- Dispatch back: `B1 PR #17 amend shipped — head <SHA>, 8/8 green, cost widget now reads KBL_COST_DAILY_CAP_EUR / renders €. Ready for B2 re-review.`
- ~15 min.

---

## Task 2 (second): KBL_PIPELINE_SCHEDULER_WIRING — PR #18

Brief at `briefs/_drafts/KBL_PIPELINE_SCHEDULER_WIRING_BRIEF.md`. B2 APPROVED at `briefs/_reports/B2_scheduler_wiring_brief_rereview_20260419.md` (head post-§Scope.6-verification-note push; see below).

**§Scope.6 Mac Mini verification already run by AI Head (2026-04-19, all three checks pass).** Premise confirmed — Mac Mini poller is Step-7-only. Proceed without blocking.

### Summary

- Extract `_process_signal_remote(signal_id, conn)` in `kbl/pipeline_tick.py` — Steps 1-6 only, Step 7 skipped (Mac Mini owns Step 7).
- Rewrite `main()` — drop KBL-A stub, add `KBL_FLAGS_PIPELINE_ENABLED` env gate (default `"false"`), call `_process_signal_remote` on claim.
- Register `kbl.pipeline_tick.main` in Render's APScheduler (120 s interval, `max_instances=1`, `coalesce=True`, id `kbl_pipeline_tick`).
- 7 tests per brief §Scope.5.
- Env var docs for `KBL_FLAGS_PIPELINE_ENABLED` + `KBL_PIPELINE_TICK_INTERVAL_SECONDS`.
- Branch: `kbl-pipeline-scheduler-wiring`. Target PR: #18. Reviewer: B2.

### Read the brief end-to-end before starting

- `briefs/_drafts/KBL_PIPELINE_SCHEDULER_WIRING_BRIEF.md` — full spec + all 7 tests enumerated + CHANDA pre-push + hard constraints.
- N1-N6 cosmetic nits from B2's v1 review are foldable at your discretion during impl:
  - N1: drop dead `step7_commit` import from `_process_signal_remote`
  - N2: module docstring update in-scope
  - N3: `misfire_grace_time` explicit or documented
  - N4: `IntervalTrigger(seconds=...)` consistency with `embedded_scheduler.py`
  - N5: env-gate parsing doc note
  - N6: `KBL_PIPELINE_TICK_INTERVAL_SECONDS` ValueError guard (already in brief as `int(os.environ.get(...))` — harden with try/except if you want)

### Delivery

- New PR #18.
- Dispatch back: `B1 KBL_PIPELINE_SCHEDULER_WIRING shipped — PR #18 open, branch kbl-pipeline-scheduler-wiring, head <SHA>, 7/7 new tests + full regression green. Steps 1-6 wired via _process_signal_remote; main() env-gated on KBL_FLAGS_PIPELINE_ENABLED (default closed); APScheduler job kbl_pipeline_tick registered at 120s. Step 7 unchanged. Ready for B2 review.`
- ~60-90 min.

---

## Working-tree reminder

Work in `~/bm-b1`. Quit Terminal tab after Task 2 ships — memory hygiene. (Task 1's amend is small enough that you can run both in the same tab before quitting.)

---

*Posted 2026-04-19 by AI Head. Two PRs worth of work in one queue. PR #17 amend → auto-merge on B2 APPROVE; PR #18 → B2 PR review after merge.*
