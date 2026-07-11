# B2 — financing-aukera-closeout PART A (read-only DB resolution)

**Date:** 2026-06-25 · **From:** b2 · **To:** baden-baden-desk (cc lead) · **Dispatch:** bus #4366/#4369 (lead)
**Scope:** read-only queries on `email_messages` / `email_attachments` (source=graph). No code, no mutations.

## PART B (companion) — already shipped, no PR
`baden-baden-desk` slug already on main as of `ec157240` (#423, deputy, merged 2026-06-25 11:11Z): present in
`AGENT_IDENTITY_BUS_AGENT_SLUGS`, `AGENT_IDENTITY_VALID_SLUGS`, the is-valid-slug case, role-resolve, and
`SNAPSHOT_TERMINALS`. lead's "unknown slug" was a stale `~/Desktop/baker-code` checkout (`43050303`). Confirmed
live by posting to `baden-baden-desk` from `~/bm-b2/scripts/bus_post.sh` (resolved, no error). No duplicate PR.

## Confirmed: the desk's 5 known mails (single-message threads; message_id == thread_id == conversationId)
| nNN | date | sender | atts | conversationId (thread_id) |
|-----|------|--------|------|----------------------------|
| n39 | 2026-06-18 | Merz | 21 | AAQk…MAAQAMrq6oIR7Ur9lct8noLxFLk= |
| n42 | 2026-06-22 | Merz | 1 | AAQk…MAAQAKz6hrTwKkB6kDy9fqkF7mA= |
| n46 | 2026-06-22 | Merz | 1 | AAQk…MAAQAOPT5G_jrEu9lUhFlEdcqK8= |
| n54 | 2026-06-24 | Schreiner | 5 | AAQk…MAAQAHzDlIELv71Dnb43UVIVmpk= |
| n55 | 2026-06-24 | Brandner | 5 | AAQk…MAAQAFQY5uG-ekHDjhq-S0gdR_Q= |
Sum = **33** ✓ (matches desk).

## Q1 — premise correction (fail-loud): room is 13 mails / 51 atts, not 6 / 38
The "33 + a single 6th mail = 38" model undercounts. June-2026 case-46/2026 room has **8 more** attachment-bearing
graph mails the desk hasn't catalogued:
1. 2026-06-01 · balazs · 3 · Fwd: Projekt Annaberg – Erstentwurf Darlehensvertrag · …AD80hl2QR0QJgMGkubuuUio=
2. 2026-06-03 · balazs · 2 · Re: Additional info required for the Aukera VDR · …AI1pDv8_pgpLhx9EGVHGxnE=
3. 2026-06-08 · brandner · 3 · AW: 46/2026 Kreditverhältnis mit Aukera / Projekt-Control · …AC8xfy-FwmxMkPEceNMZJAk=
4. 2026-06-08 · Merz · 2 · 46/2026 LMI GmbH ./. Aukera · …AAIM_STUmEE_k8AkmUrYMe4=
5. 2026-06-09 · brandner · 3 · WG: 46/2026 Kreditverhältnis mit Aukera / Projekt-Control · **same thread as #3**
6. 2026-06-09 · Merz · 2 · 46/2026 Lilienmatt ./. Aukere -- Review Fees · …APTFnopjkE58vle5q6mA1Yc=
7. 2026-06-15 · Merz · 2 · 46/2026 Lilienmatt ./. Aukera · …AEWbKjWNzENamZvI7EGJifI=
8. 2026-06-25 · brandner · 1 · WG: IMPORTANT: Invoice in advance Aukera/Colliers · …AP6LchoDl5FJi3Dd6bOHMpg=

If the room is strictly the Merz "46/2026" litigation file, in-scope adds are #3–#7; #1/#2/#8 are financing-adjacent
(desk decides). Total att-bearing room mails = 13; total attachments = 51.

## Q3/Q4 — FY2025 FS not where expected (fail-loud)
n54 thread (subject "WG: LILIENMATT 2025 annual financial statements") is single-message; its 5 attachments are ALL
shareholder resolutions: `250121/250127/250128/250212/250227 LM Gesellschafterbeschluss …K.pdf`. No FS sibling in the
thread (one ingested message only). Whole-graph search: the only ingested Lilienmatt FS doc is
`Lilienmatt_Financial_Statements_2024_2025_PCPrev_260422….pdf` in the 2026-04-23 'Re: 2024 FS of Lilienmatt Immobilien
GmbH' thread (…ALEGsEsE51ZLoF8ccq9PuV0=). **The FY2025 annual FS PDF is not ingested/received** — confirm with the desk
whether it was ever emailed as an attachment (vs a link/portal).

## Q2 — conversationId = thread_id (self-serve for single-message mails)
For single-message room mails thread_id == message_id, so each note's frontmatter `message_id` already IS the
conversationId. Bound now: **n33** ("Aukera fee-letter REVIEW") = 2026-06-09 Merz 'Review Fees' = …APTFnopjkE58vle5q6mA1Yc=
(item #6). Not bindable by label alone — need frontmatter message_ids/subjects: **n15** (debt-model/account-statements),
**n17/18** (Darlehensvertrag+Anlage10+Geschäftsanteilsverpfändung), **n63/66** (2025 FS — see Q3), **n64** (further Kaufverträge).

## Definitional note
Tables have no raw Graph `conversationId` column; `thread_id` is the surrogate (per #424). If the desk needs the raw
Graph conversationId string, it must come from the graph raw-ingest layer, not these tables.

## Residual-gaps verdict (desk #4392 → b2 #4393)
Desk confirmed enumeration exact (pulled all 8 threads → 46 files / 13 mails, committed `95f1c6c`); self-closed n17/18 (Anlage-10 = t1+t4) and n33 (= byte-identical re-send of n46). Three absence claims to verify:
1. **FY2025 annual FS (JA 2025): CONFIRMED ABSENT.** Whole-store search of every JA/Jahresabschluss/Financial-Statement/
   Erstellungsbericht/Bilanz attachment — latest year-end docs are **JA 2024** (`LM`/`MRCI Erstellungsbericht zum JA 2024
   signiert.pdf`, conrad.weiss, April 2026) + the `..._2024_2025_PCPrev_260422.xlsx` preview. No `Jahresabschluss 2025` /
   `Financial Statement 2025` for any entity/sender. Consistent with FY2025 JA not yet issued. → external/not-yet-existing.
2. **Lilienmatt Geschäftsanteilsverpfändung (share-pledge) DRAFT: CONFIRMED ABSENT** in the 2026 Aukera context. All pledge
   docs in graph are other entities/deals (RG7/HotelCo G.Ball 2025-05/06; Junior-Lender gantey 2023; MRCI U-Share-Pledge
   2021; Annaberg Kontoverpfändung 2020; Receivables-Pledge OpCo EXECUTED 2026-03-03 …D-5dYhyW0kDhCI0eE3_JwM=). → external.
3. **n15 + n64: NOT absent** (corrected the desk's external assumption):
   - n15 candidates: `2024/2025-LILIENMATT-SUSA_907676_6242_…xlsx` (balazs, 2026-04-10, …NUm8kWZlkM7jA8AmmqBj10=) = Lilienmatt
     account balances; and `Annaberg XXI Debt Model Aukera_Comments AB.xlsx` (balazs, 2026-05-22/25, …IR9ge2Qd0Tdv1v3_ESzMW0=).
   - n64: `260212-LM-ALESKEROV-Kaufvertrag-EN_TRANSLATED.pdf` (brandner, 2026-02-27, …NmFwTJQn09CkJDrkwGXV0A=);
     `2025-1589_Kaufvertrag Top 1.5 …Lilienmatt` standalone (brandner, 2026-01-21, …A7T2ciqMz1Kt4beMbBangE=).
   Awaiting desk to pick which n15 it means → I bind the conversationId.
