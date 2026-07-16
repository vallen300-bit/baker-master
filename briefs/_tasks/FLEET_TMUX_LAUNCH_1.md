# FLEET_TMUX_LAUNCH_1 — tmux session substrate + migration machinery (Cockpit BRIEF A)

- **Status:** DRAFT — dispatch gated on (a) Director card-behavior confirm, (b) codex-arch re-G0 PASS on SCOPE_LAB_TERMINAL_COCKPIT_1 v1.1 (@f37fc5dd)
- **Parent scope (binding):** `briefs/SCOPE_LAB_TERMINAL_COCKPIT_1.md` v1.1 on branch `claude/terminal-window-organization-991ab4` — §6, §6a, §6b, §8 P1, §9, §12. This brief implements; the scope decides. On conflict, scope wins; flag, don't improvise.
- **Dispatcher:** lead. **Builder:** b-code (assigned at dispatch). **Gate:** codex cross-vendor PR review → lead merge.
- **Worktree:** builder's own clone. Repo: baker-master.

## Context

Cockpit arc, Director-ratified 2026-07-16 (card contract confirmed via mock; "start implementing"). This is BRIEF A of 2 — the session substrate BRIEF B's page attaches to. Parent scope v1.2 @0b199b4f carries all design decisions; codex-arch G0 blockers already folded (§6a/§6b).

**Context Contract (Harness V2):** builder reads ONLY: parent scope §6/§6a/§6b/§8/§9/§12, `scripts/install_forge_push.sh` + `scripts/launchd/*.plist` (pattern), `~/baker-vault/_ops/registries/agent_registry.yml` (data), `scripts/agent_identity_generated.sh` (generator family). No vault libraries, no matter context.
**Task class:** production infra (local Mac, no Render/prod-DB surface).
**Done rubric / done-state:** all ACs below pass LIVE on this Mac; ship report + bus post; done-state = merged + B3 pilot green + POST_DEPLOY_AC_VERDICT posted.
**Gate plan:** G1 self-test (ACs live) → codex cross-vendor PR review → lead line-read + merge → B3 pilot → STOP for lead GO before wider migration.

## Problem (1-liner)

26 terminal agents launch raw in Terminal.app; the cockpit needs every one hosted in a named tmux session, web-attachable, with a safe per-seat migration path and zero duplicate seats.

## Files Modified (expected)

- NEW `scripts/fleet_terminals.sh`, NEW launch-manifest generator (`scripts/` — name at builder's discretion, generated-file header mandatory)
- NEW per-agent ttyd plist generator + installer (mirrors `install_forge_push.sh`)
- NEW migration + rollback scripts; migration ledger (generated, `~/Library/Application Support/baker/cockpit/`)
- NO edits to registry, dashboard.py, bus clients, or existing plists.

## Deliverables

1. **Install step:** `brew install tmux ttyd` (verify brew present first; fail loud).
2. **Launch-manifest generator** (scope §6b): emits per-seat `slug/cwd/launch_cmd/port/eligible`; eligibility = `status: active` AND `runtime` prefix `terminal-`; port = 7600 + registry index; same generator family as `agent_identity_generated.sh`; NO hand-kept lists.
3. **`scripts/fleet_terminals.sh`** — `up | open <slug> | status`: `up` creates tmux sessions ONLY for ledger-migrated seats, registry order, idempotent; `open` attaches a native Terminal window; `status` prints per-seat migrated/pending + session up/down.
4. **Migration state machine** (scope §6a): per-seat checkpoint → stop old seat → tmux relaunch → dual-viewer smoke (native + web) → ledger mark. Scripted, per-profile, reversible.
5. **Per-agent ttyd plist generator + installer** (codex-arch pick): one launchd plist per agent from the manifest; `ttyd -W -i 127.0.0.1 -p <port> -c <cred>`; installer mirrors `install_forge_push.sh` TCC-safe pattern (`~/Library/Application Support/baker/`).
6. **Rollback script** (scope §12 + codex-arch N4 nit N3, #12047): honors Lesson 76 — restoring a profile on disk does NOT refresh Terminal.app's cache. Failed-seat recovery = immediate direct-alias relaunch (`/bin/zsh -lic '<alias>'` in a plain new window, no profile dependency) NOW, profile-cache restore lands at the next coordinated app restart. NO promise of instant per-seat profile-cache rollback anywhere in code, docs, or ship report.

**Scope alignment (v1.3 @2b7f18e4 — supersedes the v1.2 text this brief was cut from):** §6a is now Phase-1 sandbox pilots (B3, Brisen Desk; no profile edits, no live-seat kills) + ONE coordinated global cutover on my GO; §6b manifest = validated `alias` (no cwd), launch form `/bin/zsh -lic '<alias>'`, generation-time `type` probe fails loud; reboot owner = controller plist RunAtLoad → `fleet_terminals.sh up` → ttyd KeepAlive retry-attach. Build Phase-1 machinery + cutover scripts; do NOT execute Phase 2.

## Verification

Live-flow proofs, not compile-clean (Lesson #8): run each AC on this Mac; paste command output (tmux ls, lsof, ledger states) into the ship report.

## Quality Checkpoints / Acceptance criteria (live)

Scope §8 AC 1, 3, 4, 5, 6 verbatim, PLUS:
- AC-M1: with an UNMIGRATED seat's old window open, `fleet_terminals.sh up` creates NO second session for it (dup-seat proof).
- AC-M2: pilot = B3 seat migrated end-to-end (checkpoint → tmux → native+web smoke → ledger) with zero session loss; STOP after B3 — Brisen Desk + fleet migration fire only on lead GO.
- AC-M3: `lsof` proof in ship report: every ttyd bound 127.0.0.1 only.

## Out of scope

Cockpit page/controller (BRIEF B). Any fleet-wide migration beyond the B3 pilot. Registry schema changes. App-claude seats.

## Report

Ship report to `briefs/_reports/`, bus post to lead with PR ref; POST_DEPLOY_AC_VERDICT convention after merge + pilot.
