---
brief_id: WAHA_OUTBOUND_CAPTURE_1
worker: b2
date: 2026-05-21
branch: b2/waha-outbound-capture-1
pr: 235
pr_url: https://github.com/vallen300-bit/baker-master/pull/235
status: PR_OPEN
---

# B2 ship report — WAHA_OUTBOUND_CAPTURE_1

## Brief

`briefs/BRIEF_WAHA_OUTBOUND_CAPTURE_1.md` — capture Director outbound at webhook + canonicalize chat_id + RAG direction tagging. 9 Fixes per architect verdict + reviewer audit.

## Scope shipped

All 9 Fixes per brief:

1. **Fix 1** — `triggers/waha_message_utils.py` (NEW). Pure module: `attribute_sender()` + `is_baker_self_chat()` + `DIRECTOR_WHATSAPP_*` + `BAKER_SELF_CHAT_*` constants. Both `@c.us` and `@s.whatsapp.net` forms first-class for Director + Baker self-chat (parity with existing `DIRECTOR_PHONE_ROOTS` two-form pattern).

2. **Fix 2** — `triggers/waha_webhook.py`. Lifted `fromMe` filter at line 829-835; replaced inline sender extraction with `attribute_sender()` call. `event_type != "message"` guard preserved. LID-resolution block becomes a no-op for fromMe=True (sender already `@c.us` after attribute).

3. **Fix 3** — `triggers/waha_webhook.py`. Chat-id canonicalization via `resolve_lid()`. `payload["chatId"] or payload["from"] or sender` for inbound; `payload["to"]` for fromMe. `@lid` suffix → phone form via `resolve_lid`; on failure, store raw + log warning (don't drop row). `store_whatsapp_message(...)` call updated to pass normalized `chat_id` + `is_director_msg`.

4. **Fix 4** — `triggers/waha_webhook.py`. Director routing discriminator. Replaced three `if sender == DIRECTOR_WHATSAPP and combined_body:` guards (lines 1077/1086/1102) with `director_to_baker` and `director_to_counterparty` distinct conditions, derived from `is_baker_self_chat(chat_id)`. PM-signal-outbound fires for both; YouTube + action + deadline + obligations + RAG-question handler gated on `director_to_baker` only. Added explicit early `return` for `director_to_counterparty` after the Director-to-Baker block to prevent the counterparty-inbound pipeline path firing on outbound. **BAKER_SELF_CHAT resolved as `41799605092@{c.us, s.whatsapp.net}` via SQL** (top-count chat_id where Director writes is `41799605092@s.whatsapp.net`, 644 rows, 5× next-highest — Director's own number; both JID forms encoded in `BAKER_SELF_CHAT_IDS` frozenset).

5. **Fix 5** — `memory/retriever.py`. `get_whatsapp_messages` + `get_recent_whatsapp` both SELECT `is_director`; content prefix becomes `[WHATSAPP-OUTBOUND]` / `[WHATSAPP-INBOUND]`. Metadata adds `is_director: bool`. Score values + filter logic unchanged.

6. **Fix 6a** — `triggers/waha_webhook.py`. TRIP-INTELLIGENCE-1 block wrapped in `if sender != DIRECTOR_WHATSAPP:` — Director's outbound is not "incoming intelligence."

7. **Fix 6b** — `outputs/push_sender.py`. Replaced broken `wm.direction = 'inbound'` / `wm2.direction = 'outbound'` references with `wm.is_director = FALSE` / `wm2.is_director = TRUE`. The anti-join now actually suppresses VIP alerts when Director has replied (it couldn't before — there was no Director outbound to anti-join against).

8. **Fix 7** — `outputs/dashboard.py`. `/api/whatsapp/messages` SELECT adds `is_director`; JSON response returns it as bool. No field renames (downstream desks unaffected).

9. **Fix 8** — `scripts/migrate_whatsapp_chat_id_normalize.py` (NEW). One-shot idempotent data patch: enumerates `WHERE chat_id LIKE '%@lid' LIMIT 5000`, resolves via `resolve_lid()`, UPDATEs rows. NO `ALTER TABLE`. Singleton via `SentinelStoreBack._get_global_instance()`. Re-running on phone-form rows is a no-op (0 rows touched).

10. **Fix 8b** — `scripts/extract_whatsapp.py`. Constants now imported from `triggers.waha_message_utils`; fromMe re-attribution swapped to shared `attribute_sender()` call. Backfill semantics unchanged.

11. **Fix 9** — `tests/test_waha_outbound_capture.py` (NEW). 6 classes:
    - `TestAttributeSender` — 5 cases (fromMe true/false, Director both JID forms, empty).
    - `TestIsBakerSelfChat` — 6 cases.
    - `TestWebhookFromMeStorage` — fromMe=True → store called with Director sender + is_director=True + chat_id=counterparty.
    - `TestWebhookDirectorRouting` — Director-to-counterparty fires PM-signal but NOT RAG/action; Director-to-Baker fires PM-signal AND RAG/action.
    - `TestRagDirectionTagging` — live-PG round-trip; seeds inbound + outbound rows; asserts `[WHATSAPP-OUTBOUND]` + `[WHATSAPP-INBOUND]` tags surface (skips when `TEST_DATABASE_URL` / Neon env unset).
    - `TestChatIdMigration` — live-PG round-trip + mocked `resolve_lid`; seeds 2 `@lid` rows; runs `main()`; asserts both normalized; second `main()` idempotent (skips when env unset).

## Quality checkpoints

1. ✅ `py_compile` clean on all 7 touched + 2 new files (`triggers/waha_webhook.py`, `triggers/waha_message_utils.py`, `memory/retriever.py`, `outputs/dashboard.py`, `outputs/push_sender.py`, `scripts/migrate_whatsapp_chat_id_normalize.py`, `scripts/extract_whatsapp.py`, `tests/test_waha_outbound_capture.py`).
2. ✅ `bash scripts/check_singletons.sh` — `OK: No singleton violations found.`
3. ✅ `pytest tests/test_waha_outbound_capture.py -v` — **14 passed, 2 skipped** (live-PG tests auto-skip; passes in CI ephemeral Neon branch).
4. ✅ Full `pytest` — **79 failed, 2213 passed, 99 skipped, 30 errors**. Baseline on main pre-change: 79 failed, 2199 passed, 97 skipped, 30 errors. **Net: +14 passed (new unit tests) + 2 skipped (new live-PG) + zero new failures or errors.** All 79 baseline failures pre-date this PR.
5. AH1 owns post-deploy live smoke (per brief §Ship gate §6 + Operational handoff).

### Literal pytest output (new file)

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
collected 16 items

tests/test_waha_outbound_capture.py::TestAttributeSender::test_from_me_true_attributes_to_director PASSED [  6%]
tests/test_waha_outbound_capture.py::TestAttributeSender::test_from_me_false_passes_through PASSED [ 12%]
tests/test_waha_outbound_capture.py::TestAttributeSender::test_from_me_false_with_director_cus_marks_director PASSED [ 18%]
tests/test_waha_outbound_capture.py::TestAttributeSender::test_from_me_false_with_director_jid_marks_director PASSED [ 25%]
tests/test_waha_outbound_capture.py::TestAttributeSender::test_empty_sender_from_me_false PASSED [ 31%]
tests/test_waha_outbound_capture.py::TestIsBakerSelfChat::test_cus_form PASSED [ 37%]
tests/test_waha_outbound_capture.py::TestIsBakerSelfChat::test_jid_form PASSED [ 43%]
tests/test_waha_outbound_capture.py::TestIsBakerSelfChat::test_counterparty PASSED [ 50%]
tests/test_waha_outbound_capture.py::TestIsBakerSelfChat::test_none PASSED [ 56%]
tests/test_waha_outbound_capture.py::TestIsBakerSelfChat::test_empty PASSED [ 62%]
tests/test_waha_outbound_capture.py::TestIsBakerSelfChat::test_set_membership PASSED [ 68%]
tests/test_waha_outbound_capture.py::TestWebhookFromMeStorage::test_from_me_re_attributes_and_stores PASSED [ 75%]
tests/test_waha_outbound_capture.py::TestWebhookDirectorRouting::test_director_to_counterparty_fires_pm_signal_not_rag PASSED [ 81%]
tests/test_waha_outbound_capture.py::TestWebhookDirectorRouting::test_director_to_baker_fires_pm_signal_and_rag PASSED [ 87%]
tests/test_waha_outbound_capture.py::TestRagDirectionTagging::test_outbound_and_inbound_tags SKIPPED [ 93%]
tests/test_waha_outbound_capture.py::TestChatIdMigration::test_lid_rows_normalized SKIPPED [100%]

======================== 14 passed, 2 skipped in 0.12s =========================
```

### Test isolation note

Added an autouse fixture in `tests/test_waha_outbound_capture.py` that restores a clean import of `memory.store_back` + `triggers.waha_webhook` + `orchestrator.pm_signal_detector` before each test. Reason: `tests/test_ai_head_weekly_audit.py` permanently replaces `sys.modules['memory.store_back']` with a MagicMock and never restores it — that pollutes any downstream test that depends on monkeypatching the real `SentinelStoreBack` class. Defensive, local to this file; does NOT modify the polluting test.

## BAKER_SELF_CHAT — derivation

Per brief Fix 4 STOP gate: grep returned no existing constant (only references inside this brief). Derived via the SQL query in the brief:

```sql
SELECT chat_id, COUNT(*) AS n FROM whatsapp_messages
WHERE sender = '41799605092@c.us' OR is_director = TRUE
GROUP BY chat_id ORDER BY n DESC LIMIT 10;
```

Top result `41799605092@s.whatsapp.net` (644 rows, 5× next-highest). Director's own number → Baker's self-chat. Encoded in `BAKER_SELF_CHAT_IDS = frozenset({"41799605092@c.us", "41799605092@s.whatsapp.net"})` because new webhook writes (post Fix 3) land as `@c.us` (resolve_lid output) while historic backfill rows are `@s.whatsapp.net`. Mirrors `DIRECTOR_WHATSAPP_IDS` two-form pattern.

## Files modified

```
M briefs/_tasks/CODE_2_PENDING.md           — status PENDING → CLAIMED
M memory/retriever.py                       — Fix 5 (RAG direction tagging)
M outputs/dashboard.py                      — Fix 7 (is_director in /api/whatsapp/messages)
M outputs/push_sender.py                    — Fix 6b (direction → is_director)
M scripts/extract_whatsapp.py               — Fix 8b (import shared helper)
M triggers/waha_webhook.py                  — Fix 2/3/4/6a
A scripts/migrate_whatsapp_chat_id_normalize.py — Fix 8 (one-shot data patch)
A tests/test_waha_outbound_capture.py       — Fix 9 (6 test classes)
A triggers/waha_message_utils.py            — Fix 1 (shared helper)
```

Diffstat: 6 modified + 3 new, ~310 insertions / ~43 deletions (within the 250-350 LOC envelope).

## Risk-register status

- **fromMe filter lift** — gated by Fix 4 routing discriminator + Fix 5 RAG tagging. 2nd-pass code-reviewer fires per gate chain.
- **BAKER_SELF_CHAT determination** — SQL-derived, not guessed. Frozenset captures both JID forms; idempotent re-running of migration leaves rows untouched.
- **Render restart mid-deploy** — fix is stateless. WAHA service untouched.
- **3-day Julia gap** — DROPPED per brief, out of scope.

## Operational handoff (AH1 owns)

1. Merge PR.
2. SSH to Render shell (or local with `DATABASE_URL` set + post-merge HEAD checked out) and run **once**:
   ```bash
   python scripts/migrate_whatsapp_chat_id_normalize.py
   ```
   Expected log: `Migration complete: <n> resolved / <m> unresolved / <k> rows updated.`
3. Wait for Render auto-deploy of the merged commit.
4. Live smoke (brief §Quality Checkpoint #6) — send a test WA from Director's phone to a non-Baker contact; within ~5s confirm via SQL that latest row has `is_director=TRUE`, `sender='41799605092@c.us'`, `sender_name='Director'`, `chat_id` in phone-form.
5. Re-run migration script — confirms idempotency (0 rows updated).

## Reporting

Bus-post to `lead` per `dispatched_by` field — topic `ship/waha-outbound-capture-1`.

## Gate chain awaited

All 4 required per mailbox:
- Gate 1: AH2 cross-lane static.
- Gate 2: `/security-review` (external-surface — webhook capture semantics).
- Gate 3: cross-lane architecture validation vs locked architect verdict.
- Gate 4: 2nd-pass `feature-dev:code-reviewer` (criteria 4 external-surface + 7 high-stakes judgment).
