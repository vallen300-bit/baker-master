# BRIEF_VIP_BACKFILL_1 — VIP Contacts Backfill Pass

**Date:** 2026-04-26
**Author:** AI Head Build-reviewer
**Source:** RA-19 Tier B handoff item 6 (Director-ratified 2026-04-26 "the rest agreed")
**Type:** Data-only (Baker MCP writes) — no code changes
**Tier dispatch:** B-code (B1 / B5 — pick whichever idle)

---

## 1. Bottom-line

Backfill 9 missing VIPs in `vip_contacts` table. Update 2 existing Steininger rows from connector tier 3 → counterparty tier. No schema changes; no DDL. All writes are INSERT or UPDATE on existing schema.

Director quote: *"the rest agreed"* (2026-04-26 Sun late afternoon, via RA-19 handoff). UBS gap explicitly deferred — Director may surface separately.

## 2. Why now

- Block 2 Cat 3 (VIPs / counterparties) closed today. Coverage gap surfaced: 4 counterparties missing entirely, MOHG ops layer (T2) missing, Andrea Russo new T1 needed, Hassa needs counterparty-closed flag.
- People.yml v3 and org-chart §6 reflect the human-side closure; vip_contacts is the operational tier (cadence tracking, sentiment, contact ops). Drift between people.yml and vip_contacts is real today; this brief closes one of the gaps.
- No upstream/downstream dependency. Independent of M1 wiki stream.

## 3. Scope

### 3.1 New rows to insert (9)

| # | Name | Email (best known) | Role | contact_type | tier | Notes |
|---|---|---|---|---|---|---|
| 1 | Andrey Wertheimer | (lookup) | Wertheimer SFO — Chanel family-office LP opportunity | principal | 1 | Counterparty for `wertheimer` matter |
| 2 | Antje Bonnewitz | a.bonnewitz@aukera.ag | Aukera fund/GP contact — KYC + loan terms | partner | 1 | Counterparty for `aukera` matter; senior lender on MOVIE + Annaberg/Lilienmatt/MRCI |
| 3 | Philippe Soulier | (lookup) | Bora Bora Mandarin partner — local-expert coordination | partner | 1 | Counterparty for `philippe-soulier` slug |
| 4 | Anna Egger | aegger@mohg.com | MOHG Vienna ops | operator | 2 | MOVIE asset operator side |
| 5 | Katja Graf | kgraf@mohg.com | MOHG Vienna ops | operator | 2 | MOVIE asset operator side |
| 6 | Christoph Schauer | cschauer@mohg.com | MOHG Vienna ops | operator | 2 | MOVIE asset operator side |
| 7 | Andrea Russo | (lookup) | Tax Specialist, Geneva | advisor | 1 | Internal Brisen team (replaces edita-russo composite) |
| 8 | Michal Hassa | michal.hassa@tfkable.com | Cupial counterparty counsel — TFKable | lawyer | 2 | **counterparty-closed** flag (Cupial dispute ended 2026-04-26); historical only |
| 9 | Steininger entry — see §3.2 (UPDATE existing) | | | | | |

### 3.2 Updates to existing rows

| id | Current state | Target state | Reason |
|---|---|---|---|
| 1501 (Michael Steininger) | contact_type=connector, tier=3 | contact_type=principal, tier=2, role_context updated to "Steininger family — counterparty in Kitzbühel Six Senses dispute" | Counterparty alignment with `steininger` matter slug |
| 1391 (Walther Steininger) | contact_type=connector, tier=3 | contact_type=principal, tier=2, role_context updated to "Steininger family — counterparty in Kitzbühel Six Senses dispute" | Same |

### 3.3 Out of scope

- **UBS gap** — deferred per Director call. May be surfaced as separate brief.
- **Schema additions** — no new columns. `counterparty-closed` for Hassa goes into `role_context` text + `cadence_tracking=false` (same pattern as Cupial row 1747 closure 2026-04-26).
- **Email sentinel re-ingestion** — none triggered.

## 4. API / endpoint

- **Tool:** Baker MCP `mcp__baker__baker_raw_write` (INSERT + UPDATE on `vip_contacts` table)
- **Alternate tool:** `mcp__baker__baker_upsert_vip` if available + suitable. Verify schema match first.
- **API version:** Baker MCP — live as of 2026-04-19 per LONGTERM.md
- **Deprecation check date:** 2026-04-26 (verified live + responding this session)
- **Fallback:** Baker HTTP API `https://baker-master.onrender.com/mcp?key=bakerbhavanga` if MCP fails. Same payload structure.

## 5. Code Brief Standards compliance

- (1-3) API version + deprecation + fallback: §4 above ✓
- (4) Migration-vs-bootstrap DDL check: N/A — no schema changes ✓
- (5) Ship gate: pytest equivalent — `mcp__baker__baker_raw_query` SELECT verifying all 9 INSERTs landed + 2 UPDATEs reflected ✓
- (6) Test plan: §6 below ✓
- (7) file:line citations: N/A ✓
- (8) Singleton pattern: N/A — no code ✓
- (9) Post-merge handoff: N/A — no merge; data-only ✓
- (10) Invocation-path audit: N/A — no capability touched ✓

## 6. Test plan

```sql
-- Pre-flight (capture baseline counts)
SELECT COUNT(*) FROM vip_contacts;
SELECT COUNT(*) FROM vip_contacts WHERE contact_type = 'principal';
SELECT id, name, contact_type, tier FROM vip_contacts WHERE id IN (1391, 1501);

-- After all writes
SELECT id, name, email, role, contact_type, tier FROM vip_contacts
  WHERE name ILIKE '%wertheimer%' OR name ILIKE '%bonnewitz%'
     OR name ILIKE '%soulier%' OR email LIKE '%mohg.com%'
     OR name = 'Andrea Russo' OR name = 'Michal Hassa'
  ORDER BY name;
-- expect 8 rows new (Wertheimer + Bonnewitz + Soulier + 3 MOHG + Russo + Hassa)

SELECT id, name, contact_type, tier, role_context FROM vip_contacts
  WHERE id IN (1391, 1501);
-- expect tier=2, contact_type=principal, role_context updated

SELECT id, name, role_context, cadence_tracking FROM vip_contacts
  WHERE name = 'Michal Hassa';
-- expect cadence_tracking=false, role_context contains "counterparty-closed"
```

## 7. Acceptance criteria

- All 9 new rows present with correct contact_type + tier per §3.1
- Both Steininger rows updated per §3.2
- Hassa row marked counterparty-closed (role_context + cadence_tracking=false)
- No regressions on existing rows (baseline count + non-target rows unchanged)
- Smoke-test SELECTs in §6 return expected results
- Brief-back report includes literal SELECT output (not "by inspection")

## 8. Email-pull lookup helpers (if email unknown)

For Wertheimer / Soulier / Russo where email is "(lookup)", run:

```sql
SELECT DISTINCT sender_name, sender_email FROM email_messages
  WHERE sender_name ILIKE '%wertheimer%' OR sender_name ILIKE '%soulier%' OR sender_name ILIKE '%russo%'
  ORDER BY sender_name LIMIT 10;
```

Use confirmed sender_email if available. If still unresolved, leave email NULL on insert and flag in brief-back report for Director follow-up.

## 9. Authority chain

- Director ratification: 2026-04-26 "the rest agreed" (RA-19 Tier B handoff item 6)
- RA proposal: RA-19 session, Block 2 Cat 3 close
- AI Head Tier B execution: brief-drafting (this file) + dispatch to B-code
- B-code execution: data writes, brief-back ship report

## 10. Ship-gate

Literal Baker MCP SELECT output reproducing §6 test plan. No "by inspection" claims. Brief-back to `briefs/_reports/BN_vip_backfill_1_20260426.md`.
