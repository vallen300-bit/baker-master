# BRISEN_LAB_WAKE_LISTENER_ALIAS_ALLOWLIST_1

**Repo:** `brisen-lab` (base `main` @a7b78f9) · **Worker:** b3 · **Dispatcher:** lead (AH1)
**Recommended effort:** medium (small additive change, one file + plist + installer; correctness matters but surface is tiny)
**Origin:** Mac Mini wiring arc 2026-07-04 (lead). Second wake-listener host (Mac Mini) is coming online for desk seats (#5140 / step-2 pilot). Current listener has NO per-machine filter — two hosts running listeners means every `wake_request` double-dispatches (`open brisen-lab://wake/<alias>` fires on BOTH machines).

---

## Problem

`tools/wake-listener/wake-listener.py` line 25: `ALLOWED_ALIASES = set(WAKEABLE_TERMINALS)` — every listener instance accepts every wakeable alias. Fine with one host; broken with two. Aliases are host-resident (b1-b4/deputy/clerk live on the laptop; desk seats will live on the Mini), so each host's listener must only dispatch its OWN aliases.

Also fix a known installer gap while in the file: `install.sh` copies `wake-listener.py` + plist but NOT `agent_identity_generated.py` — the listener import fails on a fresh host unless the identity file is copied by hand (bit us on the Mini 2026-07-03).

## Tasks

### T1 — Env allowlist in `wake-listener.py`
1. Read env `WAKE_ALIAS_ALLOWLIST` (comma-separated aliases, whitespace-tolerant).
2. If set and non-empty: `ALLOWED_ALIASES = requested ∩ set(WAKEABLE_TERMINALS)`. Log ONE startup line naming the effective set AND any requested-but-unknown aliases (loud, not fatal).
3. If unset/empty: current behavior (all of `WAKEABLE_TERMINALS`) — zero change for the existing laptop install.
4. Keep the existing `alias not in ALLOWED_ALIASES` warning path (line ~90) untouched — filtered wakes log `ignored wake_request` as today.

### T2 — Plist wiring
Add an `EnvironmentVariables` block to `com.baker.wake-listener.plist` with a `WAKE_ALIAS_ALLOWLIST` placeholder (empty string = allow-all default). Comment in the plist explaining per-host use.

### T3 — Installer
1. `install.sh`: copy `agent_identity_generated.py` into `$INSTALL_DIR` alongside the listener (fixes the fresh-host import gap).
2. `install.sh`: accept optional `WAKE_ALIAS_ALLOWLIST` env at install time; if set, `sed`/`plutil` it into the installed plist before bootstrap. Document in README.md (2-3 lines: laptop = unset, Mini = desk aliases).

## Constraints
- Additive only. Unset env ⇒ byte-identical behavior to today. Do NOT touch the SSE loop, handler-regression self-check, or foreground logic.
- Do NOT hand-edit `agent_identity_generated.py`.
- Do NOT deploy to any host — lead runs the Mini/laptop installs (host state is mid-arc, launchd domains are foot-gun-heavy).
- Tests first: unit test for the allowlist parse/intersection (pure function — extract it so it's testable).

## Acceptance criteria
1. `WAKE_ALIAS_ALLOWLIST="bb-desk, movie-desk"` ⇒ listener dispatches bb-desk/movie-desk wakes, logs-and-ignores `lead`.
2. Unknown alias in allowlist (e.g. `notreal`) ⇒ loud startup log, listener still runs with the valid subset.
3. Env unset ⇒ `ALLOWED_ALIASES == set(WAKEABLE_TERMINALS)` (regression test).
4. Fresh-dir `install.sh` run leaves a working `$INSTALL_DIR` (identity file present) — assert file copied.
5. Existing tests green; new tests for AC1-AC3.
6. Ship report to lead on bus; post-deploy AC is N/A (no deploy — installs are lead's), say so explicitly per `post-deploy-ac-bus-gate`.

## Notes for worker
- File: `tools/wake-listener/wake-listener.py` (~line 23-25 import + module constant; ~line 90 usage).
- Plist: `tools/wake-listener/com.baker.wake-listener.plist`. Installer: `tools/wake-listener/install.sh`.
- Branch: `b3/wake-listener-alias-allowlist-1`. PR to `main`, ship report + gate verdicts to lead on bus.
