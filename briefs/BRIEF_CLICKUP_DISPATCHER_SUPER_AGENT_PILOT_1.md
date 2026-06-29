# BRIEF: CLICKUP_DISPATCHER_SUPER_AGENT_PILOT_1 - ClickUp status clerk pilot

## Context

Dispatcher ClickUp-to-bus relay is live and proven. The next step is a
pull-only pilot where ClickUp Super Agent acts as a cheap status clerk and
packet-cleanup layer, while Baker Dispatcher remains the deterministic validator,
bus relay, reply mapper, and audit engine.

This brief implements the Baker side only. It does not create the ClickUp Super
Agent, mutate ClickUp automations, deploy code, or give ClickUp any Baker/bus
credentials.

## Estimated time: ~4-6h
## Complexity: Medium
## Task class: medium-feature / coordination rail
## Harness-V2: applies
## Prerequisites:

- Manual ClickUp setup remains Director/lead-owned:
  - Dispatcher Queue list exists.
  - Statuses exist: `Packet Draft`, `Ready for Agent`, `Agent Working`,
    `Agent Drafted`, `Ready for Baker Relay`, `Relayed`, `Waiting Reply`,
    `Replied`, `Blocked`, `Needs Director`, `Closed`.
  - Standing task exists: `[dispatcher][standing_status] Dispatcher status ledger`.
  - Super Agent profile exists: `Dispatcher Status Clerk`.
- Baker Render env already has the Dispatcher MVP env:
  - `DISPATCHER_ENABLED`
  - `DISPATCHER_CLICKUP_LIST_ID`
  - `DISPATCHER_BUS_URL`
  - `BRISEN_LAB_TERMINAL_KEY_DISPATCHER`
  - `DISPATCHER_MAX_BUS_POSTS_PER_TICK`
- No secrets in code, tests, brief, logs, or ClickUp comments.

## Context Contract

- **Owner:** lead dispatches; Code Brisen implements.
- **Architecture:** ClickUp Super Agent writes comments only. Baker validates.
- **Control plane:** Baker Dispatcher remains source of relay truth.
- **Audit plane:** existing `dispatcher_bus_threads.payload` and
  `baker_actions` carry pilot evidence; no new table for Phase 1.
- **Authority:** no bus dispatch from ClickUp; no Director messages from code;
  no webhook endpoint in Phase 1.

## Current State

- `orchestrator/dispatcher.py` parses `DISPATCHER PACKET` and formats bus
  messages.
- `orchestrator/dispatcher_relay.py` reads ClickUp list tasks, dispatches due /
  blocked / ready / stale tasks, dedupes through `dispatcher_bus_threads`, and
  copies mapped bus replies back to ClickUp comments.
- `triggers/dispatcher_tick.py` calls `orchestrator.dispatcher_relay.run_tick()`.
- `triggers/embedded_scheduler.py` registers `dispatcher_tick` only when
  `DISPATCHER_ENABLED` is truthy.
- `clickup_client.py` already has `get_tasks()`, `get_task_comments()`,
  `get_task_detail()`, `update_task()`, and `post_comment()`.
- Live schema verified:
  - `dispatcher_bus_threads`: `id`, `clickup_task_id`, `owner_slug`,
    `recipient_slug`, `bus_message_id`, `bus_thread_id`, `status`,
    `reason_code`, `condition_hash`, `last_sent_at`, `last_reply_at`,
    `payload`, `dedup_key`, `created_at`, `updated_at`.
  - `clickup_tasks`: `id`, `name`, `description`, `status`, `priority`,
    `due_date`, `date_created`, `date_updated`, `list_id`, `list_name`,
    `space_id`, `workspace_id`, `assignees`, `tags`, `comment_count`,
    `last_synced`, `baker_tier`, `baker_writable`.

## Engineering Craft Gates

- Diagnose: applies - validate Super Agent comments before relay; reject malformed
  output deterministically.
- Prototype: N/A - the design uncertainty is operational, not code-path; pilot is
  bounded by task count and status contract.
- TDD/verification: applies - parser and relay tests first; no live ClickUp write
  until post-deploy smoke.

## Done Rubric / Done-State Class

Done-state class: **local implementation ready, deploy gated**.

Done means:

1. Baker can parse latest `DISPATCHER_AGENT_RESULT v1` task comment.
2. Baker only relays tasks in `Ready for Baker Relay` after both Agent result and
   original `DISPATCHER PACKET` validate.
3. Invalid Agent output moves the task to `Blocked` with a Baker rejection comment.
4. Successful relay writes `BAKER_RELAY_RECEIPT v1` and sets ClickUp status to
   `Waiting Reply`.
5. Bus reply writeback writes `BAKER_REPLY_RECEIPT v1` and sets ClickUp status to
   `Replied`.
6. Pilot counters are queryable from `dispatcher_bus_threads.payload`.
7. Focused tests and compile checks pass.

---

## Fix/Feature 1: Parse Super Agent result comments

### Problem

The Super Agent writes natural-language-looking ClickUp comments. Baker must
accept only the strict `DISPATCHER_AGENT_RESULT v1` block and must not trust the
Agent's summary over the original packet.

### Current State

- `orchestrator.dispatcher.parse_schedule_packet(text)` validates the original
  packet body.
- `orchestrator.dispatcher_relay.dispatch_task(task, conn, now=None)` currently
  ignores task comments and uses task status/due date as the dispatch trigger.
- `ClickUpClient.get_task_comments(task_id)` returns a list of task comments.

### Implementation

Add these helpers to `orchestrator/dispatcher_relay.py` near the existing task
text/status helpers.

```python
AGENT_RESULT_HEADER = "DISPATCHER_AGENT_RESULT v1"
VALID_AGENT_PACKET_STATUSES = {"valid", "invalid", "needs_clarification"}
VALID_AGENT_NEXT_STATES = {"Ready for Baker Relay", "Blocked", "Needs Director"}
VALID_AGENT_PRIORITIES = {"low", "normal", "high", "urgent"}


def _comment_text(comment: dict[str, Any]) -> str:
    if not isinstance(comment, dict):
        return ""
    text = comment.get("comment_text") or comment.get("text_content") or ""
    items = comment.get("comment")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and item.get("text"):
                text += str(item["text"])
    return str(text or "").strip()


def _parse_agent_result_block(text: str) -> dict[str, str]:
    lines = [line.rstrip() for line in (text or "").splitlines()]
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == AGENT_RESULT_HEADER)
    except StopIteration:
        return {}
    fields: dict[str, str] = {}
    for line in lines[start + 1:]:
        if not line.strip():
            continue
        if line.startswith("BAKER_") or line.startswith("DISPATCHER_"):
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip().lower()] = value.strip()
    return fields


def latest_agent_result(comments: list[dict[str, Any]]) -> dict[str, str]:
    for comment in reversed(comments or []):
        parsed = _parse_agent_result_block(_comment_text(comment))
        if parsed:
            return parsed
    return {}


def validate_agent_result(
    result: dict[str, str],
    *,
    task_id: str,
    packet: DispatcherPacket,
) -> list[str]:
    errors: list[str] = []
    if not result:
        return ["missing DISPATCHER_AGENT_RESULT v1"]
    if result.get("task_id") != task_id:
        errors.append("task_id mismatch")
    if result.get("packet_status") != "valid":
        errors.append("invalid packet_status")
    if result.get("priority") not in VALID_AGENT_PRIORITIES:
        errors.append("invalid priority")
    if result.get("next_state") != "Ready for Baker Relay":
        errors.append("invalid next_state")
    if resolve_owner_slug(result.get("owner_slug", "")) != packet.owner_slug:
        errors.append("owner_slug mismatch")
    if result.get("due_at") != packet.due_at.isoformat():
        errors.append("due_at mismatch")
    return errors
```

### Key Constraints

- Do not parse free prose as authority.
- Do not relay if the Agent result task id differs from the ClickUp task id.
- Do not relay unless `packet_status: valid` and
  `next_state: Ready for Baker Relay`.
- Do not relay unless the Agent result owner/due date match the parsed original
  packet.
- Do not let `director_visible_summary` overwrite the packet's `required_action`.
- Do not require `director_visible_summary` for relay; it is presentation-only.

### Verification

Add `tests/test_dispatcher_agent_result.py` with:

- valid block parses from latest comment;
- older valid block loses to newer block;
- missing block rejects;
- task id mismatch rejects;
- invalid `packet_status`, `priority`, and `next_state` reject;
- owner/due date mismatch rejects.

---

## Fix/Feature 2: Gate outbound relay on `Ready for Baker Relay`

### Problem

The existing Dispatcher MVP relays due/blocked/ready/stale tasks. The pilot adds
a stricter ClickUp/Super-Agent path: tasks with status `Ready for Baker Relay`
must first pass Agent-result validation and original-packet validation.

### Current State

- `dispatch_reason_for_task()` maps `blocked`, `ready`, due date, and stale update
  to relay reasons.
- The pilot status string `Ready for Baker Relay` is not currently special.

### Implementation

Add a status constant:

```python
READY_FOR_BAKER_RELAY_STATUS = "ready for baker relay"
```

Change `dispatch_reason_for_task()`:

```python
    if status == READY_FOR_BAKER_RELAY_STATUS:
        return "agent_result"
```

Extend `VALID_REASONS`:

```python
VALID_REASONS = frozenset({
    "due", "blocked", "unblocked", "stale", "needs_clarification", "agent_result"
})
```

Because the live migration currently restricts `dispatcher_bus_threads.reason_code`,
add a new migration:

```sql
-- == migrate:up ==

ALTER TABLE dispatcher_bus_threads
    DROP CONSTRAINT IF EXISTS dispatcher_bus_threads_reason_check;

ALTER TABLE dispatcher_bus_threads
    ADD CONSTRAINT dispatcher_bus_threads_reason_check
    CHECK (reason_code IN (
        'due',
        'blocked',
        'unblocked',
        'stale',
        'needs_clarification',
        'agent_result'
    ));
```

Use a new migration file. Do not edit
`migrations/20260628c_dispatcher_clickup_bus_relay.sql`.

After `packet = parsed.packet` inside `dispatch_task()`, add:

```python
    agent_result: dict[str, str] = {}
    agent_errors: list[str] = []
    if reason == "agent_result":
        comments = []
        try:
            from clickup_client import ClickUpClient
            comments = ClickUpClient._get_global_instance().get_task_comments(task_id)
        except Exception as e:
            logger.warning("dispatcher failed reading agent result comments for %s: %s", task_id, e)
            agent_errors = ["clickup comments unavailable"]
        if not agent_errors:
            agent_result = latest_agent_result(comments)
            agent_errors = validate_agent_result(agent_result, task_id=task_id, packet=packet)
        if agent_errors:
            return reject_agent_result(task, agent_errors, conn)
```

Add `reject_agent_result()`:

```python
def reject_agent_result(task: dict[str, Any], errors: list[str], conn: Any) -> dict[str, Any]:
    task_id = _clickup_task_id(task) or "unknown"
    body = (
        "BAKER_RELAY_REJECTED v1\n"
        f"task_id: {task_id}\n"
        f"reason_code: invalid_agent_result\n"
        f"errors: {', '.join(errors)}\n"
        "status: Blocked"
    )
    try:
        from clickup_client import ClickUpClient
        client = ClickUpClient._get_global_instance()
        client.post_comment(task_id, body)
        client.update_task(task_id, status="Blocked")
    except Exception as e:
        logger.warning("dispatcher failed writing Agent rejection for %s: %s", task_id, e)
        return {"ok": False, "reason": "agent_result_reject_write_failed", "error": str(e)}
    return {"skipped": True, "reason": "invalid_agent_result", "errors": errors}
```

When Agent result is valid, include it in the dispatch payload:

```python
        "agent_result": agent_result,
        "agent_result_status": "accepted" if reason == "agent_result" else None,
```

### Key Constraints

- Original `DISPATCHER PACKET` validation remains mandatory.
- Agent output can block/reject but cannot bypass owner/date/action validation.
- `Needs Director` from the Agent does not message Director; Baker writes a
  ClickUp state/comment only.
- If the Agent result says `Blocked` or `Needs Director`, Baker rejects relay and
  writes a `BAKER_RELAY_REJECTED v1` comment; it does not bus-dispatch.
- All DB except paths must rollback before new queries.

### Verification

Extend `tests/test_dispatcher_relay.py`:

- `Ready for Baker Relay` without Agent result writes rejection and does not post bus.
- Valid Agent result plus valid packet posts one bus message.
- Invalid Agent result plus valid packet does not reserve/send bus.
- Valid Agent result plus invalid packet uses existing needs-clarification path.
- New reason code migration contains `agent_result`.

---

## Fix/Feature 3: Write Baker receipts and ClickUp statuses

### Problem

The Director should be able to read ClickUp as the operating surface. Today the
MVP copies replies back, but it does not write the explicit receipt blocks or
status transitions defined for the pilot.

### Current State

- `complete_dispatch()` records `waiting_reply` in `dispatcher_bus_threads`.
- `process_replies()` posts a free-form ClickUp comment with the bus reply body
  and then calls `record_reply()`.
- `ClickUpClient.update_task(task_id, status="...")` exists.

### Implementation

Add receipt formatters:

```python
def format_relay_receipt(
    *,
    task_id: str,
    bus_message_id: Optional[int],
    bus_thread_id: Optional[str],
    recipient_slug: str,
    reason_code: str,
) -> str:
    return (
        "BAKER_RELAY_RECEIPT v1\n"
        f"task_id: {task_id}\n"
        f"bus_message_id: {bus_message_id or ''}\n"
        f"bus_thread_id: {bus_thread_id or ''}\n"
        f"recipient_slug: {recipient_slug}\n"
        f"reason_code: {reason_code}\n"
        f"relayed_at: {datetime.now(timezone.utc).isoformat()}\n"
        "status: Waiting Reply"
    )


def format_reply_receipt(*, task_id: str, event_id: Any, reply_from: str, body: str) -> str:
    summary = " ".join(str(body or "").split())[:500]
    return (
        "BAKER_REPLY_RECEIPT v1\n"
        f"task_id: {task_id}\n"
        f"reply_event_id: {event_id}\n"
        f"reply_from: {reply_from}\n"
        f"reply_at: {datetime.now(timezone.utc).isoformat()}\n"
        f"summary: {summary}\n"
        "status: Replied"
    )
```

After `complete_dispatch()` succeeds in `dispatch_task()`, write:

```python
    receipt = format_relay_receipt(
        task_id=task_id,
        bus_message_id=message_id,
        bus_thread_id=result.get("thread_id"),
        recipient_slug=packet.owner_slug,
        reason_code=reason,
    )
    try:
        from clickup_client import ClickUpClient
        client = ClickUpClient._get_global_instance()
        client.post_comment(task_id, receipt)
        client.update_task(task_id, status="Waiting Reply")
    except Exception as e:
        logger.warning("dispatcher receipt/status write failed for %s: %s", task_id, e)
        mark_waiting_room_error(conn, dispatch_id=int(reserved["id"]), error=f"receipt_write_failed: {e}")
```

In `process_replies()`, replace the free-form comment body with
`format_reply_receipt(...)` followed by the clipped raw body:

```python
            reply_from = event.get("from_terminal") or msg.get("from_terminal") or "unknown"
            comment = (
                format_reply_receipt(
                    task_id=task_id,
                    event_id=msg_id,
                    reply_from=reply_from,
                    body=body,
                )
                + "\n\nRaw reply:\n"
                + body[:3000]
            )
            posted = client.post_comment(task_id, comment)
            if not posted:
                logger.warning("dispatcher failed to write ClickUp reply comment for %s", task_id)
                continue
            status_updated = client.update_task(task_id, status="Replied")
            if not status_updated:
                logger.warning("dispatcher failed to set ClickUp task Replied for %s", task_id)
                continue
```

Do not ACK the bus message until both the reply comment and status update succeed.

### Key Constraints

- Receipt write failure must not duplicate bus sends.
- Bus ACK must remain after ClickUp write success.
- Do not include full secret-bearing payloads in receipts.
- Stay within `ClickUpClient` write cap; if cap is hit, skip ACK and retry later.

### Verification

Extend tests:

- relay success posts `BAKER_RELAY_RECEIPT v1` and updates status to `Waiting Reply`;
- mapped reply posts `BAKER_REPLY_RECEIPT v1`, sets status `Replied`, then ACKs;
- status update failure does not ACK;
- receipt write failure records an error in `dispatcher_bus_threads.payload`.

---

## Fix/Feature 4: Pilot counters from existing payloads

### Problem

The pilot needs acceptance/rejection metrics, but a new table is unnecessary for
the first 20-task run.

### Current State

- `dispatcher_bus_threads.payload` is JSONB and already stores per-dispatch
  metadata.
- `baker_actions` records ClickUp write attempts from `ClickUpClient`.

### Implementation

For Agent-result dispatches, ensure `payload` includes:

```python
{
    "pilot": "clickup_dispatcher_super_agent",
    "agent_result_status": "accepted",
    "agent_result": agent_result,
}
```

For Agent-result rejection comments, do not reserve a bus thread. Instead rely on
the ClickUp `BAKER_RELAY_REJECTED v1` comment and `baker_actions` write audit.

Add a helper for a local/live metric probe:

```python
def pilot_metric_sql() -> str:
    return """
    SELECT
        COUNT(*) FILTER (WHERE payload->>'agent_result_status' = 'accepted') AS accepted,
        COUNT(*) FILTER (WHERE reason_code = 'agent_result') AS relayed,
        COUNT(*) FILTER (WHERE status = 'replied') AS replied
    FROM dispatcher_bus_threads
    WHERE payload->>'pilot' = 'clickup_dispatcher_super_agent'
      AND created_at >= NOW() - INTERVAL '30 days'
    LIMIT 1
    """
```

This helper is optional; the SQL below is the acceptance probe.

### Key Constraints

- No schema migration for counters.
- No weekly AI Super Credit automation in this brief; Director/lead logs credits
  manually during pilot.
- Do not infer rejected count from bus rows, because invalid Agent results are
  deliberately not bus-dispatched.

### Verification

Add a unit test asserting accepted Agent dispatch payload contains:

- `pilot`
- `agent_result_status`
- `agent_result.task_id`

---

## Files Modified

- `orchestrator/dispatcher_relay.py` - Agent-result parser, validation gate,
  receipt writers, status updates, pilot payload metadata.
- `migrations/20260629a_dispatcher_agent_result_reason.sql` - extend
  `dispatcher_bus_threads.reason_code` check to include `agent_result`.
- `tests/test_dispatcher_agent_result.py` - parser/validator coverage.
- `tests/test_dispatcher_relay.py` - relay/status/receipt/rejection coverage.

## Do NOT Touch

- `migrations/20260628c_dispatcher_clickup_bus_relay.sql` - already-applied
  migration; amend with a new migration only.
- `clickup_client.py` write policy - existing Director-authorized policy is out
  of scope; use existing kill switch/write cap.
- `orchestrator/dispatcher.py` packet contract - original packet remains the
  authority.
- `triggers/embedded_scheduler.py` cadence/env gates - Phase 1 stays pull-only.
- Any ClickUp automation/webhook setup - manual operational step, not code.
- Any Baker/bus/ClickUp secret values.

## Quality Checkpoints

1. New migration is additive and does not edit applied migrations.
2. Every SQL query has `LIMIT` where applicable.
3. Every DB exception path rolls back before reuse.
4. `Ready for Baker Relay` is the only Agent-result relay state.
5. Invalid Agent output cannot send a bus message.
6. Original packet validation still rejects invalid owners/dates/actions.
7. Receipt/status writes happen after bus send, before bus ACK.
8. Webhook push remains out of scope.

## Verification Commands

```bash
python3 -m py_compile orchestrator/dispatcher.py orchestrator/dispatcher_relay.py triggers/dispatcher_tick.py triggers/embedded_scheduler.py
python3 -m pytest tests/test_dispatcher_packet.py tests/test_dispatcher_relay.py tests/test_dispatcher_agent_result.py tests/test_dispatcher_scheduler.py -q
```

## Verification SQL

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'dispatcher_bus_threads'
ORDER BY ordinal_position
LIMIT 50;
```

```sql
SELECT
    COUNT(*) FILTER (WHERE payload->>'agent_result_status' = 'accepted') AS accepted,
    COUNT(*) FILTER (WHERE reason_code = 'agent_result') AS relayed,
    COUNT(*) FILTER (WHERE status = 'replied') AS replied
FROM dispatcher_bus_threads
WHERE payload->>'pilot' = 'clickup_dispatcher_super_agent'
  AND created_at >= NOW() - INTERVAL '30 days'
LIMIT 1;
```

```sql
SELECT action_type, target_task_id, success, created_at
FROM baker_actions
WHERE trigger_source = 'clickup_client'
  AND action_type IN ('post_comment', 'update_task')
ORDER BY created_at DESC
LIMIT 20;
```

## Manual Post-Deploy Pilot Smoke

Do this only after merge, deploy, and explicit activation.

1. Create one ClickUp task in Dispatcher Queue with a valid `DISPATCHER PACKET`.
2. Put task in `Ready for Agent`.
3. Run/trigger `Dispatcher Status Clerk` so it writes one
   `DISPATCHER_AGENT_RESULT v1` comment.
4. Set task to `Ready for Baker Relay`.
5. Wait for `dispatcher_tick`.
6. Confirm task gets `BAKER_RELAY_RECEIPT v1` and status `Waiting Reply`.
7. Confirm bus owner receives a dispatcher message.
8. Reply to dispatcher on bus.
9. Confirm task gets `BAKER_REPLY_RECEIPT v1` and status `Replied`.
10. Run Verification SQL and record accepted/relayed/replied counts.

## Rollback

1. Set `DISPATCHER_ENABLED=false` on Render and redeploy.
2. Disable ClickUp Automation that triggers `Dispatcher Status Clerk`.
3. Leave `dispatcher_bus_threads` rows intact for audit.
4. Do not delete ClickUp task comments; they are pilot evidence.

## References

- Operating design:
  `/Users/dimitry/baker-vault/_ops/briefs/plans/CLICKUP_DISPATCHER_SUPER_AGENT_PILOT_20260629.md`
- Prior MVP brief:
  `briefs/BRIEF_DISPATCHER_CLICKUP_BUS_RELAY_MVP_1.md`
- Existing implementation:
  `orchestrator/dispatcher.py`
  `orchestrator/dispatcher_relay.py`
  `triggers/dispatcher_tick.py`
  `triggers/embedded_scheduler.py`
