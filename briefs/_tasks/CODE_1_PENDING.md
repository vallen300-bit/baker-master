# CODE_1 — COMPLETE (SCHEDULER_SINGLETON_HARDEN_1)

**Status:** COMPLETE — PR #84 merged + deployed + production-verified
**PR:** https://github.com/vallen300-bit/baker-master/pull/84
**Branch:** `b1/scheduler-singleton-harden-1` (deleted post-merge)
**Merge commit:** `f0f53e04` (2026-04-29T17:23:53Z, squash)
**Deploy:** `dep-d7p3taq49v5s73efel70` live 17:43:21Z
**Ship report:** `briefs/_reports/B1_scheduler_singleton_harden_20260430.md`

## Pre-merge reviews — both APPROVE

- **AI Head A `/security-review`** (Lesson #52 mandatory): zero HIGH/MEDIUM findings. Parameterized advisory-lock SQL, module-scoped held connection (no pool poisoning), no credential leak in error paths, graceful fallback on `POSTGRES_HOST_DIRECT` unset.
- **B3 situational review** (`8d15d40`): APPROVE, all 10 specific concerns clean. One MEDIUM operational flag — `POSTGRES_HOST_DIRECT` required pre-merge — resolved at 17:35Z (Tier B action log entry; Render env-var set via per-key PUT, total var count 53→54).

## Production verification — ALL PASS (2026-04-29 18:15Z)

Window: 17:57Z onward (5min post-deploy-chain drain + 18min clean observation; no concurrent deploy).

### SQL #1 — every job `distinct_anchors=1` (singleton enforcement)

| job_id | fires/18min | distinct_anchors | anchor (sub-second) |
|---|---|---|---|
| kbl_bridge_tick | 18 (60s) | **1** | 38.434904 |
| kbl_pipeline_tick | 9 (120s) | **1** | 38.434731 |
| doc_pipeline_drain | 9 (120s) | **1** | 38.400493 |
| scheduler_heartbeat | 4 (300s) | **1** | 38.434341 |
| email_poll | 4 (300s) | **1** | 38.306594 |
| slack_poll | 4 | **1** | 38.334492 |
| vault_sync_tick | 4 | **1** | 38.440306 |
| cortex_stuck_cycle_sentinel | 4 | **1** | 38.439574 |
| memory_watchdog | 4 | **1** | 38.434516 |
| expire_browser_actions | 4 | **1** | 38.433919 |
| clickup_poll | 3 | **1** | 8.311840 |
| fireflies_scan / evening_push_digest / calendar_prep | 1 each | **1** each | various |

**Pre-PR-#84 baseline = 2× per cadence. Post-merge = exactly 1×. Fix confirmed end-to-end.**

### SQL #2 — `pg_locks` shows exactly 1 row for `objid=8800100`

```
locktype: advisory | classid: 0 | objid: 8800100 | granted: True | pid: 23823
```

Lock visible + held by single backend.

### SQL #3 — `cortex_pipeline.maybe_dispatch` still 1× per signal (no Cortex regression)

`dispatches_per_signal = 1` for every cycle in last 24h (cycles 6afd444c + 9b525a25 — both AO matter, both 1×). Cortex cost-gate atomic-claim (`record_decision`) continues to dedup as designed.

## Deploy chain stress-test (incidental)

Singleton lock survived 3 back-to-back deploys in 12 min (commits `f0f53e0` PR #84 → `e541abd` V3 roadmap → `1273093` V3 parked items). Each deploy = NEW container's lock-acquire returns None → spawn lock-poll thread → OLD container drains + dies → lock auto-releases → NEW acquires within 30s → starts scheduler. Steady-state achieved post-chain-settle. Real-world proof of Render-Pro zero-downtime overlap handling.

## Mailbox hygiene

Per ratified 2026-04-24 §3 — overwritten to COMPLETE with PR URL + post-deploy verification.

## Side observation surfaced (parked, not blocker)

B3 surfaced during review: pre-existing lock-key collision at `orchestrator/financial_detector.py:76` + `orchestrator/initiative_engine.py:630` — both use `pg_try_advisory_xact_lock(900300)`. One silently no-ops when the other holds. Out of scope for PR #84. Parked as `ADVISORY_LOCK_KEY_AUDIT_1` in V3 roadmap Wave 2.

## Co-Authored-By

```
Co-authored-by: Code Brisen #1 <b1@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
