---
status: PENDING
brief: inline
trigger_class: TIER_B_DAEMON_PARSER_LOGIC
dispatched_at: 2026-05-13
dispatched_by: ai-head-1 (AH1)
target: b3
director_ratification: Director 2026-05-13 "sent dispatch by bus to all the workers to deal with all of the issues step by step"
priority: P2
phase: 1 of 1
expected_pr_count: 1 (baker-master)
expected_branch: b3/forge-daemon-frontmatter-status-authoritative-1
expected_complexity: low (~30-45 min including Case F fixture)
mandatory_2nd_pass: FALSE
hard_ship_gate: literal `bash tests/test_forge_snapshot_push.sh` GREEN (all existing cases + new Case F + new frontmatter-status case) pasted in PR description
gates_required:
  - AH2 /security-review
  - picker-architect
last_heartbeat: null
heartbeat_cadence: 12h max
---

# CODE_3_PENDING — FORGE_DAEMON_FRONTMATTER_STATUS_AUTHORITATIVE_1 — 2026-05-13

**Repo:** baker-master (`~/bm-b3`)
**Branch:** `b3/forge-daemon-frontmatter-status-authoritative-1`
**Base SHA:** `git pull --ff-only origin main` first (current main = 948af22 or newer; includes your prior BRISEN_LAB_CARD_STATE_FIX_1 ship)

## Problem (two folded items)

### #1 — Parser: frontmatter `status:` field as authoritative

Today the forge daemon (`~/Library/Application Support/baker/forge_snapshot_push.sh` — source in repo) classifies mailbox state purely by filename suffix (`_PENDING` / `_COMPLETE` / `_DROPPED`).

**Drift caught 2026-05-12 eve:** b4's `CODE_4_PENDING.md` had frontmatter `status: STAGED` (Director-ratified pivot 2026-05-11) but filename was still `_PENDING` → daemon reported pending → red card lied. Rectified manually by renaming to `_DROPPED`.

**Fix:** read frontmatter `status:` and treat as authoritative when present; fallback to filename pattern when no frontmatter or no `status:` key.

### #2 — Test fixture for daemon Case F (complete-in-one-clone, empty-in-other)

`tests/test_forge_snapshot_push.sh` is missing a case that covers `pick_active_clone` scoring when one clone has a COMPLETE mailbox and a sibling clone is empty. This is the bug AH1 hotfixed at `f5012a9` after Director observed oscillation post-merge. The fix is in place; the test isn't.

**Fix:** add Case F to `tests/test_forge_snapshot_push.sh`. Two-clone setup: clone-A has `CODE_X_COMPLETE.md`, clone-B is empty. Assert `pick_active_clone` returns clone-A (score 50 > 0).

## Acceptance criteria

1. Parser reads frontmatter `status:` when present; treats as authoritative; falls back to filename pattern otherwise.
2. Mapping: frontmatter `status: STAGED` / `DROPPED` / `IN_PROGRESS` / `PENDING` / `COMPLETE` map to daemon classifications (decide sensibly — `STAGED` and `DROPPED` should NOT show as pending/red).
3. Case F added to `tests/test_forge_snapshot_push.sh`; passes pre + post.
4. New test case added covering frontmatter-status authority (assert: filename `_PENDING` + frontmatter `status: DROPPED` → daemon classifies as DROPPED, not PENDING).
5. No regression on existing 5 cases.

## Ship gate

Literal `bash tests/test_forge_snapshot_push.sh` exit-0 output (all cases PASS, including new Case F + frontmatter-status case) pasted in PR description.

## Bus-post on ship

```
BAKER_ROLE=b3 ~/Desktop/baker-code/scripts/bus_post.sh lead "SHIP: FORGE_DAEMON_FRONTMATTER_STATUS_AUTHORITATIVE_1 — PR #<N> open. Frontmatter status authoritative; Case F fixture added. Ship gate: forge_snapshot_push tests all PASS." ship/forge-daemon-frontmatter-status-authoritative-1
```
