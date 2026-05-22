---
status: COMPLETE
brief: briefs/BRIEF_HAG_DESK_CARDS_LOOP_INCLUDE_1.md
brief_id: HAG_DESK_CARDS_LOOP_INCLUDE_1
target_repo: brisen-lab
matter_slug: baker-internal
dispatched_at: 2026-05-22T10:30:00Z
dispatched_by: lead
target: b1
working_branch: b1/hag-desk-cards-loop-include-1
reply_to: lead
deadline: 2026-05-22T20:00:00Z
priority: tier-b
claimed_at: 2026-05-22T10:32:00Z
shipped_at: 2026-05-22T10:28:13Z
ship_pr: https://github.com/vallen300-bit/brisen-lab/pull/28
ship_commit: a4f90fc
report: briefs/_reports/B1_HAG_DESK_CARDS_LOOP_INCLUDE_1_20260522.md
bus_dispatch_msg: 669
bus_ship_msg: 670
---

# CODE_1_PENDING — HAG_DESK_CARDS_LOOP_INCLUDE_1 — 2026-05-22

**Brief:** `briefs/BRIEF_HAG_DESK_CARDS_LOOP_INCLUDE_1.md`
**Working branch:** `b1/hag-desk-cards-loop-include-1` (branch off `main` of brisen-lab)
**Repo:** brisen-lab (NOT baker-master)
**Pre-requisites:** PR #27 brisen-lab merged 10:17Z (KNOWN_CARD_SLUGS contains hag-desk)

## Acceptance criteria (testable)

### AC1 — bus.py:1005 for-loop tuple updated
- Single-element addition of `"hag-desk"` after `"b4"`, before the closing paren.
- No other line modified in `bus.py`.

### AC2 — Regression test added
- New test `test_v2_terminals_response_includes_hag_desk` in `tests/test_a3_a8_a9_bus.py`.
- Asserts `"hag-desk"` is in the slugs list returned by `/api/v2/terminals`.
- Uses existing `_CACHE.pop("v2_terminals", None)` pattern.

### AC3 — Test suite green
- `pytest tests/test_a3_a8_a9_bus.py -v` exits 0, all existing + new test PASS.
- Literal output pasted in PR description — no "pass by inspection."

### AC4 — Post-deploy smoke (AH1 Tier-B, out of b1 scope)
- AH1 runs `curl /api/v2/terminals` to confirm hag-desk slug present with `unacked_count > 0` + `recent_messages` populated.

## Ship gate
Literal `pytest tests/test_a3_a8_a9_bus.py -v` output in PR description.

## Reporting
- Bus-post `lead` on PR open: `BAKER_ROLE=b1 ~/bm-b1/scripts/bus_post.sh lead "PR #<num> opened: HAG_DESK_CARDS_LOOP_INCLUDE_1" ship/hag-desk-cards-loop-include`

## Files Modified (expected)
- `bus.py` — +1 element in tuple at line 1005
- `tests/test_a3_a8_a9_bus.py` — +1 test function

## Do NOT Touch
- Cortex special-case append at bus.py:1030-1043
- SQL queries
- _emit_badge_refresh() (already correct post PR #27)
- Front-end files
- db.py terminal_tiers / lifecycle.py token-pressure — separate concerns, out of scope
