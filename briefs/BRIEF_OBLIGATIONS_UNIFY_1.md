# BRIEF: OBLIGATIONS-UNIFY-1 — Merge Commitments + Deadlines

**Status:** READY FOR REVIEW
**Author:** AI Head (Claude Code, Session 24)
**Date:** 2026-03-16
**Priority:** MEDIUM — needed for Trip Intelligence (Card 4: People) and Networking health
**Effort:** ~1 session

---

## Problem

"What's owed/promised" lives in two separate tables with different schemas:

| Table | Rows | Schema | Status values |
|-------|------|--------|---------------|
| `deadlines` | 442 (61 active) | description, due_date, priority, confidence, source_snippet, reminder_stage | active, dismissed, pending_confirm |
| `commitments` | 507 (436 open) | description, assigned_to, assigned_by, due_date, source_type, source_context, matter_slug | open, overdue, dismissed |

This creates 3 problems:
1. **Trip Card 4 (People)** needs "what's owed/promised per contact" — has to query two tables
2. **Networking tab** can't show commitment health per contact — data split across systems
3. **Dashboard** has separate Deadlines + Commitments tabs with different UX

---

## Proposed Solution: Add severity to deadlines, migrate commitments in

**Don't create a third table.** Extend `deadlines` with the missing commitment fields, then migrate commitment data in.

### New columns on `deadlines`:

```sql
ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS severity VARCHAR(10) DEFAULT 'firm';
-- hard = legal/contractual (red), firm = promised with date (amber), soft = mentioned, no date (blue)

ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS assigned_to TEXT;
ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS assigned_by TEXT;
ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS matter_slug TEXT;
ALTER TABLE deadlines ADD COLUMN IF NOT EXISTS obligation_type VARCHAR(20) DEFAULT 'deadline';
-- 'deadline' (Baker-extracted), 'commitment' (migrated from commitments table)
```

### Severity classification:

| Severity | Color | Meaning | Example |
|----------|-------|---------|---------|
| **hard** | Red | Legal, contractual, regulatory. Financial consequence if missed. | Hagenauer Gewaehrleistungsfrist expires Mar 2027 |
| **firm** | Amber | Promised with a date. Relationship damage if missed. | "Deliver valuation report by April 1" |
| **soft** | Blue | Mentioned, no specific date. Social expectation. | "We should visit the Vienna site together" |

### Migration SQL:

```sql
INSERT INTO deadlines (description, due_date, source_type, source_id, status, matter_slug,
                        assigned_to, assigned_by, severity, obligation_type, created_at)
SELECT
    c.description,
    c.due_date,
    c.source_type,
    c.source_id,
    CASE c.status
        WHEN 'open' THEN 'active'
        WHEN 'overdue' THEN 'active'
        WHEN 'dismissed' THEN 'dismissed'
        ELSE 'active'
    END,
    c.matter_slug,
    c.assigned_to,
    c.assigned_by,
    CASE
        WHEN c.due_date IS NOT NULL THEN 'firm'
        ELSE 'soft'
    END,
    'commitment',
    c.created_at
FROM commitments c
ON CONFLICT DO NOTHING;
```

### After migration:
- Rename view: `obligations` = unified view of `deadlines` table
- Dashboard: one "Obligations" tab replaces both Deadlines + Commitments
- Trip Card 4: single query `WHERE assigned_to ILIKE '%contact_name%' OR description ILIKE '%contact_name%'`
- Networking: per-contact obligation count from one table

---

## Implementation Sequence

| Step | What | Where |
|------|------|-------|
| 1 | Add columns to deadlines (ALTER TABLE, idempotent) | store_back.py |
| 2 | Classify existing deadlines with severity (Haiku batch or rules) | One-time SQL |
| 3 | Migrate commitments → deadlines | One-time SQL |
| 4 | Update Dashboard Deadlines tab to show severity badges | app.js |
| 5 | Update Trip Card 4 queries to use unified table | dashboard.py |
| 6 | Deprecate commitments table (don't delete, just stop writing) | store_back.py, pipeline |
| 7 | Optional: rename Deadlines tab → Obligations | index.html |

---

## What This Unlocks

- **Trip Card 4 (People):** "You promised AO a tour" + "AO owes updated valuation" — one query
- **Networking health:** obligation count per contact
- **Simpler dashboard:** one tab instead of two
- **Severity-based prioritization:** hard deadlines get red treatment, soft commitments get blue

---

## Risk

**Low.** Additive schema changes (ALTER TABLE ADD COLUMN). Migration is idempotent (ON CONFLICT DO NOTHING). Commitments table stays as-is (read fallback) until we're confident the unified view works. No LLM cost.

---

## Data volumes

- 61 active deadlines + 436 open commitments = ~497 active obligations
- 28 overdue commitments need immediate triage (many are likely stale)
