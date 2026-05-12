---
status: PENDING
brief: inline
trigger_class: TIER_B_BACKEND_DIAGNOSE_AND_FIX
dispatched_at: 2026-05-13
dispatched_by: ai-head-1 (AH1)
target: b1
director_ratification: Director 2026-05-13 "sent dispatch by bus to all the workers to deal with all of the issues step by step"
priority: P2
phase: 1 of 1
expected_pr_count: 1 (baker-master)
expected_branch: b1/vault-mirror-sync-tick-diagnose-1
expected_complexity: low-medium (~1-2h)
mandatory_2nd_pass: FALSE
hard_ship_gate: literal `pytest tests/test_vault_mirror.py -v` GREEN + live verification (force a baker-vault commit, wait ≤5 min, confirm `vault_mirror_last_pull` in `/health` advances without manual deploy) pasted in PR description
gates_required:
  - AH2 /security-review
  - picker-architect
last_heartbeat: null
heartbeat_cadence: 12h max
---

# CODE_1_PENDING — VAULT_MIRROR_SYNC_TICK_DIAGNOSE_1 — 2026-05-13

**Repo:** baker-master (`~/bm-b1`)
**Branch:** `b1/vault-mirror-sync-tick-diagnose-1`
**Base SHA:** `git pull --ff-only origin main` first (current main = 948af22 or newer)

## Problem

`triggers/embedded_scheduler.py:972-985` registers APScheduler job `vault_sync_tick` for every 300s (`vault_mirror.sync_interval_seconds`). `/health` confirms scheduler running with 62 jobs. BUT actual pull cadence on baker-master `srv-d6dgsbctgctc73f55730` was observed at 66+ min between pulls — the job is registered but silent.

**Anchor (2026-05-11 ~07:00-07:50Z):** `/health` showed `vault_mirror_last_pull: 2026-05-11T06:40:31.910656+00:00` at session-time 07:46Z (66 min stale). Forced 2nd Render deploy `dep-d80oir7aqgkc73aabds0` to pick up baker-vault commit `8f19415`; auto-cron should have pulled within 5 min and didn't.

**Effect:** Director-curated YAML edits to baker-vault don't propagate to baker-master without a manual Render redeploy. Cockpit fallback fix workflow took ~25 min instead of ~5 min.

## Hypotheses (rank + investigate)

1. Job-id collision — another scheduler entry overwrites `vault_sync_tick`.
2. Job persisted/disabled in jobstore from prior run.
3. Wrong trigger (e.g. registered with `next_run_time=None` and never advanced).
4. Job runs but `vault_mirror.sync_tick` swallows exceptions silently.
5. Render-side process reload kills the job at unknown cadence.

## Acceptance criteria

1. Root cause identified + named in PR description (one of the above OR a new hypothesis with evidence).
2. Fix lands: `vault_sync_tick` actually fires every 300s on baker-master.
3. Live verification: write a baker-vault commit, wait ≤5 min, confirm `vault_mirror_last_pull` in `https://baker-master.onrender.com/health` advances without manual Render deploy.
4. Test added at `tests/test_vault_mirror.py` covering the failure mode you fixed.
5. **Do NOT** ship a workaround (separate cron-trigger, manual-pull endpoint, etc.). Diagnose the existing job first; it's already wired correctly per source inspection.

## Ship gate

Literal `pytest tests/test_vault_mirror.py -v` GREEN output pasted in PR description + live `/health` before/after timestamps proving the auto-pull works.

## Bus-post on ship

```
BAKER_ROLE=b1 ~/Desktop/baker-code/scripts/bus_post.sh lead "SHIP: VAULT_MIRROR_SYNC_TICK_DIAGNOSE_1 — PR #<N> open. Root cause: <one-line>. Ship gate: pytest GREEN + live /health verified." ship/vault-mirror-sync-tick-diagnose-1
```
