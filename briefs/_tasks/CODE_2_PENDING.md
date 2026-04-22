# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2
**Task posted:** 2026-04-22 ~11:52 UTC
**Status:** OPEN — `STEP5_EMPTY_DRAFT_INVESTIGATION_1` + Step 5 observability fix (bundled)

---

## Brief-route note (charter §6A)

Freehand dispatch. Continuation-of-work following your PR #40 Part B diagnostic. Director cleared "all outstanding" at 2026-04-22 ~11:48 UTC. Dispatching in parallel with B1's CLAIM_LOOP_RUNNING_STATES_3.

This brief has TWO interleaved goals — investigation + observability fix — because you can't diagnose Step 5 if Step 5 is log-silent. Add the `emit_log` calls first, then read the new logs to diagnose.

---

## Context — what your PR #40 Part B found

Quoting your report: **"13 of 19 `full_synthesis` rows have `LENGTH(opus_draft_markdown) = 0` — Opus wrote nothing. Smoking gun: body-floor is the reporter, not the cause."** You correctly punted to Step 5 investigation.

Since PR #40 shipped, the class has grown: **13 rows now at `finalize_failed` with `finalize_retry_count=3`**, each blocked on Step 6 body-too-short exhaustion because `opus_draft_markdown` was written empty. These are cost-paid, content-lost rows.

Your diagnosis had 3 branches:
1. Opus API transient error — Step 5 should raise, not persist empty.
2. Opus 200 OK empty `content[0].text` (content-filter / thinking-only) — Step 5 should detect + mark failed, not emit blank draft.
3. Step 5 capture path writes `''` on some exception branch.

AI Head CONFIRMED (by SQL): `kbl_log` has **zero** entries for `component='step5_opus'` in 48h. Observability gap #1 from your CORTEX_GATE2 report. **Step 5 imports `emit_log` but never calls it.** So we have no trace data to bisect the 3 branches — you need to add logging, then watch.

## Scope — 3 parts, ship together as one PR

### Part A — Add `emit_log` calls to `kbl/steps/step5_opus.py`

Match `kbl/steps/step6_finalize.py`'s shape. Minimum log points needed to bisect the 3 branches:

1. **Entry** — `INFO` on Step 5 entry: `emit_log("INFO", "step5_opus", signal_id, "step5 entry: decision=...")`.
2. **Opus call start** — `INFO` with model + token budget + prompt hash. Helps correlate cost + retries.
3. **Opus call return** — `INFO` with HTTP status (if available from client wrapper), response length in chars, stop_reason.
4. **Empty-content detection** — `WARN` if `content[0].text` is empty OR `content` list is empty. This is the critical branch-(2) signal.
5. **R3 reflip** — `WARN` on each reflip attempt: `emit_log("WARN", "step5_opus", signal_id, f"r3 reflip {attempt}/3: {reason}")`.
6. **Exception branches** — `ERROR` on each `except` block with the exception type + short message.
7. **Terminal states** — `INFO` on `opus_failed` / `paused_cost_cap` flip; `ERROR` on unexpected state.
8. **Draft written** — `INFO` with `draft_len` at write time. If draft_len is 0, log a WARN saying "wrote empty draft, step 6 will reject" — explicit smoking gun.

Use the exact `emit_log(level, component, signal_id, message)` signature from `step6_finalize.py:568-584`. Component string: `"step5_opus"`.

**Don't over-log.** Aim ~8 call sites total. Ship report lists each with file:line.

### Part B — Diagnose the 13 stuck rows

Run the SQL query from your PR #40 Part B again, expanded to ALL `finalize_failed` rows with empty `opus_draft_markdown`:

```sql
SELECT id, step_5_decision, primary_matter, finalize_retry_count,
       LENGTH(COALESCE(opus_draft_markdown,'')) AS draft_len,
       started_at, created_at, (NOW() - created_at) AS age
  FROM signal_queue
 WHERE status='finalize_failed'
   AND LENGTH(COALESCE(opus_draft_markdown,''))=0
 ORDER BY id DESC;
```

Then cross-reference with `api_cost_log` (it exists — AI Head saw it in `information_schema.tables`) to check if Opus was actually called for these signals:

```sql
SELECT acl.signal_id, acl.ts, acl.model, acl.input_tokens, acl.output_tokens,
       acl.cost_usd, acl.notes
  FROM api_cost_log acl
 WHERE acl.signal_id IN (<list from above>)
   AND acl.component LIKE '%step5%'
 ORDER BY acl.ts;
```

(Column names may differ — inspect `information_schema.columns` for `api_cost_log` first. Adapt the query.)

**Deliverable for Part B:** one paragraph answering three questions:
1. Was Opus actually called for the 13 rows? (If output_tokens=0 across the board → branch 1 or 2. If output_tokens>0 but draft empty → branch 3, capture bug.)
2. Any cost anomalies (unusually high or exactly 0)?
3. Any correlation with `primary_matter` (AI Head suspects hagenauer-rg7 over-routing bias).

No code changes for Part B. One data-backed paragraph.

### Part C — Re-queue decision (recommend, don't execute)

For the 13 stuck `finalize_failed` rows — what's the recovery path?

- Option A: `UPDATE signal_queue SET status='pending', step_5_decision=NULL, finalize_retry_count=0 WHERE id IN (...)` — re-enter the pipeline from Step 1. Costs another Opus pass on each.
- Option B: Leave terminal. Cortex won't see these 13 signals; triage if they're high-value.
- Option C: Wait — once Part A's logging is deployed, a follow-up brief can attempt replay with the new trace data.

**Recommend one**, don't execute. AI Head + Director choose after reviewing.

## Tests

### Part A tests (`tests/steps/test_step5_opus.py` or nearest existing Step 5 test file)

At minimum: 3 tests asserting `emit_log` is called in key paths. Mock `emit_log`, run a stub-path signal through Step 5 (if test fixtures exist), assert `emit_log.call_args_list` contains the expected (level, component, signal_id, message-prefix) tuples.

If no Step 5 test scaffold exists, add one minimal fixture + 3 tests. Don't retrofit a full test suite — that's out of scope.

### Full pytest gate

Run `pytest tests/`. Baseline post PR #40: `16 failed, 805 passed, 21 skipped`. Your additions should be `+N passed` with zero new failures. Any new failure → REQUEST_CHANGES on yourself.

## Out of scope (explicit)

- **No Step 5 logic change.** Only add `emit_log`. Don't touch retry ladder, Opus call, capture path.
- **No Step 6 changes.** `_body_length` floor stays. `finalize_retry_count` schema unchanged.
- **No re-queue execution.** Only recommend.
- **No fix for the empty-draft root cause.** That's the follow-up brief, informed by your diagnosis + the new logs.
- **Step 1 matter-routing / hagenauer-rg7 over-routing** — Cortex Design §4, Director territory. Note in report if you see it; don't act.

## Ship shape

- PR title: `STEP5_EMPTY_DRAFT_INVESTIGATION_1: add Step 5 observability + diagnose 13 stuck rows`
- Branch: `step5-empty-draft-investigation-1`
- Files: `kbl/steps/step5_opus.py` + new/existing step5 test file + ship report. 2-3 files.
- Commit style: one clean commit.
- Ship report path: `briefs/_reports/B2_step5_empty_draft_investigation_20260422.md`. Include:
  - Part A §before/after (line numbers + 8 log call-site listing)
  - Part B diagnostic paragraph with SQL results quoted
  - Part C recommendation with reasoning
  - Full pytest log head+tail (no "by inspection")
- Tier A auto-merge on B3 APPROVE.

**Timebox:** 3h. Split evenly: 1h Part A (logging), 1h Part B (SQL + analysis), 30min Part C + ship report, 30min buffer.

**Working dir:** `~/bm-b2`.

---

**Dispatch timestamp:** 2026-04-22 ~11:52 UTC (parallel with B1 RUNNING_STATES_3)
