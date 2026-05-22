---
brief_id: HAG_DESK_CARDS_LOOP_INCLUDE_1
builder: b1
status: shipped (AC1-AC3); AC4 out-of-scope (AH1 Tier-B post-deploy smoke)
ship_pr: https://github.com/vallen300-bit/brisen-lab/pull/28
ship_commit: a4f90fc
target_repo: brisen-lab
dispatched_by: lead
dispatched_at: 2026-05-22T10:30:00Z
claimed_at: 2026-05-22T10:32:00Z
shipped_at: 2026-05-22T10:28:13Z
bus_dispatch_msg: 669
bus_ship_msg: 670
---

# B1 ship report — HAG_DESK_CARDS_LOOP_INCLUDE_1

## Outcome

One-element addition to the for-loop tuple at `bus.py:1005` in `_build_terminals_response()`. This was the **third + final** hardcoded slug-list missed by HAGENAUER_DESK_ON_BUS_1 (PR #25):

1. ✅ Snapshot pusher TERMINALS array → PR #238 baker-master (HAG_DESK_HEARTBEAT_DAEMON_1)
2. ✅ `bus.py:895` `KNOWN_CARD_SLUGS` tuple → PR #27 brisen-lab (HAG_DESK_BADGE_SLUG_LIST_FIX_1, merged 10:17Z)
3. ✅ `bus.py:1005` card loop → **PR #28 brisen-lab** (this brief)

Before the fix: even though PR #27 caused `bus_badge_change` SSE events to fire correctly for hag-desk, the `/api/v2/terminals` REST response (used by Director's "Bus inbox" modal) never built a card for hag-desk because the for-loop iteration excluded the slug. Director saw "(no bus messages)" on the modal even when hag-desk inbox had unacked rows.

Cortex special-case append at lines 1030-1043 intentionally left alone — separate render path (no git/mailbox snapshot fields).

## Files changed

| File | Change |
|---|---|
| `bus.py` (brisen-lab) | +1 element in for-loop tuple at line 1005 |
| `tests/test_a3_a8_a9_bus.py` (brisen-lab) | +`test_v2_terminals_response_includes_hag_desk` (~10 LOC) |
| `briefs/_tasks/CODE_1_PENDING.md` (baker-master) | frontmatter PENDING → CLAIMED → COMPLETE |

## Acceptance criteria

### AC1 — bus.py:1005 for-loop tuple updated ✅
`hag-desk` appended as 8th element, immediately before the closing paren. No other line in `bus.py` touched (verified `git diff --stat bus.py` = 1 insertion / 1 deletion on line 1005).

### AC2 — Regression test added ✅
`test_v2_terminals_response_includes_hag_desk` placed right after `test_bus_badge_change_emitted_for_hag_desk`. Uses `_CACHE.pop("v2_terminals", None)` per the existing pattern. Asserts `"hag-desk"` appears in the slugs list from `/api/v2/terminals`.

### AC3 — Test suite green ✅
Literal `pytest tests/test_a3_a8_a9_bus.py -v` output (live Neon test DB):

```
collected 15 items

tests/test_a3_a8_a9_bus.py::test_a3_dispatch_kind_sets_wake_attempted_at_on_drain PASSED [  6%]
tests/test_a3_a8_a9_bus.py::test_a4_exclude_self_filter PASSED           [ 13%]
tests/test_a3_a8_a9_bus.py::test_a5_director_only_tier_validates PASSED  [ 20%]
tests/test_a3_a8_a9_bus.py::test_a8_soft_delete_sender_within_window PASSED [ 26%]
tests/test_a3_a8_a9_bus.py::test_a8_director_can_delete_anytime PASSED   [ 33%]
tests/test_a3_a8_a9_bus.py::test_a9_retention_forever_soft_delete_only PASSED [ 40%]
tests/test_a3_a8_a9_bus.py::test_inbox_badge_count_in_terminals_response PASSED [ 46%]
tests/test_a3_a8_a9_bus.py::test_inbox_badge_clears_on_ack PASSED        [ 53%]
tests/test_a3_a8_a9_bus.py::test_inbox_badge_excludes_broadcast_wildcard PASSED [ 60%]
tests/test_a3_a8_a9_bus.py::test_inbox_badge_sse_event_emitted_on_post PASSED [ 66%]
tests/test_a3_a8_a9_bus.py::test_bus_badge_change_emitted_for_hag_desk PASSED [ 73%]
tests/test_a3_a8_a9_bus.py::test_v2_terminals_response_includes_hag_desk PASSED [ 80%]
tests/test_a3_a8_a9_bus.py::test_inbox_badge_excludes_soft_deleted PASSED [ 86%]
tests/test_a3_a8_a9_bus.py::test_ack_forbidden_emits_no_badge_change PASSED [ 93%]
tests/test_a3_a8_a9_bus.py::test_inbox_badge_multi_recipient PASSED      [100%]

================== 15 passed, 3 warnings in 119.00s ==================
```

### AC4 — Post-deploy smoke (AH1 Tier-B) — pending
After PR #28 merge + Render auto-deploy, AH1:
- `curl /api/v2/terminals` confirms `slugs` list contains `hag-desk` with `unacked_count > 0` and `recent_messages` populated.
- Director's browser modal "Bus inbox" view for hag-desk now renders actual messages (not "(no bus messages)").

## Bus posts

- Dispatch: msg 669 (lead → b1, `dispatch/hag-desk-cards-loop-include-1`)
- Ship: msg 670 (b1 → lead, `ship/hag-desk-cards-loop-include`)

## Notes for AH1 / lead

- Brief noted (line 24) that `db.py:226-235 terminal_tiers` lacks hag-desk and `lifecycle.py:491-493` token-pressure config also lacks it; both flagged as out-of-scope for this brief. If post-deploy Director encounters auth-tier or token-pressure issues for hag-desk, those are separate fix briefs.
- With this PR merged + deployed, the prior PR #26 baker-master hotfix that injected hag-desk client-side via `app.py:40` TERMINALS list may now be redundant. AH1 may want to evaluate whether to revert / consolidate.
