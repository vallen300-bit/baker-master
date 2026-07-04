---
name: forge-snapshot-push-install
description: Install / reinstall the laptop forge-snapshot-push launchd agent that feeds Brisen Lab terminal-card telemetry (daemon_last_seen). KeepAlive-hardened so it self-resumes.
when_to_use: The Brisen Lab dashboard shows terminal cards greyed / "WAKE PAUSED" / stale telemetry, or lead posts a lifecycle/forge-telemetry-stale alert, or after a laptop reboot / key rotation.
---

# Forge snapshot pusher — install & self-resume

`com.baker.forge-snapshot-push` is the laptop launchd agent that pushes each
terminal's git/mailbox/PR snapshot to Brisen Lab every 30s, populating
`forge_snapshots.daemon_last_seen`. When it dies, the dashboard's terminal cards
go stale — and since BRISEN_LAB_FORGE_TELEMETRY_DURABILITY_1 the cards grey
within ~10 min at read time and lead gets a one-shot `kind=alert` bus message.

## Install / reinstall (one line)

```bash
FORGE_KEY="$(op read 'op://Baker/forge-key/password')" bash ~/bm-b1/scripts/install_forge_push.sh
```

The installer is idempotent: it unloads any existing agent, re-renders the plist
with the current `FORGE_KEY`, co-deploys the worker + `agent_identity_generated.sh`
to the TCC-safe `~/Library/Application Support/baker/`, and `launchctl load -w`s it.
Verify: `launchctl list | grep forge-snapshot-push` · Log:
`~/Library/Logs/forge-snapshot-push.log`.

## ⚠️ Foot-gun — install ONLY from a Terminal session

Install from a real **Terminal** window, NOT from a Cowork App session. The Cowork
overlay wipes `~/Library` writes within ~15s, so a plist/worker installed from
inside Cowork silently disappears (lived incident 2026-07-04 — this is why the
pusher "died"). If you must trigger it from an agent, have the Director run the
one-liner via a `! <command>` prompt in a Terminal-backed session.

## Self-resume hardening (T3)

The plist carries `RunAtLoad` (resumes on reboot/login, once loaded) and
`KeepAlive` (resumes on crash). **Flagged to lead:** the worker is a fast-exit
periodic script with `StartInterval=30`, so literal `KeepAlive=true` makes launchd
relaunch on every exit (throttled to ~10s) — effectively a ~10s cadence (≈3× the
intended 30s) plus respawn log spam. If the 30s cadence matters, switch the plist
to the crash-only form, which preserves `StartInterval`:

```xml
<key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
```

Note that neither `RunAtLoad` nor `KeepAlive` survives a `launchctl unload` or a
Cowork `~/Library` wipe — those need a reinstall (the one-liner above). The durable
backstop for a silent death is the server-side staleness alarm, not the plist.
