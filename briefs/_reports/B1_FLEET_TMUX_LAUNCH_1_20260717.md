# B1 Ship Report — FLEET_TMUX_LAUNCH_1 (Cockpit BRIEF A)

- **Brief:** `briefs/_tasks/FLEET_TMUX_LAUNCH_1.md` @643e1bf2 (corrected) — tmux session substrate + migration machinery.
- **Binding scope:** `SCOPE_LAB_TERMINAL_COCKPIT_1.md` v1.3.2 @46d8134f (§6/§6a/§6b/§6c/§8/§9/§12).
- **Branch:** `b1/fleet-tmux-launch` off main. **Repo:** baker-master.
- **Dispatcher / gate:** lead → codex cross-vendor PR review → lead merge.
- **Task class:** production infra (local Mac). **Done-state:** merged + B3 pilot green + POST_DEPLOY_AC_VERDICT.
- **Rulings folded:** join v1.3.2 #12093 (reconcile-to-exactly-one, markers-only, provenance); credential ownership #12074; Phase-2 built-not-executed #12080.

## Deliverables (all committed on branch)

| # | Deliverable | File | Commit |
|---|---|---|---|
| 1 | brew install tmux ttyd | (live) `/opt/homebrew/bin/{tmux,ttyd}` | — |
| 2 | Launch-manifest generator (§6b, join v1.3.2) | `scripts/generate_cockpit_manifest.py` + generated `cockpit_launch_manifest.json` + `cockpit_manifest_reconciliation.md` | 851a677e→b30e1d3c |
| 3 | Fleet launcher up\|open\|status + ledger | `scripts/fleet_terminals.sh` | c376f6d0 |
| 4 | Migration state machine (§6a) | `scripts/cockpit_migrate.sh` | 1d642c43 |
| 5 | Per-agent ttyd plist generator + installer (§6c) | `scripts/install_cockpit_ttyd.sh` + `scripts/launchd/com.baker.cockpit-ttyd.plist.template` | e2f08018 |
| 6 | Rollback (§12, Lesson 76) | `scripts/cockpit_rollback.sh` | 1d642c43 |

## Manifest resolution (join v1.3.2 / #12093)

Derived at generation time from live sources only (registry eligibility + Terminal.app
CommandStrings + each alias's own zsh function markers). NO hand-kept list, NO registry
schema change, NO cwd parsing. Reconcile-to-exactly-one; conflict/zero/multiple = fail loud.

- **26/26 eligible seats resolved**, `--strict` exit 0. Pilot seats b3(7608) + brisen-desk(7628) both resolve with agreeing `BAKER_ROLE`+`FORGE_TERMINAL`.
- Latent defect surfaced (informational, non-eligible): BEN profile markers conflict (`BAKER_ROLE=BB_FINANCE` vs `FORGE_TERMINAL=ben`) → unresolved, not masked. Flagged to lead.
- Full per-profile provenance in `cockpit_manifest_reconciliation.md` for reviewer line-read.

## Acceptance criteria — LIVE results (not compile-clean; Lesson #8)

| AC | Result | Evidence |
|---|---|---|
| §8-1 / AC-M1 dup-seat guard | **PASS** | `fleet_terminals.sh up` creates sessions only for ledger `migrated` seats; unmigrated seat never launched; re-run no-op. Live: b3 up, 25 seats pending/down. |
| §8-3 kill cockpit/ttyd → native unaffected, reattach, zero loss | **PASS (live)** | Killed b3 ttyd (pid 84633) → tmux `b3` SURVIVED → KeepAlive relaunched ttyd (pid 90686) → web reattached HTTP 200 → session UP. |
| §8-4 reboot → launchd restores | **DESIGN (not reboot-tested)** | Reboot owner = controller plist `RunAtLoad` → `fleet_terminals.sh up` → per-agent ttyd `KeepAlive` retry-attach. Documented; honest: not exercised via a real reboot. |
| §8-5 / AC-M3 127.0.0.1-only | **PASS (live)** | `lsof`: `ttyd 90686 TCP 127.0.0.1:7608 (LISTEN)` — loopback only, no `*:`. no-cred→401, cred→200. |
| §8-6 rollback | **SCRIPTED, deferred** | `cockpit_rollback.sh seat b3 [--relaunch]` present; NOT run now (b3 held live for deputy-codex probe). Lesson 76 honored: no instant profile-cache-rollback promise; `--relaunch` re-seats via direct alias. |
| AC-M2 B3 end-to-end, zero session loss | **PASS (live)** | `cockpit_migrate.sh sandbox b3` exit 0: checkpoint→tmux→native+web smoke→ledger. b3 pane shows real Claude Code v2.1.158 / Opus 4.8 / B3 seat live. |

## STOP discipline

Pilot = **B3 only**. Brisen Desk + fleet migration + Phase-2 cutover all **locked on lead GO**.
`cockpit_migrate.sh cutover` is BUILT-NOT-EXECUTED — hard guard refuses without both
pilots green AND `COCKPIT_PHASE2_GO=LEAD-RATIFIED` (verified exit 3).

## Integration with BRIEF B (controller, deputy-codex)

Substrate installer deploys `fleet_terminals.sh` + manifest (as `launch_manifest.json`) to
`$DEPLOY_DIR` — the paths the merged controller installer validates. Credential is
controller-owned (#12074): read-only, fail-loud-if-absent, never created here.

## Harness V2

POST_DEPLOY_AC_VERDICT to be posted after merge + pilot per the convention. Done rubric
answered above (live AC table), not just "tests passed".
