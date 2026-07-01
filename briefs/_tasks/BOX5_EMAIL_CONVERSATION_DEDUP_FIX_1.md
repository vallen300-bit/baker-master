# BRIEF: BOX5_EMAIL_CONVERSATION_DEDUP_FIX_1

**Dispatched to:** b2 (ran the #4956 root-cause trace — has full context)
**dispatched_by:** lead (AH1)
**Task class:** BUGFIX — P0 silent data loss on the primary ingestion path.
**Harness-V2:** applies (production-facing behavior change on the email sink). Context Contract + done rubric + gate plan below.
**Effort recommendation:** high (surgical but cross-source blast radius; partially reverses ALERT-DEDUP-1 — must not re-introduce the alert-spam it fixed).

---

## PROBLEM (root cause CONFIRMED — b2 #4956 + AH1 code read 2026-07-01)

`triggers/email_trigger.py::_process_email_threads` (def @871) dedups the **persistent, cross-cycle** layer on `thread_id` (=conversationId), not on a per-message id:

- **L918** `if trigger_state.is_processed("email", thread_id): skipped += 1; continue`
- **L927** `trigger_state.mark_processed("email", thread_id)`
- **L931** `message_id = thread_id`  ← storage + pipeline source_id both keyed on the thread, not the message
- **L936-948** `store.store_email_message(message_id=message_id, thread_id=thread_id, …)`

**Effect:** the first message on a conversation is processed; **every subsequent reply on that same conversationId hits `is_processed`=True → `continue` → is NEVER stored in `email_messages`, NEVER pipelined, NEVER routed.** Silent, permanent, cross-source: gmail / exchange / graph / bluewin all funnel through this sink. This is the exact failure Director escalated — "signals not reaching the ticketing desk." Verified live: Siegfried's 2026-07-01 reply on the Aukera/ESG conversation (first seen 06-29) was dropped this way.

**Why thread_id was chosen (the trap you must not fall back into):** the L917 comment records that a prior attempt at message-level dedup "only partially matched trigger_log entries, causing repeat processing every cycle." So the fix is NOT "just switch the key to `message_id`" — it is "switch to a **stable, always-present per-message id** and mark/check the SAME key, so no message is processed twice AND no reply is dropped."

## CONTEXT CONTRACT (read before touching code)

- **Three distinct dedup layers — know which you are changing:**
  1. **Within-cycle** (L888-892) `_seen_threads_this_cycle` on `thread_id` — guards Gmail pagination returning a thread twice in ONE poll. **Leave thread-level** unless your per-message key trivially subsumes it. Low risk; do not gold-plate.
  2. **Cross-cycle persistent** (L918/L927) `trigger_state.is_processed/mark_processed("email", thread_id)` — **THE BUG. This is your target.**
  3. **Storage key** (L931/L936) `message_id = thread_id` — **also your target** (storage must be per-message so replies persist).
- **Per-message ids are available in metadata** — L271 already reads `metadata.get("all_message_ids")` and `metadata.get("message_id")`. **DIAGNOSE GATE (do this FIRST, report before coding):** confirm whether the `thread["metadata"]` objects reaching `_process_email_threads` actually carry `all_message_ids` / a per-message id, for EACH source (graph/exchange, gmail, bluewin). If a source lacks a stable per-message id at this point, trace upstream to `check_new_emails` (@706) / the extractor and surface it — do NOT invent one. Candidate stable keys: graph `m['id']` / `internetMessageId`; gmail message id; exchange internetMessageId.
- **`store_email_message` upsert semantics:** confirm the `email_messages` PK / `ON CONFLICT` target. Today with `message_id=thread_id`, a reply's INSERT conflicts on the thread key and DO-NOTHINGs (a second reason replies never land). Per-message `message_id` must make each reply a distinct row. Verify the conflict target is `message_id` (or add the right one) — do not silently change a PK without a migration.
- **`SentinelStoreBack` / `SentinelRetriever` singletons** — use `_get_global_instance()` (hard rule, CI-guarded `scripts/check_singletons.sh`). The code already does.
- **All DB/API in try/except** (repo hard rule) — the store call already is; keep that.
- **`trigger_state` (`triggers/state.py`)** `is_processed(source, source_id)` @494, `mark_processed(source, source_id)` @529 — source stays `"email"`; only the `source_id` value changes from thread_id → per-message key. Confirm `mark_processed` is idempotent / append-safe at scale (trigger_log growth is acceptable; it already grew per-thread).

## FIX DESIGN (two-tier — store everything, gate only the expensive step)

1. **Persistent dedup + storage key → per-message.** Pick the newest per-message id in the thread (or iterate message ids). Check `is_processed("email", <per_message_key>)`; if new → store the message (message_id=`<per_message_key>`, thread_id COLUMN=conversationId) and mark_processed that key. Result: first message processed once; each reply processed once; a re-poll with no new reply skips. This alone fixes the drop.
2. **Thread-level novelty ONLY as a gate before the expensive pipeline/alert step (preserve ALERT-DEDUP-1's intent).** A genuine new human reply SHOULD reach the desk, so it SHOULD run the pipeline. But guard against re-running the Opus pipeline on unchanged thread content (e.g. a message re-delivered under a churned id). Keep/adjust a thread-novelty check right before `pipeline.run()` so cost is spent only on genuinely-new thread state. **Do not over-build** — if the per-message key is provably stable, message-level dedup already gives once-only semantics; a heavy thread-novelty layer may be unnecessary. Call this in your Diagnose report and let codex-arch's parallel design note (bus, topic `design/box5-email-dedup-two-tier`) settle the tier boundary before you finalize.
3. **received_date watermark (L904-914)** is orthogonal — leave it. (Bluewin 2035-dated poisoning is a SEPARATE dropped brief; do not touch.)

## ACCEPTANCE CRITERIA

- **AC1 (regression test — the bug):** a test that feeds two messages on the SAME conversationId across two poll cycles asserts BOTH are stored in `email_messages` (2 distinct rows) AND both produce a pipeline/trigger event. Must FAIL on current `main`, PASS after fix.
- **AC2 (no-repeat, ALERT-DEDUP-1 property):** re-running a poll with NO new message produces ZERO new stored rows and ZERO new pipeline runs for that thread (prove the old "repeat processing every cycle" trap is not reintroduced).
- **AC3 (cross-source):** the per-message key is resolved correctly for graph/exchange, gmail, and bluewin (or Diagnose surfaces any source that can't and it's explicitly scoped). No source silently falls back to thread_id.
- **AC4 (within-cycle pagination):** the L888 within-cycle guard still collapses a paginated-duplicate thread in one poll (no double-store within a single cycle).
- **AC5:** `pytest` green for touched modules; `bash scripts/check_singletons.sh` clean; if the PK/conflict target changes, a migration is included and `applied_migrations.lock` handling is correct.
- **AC6 (live canary — the goal):** after deploy, the previously-dropped ESG/Aukera reply (Siegfried, 2026-07-01) ingests into `email_messages`, flows through the pipeline, and — because it carries Aukera keywords + thread-continuity to a BB-AUK-001-bound anchor — **routes to the Baden-Baden desk ticket**. This is the end-to-end proof: ingestion sentinel → ticketing → BB desk.

## GATE PLAN (Harness V2)

- **G1 (b2):** Diagnose report first (per-source key availability + upsert semantics) → build → AC1-AC5 green locally → ship to a branch, open PR, bus-post `ship/box5-email-conversation-dedup-fix-1` to lead.
- **G3 (codex bus terminal, NOT the subagent — HARD RULE):** route the PR to the live `codex` bus terminal for independent review (it runs py_compile/pytest/check_singletons + real repo exploration). Effort: high.
- **G4 (AH1/lead):** `/security-review` + independent trace of the cross-source key resolution + confirm ALERT-DEDUP-1 property held; then squash-merge to main.
- **Deploy:** push to main → Render auto-deploys.
- **Post-deploy:** run AC6 live canary end-to-end; emit `POST_DEPLOY_AC_VERDICT v1` to the bus. Then verify via the new drop-log (`box5_dropped_signals`, PR #452) that the dedup gate is no longer the binding drop.

## OUT OF SCOPE
- Bluewin 2035-date received_date clamp (Director DROPPED).
- Gate-2 keyword-breadth widening (HELD pending codex-arch #4942 + real drop-data).
- Any change to the received_date watermark logic.
- `email_messages` recipient (To/CC) completeness gap (separate; note only).

## ROLLBACK
Additive-behavior branch; rollback = revert the squash commit. If a PK/conflict migration is included, document the down-path.
