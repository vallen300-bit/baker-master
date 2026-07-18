# COCKPIT_BRIDGE_HARDENING_2 — kill-switch socket revoke + credential isolation

**Priority:** P1 (D1) / P2 (D2-D4) · **Worker:** b1 (bridge author) · **Dispatched:** 2026-07-18 (lead)
**Report topic:** `gates/cockpit-bridge-hardening-2`
**Source:** codex construction audit #12861 + codex-arch audit #12834-36 (P2 set). P1 token-gate finding from both audits already closed: brisen-lab PR #155 @9769b49 (fail-closed `cockpit_access`).

## Problem

The cockpit emergency stop and credential model have four verified gaps: the
server flag does not sever already-open websockets; the bridge agent accepts a
generic terminal key before its dedicated key; key rotation does not close an
open bridge socket; and one shared Basic credential is copied into every seat's
ttyd plist.

## Context

Surface: COCKPIT_IN_LAB_BRIDGE_1 (Lab `cockpit_bridge.py`/`app.py` ⇄ laptop
`scripts/cockpit_bridge_agent.py` ⇄ controller 127.0.0.1:7800). Runbook
`.claude/how-to/cockpit-cloud-access.md` — interim two-step-kill warning added
@this dispatch; D1 restores the one-step server-side kill the runbook originally
promised.

### Surface contract: N/A — backend/transport hardening only; no user-clickable surface added or modified (D1-D4 change socket/credential lifecycle behind the existing UI).

## Deliverables

**D1 (P1, brisen-lab):** flag transition OFF closes live sockets: a watcher
(per-connection task or shared periodic sweep, ≤5s cadence) checks
`cockpit_embed_enabled()`; on false → close bridge WS + all active terminal
WS + reject in-flight proxy streams. Runbook's "either switch alone" claim
becomes true again for the server flag; update the runbook block in the same PR
(baker-master side note: lead holds the interim warning edit — coordinate, don't
conflict).

**D2 (P2, baker-master `scripts/cockpit_bridge_agent.py`):** dedicated-key
isolation — agent must authenticate ONLY with `BRISEN_LAB_COCKPIT_BRIDGE_KEY`;
remove/refuse any fallback to generic terminal keys (codex-arch finding).

**D3 (P2, brisen-lab):** close-on-rotate — changing
`BRISEN_LAB_COCKPIT_BRIDGE_KEY` invalidates the open bridge socket (server
closes on next watcher tick when presented-key no longer matches; re-handshake
required).

**D4 (P2, baker-master `scripts/install_cockpit_ttyd.sh`):** per-seat ttyd
credentials (or controller-mediated per-session token) replacing the single
shared Basic credential in every plist; atomic rotation path documented.

## Files Modified

- brisen-lab: `cockpit_bridge.py`, `app.py` (watcher wiring), tests_unit/test_cockpit_bridge.py (D1, D3).
- baker-master: `scripts/cockpit_bridge_agent.py` (D2), `scripts/install_cockpit_ttyd.sh` + plist template (D4), `.claude/how-to/cockpit-cloud-access.md` (runbook restore), matching tests.

## Harness V2

- **Context Contract:** audits #12861 + #12834-36 bodies (bus), bridge code both
  repos, this brief. No vault reads needed.
- **Task class:** production security hardening, Tier-A merge path.
- **Done rubric / done-state class:** post-deploy AC bus verdict on the report
  topic; each AC PASS/FAIL with probe transcripts.
- **Gate plan:** codex bus-seat gate both tips → /security-review → lead merge →
  deploy → live AC verdict. codex-arch re-verify on P2 set.

## Verification

- Literal-flow probes: open a terminal WS through the Lab, unset flag, assert
  socket closes ≤5s (D1); rotate bridge key, assert open socket drops (D3);
  agent with generic terminal key only → handshake rejected (D2).
- Unit tests for each new branch; both repos' suites green (known py3.9-only
  local failures exempt — list them in the report).

## Quality Checkpoints / Acceptance criteria

- AC1: live terminal WS severed ≤5s after flag unset; new requests 404. Flag
  back ON restores service without agent restart.
- AC2: bridge agent refuses to authenticate with a non-dedicated key (test).
- AC3: key rotation closes the open bridge socket ≤5s (live probe).
- AC4: two seats have distinct ttyd credentials; rotating one doesn't touch the
  other (install-script test).
- AC5: no regression: cockpit grid + terminal open work through the Lab
  post-deploy (screenshot).

## Gate

Codex gate + /security-review pre-merge; lead merges; codex-arch owns re-verify
of the P2 set. Blast-radius ratification (one session = full fleet) is held by
lead as accepted-risk pending this brief's D2-D4 — noted for the record.
