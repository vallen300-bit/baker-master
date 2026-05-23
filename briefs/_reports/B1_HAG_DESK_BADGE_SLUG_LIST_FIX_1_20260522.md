---
brief_id: HAG_DESK_BADGE_SLUG_LIST_FIX_1
builder: b1
status: shipped (AC1-AC3); AC4 out-of-scope (AH1 Tier-B post-deploy smoke)
ship_pr: https://github.com/vallen300-bit/brisen-lab/pull/27
ship_commit: 77831f5
target_repo: brisen-lab
dispatched_by: lead
dispatched_at: 2026-05-22T08:22:00Z
claimed_at: 2026-05-22T08:25:00Z
shipped_at: 2026-05-22T08:29:00Z
bus_dispatch_msg: 662
bus_ship_msg: 663
---

# B1 ship report — HAG_DESK_BADGE_SLUG_LIST_FIX_1

## Outcome

One-element tuple addition to `bus.py:895-897` `KNOWN_CARD_SLUGS` — added `"hag-desk"` as the 9th element. This closes the last server-side gap from HAGENAUER_DESK_ON_BUS_1 (PR #25 brisen-lab, merged 2026-05-21): the bus recipient whitelist, `/msg/hag-desk` route, card slot, and `app.js` TERMINALS were all wired, but `_emit_badge_refresh` at `bus.py:1056` filters affected recipients through `KNOWN_CARD_SLUGS`, so hag-desk dispatches never produced the `bus_badge_change` SSE envelope and the card's unread badge never updated in real-time.

Regression test added that mirrors the existing positive-case pattern at `tests/test_a3_a8_a9_bus.py::test_inbox_badge_sse_event_emitted_on_post`, swapping the recipient from `b3` → `hag-desk` and asserting both the `bus_badge_change` envelope fires AND `badges["hag-desk"]` is present with `unacked_count >= 1`.

## Files changed

| File | Change |
|---|---|
| `bus.py` (brisen-lab) | +1 element in `KNOWN_CARD_SLUGS` tuple at line 895-897 |
| `tests/test_a3_a8_a9_bus.py` (brisen-lab) | +`test_bus_badge_change_emitted_for_hag_desk` (~36 LOC) |
| `briefs/_tasks/CODE_1_PENDING.md` (baker-master) | frontmatter PENDING → CLAIMED, `claimed_at` set |

## Acceptance criteria

### AC1 — KNOWN_CARD_SLUGS tuple updated ✅
`bus.py:895-897` now includes `"hag-desk"` as the 9th element. No other line in `bus.py` touched (verified `git diff --stat bus.py` = 2 insertions/deletions, both on line 896).

### AC2 — Regression test added ✅
`test_bus_badge_change_emitted_for_hag_desk` added immediately after `test_inbox_badge_sse_event_emitted_on_post`. Mirrors the helper usage (`_post`, `app_module._subscribers` queue attach, `_CACHE` invalidation) — no new fixtures, no `conftest.py` edit. The `BRISEN_LAB_TERMINAL_KEYS` env map does not need a `hag-desk` entry because the test posts AS `lead` (with `lead-key`) TO `["hag-desk"]`; only the recipient side flows through `KNOWN_CARD_SLUGS`.

### AC3 — Test suite green ✅
Literal `pytest tests/test_a3_a8_a9_bus.py -v` output (live Neon test DB via `TEST_DATABASE_URL_BRISEN_LAB`):

```
collected 14 items

tests/test_a3_a8_a9_bus.py::test_a3_dispatch_kind_sets_wake_attempted_at_on_drain PASSED [  7%]
tests/test_a3_a8_a9_bus.py::test_a4_exclude_self_filter PASSED           [ 14%]
tests/test_a3_a8_a9_bus.py::test_a5_director_only_tier_validates PASSED  [ 21%]
tests/test_a3_a8_a9_bus.py::test_a8_soft_delete_sender_within_window PASSED [ 28%]
tests/test_a3_a8_a9_bus.py::test_a8_director_can_delete_anytime PASSED   [ 35%]
tests/test_a3_a8_a9_bus.py::test_a9_retention_forever_soft_delete_only PASSED [ 42%]
tests/test_a3_a8_a9_bus.py::test_inbox_badge_count_in_terminals_response PASSED [ 50%]
tests/test_a3_a8_a9_bus.py::test_inbox_badge_clears_on_ack PASSED        [ 57%]
tests/test_a3_a8_a9_bus.py::test_inbox_badge_excludes_broadcast_wildcard PASSED [ 64%]
tests/test_a3_a8_a9_bus.py::test_inbox_badge_sse_event_emitted_on_post PASSED [ 71%]
tests/test_a3_a8_a9_bus.py::test_bus_badge_change_emitted_for_hag_desk PASSED [ 78%]
tests/test_a3_a8_a9_bus.py::test_inbox_badge_excludes_soft_deleted PASSED [ 85%]
tests/test_a3_a8_a9_bus.py::test_ack_forbidden_emits_no_badge_change PASSED [ 92%]
tests/test_a3_a8_a9_bus.py::test_inbox_badge_multi_recipient PASSED      [100%]

================== 14 passed, 3 warnings in 111.09s ==================
```

### AC4 — Post-deploy smoke (AH1 Tier-B) — pending
brisen-lab auto-deploys on push to `main`. After merge + Render redeploy, AH1 runs the SSE-tap + bus-post smoke from the brief (§Post-merge deploy) and confirms `bus_badge_change` envelope with `hag-desk` in `badges` dict.

## Bus posts

- Dispatch: msg 662 (lead → b1, `dispatch/hag-desk-badge-slug-list-fix-1`)
- Ship: msg 663 (b1 → lead, `ship/hag-desk-badge-slug-fix`)

## Notes for AH1 / lead

- Brief noted "test fixture may need a hag-desk entry — surface as blocker if so." Not a blocker: `_post()` posts AS the auth-key holder (`lead`) TO the URL path's `{terminal}`; only `KNOWN_CARD_SLUGS` membership matters for the badge path, and that's exactly what this fix addresses.
- `_build_terminals_response()` (`bus.py:900`) iterates `KNOWN_CARD_SLUGS` to build `/api/v2/terminals`. Once merged + deployed, the hag-desk card will appear there too (currently injected client-side via `app.py:40` hotfix in PR #26). AH1 may want to revisit whether that hotfix is still needed post-deploy.
