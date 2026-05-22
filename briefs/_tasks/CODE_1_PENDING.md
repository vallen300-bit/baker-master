---
status: PENDING
brief: briefs/BRIEF_HAG_DESK_BADGE_SLUG_LIST_FIX_1.md
brief_id: HAG_DESK_BADGE_SLUG_LIST_FIX_1
target_repo: brisen-lab
matter_slug: baker-internal
dispatched_at: 2026-05-22T08:22:00Z
dispatched_by: lead
target: b1
working_branch: b1/hag-desk-badge-slug-list-fix-1
reply_to: lead
deadline: 2026-05-22T20:00:00Z
priority: tier-b
---

# CODE_1_PENDING — HAG_DESK_BADGE_SLUG_LIST_FIX_1 — 2026-05-22

**Brief:** `briefs/BRIEF_HAG_DESK_BADGE_SLUG_LIST_FIX_1.md`
**Working branch:** `b1/hag-desk-badge-slug-list-fix-1` (branch off `main` of brisen-lab repo)
**Repo:** brisen-lab (NOT baker-master)
**Pre-requisites:** none — HAGENAUER_DESK_ON_BUS_1 already merged 2026-05-21 added hag-desk to bus whitelist + card slot + JS TERMINALS; this brief closes one missed tuple

## Acceptance criteria (testable)

### AC1 — KNOWN_CARD_SLUGS tuple updated
- `bus.py:895-897` includes `"hag-desk"` as the 9th element.
- No other line in `bus.py` modified.

### AC2 — Regression test added
- New test `test_bus_badge_change_emitted_for_hag_desk` in `tests/test_a3_a8_a9_bus.py`.
- Mirrors existing positive-case pattern (find the ~lines 200-225 positive-emission test, copy, swap recipient to `hag-desk`).
- Asserts `bus_badge_change` envelope fires + `badges["hag-desk"]` is present with `unacked_count >= 1`.

### AC3 — Test suite green
- `pytest tests/test_a3_a8_a9_bus.py -v` exits 0 with all existing tests + new test PASS.
- Literal output pasted in PR description — no "pass by inspection."

### AC4 — Post-deploy smoke (AH1 Tier-B, out of b1 scope)
- AH1 runs SSE-tap + bus_post on prod after Render auto-deploys.
- Must observe `bus_badge_change` event for hag-desk.

## Ship gate
Literal `pytest tests/test_a3_a8_a9_bus.py -v` output (all green) in PR description.

## Reporting
- Bus-post `lead` on PR open: `BAKER_ROLE=b1 ~/bm-b1/scripts/bus_post.sh lead "PR #<num> opened: HAG_DESK_BADGE_SLUG_LIST_FIX_1" ship/hag-desk-badge-slug-fix`
- Bus-post `lead` on any blocker: same script, topic `blocker/hag-desk-badge-slug-fix`

## Files Modified (expected)
- `bus.py` — +1 element in tuple
- `tests/test_a3_a8_a9_bus.py` — +1 test function

## Do NOT Touch
- Any front-end file (`static/*`) — already wired
- Any other line in `bus.py`
- `_build_terminals_response()` — picks up new tuple entry automatically
