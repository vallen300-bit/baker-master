# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (fresh terminal tab)
**Task posted:** 2026-04-21 (post-BRIDGE_HOT_MD_AND_TUNING_1 merge + hot.md seed)
**Status:** OPEN — pipeline diagnostic (Steps 2-7 frozen)

---

## Task: Diagnose why signal_queue rows freeze at `stage=triage, status=processing`

**This is a DIAGNOSTIC, not a fix.** Read the existing pipeline code, trace what happens after a row is inserted into `signal_queue`, identify where the 15 current rows got stuck, report findings. A fix will be a separate brief once we know what's broken.

---

## Context

The bridge (merged 2026-04-20, now enhanced with hot.md axis merged 2026-04-21) is producing rows into `signal_queue`. As of handover: **15 rows present, 0 advanced past `stage=triage, status=processing`.** Every downstream column (triage_score, triage_summary, triage_confidence, enriched_summary, step_5_decision, target_vault_path, commit_sha) is NULL.

Which means Step 1 works, Steps 2-7 aren't running — OR they ran briefly and errored silently.

**Cortex T3 Gate 1 requires ≥5-10 signals through Steps 1-7 end-to-end.** This diagnostic unblocks that gate. It is the single highest-leverage investigation we have open right now.

---

## Scope

1. **Find the pipeline tick entry point.** Start at `triggers/embedded_scheduler.py` — look for `kbl_pipeline_tick` or similar APScheduler job. Trace what function it calls.
2. **Trace the state machine.** `signal_queue.stage` and `signal_queue.status` columns drive it. Map the intended transitions: what stage follows triage? What moves a row from `status=processing` to `status=completed`?
3. **Identify the blocking step.** Is it:
   - (a) Pipeline tick not firing at all (check `/health` for the job; check logs for tick heartbeats)
   - (b) Pipeline tick firing but finding nothing to do (e.g., reads from wrong stage/status)
   - (c) Pipeline tick attempting Step 2+ but erroring silently (swallowed exception, no log)
   - (d) Step 2+ code doesn't exist yet — pipeline was shadow-mode only
4. **Check live data.** Use `mcp__baker__baker_raw_query` to inspect the 15 rows' `result`, `processed_at`, `started_at`, `stage`, `status` + any extracted fields. Compare with any error log around the tick time.
5. **Report the root cause** — which of (a)–(d), or something else — with evidence (code path, log line, SQL result).

---

## Key files to read (start here)

- `triggers/embedded_scheduler.py` — APScheduler job registration. Find `kbl_pipeline_tick`.
- `kbl/pipeline/` or `kbl/triage/` — likely home of the state-machine code. Grep for `stage=` and `status=` in UPDATE statements.
- `outputs/dashboard.py` line ~448+ — FastAPI startup hook registers the scheduler. Verify `kbl_pipeline_tick` is in the registered list (not just the bridge tick).
- Render logs: grep for "pipeline_tick" or "triage" around last tick timestamps to see what it's doing.

## Read-only scope

Do NOT write fixes. Do NOT modify pipeline code. ONE-line stop-gap exceptions (e.g., "add a logger.warning where a swallow was silent") should be flagged in the report as recommendations, not shipped.

---

## Deliverable

File: `briefs/_reports/B2_pipeline_diagnostic_20260421.md` on baker-master.

Structure:
- **Root cause:** one sentence
- **Evidence:** code references + log excerpts + SQL results
- **Unblock effort estimate:** XS (< 1h) / S (1-4h) / M (half-day) / L (> day)
- **Proposed next brief:** one-line description of what needs to ship to close Gate 1

Tag AI Head in the commit message. AI Head writes the follow-up brief based on your report.

## Expected duration

~1-2 hours for the diagnostic. If it takes more than 3 hours, ping — likely means scope is bigger than expected (e.g., code doesn't exist vs. has a bug).

Close tab after report shipped.
