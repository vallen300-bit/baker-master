---
brief_id: CAPABILITY_RUNNER_COST_RUNAWAY_DIAGNOSTIC_1
authored_by: lead (AH1)
authored_at: 2026-05-25
director_ratified: 2026-05-25 (chat — "go" after lead proved Gmail polling fix only addresses the symptom downstream of the cost breaker)
target: b4
reply_target: lead (AH1)
expected_time: ~1-2h
complexity: Low (read-only investigation)
type: READ-ONLY DIAGNOSTIC (no code changes — investigate + propose only)
target_repo: baker-master (single repo)
matter_slug: baker-internal
peer_brief: GMAIL_ATTACHMENT_VISIBILITY_PATCH_1 (PR #259, merged 11:00:44Z — addresses visibility on a different defect downstream of this cost breaker)
followup_brief: CAPABILITY_RUNNER_COST_FIX_1 (NOT this brief — sized by lead from your diagnosis)
---

# BRIEF: CAPABILITY_RUNNER_COST_RUNAWAY_DIAGNOSTIC_1 — diagnose the €100/day capability_runner spend that's tripping the cost breaker daily since 2026-05-21

## Context

### Surface contract: N/A — pure read-only investigation. No code changes, no DB writes, no LLM calls, no schema edits. Only SQL SELECTs against api_cost_log + code reads via Read/Grep.

**Defect:** `capability_runner` (source attribution in `api_cost_log.source`) is driving 80% of Baker's daily LLM spend. The `COST_HARD_STOP_EUR=100.0` circuit breaker (`orchestrator/cost_monitor.py:50`) trips every day at ~05:40Z, blocking all downstream LLM-dependent paths (document classification, Tier-2 message extraction, etc.) until midnight UTC reset.

Cost breaker first tripped 2026-05-21 — has tripped every day since (per b4's diagnostic §2e: 2026-05-21 €115.31, 2026-05-22 €104.19, 2026-05-23 €103.58, 2026-05-24 €115.86, 2026-05-25 €104.88 so far at 08:50Z). The breaker is correctly doing its job — but the root cause of the spend explosion is not yet named.

**Lead's pre-flight signal-gathering (2026-05-25 ~11:30Z, via baker_raw_query MCP):**

Last 24h `api_cost_log` aggregation by source:

| source | calls | EUR |
|---|---|---|
| `capability_runner` | 1,172 | 104.83 |
| `pipeline` | 348 | 24.04 |
| `agent_loop_synthesis` | 3 | 2.29 |
| `email_draft` | 75 | 2.13 |
| (10 more long-tail sources) | ~2,200 | <€2 each |

Capability breakdown of the 1,172 `capability_runner` calls:

| capability_id | matter_slug | calls | EUR |
|---|---|---|---|
| `finance` | **(none)** | 624 | 65.99 |
| `legal` | **(none)** | 500 | 35.75 |
| `game_theory` | (none) | 25 | 0.87 |
| `research` | (none) | 7 | 0.69 |
| `sales` | (none) | 4 | 0.61 |
| 3 long-tail (russo_at, russo_fr, synthesizer) | (none) | <10 | <€0.30 each |

**Two smoking signals:**
1. **ALL 1,172 calls have `matter_slug = NULL`.** Properly-routed Cortex calls (matter-scoped) carry matter_slug. NULL means these are firing from a non-matter source — a sentinel sweep, scheduled job, sidebar query, or runaway dispatch.
2. **Concentration overnight (00:00Z-05:40Z UTC, every day).** Hourly pattern:

| hour (UTC) | finance calls | finance EUR | legal calls | legal EUR |
|---|---|---|---|---|
| 2026-05-25 00:00Z | 79 | 9.76 | 39 | 3.03 |
| 2026-05-25 01:00Z | 125 | 15.58 | 144 | 13.67 |
| 2026-05-25 02:00Z | 79 | 9.68 | 167 | 10.26 |
| 2026-05-25 03:00Z | 123 | 8.92 | 54 | 2.75 |
| 2026-05-25 04:00Z | 89 | 9.54 | 25 | 2.23 |
| 2026-05-25 05:00Z | 41 | 3.35 | 31 | 1.45 |
| 2026-05-25 06:00Z+ | **0** (breaker tripped at 05:40Z) | | | |
| 2026-05-24 12:00Z (prior day) | 15 | 1.15 | 15 | (low) |

So nighttime cron-like burst spends the €100 budget in ~5 hours, then breaker blocks all downstream pipeline work the rest of the day until midnight UTC reset.

**Lead's hypothesis (medium-low confidence — b4 to confirm/refute):**

Some scheduler (APScheduler / sentinel / startup task / cron) fires finance + legal capabilities ~25-40 times per hour with NO matter context. Likely causes (top 4):
1. **Sentinel sweep loop** — a sentinel like `cortex_stuck_cycle_sentinel` or similar iterates over an unbounded set (all matters, all signals, all "trigger" rows) and invokes capability_runner per-iteration without dedup.
2. **Re-dispatch on every poll** — a poll cycle that should fire ONCE per signal is firing EVERY cycle (no watermark or processed-flag).
3. **Startup backfill** — a Render restart triggers a backfill that ranges over historical data without bound. Lesson #10 anti-pattern: "Startup backfill OOM — backfill_fireflies ran pipeline.run() on 50 transcripts every deploy."
4. **Cortex Phase-3 specialist over-firing** — Phase 3b invokes domain specialists; finance + legal are 2 of the 5 spec'd specialists. If Phase 3 fires from a meta-trigger that lacks dedup/cap-per-cycle, it could explode.

This brief is **strictly read-only investigation.** No code edits. Lead authors `CAPABILITY_RUNNER_COST_FIX_1` after b4's diagnosis names the root cause.

**Anchor lessons:**
- `tasks/lessons.md` §"Startup backfill OOM" (Lesson #?): "`backfill_fireflies()` ran pipeline.run() + Qdrant embed on 50 transcripts every deploy — 3.2GB spike → OOM."
- `tasks/lessons.md` §"Concurrent startup tasks": "Render rolls two instances during deploy — both ran backfill simultaneously, doubling memory."
- `tasks/lessons.md` §"Skip exploration": "SPECIALIST-UPGRADE-1 with 5-7x wrong cost estimates — always read code + check DB schema first."

## Estimated time: ~1-2h
## Complexity: Low (read-only)
## Prerequisites
- Read access to `api_cost_log` table via `baker_raw_query` MCP or direct Postgres.
- Read access to `scripts/`, `triggers/`, `orchestrator/`, `outputs/dashboard.py`.
- Render log API access (lead provides key in dispatch envelope if needed for cross-verification).

---

## Step 1 — Confirm signal: per-capability + per-hour explosion (15 min)

### Goal
Independently verify lead's pre-flight aggregation. Re-run the SQL queries below, paste raw output into report. If your numbers differ materially from lead's, surface in report intro — they may have shifted since 11:30Z.

### SQL queries (run all 4, paste output into report)

```sql
-- Q1: source breakdown last 24h
SELECT source, COUNT(*) AS calls, SUM(cost_eur)::numeric(10,4) AS eur
FROM api_cost_log
WHERE logged_at > NOW() - INTERVAL '24 hours'
GROUP BY source
ORDER BY eur DESC
LIMIT 20;

-- Q2: capability_runner breakdown by capability_id + matter_slug
SELECT capability_id, COALESCE(matter_slug,'(none)') AS matter,
       COUNT(*) AS calls, SUM(cost_eur)::numeric(10,4) AS eur
FROM api_cost_log
WHERE source = 'capability_runner'
  AND logged_at > NOW() - INTERVAL '24 hours'
GROUP BY capability_id, matter_slug
ORDER BY eur DESC
LIMIT 30;

-- Q3: hourly burst pattern (finance + legal only)
SELECT date_trunc('hour', logged_at) AS hour, capability_id,
       COUNT(*) AS calls, SUM(cost_eur)::numeric(10,4) AS eur
FROM api_cost_log
WHERE source = 'capability_runner'
  AND capability_id IN ('finance','legal')
  AND logged_at > NOW() - INTERVAL '24 hours'
GROUP BY 1, 2
ORDER BY hour DESC, eur DESC
LIMIT 50;

-- Q4: task_id distribution — are calls for ONE recurring task or N distinct tasks?
SELECT task_id, capability_id, COUNT(*) AS calls,
       SUM(cost_eur)::numeric(10,4) AS eur,
       MIN(logged_at), MAX(logged_at)
FROM api_cost_log
WHERE source = 'capability_runner'
  AND capability_id IN ('finance','legal')
  AND logged_at > NOW() - INTERVAL '24 hours'
GROUP BY task_id, capability_id
ORDER BY eur DESC
LIMIT 30;
```

### What Q4 tells us
- If task_id is highly concentrated (1-10 distinct task_ids dominating spend) → SINGLE looping task. Look for the dispatch site that builds that task_id.
- If task_id is uniform-NULL → caller isn't setting task_id. Read capability_runner.py to find callers that don't pass task_id.
- If task_id is unique-per-call → genuine fan-out from a real source feeding 100s of distinct tasks. Look at signal_queue / triggers for the source.

---

## Step 2 — Identify capability_runner callers (20 min)

### Goal
Find every code site that invokes capability_runner with capability_id in {`finance`, `legal`}. Note which set matter_slug, which don't.

### Commands

```bash
# All sites that import or call capability_runner
grep -rn "from orchestrator.capability_runner import\|capability_runner\.\|run_single\|run_multi\|run_streaming\|run_synthesizer" --include="*.py" -l .

# Read each match site — note which pass matter_slug + which don't
grep -rn "capability_runner" --include="*.py" -n . | head -40

# Find dispatch points that select capability by id
grep -rn "capability_id.*['\"]finance['\"]\\|capability_id.*['\"]legal['\"]" --include="*.py" -n .

# Find scheduled invocations (APScheduler, cron, periodic tasks)
grep -rn "scheduler\.add_job\|add_periodic_task\|@scheduled\|trigger.*Interval\|trigger.*Cron" --include="*.py" -n .
```

### Output to report
List of (file, line, calls capability_id=finance|legal, sets matter_slug yes/no, fired from: { scheduler / sentinel / signal_queue / sidebar / startup / explicit }).

---

## Step 3 — Identify the trigger source (30 min)

### Goal
For each suspect caller from Step 2, trace back to what triggers it. Three possible classes:

1. **Scheduled job (cron / APScheduler / Render startup hook).** Search `embedded_scheduler.py`, `triggers/`, `outputs/dashboard.py` for `add_job`, `register_job`, `app.on_event("startup")`, periodic intervals.
2. **Signal-driven (signal_queue → Cortex Phase 1-3).** Search for `signal_queue` reads + Cortex Phase 3 dispatch sites. Check if Phase 3 is firing on every signal without dedup.
3. **Sentinel sweep (auto-iterate over matters / signals / rows).** Search `*_sentinel*.py` for loops over `cortex_phase_outputs`, `signal_queue`, `proposals`, `matters`, etc.

### Commands

```bash
# Scheduled jobs
grep -rn "add_job\|scheduler\.\|app\.on_event\|@app\.on_event\|background_tasks\.add_task" --include="*.py" -n . | grep -v test | head -30

# Sentinel sweeps
ls scripts/*sentinel*.py orchestrator/*sentinel*.py 2>&1
grep -rn "capability_runner\|run_single\|run_multi" scripts/*sentinel*.py orchestrator/*sentinel*.py 2>&1

# Cortex Phase 3 / Phase 3b dispatch
grep -rn "phase_3\|phase3\|invoke_specialist\|Phase 3" --include="*.py" -n . | head -30
```

### Output to report
The named trigger source for each suspect caller. Cite file:line.

---

## Step 4 — Read the runaway code path (30 min)

### Goal
For each high-volume caller from Step 3, read the actual code path. Look for:

1. **Missing dedup** — does it check "have I already processed this signal/row/task before invoking?" If not, every poll/sweep re-dispatches.
2. **Unbounded iteration** — does it `LIMIT` the per-cycle batch? If not, a backlog spike compounds.
3. **Missing watermark** — does it advance a `last_processed_at` after each cycle? If not, every cycle re-processes the same set.
4. **Per-iteration LLM call inside an outer loop** — pattern like `for signal in signals: run_single(capability="finance", ...)`. That's quadratic if signals is large.
5. **Recursive dispatch** — capability X dispatches capability Y which dispatches X. Cycle detection?
6. **Render restart double-fire** — `app.on_event("startup")` task running on both instances during deploy.

### Anchor reading
- `orchestrator/capability_runner.py` (1400+ LOC; specifically the `run_single` + `run_multi` entry points + any synthesizer that fan-outs)
- `orchestrator/cortex_runner.py` (Cortex 6-phase orchestrator)
- `orchestrator/cortex_phase3*.py` (Phase 3 specialist invocation; finance + legal are 2 of 5 specs)
- `triggers/*.py` (any trigger that feeds Cortex)
- `scripts/*sentinel*.py`
- `outputs/dashboard.py` lines around `app.on_event("startup")` + APScheduler registration

### Output to report
Annotated code snippet of the runaway path (with line numbers) + a single-paragraph explanation of WHY it's firing 600+ times/day. Confidence rating (high / medium / low).

---

## Step 5 — Cross-check against b4's GMAIL_POLLING_DIAGNOSTIC_1 finding (10 min)

### Goal
The Gmail polling silent-swallow b4 diagnosed is downstream of this cost breaker. After the breaker trips at 05:40Z, EVERY downstream classify/extract call is blocked (per b4 §2e Render logs: `"Extraction skipped (circuit breaker at EUR 104.87)"`, `"Document classification blocked by circuit breaker"`). So this brief's defect compounds b4's defect.

### Output to report
One paragraph: is the capability_runner runaway INDEPENDENT of the Gmail polling silent-swallow, or are they linked? (Lead's pre-flight read says independent — different code paths, different timestamps. Confirm or refute with evidence.)

---

## Step 6 — Recommend fix shape (15 min)

### Goal
Based on Steps 1-4 root-cause naming, propose 1-3 fix-shape options for the lead to size into `CAPABILITY_RUNNER_COST_FIX_1`. Examples:

- **Option A — kill the runaway dispatch entirely** (if it's a bug, not a feature)
- **Option B — add per-cycle cap** (e.g. max 5 finance + 5 legal calls per cycle, queue the rest with backoff)
- **Option C — add watermark / dedup** (each signal/row processed once, not every cycle)
- **Option D — switch model tier** (if finance/legal can run on Sonnet/Haiku instead of Opus, ~5-10x cost reduction)
- **Option E — make it matter-scoped** (every call must have matter_slug; reject NULL matter)
- **Option F — short-term mute** (raise breaker to €200 + queue the long fix; for filing-deadline-week)

For each option: rough effort estimate (S/M/L), risk, and impact on the daily €100 breaker trip.

### Output to report
Top 2-3 recommended options ranked by impact:effort ratio. DO NOT pick a winner — lead picks after seeing your evidence chain.

---

## Step 7 — Write the report (15 min)

### Goal
Single markdown file at `briefs/_reports/B4_capability_runner_cost_runaway_diagnostic_1_20260525.md` (mirror the structure of `briefs/_reports/B4_gmail_polling_diagnostic_1_20260525.md`).

### Required sections
1. **Bottom line** (1 paragraph: what's broken + confidence rating)
2. **Evidence chain** (Q1-Q4 SQL output, hourly pattern, caller list, code-path map with file:line)
3. **What's broken vs what's working** (table — same shape as b4's §3)
4. **Recommended fix shape** (1-3 options ranked, no winner picked)
5. **Risks of recommended fix** (1 sentence per option)
6. **Investigation steps — what ran, what didn't** (table — same shape as b4's §"Investigation steps")
7. **References** (cite all files read with full path + line numbers)

### Ship via bus
- Bus-post to `lead` with topic `diag/capability-runner-cost-runaway-1`.
- Body: 1-paragraph TL;DR with confidence rating, then path to full report, then top 2-3 fix-shape options + their relative impact:effort ratio.

---

## Files Modified

NONE. This brief is strictly read-only.

You will create exactly ONE new file: `briefs/_reports/B4_capability_runner_cost_runaway_diagnostic_1_20260525.md` (your diagnostic report). No edits to existing files. No DB writes. No LLM calls (besides Claude Code's own session, which doesn't write to `api_cost_log`).

## Do NOT Touch

- `orchestrator/cost_monitor.py` — investigate, do NOT raise/lower breaker thresholds.
- `orchestrator/capability_runner.py` — investigate, do NOT modify call sites.
- `orchestrator/cortex_runner.py` + `cortex_phase3*.py` — investigate, do NOT modify dispatch logic.
- `triggers/*.py` — investigate, do NOT modify polling cadence or trigger registration.
- `embedded_scheduler.py` — investigate, do NOT modify scheduled jobs.
- `outputs/dashboard.py` — investigate the startup hook + APScheduler registration only, do NOT modify any endpoint.
- `api_cost_log` table — read-only SELECT, no UPDATE/DELETE/INSERT.
- The cost circuit breaker setting — do NOT raise from €100 to €200 even if "obvious fix"; raising the cap is a Director-ratification-required decision (Tier C-adjacent).

## Quality Checkpoints

1. Q1-Q4 SQL queries run + raw output pasted into report.
2. Caller list (Step 2) names every code site invoking capability_runner with finance/legal capability_id.
3. Trigger source (Step 3) named with file:line for each suspect caller.
4. Runaway code path (Step 4) read + annotated in report with file:line.
5. Cross-check with b4's GMAIL_POLLING_DIAGNOSTIC_1 (Step 5) — explicit "independent" or "linked" judgment with evidence.
6. Top 2-3 fix-shape options recommended with effort/risk/impact (Step 6); NO winner picked.
7. Report shape mirrors `briefs/_reports/B4_gmail_polling_diagnostic_1_20260525.md` (use it as template).
8. Confidence rating named in bottom line (high/medium-high/medium-low/low).
9. ZERO code edits, ZERO DB writes, ZERO LLM calls beyond Claude Code session.
10. Ship report bus message to `lead` with topic `diag/capability-runner-cost-runaway-1`.

## Verification SQL

N/A — this brief is the SQL investigation itself. The 4 SQL queries in Step 1 ARE the verification.

## Gate chain (after report ships)

- No gate chain for a read-only diagnostic. Lead reads your report, sizes `CAPABILITY_RUNNER_COST_FIX_1`, dispatches to whichever b-code is free. Same pattern as b4's GMAIL_POLLING_DIAGNOSTIC_1 → GMAIL_ATTACHMENT_VISIBILITY_PATCH_1 → (future) GMAIL_POLLING_FIX_1 chain.

## Reply target

Post your ship report bus message to **lead (AH1)** with topic `diag/capability-runner-cost-runaway-1`. Include: confidence rating (high/medium-high/medium-low/low), 1-paragraph TL;DR with top 2-3 fix-shape options + their impact:effort ratio, path to full report file.

## Director context

Director ratified this brief's authorization at 2026-05-25 ~11:30Z chat after lead surfaced the capability_runner = 80%-of-daily-spend signal in the cost-breaker observation window for PR #259 (Gmail attachment visibility patch). The ratification phrase: "go".

This is a **peer-defect to the Gmail polling outage** — both surfaced from b4's prior GMAIL_POLLING_DIAGNOSTIC_1 report (§2e + §"Out of scope"). Fixing one without the other leaves Baker degraded: the visibility patch (PR #259) helps the polling team diagnose, but the cost breaker still trips daily at 05:40Z and blocks downstream classify/extract for the rest of the day. Both fixes are needed for full recovery.

Authority class: Tier A (lead-authored read-only diagnostic brief, no code changes, no LLM calls).

## What NOT to do

- Do NOT modify any code in this brief. Read-only investigation.
- Do NOT call any LLM beyond Claude Code's session. Specifically: do NOT invoke `baker_grok_ask`, `baker_grok_web_search`, `mcp__baker__baker_actions`, or any other baker MCP that hits an LLM provider — those would ADD to `capability_runner` / `pipeline` spend you're investigating.
- Do NOT raise the cost breaker threshold. That's a Director decision after fix-shape ratification.
- Do NOT execute the proposed fix. This brief is diagnose-only.
- Do NOT bulk-DELETE rows from `api_cost_log` to "clean up." It's historical accounting.
- Do NOT dispatch finance or legal capability calls during your investigation — your manual triggering would skew the very table you're analyzing.
- Do NOT scope-creep into the Gmail polling defect — that's PR #259 + (future) `GMAIL_POLLING_FIX_1` lane. If you find them linked, name the link in Step 5; don't propose joint fixes here.
- Do NOT skip the SQL output paste — Quality Checkpoint #1 requires literal Q1-Q4 output in the report.
- Do NOT skip the file:line citations — Quality Checkpoint #2-#4 require file:line for every caller, trigger source, and code-path annotation.
- Do NOT propose a single "winner" fix shape — Step 6 requires 2-3 options with effort/risk/impact; lead picks.
