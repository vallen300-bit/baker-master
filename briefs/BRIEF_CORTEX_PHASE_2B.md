# BRIEF: CORTEX-PHASE-2B — Qdrant Semantic Dedup Gate + Shadow Mode

## Context
Phase 2A deployed: event bus + tool router + attribution. But no semantic dedup — duplicate deadlines still slip through. The existing text-based `_deadline_dedup_check()` catches exact-date keyword matches but misses paraphrased obligations from different sources (email + meeting + WhatsApp about the same thing).

This brief adds the Qdrant semantic dedup gate to `publish_event()`. Shadow mode first: logs dedup decisions without blocking writes. After 2 weeks calibration, flip `auto_merge_enabled=true`.

**Split:** This is 2B-i (dedup gate + backfill). Pipeline rewiring (MCP, email, Fireflies) is 2B-ii — separate brief after this is validated.

**Parent brief:** `briefs/BRIEF_AGENT_ORCHESTRATION_1.md` Phase 2, steps 2-4, 11-13.

## Estimated time: ~5-6h
## Complexity: Medium-High
## Prerequisites: Phase 2A deployed (cortex_events table, publish_event() exists)

---

## Step 1: Create `cortex_obligations` Qdrant Collection

### Problem
No vector collection for deadlines/decisions. Semantic similarity search impossible.

### Current State
15 Qdrant collections exist. None for deadlines or obligations. Collection creation pattern: `store_back._ensure_collection()` at line 740.

### Implementation

Add to `memory/store_back.py` in `__init__`, after `_ensure_cortex_events_table()` (line 177):

```python
        # CORTEX-PHASE-2B: Qdrant dedup collection
        self._ensure_cortex_obligations_collection()
```

Add the method (after `_ensure_cortex_events_table`):

```python
def _ensure_cortex_obligations_collection(self):
    """CORTEX-PHASE-2B: Create Qdrant collection for semantic dedup."""
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import VectorParams, Distance
        from config.settings import config

        if not config.qdrant.url or not config.qdrant.api_key:
            logger.warning("Qdrant not configured — skipping cortex_obligations collection")
            return

        client = QdrantClient(url=config.qdrant.url, api_key=config.qdrant.api_key)
        try:
            client.get_collection("cortex_obligations")
            logger.info("cortex_obligations collection already exists")
        except Exception:
            client.create_collection(
                collection_name="cortex_obligations",
                vectors_config=VectorParams(
                    size=1024,  # Voyage AI voyage-3
                    distance=Distance.COSINE,
                ),
            )
            logger.info("Created cortex_obligations Qdrant collection")
    except Exception as e:
        logger.warning(f"Could not ensure cortex_obligations collection: {e}")
```

### Verification
Check Qdrant dashboard or:
```python
from qdrant_client import QdrantClient
client = QdrantClient(url=..., api_key=...)
info = client.get_collection("cortex_obligations")
print(info.vectors_count, info.points_count)
# → 0, 0 (empty until backfill)
```

---

## Step 2: Add Semantic Dedup Gate to `publish_event()`

### Problem
`publish_event()` accepts all writes. No similarity check before insertion.

### Current State
`models/cortex.py` has `publish_event()` that inserts into `cortex_events` and runs post-write hooks. No pre-write checks.

### Implementation

Add dedup functions to `models/cortex.py`:

```python
# ─── Qdrant Semantic Dedup Gate ───

def _get_qdrant():
    """Get Qdrant client singleton."""
    from qdrant_client import QdrantClient
    from config.settings import config
    if not hasattr(_get_qdrant, '_client'):
        if not config.qdrant.url:
            return None
        _get_qdrant._client = QdrantClient(
            url=config.qdrant.url,
            api_key=config.qdrant.api_key,
        )
    return _get_qdrant._client


def _embed_text(text: str) -> list:
    """Embed text using Voyage AI. Returns 1024-dim vector."""
    import voyageai
    from config.settings import config
    if not config.voyage.api_key:
        return []
    client = voyageai.Client(api_key=config.voyage.api_key)
    result = client.embed(
        texts=[text[:2000]],  # Cap at 2000 chars to control cost
        model=config.voyage.model,  # "voyage-3"
        input_type="document",
    )
    return result.embeddings[0]


def check_dedup(
    description: str,
    category: str,
    due_date: str = None,
    amount: float = None,
) -> tuple:
    """
    Unconditional semantic check before any shared write.
    Returns: ('new', None) | ('auto_merge', canonical_id) | ('review', canonical_id)

    Thresholds (from architecture brief):
    - >= 0.92: auto-merge (same obligation, different words)
    - 0.85-0.92: human review queue
    - < 0.85: definitely new

    Field override: if dates or amounts differ, NEVER auto-merge.
    """
    qdrant = _get_qdrant()
    if not qdrant:
        return ('new', None)

    try:
        embedding = _embed_text(description)
        if not embedding:
            return ('new', None)

        from qdrant_client.models import Filter, FieldCondition, MatchValue

        results = qdrant.search(
            collection_name="cortex_obligations",
            query_vector=embedding,
            query_filter=Filter(
                must=[FieldCondition(key="category", match=MatchValue(value=category))]
            ),
            score_threshold=0.85,  # Floor — below this, definitely new
            limit=3,
        )

        if not results:
            return ('new', None)

        best = results[0]
        score = best.score
        existing = best.payload

        # NEVER auto-merge if structured fields differ
        if due_date and existing.get('due_date') and due_date != existing['due_date']:
            return ('new', None)  # Different dates = different obligation
        if amount and existing.get('amount') and abs(amount - existing['amount']) > 0.01:
            return ('new', None)  # Different amounts = different obligation

        if score >= 0.92:
            return ('auto_merge', existing.get('canonical_id'))
        elif score >= 0.85:
            return ('review', existing.get('canonical_id'))
        else:
            return ('new', None)

    except Exception as e:
        logger.warning("check_dedup failed (non-fatal, treating as new): %s", e)
        return ('new', None)


def upsert_obligation_vector(
    canonical_id: int,
    description: str,
    category: str,
    due_date: str = None,
    source_agent: str = None,
):
    """Write/update the Qdrant vector for an obligation."""
    qdrant = _get_qdrant()
    if not qdrant:
        return

    try:
        embedding = _embed_text(description)
        if not embedding:
            return

        from qdrant_client.models import PointStruct

        point_id = f"{category}_{canonical_id}"
        qdrant.upsert(
            collection_name="cortex_obligations",
            points=[PointStruct(
                id=abs(hash(point_id)) % (2**63),  # Qdrant needs int or UUID
                vector=embedding,
                payload={
                    "canonical_id": canonical_id,
                    "category": category,
                    "description": description[:500],
                    "due_date": due_date,
                    "source_agent": source_agent,
                    "point_key": point_id,
                },
            )],
        )
        logger.info("cortex: upserted vector for %s", point_id)
    except Exception as e:
        logger.warning("upsert_obligation_vector failed (non-fatal): %s", e)
```

Now modify `publish_event()` to call the dedup gate. Add BEFORE the INSERT:

```python
def publish_event(
    event_type: str,
    category: str,
    source_agent: str,
    source_type: str,
    payload: dict,
    source_ref: str = None,
    canonical_id: int = None,
) -> Optional[int]:
    """Publish an event to the Cortex event bus."""

    # CORTEX-PHASE-2B: Pre-write semantic dedup gate
    dedup_category = category if category in ("deadline", "decision") else None
    dedup_result = ('new', None)

    if dedup_category:
        try:
            dedup_result = check_dedup(
                description=payload.get("description", payload.get("decision", "")),
                category=dedup_category,
                due_date=payload.get("due_date"),
                amount=payload.get("amount"),
            )
        except Exception as e:
            logger.warning("Dedup gate failed (non-fatal): %s", e)
            dedup_result = ('new', None)

        # Check auto_merge_enabled flag
        store = _get_store()
        auto_merge = store.get_cortex_config('auto_merge_enabled', False)

        if dedup_result[0] == 'auto_merge':
            if auto_merge:
                # LIVE MODE: Actually merge — skip the write, return existing
                logger.info(
                    "cortex DEDUP: auto-merge %s into canonical #%s (score >= 0.92)",
                    category, dedup_result[1]
                )
                # Still log the merge event for audit
                _log_dedup_event(event_type, category, source_agent, payload,
                                 dedup_result, "merged")
                return dedup_result[1]  # Return existing canonical_id
            else:
                # SHADOW MODE: Log but don't block
                logger.info(
                    "cortex SHADOW: would_merge %s into canonical #%s (auto_merge OFF)",
                    category, dedup_result[1]
                )
                _log_dedup_event(event_type, category, source_agent, payload,
                                 dedup_result, "would_merge")
                # Fall through to normal insert

        elif dedup_result[0] == 'review':
            logger.info(
                "cortex DEDUP: review_needed %s — similar to canonical #%s (0.85-0.92)",
                category, dedup_result[1]
            )
            _log_dedup_event(event_type, category, source_agent, payload,
                             dedup_result, "review_needed")
            # Fall through to normal insert (Director reviews later)

    # ... existing INSERT INTO cortex_events code continues here ...
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

        # Post-write: upsert vector (so future writes can dedup against this one)
        if dedup_category and canonical_id:
            try:
                upsert_obligation_vector(
                    canonical_id=canonical_id,
                    description=payload.get("description", payload.get("decision", "")),
                    category=dedup_category,
                    due_date=payload.get("due_date"),
                    source_agent=source_agent,
                )
            except Exception as e:
                logger.warning("Post-write vector upsert failed (non-fatal): %s", e)

        # Existing post-write hooks
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


def _log_dedup_event(
    event_type: str, category: str, source_agent: str,
    payload: dict, dedup_result: tuple, dedup_action: str,
):
    """Log dedup decisions to cortex_events for shadow mode analysis."""
    conn = _get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO cortex_events
                (event_type, category, source_agent, source_type,
                 payload, refers_to)
            VALUES (%s, %s, %s, 'dedup_gate', %s, %s)
        """, (
            dedup_action,  # "would_merge", "merged", "review_needed"
            category,
            source_agent,
            json.dumps({
                **payload,
                "dedup_score": ">=0.92" if dedup_result[0] == "auto_merge" else "0.85-0.92",
                "matched_canonical": dedup_result[1],
            }),
            dedup_result[1],  # refers_to = canonical_id of the matched obligation
        ))
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning("_log_dedup_event failed: %s", e)
    finally:
        _put_conn(conn)
```

### Key Constraints
- **Shadow mode (auto_merge_enabled=false):** Dedup gate runs, logs results, but NEVER blocks writes. All obligations still get created.
- **Live mode (auto_merge_enabled=true):** Score >= 0.92 with matching structured fields → skip write, return existing canonical_id.
- **Field override:** Different dates or amounts → ALWAYS treat as new, regardless of text similarity.
- **Failure mode:** If Qdrant or Voyage AI is down, `check_dedup` returns `('new', None)` — writes proceed normally.
- **Embedding cost:** ~$0.0001/embed. At 100 deadlines/day = $0.01/day. Negligible.
- **Text cap:** Descriptions capped at 2000 chars for embedding to control cost.

### Verification

**Shadow mode test:**
```sql
-- After agent creates a deadline through Cortex:
SELECT event_type, category, source_agent, payload->>'dedup_score' as score
FROM cortex_events
WHERE event_type IN ('would_merge', 'review_needed', 'merged')
ORDER BY id DESC LIMIT 10;
```

---

## Step 3: Backfill Existing Deadlines into Qdrant

### Problem
57 active deadlines exist in PostgreSQL but have no vectors. The dedup gate can't find them.

### Implementation

Create `scripts/backfill_deadline_vectors.py`:

```python
#!/usr/bin/env python3
"""
CORTEX-PHASE-2B: One-time backfill of active deadlines into cortex_obligations Qdrant collection.
Run AFTER deploy. NOT on startup (OOM anti-pattern).
Safe to re-run (upserts by canonical_id).
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)


def main():
    import psycopg2
    from models.cortex import upsert_obligation_vector

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Active deadlines
    cur.execute("""
        SELECT id, description, due_date, source_type
        FROM deadlines
        WHERE status = 'active' AND description IS NOT NULL
        ORDER BY id
        LIMIT 200
    """)
    deadlines = cur.fetchall()
    print(f"Found {len(deadlines)} active deadlines to backfill")

    success = 0
    for dl_id, desc, due_date, source_type in deadlines:
        try:
            due_str = due_date.strftime("%Y-%m-%d") if due_date else None
            upsert_obligation_vector(
                canonical_id=dl_id,
                description=desc,
                category="deadline",
                due_date=due_str,
                source_agent=source_type or "backfill",
            )
            success += 1
            if success % 10 == 0:
                print(f"  Backfilled {success}/{len(deadlines)}...")
            time.sleep(0.1)  # Rate limit Voyage AI
        except Exception as e:
            print(f"  FAILED deadline #{dl_id}: {e}")

    print(f"\nDone: {success}/{len(deadlines)} deadlines backfilled to Qdrant")

    # Also backfill recent decisions (last 30 days)
    cur.execute("""
        SELECT id, decision
        FROM decisions
        WHERE created_at > NOW() - INTERVAL '30 days'
          AND decision IS NOT NULL
        ORDER BY id
        LIMIT 100
    """)
    decisions = cur.fetchall()
    print(f"\nFound {len(decisions)} recent decisions to backfill")

    d_success = 0
    for dec_id, decision_text in decisions:
        try:
            upsert_obligation_vector(
                canonical_id=dec_id,
                description=decision_text,
                category="decision",
                source_agent="backfill",
            )
            d_success += 1
            if d_success % 10 == 0:
                print(f"  Backfilled {d_success}/{len(decisions)}...")
            time.sleep(0.1)
        except Exception as e:
            print(f"  FAILED decision #{dec_id}: {e}")

    print(f"Done: {d_success}/{len(decisions)} decisions backfilled to Qdrant")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
```

### Key Constraints
- **NOT on startup** — run manually or via one-time endpoint. Startup OOM is a known anti-pattern.
- **Rate limited** — 0.1s sleep between Voyage API calls.
- **Safe to re-run** — uses `upsert` (overwrites by canonical_id hash).
- **LIMIT 200/100** — bounded queries.

### Verification
```python
# After running backfill:
from qdrant_client import QdrantClient
client = QdrantClient(url=..., api_key=...)
info = client.get_collection("cortex_obligations")
print(f"Points: {info.points_count}")
# → Should be ~57 (deadlines) + ~N (recent decisions)
```

---

## Files Modified

- `models/cortex.py` — `check_dedup()`, `upsert_obligation_vector()`, `_embed_text()`, `_get_qdrant()`, `_log_dedup_event()`, modified `publish_event()`
- `memory/store_back.py` — `_ensure_cortex_obligations_collection()` + init call
- `scripts/backfill_deadline_vectors.py` — NEW: one-time backfill

## Do NOT Touch

- `models/deadlines.py` — existing text-based dedup stays as independent fallback
- `baker_mcp/baker_mcp_server.py` — MCP rewiring is Phase 2B-ii
- `triggers/email_trigger.py` — pipeline rewiring is Phase 2B-ii
- `triggers/fireflies_trigger.py` — pipeline rewiring is Phase 2B-ii
- `orchestrator/agent.py` — tool router already routes through `publish_event()`

## Quality Checkpoints

1. `cortex_obligations` Qdrant collection exists (1024d, COSINE)
2. `auto_merge_enabled` is still `false` (shadow mode)
3. Agent creates deadline via Cortex → vector upserted to Qdrant
4. Agent creates similar deadline → `would_merge` event logged in cortex_events
5. Agent creates deadline with different date → treated as new (field override)
6. Qdrant down → writes proceed normally (graceful fallback)
7. Voyage AI down → writes proceed normally (graceful fallback)
8. Backfill script runs successfully (~57 deadlines + ~N decisions)
9. All Python files pass syntax check
10. Render restart → collection auto-created, vectors persist in Qdrant Cloud

## Verification SQL
```sql
-- Shadow mode dedup events:
SELECT event_type, category, source_agent,
       payload->>'dedup_score' as score,
       payload->>'matched_canonical' as matched
FROM cortex_events
WHERE event_type IN ('would_merge', 'review_needed')
ORDER BY id DESC LIMIT 10;

-- Feature flags:
SELECT * FROM cortex_config;

-- Total Cortex events:
SELECT event_type, COUNT(*) FROM cortex_events GROUP BY event_type ORDER BY count DESC;
```

## Cost Impact
- **Voyage AI embeddings:** ~$0.0001/embed. Backfill: 57+N embeds = <$0.02. Daily: ~100 embeds = $0.01/day.
- **Qdrant Cloud:** Already paid, new collection within existing capacity.
- **No LLM calls added.** Dedup is pure vector math.

## Backfill Execution

Run AFTER deploy, NOT on startup:

**Option A: Via Render shell**
```bash
cd /opt/render/project/src && python scripts/backfill_deadline_vectors.py
```

**Option B: One-time API endpoint** (add to dashboard.py, remove after use)
```python
@app.get("/api/admin/backfill-vectors")
async def backfill_vectors():
    import subprocess
    result = subprocess.run(
        ["python", "scripts/backfill_deadline_vectors.py"],
        capture_output=True, text=True, timeout=120
    )
    return {"stdout": result.stdout, "stderr": result.stderr}
```

**Recommended: Option B** — I can trigger it via curl after deploy, no Render shell needed.
