# ARM_ALARM_SLEEP_GAP_SUPPRESS_1

**Lane:** deputy-codex — BUILDER (you build and ship; you do NOT review or gate. Codex seat gates.)
**Task class:** local-daemon reliability fix (production-adjacent: alarm path emails the Director).
**Dispatcher:** lead. Report back to lead on the bus.

## Context

`arm_alarm_check.sh` (launchd `com.baker.arm-alarm`, 3-min cadence) watches
marker files under `~/.brisen-lab/arm-alarm/markers/` and FIREs RED
email+notification to the Director when a source goes stale. The `arm-cadence`
poller writes snapshots ~every 30 min — but only while the Mac is awake.

**Context Contract (endpoints/surfaces this brief binds):**
- `scripts/arm_alarm_check.sh` — canonical source, baker-master. Verified present.
- `~/Library/Application Support/baker/arm_alarm_check.sh` — deployed copy launchd actually runs (verified via PlistBuddy on `com.baker.arm-alarm.plist`).
- `~/.brisen-lab/arm-alarm.log` — evidence log; `~/.brisen-lab/arm-alarm/state.json` — incident state.
- `pmset -g log` / `sysctl kern.sleeptime kern.waketime` — sleep/wake evidence surfaces (local, no auth).
- No repo web endpoints touched; no auth-class changes.

## Problem (evidence-backed, 2026-07-23)

1. **Sleep-gap false REDs email the Director.** Lid closed overnight
   (Director-confirmed 07-23 morning). Snapshots pause during sleep; the alarm
   reads age > max_age as `cadence:stale` and FIREs. Three false RED→RECOVER
   pairs in 24h: 18:35Z→18:40Z, 21:25Z→01:06Z, 02:08Z→05:38Z (recovered on
   first check after the 05:35:38Z post-wake snapshot). All self-resolved;
   every one emailed the Director.
2. **AMBER absent-marker log pollution.** `report.json` + `canary.json`
   sources log "AMBER … marker absent" on EVERY 3-min check since install
   2026-07-13 (4,070+ lines). The script header itself says those writer
   pipelines "are separate briefs that may not be live" — never built.
   Designed-degraded, not a regression; the spam buries real lines.

## Files Modified

- `scripts/arm_alarm_check.sh` (baker-master — canonical)
- `~/Library/Application Support/baker/arm_alarm_check.sh` (deployed copy — resync, out-of-repo)
- No other files. State-file schema additions allowed only for suppression bookkeeping keys.

## Acceptance criteria

1. **Sleep-aware staleness:** before FIREing an age-based staleness incident,
   compute sleep overlap for the staleness window (`pmset -g log` sleep/wake
   entries or `kern.sleeptime`/`kern.waketime`). Sleep covering the majority
   of the gap ⇒ no FIRE; one `SUPPRESSED sleep-gap` log line.
2. **Post-wake grace:** no staleness FIRE within one cadence poll interval +
   margin (default ~35 min, env-tunable `ARM_ALARM_WAKE_GRACE_S`) after wake.
3. **Real failures still fire:** marker stale while machine awake all window ⇒
   FIRE exactly as today.
4. **Absent-marker de-spam:** a marker that has NEVER existed logs AMBER at
   most once per 24h (or env-gated off until writer briefs ship). A marker
   that existed then disappeared still logs every check (regression signal).
5. **No delivery-path changes:** recipient resolution, email/notify mechanics
   untouched.

## Verification

- Simulated runs (fake marker ages + stubbed sleep records):
  (a) old marker + no sleep ⇒ FIRE; (b) old marker + covering sleep window ⇒
  SUPPRESSED; (c) fresh-wake within grace ⇒ no FIRE; (d) never-existed marker ⇒
  ≤1 AMBER line/24h. Paste the four proof lines in the ship receipt.
- Both copies in sync: `shasum` of canonical vs deployed in receipt.
- `git ls-remote` line per Lesson #131 receipts rule.

## Done rubric / gate plan

- **Done-state class:** merged + deployed-local + simulated-proof (no Render deploy involved).
- **Gate plan:** codex seat gates the diff BEFORE merge (serial seat — nudge lead after ~30 min silence). Lead merges on PASS, then verifies deployed-copy resync hash. Builder self-verify is NOT a gate (Lesson #131).
