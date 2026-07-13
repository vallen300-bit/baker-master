# B4 Ship Report — ARM_OUT_OF_BAND_ALARM_1

- **Brief:** ARM_OUT_OF_BAND_ALARM_1 (Plan v3 micro-brief, bus dispatch #10404 from deputy-codex; endorsed as b4's new lane by lead #10416)
- **Charter:** DRAFT_SPEC_ARM_BUS_CUSTODIAN_AMENDMENT_V1 (RATIFIED v1.1 @c435b18) — D3 canary + §3 "report missed by 07:00 UTC = RED (the watchdog must be watched)"
- **PR:** (opened this run) → main
- **Branch:** b4/arm-out-of-band-alarm-1
- **Date:** 2026-07-13
- **Gate:** codex review, then lead merge (mirrors the arm-cadence gate)

## What shipped
The **out-of-band** half of ARM's alarm coverage. ARM's normal alarms fire *through
the bus* (`arm_flag_lead`). Two failure modes cannot be delivered that way:
- **Canary failure** — the post→wake→ack loop is broken, so a bus alarm never lands.
- **Report-miss** — ARM never woke to synthesise its daily report, so it cannot post
  its own "I'm dead" alarm.

This is a KeepAlive-hardened launchd job (`com.baker.arm-alarm`) that polls **local
freshness markers only** every ≤5 min and, on failure, alarms **off the bus** (Outlook.app
email + a macOS notification), deduped per incident key. It never touches the bus.

| File | Role |
|---|---|
| `scripts/arm_alarm_check.sh` | Watchdog. Reads `markers/report.json` + `markers/canary.json` (SOURCES[] extension point), dedupes via `state.json` (cooldown + recovery re-arm), sends email (Outlook Pattern A) + macOS notification. Zero LLM, **zero bus**, always exit 0; single-instance mutex. |
| `scripts/install_arm_alarm_job.sh` | Idempotent single-job install (TCC-safe, no secret) + `--check` drift mode. Interval clamped **≤300s** so the SLO cannot be misconfigured away. |
| `scripts/arm_alarm_drift_check.sh` | Fail-open sentinel; logs + bus-posts lead if the alarm JOB is not installed/healthy (install-health meta-check — allowed on the bus; distinct from the alarm's own out-of-band send). |
| `scripts/launchd/com.baker.arm-alarm.plist` | Crash-only KeepAlive, StartInterval=180, RunAtLoad. |
| `scripts/tests/test_arm_alarm.sh` | 52 hermetic checks (senders injected as recorders — no real email/launchctl/bus), incl. delivery-truth + bounded-backoff. |

## Done rubric (the micro-brief's 5 asks)
- **Owner** ✅ — ARM custodian; operationally the host-side launchd job `com.baker.arm-alarm` on the always-on ARM host. Drift-post accountable = `lead`.
- **Trigger** ✅ — canary marker stale/`ok:false`, or report marker stale (missed daily). SOURCES[] adds more out-of-band signals with no code change.
- **≤5 min alarm SLO** ✅ — structurally guaranteed: StartInterval=180s (clamped ≤300s), detection ≤ one poll, send sub-second → worst-case ~180s + send ≪ 300s. `--check` FAILs if the installed interval ever exceeds 300s.
- **Dedupe** ✅ — one alarm per incident key (source+type, mirrors charter F4); recovery emitted + key re-armed; 6h cooldown backstop for a still-active incident. Tests 3–6 prove fire-once / suppress-within-cooldown / re-alarm-past-cooldown / recover.
- **Test evidence** ✅ — see below.
- **Separate from bus reliability controls** ✅ — worker makes no bus call (test 1 asserts no `X-Terminal-Key`/`LAB_URL`/`curl …/msg`); it is a distinct launchd job, not an edit to the arm-cadence poller.

## Codex G2 fix (#10455 → re-route to codex)
First cut had a **delivery-truth** bug codex caught: the worker marked an incident
"alarmed" and suppressed re-alarms in a shell loop that ran *after* state was
committed, and `subprocess.run(check=False)` treated an Outlook failure as success —
so a failed out-of-band send (Outlook/M365 down, the exact scenario this exists for)
was silently lost. **Fixed:** delivery now lives *inside* the reconcile program; an
incident is marked alarmed / cooldown-suppressed **only after ≥1 channel returns a
real success** (osascript returncode checked). If both channels fail: log `SEND-FAIL`,
set `delivery_pending`, and **retry each poll with bounded exponential backoff**
(`ARM_ALARM_BACKOFF_BASE_S`..`_CAP_S`) — never suppressed. A recovery for an alarm
that was never delivered clears silently (`CLEAR-UNDELIVERED`). Transport sits behind
the `ARM_ALARM_SEND_CMD`/`_NOTIFY_CMD` adapter seam (#10425) so push can be added later
without touching trigger/dedupe. New regression tests 13–16 cover both-fail, partial
(1-of-2), retry-then-succeed, undelivered-recovery, and backoff growth.

## Test evidence
```
arm_alarm tests: 52 passed, 0 failed
arm_cadence tests: 20 passed, 0 failed   # sibling, no regression
```
Coverage: fresh=no-alarm, stale-report=1-alarm, dedupe-within-cooldown, cooldown-backstop
re-alarm, recovery-notice + incident-cleared + re-arm, canary `ok:false`, missing-marker
AMBER default, `MISSING_IS_RED=1` flip, installer dry-run, interval clamp→300, `--check`
DRIFT, drift sentinel fail-open, + structural invariants (crash-only KeepAlive, TCC-safe
dir, no secret in plist, non-bus, tolerant exit 0).

## Design decisions (in-role, reversible — decided + documented)
1. **Local freshness markers, not a bus read.** To stay genuinely out-of-band the watchdog
   reads only local marker files the producers write (`report.json` {delivered_at},
   `canary.json` {ok, checked_at}). Reading the bus to learn "is the canary ok" would
   defeat the purpose when the bus is the thing that is down.
2. **Missing-marker = AMBER by default (`MISSING_IS_RED=0`).** The canary cron + report
   pipeline are separate briefs that may not be live on install day; a never-seen marker
   logs AMBER instead of false-paging. Flip to RED once every producer is guaranteed live.
3. **Email = Outlook.app Pattern A (autonomous send) + a macOS notification as a
   zero-dependency second channel** (fires even if Outlook/M365 auth is broken).
4. **No register entry.** Like arm-cadence, this periodic launchd watchdog has no
   cursor/progress table, so it is out of `config/long_running_jobs.yml` scope by design.

## For lead — decisions flagged for review (not blockers)
- **Email recipient default = `dvallen@brisengroup.com`** (env `ARM_ALARM_EMAIL_TO`, per-host
  overridable). Rationale: the whole point is to reach a human when the bus (lead's normal
  channel) is down, so it targets the Director's ops address. If you want it pointed at a
  dedicated ops inbox or cc'd, it is one env change — flag it. (Director relayed the
  transport choice "email via Outlook.app" this session; recipient default is mine to review.)
- **Deploy = host-side install post-merge; you pick the host** (same always-on box as
  arm-cadence): `bash scripts/install_arm_alarm_job.sh`. POST_DEPLOY_AC =
  `launchctl list | grep com.baker.arm-alarm` + `install_arm_alarm_job.sh --check` → CLEAN.
- **Producers not built here (scope):** the ARM report-synthesis marker write + the canary
  verifier marker write are the alarm's inputs. Until they exist, markers are absent →
  AMBER (no false page). Wiring them = their own briefs.
- **Optional follow-up:** a daily `arm_alarm_drift_check.sh` launchd install (mirrors the
  forge/arm-cadence drift-cron split). Flagged, not built here.
