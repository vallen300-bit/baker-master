# FLEET_SESSION_START_SLIM_1 — per-role skill manifests + startup trim, ALL agents

dispatched_by: lead
Harness-V2: N/A — harness/config trim, no production code path; AC = measured token deltas.
priority: high
depends_on: LEAD_SESSION_START_SLIM_2_1 (@671f14e1 — lead-scope pilot; reuse its mechanism verbatim)

## Context

Director directive 2026-07-16 (ratified): lead startup 11% → ≤6.5% target ratified; scope EXTENDED fleet-wide same day — "review the load bearing of other agents… a researcher doesn't need all the skills that you have." Root cause measured in the lead brief: 137 vault skills' frontmatter (~109KB ≈ 27k tokens) registers into EVERY picker regardless of role, plus per-role orientation files restating shared rule bodies.

## Problem

Every agent picker (deputy, b1–b4, researcher, librarian, matter desks, dispatcher, cowork seats) loads the full skill catalog + its own orientation stack at session start. Estimated 8–12% of window burned before first task, per seat, every session. Workers on 200k windows are hit proportionally ~5× harder than lead's 1M.

## Work items

1. **Measurement sweep (mechanical, first).** For each picker in the 12-row install map: sum bytes of (a) registered skill frontmatter, (b) CLAUDE.md chain, (c) role-context hook injections, (d) orientation/Tier-0 mandatory reads. Output: one table, per-seat before-bytes + %-of-window (respect each seat's actual window size). Commit to `wiki/_fleet/audits/2026-07-fleet-session-start-load.md`.
2. **Role→skill matrix (judgment — deputy authors, codex gates, lead line-reads).** For each role, classify every vault skill KEEP / DROP-to-pointer. Default posture: desks keep matter+register skills, drop build/dispatch SOPs; workers (b1–b4) keep build/gate skills, drop registers + matter skills; researcher keeps research/verify/fan-out family only. Every DROP stays reachable via the shared `skill-index` pointer skill (built in the lead brief). NO shared skill description edits — registration scope only, same safety rule as lead brief.
3. **Rollout.** Apply manifests per picker AFTER the lead-scope pilot passes AC1 (≤6.5% live). One PR per picker-group (workers / desks / support seats), forge snapshot push after each, so a bad manifest never bricks the whole fleet at once.
4. **Orientation dedupe fleet-wide.** Same collapse as lead item 2: each role's orientation file ≤4KB, pointers not restated bodies. Desks' role-context hooks trimmed to their register spec.

## Files Modified

- Each picker's `.claude/skills/` registration (manifest/symlinks) — per 12-row map
- `wiki/_fleet/audits/2026-07-fleet-session-start-load.md` (NEW — measurement table)
- `_ops/agents/<role>/orientation.md` per role (item 4)
- `.claude/role-context/<role>.md` per picker (item 4)

## Verification

- Before/after byte table per seat committed with each rollout PR.
- One fresh-session context-meter reading per picker-group post-rollout.
- Per-seat spot-check: 3 dropped skills reachable via skill-index pointer.

## Acceptance criteria

- AC1: every seat's post-pin startup ≤6.5% of ITS window (workers may need a higher floor — surface, don't silently pass).
- AC2: zero skill-loss — every dropped skill discoverable via skill-index; mandatory-trigger skills for that role all still registered (e.g. researcher keeps researcher-verify-citations).
- AC3: no cross-seat regression — a seat never loses a skill its role file names as mandatory.
- AC4: rollout staged worker-group first (cheapest blast radius), desks last.

## Gate plan

deputy authors matrix → codex cross-vendor gate (fleet-wide config = high-impact class) → lead line-read → deputy-codex applies per picker-group → forge snapshot push → live meter readings close AC1.
