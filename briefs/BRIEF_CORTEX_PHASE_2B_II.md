# BRIEF: CORTEX-PHASE-2B-II — Rewire Pipelines Through Cortex Event Bus

## Context
Cortex Phase 2B deployed the semantic dedup gate (`cortex_obligations` Qdrant collection + `check_dedup()` + shadow mode). But 12 write paths still create deadlines/decisions by calling `insert_deadline()` or direct SQL INSERT — bypassing the event bus entirely. This means no dedup check, no `source_agent` attribution, no audit trail, and no `decisions→insights` pipeline for pipeline-created obligations.

This brief rewires the 4 key functions that cover all 12 paths.

## Estimated time: ~3h
## Complexity: Medium
## Prerequisites: Cortex Phase 2A + 2B deployed (confirmed: `tool_router_enabled=true`, `auto_merge_enabled=false`)

---

## Feature 1: Convenience Wrappers in `models/cortex.py`

### Problem
Every call site that wants to go through Cortex needs to: call `insert_deadline()`, extract the ID, call `publish_event()`, handle errors. This is 15+ lines of boilerplate per call site — error-prone and verbose.

### Current State
`publish_event()` exists (line 169) but doesn't INSERT — it only logs to `cortex_events` + runs dedup + audit. The actual INSERT happens in `models/deadlines.py::insert_deadline()` (line 265) or direct SQL.

### Implementation
Add two convenience functions to `models/cortex.py` at the END of the file (after `_auto_queue_insights()`):

```python
# ─── Convenience Wrappers (Phase 2B-ii) ───

def cortex_create_deadline(
    description: str,
    due_date,  # datetime or str
    source_type: str,
    source_agent: str,
    confidence: str = "medium",
    priority: str = "normal",
    source_id: str = None,
    source_snippet: str = None,
) -> Optional[int]:
    """
    Create a deadline through the Cortex event bus.
    1. INSERT via legacy insert_deadline()
    2. Set source_agent on the row
    3. Publish event (dedup + audit + vector upsert)

    Returns deadline ID or None. publish_event failure is non-fatal.
    """
    from models.deadlines import insert_deadline
    from datetime import datetime, timezone

    # Normalize due_date to datetime
    if isinstance(due_date, str):
        try:
            due_date = datetime.fromisoformat(due_date)
            if due_date.tzinfo is None:
                due_date = due_date.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            logger.warning("cortex_create_deadline: invalid due_date %s", due_date)
            return None

    # 1. Legacy INSERT
    dl_id = insert_deadline(
        description=description,
        due_date=due_date,
        source_type=source_type,
        confidence=confidence,
        priority=priority,
        source_id=source_id,
        source_snippet=source_snippet,
    )
    if not dl_id:
        return None

    # 2. Set source_agent
    try:
        conn = _get_conn()
        if conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE deadlines SET source_agent = %s WHERE id = %s",
                (source_agent, dl_id),
            )
            conn.commit()
            cur.close()
            _put_conn(conn)
    except Exception as e:
        logger.warning("cortex_create_deadline: source_agent update failed: %s", e)
        try:
            conn.rollback()
        except Exception:
            pass
        _put_conn(conn)

    # 3. Publish event (non-fatal)
    due_str = due_date.strftime("%Y-%m-%d") if hasattr(due_date, 'strftime') else str(due_date)
    try:
        publish_event(
            event_type="accepted",
            category="deadline",
            source_agent=source_agent,
            source_type=source_type,
            payload={
                "description": description,
                "due_date": due_str,
                "priority": priority,
                "confidence": confidence,
            },
            source_ref=source_id,
            canonical_id=dl_id,
        )
    except Exception as e:
        logger.warning("cortex_create_deadline: publish_event failed (non-fatal): %s", e)

    return dl_id


def cortex_store_decision(
    decision: str,
    source_agent: str,
    reasoning: str = "",
    confidence: str = "high",
    trigger_type: str = "pipeline",
    project: str = "",
) -> Optional[int]:
    """
    Store a decision through the Cortex event bus.
    1. INSERT via legacy log_decision()
    2. Set source_agent on the row
    3. Publish event (dedup + audit + insights pipeline)

    Returns decision ID or None. publish_event failure is non-fatal.
    """
    # 1. Legacy INSERT
    store = _get_store()
    dec_id = store.log_decision(
        decision=decision,
        reasoning=reasoning,
        confidence=confidence,
        trigger_type=trigger_type,
    )
    if not dec_id:
        return None

    # 2. Set source_agent
    try:
        conn = _get_conn()
        if conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE decisions SET source_agent = %s WHERE id = %s",
                (source_agent, dec_id),
            )
            conn.commit()
            cur.close()
            _put_conn(conn)
    except Exception as e:
        logger.warning("cortex_store_decision: source_agent update failed: %s", e)
        try:
            conn.rollback()
        except Exception:
            pass
        _put_conn(conn)

    # 3. Publish event (non-fatal)
    try:
        publish_event(
            event_type="accepted",
            category="decision",
            source_agent=source_agent,
            source_type=trigger_type,
            payload={
                "decision": decision,
                "reasoning": reasoning,
                "confidence": confidence,
                "project": project,
            },
            canonical_id=dec_id,
        )
    except Exception as e:
        logger.warning("cortex_store_decision: publish_event failed (non-fatal): %s", e)

    return dec_id
```

### Key Constraints
- `publish_event()` failure MUST NOT prevent the deadline/decision from being created
- Keep calling `insert_deadline()` and `log_decision()` — don't duplicate INSERT logic
- `_put_conn(conn)` MUST be called in both success and error paths (connection pool)
- `conn.rollback()` in every except block

### Verification
After deploy, create a test deadline via MCP:
```sql
SELECT id, description, source_agent, source_type FROM deadlines ORDER BY id DESC LIMIT 3;
SELECT id, event_type, category, source_agent FROM cortex_events ORDER BY id DESC LIMIT 5;
```

---

## Feature 2: Rewire MCP Tools

### Problem
`baker_add_deadline` and `baker_store_decision` in `baker_mcp_server.py` use raw SQL INSERT — no dedup, no attribution, no audit.

### Current State
`baker_mcp/baker_mcp_server.py`:
- Lines 753-769: `baker_store_decision` — direct INSERT into `decisions`
- Lines 771-787: `baker_add_deadline` — direct INSERT into `deadlines`

### Implementation
Replace the raw SQL blocks with calls to the new wrappers. Feature-flagged: check `tool_router_enabled` first, fall back to legacy if OFF.

**Replace lines 753-769** (`baker_store_decision`):

```python
    elif name == "baker_store_decision":
        decision = args["decision"]
        reasoning = args.get("reasoning", "")
        confidence = args.get("confidence", "high")
        project = args.get("project", "")

        # CORTEX-PHASE-2B-II: Route through event bus when flag ON
        _use_cortex = False
        try:
            from memory.store_back import SentinelStoreBack
            _store = SentinelStoreBack._get_global_instance()
            _use_cortex = _store.get_cortex_config('tool_router_enabled', False)
        except Exception:
            pass

        if _use_cortex:
            from models.cortex import cortex_store_decision
            dec_id = cortex_store_decision(
                decision=decision,
                source_agent="cowork",
                reasoning=reasoning,
                confidence=confidence,
                trigger_type="cowork_session",
                project=project,
            )
            if dec_id:
                return f"Decision stored via Cortex (id={dec_id}, confidence={confidence}):\n  {decision}"
            return "Error: failed to store decision"
        else:
            # Legacy path (feature flag OFF)
            metadata = json.dumps({"source": "cowork_mcp", "project": project}) if project else json.dumps({"source": "cowork_mcp"})
            row = _write(
                """
                INSERT INTO decisions (decision, reasoning, confidence, trigger_type, metadata, created_at)
                VALUES (%s, %s, %s, 'cowork_session', %s::jsonb, NOW())
                RETURNING id, decision, confidence
                """,
                (decision, reasoning, confidence, metadata),
            )
            if row:
                return f"Decision stored (id={row['id']}, confidence={row['confidence']}):\n  {row['decision']}"
            return "Error: failed to store decision"
```

**Replace lines 771-787** (`baker_add_deadline`):

```python
    elif name == "baker_add_deadline":
        description = args["description"]
        due_date = args["due_date"]
        priority = args.get("priority", "normal")
        source_snippet = args.get("source_snippet", "")
        confidence = args.get("confidence", "high")

        # CORTEX-PHASE-2B-II: Route through event bus when flag ON
        _use_cortex = False
        try:
            from memory.store_back import SentinelStoreBack
            _store = SentinelStoreBack._get_global_instance()
            _use_cortex = _store.get_cortex_config('tool_router_enabled', False)
        except Exception:
            pass

        if _use_cortex:
            from models.cortex import cortex_create_deadline
            dl_id = cortex_create_deadline(
                description=description,
                due_date=due_date,
                source_type="cowork_session",
                source_agent="cowork",
                confidence=confidence,
                priority=priority,
                source_id="mcp",
                source_snippet=source_snippet,
            )
            if dl_id:
                return f"Deadline created via Cortex (id={dl_id}, priority={priority}):\n  {description}\n  Due: {due_date}"
            return "Error: failed to create deadline"
        else:
            # Legacy path (feature flag OFF)
            row = _write(
                """
                INSERT INTO deadlines (description, due_date, source_type, source_id, source_snippet, confidence, priority, status)
                VALUES (%s, %s, 'cowork_session', 'mcp', %s, %s, %s, 'active')
                RETURNING id, description, due_date, priority
                """,
                (description, due_date, source_snippet, confidence, priority),
            )
            if row:
                return f"Deadline created (id={row['id']}, priority={row['priority']}):\n  {row['description']}\n  Due: {row['due_date']}"
            return "Error: failed to create deadline"
```

### Key Constraints
- Keep legacy path as `else` — if feature flag is OFF or check fails, old behavior is untouched
- `source_agent="cowork"` for MCP tools (Director/Cowork sessions)
- Don't change the MCP tool schema or return format (other tools parse these strings)

### Verification
```bash
# Test via MCP — should show "via Cortex" in response
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_add_deadline","arguments":{"description":"TEST cortex routing via MCP","due_date":"2026-05-01","priority":"low"}}}'
```
Then verify:
```sql
SELECT id, description, source_agent, source_type FROM deadlines WHERE description LIKE '%TEST cortex%' ORDER BY id DESC LIMIT 1;
SELECT id, event_type, category, source_agent FROM cortex_events WHERE category='deadline' ORDER BY id DESC LIMIT 3;
```
Clean up: `DELETE FROM deadlines WHERE description LIKE '%TEST cortex%';`

---

## Feature 3: Rewire `extract_deadlines()` in `deadline_manager.py`

### Problem
`extract_deadlines()` is the single chokepoint — called by email trigger, Fireflies trigger, and Plaud trigger. It calls `insert_deadline()` directly (line 149). Rewiring this one function covers 6 of 12 paths.

### Current State
`orchestrator/deadline_manager.py`, lines 52-166:
- Calls `call_flash()` to extract deadlines from text
- Dedup via `find_duplicate_deadline()` (local date-based check)
- Calls `insert_deadline()` for each new deadline (line 149)
- No `source_agent` parameter exists

### Implementation
**Step 1:** Add `source_agent` parameter to function signature (line 52):

Change:
```python
def extract_deadlines(
    content: str,
    source_type: str,
    source_id: str = "",
    sender_name: str = "",
    sender_email: str = "",
    sender_whatsapp: str = "",
) -> int:
```

To:
```python
def extract_deadlines(
    content: str,
    source_type: str,
    source_id: str = "",
    sender_name: str = "",
    sender_email: str = "",
    sender_whatsapp: str = "",
    source_agent: str = "",
) -> int:
```

**Step 2:** Replace `insert_deadline()` call at line 149 with Cortex wrapper:

Change the block at lines 149-163:
```python
        dl_id = insert_deadline(
            description=description,
            due_date=due_date,
            source_type=source_type,
            confidence=confidence,
            priority=priority,
            source_id=source_id,
            source_snippet=snippet,
        )
        if dl_id:
            inserted += 1
            conf_label = "SOFT" if confidence == "soft" else "HARD"
            logger.info(
                f"Deadline extracted: #{dl_id} [{conf_label}/{priority}] "
                f'"{description[:60]}" due {due_date_str} (from {source_type})'
            )
```

To:
```python
        # CORTEX-PHASE-2B-II: Route through event bus when flag ON
        _use_cortex = False
        try:
            from memory.store_back import SentinelStoreBack
            _cstore = SentinelStoreBack._get_global_instance()
            _use_cortex = _cstore.get_cortex_config('tool_router_enabled', False)
        except Exception:
            pass

        if _use_cortex:
            from models.cortex import cortex_create_deadline
            dl_id = cortex_create_deadline(
                description=description,
                due_date=due_date,
                source_type=source_type,
                source_agent=source_agent or f"{source_type}_pipeline",
                confidence=confidence,
                priority=priority,
                source_id=source_id,
                source_snippet=snippet,
            )
        else:
            dl_id = insert_deadline(
                description=description,
                due_date=due_date,
                source_type=source_type,
                confidence=confidence,
                priority=priority,
                source_id=source_id,
                source_snippet=snippet,
            )

        if dl_id:
            inserted += 1
            conf_label = "SOFT" if confidence == "soft" else "HARD"
            logger.info(
                f"Deadline extracted: #{dl_id} [{conf_label}/{priority}] "
                f'"{description[:60]}" due {due_date_str} (from {source_type})'
            )
```

**Step 3:** Keep existing `find_duplicate_deadline()` check (line 129). It runs BEFORE the insert and handles date-based dedup. The Cortex semantic dedup is complementary (catches same obligation with different wording). Both checks running is correct — belt and suspenders.

### Key Constraints
- Do NOT remove `find_duplicate_deadline()` — it's a different dedup layer (date-based vs semantic)
- `source_agent` defaults to `""` — backward compatible with all existing callers
- If `source_agent` is empty, construct it from `source_type` (e.g., `"email_pipeline"`)
- Feature flag check uses `try/except` — if store not available, legacy path runs

### Verification
After deploy, send a test email that contains a deadline. Then:
```sql
SELECT id, description, source_agent, source_type FROM deadlines WHERE source_type='email' ORDER BY id DESC LIMIT 3;
SELECT id, event_type, source_agent FROM cortex_events WHERE source_agent LIKE '%email%' ORDER BY id DESC LIMIT 3;
```

---

## Feature 4: Rewire `_extract_director_commitments_as_deadlines()` in Fireflies Trigger

### Problem
Meeting commitment extraction (both Fireflies and Plaud) calls `insert_deadline()` directly — no Cortex routing.

### Current State
`triggers/fireflies_trigger.py`, lines 155-234:
- `_extract_director_commitments_as_deadlines()` — extracts Director's commitments from meeting transcripts
- Calls `insert_deadline()` at line 227
- Called by Fireflies (directly) and Plaud (via import at `plaud_trigger.py` line 411)

### Implementation
Replace the `insert_deadline()` call at lines 227-234:

Change:
```python
        did = insert_deadline(
            description=f"[Commitment to {to_whom}] {desc}" if to_whom else f"[Meeting commitment] {desc}",
            due_date=_dd,
            source_type="meeting",
            source_id=f"commitment-meeting:{source_id}",
            confidence="medium",
            priority=priority,
            source_snippet=f"Meeting: {meeting_title}\nParticipants: {participants}",
```

To:
```python
        # CORTEX-PHASE-2B-II: Route through event bus when flag ON
        _use_cortex = False
        try:
            from memory.store_back import SentinelStoreBack
            _cstore = SentinelStoreBack._get_global_instance()
            _use_cortex = _cstore.get_cortex_config('tool_router_enabled', False)
        except Exception:
            pass

        _dl_desc = f"[Commitment to {to_whom}] {desc}" if to_whom else f"[Meeting commitment] {desc}"
        if _use_cortex:
            from models.cortex import cortex_create_deadline
            did = cortex_create_deadline(
                description=_dl_desc,
                due_date=_dd,
                source_type="meeting",
                source_agent="meeting_pipeline",
                confidence="medium",
                priority=priority,
                source_id=f"commitment-meeting:{source_id}",
                source_snippet=f"Meeting: {meeting_title}\nParticipants: {participants}",
            )
        else:
            did = insert_deadline(
                description=_dl_desc,
                due_date=_dd,
                source_type="meeting",
                source_id=f"commitment-meeting:{source_id}",
                confidence="medium",
                priority=priority,
                source_snippet=f"Meeting: {meeting_title}\nParticipants: {participants}",
```

**Note:** The `from models.deadlines import insert_deadline` at line 212 must stay — it's the `else` fallback.

### Key Constraints
- Plaud trigger imports this function at `plaud_trigger.py` line 411 — gets rewired automatically, no changes needed in plaud_trigger.py
- Keep `insert_deadline` import for fallback path
- `source_agent="meeting_pipeline"` for both Fireflies and Plaud (they share the function)

### Verification
After next meeting transcript is processed:
```sql
SELECT id, description, source_agent FROM deadlines WHERE source_type='meeting' ORDER BY id DESC LIMIT 3;
SELECT id, event_type, source_agent FROM cortex_events WHERE source_agent='meeting_pipeline' ORDER BY id DESC LIMIT 3;
```

---

## Feature 5: Pass `source_agent` From Callers (Email + Fireflies + Plaud)

### Problem
The callers of `extract_deadlines()` don't pass `source_agent` yet. After Feature 3 adds the parameter, update the callers.

### Implementation

**Email trigger** (`triggers/email_trigger.py` line 927):
Change:
```python
            extract_deadlines(
                content=thread["text"],
                source_type="email",
                source_id=message_id,
                sender_name=metadata.get("primary_sender", ""),
                sender_email=metadata.get("primary_sender_email", ""),
            )
```
To:
```python
            extract_deadlines(
                content=thread["text"],
                source_type="email",
                source_id=message_id,
                sender_name=metadata.get("primary_sender", ""),
                sender_email=metadata.get("primary_sender_email", ""),
                source_agent="email_pipeline",
            )
```

**Fireflies trigger** — find ALL calls to `extract_deadlines` in `triggers/fireflies_trigger.py` and add `source_agent="meeting_pipeline"`:
```python
            extract_deadlines(
                content=transcript_text,
                source_type="meeting",
                source_id=source_id,
                ...,
                source_agent="meeting_pipeline",
            )
```

**Plaud trigger** — find ALL calls to `extract_deadlines` in `triggers/plaud_trigger.py` and add `source_agent="meeting_pipeline"`:
```python
            extract_deadlines(
                content=transcript_text,
                source_type="plaud",
                source_id=source_id,
                ...,
                source_agent="meeting_pipeline",
            )
```

### Key Constraints
- `source_agent` is a new kwarg with default `""` — existing callers that DON'T pass it won't break
- This is a cosmetic improvement (better attribution). If missed, `source_agent` falls back to `f"{source_type}_pipeline"`

---

## Files Modified
- `models/cortex.py` — add `cortex_create_deadline()` + `cortex_store_decision()` convenience wrappers
- `baker_mcp/baker_mcp_server.py` — rewire `baker_store_decision` + `baker_add_deadline` with feature flag
- `orchestrator/deadline_manager.py` — add `source_agent` param, rewire `insert_deadline()` call
- `triggers/fireflies_trigger.py` — rewire `_extract_director_commitments_as_deadlines()` + pass `source_agent` to `extract_deadlines()`
- `triggers/email_trigger.py` — pass `source_agent="email_pipeline"` to `extract_deadlines()`
- `triggers/plaud_trigger.py` — pass `source_agent="meeting_pipeline"` to `extract_deadlines()`

## Do NOT Touch
- `orchestrator/agent.py` — `_cortex_route()` already works correctly (Phase 2A)
- `models/deadlines.py` — `insert_deadline()` stays as-is (legacy INSERT layer)
- `memory/store_back.py` — `log_decision()` stays as-is (called by `cortex_store_decision()`)
- `triggers/email_trigger.py` lines 885-911 — OBLIGATIONS-DETECT-1 direct `insert_deadline()` call. Rewire this in Phase 3 (needs own dedup logic review). Low volume — only fires on outbound emails with commitment keywords.
- `triggers/clickup_trigger.py` — ClickUp sync deadline INSERT. Not a user obligation, different semantics. Phase 4.

## Quality Checkpoints
1. Syntax check all 6 modified files: `python3 -c "import py_compile; py_compile.compile('FILE', doraise=True)"`
2. `models/cortex.py` — verify `cortex_create_deadline()` and `cortex_store_decision()` both have `conn.rollback()` in except blocks
3. `baker_mcp_server.py` — verify legacy path preserved as `else` (feature flag OFF = old behavior)
4. `deadline_manager.py` — verify `find_duplicate_deadline()` still runs BEFORE the Cortex/legacy fork
5. `fireflies_trigger.py` — verify `insert_deadline` import kept at line 212 for fallback
6. No new imports at module level — all imports inside functions (lazy) to avoid circular deps
7. After deploy: create a test deadline via MCP, verify `source_agent='cowork'` and cortex_event exists
8. After deploy: verify existing functionality unchanged — email/meeting pipelines still create deadlines

## Verification SQL
```sql
-- After deploy: check recent deadlines have source_agent populated
SELECT id, description, source_agent, source_type, created_at
FROM deadlines
WHERE created_at > NOW() - INTERVAL '1 hour'
ORDER BY id DESC LIMIT 10;

-- Check cortex_events are being created
SELECT id, event_type, category, source_agent, source_type, created_at
FROM cortex_events
WHERE created_at > NOW() - INTERVAL '1 hour'
ORDER BY id DESC LIMIT 10;

-- Check feature flag is ON
SELECT key, value FROM cortex_config WHERE key = 'tool_router_enabled';

-- Dedup shadow mode: any would_merge events?
SELECT id, event_type, source_agent, payload->>'description' as desc
FROM cortex_events
WHERE event_type IN ('would_merge', 'review_needed')
ORDER BY id DESC LIMIT 10;
```
