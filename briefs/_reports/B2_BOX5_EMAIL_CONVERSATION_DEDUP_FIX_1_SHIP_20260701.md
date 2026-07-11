# B2 SHIP REPORT — BOX5_EMAIL_CONVERSATION_DEDUP_FIX_1

- **Brief:** `briefs/_tasks/BOX5_EMAIL_CONVERSATION_DEDUP_FIX_1.md`
- **Dispatched by:** lead (bus #4968); diagnose #4973 → ack/GO #4977
- **Branch:** `b2/box5-email-conversation-dedup-fix-1` · **Commit:** `9ff61594` · **PR:** #453 → `main`
- **Date:** 2026-07-01 · **Task class:** BUGFIX (P0) · **Harness-V2:** applies
- **Gate handoff:** G1 done (this) → **G3 codex bus terminal (effort HIGH)** → lead G4 `/security-review` + cross-source trace → merge → deploy → AC6 live canary + `POST_DEPLOY_AC_VERDICT v1`.

## Done rubric
The email sink now dedups + stores **per message**, not per conversation, so replies on an already-seen thread are never dropped — across all four sources — with no repeat-processing regression and no migration.

## Diagnose gate (reported #4973, lead-acked #4977)
- **Affected sources:** gmail + graph only (both thread on conversation-level). Exchange + bluewin were never affected — their `thread_id` is already the per-message RFC822 `Message-ID`.
- **Per-message key availability:** gmail `metadata['message_id']` (latest) + `all_message_ids`; graph needed a 1-line add (`metadata['message_id'] = m['id']`); exchange/bluewin fall back to `thread_id` (=Message-ID).
- **Upsert:** `email_messages` PK = `message_id`; `store_email_message` `ON CONFLICT (message_id) DO UPDATE`. Per-message `message_id` ⇒ each reply a distinct row. **No migration.**

## Fix (two files)
- `triggers/email_trigger.py::_process_email_threads` — `msg_key = metadata.get("message_id") or thread_id`; all three layers keyed on `msg_key`:
  1. within-cycle guard (`_seen_this_cycle`) — moved to per-message (lead-blessed deviation #4977): graph's per-folder delta returns multiple messages of one conversationId in a single poll; a thread-level guard dropped all but the first intra-cycle.
  2. persistent dedup `is_processed`/`mark_processed` — on `msg_key`.
  3. storage `message_id = msg_key`; `thread_id` retained in the `thread_id` column for correlation/routing.
  No separate thread-novelty gate (deputy-codex #4975 + codex-arch: that gate *was* the drop).
- `triggers/graph_mail_trigger.py::_to_thread` — carry `metadata['message_id'] = m['id']` (per-message Graph id, already in `_SELECT`).

## Acceptance criteria → tests (`tests/test_box5_email_dedup.py`, 9 tests)
| AC | Test | Note |
|----|------|------|
| AC1 reply-both-stored across cycles | `test_ac1_reply_on_same_conversation_both_stored_across_cycles` | **PROVEN fail-on-main** (stash-verified: main stored only `['AAQk-ESG-conversation']`) |
| AC2 no-repeat (ALERT-DEDUP-1 held) | `test_ac2_no_new_store_or_pipeline_when_no_new_message` | |
| AC3 cross-source key resolution | `test_ac3_per_source_key_resolution` | parametrized graph/gmail/exchange/bluewin |
| AC4 within-cycle paginated dup collapses | `test_ac4_within_cycle_paginated_duplicate_collapses` | |
| AC4b graph multi-msg/convo/cycle both stored | `test_ac4b_graph_multi_message_same_conversation_one_cycle_all_stored` | **also fail-on-main** |
| AC6 proxy (ESG reply shape) | `test_esg_reply_accepted_after_earlier_thread_message` | live AC6 is lead's post-deploy step |

## G1 self-check (literal runs)
- `py_compile` — OK (both source files + both test files).
- **Fail-on-main proof:** `git stash` the two source fixes → AC1 stored `['AAQk-ESG-conversation']` (reply dropped) + AC4b `['conv-1']` (collapsed) → both FAIL; `stash pop` → both PASS.
- `pytest tests/test_box5_email_dedup.py tests/test_graph_mail_trigger.py tests/test_layer0_dedupe.py` — **75 passed, 1 skipped** (live-PG auto-skip).
- `scripts/check_singletons.sh` — OK. Clean rename check (`_seen_threads_this_cycle` → `_seen_this_cycle`, no stragglers).
- **No migration**, no new env, no new scheduled job. Diff = 2 source + 2 test files.

## NOT verified (fail-loud)
- Unit tests use mocked store/pipeline/trigger_state — **not** run against live PG or the live pipeline. AC6 (the ESG reply actually ingesting + routing to the BB desk end-to-end) is unverified and is lead's post-deploy canary step.
- Not merged, not deployed, not codex/lead-reviewed yet.

## Reviewer focus (G3 codex, HIGH)
- Cross-source key correctness (esp. exchange/bluewin fallback to `thread_id`=Message-ID is genuinely per-message).
- ALERT-DEDUP-1 property truly held (AC2) — no re-run on unchanged content.
- within-cycle deviation soundness (graph intra-cycle multi-message).

---

## F1 fold — codex G3 HIGH: attachment store key aligned to per-message row key (commit `a83852f0`)

**Finding (codex G3, HIGH):** F0 moved the email-**row** key to per-message but left the **attachment** store keys on the old conversation key → split-brain. The read path joins `email_attachments.message_id == email_messages.message_id`, so attachments became a **false-empty surface** for exactly the tickets this brief fixes.

**Invariant enforced:** attachment store key MUST equal the email-row key, per row, every source.
- **graph** (`_capture_graph_attachments`): `store_key = m.get("conversationId") or fetch_id` → `fetch_id or m.get("conversationId")` (= `m['id'] or conversationId` = the row's `msg_key`).
- **gmail** (`_capture_gmail_thread_attachments`): `row_message_id = metadata.thread_id or message_id` → `metadata.message_id or thread_id`. Every attachment enumerated across the thread lands under this one row key.
- **exchange:** no attachment-capture path (nothing to diverge). **bluewin:** already keyed by `dedup_key` (=Message-ID=thread_id=row key) — verified consistent, unchanged.
- **No migration**; pre-fix rows are internally consistent (row+attachments both under conversationId) so **no backfill** — only forward ingest made per-row consistent.

**Tests:**
- `test_box5_email_dedup.py`: +`test_graph_attachment_key_equals_email_row_key` (local, PROVEN fail-on-pre-F1), +`test_graph_capture_read_parity_end_to_end` (live-PG: capture → `list_attachments` reachable under the per-message key, empty under old conversationId).
- `test_forward_attachment_parity.py`: graph + gmail assertions updated from the OLD conversationId contract to the NEW per-message contract.
- `test_graph_mail_trigger.py`: `test_store_key_is_conversation_id_when_present` → `..._is_per_message_id_when_present` (new contract).

**Verified:** F1 key-parity **PROVEN fail-on-pre-F1** (git-stash: attachment keyed `AAQk-conv` vs row `AAMk-msg`) → pass-on-fix. Sweep: **78 passed, 2 skipped** (live-PG auto-skip). Singletons clean.
**NOT verified:** live-PG read-parity (`test_graph_capture_read_parity_end_to_end`) + the gmail path (`tools.gmail` needs `mcp`) run in codex/CI, not locally.

**Re-gate:** codex G3 (HIGH) again.
