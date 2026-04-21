# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (fresh terminal tab)
**Task posted:** 2026-04-21 (post-B2-diagnostic)
**Status:** OPEN — STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1

---

## Task: Implement STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1

Brief: `briefs/BRIEF_STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1.md` (this commit). Self-contained. Read end-to-end — small but load-bearing.

**Why you:** you wrote the bridge that produces the `payload->>'alert_body'` shape. Best positioned to align the Step 1-5 consumers against that canonical source.

**Brief reference for context:**
- B2's diagnostic: `briefs/_reports/B2_pipeline_diagnostic_20260421.md` (commit `1ac8ed0`)
- Your bridge implementation: `kbl/bridge/alerts_to_signal.py` (merged at commit `2ca3865`, enhanced with hot.md at PR #29 merge)

---

## Scope summary (full detail in brief)

1. **Redirect all step readers from `raw_content` to `COALESCE(payload->>'alert_body', summary, '') AS raw_content`** in 4 step consumer files (verify exact file list via grep before editing). Alias preserved so downstream code doesn't need refactoring.
2. **Fix test fixtures** in 5 affected test modules. Create shared `tests/fixtures/signal_queue.py::insert_test_signal()` helper if none exists.
3. **NEW integration test** at `tests/test_bridge_pipeline_integration.py` — uses `alerts_to_signal.map_alert_to_signal` to produce a live-shape row, then calls pipeline tick, asserts advance past triage. Uses `needs_live_pg`.
4. **Recovery UPDATE** for 15 stranded rows — SQL in brief §Fix 4. Include verbatim in your ship report. **AI Head runs it Tier B, post-merge, with Director's explicit "yes."** You do NOT run it.

---

## Critical constraints (from brief)

- **Do NOT touch `pipeline_tick.py:359-365` emit_log block.** B2 called out that diagnostic-friendliness (surfacing exact SQL on failure) saved this investigation. Preserve it.
- **No schema changes.** Code fix only. Do not add a `raw_content` generated column.
- **Fallback is a safety net, not a cover-up.** COALESCE documented with a comment at each site explaining intent: future producers writing to a new column should surface as errors, not silent empty-string degradations.
- **No force push.** Same branch if amending, new branch if starting fresh.

---

## Pre-merge verification (per B3's N3 lesson)

Your ship report MUST include:
1. Grep output confirming all `SELECT raw_content` references in `kbl/steps/` are redirected (zero remaining).
2. All affected step unit tests green.
3. New bridge → Step-1 integration test green.
4. Recovery UPDATE SQL verbatim in the report.
5. Confirmation `emit_log` at `pipeline_tick.py:359-365` is untouched.

---

## Deliverable

**PR on baker-master.** Branch: `step-consumers-signal-content-source-fix-1`. Base: `main`. Reviewer: **B3** (fresh from PR #29 review, familiar with both bridge + pipeline).

Ship report: `briefs/_reports/B1_step_consumers_fix_ship_20260421.md` on baker-master.

Commit message: `fix(pipeline): STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1 — align step readers with bridge payload shape`

## Expected duration

S — 1-4h per B2's estimate. Flag if > 5h (means scope is bigger than the diagnostic anticipated).

## After this

AI Head auto-merges on B3 APPROVE per Tier A. Then:
1. Wait for Render deploy (~3 min).
2. Director authorizes recovery UPDATE → AI Head runs it.
3. Wait one pipeline tick cycle (~120s).
4. Verify signals advance past triage + kbl_cost_ledger gets rows.
5. **Gate 1 unblocks.** 5-10 end-to-end signals close it.

Close tab after ship.
