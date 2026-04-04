# BRIEF: LANDING-FIX-4 — Dedup Regex Hotfix + Meeting Alert Filter

## Context
Post-deploy verification of Briefs 1-3 found two remaining issues: (1) the Promised To Do dedup regex only strips one leading bracket group, so `[BAKER/Handoff Notes] [russo_ai]` pairs aren't merged; (2) the Meetings card shows non-meeting alerts like "Fireflies Transcript Access" and "Granola AI Privacy Vulnerabilities" because the query is too broad (any alert tagged `meeting`).

## Estimated time: ~15min
## Complexity: Low
## Prerequisites: Briefs 1-3 deployed

---

## Fix 1: Dedup regex — strip ALL leading brackets + fuzzy match

### Problem
Promised To Do shows 14 raw items, DISTINCT ON only eliminates 4 → still 10 shown. Two bugs:
- Regex `^\[.*?\]\s*(\[.*?\]\s*)*` only strips one bracket group. `[BAKER/Handoff Notes] [russo_ai] Obtain...` normalizes to ` [russo_ai] obtain...` (leading space + second bracket remains).
- Even with correct stripping, ID 1332 (`...tax analysis document`) and ID 1331 (`...tax analysis document - retrieve and review...`) have different suffixes. Need fuzzy match via LEFT truncation.

### Current State
`outputs/dashboard.py` lines 2185-2201.

### Implementation
Two find-replace operations in `outputs/dashboard.py`:

**Find (line 2185-2187):**
```python
                SELECT DISTINCT ON (
                    REGEXP_REPLACE(LOWER(description), '^\[.*?\]\s*(\[.*?\]\s*)*', '')
                )
```

**Replace with:**
```python
                SELECT DISTINCT ON (
                    LEFT(REGEXP_REPLACE(LOWER(description), '^(\[.*?\]\s*)+', ''), 45)
                )
```

**Find (line 2199):**
```python
                ORDER BY REGEXP_REPLACE(LOWER(description), '^\[.*?\]\s*(\[.*?\]\s*)*', ''),
```

**Replace with:**
```python
                ORDER BY LEFT(REGEXP_REPLACE(LOWER(description), '^(\[.*?\]\s*)+', ''), 45),
```

### Why this works
- `^(\[.*?\]\s*)+` with the `+` quantifier strips ALL leading `[bracket]` groups in one pass
- `LEFT(..., 45)` truncates to first 45 chars after stripping — merges descriptions that share the same prefix but one has extra detail appended (e.g., `obtain complete ebner stolz tax analysis document` vs `obtain complete ebner stolz tax analysis document - retrieve and review...`)
- `LENGTH(source_snippet) DESC` still picks the row with richer context

### Verification
```sql
-- Should return 10 rows (down from 14 raw), with IDs 1332/1336 eliminated:
SELECT DISTINCT ON (
    LEFT(REGEXP_REPLACE(LOWER(description), '^(\[.*?\]\s*)+', ''), 45)
)
    id, LEFT(description, 60) as desc_short
FROM deadlines
WHERE status = 'active'
  AND (is_critical IS NOT TRUE)
  AND due_date >= CURRENT_DATE
  AND due_date <= CURRENT_DATE + INTERVAL '7 days'
  AND NOT (description ILIKE '%flight%' OR description ILIKE '%departure%'
           OR description ILIKE '%travel%' OR description ILIKE '%airport%'
           OR description ILIKE '%boarding%' OR description ILIKE '%check-in%')
ORDER BY LEFT(REGEXP_REPLACE(LOWER(description), '^(\[.*?\]\s*)+', ''), 45),
         LENGTH(COALESCE(source_snippet, '')) DESC,
         priority DESC, created_at DESC
LIMIT 10;
```

---

## Fix 2: Tighten meeting_alerts query — title must mention "meeting"

### Problem
Meetings card shows 5 items including "Critical: Fireflies Meeting Transcript Access Still Not Live" and "Granola AI Note-Taking App: Critical Privacy Vulnerabilities". These are operational alerts that happen to have a `meeting` tag, not actual meetings.

### Current State
`outputs/dashboard.py` lines 2311-2319:
```python
            # LANDING-FIX-3: Meeting alerts for Meetings card
            try:
                cur.execute("""
                    SELECT id, title, body, tags, created_at
                    FROM alerts
                    WHERE status = 'pending'
                      AND tags ? 'meeting'
                      AND created_at >= NOW() - INTERVAL '48 hours'
                    ORDER BY created_at DESC
```

### Implementation
**Find:**
```python
                    SELECT id, title, body, tags, created_at
                    FROM alerts
                    WHERE status = 'pending'
                      AND tags ? 'meeting'
                      AND created_at >= NOW() - INTERVAL '48 hours'
                    ORDER BY created_at DESC
```

**Replace with:**
```python
                    SELECT id, title, body, tags, created_at
                    FROM alerts
                    WHERE status = 'pending'
                      AND tags ? 'meeting'
                      AND title ILIKE '%%meeting%%'
                      AND created_at >= NOW() - INTERVAL '48 hours'
                    ORDER BY created_at DESC
```

### Why this works
Requires both the `meeting` tag AND the word "meeting" in the title. This filters out alerts that are tagged `meeting` for context but aren't about actual meetings (e.g., "Granola AI Privacy Vulnerabilities" has the meeting tag because it was discussed in a meeting, but isn't a meeting itself).

### Verification
```sql
-- Should return only actual meeting alerts:
SELECT id, title FROM alerts
WHERE status = 'pending'
  AND tags ? 'meeting'
  AND title ILIKE '%meeting%'
  AND created_at >= NOW() - INTERVAL '48 hours'
ORDER BY created_at DESC LIMIT 5;
```

---

## Files Modified
- `outputs/dashboard.py` — 2 changes (dedup regex + meeting query filter)

## Do NOT Touch
- `outputs/static/app.js` — no frontend changes
- `outputs/static/index.html` — no cache bust needed (backend-only changes)

## Quality Checkpoints
1. Promised To Do count drops from current level (duplicates merged)
2. Meetings card shows only actual meetings (Oskolkov, Vienna April 7, etc.)
3. No "Fireflies" or "Granola" in Meetings card
4. Python syntax check passes
5. No errors in Render logs
