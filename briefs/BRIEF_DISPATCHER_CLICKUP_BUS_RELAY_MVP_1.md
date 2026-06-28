# BRIEF: DISPATCHER_CLICKUP_BUS_RELAY_MVP_1 - ClickUp timetable to bus dispatcher

## Context

Director ratified the airport model refinement on 2026-06-28: ClickUp is the
airport timetable, the ClickUp scheduling persona is **Dispatcher**, and desks
remain the reasoning owners. The Baden-Baden desk Lilienmatt / Aukera test proved
the desk can reason correctly, but its dates, blocking events, and condition
precedents stayed inside prose instead of becoming scheduled, owned, follow-up
work.

Dispatcher must be able to:
- hold dates and condition precedents in ClickUp;
- route due / stale / blocked / unblocked tasks to the actual agent owner on the bus;
- receive replies back from agents;
- write the reply/result back to ClickUp;
- update the waiting-room record so airport state is not hidden in chat.

This brief builds the narrow MVP. It does not create a terminal agent and does not
message the Director.

## Estimated time: ~6-8h
## Complexity: Medium
## Task class: medium-feature / coordination rail
## Harness-V2: applies
## Prerequisites:

- Director/lead Tier-B activation after code merge:
  - create a `dispatcher` terminal key;
  - add `dispatcher` to the brisen-lab terminal-key map;
  - set Baker Render env `BRISEN_LAB_TERMINAL_KEY_DISPATCHER`;
  - keep `DISPATCHER_ENABLED=false` until post-deploy smoke passes.
- Existing ClickUp API key must remain scoped through `ClickUpClient`.
- Do not commit or expose secret values.

## Context Contract

- **Owner:** codex-arch as local builder; Dispatcher runtime remains service-side.
- **Task class:** medium-feature because it adds a DB table, scheduler hook, bus identity, and ClickUp/bus bridge.
- **Interfaces:** ClickUp task/list API, brisen-lab bus `/msg/*`, `dispatcher_bus_threads`, `waiting_room_items`.
- **Activation state:** default-off by `DISPATCHER_ENABLED=false`; no runtime effect until explicit post-deploy activation.
- **Authority:** no Director messages, no external sends, no terminal automation, no ClickUp policy change.

## Done Rubric / Done-State Class

Done-state class: **local implementation ready, deploy gated**.

Done means:
1. Dispatcher is a system bus sender/recipient, not a terminal agent.
2. Schedule packets validate owner, due date, required action, and condition precedents.
3. Outbound bus sends are deduped and retryable on failed sends.
4. Inbound replies write back only when mapped through `dispatcher_bus_threads`.
5. Chartered packets mirror to waiting room; scheduled packets remain dispatcher-only.
6. Scheduler is default-off and test-covered.
7. Focused tests and gates pass.

## Gate Plan

1. Cowork AH1 second-pair review on the brief/process shape.
2. Deputy-codex architecture gate on airport fit and relay responsibility split.
3. Codex correctness/security gate on bus/ClickUp/DB safety.
4. Final narrow delta gates after any second-pair changes.
5. Post-deploy activation smoke only after separate Director/lead Tier-B activation.

---

## Fix/Feature 0: ClickUp write-policy preflight

### Problem

Dispatcher will write ClickUp comments and may later update tasks. The existing
ClickUp client carries a Director-authorized 2026-03-25 write-all policy with a
kill switch and max-write counter. This MVP must not bury a ClickUp write-policy
change inside Dispatcher.

### Current State

- `clickup_client.py` has `_BAKER_SPACE_ID = "901510186446"`, but the live client
  behavior is read-all / write-all with `BAKER_CLICKUP_READONLY` and per-cycle
  write caps.
- Cowork AH1 second-pair review #4564: reversing write-all back to BAKER-only is
  a separate policy decision, not part of this default-off Dispatcher PR.

### Implementation

Do not change `ClickUpClient._check_write_allowed()` in this MVP. Dispatcher must
constrain itself by configuration:

- require `DISPATCHER_CLICKUP_LIST_ID`;
- use `BAKER_CLICKUP_READONLY`;
- keep `DISPATCHER_MAX_BUS_POSTS_PER_TICK`;
- log ClickUp writes through existing `ClickUpClient` action logging.

### Verification

`tests/test_clickup_client.py` remains a guard for the existing kill switch and
write-count behavior; do not add a global BAKER-space policy change here.

---

## Fix/Feature 1: Add Dispatcher as a system bus participant

### Problem

Dispatcher lives in ClickUp/service-land, not in a terminal. It must still be a
first-class bus sender and recipient so agents can reply to it.

### Current State

- Generated identity source: `/Users/dimitry/baker-vault/_ops/registries/agent_registry.yml`.
- Generated Baker artifacts:
  - `orchestrator/agent_identity_data.py`
  - `scripts/agent_identity_generated.sh`
  - `tests/fixtures/session-start-bus-drain.sh`
- `scripts/generate_agent_identity_artifacts.py` already supports non-agent
  system sender `daemon`.

### Engineering Craft Gates

- Diagnose: applies - verify slug resolution and generated artifact drift.
- Prototype: N/A - same pattern as `daemon`.
- TDD/verification: applies - add explicit registry tests before generation.

### Implementation

Do **not** add Dispatcher as a terminal/fleet agent. Add it as a system bus
participant:

1. In `scripts/generate_agent_identity_artifacts.py`, change:

```python
SYSTEM_RECIPIENT_SLUGS = ("director", "daemon", "dispatcher")
SYSTEM_SENDER_SLUGS = ("daemon", "dispatcher")
```

2. Add tests in `tests/test_agent_identity_registry.py`:

```python
def test_dispatcher_resolves_as_system_bus_participant_not_terminal_agent():
    assert "dispatcher" in SYSTEM_SENDER_SLUGS
    assert "dispatcher" in VALID_BUS_SLUGS
    assert ROLE_TO_SLUG.get("dispatcher") == "dispatcher"
    assert ROLE_TO_SLUG.get("DISPATCHER") == "dispatcher"
    assert "dispatcher" not in BUS_AGENT_SLUGS
    assert all(not item.startswith("dispatcher:") for item in SNAPSHOT_TERMINALS)
```

3. Regenerate:

```bash
python3 scripts/generate_agent_identity_artifacts.py --write
```

4. Verify:

```bash
python3 scripts/generate_agent_identity_artifacts.py --check
python3 -m pytest tests/test_agent_identity_registry.py -q
```

### Key Constraints

- `dispatcher` must be a sender and recipient.
- `dispatcher` must not be in `BUS_AGENT_SLUGS`.
- `dispatcher` must not have a snapshot terminal path.
- `director` remains recipient-only, never sender.

---

## Fix/Feature 2: Dispatcher schedule packet contract

### Problem

Desk reasoning currently creates actionable dates inside prose. Dispatcher needs a
small, deterministic packet so it can create/update ClickUp tasks and route them
back to the right owner.

### Current State

- Waiting-room MVP exists in `orchestrator/waiting_room.py`.
- `waiting_room_items` columns are:
  `flight_type`, `item_type`, `item_ref`, `owner_slug`, `reason_code`, `status`,
  `ready_after`, `last_nudge_at`, `nudge_count`, `payload`, `dedup_key`.
- `clickup_tasks` columns include:
  `id`, `name`, `description`, `status`, `priority`, `due_date`, `list_id`,
  `list_name`, `space_id`, `workspace_id`, `assignees`, `tags`, `baker_writable`.

### Engineering Craft Gates

- Diagnose: applies - parse missing/ambiguous packet fields without silent action.
- Prototype: N/A - plain text contract is enough for MVP.
- TDD/verification: applies - packet parser unit tests first.

### Implementation

Create `orchestrator/dispatcher.py` with a pure parser:

```text
DISPATCHER PACKET
title: <short task title>
owner_slug: <valid bus slug>
matter_slug: <optional matter slug>
flight_type: scheduled|chartered
due_at: <ISO timestamp or YYYY-MM-DD>
priority: low|normal|high|urgent
condition_precedent:
- <condition that must be true before action>
blocked_by:
- <current blocker, if any>
required_action: <what owner must do>
source: <desk slug / researcher / lead>
```

Parser behavior:
- `owner_slug` must resolve through `ROLE_TO_SLUG`.
- `owner_slug` must not resolve to `director`, `daemon`, or `dispatcher`.
- Missing `owner_slug`, missing due date, or malformed conditions returns a
  `needs_clarification` result, not a task write.
- `flight_type` defaults to `chartered`.
- `priority` defaults to `normal`.

Add tests in `tests/test_dispatcher_packet.py`:
- valid Baden-Baden packet parses;
- valid Researcher packet parses;
- missing owner returns `needs_clarification`;
- invalid recipient returns `needs_clarification`;
- Director recipient is rejected;
- condition precedents preserve order.

### Key Constraints

- Dispatcher does not reason about the finance/legal substance.
- Dispatcher asks the source agent for clarification when packet fields are
  missing.
- No Opus call in this MVP.

---

## Fix/Feature 3: Dispatcher ClickUp-to-bus relay

### Problem

When a ClickUp task becomes due, unblocked, stale, or unclear, the owner should
receive a normal bus message. Replies should return to Dispatcher and be written
back into ClickUp.

### Current State

- `ClickUpClient` can `get_task_detail`, `get_task_comments`, `post_comment`,
  and `update_task`.
- `bus_post.sh` shows the bus POST shape:
  - `POST https://brisen-lab.onrender.com/msg/<recipient>`
  - header `X-Terminal-Key: <dispatcher key>`
  - JSON body with `kind`, `body`, `to`, `tier_required`, optional `topic`.
- `check-codexarch-inbox.sh` shows inbox read shape:
  - `GET /msg/<slug>?limit=N`
  - `GET /event/<id>/full`
  - `POST /msg/<id>/ack`

### Engineering Craft Gates

- Diagnose: applies - relay failures must be visible and retryable.
- Prototype: N/A - deterministic HTTP bridge.
- TDD/verification: applies - mock ClickUp + bus HTTP, then one live read-only
  smoke after deploy.

### Implementation

Add `orchestrator/dispatcher_relay.py`.

Core pieces:

1. Env gates:

```python
DISPATCHER_ENABLED=false
DISPATCHER_CLICKUP_LIST_ID=901521426367
DISPATCHER_BUS_URL=https://brisen-lab.onrender.com
BRISEN_LAB_TERMINAL_KEY_DISPATCHER=<secret, Render env only>
DISPATCHER_MAX_BUS_POSTS_PER_TICK=10
DISPATCHER_STALE_HOURS=24
```

2. Candidate selection:

- Read configured ClickUp list only for MVP.
- Select tasks tagged `dispatcher` or whose description starts with
  `DISPATCHER PACKET`.
- Candidate states:
  - due now or overdue;
  - status contains `blocked`;
  - status contains `ready`;
  - stale since last dispatcher post by `DISPATCHER_STALE_HOURS`.

3. Bus send:

```python
def post_bus_message(recipient_slug: str, body: str, *, topic: str) -> dict:
    key = os.environ.get("BRISEN_LAB_TERMINAL_KEY_DISPATCHER", "").strip()
    if not key:
        return {"ok": False, "error": "dispatcher_key_missing"}
    payload = {
        "kind": "dispatch",
        "body": body,
        "to": [recipient_slug],
        "tier_required": "B",
        "topic": topic,
    }
    ...
```

Use `urllib.request` or `httpx` with explicit timeout <= 15s. Never include
secrets in logs.

4. Bus message body:

```text
TO: <owner_slug>
FROM: dispatcher
RE: <task title>

ClickUp task: <task id or URL>
Due: <due date>
Status: <due|blocked|unblocked|stale|needs_clarification>
Condition precedent:
- <condition 1>
- <condition 2>
Blocked by:
- <blocker 1>
Required action: <required_action>

Reply to dispatcher with DONE / BLOCKED / NEEDS-CLARIFICATION / RESCHEDULE.
```

5. Reply read:

- Poll `/msg/dispatcher?limit=50`.
- For each unacked reply:
  - read full event;
  - locate mapped ClickUp task by `parent_id`, `thread_id`, or outbound
    `bus_message_id` in `dispatcher_bus_threads`;
  - write a ClickUp comment:
    `Dispatcher bus reply from <sender>: <body excerpt>`;
  - ack only after ClickUp comment succeeds.
- If no task mapping exists, do not write to ClickUp and do not ACK. Log the
  unmapped reply for operator follow-up.

6. Waiting-room link:

- For each sent **chartered** task, upsert `waiting_room_items` using:
  - `flight_type='chartered'`;
  - `item_type='clickup_task'`;
  - `item_ref=<clickup task id>`;
  - `owner_slug=<owner_slug>`;
  - `reason_code='dispatcher_due'|'dispatcher_blocked'|'dispatcher_stale'`;
  - `ready_after=<due_at>`;
  - `payload` containing `bus_message_id`, `clickup_task_id`, `condition_status`.

Scheduled packets stay in `dispatcher_bus_threads` only until a scheduled
waiting-room/missed-departure rail exists. Do not silently mirror scheduled
rows into the current chartered-only waiting-room nudge path.

### Key Constraints

- No Director bus messages.
- No external sends.
- No terminal automation.
- No Opus or LLM call.
- Max 10 ClickUp writes per tick.
- If bus send fails, write a ClickUp comment only if safe and within write cap.

---

## Fix/Feature 4: Durable dispatcher mapping table

### Problem

Replies need a stable ClickUp task to bus-thread mapping. Do not rely only on
searching text.

### Current State

No `dispatcher_*` table exists in production.

### Engineering Craft Gates

- Diagnose: applies - mapping prevents orphaned replies.
- Prototype: N/A - small additive table.
- TDD/verification: applies - migration-shape test + insert/update unit test.

### Implementation

Add migration `migrations/20260628c_dispatcher_clickup_bus_relay.sql`:

```sql
-- == migrate:up ==

CREATE TABLE IF NOT EXISTS dispatcher_bus_threads (
    id BIGSERIAL PRIMARY KEY,
    clickup_task_id TEXT NOT NULL,
    owner_slug TEXT NOT NULL,
    recipient_slug TEXT NOT NULL,
    bus_message_id BIGINT,
    bus_thread_id TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    reason_code TEXT NOT NULL,
    condition_hash TEXT,
    last_sent_at TIMESTAMPTZ,
    last_reply_at TIMESTAMPTZ,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    dedup_key TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT dispatcher_bus_threads_status_check
        CHECK (status IN ('open', 'waiting_reply', 'replied', 'closed', 'failed')),
    CONSTRAINT dispatcher_bus_threads_reason_check
        CHECK (reason_code IN (
            'due',
            'blocked',
            'unblocked',
            'stale',
            'needs_clarification'
        ))
);

CREATE INDEX IF NOT EXISTS idx_dispatcher_bus_threads_task
    ON dispatcher_bus_threads (clickup_task_id);

CREATE INDEX IF NOT EXISTS idx_dispatcher_bus_threads_status_sent
    ON dispatcher_bus_threads (status, last_sent_at DESC);
```

Add helper functions in `orchestrator/dispatcher_relay.py`:
- `make_dedup_key(clickup_task_id, recipient_slug, reason_code, condition_hash)`;
- `record_dispatch(...)`;
- `record_reply(...)`;
- every DB except block calls `conn.rollback()` before further use.

### Verification SQL

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name='dispatcher_bus_threads'
ORDER BY ordinal_position
LIMIT 50;
```

---

## Fix/Feature 5: Scheduler wiring, default-off

### Problem

Dispatcher must run automatically, but the MVP must not create a noisy new
production loop before activation.

### Current State

- `triggers/embedded_scheduler.py` already registers jobs.
- ClickUp poll is daily at 04:30 UTC by Director rule.
- Dispatcher is operational scheduling, not the broad ClickUp ingest poll.

### Engineering Craft Gates

- Diagnose: applies - scheduler registration must be testable without starting
  scheduler.
- Prototype: N/A.
- TDD/verification: applies - AST or fake scheduler test proves default-off.

### Implementation

In `triggers/embedded_scheduler.py`, add default-off registration:

```python
if os.environ.get("DISPATCHER_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}:
    from triggers.dispatcher_tick import run_dispatcher_tick
    scheduler.add_job(
        run_dispatcher_tick,
        IntervalTrigger(minutes=int(os.environ.get("DISPATCHER_TICK_MINUTES", "15"))),
        id="dispatcher_tick",
        name="Dispatcher ClickUp-to-bus tick",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
```

Create `triggers/dispatcher_tick.py` as a thin wrapper:

```python
def run_dispatcher_tick() -> None:
    from orchestrator.dispatcher_relay import run_tick
    run_tick()
```

### Verification

- `DISPATCHER_ENABLED` unset: scheduler does not add `dispatcher_tick`.
- `DISPATCHER_ENABLED=true`: fake scheduler receives one `dispatcher_tick`.
- py_compile:
  ```bash
  python3 -m py_compile orchestrator/dispatcher.py orchestrator/dispatcher_relay.py triggers/dispatcher_tick.py triggers/embedded_scheduler.py
  ```

---

## Files Modified

- `scripts/generate_agent_identity_artifacts.py` - add Dispatcher as system sender/recipient.
- `orchestrator/agent_identity_data.py` - regenerated.
- `scripts/agent_identity_generated.sh` - regenerated.
- `tests/fixtures/session-start-bus-drain.sh` - regenerated.
- `orchestrator/dispatcher.py` - schedule packet parser.
- `orchestrator/dispatcher_relay.py` - ClickUp-to-bus and bus-to-ClickUp relay.
- `triggers/dispatcher_tick.py` - scheduler wrapper.
- `triggers/embedded_scheduler.py` - default-off job registration.
- `migrations/20260628c_dispatcher_clickup_bus_relay.sql` - durable mapping.
- `tests/test_agent_identity_registry.py` - Dispatcher system participant tests.
- `tests/test_dispatcher_packet.py` - packet parser tests.
- `tests/test_dispatcher_relay.py` - relay and mapping tests.
- `tests/test_dispatcher_scheduler.py` - default-off scheduler tests.

## Do NOT Touch

- `migrations/20260628b_router_second_look_and_waiting_room.sql` - already pushed; never edit applied migration.
- `orchestrator/waiting_room.py` schema assumptions - use existing `item_ref` / `payload` unless a separate migration is proven necessary.
- `outputs/dashboard.py` - no UI in this MVP.
- B-code mailbox files - this brief is not a dispatch until lead assigns it.
- Any external email / WhatsApp send path.
- Render env vars or 1Password secrets inside this code PR.

## Quality Checkpoints

1. Dispatcher is resolvable as a bus sender and recipient.
2. Dispatcher is not a terminal/snapshot agent.
3. Director cannot be a Dispatcher recipient.
4. Invalid owner routes to `lead` or `needs_clarification`, never silent drop.
5. Dispatcher does not change ClickUp's existing write-all policy.
6. `BAKER_CLICKUP_READONLY=true` blocks all Dispatcher ClickUp writes.
7. Scheduled packets do not mirror into `waiting_room_items` until a scheduled rail exists.
8. Bus send failure does not ack a Dispatcher inbox reply.
9. ClickUp comment failure does not ack a Dispatcher inbox reply.
10. Duplicate due ticks do not post duplicate bus messages for unchanged condition hash.
11. Chartered waiting-room item is updated for every outbound bus post; any waiting-room failure is recorded in `dispatcher_bus_threads.payload`.
12. `DISPATCHER_ENABLED=false` means no scheduler job.
13. All DB queries include LIMIT where unbounded.
14. Every DB except path rolls back before reuse.
15. Gates required before commit: cowork-ah1 second-pair, deputy-codex architecture, codex correctness/security.

## Verification Commands

```bash
python3 scripts/generate_agent_identity_artifacts.py --check
python3 -m py_compile orchestrator/dispatcher.py orchestrator/dispatcher_relay.py triggers/dispatcher_tick.py triggers/embedded_scheduler.py
python3 -m pytest tests/test_agent_identity_registry.py tests/test_dispatcher_packet.py tests/test_dispatcher_relay.py tests/test_dispatcher_scheduler.py -q
python3 -m pytest tests/test_migration_runner.py::test_migration_file_has_up_marker -q
```

Known caveat: `test_migration_file_has_up_marker` currently fails on 13 legacy
migrations. The new `20260628c_dispatcher_clickup_bus_relay.sql` must not appear
in the missing-marker list.

## Post-Deploy Activation Smoke

Lead-only / Tier-B activation after deploy:

1. Add Dispatcher key to brisen-lab and Baker env.
2. Flip `DISPATCHER_ENABLED=true`.
3. Create one test ClickUp task in BAKER space with:
   - tag `dispatcher`;
   - owner_slug `codex-arch` or `lead`;
   - due date now;
   - one condition precedent.
4. Confirm bus receives one message from `dispatcher`.
5. Reply to `dispatcher`.
6. Confirm the reply lands as a ClickUp comment.
7. Confirm `dispatcher_bus_threads` row moved to `replied`.
8. Confirm matching `waiting_room_items` row exists.

## Rollback

1. Set `DISPATCHER_ENABLED=false`.
2. Leave tables in place.
3. Remove/ignore Dispatcher ClickUp tag on test tasks.
4. Do not delete bus history.
