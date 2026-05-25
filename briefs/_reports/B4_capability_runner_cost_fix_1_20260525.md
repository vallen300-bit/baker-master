---
brief_id: CAPABILITY_RUNNER_COST_FIX_1
shipped_by: b4
shipped_at: 2026-05-25
pr: https://github.com/vallen300-bit/baker-master/pull/263
branch: b4/capability-runner-cost-fix-1
commit: 1071125
status: shipped_awaiting_review
reply_target: lead (AH1)
peer_brief: CAPABILITY_RUNNER_COST_RUNAWAY_DIAGNOSTIC_1
---

# B4 ship report — CAPABILITY_RUNNER_COST_FIX_1

## What shipped

Option A from B4 diagnostic §5: 14-LOC short-circuit guard in `triggers/waha_webhook.py` between `_baker_self = is_baker_self_chat(chat_id)` (line 1117) and `director_to_baker = (...)` (line 1118).

```python
if from_me and _baker_self:
    logger.info(
        f"COST_RUNAWAY_FIX_1: self-chat loop guard dropping fromMe=true "
        f"msg_id={msg_id} (audit-trail INSERT preserved upstream)"
    )
    return {"status": "self_chat_loop_guard_drop", "msg_id": msg_id}
```

Plus 1 new test class (`TestSelfChatLoopGuard`, 2 methods) in `tests/test_waha_outbound_capture.py`. One pre-existing test (`test_director_to_baker_fires_pm_signal_and_rag`) removed — it asserted pre-fix (buggy) behaviour; replaced with an explanatory comment pointing to the new class.

## Files modified

- `triggers/waha_webhook.py` — +20 LOC (14 functional + 6 comment)
- `tests/test_waha_outbound_capture.py` — +135 LOC, -10 LOC

Total diff: 2 files, +145 / -10.

## Pytest output (literal, python3.12)

### Target file
```
tests/test_waha_outbound_capture.py::TestAttributeSender::test_from_me_true_attributes_to_director PASSED [  5%]
tests/test_waha_outbound_capture.py::TestAttributeSender::test_from_me_false_passes_through PASSED [ 11%]
tests/test_waha_outbound_capture.py::TestAttributeSender::test_from_me_false_with_director_cus_marks_director PASSED [ 17%]
tests/test_waha_outbound_capture.py::TestAttributeSender::test_from_me_false_with_director_jid_marks_director PASSED [ 23%]
tests/test_waha_outbound_capture.py::TestAttributeSender::test_empty_sender_from_me_false PASSED [ 29%]
tests/test_waha_outbound_capture.py::TestIsBakerSelfChat::test_cus_form PASSED [ 35%]
tests/test_waha_outbound_capture.py::TestIsBakerSelfChat::test_jid_form PASSED [ 41%]
tests/test_waha_outbound_capture.py::TestIsBakerSelfChat::test_counterparty PASSED [ 47%]
tests/test_waha_outbound_capture.py::TestIsBakerSelfChat::test_none PASSED [ 52%]
tests/test_waha_outbound_capture.py::TestIsBakerSelfChat::test_empty PASSED [ 58%]
tests/test_waha_outbound_capture.py::TestIsBakerSelfChat::test_set_membership PASSED [ 64%]
tests/test_waha_outbound_capture.py::TestWebhookFromMeStorage::test_from_me_re_attributes_and_stores PASSED [ 70%]
tests/test_waha_outbound_capture.py::TestWebhookDirectorRouting::test_director_to_counterparty_fires_pm_signal_not_rag PASSED [ 76%]
tests/test_waha_outbound_capture.py::TestSelfChatLoopGuard::test_fromme_self_chat_short_circuits PASSED [ 82%]
tests/test_waha_outbound_capture.py::TestSelfChatLoopGuard::test_fromme_counterparty_still_routes PASSED [ 88%]
tests/test_waha_outbound_capture.py::TestRagDirectionTagging::test_outbound_and_inbound_tags SKIPPED [ 94%]
tests/test_waha_outbound_capture.py::TestChatIdMigration::test_lid_rows_normalized SKIPPED [100%]

======================== 15 passed, 2 skipped in 0.15s =========================
```

2 skipped = live-PG tests (`needs_live_pg` fixture) — expected; no `TEST_DATABASE_URL` exported.

### Regression subset (`-k "waha or capability"`)
```
========== 36 passed, 6 skipped, 2497 deselected, 9 warnings in 0.90s ==========
```

0 failures. 6 skipped split between live-PG (unrelated) + unknown `pytest.mark.asyncio` (cortex_run_stream — pre-existing, not introduced by this PR).

## Reviewer invariants (per brief §Gate-1 + Gate-2 reviewer instructions)

1. **Guard placement** — between `_baker_self =` and `director_to_baker =`. ✓ (Read tool verified.)
2. **Storage INSERT preserved** — `store.store_whatsapp_message()` at line ~983 runs upstream of guard, unconditionally. ✓
3. **Counterparty path unaffected** — `director_to_counterparty` continues to work (guard's `_baker_self` predicate excludes non-self-chat). Verified by new `test_fromme_counterparty_still_routes`. ✓
4. **No `attribute_sender` change** — fix at call site only. `triggers/waha_message_utils.py` untouched. ✓

## Trade-off (Gate-5 — Director ratification required pre-merge)

Guard drops Director's own phone-typed self-chat messages too. Baker cannot currently distinguish Baker-outbound vs Director-phone-outbound on the self-chat (both arrive as `fromMe=true`, both attribute to Director). If Director uses the self-chat as a Baker-Q&A interface, that interface stops working post-merge.

Alternative: Option B (per-msg-id origin-tag on outbound sends, ~1-2h estimated). Lead surfaces choice at Gate-5.

## Post-merge verification (lead observes)

- Render logs grep `COST_RUNAWAY_FIX_1` — drop events expected on every Baker outbound to self-chat (~10-30s cadence pre-stop).
- `api_cost_log` daily total for `source = 'capability_runner'` — expected to drop from €80-100/day to <€5/day within 24h.
- Gmail document writes resume (downstream consequence — V1+V2 visibility patches unblocked when breaker stops tripping).

## Anchors

- Brief: `briefs/BRIEF_CAPABILITY_RUNNER_COST_FIX_1.md` (commit `0799d92` on main)
- B4 diagnostic: `briefs/_reports/B4_capability_runner_cost_runaway_diagnostic_1_20260525.md` (§5 Option A)
- Mailbox: `briefs/_tasks/CODE_4_PENDING.md`
- PR: https://github.com/vallen300-bit/baker-master/pull/263
- Commit: `1071125`
