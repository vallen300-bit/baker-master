# BRIEF: DEEP-MODE-2 — Cross-Session Memory

**Author:** AI Head (Session 20)
**For:** Code 300 (after DEEP-MODE-1)
**Priority:** HIGH — gives Baker continuity across sessions
**Estimated scope:** 2 files, ~60 lines new code
**Cost:** Zero — pure PostgreSQL ILIKE queries

---

## Problem

Baker stores every conversation to `conversation_memory` (138 entries, 9 days of history). But this data is never retrieved by topic. When the Director asks about Cupial today, Baker doesn't know they had a detailed discussion about Cupial escrow 6 days ago.

Current retrieval: `get_recent_conversations(limit=5)` — returns the 5 most recent, regardless of relevance. Used only for intent classification context, not for answering questions.

## Solution

Two changes:

1. **New method: `get_relevant_conversations()`** — topic-aware retrieval from conversation_memory
2. **Inject into the deep path** — prior conversations appear as "PRIOR BAKER CONVERSATIONS" in the system prompt

This gives Baker cross-session memory. When the Director asks about Cupial, Baker retrieves the Mar 5 Cupial discussion and can say "As we discussed last week about the Cupial escrow..."

## Implementation

### File 1: `memory/store_back.py`

Add new method to `SentinelStoreBack` class, right after `get_recent_conversations()` (~line 3456):

```python
def get_relevant_conversations(self, query: str, limit: int = 10,
                                exclude_hours: int = 1) -> list:
    """
    DEEP-MODE-2: Fetch past conversations relevant to the current query.
    Uses ILIKE matching on question and answer columns.
    Excludes conversations from the last N hours (those are in the current session).
    Returns list of dicts: [{question, answer, created_at}, ...] newest-first.
    """
    conn = self._get_conn()
    if not conn:
        return []
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Extract significant words from query (3+ chars)
        import re
        words = [w for w in re.findall(r'\b\w+\b', query.lower())
                 if len(w) >= 3 and w not in (
                     'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all',
                     'can', 'was', 'has', 'how', 'what', 'when', 'where',
                     'who', 'why', 'with', 'about', 'from', 'have', 'this',
                     'that', 'they', 'will', 'would', 'could', 'should',
                     'baker', 'tell', 'show', 'please', 'know', 'check',
                     'give', 'find', 'look', 'any', 'some', 'there',
                 )]

        if not words:
            return []

        # Build OR conditions: any significant word in question OR answer
        conditions = []
        params = []
        for word in words[:5]:  # cap at 5 keywords
            conditions.append("(LOWER(question) LIKE %s OR LOWER(COALESCE(answer,'')) LIKE %s)")
            pattern = f"%{word}%"
            params.extend([pattern, pattern])

        where_clause = " OR ".join(conditions)

        cur.execute(f"""
            SELECT question, answer, created_at
            FROM conversation_memory
            WHERE ({where_clause})
              AND answer IS NOT NULL
              AND LENGTH(answer) > 50
              AND created_at < NOW() - INTERVAL '{exclude_hours} hours'
            ORDER BY created_at DESC
            LIMIT %s
        """, params + [limit])

        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows
    except Exception as e:
        logger.warning(f"get_relevant_conversations failed: {e}")
        return []
    finally:
        self._put_conn(conn)
```

### File 2: `outputs/dashboard.py`

In `_scan_chat_deep()`, add a new pre-fetch section after the existing ones (after "Past deep analyses" block, before the deadlines block):

```python
    # Prior Baker conversations on same topic (cross-session memory)
    try:
        store = _get_store()
        relevant_convos = store.get_relevant_conversations(req.question, limit=8, exclude_hours=1)
        if relevant_convos:
            lines = []
            for c in relevant_convos:
                date_str = c['created_at'].strftime('%Y-%m-%d %H:%M') if c.get('created_at') else ''
                q = (c.get('question') or '')[:200]
                a = (c.get('answer') or '')[:1000]
                lines.append(f"**[{date_str}] Director asked:** {q}\n**Baker answered:** {a}")
            pre_parts.append("## PRIOR BAKER CONVERSATIONS ON THIS TOPIC\n" +
                           "\n\n---\n\n".join(lines))
    except Exception:
        pass
```

The `exclude_hours=1` ensures we don't duplicate the current session's turns (which are already in the message history).

## What This Gets Us

| Before | After |
|--------|-------|
| "What about Cupial escrow?" → Baker searches from scratch | Baker retrieves the Mar 5 Cupial discussion and builds on it |
| Each session starts cold | Baker remembers what was discussed in prior sessions |
| "As I told you yesterday..." → Baker has no idea | Baker can reference the prior conversation |

## What This Does NOT Do (future work)

- **Semantic search over conversations** — this uses ILIKE keyword matching, not vector similarity. For most cases (proper names, project names, specific terms) ILIKE works fine. Embedding-based retrieval would be a future upgrade.
- **Session grouping** — conversations aren't tagged by session. A future enhancement could add session_id for better grouping.
- **Topic extraction** — auto-tagging conversations with topics/entities for faster retrieval.

## Testing

1. `python3 -c "import py_compile; py_compile.compile('memory/store_back.py', doraise=True)"`
2. `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"`
3. Test: Ask "what about Cupial?" — should include prior Cupial conversations in the system prompt
4. Test: Ask a brand new topic — should find no prior conversations (empty, no injection)
