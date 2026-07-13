# B4 Ship Report — ARM_CADENCE_LAUNCHD_JOB_1

- **Brief:** ARM_CADENCE_LAUNCHD_JOB_1 (bus dispatch #10331, from lead)
- **Charter:** DRAFT_SPEC_ARM_BUS_CUSTODIAN_AMENDMENT_V1 (RATIFIED v1.1 @c435b18) — D2 + §4
- **PR:** #553 → main
- **Branch:** b4/arm-cadence-launchd-job-1 @a25e5d51
- **Date:** 2026-07-13
- **Gate:** codex review, then lead merge (per dispatch)

## What shipped
ARM's machine-cadence watchdog — a KeepAlive-hardened launchd job that captures a
bus-health telemetry snapshot every 30 min with **zero LLM per poll**, so ARM only
spends tokens on report synthesis + alarm wording (charter D2/§5).

| File | Role |
|---|---|
| `scripts/arm_cadence_poll.sh` | Poller. `GET /api/bus_health` → atomic snapshot `~/.brisen-lab/arm-cadence/latest.json` + timestamped history. Always exit 0; single-instance mutex; prune. |
| `scripts/install_arm_cadence_job.sh` | Idempotent single-job install (TCC-safe, no secret) + `--check` drift mode. |
| `scripts/arm_cadence_drift_check.sh` | Fail-open sentinel; logs + bus-posts lead on drift. |
| `scripts/launchd/com.baker.arm-cadence.plist` | Crash-only KeepAlive, StartInterval=1800, RunAtLoad. |
| `scripts/tests/test_arm_cadence.sh` | 20 hermetic checks. |

## Done rubric
- **Structural, not prompt-driven** ✅ — launchd-run, KeepAlive crash-only; the watchdog is itself watched (§3). Verified: plist `KeepAlive.SuccessfulExit=false`, `StartInterval=1800` (plutil-lint OK).
- **Zero LLM per poll** ✅ — curl-only; snapshot is pure JSON, no model call in the poll path.
- **TCC-safe** ✅ — deploys to `~/Library/Application Support/baker`, never `~/Desktop` (test asserts no `Desktop` ref).
- **Snapshot ARM reads at wake** ✅ — `latest.json` atomic write (temp+mv); live poll captured 10 seats + latency + delivery.
- **Install script + drift check** ✅ — both present; `--check` covers exec-bit + syntax + freshness (E23 blocker-2 existence≠healthy lesson).
- **Tolerant / fail-loud-where-it-matters** ✅ — poll always exit 0 (freshness is the signal); drift surfaces via log line + bus alarm to lead.

## Test evidence
```
arm_cadence tests: 20 passed, 0 failed
```
Live poll vs brisen-lab: `OK snapshot …Z.json (sources=1)`, http=200, ok=true, exit 0, 10 seats.

## Design decisions (in-role, reversible — decided + documented, not escalated)
1. **v0 machine surface = `/api/bus_health` only.** Already aggregates seats/latency/integrity/delivery. `arm_sql` lease/wake/envelope tables added via the frozen `SOURCES[]` extension point as P1–P4 land — not guessed against unshipped schema.
2. **Snapshot at `~/.brisen-lab/arm-cadence/latest.json`** (ARM filesystem-readable). ARM synthesis is not yet wired; this is the read contract for it.
3. **No embedded key** — `/api/bus_health` is public (http=200 unauth); nothing for codex G3 to find leaking.

## For lead
- **Deploy = host-side install post-merge; you pick the host** (always-on box, not an ephemeral b4 clone): `bash scripts/install_arm_cadence_job.sh`. POST_DEPLOY_AC = `launchctl list | grep com.baker.arm-cadence` + `install_arm_cadence_job.sh --check` → CLEAN.
- **Separate small brief needed:** the daily drift-check launchd install (mirrors the forge-drift-cron split). Flagged, not built here.
- **Reconciled stale seat state:** mailbox now points at this brief; BUS_CONSOLE autostub checkpoint deleted (BUS_CONSOLE closed PR #525, E23 closed PR #551).
