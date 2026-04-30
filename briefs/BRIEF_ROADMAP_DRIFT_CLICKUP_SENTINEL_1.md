# BRIEF — ROADMAP_DRIFT_CLICKUP_SENTINEL_1

**Owner:** B-code (assigned: B2)
**Author:** AI Head A (App)
**Drafted:** 2026-04-30
**Priority:** MEDIUM
**ETA:** 2026-05-03
**Roadmap item:** `roadmap-drift-clickup-sentinel` (V4 queued)

## Problem

V4 roadmap is YAML source-of-truth at `baker-vault/_ops/processes/cortex-roadmap-current.yml`, auto-rendered to brisen-docs HTML. Director's standing rule (2026-04-30): NO PARKED status, backlog goes to ClickUp Cortex Backlog list. Drift detector must be ClickUp-based, NOT Slack.

Without an automated drift check, AI Head A must manually compare YAML last-edit timestamp vs PR merge cadence on every session start to spot drift.

## Goal

Daily 06:00 UTC sentinel that detects roadmap drift and writes findings to a recurring ClickUp task. AI Head A reads it on session start.

## Spec

### Drift definition

Drift = ≥5 PRs merged on either repo (`baker-vault` or `baker-master` since the last `cortex-roadmap-current.yml` edit on `baker-vault main`.

### Detection logic

1. Fetch latest commit timestamp on `_ops/processes/cortex-roadmap-current.yml` (baker-vault main).
2. Fetch list of PR merges on baker-vault main + baker-master main with merge_at > YAML last-edit timestamp.
3. Count merged PRs.
4. If count ≥ 5 → DRIFT detected.

### Output

If drift detected:
- Write a comment on the recurring ClickUp task `86c9k6kau` (drift sentinel, BAKER space "Cortex Backlog" list `901523104264`) with body:
  ```
  Drift detected YYYY-MM-DD HH:MM UTC.
  YAML last edit: <timestamp> on <commit-sha>
  PRs merged since:
  - baker-vault: <list of #PRs with titles>
  - baker-master: <list of #PRs with titles>
  Total: <N> PRs without YAML update.
  ```

If no drift: write nothing (silent pass to keep noise floor low).

### Schedule

APScheduler job in `15_Baker_Master/01_build` Render service, cron `0 6 * * *` UTC. Job name: `roadmap_drift_sentinel`. Singleton-locked per scheduler-singleton pattern (advisory_lock — pick a unique key, e.g. `900900`, audit per LOCK_KEY_900300_COLLISION_1 conventions).

### Auth/secrets

- GitHub PAT for PR list queries (already used by other sentinels — reuse).
- ClickUp token for comment write (already used by `mcp__baker__baker_clickup_tasks` — reuse same secret).

## Implementation

1. New file: `orchestrator/roadmap_drift_sentinel.py` — implements drift detection + ClickUp write.
2. Wire into APScheduler init in main FastAPI app startup (`main.py` or `scheduler.py` — match existing pattern).
3. Tests: `tests/orchestrator/test_roadmap_drift_sentinel.py` — mock GitHub + ClickUp clients, assert drift logic with synthetic timestamps + PR lists.

## Test plan

1. Unit tests: 4 cases — (a) <5 PRs, no drift, no write; (b) ≥5 PRs, drift, ClickUp write fired; (c) GitHub API failure → graceful no-op + log; (d) ClickUp API failure → log error but don't crash scheduler.
2. Pre-pytest re-checkout ritual.
3. Manual smoke: trigger the scheduler job once via Render shell or a debug endpoint; verify comment appears on task `86c9k6kau`.

## Done definition

- PR opened with code + tests + manual smoke evidence.
- Pytest green.
- AI Head A reviews + merges (non-trigger-class — no auth changes, no DB schema, no Director-override).

## Notes for B2

- Lock key 900900 may collide post-LOCK_KEY_900300_COLLISION_1 (B3 lane). Coordinate via mailbox: if B3 ships first, re-grep `pg_try_advisory` and pick next free key.
- ClickUp API surface is via `mcp__baker__baker_clickup_tasks` for AI Head; B-code calls the underlying ClickUp REST directly. Reference existing ClickUp integration in repo for pattern (search `clickup` in orchestrator/).
