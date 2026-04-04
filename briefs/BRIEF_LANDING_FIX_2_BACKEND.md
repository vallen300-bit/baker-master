# BRIEF: LANDING-FIX-2 — Backend SQL Fixes for Landing Page

## Context
Dashboard audit (Apr 3) found: meeting alert appearing in Travel card, duplicate deadlines in Promised To Do, and a connection reuse bug. All fixes are in `outputs/dashboard.py`.

## Estimated time: ~30min
## Complexity: Low-Medium
## Prerequisites: None (independent of Brief 1)

---

## Fix 1: Exclude meeting-tagged alerts from travel_alerts query

### Problem
"Oskolkov Monaco Meeting TODAY — Final Prep Check" shows in the Travel card. Alert 14833 has tags `['meeting', 'travel', 'sales', 'investor']` — the `travel` tag pulls it into the travel alerts query.

### Current State
`outputs/dashboard.py` lines 2416-2421:
```python
cur.execute("""
    SELECT * FROM alerts
    WHERE status = 'pending'
      AND (tags ? 'travel' OR title ILIKE '%%flight%%')
    ORDER BY created_at DESC
    LIMIT 10
""")
```

### Implementation
**Find:**
```python
            cur.execute("""
                SELECT * FROM alerts
                WHERE status = 'pending'
                  AND (tags ? 'travel' OR title ILIKE '%%flight%%')
                ORDER BY created_at DESC
                LIMIT 10
            """)
```

**Replace with:**
```python
            cur.execute("""
                SELECT * FROM alerts
                WHERE status = 'pending'
                  AND (tags ? 'travel' OR title ILIKE '%%flight%%')
                  AND NOT (tags ? 'meeting')
                ORDER BY created_at DESC
                LIMIT 10
            """)
```

### Key Constraints
- Only add the `AND NOT (tags ? 'meeting')` clause — don't restructure the query
- This preserves alerts that are purely travel (flights, departures) while excluding meeting prep alerts that happen to involve travel

### Verification
```sql
-- Should return 0 rows for the Oskolkov alert:
SELECT id, title, tags FROM alerts
WHERE status = 'pending'
  AND (tags ? 'travel' OR title ILIKE '%flight%')
  AND NOT (tags ? 'meeting')
  AND title ILIKE '%Oskolkov%'
LIMIT 5;
```

---

## Fix 2: Deduplicate Promised To Do deadlines

### Problem
ClickUp sync creates two deadline records per task:
- ID 1336: `[BAKER/Handoff Notes] [russo_ai] Obtain current shareholder loan...` (snippet: `clickup_deadline:86c94dgxh`)
- ID 1335: `Obtain current shareholder loan...` (snippet: full context)

Same pattern for IDs 1332 + 1331 (Ebner Stolz). Count shows 10, real unique items ~7-8.

### Current State
`outputs/dashboard.py` lines 2183-2196:
```python
cur.execute("""
    SELECT id, description, due_date, source_type, confidence,
           priority, status, created_at,
           LEFT(source_snippet, 500) AS source_snippet
    FROM deadlines
    WHERE status = 'active'
      AND (is_critical IS NOT TRUE)
      AND due_date >= CURRENT_DATE
      AND due_date <= CURRENT_DATE + INTERVAL '7 days'
      AND NOT (description ILIKE '%%flight%%' OR description ILIKE '%%departure%%'
               OR description ILIKE '%%travel%%' OR description ILIKE '%%airport%%'
               OR description ILIKE '%%boarding%%' OR description ILIKE '%%check-in%%')
    ORDER BY priority DESC, created_at DESC LIMIT 10
""")
```

### Implementation
Wrap the query with `DISTINCT ON` to deduplicate by normalized description. The key insight: duplicates have the same core text — one prefixed with `[BAKER/Handoff Notes] [russo_ai]`. We strip that prefix for dedup and keep the row with the longer `source_snippet` (more useful context).

**Find:**
```python
            cur.execute("""
                SELECT id, description, due_date, source_type, confidence,
                       priority, status, created_at,
                       LEFT(source_snippet, 500) AS source_snippet
                FROM deadlines
                WHERE status = 'active'
                  AND (is_critical IS NOT TRUE)
                  AND due_date >= CURRENT_DATE
                  AND due_date <= CURRENT_DATE + INTERVAL '7 days'
                  AND NOT (description ILIKE '%%flight%%' OR description ILIKE '%%departure%%'
                           OR description ILIKE '%%travel%%' OR description ILIKE '%%airport%%'
                           OR description ILIKE '%%boarding%%' OR description ILIKE '%%check-in%%')
                ORDER BY priority DESC, created_at DESC LIMIT 10
            """)
```

**Replace with:**
```python
            # LANDING-FIX-2: Deduplicate ClickUp-synced deadlines that differ only by prefix
            cur.execute("""
                SELECT DISTINCT ON (
                    REGEXP_REPLACE(LOWER(description), '^\[.*?\]\s*(\[.*?\]\s*)*', '')
                )
                    id, description, due_date, source_type, confidence,
                    priority, status, created_at,
                    LEFT(source_snippet, 500) AS source_snippet
                FROM deadlines
                WHERE status = 'active'
                  AND (is_critical IS NOT TRUE)
                  AND due_date >= CURRENT_DATE
                  AND due_date <= CURRENT_DATE + INTERVAL '7 days'
                  AND NOT (description ILIKE '%%flight%%' OR description ILIKE '%%departure%%'
                           OR description ILIKE '%%travel%%' OR description ILIKE '%%airport%%'
                           OR description ILIKE '%%boarding%%' OR description ILIKE '%%check-in%%')
                ORDER BY REGEXP_REPLACE(LOWER(description), '^\[.*?\]\s*(\[.*?\]\s*)*', ''),
                         LENGTH(COALESCE(source_snippet, '')) DESC,
                         priority DESC, created_at DESC
                LIMIT 10
            """)
```

### How it works
- `REGEXP_REPLACE(LOWER(description), '^\[.*?\]\s*(\[.*?\]\s*)*', '')` strips leading `[bracketed]` prefixes
- `DISTINCT ON` keeps one row per normalized description
- `ORDER BY ... LENGTH(source_snippet) DESC` prefers the row with richer context (not the bare `clickup_deadline:XXXX`)
- Then sorts by priority and recency as before

### Key Constraints
- The LIMIT 10 stays — unbounded queries are a Baker anti-pattern
- Don't change the WHERE filters — they correctly exclude travel and critical items
- This only affects display dedup — the underlying duplicate records remain (cleaning those is a separate data hygiene task)

### Verification
```sql
-- Test the dedup query standalone:
SELECT DISTINCT ON (
    REGEXP_REPLACE(LOWER(description), '^\[.*?\]\s*(\[.*?\]\s*)*', '')
)
    id, description, LEFT(source_snippet, 60) as snippet
FROM deadlines
WHERE status = 'active'
  AND (is_critical IS NOT TRUE)
  AND due_date >= CURRENT_DATE
  AND due_date <= CURRENT_DATE + INTERVAL '7 days'
  AND NOT (description ILIKE '%flight%' OR description ILIKE '%departure%'
           OR description ILIKE '%travel%' OR description ILIKE '%airport%')
ORDER BY REGEXP_REPLACE(LOWER(description), '^\[.*?\]\s*(\[.*?\]\s*)*', ''),
         LENGTH(COALESCE(source_snippet, '')) DESC,
         priority DESC, created_at DESC
LIMIT 10;
-- Expected: ~7-8 rows instead of 10, no duplicate pairs
```

---

## Fix 3: Move travel queries inside connection block

### Problem
`conn` is returned to the pool at line 2270 (`store._put_conn(conn)`), then reused at lines 2415 and 2431 for `travel_alerts` and `travel_deadlines` queries. This is unsafe — the connection is back in the pool and could be given to another concurrent request.

### Current State
Structure of `get_morning_brief()`:
```
conn = store._get_conn()          # line 2104
try:
    # ... stats, fires, deadlines queries ...
    cur.close()                    # line 2268
finally:
    store._put_conn(conn)          # line 2270

# ... narrative generation ...

# travel_alerts query uses conn    # line 2415  <-- BUG: conn already returned
# travel_deadlines query uses conn # line 2431  <-- BUG: conn already returned
```

### Implementation
Move the two travel queries INSIDE the existing `try/finally` block, just before `cur.close()` at line 2268.

**Step 1:** Find the `cur.close()` line inside the first connection block (line 2268). ADD the following two query blocks BEFORE it:

**Find:**
```python
            cur.close()
        finally:
            store._put_conn(conn)
```

(This is at lines 2268-2270)

**Replace with:**
```python
            # LANDING-FIX-2: Travel queries moved inside connection block (was using conn after pool return)
            # Travel alerts (any tier, not just top_fires tier=1)
            try:
                cur.execute("""
                    SELECT * FROM alerts
                    WHERE status = 'pending'
                      AND (tags ? 'travel' OR title ILIKE '%%flight%%')
                      AND NOT (tags ? 'meeting')
                    ORDER BY created_at DESC
                    LIMIT 10
                """)
                _travel_alerts_rows = [_serialize(dict(r)) for r in cur.fetchall()]
            except Exception as e:
                logger.warning(f"Morning brief: travel alerts query failed: {e}")
                conn.rollback()
                _travel_alerts_rows = []

            # Travel-related deadlines (next 3 days)
            try:
                cur.execute("""
                    SELECT id, description, due_date, priority, source_snippet
                    FROM deadlines
                    WHERE status = 'active'
                      AND due_date >= CURRENT_DATE
                      AND due_date < CURRENT_DATE + INTERVAL '4 days'
                      AND (description ILIKE '%%flight%%' OR description ILIKE '%%departure%%'
                           OR description ILIKE '%%travel%%' OR description ILIKE '%%airport%%'
                           OR description ILIKE '%%train%%' OR description ILIKE '%%depart%%')
                    ORDER BY due_date ASC LIMIT 10
                """)
                _travel_deadlines_rows = [_serialize(dict(r)) for r in cur.fetchall()]
            except Exception as e:
                logger.warning(f"Morning brief: travel deadlines query failed: {e}")
                conn.rollback()
                _travel_deadlines_rows = []

            cur.close()
        finally:
            store._put_conn(conn)
```

**Step 2:** DELETE the old travel_alerts block (the one that was at lines 2412-2426):

**Find and delete:**
```python
        # TRAVEL-FIX-1: Dedicated travel alerts (any tier, not just top_fires tier=1)
        travel_alerts = []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT * FROM alerts
                WHERE status = 'pending'
                  AND (tags ? 'travel' OR title ILIKE '%%flight%%')
                ORDER BY created_at DESC
                LIMIT 10
            """)
            travel_alerts = [_serialize(dict(r)) for r in cur.fetchall()]
            cur.close()
        except Exception as e:
            logger.warning(f"Morning brief: travel alerts query failed: {e}")
```

**Replace with:**
```python
        # LANDING-FIX-2: travel_alerts now fetched inside connection block above
        travel_alerts = _travel_alerts_rows
```

**Step 3:** DELETE the old travel_deadlines block (was at lines 2428-2446):

**Find and delete:**
```python
        # TRAVEL-HYGIENE-1: Travel-related deadlines (next 3 days) for grid
        travel_deadlines = []
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT id, description, due_date, priority, source_snippet
                FROM deadlines
                WHERE status = 'active'
                  AND due_date >= CURRENT_DATE
                  AND due_date < CURRENT_DATE + INTERVAL '4 days'
                  AND (description ILIKE '%%flight%%' OR description ILIKE '%%departure%%'
                       OR description ILIKE '%%travel%%' OR description ILIKE '%%airport%%'
                       OR description ILIKE '%%train%%' OR description ILIKE '%%depart%%')
                ORDER BY due_date ASC LIMIT 10
            """)
            travel_deadlines = [_serialize(dict(r)) for r in cur.fetchall()]
            cur.close()
        except Exception as e:
            logger.warning(f"Morning brief: travel deadlines query failed: {e}")
```

**Replace with:**
```python
        # LANDING-FIX-2: travel_deadlines now fetched inside connection block above
        travel_deadlines = _travel_deadlines_rows
```

### Key Constraints
- The `conn.rollback()` in except blocks is mandatory (PostgreSQL pattern from lessons.md)
- The variable names `_travel_alerts_rows` / `_travel_deadlines_rows` use underscore prefix to avoid shadowing the `travel_alerts` / `travel_deadlines` variables used later in the return dict
- Note: Fix 1's `AND NOT (tags ? 'meeting')` is already included in the moved query — don't apply it twice

### Verification
After deploy, reload the dashboard. Travel card and all 4 grid cells should load normally. Check Render logs for no new errors:
```
# In Render logs, search for:
"travel alerts query failed"
"travel deadlines query failed"
# Both should NOT appear
```

---

## Syntax Check
After all changes, run:
```bash
python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"
```

---

## Files Modified
- `outputs/dashboard.py` — 3 changes (meeting tag exclusion, deadline dedup, connection fix)

## Do NOT Touch
- `outputs/static/app.js` — frontend changes are in Brief 1
- `outputs/static/index.html` — no changes needed
- `models/deadlines.py` — critical items query is separate
- Any trigger files

## Quality Checkpoints
1. Travel card: no "Oskolkov Monaco Meeting" item
2. Promised To Do: ~7-8 items (not 10), no duplicate pairs
3. No connection errors in Render logs
4. All 4 grid cells load correctly
5. Python syntax check passes
