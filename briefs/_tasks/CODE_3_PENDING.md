---
status: PENDING
brief: ~/baker-vault/_ops/briefs/director-facing-filter-v1.md
brief_id: DIRECTOR_FACING_FILTER_V1_PHASE_1
target_repo: baker-master
working_dir: ~/bm-b3
matter_slug: baker-internal
cross_matter_usage: [all-matters — fleet-wide pre-send filter affects every desk + AH1/AH2]
dispatched_at: 2026-05-19T11:20:00Z
dispatched_by: cowork-ah1
director_auth: 2026-05-19 chat — "ratified"
trigger_class: MEDIUM-HIGH
gate_chain:
  gate_1_static: REQUIRED (deputy / AH2 cross-lane)
  gate_2_security_review: REQUIRED (touches user-global hooks + ~/.claude/settings.json wiring + new vault build step)
  gate_3_cross_lane_architecture: REQUIRED (fleet-wide tooling, new plugin packaging pattern for Brisen, blast-radius covers every Claude Code session on Director's Mac)
  gate_4_2nd_pass_code_reviewer: REQUIRED (per ai-head/SKILL.md §Code-reviewer 2nd-pass Protocol trigger #4 — touches external-surface perimeter via user-global hooks + settings.json + new Anthropic plugin schema; high blast radius if a hook hangs/loops)
estimated_effort: 12-14h (multi-component, 15 stress fixtures, settings.json idempotent merge, plugin metadata)
working_branch_suggestion: b3/director-facing-filter-v1
reply_target: cowork-ah1 (bus topic `ship/director-facing-filter-v1`)
ship_target: 2026-05-22
phase_2_note: Filter #1 (Stakeholder-Authority validator subagent) + Filter #3 (Contract-Gate evidence-file) ship in separate brief, target 27 May, b2 lane parallel. Out of scope for THIS brief.
---

# CODE_3_PENDING — DIRECTOR_FACING_FILTER_V1_PHASE_1 — 2026-05-19

## Brief

Brief lives in baker-vault (fleet tooling, not pure baker-master code):

`~/baker-vault/_ops/briefs/director-facing-filter-v1.md` (committed baker-vault b5b0032)

Read end-to-end before starting. The brief is structured as 9 self-contained components — most have skeleton code + spec for you to flesh out. Stress fixtures are the source of truth for filter behavior; regex shape is for you to finalize against fixture expectations.

## Working branch

`b3/director-facing-filter-v1` in baker-master (`~/bm-b3`).

baker-vault changes (`_ops/people/authority-profiles.yml`, `_ops/people/README.md`, `_ops/processes/standing-rules-pack.md`) ship in a sibling vault PR — use `~/baker-vault` working tree. Coordinate both PRs in the same chat turn.

## Pre-requisites

- b3 idle confirmed by lead (bus #508).
- No upstream blockers — standalone build.
- baker-vault clean for new commits (specific-file adds; coordinate via bus with lead/cowork-ah1 before pushes).

## Acceptance criteria

Per brief §Ship gate (verbatim):

1. `pytest tests/test_director_facing_filter_v1.py -v` — all 15 fixtures green. Literal stdout in PR description.
2. `bash -n tests/fixtures/director-facing-filter/hooks/*.sh` — syntax-check on every hook.
3. `python3 -c "import json; json.load(open('tests/fixtures/director-facing-filter/.claude-plugin/plugin.json'))"` — plugin.json parseable.
4. `python3 tests/fixtures/director-facing-filter/scripts/build_authority_profiles.py --dry-run | python3 -c "import sys,yaml; d=yaml.safe_load(sys.stdin); assert 'rolf-hubner' in d['authority_profiles'], 'rolf-hubner profile missing'"` — Rolf profile builds correctly.
5. T1 + T2 fixtures pass (the ship criterion from MOVIE Desk brief).
6. Reentrancy: re-run any blocked fixture with `stop_hook_active=true` in payload → expect exit 0 (no block).
7. /security-review on the PR — pass / NO_FINDINGS.

## Ship gate

Literal `pytest` output (no "pass by inspection"). PR description includes pytest stdout + cross-link to baker-vault sibling PR (authority-profiles.yml + README + standing-rules-pack.md).

## Reporting (bus reply-to-sender — Director-ratified 2026-05-17)

On PR open, bus-post `cowork-ah1` (NOT `lead`) per `dispatched_by` field:

```bash
BAKER_ROLE=b3 ~/Desktop/baker-code/scripts/bus_post.sh cowork-ah1 \
  "ship/director-facing-filter-v1 — PR #<N> open; pytest <X/X>; T1+T2 ship criterion met; sibling baker-vault PR #<M>. Awaiting AH1+AH2 gate chain (gates 1-4 required per coordination header)." \
  ship/director-facing-filter-v1
```

cowork-ah1 (this brief's author) handles gate orchestration + merge.

## Heartbeat cadence (per §B-code stall chase — Director-ratified 2026-05-05)

Minimum every 12h while actively building. Two consecutive 12h misses → cowork-ah1 auto-surfaces stall to Director. Heartbeat = (a) UPDATE entry in this mailbox file with ISO timestamp, OR (b) commit on working branch with `mailbox(b3): heartbeat <ISO> — <where>` pattern, OR (c) ship-report file write.
