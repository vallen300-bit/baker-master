# CODE_3 — COMPLETE (SITUATIONAL_REVIEW_PR84_SCHEDULER_SINGLETON)

**Status:** COMPLETE — 2026-04-29T17:21Z
**Builder:** B3
**Verdict:** APPROVE
**Report:** `briefs/_reports/B3_pr84_situational_review_20260429.md`
**GitHub review:** posted as `COMMENTED` on PR #84 (2026-04-29T17:21:19Z) — `gh pr review --approve` rejected by GitHub (same-account-as-PR-author rule); §0 verdict in the comment body is APPROVE-equivalent per dispatch protocol.

## Summary

All 10 dispatch concerns clean against `origin/b1/scheduler-singleton-harden-1` head `133a852`:

| # | Concern | Status |
|---|---|---|
| 1 | `_held_conn` never enters any pool | clean |
| 2 | Lock uses `direct_dsn_params` (not pooled) | clean |
| 3 | Session-variant `pg_try_advisory_lock` (not xact) | clean |
| 4 | `autocommit = True` on held conn | clean |
| 5 | Retry thread daemon + idempotent + exit reachable | clean |
| 6 | HOST_DIRECT-unset failure mode | **MEDIUM operational flag (§2)** — code matches brief Step 1C but contradicts brief's Render-env-var paragraph; deployment ordering must be honored |
| 7 | No new schema / migration / `slugs.yml` | clean |
| 8 | Heartbeat probe doesn't raise out | clean (early-return matches brief Step 4) |
| 9 | `SCHEDULER_LOCK_KEY = 8800100` collision check | clean |
| 10 | Test cleanup (`release_singleton_lock` first + `try/finally`) | clean (better than brief sketch) |

## Action for AI Head A

- Confirm `POSTGRES_HOST_DIRECT` is set on Render via MCP merge mode **before** merge (per brief §"Render env var (Director action)"). If unset, the scheduler will not run at all post-deploy until the env lands and the next deploy completes. See report §2.
- Pre-existing collision: `orchestrator/financial_detector.py:76` and `orchestrator/initiative_engine.py:630` both use `pg_try_advisory_xact_lock(900300)`. Surfaced incidentally during concern-9 grep. **Out of scope for PR #84** — flag for follow-up brief if deemed actionable.

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
