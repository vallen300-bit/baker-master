---
brief_id: CAPABILITY_RUNNER_COST_FIX_1
authored_by: lead (AH1)
authored_at: 2026-05-25
director_ratified: 2026-05-25 (chat — "go" on Option A after b4 diagnostic)
target: b4
reply_target: lead (AH1)
expected_time: ~30-45 min
complexity: Low (5-10 LOC + 1 unit test)
type: backend defect fix (Option A from b4 diagnostic)
target_repo: baker-master (single repo)
matter_slug: baker-internal
peer_brief: CAPABILITY_RUNNER_COST_RUNAWAY_DIAGNOSTIC_1 (b4 diagnostic at briefs/_reports/B4_capability_runner_cost_runaway_diagnostic_1_20260525.md — root-caused the WhatsApp self-chat feedback loop)
heartbeat_cadence: 15 min (small brief; flag if not shipped within 1h)
gate_chain: Gate-1+2 lead | Gate-3 SKIP (≤15 LOC) | Gate-4 SKIP | Gate-5 lead merge | post-merge lead observes Render logs 30 min for fromMe self-chat drop events + cost_monitor daily total
---

# BRIEF: CAPABILITY_RUNNER_COST_FIX_1 — kill the WhatsApp self-chat feedback loop chewing €100/day since 2026-05-21

## Context

### Surface contract: N/A — pure backend defect fix. No UI changes, no new endpoints, no schema edits. Single-guard insertion in webhook handler + 1 unit test.

### Defect (root-caused by b4)

Baker has been talking to itself in Director's WhatsApp self-chat since 2026-05-21:

1. Baker emits a reply via WAHA to chat `41799605092@c.us` (Director's self-chat).
2. WAHA fires a `fromMe=true` webhook back to Baker with the reply text in `payload.body`.
3. `attribute_sender(raw_sender, raw_sender_name, from_me=True)` at `triggers/waha_message_utils.py:42-43` unconditionally re-attributes the message as `(DIRECTOR_WHATSAPP_CUS, "Director", True)`.
4. `triggers/waha_webhook.py:1117-1118` computes `director_to_baker = (sender == DIRECTOR_WHATSAPP and _baker_self and bool(combined_body))` = `True` on Baker's own outbound.
5. `_handle_director_question` (line 1207) fires → `CapabilityRouter.route()` picks `finance` + `legal` in delegate mode → `CapabilityRunner.run_single/run_multi` without `matter_slug` → ~3-8 Opus rows per invocation, zero cache hits, no `matter_slug`/`task_id`.
6. Baker's resulting reply triggers another `fromMe=true` webhook → infinite loop.
7. Loop throttled only by per-iter latency (~10-30s); `COST_HARD_STOP_EUR=100.0` stops it ~5h in.

Smoking-gun evidence (b4's report §2g): 579 `is_director=True` overnight messages all in `41799605092@c.us`, bodies are unmistakably Baker-style replies. Cost breakdown: `capability_runner` = 82% of 24h LLM spend; `finance`+`legal` = 97% of that; ALL rows have `matter_slug=NULL`.

Linked to Gmail polling blackout (V1+V2 visibility patches): document classification fails because breaker trips daily — fix this loop and Gmail document writes resume automatically.

### Trade-off Director must accept BEFORE merge (lead surfaces at Gate-5)

Option A (this brief) drops ALL `fromMe=true` events on Baker's self-chat — including any messages Director types himself into the self-chat from his phone. Baker cannot currently distinguish Baker-outbound vs Director-phone-outbound on the self-chat (both arrive as `fromMe=true`, both are stored with `is_director=True`). If Director uses the self-chat as a Baker-Q&A interface, that interface stops working post-merge.

If that feature is wanted, ship Option B (per-msg-id origin-tag on outbound sends, ~1-2h) instead. Lead will confirm with Director at Gate-5 (pre-merge) before squashing the PR. b4 should still implement Option A as designed — the merge gate handles the strategic choice; the implementation is the same shape either way (small guard, unit test, regression suite).

Anchor: `tasks/lessons.md` will get a new entry after merge documenting the loop pattern.

## Estimated time: ~30-45 min
## Complexity: Low (5-10 LOC + 1 unit test)
## Prerequisites: branch `b4/capability-runner-cost-fix-1` off `main` HEAD

---

## Fix 1: Insert self-chat loop guard upstream of question-handler

### Problem
`triggers/waha_webhook.py:1117-1212` fires the full Director-question path (`_handle_director_message` → `extract_deadlines` → OBLIGATIONS-DETECT → `_handle_director_question`) on Baker's own outbound replies, creating an infinite loop that burns ~€100/day.

### Current State (verified line-by-line)

`triggers/waha_webhook.py`:

```python
# Line 837:
from_me = payload.get("fromMe", False)

# Line 845-846:
from triggers.waha_message_utils import attribute_sender, is_baker_self_chat
sender, sender_name, is_director_msg = attribute_sender(raw_sender, raw_sender_name, from_me)

# Lines 980-996 (PRESERVED — happens upstream of guard, audit trail intact):
store.store_whatsapp_message(msg_id=..., sender=..., chat_id=..., ...)

# Lines 1117-1119 (TARGET INSERTION POINT):
_baker_self = is_baker_self_chat(chat_id)
director_to_baker = (sender == DIRECTOR_WHATSAPP and _baker_self and bool(combined_body))
director_to_counterparty = (sender == DIRECTOR_WHATSAPP and not _baker_self and bool(combined_body))

# Lines 1136-1212 — YouTube ingest, action handler, deadline extraction,
# obligations detect, question handler — ALL fire on director_to_baker=True
```

### Implementation

In `triggers/waha_webhook.py`, between the current line 1117 (`_baker_self = is_baker_self_chat(chat_id)`) and line 1118, insert:

```python
    _baker_self = is_baker_self_chat(chat_id)

    # COST_RUNAWAY_FIX_1: Drop fromMe=true on Baker self-chat before any
    # question-handler / RAG / deadline / obligations path fires. Baker's
    # own outbound replies to Director's self-chat arrive as fromMe=true
    # webhook events, get re-attributed to Director by attribute_sender
    # (triggers/waha_message_utils.py:42-43), and would otherwise infinite-
    # loop through _handle_director_question — burning ~€100/day on
    # capability_runner Opus calls (zero matter_slug, zero cache hits).
    # Audit trail INSERT to whatsapp_messages already happened upstream
    # at line ~983, so we preserve that even though we drop the processing.
    # Trade-off: Director's own phone-typed self-chat messages are also
    # dropped — that interface stops working. Lead-gated at Gate-5.
    # Anchor: briefs/_reports/B4_capability_runner_cost_runaway_diagnostic_1_20260525.md
    if from_me and _baker_self:
        logger.info(
            f"COST_RUNAWAY_FIX_1: self-chat loop guard dropping fromMe=true "
            f"msg_id={msg_id} (audit-trail INSERT preserved upstream)"
        )
        return {"status": "self_chat_loop_guard_drop", "msg_id": msg_id}

    director_to_baker = (sender == DIRECTOR_WHATSAPP and _baker_self and bool(combined_body))
    director_to_counterparty = (sender == DIRECTOR_WHATSAPP and not _baker_self and bool(combined_body))
```

### Key Constraints

- **DO NOT touch `triggers/waha_message_utils.py`** — the `attribute_sender` re-attribution logic is correct for the Director-to-counterparty flow that BRIEF_WAHA_OUTBOUND_CAPTURE_1 introduced. The bug is the absence of a guard at the call site, not the attribution itself.
- **DO NOT touch the `store.store_whatsapp_message()` call at line 983** — the audit-trail INSERT must continue running so we have history of Baker's own outbound for debugging/forensics.
- **DO NOT touch `director_to_counterparty` path** — that's Director sending to other people (counterparties). Different path, different bug. Director-outbound to counterparties is `fromMe=true && NOT _baker_self` — the guard above only intercepts `fromMe && _baker_self`, leaving counterparty outbound paths intact.
- **PM-signal at line 1125 is correctly skipped by the guard** — `detect_relevant_pms_outbound` only matters for Director's outbound to PM contacts. Baker's self-chat replies aren't "outbound to a PM contact" — fine to skip.
- **YouTube auto-ingest at line 1136 is correctly skipped** — Baker doesn't send YouTube links to itself.

### Verification

After deploy, lead runs (with `X-Baker-Key` from 1Password):

```bash
# 1. Confirm guard fires on self-chat fromMe events — check Render logs
curl -sS -H "Authorization: Bearer ${RENDER_API_KEY}" \
  "https://api.render.com/v1/logs?ownerId=<owner>&resource=<svc>&text=COST_RUNAWAY_FIX_1&limit=100"

# Expected: each self-chat-loop-guard-drop log row corresponds to a
# fromMe=true event that would previously have fired the question
# handler.

# 2. Confirm cost_monitor stops tripping daily
curl -sS -H "X-Baker-Key: $KEY" \
  "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -d '{"tool":"baker_raw_query","args":{"query":"SELECT DATE(created_at) d, SUM(cost_eur) FROM api_cost_log WHERE source = '\''capability_runner'\'' AND created_at > NOW() - INTERVAL '\''3 days'\'' GROUP BY 1 ORDER BY 1"}}'

# Expected: daily capability_runner spend drops from €80-100/day to
# <€5/day within 24h.
```

---

## Fix 2: Add unit test for the guard

### Problem
The guard must not regress on future changes. Add a unit test in the existing `tests/test_waha_outbound_capture.py` (which already has `fromMe=True` webhook test fixtures).

### Implementation

Append a new test to `tests/test_waha_outbound_capture.py`:

```python
def test_fromme_self_chat_short_circuits_before_question_handler(self, monkeypatch):
    """COST_RUNAWAY_FIX_1: fromMe=True on Baker self-chat must drop before
    _handle_director_question fires. Loop guard prevents the WhatsApp
    self-chat feedback loop that was burning ~€100/day pre-fix.
    """
    from triggers import waha_webhook as ww

    # Spies — verify these are NOT called
    question_handler_called = {"n": 0}
    deadline_extractor_called = {"n": 0}

    def _spy_question_handler(*args, **kwargs):
        question_handler_called["n"] += 1
        return True

    def _spy_extract_deadlines(*args, **kwargs):
        deadline_extractor_called["n"] += 1

    monkeypatch.setattr(ww, "_handle_director_question", _spy_question_handler)
    monkeypatch.setattr(
        "orchestrator.deadline_manager.extract_deadlines",
        _spy_extract_deadlines,
    )

    # Stub storage so we don't need a real DB connection
    monkeypatch.setattr(
        "memory.store_back.SentinelStoreBack._get_global_instance",
        lambda: _StubStore(),
    )

    payload = self._build_payload(
        from_me=True,
        from_addr="41799605092@c.us",
        to_addr="41799605092@c.us",
        body="This is Baker's own outbound reply text.",
    )

    result = ww.handle_waha_webhook({"event": "message.any", "payload": payload})

    assert result.get("status") == "self_chat_loop_guard_drop", (
        f"Guard must short-circuit. Got: {result}"
    )
    assert question_handler_called["n"] == 0, (
        "_handle_director_question MUST NOT fire on fromMe=true self-chat"
    )
    assert deadline_extractor_called["n"] == 0, (
        "extract_deadlines MUST NOT fire on fromMe=true self-chat"
    )
```

Helper `_build_payload` should already exist in the test class (used by the existing fromMe=True tests at line 132+). `_StubStore` minimum:

```python
class _StubStore:
    def store_whatsapp_message(self, **kw): pass
    def match_contact_by_name(self, **kw): return None
    def record_interaction(self, **kw): pass
    def _get_conn(self): return None
```

### Verification

```bash
pytest tests/test_waha_outbound_capture.py -v -k "self_chat_loop_guard or fromme"
```

Expected: all existing fromMe tests still pass + new test passes.

---

## Files Modified
- `triggers/waha_webhook.py` — insert 14 LOC guard (logger.info + return) between current lines 1117 and 1118.
- `tests/test_waha_outbound_capture.py` — append 1 new test (~40 LOC including stub).

## Do NOT Touch
- `triggers/waha_message_utils.py` — attribution logic is correct; the fix is at the call site.
- `triggers/waha_webhook.py` lines 977-996 (whatsapp_messages INSERT) — audit trail must keep running.
- `triggers/waha_webhook.py` lines 1218-1219 (director_to_counterparty) — different path, not affected.
- `orchestrator/cost_monitor.py` — breaker is working correctly; root cause is upstream.
- `orchestrator/capability_runner.py` — runner behaviour is fine; root cause is upstream.

## Quality Checkpoints

1. Run `python3 -c "import py_compile; py_compile.compile('triggers/waha_webhook.py', doraise=True)"` — must pass.
2. Run `pytest tests/test_waha_outbound_capture.py -v` — all existing tests pass + new guard test passes.
3. Run full regression `pytest tests/ -v -x` (or at least the waha + capability subset).
4. Confirm guard placement — should be AFTER `_baker_self = is_baker_self_chat(chat_id)` and BEFORE `director_to_baker = ...`. The guard depends on `_baker_self` being computed.
5. Confirm return shape — `{"status": "self_chat_loop_guard_drop", "msg_id": msg_id}` is a new status value; callers of the webhook handler only check for presence of `status` field, so this is safe.
6. Post-deploy log spot-check: tail Render logs for `COST_RUNAWAY_FIX_1` substring — should see drop events on every Baker outbound to self-chat.
7. Post-deploy 24h cost check: `capability_runner` daily total should drop from €80-100 to <€5.

## Verification SQL

```sql
-- Confirm capability_runner daily spend drops post-deploy
SELECT
  DATE(created_at) AS day,
  SUM(cost_eur) AS daily_eur,
  COUNT(*) AS calls
FROM api_cost_log
WHERE source = 'capability_runner'
  AND created_at > NOW() - INTERVAL '4 days'
GROUP BY 1
ORDER BY 1
LIMIT 10;
```

Expected: deploy-day total drops sharply; subsequent days <€5/day.

```sql
-- Confirm Gmail document writes resume post-deploy (downstream consequence)
SELECT
  DATE(created_at) AS day,
  COUNT(*) AS doc_count
FROM documents
WHERE source_type = 'email'
  AND created_at > NOW() - INTERVAL '7 days'
GROUP BY 1
ORDER BY 1
LIMIT 10;
```

Expected: document_count climbs back toward pre-2026-05-21 baseline once breaker stops tripping.

## Gate-1 + Gate-2 reviewer instructions (for lead)

Beyond standard architecture + security pass, verify these 4 invariants:

1. **Guard placement** — between `_baker_self =` and `director_to_baker =` (the order matters; guard depends on `_baker_self`).
2. **Storage INSERT preserved** — `store.store_whatsapp_message(...)` at line ~983 still runs unconditionally on every webhook (not gated by the new guard).
3. **counterparty path unaffected** — `director_to_counterparty` continues to work for Director's outbound to other contacts. Quick test: simulate `from_me=True`, `chat_id="41796720083@c.us"` (some counterparty), confirm `director_to_counterparty=True` and the storage + short-circuit at line 1218 still fires.
4. **No `attribute_sender` change** — the fix MUST be at the call site, not in the attribution helper. Modifying `attribute_sender` would break BRIEF_WAHA_OUTBOUND_CAPTURE_1's Director-to-counterparty re-attribution.

## Bus protocol

Ship report to lead via topic `ship/capability-runner-cost-fix-1`. Include literal `pytest` output (no "pass by inspection"). Include PR number + commit hash. Heartbeat every 15 min if not shipped within 30 min.
