# Brief: CONTACTS-RENAME-1 — Rename vip_contacts → contacts

**Author:** AI Head (Session 21)
**For:** Code 300
**Priority:** LOW — cosmetic, but removes "VIP" language that contradicts the all-equal contact model

---

## Problem

The `vip_contacts` table name implies gatekeeping — a tier system where some contacts are VIPs and others aren't. Session 19-20 established the opposite: all people are equal, no VIP gatekeeping. The UI already says "Contacts" (Session 20 renamed it), but the DB table and all code references still say `vip_contacts`.

128 occurrences across 36 files (13 Python files + briefs/docs).

## Approach: DB View + Gradual Code Migration

**Do NOT rename the table directly.** That would break all 13 Python files at once and require a perfectly coordinated deploy. Instead:

### Step 1: Create a view (zero risk)

```sql
CREATE OR REPLACE VIEW contacts AS SELECT * FROM vip_contacts;
```

This means both `vip_contacts` and `contacts` work in queries. Old code keeps working. New code can use `contacts`.

### Step 2: Update Python files (one at a time)

Replace `vip_contacts` with `contacts` in these 13 files. Each file can be updated independently since the view makes both names valid:

| File | Occurrences | Risk |
|------|-------------|------|
| `memory/store_back.py` | 23 | Medium — most queries live here |
| `outputs/dashboard.py` | 10 | Medium — API endpoints |
| `orchestrator/agent.py` | 1 | Low |
| `orchestrator/decision_engine.py` | 3 | Low |
| `orchestrator/action_handler.py` | 6 | Low |
| `orchestrator/scan_prompt.py` | 1 | Low |
| `orchestrator/deadline_manager.py` | 2 | Low |
| `memory/retriever.py` | 2 | Low |
| `triggers/waha_webhook.py` | 2 | Low |
| `triggers/email_trigger.py` | 2 | Low |
| `triggers/calendar_trigger.py` | 1 | Low |
| `scripts/backfill_wa_contacts.py` | 4 | Low — script only |
| `models/deadlines.py` | 15 | Low — data models |

### Step 3: Update MCP server

The Baker MCP server (outside this repo, in Dropbox) has tools like `baker_vip_contacts` and `baker_upsert_vip`. These should be renamed to `baker_contacts` and `baker_upsert_contact`. Since Cowork and Claude Code use these tool names, this is a coordinated change — update MCP server + inform both consumers.

**Defer this step.** MCP tool names are API contracts — rename after all Python code is migrated and stable.

### Step 4: Rename actual table (final step, after everything works on the view)

```sql
ALTER TABLE vip_contacts RENAME TO contacts;
DROP VIEW IF EXISTS contacts;  -- view name now conflicts, but table takes precedence
```

**Only do this after Step 2 is complete and deployed.** The view ensures zero-downtime migration.

## Files to Modify

**Step 1 (this session):**

| File | Change |
|------|--------|
| `memory/store_back.py` | Add `CREATE OR REPLACE VIEW contacts AS SELECT * FROM vip_contacts` to ensure_tables |

**Step 2 (this session or next):**

All 13 Python files listed above — find/replace `vip_contacts` → `contacts` in SQL strings. Do NOT rename Python variable names (e.g., `vip_contact_id`) — only SQL table references.

## Verification

1. After Step 1: `SELECT * FROM contacts LIMIT 1` works
2. After Step 2: All endpoints still work, no 500 errors
3. Both `vip_contacts` and `contacts` return the same data
4. grep confirms zero remaining `vip_contacts` in Python SQL strings

## What NOT to Do

- Do NOT rename Python variables/function names (e.g., `_ensure_vip_contacts_table`, `upsert_vip`) — that's a separate refactor
- Do NOT rename MCP tools yet — API contract change needs coordination
- Do NOT drop the original table until Step 2 is fully deployed and verified
