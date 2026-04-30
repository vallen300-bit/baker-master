# BRIEF — AUTO_TRIGGER_FAN_OUT_VERIFY_1

**Owner:** B-code (assigned: B1)
**Author:** AI Head A (App)
**Drafted:** 2026-04-30
**Priority:** CRITICAL
**ETA:** 2026-05-01
**Roadmap item:** `auto-trigger-fan-out-verify` (V4 queued)

## Problem

Today auto-trigger fires Cortex cycles on AO matter only — historical cost-gate scope. Wave 1 Track 2 shipped multi-matter cost-gate, but we have not verified that incoming signals classified onto non-AO matters actually fan out and fire cycles. Without this verification, all 22 matter brains sit dormant for auto-trigger; only Director's manual-invoke fires non-AO cycles.

## Goal

Confirm cost-gate accepts ANY of the 22 matters in `slugs.yml` (filter `status != retired`), and a non-AO signal injected via curl fires a Cortex cycle on that matter.

## Scope (verification, no code change unless gap found)

1. **Pick 3 non-AO test matters** from `baker-vault/slugs.yml` head: `hagenauer-rg7`, `mo-vie-am`, `lilienmatt`.
2. **Curl-test:** for each test matter, inject a synthetic signal via `/api/test/inject-signal` (or whatever the existing internal endpoint is — check `routes/sentinel.py` or similar; if no test endpoint exists, use direct `INSERT INTO signals(...)` via Render psql).
3. **Verify:**
   - Signal classifies onto the target matter (`signal_classifications` row, `matter_slug = <target>`).
   - Cost-gate fires (check `cost_gate_decisions` log for that matter).
   - Cycle starts (check `cortex_cycles` row, status `started`/`running` for that matter within 60s).
4. **Document outcome:** ship report at `briefs/_reports/B1_auto_trigger_fan_out_verify_20260430.md`. List 3 matters tested, status of each, any gap surfaced.

## If gap surfaced

If cost-gate rejects a non-AO matter OR cycle does not fire:
- **STOP.** Do not patch in this brief.
- File the gap as a new V4 queued item via paste-block to AI Head A.
- AI Head A authors a follow-up patch brief.

## Non-goals

- No code changes in this brief (verification only).
- Do not test all 22 matters — 3 representative samples suffice.

## Test plan

- 3 curl injections.
- 3 DB observations.
- Ship report listing each.

## Done definition

- Ship report posted with PASS/FAIL per matter.
- If all 3 PASS → mark `auto-trigger-fan-out-verify` DONE in V4 YAML.
- If any FAIL → file gap, leave queued item open with new note.
