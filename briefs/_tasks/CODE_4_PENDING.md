---
status: PENDING
brief_phase_a: briefs/BRIEF_SCHEDULER_WATCHDOG_WA_KILL_1.md
brief_phase_b: briefs/BRIEF_SCHEDULER_CRASHLOOP_RCA_2.md
trigger_class: PHASE_A=LOW (single-file kill) ; PHASE_B=LOW (RCA, no code)
dispatched_at: 2026-05-15T15:25:00Z
dispatched_by: ai-head-2 (AH2)
target: b4
prior_brief_complete: |
  HARD_DEADLINE_AUDIT_V1 (PR #198, commit 31158996, 2026-05-12). Closed.
  This dispatch supersedes the prior CODE_4_PENDING.md content.
director_ratification: |
  Director 2026-05-15 ~15:10Z (in-chat to AH2): "ah1 is busy, can you
  kill the whatsapp alert and prepare the brief to b4 to fix?"
  AH2 dispatching as deputy per orientation §recurring-workflow #1.
  AH1 (lead orchestrator) not on this dispatch — Director authorized AH2
  redirect explicitly.
priority: P0 (Phase A — user-visible noise; production-spam)
            P1 (Phase B — RCA, scope-bounded)
phase: 1 of 2 (Phase A first, then Phase B)
expected_pr_count: 1 (Phase A) + 0 (Phase B — RCA-only, ship report commit)
expected_complexity: |
  Phase A: ~10 min — single-file edit at outputs/dashboard.py:200-207
  Phase B: 1-2h — diagnostic SQL + Render log inspection + ship report
mandatory_2nd_pass: FALSE (both phases LOW trigger class)
hard_ship_gate: |
  PHASE A:
    1. `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"` clean.
    2. `pytest tests/test_watchdog_cooldown.py -v` literal green pasted in ship report.
    3. PR opened, /security-review skill clean (single-file, no auth/DB/external surface).
    4. After merge + 30 min: `SELECT COUNT(*) FROM baker_actions WHERE action_type='whatsapp_send'
       AND payload->>'text_preview' LIKE 'Baker scheduler was dead%' AND created_at > NOW() - INTERVAL '30 minutes'`
       returns 0 (literal SELECT output in ship report).

  PHASE B (after Phase A merged):
    1. Ship report committed to briefs/_reports/B4_scheduler_crashloop_rca2_<date>.md.
    2. Root cause statement single sentence + cited evidence.
    3. Evidence table for all 5 hypotheses (VERIFIED/FALSIFIED/INCONCLUSIVE).
    4. Proposed fix + risk + verification plan.
    5. Follow-up brief skeleton inline if proposed fix needs code (most likely yes).
    6. AH2 reviews ship report; surfaces proposed fix to Director for ratification before any patch.
ship_report_to: |
  Bus-post to `deputy` on each Phase A PR open + ship.
  Bus-post to `deputy` on Phase B ship-report commit.
---

# CODE_4_PENDING — Scheduler watchdog WA kill + crash-loop RCA — 2026-05-15

**Dispatched by:** AH2 (deputy) under Director directive 2026-05-15 ~15:10Z
**Working dir:** `~/bm-b4`
**Branch strategy:**
- Phase A → new branch off `main`, e.g. `b4/scheduler-watchdog-wa-kill-1`
- Phase B → no branch (ship report committed to `main` directly under `briefs/_reports/`)

Pre-flight:
1. `git pull --ff-only origin main` in `~/bm-b4`.

---

## Phase A — URGENT (ship within hours)

Read `briefs/BRIEF_SCHEDULER_WATCHDOG_WA_KILL_1.md` end-to-end.

Scope: single edit at `outputs/dashboard.py:185-209`. Replace the `send_whatsapp(...)` block with a throttled `logger.warning(...)`. Keep `restart_scheduler()` intact. Keep the 720s threshold. Keep the cooldown variable + semantics — it now throttles the WARN log instead.

Open PR titled: `fix(scheduler): disable watchdog WA alert (CRASHLOOP_RCA_2 in flight)`.

Ship gate per the brief. PR + literal pytest output. AH2 reviews + merges (Tier A — single-file behaviour-narrow, no auth/DB).

After merge: paste the post-merge `SELECT COUNT(*)` verification (30 min wait) in the ship report.

## Phase B — RCA after Phase A merges

Read `briefs/BRIEF_SCHEDULER_CRASHLOOP_RCA_2.md` end-to-end.

Scope: 6 investigation steps (env var check, Render logs, pg_locks query, heartbeat-gap distribution, WA-send correlation, root-cause statement). Deliverable = ship report at `briefs/_reports/B4_scheduler_crashloop_rca2_<date>.md`.

**No production code change in Phase B.** Proposed fix lands as a follow-up brief after Director ratifies the scope based on your RCA.

---

## Background context (read before starting)

- `BRIEF_SCHEDULER_SINGLETON_HARDEN_1.md` already shipped — `triggers/scheduler_lease.py` exists, `tests/test_scheduler_singleton.py` exists, `config/settings.py:147` has `host_direct`. Yet scheduler still crash-loops. Your RCA tells us why.
- 426 whatsapp_sends in 3 days, all the same watchdog alert text. Real alerts (Steininger / ORF, 2026-05-15 13:50Z) buried in the noise.
- Current health: `Scheduler: stopped, jobs: 0` at 15:09Z — but `scheduler_executions` table shows jobs ARE firing periodically. Scheduler dies + restarts on a ~12-min cycle.
- Hypotheses pre-listed in the RCA brief: (1) `POSTGRES_HOST_DIRECT` unset on Render, (2) held connection dies (Neon auto-suspend), (3) SIGTERM orphan lock, (4) APScheduler thread death from unhandled job exception, (5) container OOM.

## Reporting

- Bus-post to `deputy` on each PR open + ship (Phase A) and on RCA ship-report commit (Phase B), per `_ops/processes/agent-bus-posting-contract.md`.

## Co-Authored-By

```
Co-authored-by: Code Brisen #4 <b4@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
