# BRIEF: Alert Deduplication & Auto-Dismiss (ALERT-DEDUP-2)

**Author:** AI Head (Claude Code, Session 36)
**Date:** 2026-03-25
**Status:** Ready for Code Brisen
**Priority:** High — daily UX noise

## Problem

The Mac dashboard shows the same topic multiple times in the Actions/upcoming section. Examples:
- "Polish translation of documents" appears as a completed action AND as older pending alerts below
- "Engage in negotiations on Mandarin fee structure" appears several times

**Root cause:** Baker creates a new alert every time it processes a new email/trigger about the same topic. No dedup. No auto-dismiss when the Director acts.

## Fix — Two Parts

### Part 1: Auto-Dismiss Related Alerts on Action

When the Director acts on an alert (sends email, dismisses, completes), dismiss all other pending alerts about the same topic.

**File:** `orchestrator/action_handler.py`

**Logic:**
```python
def _dismiss_related_alerts(alert_id: int, conn):
    """After acting on an alert, dismiss older alerts about the same topic."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get the acted-on alert's matter_slug and title keywords
    cur.execute("SELECT matter_slug, title, source FROM alerts WHERE id = %s", (alert_id,))
    alert = cur.fetchone()
    if not alert:
        return

    # Strategy 1: Same matter_slug → dismiss all older pending
    if alert['matter_slug']:
        cur.execute("""
            UPDATE alerts SET status = 'dismissed'
            WHERE matter_slug = %s AND status = 'pending' AND id != %s
        """, (alert['matter_slug'], alert_id))

    # Strategy 2: Similar title (first 5 significant words match) → dismiss
    # Extract key words from title, find alerts with same keywords
    title_words = [w.lower() for w in (alert['title'] or '').split()
                   if len(w) > 3 and w.lower() not in ('the', 'this', 'that', 'from', 'with', 'about')][:5]
    if len(title_words) >= 3:
        pattern = '%' + '%'.join(title_words[:3]) + '%'
        cur.execute("""
            UPDATE alerts SET status = 'dismissed'
            WHERE status = 'pending' AND id != %s
              AND LOWER(title) LIKE %s
        """, (alert_id, pattern))

    conn.commit()
```

**Where to call it:**
1. `handle_email_action()` — after successful send or draft save
2. `/api/alerts/{id}/dismiss` endpoint — when Director dismisses manually
3. `/api/alerts/{id}/resolve` endpoint — when Director resolves

### Part 2: Dedup on Alert Creation

Before creating a new alert, check if a similar pending alert already exists. If yes, update it instead of creating a duplicate.

**File:** `memory/store_back.py` → `create_alert()`

**Logic:**
```python
# At the start of create_alert(), before INSERT:

# Check for existing pending alert with same source_id (exact dedup)
if source_id:
    cur.execute("""
        SELECT id FROM alerts WHERE source_id = %s AND status = 'pending'
    """, (source_id,))
    existing = cur.fetchone()
    if existing:
        # Update existing instead of creating new
        cur.execute("""
            UPDATE alerts SET body = %s, updated_at = NOW()
            WHERE id = %s
        """, (body, existing['id']))
        return existing['id']

# Check for existing pending alert with same matter + similar title
if matter_slug:
    cur.execute("""
        SELECT id, title FROM alerts
        WHERE matter_slug = %s AND status = 'pending'
          AND created_at > NOW() - INTERVAL '7 days'
        ORDER BY created_at DESC LIMIT 1
    """, (matter_slug,))
    existing = cur.fetchone()
    if existing and _titles_similar(existing['title'], title):
        # Update existing
        cur.execute("""
            UPDATE alerts SET body = %s, updated_at = NOW(), tier = LEAST(tier, %s)
            WHERE id = %s
        """, (body, tier, existing['id']))
        return existing['id']
```

**Helper function:**
```python
def _titles_similar(t1: str, t2: str, threshold: int = 3) -> bool:
    """Check if two alert titles are about the same topic."""
    words1 = set(w.lower() for w in (t1 or '').split() if len(w) > 3)
    words2 = set(w.lower() for w in (t2 or '').split() if len(w) > 3)
    overlap = len(words1 & words2)
    return overlap >= threshold
```

## Files to Modify

| File | Changes |
|------|---------|
| `memory/store_back.py` | Add dedup check at top of `create_alert()` |
| `orchestrator/action_handler.py` | Add `_dismiss_related_alerts()`, call after email send/draft |
| `outputs/dashboard.py` | Call dismiss in `/api/alerts/{id}/dismiss` and `/api/alerts/{id}/resolve` |

## Testing

1. Create two alerts with same matter_slug → only one should appear
2. Act on an alert (send email) → related alerts should auto-dismiss
3. Manually dismiss → related alerts should also dismiss
4. Different topics should NOT be affected (no false positives)

## Edge Cases

- Don't dismiss alerts with `action_required=true` and `source='browser_transaction'` — those need explicit confirmation
- Don't dismiss alerts from different sources (e.g., email alert vs WhatsApp alert about same topic) — they may need separate handling. Actually DO dismiss them — Director doesn't want to see the same topic twice regardless of source.
- `source_id` dedup is exact match — always safe. Title similarity dedup needs the 3-word threshold to avoid false positives.

## Estimated Effort

- Part 1 (auto-dismiss): ~1.5 hours
- Part 2 (dedup on creation): ~1.5 hours
- Testing: ~30 min
- **Total: ~3.5 hours**

## Success Criteria

- Zero duplicate topics visible on the dashboard
- Acting on one alert clears all related alerts
- No false positives (unrelated alerts not dismissed)
