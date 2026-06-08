---
status: PENDING
brief_id: SCHEDULER_STALL_DIAGNOSE_1
dispatch: SCHEDULER_STALL_DIAGNOSE_1
to: b2
from: lead
dispatched_by: lead
dispatched_at: 2026-06-08
task_class: diagnosis (read-only first; fix only after root-cause confirmed + lead GO)
gate_plan: DIAGNOSE -> report to lead -> (if fix) G0 codex -> G1 -> G2 if backend -> G3 codex -> merge
---

# B2 dispatch — SCHEDULER_STALL_DIAGNOSE_1 (read-only diagnosis FIRST)

**Live symptom (prod baker-master, 2026-06-08 ~12:00Z):** `GET /api/health/scheduler`
returns `{"alive":false,"scheduler_running":false,"job_count":0,"heartbeat_age_seconds":~2100 and AGING}`.
Heartbeat watermark is frozen ~35 min and the SCHEDULER-WATCHDOG-1 auto-restart (fires at
>720s×2 = 24 min) has NOT recovered it. Cortex auto-cycles + pollers are not firing.

This is your lane — you shipped SCHEDULER_NEON_IDLE_HARDEN_1 (PR #296). NOT a dashboard-wave
regression (waves were frontend-only); surfaced BY the new Fix-4 liveness pill.

**Scope:** DIAGNOSE root cause READ-ONLY first. Likely suspects to check:
- Is this multi-instance deploy overlap (an instance answering with a stale watermark) vs a
  genuine dead loop? Distinguish by checking whether the heartbeat watermark in PG is actually
  advancing (query `trigger_state` scheduler_heartbeat) vs frozen.
- Did the singleton lease (`scheduler_lease.py`, advisory lock key 8800100) get held by a dead
  conn so no instance re-acquires? (the exact failure class #296 hardened — verify the fix is live).
- Is the watchdog (dashboard.py ~188 restart-on-stale) actually running / why didn't it fire?
- embedded_scheduler heartbeat job blocked on a dead Neon conn (the probe-blocks-heartbeat
  class from #296 G0 fold)?

**Report to lead:** root cause + evidence (PG queries, log lines, /health probes) + a proposed
fix (or "restart clears it, here's why it stalled"). Do NOT push a fix or restart without lead GO.
Report = literal query/probe output, not "by inspection".
