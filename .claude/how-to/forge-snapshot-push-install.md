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

The plist carries `RunAtLoad` (resumes on reboot/login, once loaded) and a
**crash-only** `KeepAlive` (lead-ratified 2026-07-04, bus #5267):

```xml
<key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
```

Why the dict form and not `KeepAlive=true`: the worker is a fast-exit periodic
script with `StartInterval=30`. A bare `KeepAlive=true` relaunches it on *every*
exit (throttled to ~10s), collapsing the 30s cadence into a ~10s hot-loop plus
respawn log spam — the exact failure mode we are hardening against.
`{SuccessfulExit: false}` restarts only on a non-zero exit, so the 30s cadence is
preserved while a crash still self-heals.

Note that neither `RunAtLoad` nor `KeepAlive` survives a `launchctl unload` or a
Cowork `~/Library` wipe — those need a reinstall (the one-liner above). The durable
backstop for a silent death is the server-side staleness alarm, not the plist.
