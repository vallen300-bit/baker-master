# B2 Ship Report — DATA_OPS_AO_PLAUD_BACKFILL_WA_NOISE_1

- **Dispatched by:** lead (#6144) + amendments #6200 / #6209 / #6318 / #6619; standing release #6629
- **Assignee:** b2 (fresh seat)
- **Date:** 2026-07-07
- **Code PR:** #482 (`b2/wa-identity-ticket-ceiling-1`) — codex gate **PASS, no findings** (#6659)
- **Data-ops writes:** via audited `baker_raw_write` (no shell `DATABASE_URL`)

## Per-AC verdicts

### AC1 — 4 AO Plaud rows → `matter_slug='ao'` ✅ PASS
BEFORE: all 4 `<NULL>`. AFTER: all 4 `ao`. Content confirmed AO before write.
| id | date | before | after |
|---|---|---|---|
| plaud_58683bca… | 07-06 | NULL | ao |  (Russian source-of-funds / KYC)
| plaud_5ff5b488… | 07-06 | NULL | ao |  (investment strategy)
| plaud_da19b53f… | 06-25 | NULL | ao |  (bank contract / funding schedule)
| plaud_8709887b… | 06-25 | NULL | ao |  (Istanbul negotiation / sale strategy)

`GET /api/transcripts/by-matter/ao` now returns **5** rows (4 backfilled + 1 pre-existing). Canonical slug `ao` verified in `slugs.yml:40` (`oskolkov` is an alias, line 43).

### AC2 — 22-Jun Annaberg transcript re-slugged ✅ PASS (+ finding)
`plaud_4475cff5…` ("06-22 Anaberg Loan Strategy, Cash Flow, Construction Scope, Refinancing, Hotel Sale") `hagenauer-rg7` → **`annaberg`**. Canonical slug `annaberg` verified in `slugs.yml:60` ("Baden-Baden project vehicle; Aukera-financed alongside Lilienmatt").
**FINDING (out of brief scope, not touched):** two OTHER 06-22 rows are still `hagenauer-rg7` but carry Baden-Baden-flavored content, not Vienna RG7 — likely also mis-slugged, correct slug ambiguous:
- `plaud_97e71e08…` "Loan Decision, Apartment Fit-Out, Baubis/Balgerstrasse Financing, Sales Pricing" (annaberg vs mrci?)
- `plaud_114e3a36…` "Contractor Negotiation and Scope for Electrical Work" (Balazs participant → Baden-Baden?)
Left for a lead ruling — brief named only the singular Annaberg-strategy row.

### AC3 — stale WA tickets on `aukera-annaberg-financing` ✅ PASS (verify-only, desk owns disposal per #6318)
Did **not** dispose (desk disposing the 72 itself — no double-dispose). State:
| status | n | span | note |
|---|---|---|---|
| sent (open) | 72 | 06-08→07-06 | **69 identity-only** (dispose) + **3 keyword survivors** (preserve) |
| rejected | 38 | 06-07→07-07 | already disposed |
| checked_in | 9 | 06-08 | genuine, processed |
| failed | 2 | 06-13 | — |
**3 survivors to preserve** (keyword-matched, also survive the task-6 fix): `…fa2a4821` Balazs Csepregi (annaberg, 06-12); `…f8827740` Constantinos Pohanis (aukera, 07-06); `…d24fc720` Constantinos Pohanis (lilienmatt, 07-06). Note: 16 of the 69 identity-only are dated 07-06 — same-day flood, confirming #6619's "regardless of age" requirement.

### AC3b — no re-ticket on next tick ✅ PASS (via task 6)
Task-6 fix marks suppressed identity-only WA arrivals `done=True` → watermark advances past them → never re-fetched/re-ticketed. Live-PG + in-process tests confirm.

### AC4 — WRONG_TERMINAL routing ✅ REPORTED (behavior: NO re-route)
`airport_checkin_reader.py:52-59` maps `WRONG_TERMINAL → "rejected"`. A ticket a desk marks WRONG_TERMINAL is **closed/rejected, NOT forwarded to the correct desk** (e.g. MOVIE). No re-route mechanism exists — the correct desk only sees the item if independently fetched via its own keyword/participant lane.
**Traced example:** `airport-ticket-v1-a457307b` — WhatsApp from Director on `aukera-annaberg-financing`, `proposed_desk=baden-baden-desk`, checked in `WRONG_TERMINAL` by `baden-baden-desk` → `rejected`. The item was not re-ticketed to any other desk.
**Gap (P2 candidate):** a MO-VIE / nVIDIA item landing on the wrong desk is silently dropped on WRONG_TERMINAL; consider a re-route-on-WRONG_TERMINAL path (or at least a drop-log) so mis-routed items reach the right desk.

### AC5 — folder→matter_slug classifier gap ✅ REPORTED (P2 brief candidate, not built)
Plaud Note Pro organizes recordings by **folder** (Director's scheme). `triggers/plaud_trigger.py::format_plaud_transcript` (line 318) extracts title/date/transcript/summary/participants/duration but **never the folder** — the Plaud API `rec` folder field is dropped at ingest, and `meeting_transcripts` has no folder column. `matter_slug` is classified downstream (content-based, per PLAUD_TRANSCRIPT_BY_MATTER_1), which can't use the folder signal because it was never persisted — the root cause of the NULL/mis-slug rows fixed in AC1+AC2. **Proposed insertion point (do not build):** extract the Plaud folder name in `plaud_trigger.py:318`, persist a `plaud_folder` column on `meeting_transcripts`, and pass folder→matter_slug as a high-precedence hint to the downstream classifier (folder "AO"/"Annaberg" is a stronger signal than content keywords).

## Task 6 (P1 code fix) — PR #482
`AIRPORT_WA_IDENTITY_TICKET_MAX_AGE_HOURS` (default 0 = suppress all identity-only WA tickets regardless of age; N>0 = age ceiling; <0 = legacy/disabled). Suppression is in `_run_nonmail_lane` via `suppress_fn` (WA lane only); suppressed arrivals advance the watermark (not held, don't consume cap). Keyword/matter matches still ticket. `build_whatsapp_ticket` byte-identical. Tests: 12 pure-unit + 1 live-PG (CI-gated) + full airport suite 85 passed, 0 regressions. Codex medium gate PASS.

## Task 7 — watermark investigation
- **`airport_ticketing:whatsapp`: HEALTHY.** `last_seen` = 2026-07-07 15:12 (0.5h old), advancing normally. lead's interim bump (06-11 → 07-06, #6318) unstuck it; my task-6 fix removes the identity-flood/cap-freeze (identity tickets filled `cap` at bridge.py:2295-2299 → `contiguous=False` → freeze) that was the likely original 06-11 stall cause. No further fix needed.
- **NEW FINDING — `airport_ticketing:plaud`: STUCK at 2026-06-22 14:09 (361h old) while `updated_at` ticks (4.5 min).** Frozen at the exact timestamp of the re-slugged Annaberg row. Likely a held cursor (a `build_plaud_ticket` None or `issue_ticket` failure on the next 06-22+ arrival). My AC1 backfill (4 plaud rows → `ao`) may let it advance next tick IF `ao` is an active `project_registry` matter. Reported for a lead ruling — did not fix (out of scope, needs care).

## Not done / boundaries
- Did not dispose WA tickets (desk owns, #6318). Did not touch `LOOKBACK_HOURS` (b1 owns). Did not re-slug the 2 ambiguous 06-22 rows or fix the plaud watermark (flagged to lead). Did not merge PR #482 (b2 does not merge).
