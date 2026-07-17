---
name: cockpit-phase2-cutover
description: Quiet-window runbook for the ONE coordinated global Terminal→tmux+ttyd cutover (FLEET_TMUX_LAUNCH_1 §6a Phase-2). lead-run, GO-gated, single Cmd+Q.
when_to_use: When lead schedules and executes the Phase-2 fleet cutover after both Phase-1 pilots (b3, brisen-desk) are green. Not for per-seat sandbox migration.
---

# Cockpit Phase-2 cutover — quiet-window runbook

> **Who runs this:** lead, in-session, in a scheduled quiet window. The Director
> owns the timing (fleet-visible outage). B-codes build the tooling; they do NOT
> execute this. Ratified: lead #12330 (Option A) off Director GO 2026-07-17.
>
> **What it does:** rewrites EVERY eligible seat's Terminal-profile `CommandString`
> to the tmux wrapper `tmux new-session -A -s <slug> "/bin/zsh -lic '<alias>'"`
> (scope §6.1) in one pass, does the single Terminal.app quit (the ONLY Cmd+Q —
> Lesson 76: profile changes are app-wide), brings every session back under tmux
> via `fleet_terminals.sh up`, and smoke-tests each seat with per-seat rollback.

## Why it is one global quit, not per-seat

A running agent CANNOT be adopted by tmux, and a Terminal profile edit only takes
effect after Terminal.app is quit — and quit is app-wide (Lesson 76). Per-seat
profile cutover is therefore impossible. Phase-1 validated the substrate on two
idle pilots (b3, brisen-desk) without editing any profile; Phase-2 is the single
coordinated switch for the whole fleet.

## Preconditions (the script hard-gates the ones marked ✔; you own the rest)

1. ✔ Both pilots green: `b3` and `brisen-desk` = `migrated` in the ledger.
2. ✔ Manifest strict-clean: `python3 scripts/generate_cockpit_manifest.py --write --strict` exits 0 (every eligible seat resolved; 0 unresolved).
3. ✔ Controller live on :7800 (Basic-auth) and credential file present.
4. Every ACTIVE seat has checkpointed its own context (context-band rollover discipline). The script cannot do this for other agents — it only reminds.
5. Daemon refresh cadence PAUSED for the window (otherwise it re-seats agents mid-cutover via their old profiles).
6. The cutover is launched DETACHED — never from a live Terminal seat, because the single Cmd+Q would kill the running process. The script refuses if `TERM_SESSION_ID` is set (run under `nohup`/`caffeinate`, or from the controller context).

## Dry-run first (safe, writes nothing)

```bash
cd ~/bm-b2/scripts        # or the deploy dir
./cockpit_migrate.sh cutover --dry-run
```

Prints the planned per-seat rewrite (`from` bare alias → `to` tmux wrapper),
counts already-migrated, and fails loud on any drift (a profile not in its
expected pre-cutover state). Confirm the plan and pilot states before the window.

## The window (lead, detached shell)

```bash
# 0. pause the daemon refresh cadence (per its own control) + confirm seats checkpointed.
# 1. regenerate + strict-validate the manifest (fail loud if any seat unresolved):
python3 ~/bm-b2/scripts/generate_cockpit_manifest.py --write --strict

# 2. run the cutover DETACHED with the GO token (single Cmd+Q happens inside):
cd ~/bm-b2/scripts
COCKPIT_PHASE2_GO=LEAD-RATIFIED nohup ./cockpit_migrate.sh cutover --wave-size 5 \
    > ~/Library/Application\ Support/baker/cockpit/cutover_run.log 2>&1 &
```

Launch order inside the script (do not reorder): backup plist → quit Terminal →
drop cfprefsd cache → rewrite ALL profiles → mark ledger → `fleet_terminals.sh up`
→ reopen Terminal → per-seat smoke in waves of 5.

## Verify list (per seat, done by the smoke phase + your eyeball on :7800)

- `fleet_terminals.sh status` — every eligible seat `migrated` + session `up`.
- Wave report `~/Library/Application Support/baker/cockpit/cutover_wave_report.log` — one `PASS`/`FAIL` line per seat.
- On the cockpit page (:7800): card Start→up, open terminal in-page, a keystroke reaches the real tmux session.
- `lsof -nP -iTCP -sTCP:LISTEN | grep 127.0.0.1` — every ttyd bound loopback-only.

## Rollback triggers + how

- **A single seat fails smoke:** the script auto-rolls-back THAT seat — restores its
  profile CommandString from the backup (durable at the next coordinated Terminal
  restart, not instantly — Lesson 76) and re-seats it NOW via its direct alias.
  The rest stay migrated. No action needed; note the seat and diagnose after.
- **Broad failure — abort the whole cutover:**
  ```bash
  ~/bm-b2/scripts/cockpit_rollback.sh full --relaunch
  ```
  Tears down all cockpit substrate, restores every profile CommandString from the
  backup, and re-seats each agent via its direct alias immediately. The restored
  profiles become the on-launch commands again at the next Terminal.app restart.
- **Backup locations:** per-profile originals at
  `~/Library/Application Support/baker/cockpit/profile_backup.json`; full plist copy
  at `profile_backup.json.plist.bak`.

## Expected duration

~2–5 min for ~29 seats: quit+relaunch is seconds; the bulk is per-seat ttyd
install + web smoke (≤10 s/seat, waves of 5). Budget a 15-min quiet window with
margin for per-seat rollback + eyeball verification on :7800.

## Reboot owner (post-cutover, steady state)

The controller's launchd plist (`RunAtLoad`) runs `fleet_terminals.sh up` at
login, then the per-agent ttyd plists (KeepAlive) attach. tmux sessions do NOT
survive reboot — the processes relaunch fresh, same as today.
