# WAKE_LISTENER_SILENT_UNLOAD_FORENSICS_HARDENING_1

**Dispatcher:** lead · **Date:** 2026-07-18 · **Priority:** P1 (fleet-wide silent outage, 2x in 12h)
**Type:** Diagnose-first (root cause BEFORE any fix commit), then harden.

## Context

Post-cutover fleet (28 tmux seats) receives bus wakes via: Lab SSE →
`~/.brisen-lab/wake-listener.py` (launchd `com.baker.wake-listener`) → `open
brisen-lab://wake/<alias>` → Wake.app → seat nudge/spawn. Overnight incident bus
#12631: listener dead ~00:29–08:34, fleet idled. Second death 08:39–09:56 found by
lead. ARM out-of-band alarm (email) fired both times — it is the only net that held.

**Context Contract:** worker needs: this brief; `~/.brisen-lab/wake-listener.py`
(266 lines); `~/.brisen-lab/wake-listener.stdout.log`; the Wake.app main.scpt
(decompile cmd below); `~/Library/LaunchAgents/com.baker.wake-listener.plist`.
No baker-master code context needed beyond `scripts/` install conventions.
**Task class:** infra-diagnose + local-daemon hardening (laptop launchd; no Render
deploy, no dashboard.py).
**Done rubric / done-state class:** evidence-gated (AC1-AC4 below) + codex gate;
done-state = report in `briefs/_reports/` + merged hardening PR + bus verdict.
**Gate plan:** codex gate on exact tips (report topic
`gates/wake-listener-hardening-1`) before lead merge; AC4 soak verdict posts
post-merge per post-deploy-ac-bus-gate.

## Problem

`com.baker.wake-listener` (launchd, `~/.brisen-lab/wake-listener.py`) died silently
twice in 12 hours. Each death = every bus wake undelivered; the fleet idles until a
human notices (overnight incident bus #12631 — desks idle ~8h).

## Evidence (verified by lead, 2026-07-18)

1. Death signature identical both times — log ends mid-flight, no exception, no
   shutdown line, immediately after a dispatch:
   - Death 1: `00:29:26 dispatched alias=cowork-ah1` → silence until manual restore 08:34.
   - Death 2: `08:39:17 dispatched alias=lead` → silence until lead re-bootstrap 09:56.
   - Log: `~/.brisen-lab/wake-listener.stdout.log` (append-only; gaps listed above).
2. Both fatal dispatches targeted App-resident/lead-family aliases (cowork-ah1, lead).
   Dispatches to tmux seats (b1, codex, desks) never precede a death.
3. `launchctl print gui/501/com.baker.wake-listener` after death 2: **service not
   found** — fully unloaded, NOT crashed-and-held. Plist intact (mtime Jul 8).
   KeepAlive = {SuccessfulExit:false, Crashed:true} → a crash would restart; only
   an explicit `bootout`/`launchctl remove` (or a clean self-exit + successful-exit
   suppression... but exit would log) explains "service gone".
4. Listener code has NO self-kill path (read by lead: dispatch_wake → classify →
   return; _self_heal only lsregisters Wake.app).
5. Unified log (`log show`, 4h window) returned nothing for the unload — check
   longer windows / `launchd` subsystem with the death timestamps above.

## Working hypothesis (verify, do not assume)

Something in the **Wake.app spawn/nudge branch for App-resident aliases** (or a
process it launches — Cowork App login items, `register-url-handler.sh`, a fleet
script in the spawned shell profile) boots the wake-listener service out.
Known adjacent hazard: Cowork App wipes `~/Library` state (forge how-to warning).
Decompile: `osadecompile "/Users/dimitry/Applications/Brisen Lab Wake.app/Contents/Resources/Scripts/main.scpt"`.

## Deliverables

1. **Root cause** with a reproduction or a log-anchored causal chain (not a guess).
2. **Fix at the source** (whatever performs the bootout stops doing it, or the
   listener becomes immune).
3. **Watchdog hardening regardless of root cause:** a `launchd` `StartInterval`
   (300s) health-check job that re-bootstraps the listener when the service is
   absent AND posts a bus flag to `lead` topic `fleet/wake-listener-outage` when it
   had to (fail-loud — silent self-heal hides the pattern). ARM out-of-band alarm
   stays as the independent second net; do not touch it.
4. **Forensic logging:** listener logs SIGTERM via signal handler (one line) so a
   future kill is attributable; launchd-side `ExitTimeOut` review.

## Constraints

- Do NOT modify ARM alarm lanes. Do NOT touch `tasks/lessons.md` existing entries.
- Watchdog plist name: `com.baker.wake-listener-watchdog.plist`; install script
  extends `~/.brisen-lab/` convention; idempotent re-install.
- All subprocess/launchctl calls wrapped try/except; fail-loud on stderr + bus.

## Files Modified (expected)

- `~/.brisen-lab/wake-listener.py` — SIGTERM handler line (forensic logging).
- NEW `scripts/launchd/com.baker.wake-listener-watchdog.plist` + install script
  under `scripts/` (repo) staged to `~/.brisen-lab/` (host).
- NEW `briefs/_reports/WAKE_LISTENER_UNLOAD_ROOT_CAUSE_<date>.md`.
- Possibly Wake.app `main.scpt` IF root cause lands there (separate commit, flag to lead first).

## Verification

Run AC1-AC2 kill tests live and paste timestamps + log lines into the report.
AC3 causal chain must cite log/timestamp evidence, not inference alone.

## Acceptance criteria

1. AC1: kill test — `launchctl bootout` the listener manually; watchdog restores it
   within 6 min AND a bus flag lands at lead. Show both timestamps.
2. AC2: SIGTERM test — `kill -TERM <pid>`; the death is attributable in the log
   (signal line present), KeepAlive restarts it (Crashed path) or watchdog does.
3. AC3: root-cause writeup in `briefs/_reports/` with the causal chain + fix diff,
   or an explicit falsification of the App-resident-alias hypothesis with evidence.
4. AC4: 24h soak — zero unexplained gaps in `wake-listener.stdout.log` (checked at
   next lead session).
5. Codex gate on exact tips before merge (report topic `gates/wake-listener-hardening-1`).
