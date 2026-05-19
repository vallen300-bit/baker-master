---
status: COMPLETE
completed_at: 2026-05-19T22:02:56+00:00
pr: 227
pr_url: https://github.com/vallen300-bit/baker-master/pull/227
merge_sha: 5cb9a3e0
deploy: cowork-ah1 ran deploy_to_user_global.sh from ~/bm-b2 — clean; 8 hooks + lib/call_validator.py + 2 skills + pack live in ~/.claude/
ship_anchor_bus: event 572 (cowork-ah1 → b2, 2026-05-19T22:02:56Z)
brief: ~/baker-vault/_ops/briefs/director-facing-filter-v1_1.md
brief_id: DIRECTOR_FACING_FILTER_V1_1_PHASE_2
target_repo: baker-master
working_dir: ~/bm-b2
matter_slug: baker-internal
cross_matter_usage: [all-matters — fleet-wide pre-send filter judgment layer affects every desk + AH1/AH2]
dispatched_at: 2026-05-19T17:48:00Z
dispatched_by: cowork-ah1
director_auth: 2026-05-19 chat — "ratified" (Phase 2 brief af69e89; lane assignment via lead routing bus #554)
trigger_class: HIGH (novel ground — first Brisen hook calling Anthropic API at runtime + 1Password key fetch + 2 new validator skills + evidence-file pattern + annotation pass-through)
gate_chain:
  gate_1_static: REQUIRED (deputy / AH2 cross-lane)
  gate_2_security_review: REQUIRED — API-key handling especially (1Password fetch, no disk write, no log leak in error reasons, subprocess stderr explicitly dropped)
  gate_3_cross_lane_architecture: REQUIRED (cross-turn state file pending-annotations.json + first runtime Anthropic API call from hook layer + new SKILL.md prompt-template runtime pattern + multi-session race interaction with Phase 1 mode state)
  gate_4_2nd_pass_code_reviewer: REQUIRED (external-surface perimeter + API key handling + new dependency on anthropic SDK in hook Python env)
estimated_effort: 10-12h (lib/call_validator.py + 2 trigger Stop hooks + 2 validator SKILL.md files + UserPromptSubmit annotation passthrough + 17 stress fixtures with mocked SDK + plugin.json v1.1.0 update + settings.json wiring + deploy script extension + EVIDENCE_FILE_FORMAT.md documentation)
working_branch_suggestion: b2/director-facing-filter-v1-1
reply_target: cowork-ah1 (bus topic `ship/director-facing-filter-v1-1`)
ship_target: 2026-05-27
phase_1_anchor: baker-vault e17f9b7 + baker-master a59e07e (merged + deployed 2026-05-19T17:33Z)
hot_dependencies:
  - ~/baker-vault/_ops/people/authority-profiles.yml (16 profiles incl. rolf-hubner — verified loadable)
  - ~/baker-vault/_ops/processes/standing-rules-pack.md (R1 ratified)
  - ~/.claude/state/brisen-filter-mode (lazily-created by strategic-mode-router.sh; Phase 1 ships this)
  - op CLI authenticated (op://Baker API Keys/API Anthropic/credential resolves)
  - anthropic Python SDK installable in hook env (pip3 install --user anthropic pyyaml)
prior_mailbox_state: superseded — previous CODE_2_PENDING.md was UI_SURFACE_PREBRIEF_V2 COMPLETE 2026-05-19T16:34:28Z (preserved in CODE_2_COMPLETE.md). b2 idle since.
---

# CODE_2_PENDING — DIRECTOR_FACING_FILTER_V1_1_PHASE_2 — 2026-05-19

## Brief

Brief lives in baker-vault (fleet tooling, not pure baker-master code):

`~/baker-vault/_ops/briefs/director-facing-filter-v1_1.md` (committed baker-vault — pull latest before reading; today's commit landed on main)

Read end-to-end before starting. Structured as 7 self-contained components (lib + 2 Stop hook triggers + 2 validator SKILL.md + 1 UserPromptSubmit + fixtures). Most components have skeleton code + spec; fixtures are source of truth for behavior.

**Phase 1 context for you (b2):** Phase 1 shipped + deployed on Director's Mac 2026-05-19. 5 new hooks live (strategic-mode-router, authority-profile-preload, pre-send-checklist, synthesis-vs-taxonomy, standing-rules-scan) + recommendation-check.sh patched. Your Phase 2 hooks (stakeholder-authority-trigger, contract-gate-trigger, annotate-pending-checker) layer ON TOP — don't disturb existing wiring. `update_user_settings.py` is idempotent — re-run safely.

## Working branch

`b2/director-facing-filter-v1-1` in baker-master (`~/bm-b2`).

## Pre-requisites

- b2 idle confirmed by lead (bus #554) — UI_SURFACE_PREBRIEF_V2 PR #99 merged + mailbox COMPLETE.
- Phase 1 MERGED + DEPLOYED — vault e17f9b7 + master a59e07e + ~/.claude/hooks/*.sh present.
- Vault deps loaded: authority-profiles.yml has 16 entries, standing-rules-pack.md has R1.
- 1Password CLI authed: `op whoami` returns identity (verified by cowork-ah1 during Phase 2 brief authoring).
- anthropic SDK + pyyaml installable for hook Python env (deploy script pip-installs --user).

## Acceptance criteria

Per brief §Ship gate (verbatim):

1. `pytest tests/test_director_facing_filter_v1.py -v` — 32 fixtures green (15 from Phase 1 + 17 new). Literal stdout in PR.
2. `bash -n tests/fixtures/director-facing-filter/hooks/*.sh` — syntax-check on every hook including Phase 1's (no regression).
3. `python3 tests/fixtures/director-facing-filter/lib/call_validator.py --self-test` — module loads, op fetch works (or degrades cleanly).
4. Plugin.json v1.1.0 parseable + lists all 8 hooks (5 from Phase 1 + 3 from Phase 2).
5. T1 (Rolf authority) MUST BLOCK in deliberate mode (the Phase 2 ship-criterion from MOVIE Desk brief; this was DEFERRED-PASS in Phase 1 → Phase 2 closes it).
6. T2 (M1-M5) continues to BLOCK on Filter #2 + Filter #4 (Phase 1) AND now ALSO on Filter #3 (Phase 2) — verify multi-block path.
7. Mode degradation: every Phase 2 BLOCK fixture in light mode → no block + annotation file populated.
8. Validator degradation: every `lib_validate_*` fixture → PASS with reason (never blocks on infra failure).
9. /security-review on the PR — pass / NO_FINDINGS (API key handling especially).
10. Live smoke: deploy to ~/.claude/hooks, send a deliberate prompt with Rolf authority assertion in a fresh session, verify block fires.

## Ship gate

Literal `pytest` output (no "pass by inspection"). PR description includes pytest stdout. Sibling baker-vault PR if any (Phase 2 doesn't add vault files; just consumes Phase 1's authority-profiles.yml).

## Reporting (bus reply-to-sender — Director-ratified 2026-05-17)

On PR open, bus-post `cowork-ah1` (NOT `lead`) per `dispatched_by`:

```bash
BAKER_ROLE=b2 ~/Desktop/baker-code/scripts/bus_post.sh cowork-ah1 \
  "ship/director-facing-filter-v1-1 — PR #<N> open; pytest <X/X>; T1 (Rolf) BLOCK verified in deliberate; mocked SDK clean in CI. Awaiting AH1+AH2 gate chain (all 4 required per coordination header)." \
  ship/director-facing-filter-v1-1
```

cowork-ah1 handles gate orchestration + merge sequence.

## Lessons from Phase 1 ship (apply proactively)

1. **shared-FS race on baker-vault clones** — always `git checkout -b X origin/main` (explicit) when branching from baker-vault. Local main can be advanced by unpushed commits from concurrent agents. Scar: Phase 1 vault PR #100 closed for scope creep.
2. **Specific-file adds in vault** — never `git add -A` for vault commits. List specific paths.
3. **Path-normalize before set comparison** — `update_user_settings.py` does this now (Phase 1 final form); follow the same pattern if extending settings-merger.
4. **Bundle hooks per matcher entry on shared-event ordering** — Phase 1's `_find_or_create_matcher_entry()` is the pattern. Phase 2 adds 3 more hooks (2 Stop + 1 UserPromptSubmit) — bundle Stop ones into existing Phase 1 Stop matcher OR a new matcher; UserPromptSubmit ones append to existing matcher.
5. **stop_hook_active reentrancy guard** — required on every NEW Stop hook (Filter #1 + #3 triggers both).
6. **Stress-fixture-first** — define expected behavior in fixtures BEFORE writing hook code. Phase 1's 12-min initial build relied on this.

## Heartbeat cadence (per §B-code stall chase — Director-ratified 2026-05-05)

Minimum every 12h while actively building. Two consecutive 12h misses → cowork-ah1 auto-surfaces stall to Director. Heartbeat = (a) UPDATE entry in this mailbox file with ISO timestamp, OR (b) commit on working branch with `mailbox(b2): heartbeat <ISO> — <where>` pattern, OR (c) ship-report file write.
