# BRIEF: ARM_SEAT_PLUS_COWORK_AO_DESK_INSTALL_1 — install ARM (terminal seat) + batch cowork-ao-desk (app seat) rows

dispatched_by: lead
reply_to: lead (bus topic `fleet/arm-install`)
Harness-V2: task class = infra-install (multi-repo wiring) · Context Contract: this brief + SPEC_ARM_AGENT_v1.md + install SOP + bus #7974 (quoted below) · done rubric §Verification + §Quality Checkpoints · gate plan: per-repo PRs → codex bus G3 `reasoning_effort=medium` → lead merges in three-repo order (vault → baker-master → brisen-lab). POST_DEPLOY_AC_VERDICT v1 required (brisen-lab deploy + seeded bus test).

## Context
Two Director-ratified installs, batched single-editor to avoid two-agent collisions on the shared slug-lists (lead ruling #7959, cowork-ah1 batch accepted #7974):
1. **ARM** (Agent Relationship Manager) — new TERMINAL seat, slug `arm`. Fleet advisory: directory upkeep + conformance audits + routing advice; advise-only (lead keeps ALL dispatch/enforcement). Spec (final, codex-arch G0 PASS-WITH-INSTALL-NOTE #7927): `~/baker-vault/_ops/build/baker-os-v2/05_outputs/domain-agent-program/SPEC_ARM_AGENT_v1.md` — v1.1, F1-F4 folded. Seat: Sonnet-1M, registry AG-2xx shared-specialist, writes caged to `wiki/_fleet/**`.
2. **cowork-ao-desk** — new APP seat (Cowork), AG-309, full-peer twin of terminal ao-desk, mirror of cowork-bb-desk (AG-308). Local rows already DONE by cowork-ah1; only the SHARED-repo rows ride here (exact patches from #7974 quoted in §Implementation).

Canonical SOP: `~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md` (12-row map; enumerate every row, `N/A — <reason>` allowed, silence not). Install is registry-driven since MOVIE-desk install: registry row + generator regen covers most hardcoded lists — but verify each generated artifact, do not assume.

## Problem
ARM is ratified with no seat: no registry row, no picker, no bus key, no wake wiring, no cage. cowork-ao-desk is half-installed (local rows done, shared rows held for single-editor batching). Until both land, ARM's ramp (offline acceptance → 1-wk shadow → live) cannot start and cowork-ao-desk cannot join the bus.

## Estimated time: ~1 day · Complexity: Medium-High · Prerequisites: none (all gates passed; Director-ratified both)

## 12-row map — ARM (terminal runtime)
1. Picker `~/bm-arm/` — CREATE (CLAUDE.md Tier-0 reads per spec §2; canonical `~/bm-b1/scripts/bus_post.sh` path, NOT Desktop/baker-code).
2. Shell alias `~/.zshrc` `arm()` — CREATE.
3. Terminal.app profile — **N/A for you — Director/lead Tier-C UI action; flag in ship report as owed**.
4. Picker CLAUDE.md — CREATE (spec §1 charter + §2 structural enforcement blocks; cage + advise-only mandate inline).
5/6. bus_post.sh recipient+sender lists — via registry regen; VERIFY `arm` appears in regenerated `agent_identity_generated.sh`.
7. SessionStart drain hook — via regenerated fixture; VERIFY + install user-global (this host; Mini at next sync).
8. 1Password key `BRISEN_LAB_TERMINAL_KEY_arm` — CREATE (API_CREDENTIAL, 64-char, same generator as cowork-ah1 used for AG-309).
9. Render env `BRISEN_LAB_TERMINAL_KEYS` JSON — ADD `"arm"` (+ `"cowork-ao-desk"` same PUT); POST /deploys after (PUT alone does not restart); verify ALL expected keys present after.
10. brisen-lab front-end — `index.html` card `data-alias="arm"` + regenerated `agent_identity_generated.js`.
11. brisen-lab server — registry regen (bus.py KNOWN_CARD_SLUGS/app.py TERMINALS now generated); VERIFY all four legacy sites resolve `arm` + regression tests.
12. Forge snapshot pusher TERMINALS — ADD `arm` + `tests/test_forge_snapshot_push.sh` case; redeploy pusher on Mini (canonical host) post-merge.
Plus: wake rows (terminal runtime → generator emits wake-listener allowlist; wake-handler fnMap/cwdForAlias → `~/bm-arm`) + agent-bus-posting-contract SKILL desk list.

## 12-row map — cowork-ao-desk (app runtime, batched rows only)
Rows 1/2/4/8: **N/A — done locally by cowork-ah1 (#7974 "DONE by me")**. Rows 2/3/13/14-equivalents (Terminal profile, wake-handler, wake-listener): **N/A — app-claude runtime invisible to wake-handler (SOP 8th-pass; cowork-bb-desk precedent)**. Remaining shared rows = §Implementation patches.

## Implementation (verbatim from #7974 + ARM spec §2)
1. **baker-vault** `_ops/registries/agent_registry.yml`: insert AG-309 block after AG-308 (~line 302) exactly as #7974 PATCH 1; insert ARM block (agent_id next free AG-2xx, slug `arm`, status active, bus_enabled true, scope shared-specialist, runtime terminal, reports_to lead, model sonnet-1m per spec §5). Also `git add` the UNCOMMITTED `_ops/agents/cowork-ao-desk/orientation.md` sitting in the shared tree (cowork-ah1 flag) — **use a /tmp clone of baker-vault for all vault commits; the shared checkout is contested (lead incident 12:22Z)**.
2. **baker-master** `scripts/generate_agent_identity_artifacts.py` `_snapshot_path_for()` (~line 161): add `cowork-ao-desk → /Users/dimitry/bm-cowork-ao-desk` branch (verbatim #7974 PATCH 2) + `arm → /Users/dimitry/bm-arm`. REGEN `--write`; commit `orchestrator/agent_identity_data.py` + `scripts/agent_identity_generated.sh` + `tests/fixtures/session-start-bus-drain.sh`. Gate: `pytest tests/test_agent_identity_registry.py tests/test_agent_identity_generated.py`.
3. **brisen-lab** regen (agent_identity_generated.py + static/agent_identity_generated.js + tools/wake-listener copy); `index.html`: two cards (`arm`, `cowork-ao-desk` beside cowork-bb-desk ~line 122). Gate: `pytest tests/test_agent_identity_generated.py tests/test_bus_autowake.py`.
4. **Render env** (Hand Site B): add BOTH keys to `BRISEN_LAB_TERMINAL_KEYS` (op read the two 1P items; NEVER paste raw keys to bus/brief) → POST /deploys → verify keys present via GET env-vars.
5. **ARM artifacts** (spec §2): `arm_sql` wrapper (table ALLOW-LIST — introspect live schema first, do not guess columns), `arm_bus_reply.sh`, `arm_flag_lead.sh`, secrets read-deny PreToolUse hook, `wiki/_fleet/**` write cage, `arm_directory_reconcile.sh`. Mirror librarian's cage pattern (`~/bm-librarian` precedent).
6. **Post-merge**: cp regenerated drain-hook fixture → `~/.claude/hooks/session-start-bus-drain.sh`; verify `grep -E "arm|cowork-ao-desk"` hits both.

## Key constraints
- Single-editor: NO other agent edits shared slug surfaces until this lands (cowork-ah1 holding per #7974).
- Three-repo PR order: vault → baker-master → brisen-lab. One PR per repo, codex G3 each (`reasoning_effort=medium`), lead merges.
- ARM ramp does NOT start in this brief: install ends at seat-exists + bus-proven. Offline acceptance (directory v2 rebuild + 5 seeded routing Qs) + 1-wk shadow = follow-up brief.
- Never paste key material anywhere; 1P references only.
- All DB/API calls try/except; every generated-artifact claim verified by grep/pytest, not "regen ran".

## Verification (done rubric)
1. Seeded bus test per spec §2(d) install note: post to `arm` with real-but-foreign row ids → ARM key reads own inbox only; foreign read rejected (`reader_slug_mismatch`).
2. `curl /msg/arm` + `/msg/cowork-ao-desk` with own keys → 200; wake_health lists both slugs.
3. Live wake AC (per today's focus-guard lesson): one background wake → `arm` spawns a seat on this host; log lines cited.
4. Drain hook: session-start fixture renders both slugs' unread (unread=true surface per PR #506).
5. POST_DEPLOY_AC_VERDICT v1 on topic `fleet/arm-install` with evidence pointers (commits, deploy id, log lines, msg ids).

## Files Modified
- baker-vault: `_ops/registries/agent_registry.yml`, `_ops/agents/cowork-ao-desk/orientation.md` (add), `_ops/agents/arm/orientation.md` (new)
- baker-master: `scripts/generate_agent_identity_artifacts.py`, regenerated identity artifacts ×3
- brisen-lab: regenerated identity ×3, `static/index.html`, tests
- local: `~/bm-arm/**` (new), `~/.zshrc`, `~/.claude/hooks/session-start-bus-drain.sh` (post-merge install), forge pusher TERMINALS + test

## Do NOT Touch
- `wiki/**` outside `_fleet` cage artifacts — ARM's cage is the point.
- Existing seats' registry rows; `baker-vault/slugs.yml` (separate-repo rule).
- Any wake-handler main.scpt logic (focus-guard re-land is a separate gated lane).

## Quality Checkpoints
1. Every 12-row entry in ship report: DONE / N/A-with-reason — no silent rows.
2. Regen artifacts diffed + committed together (three files baker-master, three brisen-lab).
3. Render env verified key-by-key after PUT; deploy POSTED and live.
4. Both seeded tests pass with evidence; live wake AC cited.
5. Terminal.app profile row flagged as owed (Tier-C) in ship report.
