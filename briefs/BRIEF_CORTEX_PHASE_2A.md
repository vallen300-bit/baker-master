# BRIEF: CORTEX-PHASE-2A — Event Bus + Tool Router + Decisions→Insights Pipeline

## Context
Phase 1A deployed: `wiki_pages` + `cortex_config` + dual-run context loading. Now we need the event bus so shared writes (deadlines, decisions) flow through Cortex for attribution, audit, and auto-routing. This is the first deployable slice of Phase 2 — behind `tool_router_enabled` feature flag (OFF by default).

**Director request:** Decisions→pm_pending_insights pipeline so Monaco debrief gap never happens again.

**Parent brief:** `briefs/BRIEF_AGENT_ORCHESTRATION_1.md`

## Estimated time: ~4-5h
## Complexity: Medium
## Prerequisites: Phase 1A complete (cortex_config table exists)

---

## Step 1: Create `cortex_events` Table

### Problem
No append-only event log for shared writes. No audit trail beyond baker_actions (ClickUp only).

### Current State
`cortex_events` table does not exist. `baker_actions` only logs ClickUp writes.

### Implementation

Add `_ensure_cortex_events_table()` to `memory/store_back.py`, right after `_ensure_cortex_config_table()` (line 175):

```python
self._ensure_cortex_events_table()
```

Method (add after `get_cortex_config`, around line 2570):

```python
def _ensure_cortex_events_table(self):
    """CORTEX-PHASE-2A: Append-only event bus for shared writes."""
    conn = self._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cortex_events (
                id BIGSERIAL PRIMARY KEY,
                event_type TEXT NOT NULL,
                category TEXT NOT NULL,
                source_agent TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_ref TEXT,
                payload JSONB NOT NULL,
                refers_to BIGINT,
                canonical_id INTEGER,
                qdrant_id TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_cortex_events_type
            ON cortex_events(event_type, created_at)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_cortex_events_category
            ON cortex_events(category, created_at)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_cortex_events_agent
            ON cortex_events(source_agent, created_at)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_cortex_events_refers
            ON cortex_events(refers_to) WHERE refers_to IS NOT NULL
        """)
        conn.commit()
        cur.close()
        logger.info("cortex_events table verified")
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"Could not ensure cortex_events table: {e}")
    finally:
        self._put_conn(conn)
```

### Verification
```sql
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name = 'cortex_events' ORDER BY ordinal_position;
```
→ 11 columns

---

## Step 2: Add `source_agent` Column to `deadlines` and `decisions`

### Problem
`source_type='agent'` — but WHICH agent? Need attribution.

### Current State
- `deadlines` has `source_type` (varchar) but no `source_agent`
- `decisions` has `trigger_type` (text) but no `source_agent`

### Implementation

In `_ensure_cortex_events_table()`, add after the CREATE TABLE block:

```python
# Add source_agent to deadlines and decisions (nullable — won't break existing inserts)
cur.execute("ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS source_agent TEXT")
cur.execute("ALTER TABLE decisions ADD COLUMN IF NOT EXISTS source_agent TEXT")
```

### Verification
```sql
SELECT column_name FROM information_schema.columns
WHERE table_name = 'deadlines' AND column_name = 'source_agent';
-- Should return 1 row

SELECT column_name FROM information_schema.columns
WHERE table_name = 'decisions' AND column_name = 'source_agent';
-- Should return 1 row
```

---

## Step 3: Create `models/cortex.py` — Event Bus Core

### Problem
No centralized function for shared writes. Each tool does its own INSERT.

### Implementation

Create new file `models/cortex.py`:

```python
"""
Baker Cortex v2 — Event Bus
CORTEX-PHASE-2A: publish_event() + audit + decisions→insights pipeline.
Behind tool_router_enabled feature flag.
"""
import json
import logging
from typing import Optional
from datetime import datetime, timezone

logger = logging.getLogger("baker.cortex")


def _get_store():
    """Get SentinelStoreBack singleton."""
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


def _get_conn():
    store = _get_store()
    return store._get_conn()


def _put_conn(conn):
    store = _get_store()
    store._put_conn(conn)


def publish_event(
    event_type: str,
    category: str,
    source_agent: str,
    source_type: str,
    payload: dict,
    source_ref: str = None,
    canonical_id: int = None,
) -> Optional[int]:
    """
    Publish an event to the Cortex event bus.
    This is the SINGLE entry point for all coordinated writes.

    Returns: event ID or None on failure.
    """
    conn = _get_conn()
    if not conn:
        logger.error("cortex.publish_event: no DB connection")
        return None
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO cortex_events
                (event_type, category, source_agent, source_type,
                 source_ref, payload, canonical_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            event_type, category, source_agent, source_type,
            source_ref, json.dumps(payload), canonical_id,
        ))
        event_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        logger.info(
            "cortex event #%d: %s/%s by %s (canonical=%s)",
            event_id, event_type, category, source_agent, canonical_id
        )

        # Post-write hooks (non-blocking — failures logged, not raised)
        try:
            _audit_to_baker_actions(event_type, category, source_agent, payload, event_id)
        except Exception as e:
            logger.warning("cortex audit failed (non-fatal): %s", e)

        try:
            _auto_queue_insights(category, source_agent, payload, canonical_id)
        except Exception as e:
            logger.warning("cortex insights queue failed (non-fatal): %s", e)

        return event_id
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("cortex.publish_event failed: %s", e)
        return None
    finally:
        _put_conn(conn)


def _audit_to_baker_actions(
    event_type: str, category: str, source_agent: str,
    payload: dict, event_id: int,
):
    """Log every Cortex event to baker_actions for audit trail."""
    conn = _get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO baker_actions
                (action_type, payload, trigger_source, success)
            VALUES (%s, %s, %s, TRUE)
        """, (
            f"cortex:{event_type}:{category}",
            json.dumps({
                "event_id": event_id,
                "source_agent": source_agent,
                "summary": str(payload.get("description", payload.get("decision", "")))[:200],
            }),
            source_agent,
        ))
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning("_audit_to_baker_actions failed: %s", e)
    finally:
        _put_conn(conn)


# ─── Decisions → PM Pending Insights Pipeline ───

# Map: keyword patterns → PM slugs that should receive the insight
PM_MATTER_KEYWORDS = {
    "ao_pm": [
        "oskolkov", "andrey", "ao", "aelio", "aukera", "capital call",
        "hagenauer", "lilienmatt", "balgerstrasse", "rg7", "riemergasse",
        "participation agreement", "rosfinmonitoring",
    ],
    "movie_am": [
        "movie", "mandarin oriental", "mohg", "mario habicher",
        "francesco", "robin", "rolf", "operator", "occupancy",
        "revpar", "gop", "ff&e", "warranty", "rg7", "riemergasse",
    ],
}

# Map: keyword → target view file for the insight
INSIGHT_TARGET_FILES = {
    "capital call": "agenda.md",
    "hagenauer": "agenda.md",
    "lilienmatt": "agenda.md",
    "balgerstrasse": "agenda.md",
    "aukera": "agenda.md",
    "rosfinmonitoring": "psychology.md",
    "co-ownership": "psychology.md",
    "udmurtia": "psychology.md",
    "oskolkov": "agenda.md",
    "prey": "communication_rules.md",
    "hunt": "communication_rules.md",
    "signal": "communication_rules.md",
    "movie": "agenda.md",
    "mandarin": "agenda.md",
    "occupancy": "kpi_framework.md",
    "revpar": "kpi_framework.md",
    "gop": "kpi_framework.md",
    "warranty": "owner_obligations.md",
    "operator": "operator_dynamics.md",
}


def _auto_queue_insights(
    category: str, source_agent: str, payload: dict,
    canonical_id: int = None,
):
    """
    When a decision is stored, check if it matches any PM's matters.
    If yes, auto-queue as pm_pending_insight targeting the right view file.
    """
    if category != "decision":
        return  # Only decisions trigger insight queueing for now

    decision_text = payload.get("decision", "")
    if not decision_text:
        return

    decision_lower = decision_text.lower()

    for pm_slug, keywords in PM_MATTER_KEYWORDS.items():
        # Don't create insight for the agent that stored the decision
        # (it already knows — the insight is for OTHER PMs, or for Director review)
        matched_keywords = [kw for kw in keywords if kw in decision_lower]
        if not matched_keywords:
            continue

        # Find best target file
        target_file = "agenda.md"  # default
        for kw, tf in INSIGHT_TARGET_FILES.items():
            if kw in decision_lower:
                target_file = tf
                break

        # Queue the insight
        conn = _get_conn()
        if not conn:
            continue
        try:
            cur = conn.cursor()
            # Check for duplicate (same pm_slug + similar text in last 24h)
            cur.execute("""
                SELECT id FROM pm_pending_insights
                WHERE pm_slug = %s AND status = 'pending'
                  AND insight = %s
                  AND created_at > NOW() - INTERVAL '24 hours'
                LIMIT 1
            """, (pm_slug, decision_text))
            if cur.fetchone():
                cur.close()
                _put_conn(conn)
                continue  # Already queued

            cur.execute("""
                INSERT INTO pm_pending_insights
                    (pm_slug, insight, target_file, target_section,
                     source_question, confidence, status)
                VALUES (%s, %s, %s, %s, %s, 'medium', 'pending')
            """, (
                pm_slug,
                decision_text,
                target_file,
                f"Auto-queued from decision (matched: {', '.join(matched_keywords[:3])})",
                f"cortex:{source_agent}:decision#{canonical_id}",
            ))
            conn.commit()
            cur.close()
            logger.info(
                "cortex: auto-queued insight for %s from decision (matched: %s, target: %s)",
                pm_slug, matched_keywords[:3], target_file,
            )
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning("_auto_queue_insights failed for %s: %s", pm_slug, e)
        finally:
            _put_conn(conn)
```

### Key Constraints
- `publish_event()` is synchronous — no async needed (runs in agent tool execution path)
- Post-write hooks (audit, insights) are in try/except — failures don't block the main write
- Insight dedup: same pm_slug + same text + last 24h = skip
- `PM_MATTER_KEYWORDS` and `INSIGHT_TARGET_FILES` are hardcoded for now — will move to `wiki_config` in Phase 2B

### Verification
```sql
-- After a decision is stored through Cortex:
SELECT id, event_type, category, source_agent FROM cortex_events
ORDER BY id DESC LIMIT 5;

-- Check audit trail:
SELECT action_type, trigger_source FROM baker_actions
WHERE action_type LIKE 'cortex:%' ORDER BY id DESC LIMIT 5;

-- Check auto-queued insights:
SELECT pm_slug, insight, target_file, source_question
FROM pm_pending_insights WHERE source_question LIKE 'cortex:%'
ORDER BY id DESC LIMIT 5;
```

---

## Step 4: Wire Tool Router into ToolExecutor

### Problem
`_create_deadline()` and `_store_decision()` write directly to target tables. Need to route through Cortex when flag is ON.

### Current State
- `_create_deadline()` at `agent.py:1522` calls `insert_deadline()` directly
- `_store_decision()` at `agent.py:1588` calls `store.log_decision()` directly
- Both use `source_type='agent'` with no agent identity

### Implementation

Modify `execute()` in `orchestrator/agent.py` (line 860). Add Cortex routing at the TOP of the method, before the existing if/elif chain:

```python
def execute(self, tool_name: str, tool_input: dict) -> str:
    """Execute a tool and return formatted text."""
    try:
        # CORTEX-PHASE-2A: Route shared writes through event bus when flag ON
        if tool_name in ("create_deadline", "store_decision"):
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
            if store.get_cortex_config('tool_router_enabled', False):
                return self._cortex_route(tool_name, tool_input)

        # ... existing if/elif chain unchanged below ...
```

Add the `_cortex_route` method to the ToolExecutor class:

```python
def _cortex_route(self, tool_name: str, tool_input: dict) -> str:
    """CORTEX-PHASE-2A: Route tool calls through the Cortex event bus."""
    import json as _json
    from models.cortex import publish_event

    # Determine source_agent from capability context
    source_agent = getattr(self, '_current_capability', 'unknown')

    if tool_name == "create_deadline":
        # Still create the deadline via legacy path (for now)
        result = self._create_deadline(tool_input)

        # Extract the deadline ID from the result
        dl_id = None
        if "Deadline created (#" in result:
            try:
                dl_id = int(result.split("(#")[1].split(")")[0])
            except (IndexError, ValueError):
                pass

        # Update source_agent on the deadline row
        if dl_id:
            self._update_source_agent("deadlines", dl_id, source_agent)

        # Publish to Cortex event bus
        publish_event(
            event_type="accepted",
            category="deadline",
            source_agent=source_agent,
            source_type="agent",
            payload={
                "description": tool_input.get("description", ""),
                "due_date": tool_input.get("due_date", ""),
                "priority": tool_input.get("priority", "normal"),
            },
            canonical_id=dl_id,
        )
        return result

    elif tool_name == "store_decision":
        # Still store via legacy path
        result = self._store_decision(tool_input)

        # Extract decision ID
        dec_id = None
        try:
            parsed = _json.loads(result)
            dec_id = parsed.get("decision_id")
        except (ValueError, TypeError):
            pass

        # Update source_agent on the decision row
        if dec_id:
            self._update_source_agent("decisions", dec_id, source_agent)

        # Publish to Cortex event bus
        publish_event(
            event_type="accepted",
            category="decision",
            source_agent=source_agent,
            source_type="agent",
            payload={
                "decision": tool_input.get("decision", ""),
                "reasoning": tool_input.get("reasoning", ""),
                "confidence": tool_input.get("confidence", "high"),
            },
            canonical_id=dec_id,
        )
        return result

    # Fallback — shouldn't reach here
    return self.execute(tool_name, tool_input)


def _update_source_agent(self, table: str, record_id: int, source_agent: str):
    """Set source_agent on a deadline or decision row."""
    if table not in ("deadlines", "decisions"):
        return  # safety
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        cur = conn.cursor()
        cur.execute(
            f"UPDATE {table} SET source_agent = %s WHERE id = %s",
            (source_agent, record_id),
        )
        conn.commit()
        cur.close()
        store._put_conn(conn)
    except Exception as e:
        logger.warning("_update_source_agent(%s, %s) failed: %s", table, record_id, e)
```

**Critical:** The `_current_capability` attribute must be set on the ToolExecutor when a capability session starts. Check where ToolExecutor is instantiated:

```python
# In capability_runner.py where ToolExecutor is created:
tool_executor._current_capability = capability.slug
```

### Key Constraints
- **Feature flag OFF = zero behavior change.** The routing check is at the top of `execute()`. If flag is OFF, falls through to existing if/elif chain.
- **Legacy path STILL runs.** The Cortex route calls `_create_deadline()` / `_store_decision()` first, THEN publishes the event. The target tables get the record. Cortex gets the audit.
- **No infinite recursion.** `_cortex_route` calls `self._create_deadline()` directly, NOT `self.execute()`.
- **Fallback at the end of `_cortex_route` must NOT call `self.execute()` recursively** — it should return an error instead.

### Verification

**Flag OFF (default):**
1. Deploy. AO PM creates a deadline.
2. `deadlines` table has the row. `cortex_events` is EMPTY. Same as before.

**Flag ON:**
```sql
UPDATE cortex_config SET value = 'true'::jsonb WHERE key = 'tool_router_enabled';
```
3. AO PM creates a deadline.
4. `deadlines` has the row WITH `source_agent='ao_pm'`
5. `cortex_events` has event with `source_agent='ao_pm'`, `category='deadline'`
6. `baker_actions` has `action_type='cortex:accepted:deadline'`

7. AO PM stores a decision about capital call.
8. `decisions` has the row WITH `source_agent='ao_pm'`
9. `cortex_events` has event with `category='decision'`
10. `pm_pending_insights` has auto-queued insight for `ao_pm` (matched on "capital call")

---

## Step 5: Set `_current_capability` on ToolExecutor

### Problem
ToolExecutor doesn't know which capability is running it. Need this for `source_agent`.

### Current State
ToolExecutor is created in `capability_runner.py`. Need to check where.

### Implementation

Search for where ToolExecutor is instantiated and add the capability slug:

```python
# Find with: grep -n "ToolExecutor(" capability_runner.py
# Add after instantiation:
tool_executor._current_capability = capability.slug
```

If ToolExecutor is a singleton/reused across capabilities, set it at the start of each capability run instead.

### Verification
```python
# In the Cortex route, source_agent should be 'ao_pm' or 'movie_am', never 'unknown'
```

---

## Files Modified

- `memory/store_back.py` — `_ensure_cortex_events_table()` + `source_agent` ALTER TABLEs
- `models/cortex.py` — NEW: `publish_event()`, audit, decisions→insights pipeline
- `orchestrator/agent.py` — Cortex routing in `execute()`, `_cortex_route()`, `_update_source_agent()`
- `orchestrator/capability_runner.py` — Set `_current_capability` on ToolExecutor

## Do NOT Touch

- `models/deadlines.py` — `insert_deadline()` stays unchanged (legacy path)
- `baker_mcp/baker_mcp_server.py` — MCP rewiring is Phase 2B
- `triggers/email_trigger.py` — Pipeline rewiring is Phase 2B
- `triggers/fireflies_trigger.py` — Pipeline rewiring is Phase 2B
- `data/ao_pm/*.md`, `data/movie_am/*.md` — View files unchanged

## Quality Checkpoints

1. `cortex_events` table exists with 11 columns
2. `deadlines.source_agent` and `decisions.source_agent` columns exist
3. Flag OFF → zero behavior change (no cortex_events rows)
4. Flag ON → `create_deadline` → cortex_events + baker_actions + source_agent set
5. Flag ON → `store_decision` about AO topic → cortex_events + pm_pending_insights auto-queued
6. Flag ON → `store_decision` about MOVIE topic → pm_pending_insights for movie_am
7. `_current_capability` is 'ao_pm' or 'movie_am', never 'unknown'
8. All Python files pass syntax check
9. Render restart → tables auto-created, flag preserved

## Verification SQL
```sql
-- Tables exist
SELECT table_name FROM information_schema.tables
WHERE table_name = 'cortex_events';

-- Columns added
SELECT column_name FROM information_schema.columns
WHERE table_name = 'deadlines' AND column_name = 'source_agent';

-- Feature flags
SELECT * FROM cortex_config;

-- After testing with flag ON:
SELECT id, event_type, category, source_agent, canonical_id
FROM cortex_events ORDER BY id DESC LIMIT 10;

SELECT action_type, trigger_source FROM baker_actions
WHERE action_type LIKE 'cortex:%' ORDER BY id DESC LIMIT 5;

SELECT pm_slug, target_file, source_question
FROM pm_pending_insights WHERE source_question LIKE 'cortex:%'
ORDER BY id DESC LIMIT 5;
```
