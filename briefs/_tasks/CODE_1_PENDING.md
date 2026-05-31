---
dispatch: SCHEDULER_LIVENESS_REVIVE_1
to: b1
from: lead
dispatched_by: lead
status: COMPLETE
merged_anchor: PR #278 squash 7ce936f (G1+G2+G3 all PASS); deputy G3 #1469
dispatched_at: 2026-05-31T12:12:00Z
authored: 2026-05-31
brief_path: /Users/dimitry/bm-aihead1/briefs/BRIEF_SCHEDULER_LIVENESS_REVIVE_1.md
target_repo: baker-master
estimated_time: ~2-3h
complexity: Medium
brief_version: v2.2 @ main 3c0e849 (recut after codex FAIL-LIGHT #1444; PASS-WITH-NITS #1452; all 3 nits folded)
codex_pre_review: PASS-WITH-NITS bus #1452 (root cause re-scoped to listener persistence; 3 nits folded into v2.2)
deputy_concur: bus #1450 (G3 will focus on fallback-conn lifecycle)
reply_to: lead
ship_topic: ship/scheduler-liveness-revive-1
anchor_chat: Director 2026-05-31 "go" after codex PASS-WITH-NITS. Supersedes the v1 dead-watchdog premise. PR #273 AC1 re-verify FAILED (scheduler_job_liveness 0 rows since 06:31Z) because _job_listener drops scheduler_executions INSERTs under conn-pool exhaustion — NOT a #274 regression.
---

# b1 dispatch — SCHEDULER_LIVENESS_REVIVE_1

Read `briefs/BRIEF_SCHEDULER_LIVENESS_REVIVE_1.md` end-to-end before any code. It is the RECUT v2.2 — the H1 + RECUT NOTE explain why v1's "dead watchdog" premise was wrong (codex disproved it with Render logs; the watchdog executes fine, the listener drops its row).

Brief cleared codex pre-review twice: FAIL-LIGHT #1444 (correctly disproved v1) → recut → PASS-WITH-NITS #1452 on v2.1. All 3 nits folded into v2.2 (`3c0e849`): (1) `from config.settings import config`, (2) direct fallback uses `config.direct_dsn_params` (non-pooled Neon endpoint), (3) +2 named test cases. No further pre-write review required.

**Scope:**
- **Fix 1 (root cause):** `triggers/embedded_scheduler.py` `_job_listener` — replace the single 100ms retry with bounded pooled backoff (100/200/400ms), then a DEDICATED short-lived `psycopg2.connect(connect_timeout=5, **config.direct_dsn_params)` fallback for the `scheduler_executions` INSERT (close in `finally`). `_record_listener_drop` only if pooled AND direct both fail.
- **Fix 2 (secondary):** `memory/store_back.py` maxconn 5→8 ONLY if you confirm the Neon connection ceiling (else leave 5, note in ship report) + `SET LOCAL statement_timeout='20s'` in the watchdog cursor block (`triggers/scheduler_liveness_sentinel.py`).
- **Optional (low priority):** non-fatal startup self-presence log after `_register_jobs(_scheduler)` (pre-`start()`), NO raise. Skip if it bloats the diff.
- DROPPED: max_instances=2 (codex Finding 2 dup-alert race). Do NOT touch any `add_job(...)`.

**Tests:** extend `tests/test_job_listener_harden.py` with (a) pooled-fail + direct-success → row inserted, drop-count unchanged; (b) pooled-fail + direct-fail → `_record_listener_drop` increments, no raise. Existing #274 listener tests + #273 liveness suite (42) must stay green on a literal `pytest` run.

**ACs:** AC1 (scheduler_job_liveness row with fired_at after deploy lands within ~25min — proves fallback works under real pressure), AC2 (no NEW false STALE alerts for live jobs), AC3 (literal pytest tail, new cases PASS). NO pass-by-inspection.

**Reply target:** lead. Ship report to `briefs/_reports/B1_SCHEDULER_LIVENESS_REVIVE_1_<YYYYMMDD>.md` + bus-post to `lead` topic `ship/scheduler-liveness-revive-1`. Tag `/security-review` per Tier-A ship contract (DB write path). Gate chain after ship: G1 AH1 fold + G2 /security-review + G3 deputy (will focus on fallback-conn lifecycle).
