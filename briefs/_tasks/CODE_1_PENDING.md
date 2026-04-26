# CODE_1_PENDING — B1: VIP_BACKFILL_1 — 2026-04-26

**Dispatcher:** AI Head B (Build-reviewer, RA-19 Tier B handoff item 6)
**Working dir:** `~/bm-b1`
**Branch:** N/A — data-only, no PR. Stay on main.
**Brief:** `briefs/BRIEF_VIP_BACKFILL_1.md`
**Status:** OPEN
**Type:** Data-only (Baker MCP writes) — NO code changes, NO PR
**Reviewer:** AI Head B (this dispatcher)

---

## §2 pre-dispatch busy-check (per `_ops/processes/b-code-dispatch-coordination.md`)

- **Mailbox prior:** `COMPLETE — PR #63 HAGENAUER_WIKI_BOOTSTRAP_1 merged d48dac8` (set 2026-04-26 by AI Head B). Idle ✓
- **Branch state:** main; pull latest before starting (`git checkout main && git pull -q`).
- **Other B-codes:** B2 → WIKI_LINT_1 in flight (no overlap). B3 → HOLD. B5 → CHANDA_PLAIN_ENGLISH_REWRITE_1.
- **Redundancy check (lesson #47):** VIP_BACKFILL_1 specific row INSERTs verified absent in `vip_contacts` via MCP query 2026-04-26. Not redundant with shipped feature.

**Dispatch authorisation:** Director ratified 2026-04-26 "the rest agreed" via RA-19 Tier B handoff item 6.

---

## Brief-route note (charter §6A)

**Data-only brief** — no code, no PR, no merge. Differs from typical B-code dispatches.

Work product = Baker MCP `baker_raw_write` SQL writes + smoke-test SELECT verification + brief-back ship report. No `pytest`, no `git diff`, no PR.

---

## Action (5 steps)

1. **Read** `briefs/BRIEF_VIP_BACKFILL_1.md` end-to-end. §3 has full row spec.

2. **Email lookups** for 3 rows where email is "(lookup)":
   ```sql
   SELECT DISTINCT sender_name, sender_email FROM email_messages
     WHERE sender_name ILIKE '%wertheimer%' OR sender_name ILIKE '%soulier%' OR sender_name ILIKE '%russo%'
     ORDER BY sender_name LIMIT 10;
   ```
   Use confirmed `sender_email` if returned. If not, leave email NULL in INSERT and flag in ship report.

3. **INSERT 9 rows** per brief §3.1. Use `mcp__baker__baker_raw_write`. Each INSERT needs `name`, `role`, `contact_type`, `tier`, `role_context`. Optional: `email`. For **Hassa**: also `cadence_tracking = false`.

4. **UPDATE 2 rows** per brief §3.2 — Steininger entries (id 1391 + 1501): `contact_type = 'principal'`, `tier = 2`, `role_context` updated.

5. **Verify** all writes via the SELECT block in brief §6. Capture **literal output** of all SELECTs into ship report.

## Ship gate (literal output required)

```sql
-- Pre-flight
SELECT COUNT(*) FROM vip_contacts;
SELECT id, name, contact_type, tier FROM vip_contacts WHERE id IN (1391, 1501);

-- Post-execution
SELECT id, name, email, role, contact_type, tier FROM vip_contacts
  WHERE name ILIKE '%wertheimer%' OR name ILIKE '%bonnewitz%'
     OR name ILIKE '%soulier%' OR email LIKE '%mohg.com%'
     OR name = 'Andrea Russo' OR name = 'Michal Hassa'
  ORDER BY name;

SELECT id, name, contact_type, tier, role_context FROM vip_contacts
  WHERE id IN (1391, 1501);

SELECT id, name, role_context, cadence_tracking FROM vip_contacts
  WHERE name = 'Michal Hassa';
```

**No "by inspection"** (per `feedback_no_ship_by_inspection.md`).

## Ship-report shape

- **Path:** `briefs/_reports/B1_vip_backfill_1_20260426.md`
- **Contents:** all SELECT outputs above (literal); list of email lookups that failed; any INSERT/UPDATE errors; explicit cadence_tracking=false confirmation for Hassa row.
- **Commit:** SINGLE commit on main (no PR). Message: `report(B1): VIP_BACKFILL_1 ship report — 9 INSERTs + 2 UPDATEs`. Co-Authored-By tag.

## Mailbox hygiene (§3)

After ship-report committed, overwrite this file:

```
COMPLETE — VIP_BACKFILL_1 data writes executed 2026-04-26 by B1. Ship report at briefs/_reports/B1_vip_backfill_1_20260426.md.
```

## Timebox

**30–45 min.** Pure Baker MCP work. If >1h, stop and report.

## Out of scope (explicit)

- **NO** schema changes (no DDL).
- **NO** UBS row (Director deferred — see brief §3.3).
- **NO** code changes anywhere.
- **NO** PR creation.
- **NO** wiki/baker-vault writes (already shipped commits `f2bcf92` + `0dd74a5`).

---

**Dispatch timestamp:** 2026-04-26 ~06:15 UTC.
**Authority chain:** Director ratification → RA-19 handoff → AI Head B brief draft + dispatch → B1 execution.
