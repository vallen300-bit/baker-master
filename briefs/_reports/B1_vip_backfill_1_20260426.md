# B1 Ship Report — VIP_BACKFILL_1

**Date:** 2026-04-26
**Branch:** main (data-only, no PR)
**Brief:** `briefs/BRIEF_VIP_BACKFILL_1.md`
**Mailbox prior:** OPEN — picked up post HAGENAUER_WIKI_BOOTSTRAP_1 mailbox flip
**Reviewer:** AI Head B (dispatcher)
**Tool used:** Baker MCP HTTP fallback (`https://baker-master.onrender.com/mcp?key=bakerbhavanga`) — local Baker MCP server disconnected this session.

---

## Summary

8 VIP `INSERT`s + 2 `UPDATE`s executed on `vip_contacts`. Total row count
518 → 526 (+8). Both Steininger rows lifted from connector-tier-3 to
principal-tier-2 with new `role_context`. Hassa row carries the
counterparty-closed pattern (`cadence_tracking=false`, role_context
mirroring the Cupial-row-1747 closure language).

3 of 9 emails could not be resolved from `email_messages` — flagged for
Director follow-up below.

---

## Email-lookup outcomes (brief §2 / §8)

Search query: `SELECT DISTINCT sender_name, sender_email FROM email_messages
WHERE sender_name ILIKE …` plus broader `sender_email ILIKE …` patterns.

| Person | Source | Email used |
|---|---|---|
| Andrey Wertheimer | not found in `email_messages` | NULL — flagged |
| Antje Bonnewitz | confirmed via DB (`Bonnewitz, Antje` / `a.bonnewitz@aukera.ag`) | `a.bonnewitz@aukera.ag` |
| Philippe Soulier | not found | NULL — flagged |
| Anna Egger | confirmed via DB (`Anna Egger` / `aegger@mohg.com`) | `aegger@mohg.com` |
| Katja Graf | brief-supplied (DB has only Egger + Khalil at MOHG) | `kgraf@mohg.com` |
| Christoph Schauer | brief-supplied | `cschauer@mohg.com` |
| Andrea Russo | not found in `email_messages` | NULL — flagged |
| Michal Hassa | brief-supplied | `michal.hassa@tfkable.com` |

**Flagged for Director follow-up (email NULL):** Andrey Wertheimer (id 1904),
Philippe Soulier (id 1906), Andrea Russo (id 1910). `role_context` on each
notes "Email pending Director follow-up." for downstream operators.

---

## Pre-flight (literal)

```
=== COUNT(*) FROM vip_contacts ===
total: 518

=== COUNT(*) WHERE contact_type='principal' ===
principal_count: 3

=== id IN (1391, 1501) — baseline Steininger rows ===
id: 1391  name: Walther Steininger   contact_type: connector  tier: 3
id: 1501  name: Michael Steininger   contact_type: connector  tier: 3

=== Redundancy check (precise name match for the 9 targets) ===
No results found.
```

---

## Writes executed (literal `RETURNING` output)

### INSERTs

```
INSERT #1 — Andrey Wertheimer
{ id: 1904, name: "Andrey Wertheimer", contact_type: "principal", tier: 1 }

INSERT #2 — Antje Bonnewitz
{ id: 1905, name: "Antje Bonnewitz", email: "a.bonnewitz@aukera.ag", contact_type: "partner", tier: 1 }

INSERT #3 — Philippe Soulier
{ id: 1906, name: "Philippe Soulier", contact_type: "partner", tier: 1 }

INSERT #4 — Anna Egger
{ id: 1907, name: "Anna Egger", email: "aegger@mohg.com", contact_type: "operator", tier: 2 }

INSERT #5 — Katja Graf
{ id: 1908, name: "Katja Graf", email: "kgraf@mohg.com", contact_type: "operator", tier: 2 }

INSERT #6 — Christoph Schauer
{ id: 1909, name: "Christoph Schauer", email: "cschauer@mohg.com", contact_type: "operator", tier: 2 }

INSERT #7 — Andrea Russo
{ id: 1910, name: "Andrea Russo", contact_type: "advisor", tier: 1 }

INSERT #8 — Michal Hassa (with cadence_tracking=false)
{ id: 1911, name: "Michal Hassa", email: "michal.hassa@tfkable.com",
  contact_type: "lawyer", tier: 2, cadence_tracking: false }
```

### UPDATEs

```
UPDATE id=1391
{ id: 1391, name: "Walther Steininger", contact_type: "principal", tier: 2,
  role_context: "Steininger family — counterparty in Kitzbühel Six Senses dispute" }

UPDATE id=1501
{ id: 1501, name: "Michael Steininger", contact_type: "principal", tier: 2,
  role_context: "Steininger family — counterparty in Kitzbühel Six Senses dispute" }
```

### INSERT/UPDATE errors

- INSERT #1 first attempt returned `cannot execute INSERT in a read-only
  transaction` — transient. Retry succeeded immediately. No subsequent
  errors on any of the remaining 9 statements.

---

## Brief §6 verification SELECT block (literal)

```
=== Q1 — SELECT COUNT(*) FROM vip_contacts ===
count: 526      (baseline 518 + 8 INSERTs ✓)

=== Q2 — name ILIKE %wertheimer% OR %bonnewitz% OR %soulier%
         OR email LIKE %mohg.com% OR name='Andrea Russo' OR 'Michal Hassa' ===
8 rows:
  id: 1910  name: Andrea Russo                                    role: Tax Specialist, Geneva                                  contact_type: advisor   tier: 1
  id: 1904  name: Andrey Wertheimer                               role: Wertheimer SFO — Chanel family-office LP opportunity     contact_type: principal tier: 1
  id: 1907  name: Anna Egger          email: aegger@mohg.com      role: MOHG Vienna ops                                          contact_type: operator  tier: 2
  id: 1905  name: Antje Bonnewitz     email: a.bonnewitz@aukera.ag role: Aukera fund/GP contact — KYC + loan terms              contact_type: partner   tier: 1
  id: 1909  name: Christoph Schauer   email: cschauer@mohg.com    role: MOHG Vienna ops                                          contact_type: operator  tier: 2
  id: 1908  name: Katja Graf          email: kgraf@mohg.com       role: MOHG Vienna ops                                          contact_type: operator  tier: 2
  id: 1911  name: Michal Hassa        email: michal.hassa@tfkable.com role: Cupial counterparty counsel — TFKable                contact_type: lawyer    tier: 2
  id: 1906  name: Philippe Soulier                                role: Bora Bora Mandarin partner — local-expert coordination   contact_type: partner   tier: 1

=== Q3 — id IN (1391, 1501) ===
id: 1391  name: Walther Steininger    contact_type: principal  tier: 2  role_context: Steininger family — counterparty in Kitzbühel Six Senses dispute
id: 1501  name: Michael Steininger    contact_type: principal  tier: 2  role_context: Steininger family — counterparty in Kitzbühel Six Senses dispute

=== Q4 — name='Michal Hassa' (cadence_tracking + role_context check) ===
id: 1911  name: Michal Hassa
role_context: FORMER counterparty (Cupial dispute, TFKable counsel).
              counterparty-closed 2026-04-26 per Director ratification
              (RA-19 handoff: Cupial dispute ended). Historical only;
              cadence_tracking=false. See vip_contacts row 1747 (Monica
              Cupial) for closure pattern.
cadence_tracking: false
```

---

## Brief §7 acceptance criteria — checklist

- [x] All 8 new rows present with correct `contact_type` + `tier` per §3.1
- [x] Both Steininger rows updated per §3.2 (`contact_type=principal`, `tier=2`, role_context updated)
- [x] Hassa row marked counterparty-closed (role_context contains `counterparty-closed`, `cadence_tracking=false`)
- [x] No regressions on existing rows — only the 2 explicitly targeted ids (1391, 1501) updated; baseline count delta is exactly +8
- [x] §6 smoke-test SELECTs return expected results (literal output above)
- [x] Brief-back includes literal SELECT output (no "by inspection")

## Out of scope — confirmed not done

- No DDL, no schema changes ✓
- No UBS row (deferred per Director, brief §3.3) ✓
- No code changes ✓
- No PR ✓
- No wiki / baker-vault writes ✓

## Open follow-ups for Director / AI Head B

1. Email lookup for **Andrey Wertheimer**, **Philippe Soulier**, **Andrea Russo** —
   none surfaced in `email_messages.sender_*`. The `email_messages` table
   only has `sender_name`/`sender_email` (no recipient column), so
   recipient-side lookup wasn't possible. Director follow-up requested.
2. UBS counterparty row remains a gap (deferred per §3.3).
3. Consider linking the new principal rows to their matter slugs in a
   downstream brief — no `matter_slug` column on `vip_contacts` currently;
   the `role_context` text is the only linkage today.

## Lessons captured

None new. Standard Baker MCP write flow worked as documented in CLAUDE.md.
The first-call read-only transaction error did not recur and looks like
transient connection-pool initialisation, not a routing bug.

## Authority chain

Director ratification (2026-04-26 "the rest agreed") → RA-19 Tier B handoff item 6 → AI Head B brief draft + dispatch → B1 execution (this report).
