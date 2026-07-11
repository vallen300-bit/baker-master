# B2 — WAKE_DELIVERY_PERSISTENCE_1 (ship)

**Dispatch:** bus #3341 from `lead`, 2026-06-18. Mac-side layer of the fleet wake outage (server layer = REMOVE_WAKE_TOPIC_GATE_1, PR #78).
**Repo:** brisen-lab. **PR:** #79 — https://github.com/vallen300-bit/brisen-lab/pull/79
**Branch:** `b2/wake-delivery-persistence-1`. **Commit:** `c51e5a4`.

## Root cause
The `brisen-lab://` URL scheme drifted off `Brisen Lab Wake.app` (`com.brisen.lab.wake`).
`System Information` and `com.zoom.video` **also claim `brisen-lab:`** (confirmed via
`lsregister -dump`), so Launch Services can bind the wrong one after a reboot/Spotlight
rescan. The wake-listener's `open brisen-lab://wake/<alias>` then failed LaunchServices
`-600/-609` and no terminal woke. Lead fixed it live with `lsregister -f`; this makes it durable.

## Deliverables
**(1) Login-time re-register guard**
- `tools/wake-handler/register-url-handler.sh` — idempotent `lsregister -f` on the Wake.app
  (+ optional `duti` default-handler pin if installed); loud-logs to `~/.brisen-lab/wake-register.log`.
- `tools/wake-handler/com.brisen.lab.wake-register.plist` — `RunAtLoad` LaunchAgent, runs the
  script on every login.
- `build.sh` installs both, bootstraps the agent in `gui/<uid>`, runs it once immediately.

**(2) Listener LaunchAgent domain hardening**
- `install.sh` comment: the listener MUST load via `launchctl bootstrap gui/<uid>`; a bare
  `launchctl kickstart` (no domain target) must never be used — the footgun that worsened the
  outage. Explicit-domain kick documented for any future need.

**(3) Self-healing listener** (`tools/wake-listener/wake-listener.py`)
- New pure helpers `classify_open()` + `update_handler_health()`. A single `-600/-609` stays a
  benign race (INFO, unchanged — `BUS_WAKE_LISTENER_BENIGN_RC_1`). **3 consecutive** benign
  failures with no successful dispatch in between = handler-regression signature → LOUD error +
  one-shot self-heal running `register-url-handler.sh`. Re-trips every 3 further failures;
  re-armed on the next success. Kept Python 3.9-safe (listener runs under `/usr/bin/python3`).

## Conflict surfaced + resolved
The existing `BUS_WAKE_LISTENER_BENIGN_RC_1` deliberately silenced `-600/-609` at INFO; the
dispatch asked for a LOUD warning on `-600/-609`. A naive loud-on-every-`-600` would re-flood the
log on benign races. Resolved by **consecutive-failure detection**: one is benign (quiet), a run
is the genuine regression (loud + self-heal). Honors both.

## Tests / verification
- `tests/test_wake_listener_health.py` — 9 cases (classify + streak/trip logic).
- **Full suite: 234 passed, 1 skipped** (pre-existing `test_a21_h7_auth`, unrelated) on local PG16.
- `shellcheck` clean; `bash -n` clean; listener compiles under `/usr/bin/python3` (3.9.6).
- Live-verified: `register-url-handler.sh` re-registers; `open brisen-lab://wake/__selftest__`
  resolves `rc=0`; our bundle claims `brisen-lab:`.

```
================== 234 passed, 1 skipped in 5.49s ==================
```

## Deploy (Mac-side, NOT auto)
`bash tools/wake-handler/build.sh` rebuilds the app + installs the guard agent. The LaunchAgent
was **not** auto-applied to the live Mac by this work — only `lsregister -f` was run live to verify
the script. Lead/Director runs `build.sh` to activate the durable guard.

## Bus
- Ship + G3 gate-request → `lead` #3342 (topic `gate-request/pr79`).

**Done rubric:** PR open + full suite green + scripts lint-clean + live-verified + G3 requested.
No post-deploy AC verdict owed from me — Mac-infra install is a lead/Director-run deploy step.
