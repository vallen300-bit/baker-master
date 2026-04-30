# CODE_1 — PENDING (AUTO_TRIGGER_FAN_OUT_VERIFY_1)

**Status:** PENDING — dispatched 2026-04-30 by AI Head A (App)
**Brief:** `briefs/BRIEF_AUTO_TRIGGER_FAN_OUT_VERIFY_1.md`
**Builder:** B1
**Priority:** CRITICAL
**ETA:** 2026-05-01

## Task summary

Verification work — confirm cost-gate accepts ANY of 22 matters and a non-AO signal fires a Cortex cycle. Pick 3 test matters: `hagenauer-rg7`, `mo-vie-am`, `lilienmatt`. Curl-test signal injection + DB observation. NO code changes unless gap surfaced — file gap as paste-block to AI Head A if found.

## Dispatch

1. Read brief: `briefs/BRIEF_AUTO_TRIGGER_FAN_OUT_VERIFY_1.md`
2. Branch: `b1/auto-trigger-fan-out-verify`
3. Pre-pytest re-checkout ritual applies for any test runs.
4. Ship report: `briefs/_reports/B1_auto_trigger_fan_out_verify_20260430.md`
5. PR open + AI Head A self-review + merge.

## Previous task (closed)

PR #90 (CORTEX_RUN_SCAN_UI_RENDER_1) shipped 2026-04-30T06:13Z, hotfix PR #91 merged 06:11Z. Wave 2 #1 closed.
