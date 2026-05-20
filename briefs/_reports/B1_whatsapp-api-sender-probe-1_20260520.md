---
brief_id: WHATSAPP_API_SENDER_PROBE_1
status: SHIPPED
pr: 232
pr_url: https://github.com/vallen300-bit/baker-master/pull/232
branch: b1/whatsapp-api-sender-probe-1
head_sha: 864e330
opened_at: 2026-05-20T13:59Z
builder: b1
dispatched_by: lead
reply_target: lead
bus_ship_msg: 610
bus_ship_topic: ship/whatsapp-api-sender-probe-1
---

# B1 ship report — WHATSAPP_API_SENDER_PROBE_1

## Outcome

PR #232 open against `main`. 14/14 pytest green including the new LID-row test. Backward-compatible diff: same response shape, additive WHERE column.

## Changes

- `outputs/dashboard.py`
  - L1018: Query `description` updated → "Match on sender, sender_name OR chat_id substring (ILIKE)".
  - L1024-1037: docstring rewritten with WAHA LID-migration note; `media_dropbox_path` paragraph preserved.
  - L1047 (the bug): `WHERE (sender ILIKE %s OR sender_name ILIKE %s OR chat_id ILIKE %s)`.
  - L1053: params tuple now `(%{c}%, %{c}%, %{c}%, from_date, to_date, limit)` — 3 contact slots, limit at index 5.
- `tests/test_whatsapp_pull_api.py`
  - Added `test_whatsapp_messages_lid_row_surfaces_via_phone_substring` — LID-shaped row (phone in `sender`, LID in `sender_name`/`chat_id`), query with phone substring `796720083`, asserts 1 hit.
  - Tightened `test_whatsapp_messages_sql_uses_canonical_media_column` — pins 3-column WHERE + 3 contact params + index-5 limit.

## Ship gates

| Gate | Result |
|---|---|
| pytest tests/test_whatsapp_pull_api.py -v | 14 passed, 7 warnings in 0.51s |
| py_compile dashboard.py | compile OK (pre-existing unrelated `\[` SyntaxWarning at L2761) |
| scripts/check_singletons.sh | OK: No singleton violations found |
| Pre-commit hook Parts 1-4 | clear (push-time `send_whatsapp()` kind-tag check also OK) |
| Diff size | 2 files / +54 / -8 (dashboard +12/-5, test +42/-3) |

## Notes for AH1

- Diff size on the test file is +42 vs brief budget of ≤30 LOC. ~30 of those lines are the new LID test itself (within budget); the remaining ~12 net are the canonical-media-column drift-guard tightening, which is required because adding a third `%{contact}%` to params shifted the limit index from 4 → 5 — leaving the old assertion in place would have given a misleading green. Flagging here in case AH1 wants a separate brief for guard-style additions next time.
- Post-merge live probe (per brief): `GET /api/whatsapp/messages?contact=796720083&from=2026-05-17&to=2026-05-20` — expect count ≥ 14 (4 from 2026-05-18 + 9+ from 2026-05-20 + 1 historical from Sep 2025 that's also now visible).

## Anchors

- Brief: `briefs/BRIEF_WHATSAPP_API_SENDER_PROBE_1.md` (main @ 9e642a5).
- Mailbox: `briefs/_tasks/CODE_1_PENDING.md` (PENDING at start; lead will flip COMPLETE post-merge).
- Bus dispatch #609 (ACKed); ship bus #610 (`ship/whatsapp-api-sender-probe-1`).
- Director ratification: "fire it" 2026-05-20.
