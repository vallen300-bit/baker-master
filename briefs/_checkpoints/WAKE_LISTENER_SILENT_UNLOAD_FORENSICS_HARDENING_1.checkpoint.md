---
brief_id: WAKE_LISTENER_SILENT_UNLOAD_FORENSICS_HARDENING_1
attempt: 1
repo: brisen-lab (code) — branch b1/wake-listener-hardening @63bd8248
dispatched_by: lead (bus #12695, P1)
report_topic: gates/wake-listener-hardening-1
status: BUILD COMPLETE + deployed to host + AC1/AC2 live PASS. Pushed brisen-lab @63bd8248. Codex-gate report posted to lead (#12798). Awaiting lead codex gate + merge. AC4 24h soak posts post-merge.
gate: codex gate on exact tips (topic gates/wake-listener-hardening-1) before lead merge
---

# WAKE_LISTENER_SILENT_UNLOAD_FORENSICS_HARDENING_1 — checkpoint

Brief: `briefs/_tasks/WAKE_LISTENER_SILENT_UNLOAD_FORENSICS_HARDENING_1.md` @9aba2c57.

## Root cause (log-anchored, hypothesis falsified)
Both 2026-07-18 silent deaths = a Claude agent session ran bare `launchctl bootout
gui/501/com.baker.wake-listener` (Death 1 00:29:45 Terminal claude, also booted
arm-cadence; Death 2 09:21:47 Cowork App claude, 42 min after any wake). bootout
REMOVES the job → KeepAlive can't revive → stayed dead. NOT the wake path.

## Done (shipped, pushed @63bd8248, deployed to host)
- NEW `tools/wake-listener/wake_listener_watchdog.sh` + `com.baker.wake-listener-watchdog.plist`
  (StartInterval 300) — re-bootstraps listener when absent/not-running; fail-loud bus
  flag to lead topic `fleet/wake-listener-outage` (sender daemon, idempotency_key, 3x retry)
  + local log; quiet when healthy. ARM alarm untouched.
- `wake-listener.py` SIGTERM/SIGINT forensic handler (log attributable line + re-raise SIG_DFL).
- `install.sh` co-installs watchdog idempotently. 2 unit tests in `tests/test_wake_listener_health.py`.
- Live AC1 (bootout→restore+flag HTTP200, manual + launchd kickstart) + AC2 (kill -TERM→
  attributable line + KeepAlive restart) PASS. Report: `briefs/_reports/WAKE_LISTENER_UNLOAD_ROOT_CAUSE_20260718.md`.

## Next concrete step (owner = lead, not B1)
Lead runs codex gate on @63bd8248 (topic gates/wake-listener-hardening-1) → merge. Then AC4
24h soak verdict (zero unexplained gaps in wake-listener.stdout.log) posts post-merge per
post-deploy-ac-bus-gate. Follow-ups flagged not done: dedicated `wake-watchdog` bus sender slug;
fleet lesson "agents must not bare-bootout shared fleet agents".

## Host state left healthy
listener running (new code, SIGTERM handler); watchdog loaded, StartInterval 300s intact.
3 AC test flags landed on lead fleet/wake-listener-outage (msg 12791 + 14:27:36 + 14:28:26) —
AC artifacts, not real outages (noted to lead in #12798).
