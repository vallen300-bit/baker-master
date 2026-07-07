# DATA_OPS_AO_PLAUD_BACKFILL_WA_NOISE_1

dispatched_by: lead
assignee: b2 (fresh seat)
task_class: data-ops (prod DB row updates + ticket disposal + 2 verify-and-report items)
priority: P2
Harness-V2: compact — data-ops, no code paths changed; done rubric = Acceptance criteria below; gate plan = self-verify SQL + lead review of report (no codex gate needed at this risk tier)

## Context

Two desk asks queued on the bus (lead inbox #6074 ao-desk, #6079 baden-baden-desk). Both are
prod-data hygiene: Plaud transcripts landing with NULL/wrong `matter_slug` in `meeting_transcripts`,
plus a stale WhatsApp identity-backfill batch spamming tickets on flight `aukera-annaberg-financing`.
No code changes in this brief — row updates, ticket disposal, and two verify-and-report items.
Root cause of the WA noise (720h ingest lookback) is ALREADY OWNED by b1's deferred C5 follow-up
(branch `b1/baker-os-v2-c5-nonmail-signals`, LOOKBACK_HOURS 720→168 revert) — do NOT touch lookback config.

## Problem

1. AO Plaud transcripts land `matter_slug=NULL` → `GET /api/transcripts/by-matter/ao` returns 0; desk blind.
2. One 22-Jun Annaberg-strategy Plaud transcript mis-slugged `hagenauer-rg7`.
3. ~35 stale WA tickets (participant-identity fetch, msgs dated 2026-06-07/08, `why_ticketed: "no keyword match"`) drip-feeding nudges onto `aukera-annaberg-financing`; mostly acks (Ок/Yes/👍) or other-lane content.
4. `meeting_transcripts` has no Plaud-folder column — Director organizes by folder; classifier can't map folder→matter_slug (report-only here).

## Tasks

1. Backfill `matter_slug='ao'` on 4 Plaud rows in `meeting_transcripts`:
   - `plaud_58683bca66d14600f366adf42e59d3fb` (07-06 KYC/source-of-funds)
   - `plaud_5ff5b48840c65e8fb949a73010ae3d92` (07-06 investment strategy)
   - Two 06-25 AO rows currently NULL, id prefixes `plaud_da19b53f` + `plaud_8709887b` — locate by prefix, confirm content is AO before update.
   - Canonical slug is `ao` (verify against `baker-vault/slugs.yml` via `kbl/slug_registry.py`; `oskolkov` is an alias, endpoint 404s it).
2. Fix the 22-Jun Annaberg-strategy Plaud row: `matter_slug` `hagenauer-rg7` → correct canonical Annaberg slug per `slugs.yml` (verify, don't guess). Locate by meeting_date 2026-06-22 + current slug `hagenauer-rg7` + Annaberg content.
3. Bulk-dispose the stale WA ticket batch on `aukera-annaberg-financing`: tickets whose source WA messages are dated 2026-06-07/08 AND `why_ticketed` = identity-only ("no keyword match"). Dispose/close, do NOT delete underlying messages. Preserve the genuine on-flight items the desk flagged (Brandner URGENT x2, Balazs ESG-Q&A, Balazs subdivision-review, 22-Jun Plaud).
4. VERIFY + REPORT: does the ticketing bridge route WRONG_TERMINAL check-ins (MO-VIE / nVIDIA items) to MOVIE Desk? Trace one example; report actual behavior.
5. REPORT: P2 brief candidate for folder→matter_slug map at Plaud ingest (classifier gap — same theme as items 1+2). One paragraph: where the classifier writes matter_slug, where folder metadata is available/lost, proposed insertion point. Do NOT build.

## Files Modified

None (data-ops only). Prod DB row updates on `meeting_transcripts` + ticket table disposal. All writes go through normal audited paths; use psql against DATABASE_URL (Render env / 1Password per standard b2 data-ops pattern).

## Verification

```sql
-- Task 1: expect 4 rows, all matter_slug='ao'
SELECT id, meeting_date, matter_slug FROM meeting_transcripts
 WHERE id LIKE 'plaud_58683bca%' OR id LIKE 'plaud_5ff5b488%'
    OR id LIKE 'plaud_da19b53f%' OR id LIKE 'plaud_8709887b%';
-- Task 1b: endpoint check — GET /api/transcripts/by-matter/ao returns ≥4 rows
-- Task 2: expect 0 rows still slugged hagenauer-rg7 with Annaberg content on 2026-06-22
-- Task 3: expect 0 open tickets on aukera-annaberg-financing sourced from 2026-06-07/08 identity-only WA batch
```

## Acceptance criteria

- AC1: 4 AO Plaud rows carry `matter_slug='ao'`; by-matter/ao endpoint returns them.
- AC2: 22-Jun Annaberg transcript re-slugged to verified canonical slug; cite slugs.yml line in report.
- AC3: stale identity-only 06-07/08 WA tickets on aukera-annaberg-financing disposed; genuine items untouched (list survivor ticket ids).
- AC4: WRONG_TERMINAL routing behavior reported with one traced example.
- AC5: folder→matter_slug gap paragraph delivered (P2 brief candidate).
- Report: bus-post to lead with per-AC verdicts + row counts BEFORE/AFTER. Ack nothing yourself — lead owns #6074/#6079 acks.
