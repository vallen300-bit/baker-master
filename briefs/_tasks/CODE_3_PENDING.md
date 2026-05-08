---
status: PENDING
brief: briefs/BRIEF_BACKFILL_THREADED_POOL_AND_OBSERVABILITY_1.md
trigger_class: TIER_B_OBSERVABILITY_PLUS_CONCURRENCY_HARDENING
dispatched_at: 2026-05-08T~11:55Z
dispatched_by: ai-head-a (terminal)
director_ratification: "go" (2026-05-08 chat verbatim, this session — explicit dispatch instruction "dispatch BRIEF_BACKFILL_THREADED_POOL_AND_OBSERVABILITY_1")
folds: 4 IMPORTANT findings from am handover session_handover_2026-05-08_am_aihead_a_plaud_token_restored_3_transcripts.md
---

# CODE_3_PENDING — BRIEF_BACKFILL_THREADED_POOL_AND_OBSERVABILITY_1

**Brief:** `briefs/BRIEF_BACKFILL_THREADED_POOL_AND_OBSERVABILITY_1.md`
**Working branch:** `b3/backfill-threaded-pool-and-observability-1`
**Working dir:** `~/bm-b3/`

**Pre-requisites:**
- baker-master `main` HEAD ≥ `bdb6416` (PR #170 merged earlier this session — doc-only, does not change code surface).
- PR #172 (`d8ebf17`) on main — your fix layers on top.
- Python 3.12 local for pytest (per Lesson #62, MacBook 3.9 default breaks PEP 604).

**Acceptance criteria (literal — REQUEST_CHANGES on any "by inspection" claim):**
1. `pytest tests/test_backfill_chain_order_and_timeout.py tests/test_store_back_pool_threadsafe.py -v` → all green, paste literal stdout in ship report.
2. `pytest tests/ -k "store_back or pool or backfill" -v` → no regression, paste literal stdout.
3. `bash scripts/check_singletons.sh` → green.
4. `python3 -c "import py_compile; py_compile.compile('memory/store_back.py', doraise=True)"` clean for all 5 modified Python files.
5. `grep -n "_run_backfill_with_timeout" outputs/dashboard.py` → zero matches post-edit (legacy alias removed per Fix 4).
6. `grep -n "report_success" triggers/plaud_trigger.py` → must show ≥1 new call inside `backfill_plaud()` lines 668-775 (in addition to the 3 existing calls in the incremental poller at lines 400/429/624).
7. `grep -n "report_success\|report_failure" triggers/fireflies_trigger.py` → must show ≥1 new call inside `backfill_fireflies()` lines 452-611 success terminus + ≥1 in the failure terminus.
8. `grep -n "ThreadedConnectionPool" memory/store_back.py` → exactly 1 match at line ~226; `grep -n "SimpleConnectionPool" memory/store_back.py` → 0 matches in code (comments OK if you reference the historical class).
9. New abandoned-thread alarm fires `report_failure("<name>_backfill", ...)` — covered by `test_abandoned_thread_increments_counter_and_fires_sentinel_alarm`.

**Scope-out (DO NOT touch — REQUEST_CHANGES if your diff hits any of these):**
- `pipeline.run()`, Qdrant, LLM call sites — backfill stays PG-only.
- Advisory lock IDs `867531` / `867532` — stable contract.
- `_backfill_running` flag semantics — stays process-local.
- Incremental poller `report_success` calls (lines 400/429/624 plaud, line 443 fireflies) — already report; do NOT add another.
- `BACKFILL_TIMEOUT_SEC = 300` — enforced by existing test.
- `pg_try_advisory_lock` / `pg_advisory_unlock` flow — NO "release on timeout" or "second-attempt-by-fresh-thread" logic. Render restart IS the recovery path.

**Ship gate:** literal `pytest` output AND `bash scripts/check_singletons.sh` green AND grep verifications #5-#8 pasted into ship report. No "pass by inspection".

**PR target:** open against `main` of `vallen300-bit/baker-master`. Title: `fix(backfill): sentinel-on-success + thread-safe pool + abandoned-thread alarm + real chain test`. Body: brief acceptance criteria checklist + literal pytest output + grep verifications.

**PL ship-report:** End your chat ship report with a fenced PL paste-block per SKILL.md §"PL ship-report contract" (target: AH1-App PL).

**Heartbeat cadence:** minimum every 12h while actively building (per SKILL.md §"B-code stall chase" 2026-05-05 ratification). Heartbeat formats accepted: mailbox UPDATE entry, ship-report file, commit-msg `mailbox(b3): heartbeat <ISO> — <where>`.

**N1 carryover from PR #170 (NOT applicable to this brief):** N1 was about the heuristic-shippable risk in `BRIEF_BAKER_PLAUD_AUTO_GENERATE_1.md` — that is a separate brief / future B-code dispatch when the implementation lands. This brief is unrelated; do not fold N1 here.
