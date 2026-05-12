---
status: PENDING
brief: inline
trigger_class: TIER_B_CONCURRENCY_PRIMITIVE_HOTFIX
dispatched_at: 2026-05-12
dispatched_by: ai-head-1 (AH1)
target: b1
director_ratification: Director 2026-05-12 21:38Z "go" (post AH1 8x /health re-poll T+17min showing non-lock replica vault_last=None)
priority: P1
phase: 1 of 1
expected_pr_count: 1 (baker-master)
expected_branch: b1/vault-mirror-non-lock-replica-hotfix-1
expected_complexity: low-medium (~30-60 min)
mandatory_2nd_pass: TRUE  # concurrency primitive + production-broken-now
hard_ship_gate: |
  8x rapid /health poll across replicas (15s spacing). ALL replicas MUST show:
  (a) vault_sync_thread_alive: true (NEW key)
  (b) vault_mirror_last_pull advancing past startup time
  Paste raw output in PR description.
gates_required:
  - AH2 /security-review
  - picker-architect (paste-block; architect not bus-attached pre-BRIEF_ARCHITECT_TERMINAL_1)
  - AH1 feature-dev:code-reviewer 2nd-pass (mandatory per SKILL.md trigger #3 — concurrency primitive)
last_heartbeat: null
heartbeat_cadence: 12h max (but expected ship ≤2h)
---

# CODE_1_PENDING — VAULT_MIRROR_NON_LOCK_REPLICA_HOTFIX_1 — 2026-05-12

**Repo:** baker-master (`~/bm-b1`)
**Branch:** `b1/vault-mirror-non-lock-replica-hotfix-1`
**Base SHA:** `git pull --ff-only origin main` first (current main = `3c8acd2` — your prior PR #193 merge)

## Problem

PR #193 (your prior ship) moved `vault_sync_tick` from singleton-locked APScheduler → per-process daemon thread spawned in `_ensure_vault_mirror()` at FastAPI startup. Intent: every replica refreshes its own mirror independently.

**Production observation (AH1 8x /health re-poll T+17min post-deploy `3c8acd2`):**

```
Deploy 3c8acd25 LIVE 21:18:49Z. Load balancer alternates 2 replicas:

LOCK-HOLDER REPLICA (sched=running, jobs=61):
  vault_last advances: 21:21:34 → 21:26:35 → 21:36:36 ✓

NON-LOCK REPLICA (sched=stopped, jobs=0):
  vault_last=None across 6 hits (21:24:03 / 21:25:36 / 21:27:40 / 21:36:15 / 21:36:30 / 21:37:33 / 21:37:49)
  ✗ Per-process daemon thread NOT running on this replica
```

`vault_sha=8590d4ac` on all hits — both replicas DID do the initial `ensure_mirror()` clone at startup, but only the lock-holder is doing periodic refresh. Original bug (Director's YAML edits propagate ~50% of requests) is still present.

## Hypotheses (rank)

1. **Silent exception in `start_sync_thread()` on non-lock replica** — most likely. Exactly the gap architect M1 + 2nd-pass L1 flagged: thread spawn (or first tick) throws an exception, caught and swallowed, thread dies, `/health` has no signal.
2. `_ensure_vault_mirror()` startup hook ordering — maybe singleton-lock check fires before `start_sync_thread()` on non-lock replica path.
3. Some environment difference between lock-holder replica and non-lock replica (env var, FS permissions, port binding side-effect) that breaks the spawn on non-lock only.
4. `start_sync_thread()` IS spawned but `_sync_loop` exits early due to a guard that only passes on lock-holder.

## Required deliverables (2-part scope)

### Part A — Observability primitive FIRST (folds 2nd-pass L1 + architect MEDIUM N1)

Before fixing, add the diagnostic primitive so you (and future operators) can see thread liveness on every replica:

1. `outputs/dashboard.py:mirror_status()` returns dict adds: `"vault_sync_thread_alive": _sync_thread is not None and _sync_thread.is_alive()`
2. Surface in `/health` JSON next to `vault_mirror_last_pull`
3. Deploy this BEFORE the fix — then re-poll across replicas to confirm WHICH hypothesis matches (thread None? thread .is_alive() false? thread alive but loop not ticking?)

### Part B — Fix the spawn / loop failure

Based on Part A evidence:
- If thread is None on non-lock → spawn never happens. Trace startup hook firing on non-lock replica; add exception logging before/after `start_sync_thread()` call in `_ensure_vault_mirror()`.
- If thread exists but not alive → spawn succeeded, loop died. Add explicit `logger.exception` in `_sync_loop`'s except block (currently silent per architect M1 / 2nd-pass L1).
- If thread alive but not ticking → first iteration is blocking on something; verify `ensure_mirror()` completes synchronously before `start_sync_thread()` (`_ensure_vault_mirror()` ordering).

### Part C — Fold 2nd-pass + architect NITs (since you're in this file anyway)

1. **M1 lock-symmetry** (2nd-pass MEDIUM escalation, architect+AH2 LOW): wrap `stop_sync_thread` body in `with _sync_thread_lock:` per 2nd-pass fix snippet.
2. **L2 timing test slack** (architect+AH2 LOW): bump `test_sync_thread_invokes_sync_tick_on_interval` to 0.1s interval + 1.0s wait + `>=3` calls.
3. **L4 concurrent-idempotency test** (architect LOW): add `test_start_sync_thread_concurrent_idempotent` using `threading.Barrier(2)` + 20-iteration loop, assert exactly one thread spawned.
4. (Architect N1 PR #191 — parametrized Case G — out of scope, file follow-up only.)

## Acceptance criteria

1. `/health` exposes `vault_sync_thread_alive: bool` on every replica.
2. After fix deploys, 8x rapid /health poll (15s spacing) across replicas shows `vault_sync_thread_alive: true` AND `vault_mirror_last_pull` is ≤5 min old on EVERY replica hit (not just lock-holder).
3. `stop_sync_thread` acquires `_sync_thread_lock`.
4. Timing test bumped to 0.1s/1.0s/≥3.
5. New concurrent-idempotency test added + GREEN.
6. `_sync_loop` exception handler now logs (no longer silent — per architect M1 / 2nd-pass L1 framing).

## Ship gate

Literal `pytest tests/test_vault_mirror.py -v` GREEN + the 8x /health poll output across replicas pasted in PR description (must show all replicas hit have `vault_sync_thread_alive: true` and advancing `vault_mirror_last_pull`).

## Bus-post on ship

```
BAKER_ROLE=b1 ~/Desktop/baker-code/scripts/bus_post.sh lead "SHIP: VAULT_MIRROR_NON_LOCK_REPLICA_HOTFIX_1 — PR #<N> open. Root cause: <one-line>. /health now exposes vault_sync_thread_alive on all replicas. Lock-symmetry + timing-test-slack + concurrent-idempotency test folded. Ship gate: pytest GREEN + 8x /health poll showing all-replica refresh." ship/vault-mirror-non-lock-replica-hotfix-1
```
