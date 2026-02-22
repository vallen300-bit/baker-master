# Brief 4C — PostgreSQL Store-Back Layer

**From:** Cowork (Architect)
**To:** Claude Code (Builder)
**Date:** 2026-02-19
**Status:** READY TO EXECUTE

---

## Context

The pipeline (`orchestrator/pipeline.py`) has a `store_back()` method at Step 5 with three TODO blocks:
1. Write contact updates to PostgreSQL
2. Write decisions to PostgreSQL
3. Embed interaction summary in Qdrant

The PostgreSQL schema already exists at `scripts/init_database.sql` — 6 tables:
- `contacts` — people Baker knows (with behavioral fields + seed data)
- `deals` — active/historical deals
- `decisions` — Baker's learning loop (decision + feedback)
- `preferences` — CEO/COO settings
- `trigger_log` — every pipeline run logged
- `alerts` — tiered alert queue (1=urgent, 2=important, 3=info)

Config is in `config/settings.py` → `PostgresConfig` (defaults: localhost:5432, db=sentinel, user=sentinel).

---

## Task 1 — PostgreSQL Setup

The system uses local PostgreSQL for now. Set it up:

```bash
# Check if PostgreSQL is installed
which psql || brew install postgresql@16

# Start service
brew services start postgresql@16

# Create role and database
psql postgres -c "CREATE ROLE sentinel WITH LOGIN PASSWORD 'sentinel_dev_2026';"
psql postgres -c "CREATE DATABASE sentinel OWNER sentinel;"

# Run schema
psql -U sentinel -d sentinel -f scripts/init_database.sql
```

**Update `.env`** (in `config/.env`) to add:
```
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=sentinel
POSTGRES_USER=sentinel
POSTGRES_PASSWORD=sentinel_dev_2026
```

**Verification:** `psql -U sentinel -d sentinel -c "SELECT count(*) FROM contacts;"` should return 10 (seed data).

---

## Task 2 — Build `memory/store_back.py` Module

Create `memory/store_back.py` — the write-side counterpart to `memory/retriever.py` (read-side).

### Required Interface

```python
class SentinelStoreBack:
    """Write layer for PostgreSQL structured memory."""

    def __init__(self):
        """Open connection pool using config.postgres."""

    # --- Contact Intelligence ---
    def upsert_contact(self, name: str, updates: dict) -> str:
        """
        Update or insert a contact. Merges fields, doesn't overwrite NULLs.
        Returns contact UUID.
        Handles: communication_style, response_pattern, preferred_channel,
                 active_deals, metadata, last_contact, etc.
        """

    def get_contact_by_name(self, name: str) -> dict | None:
        """Fuzzy lookup using pg_trgm similarity."""

    # --- Decision Log ---
    def log_decision(self, decision: str, reasoning: str,
                     confidence: str, trigger_type: str) -> int:
        """Insert into decisions table. Returns decision ID."""

    def record_feedback(self, decision_id: int, accepted: bool,
                        rejection_reason: str = None):
        """Update decision with CEO feedback (learning loop)."""

    # --- Trigger Log ---
    def log_trigger(self, trigger_type: str, source_id: str,
                    content: str, contact_id: str = None,
                    priority: str = None) -> int:
        """Log every pipeline execution. Returns trigger_log ID."""

    def update_trigger_result(self, trigger_id: int,
                              response_id: str, pipeline_ms: int,
                              tokens_in: int, tokens_out: int):
        """Update trigger_log after pipeline completes."""

    # --- Alerts ---
    def create_alert(self, tier: int, title: str, body: str = None,
                     action_required: bool = False,
                     trigger_id: int = None, contact_id: str = None,
                     deal_id: str = None) -> int:
        """Insert into alerts table. Returns alert ID."""

    def get_pending_alerts(self, tier: int = None) -> list:
        """Fetch unresolved alerts, optionally filtered by tier."""

    def acknowledge_alert(self, alert_id: int):
        """Mark alert as acknowledged."""

    def resolve_alert(self, alert_id: int):
        """Mark alert as resolved."""

    # --- Deals ---
    def upsert_deal(self, name: str, updates: dict) -> str:
        """Update or insert a deal. Returns deal UUID."""

    def get_active_deals(self) -> list:
        """All deals with status='active'."""
```

### Implementation Notes

- Use `psycopg2` (not asyncpg — the pipeline is sync).
- Use connection pooling: `psycopg2.pool.SimpleConnectionPool(minconn=1, maxconn=5)`.
- All writes use parameterized queries (no f-strings, no SQL injection).
- `upsert_contact` should use `INSERT ... ON CONFLICT (name) DO UPDATE SET ...` and only update non-NULL fields from the `updates` dict.
- Fuzzy name matching: `SELECT * FROM contacts ORDER BY similarity(name, %s) DESC LIMIT 1` with a threshold of 0.3.
- All timestamps in UTC.

### Dependency

```bash
pip install psycopg2-binary
```

---

## Task 3 — Wire into Pipeline

Replace the TODOs in `orchestrator/pipeline.py` → `store_back()` method:

```python
# In __init__, add:
from memory.store_back import SentinelStoreBack
self.store = SentinelStoreBack()

# In store_back(), replace TODOs:
def store_back(self, trigger: TriggerEvent, response: SentinelResponse):
    # 1. Log this trigger
    trigger_log_id = self.store.log_trigger(
        trigger_type=trigger.type,
        source_id=trigger.source_id,
        content=trigger.content[:1000],
        contact_id=trigger.contact_id,
        priority=trigger.priority,
    )

    # 2. Store contact updates
    for update in response.contact_updates:
        contact_name = update.pop("name", None)
        if contact_name:
            self.store.upsert_contact(contact_name, update)

    # 3. Store decisions
    for decision in response.decisions_log:
        self.store.log_decision(
            decision=decision.get("decision", ""),
            reasoning=decision.get("reasoning", ""),
            confidence=decision.get("confidence", "medium"),
            trigger_type=trigger.type,
        )

    # 4. Create alerts from response
    for alert in response.alerts:
        tier = {"urgent": 1, "important": 2, "info": 3}.get(
            alert.get("tier", "info"), 3
        )
        self.store.create_alert(
            tier=tier,
            title=alert.get("title", "Untitled alert"),
            body=alert.get("body", ""),
            action_required=alert.get("action_required", False),
            trigger_id=trigger_log_id,
        )

    # 5. Update trigger log with results
    self.store.update_trigger_result(
        trigger_id=trigger_log_id,
        response_id=str(trigger_log_id),
        pipeline_ms=response.metadata.get("pipeline_duration_ms", 0),
        tokens_in=response.metadata.get("tokens_estimated", 0),
        tokens_out=0,  # filled from Claude response usage
    )
```

**Important:** Make the store-back fault-tolerant. If PostgreSQL is down, the pipeline should still complete (log a warning, don't crash). Wrap all store operations in try/except.

---

## Task 4 — Add PostgreSQL Context to Retrieval

Currently `memory/retriever.py` only queries Qdrant. Add a method to also pull structured context from PostgreSQL:

```python
def get_structured_context(self, contact_name: str = None) -> dict:
    """
    Pull structured data from PostgreSQL to complement Qdrant vectors.
    Returns dict with: contact_profile, active_deals, pending_alerts, recent_decisions
    """
```

Wire this into the pipeline at Step 2 (retrieve_context). The structured context should be passed to the prompt builder alongside vector results.

**Note:** This is an enhancement, not a blocker. If it adds complexity, skip it and we'll add in Phase 5.

---

## Task 5 — CLI Verification Script

Create `scripts/test_storeback.py`:

```bash
python3 scripts/test_storeback.py
```

Should:
1. Connect to PostgreSQL ✓
2. Verify all 6 tables exist ✓
3. Verify seed data (10 contacts) ✓
4. Insert a test trigger_log entry ✓
5. Insert a test decision ✓
6. Create and resolve a test alert ✓
7. Upsert a contact with behavioral update ✓
8. Fuzzy match a contact name ✓
9. Clean up test data ✓

---

## Dependencies

```bash
pip install psycopg2-binary
```

`psycopg2-binary` is a standalone package, no system PostgreSQL headers needed.

---

## Success Criteria

1. ✅ PostgreSQL running with `sentinel` database and all 6 tables
2. ✅ `store_back.py` module with full CRUD for contacts, deals, decisions, triggers, alerts
3. ✅ Pipeline `store_back()` method wired up (replaces TODOs)
4. ✅ Fault-tolerant — pipeline doesn't crash if DB is down
5. ✅ Test script passes all 9 checks
6. ✅ (Optional) Structured context added to retrieval

---

## Priority Order

Tasks 1–3 are the core deliverable. Task 4 is nice-to-have. Task 5 is verification.

Do Tasks 1 → 2 → 3 → 5 → 4 (if time permits).
