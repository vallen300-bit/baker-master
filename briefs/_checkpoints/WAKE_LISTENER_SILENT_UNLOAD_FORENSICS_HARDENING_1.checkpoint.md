---
brief_id: WAKE_LISTENER_SILENT_UNLOAD_FORENSICS_HARDENING_1
attempt: 1
repo: brisen-lab (code) — branch b1/wake-listener-hardening @63bd8248
dispatched_by: lead (bus #12695, P1)
report_topic: gates/wake-listener-hardening-1
status: MERGED — brisen-lab PR #154 @42fde1b5 (codex PASS-WITH-NOTE #12805, Director GO, lead #12833). Host deployed + AC1/AC2 live PASS. B1 lane closed EXCEPT: AC4 24h soak verdict OWED tomorrow (2026-07-19) → post to gates/wake-listener-hardening-1. Then stand down to composer/origin-tag arc coordination with b2 (lead #12833).
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

## Next concrete step (B1, tomorrow 2026-07-19)
Post AC4 24h soak verdict to gates/wake-listener-hardening-1: grep `~/.brisen-lab/wake-listener.stdout.log`
for unexplained gaps since merge (~2026-07-18 14:3x). Any gap must correlate to a logged
`received SIGTERM` line (forensic handler) or a watchdog RESTORE in `wake-listener-watchdog.log`.
Zero unexplained gaps = PASS. Then stand down to composer/origin-tag arc coordination with b2.

## Queued follow-ups (lead #12833, none blocking)
1. Codex note: persistent restore-failure re-flags every 300s — no cross-run dedupe/backoff
   in `wake_listener_watchdog.sh bus_flag`. Add a cooldown/state file if lead dispatches it.
2. Dedicated `wake-watchdog` bus sender slug (currently posts as daemon/unattributed).
3. Fleet lesson "agents must not bare-bootout shared fleet agents" — LEAD writes this one.

## Host state left healthy
listener running (new code, SIGTERM handler); watchdog loaded, StartInterval 300s intact.
3 AC test flags landed on lead fleet/wake-listener-outage (msg 12791 + 14:27:36 + 14:28:26) —
AC artifacts, not real outages (noted to lead in #12798).
