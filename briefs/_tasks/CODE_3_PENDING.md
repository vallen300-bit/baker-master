# CODE_3 — PENDING (LOCK_KEY_900300_COLLISION_1)

**Status:** PENDING — dispatched 2026-04-30 by AI Head A (App)
**Brief:** `briefs/BRIEF_LOCK_KEY_900300_COLLISION_1.md`
**Builder:** B3
**Priority:** HIGH
**ETA:** 2026-05-02

## Task summary

You surfaced this during PR #84 review — `pg_try_advisory_xact_lock(900300)` collides between `orchestrator/financial_detector.py:76` and `orchestrator/initiative_engine.py:630`. Renumber `initiative_engine` to `900800`. Verify uniqueness across all detectors. ~10 LOC fix.

Audit at brief-author time: every other key (900100, 900201, 900400, 900500, 900600, 900700, 8004, 8005) is unique.

## Dispatch

1. Read brief: `briefs/BRIEF_LOCK_KEY_900300_COLLISION_1.md`
2. Branch: `b3/lock-key-900300-collision`
3. Pre-pytest re-checkout ritual.
4. PR body must include grep proof of post-edit uniqueness.
5. AI Head A solo review per autonomy charter §4 (non-trigger-class).

## Previous task (closed)

PR #84 situational review (SCHEDULER_SINGLETON_HARDEN_1) — APPROVE verdict 2026-04-29T17:21Z.
