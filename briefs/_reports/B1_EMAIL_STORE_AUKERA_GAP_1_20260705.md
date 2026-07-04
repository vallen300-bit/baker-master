# B1 — EMAIL_STORE_AUKERA_GAP_1 (Diagnose gate, no fix)

Dispatch #5582 (lead), Director-reported P1. Repo: baker-master. Read-only prod queries via baker MCP (baker_raw_query / baker_email_search / baker_email_read).

## Bottom line
**Not an ingestion gap and not a search bug.** The "very important" Merz 01-Jul 19:26 email IS in the store, fully bodied, indexed, retrievable. The desk's "jump from 02-Jul back to 24-Jun" is a **query-recall artifact**: the important email carries no "Aukera" token, and the dispute-file subject thread genuinely has no traffic 25 Jun–01 Jul. Compounded by a **UTC↔Berlin timezone** confusion (stored 17:26 UTC = 19:26 CEST).

## Q1/Q2 — is the Merz 01-Jul 19:26 email present? Which leg?
**PRESENT.** `email_messages` row:
- sender `Christian Merz <cm@merz-recht.de>`, subject `06/2026 Lilienmatt Immobilien GmbH -Restrukturierung`
- `received_date = 2026-07-01 17:26:40+00` (UTC) = **19:26 Berlin (CEST, UTC+2)** — the "19:26" the Director cited. Confirmed by the 02-Jul reply quoting `Date: Wednesday, 2026. July 1. at 19:26`.
- `source = graph` (M365/Outlook leg), `ingested_at = 2026-07-01 17:26:49` — **7-second** ingest latency. Full body stored (Weippert letter forward; ~€2M Grunderwerbsteuer risk on the Oskolkov share transfer).
- No pipeline leg dropped it. The M365/graph leg covers `merz-recht.de` post-migration and is healthy — every Merz email in the window (06-24 … 07-03) is `source=graph`.

## Q3 — why did the desk's search not return it?
**Query breadth / keyword recall — the search surface works as designed.** `baker_email_search` is a case-insensitive ILIKE over subject+sender+body, newest-first, hard cap 50, no date/thread filter.
1. The matter spans **two subject families**: `46/2026 … ./. Aukera` (the dispute file) and `06/2026 … Restrukturierung` (the restructuring/tax file). The important 01-Jul email is in the **Restrukturierung** family and contains **no "Aukera" token** anywhere (subject or body) → an "Aukera"-scoped query cannot match it.
2. The `46/2026 … ./. Aukera` dispute thread has **no traffic 25 Jun–01 Jul** (activity moved to the Restrukturierung + financing threads). So a dispute-file-scoped search legitimately shows 24-Jun → 02-Jul with nothing between — misread as "missing emails."
3. Timezone: store keeps `received_date` in **UTC**; the desk/Director reason in **Berlin local** (+2). "19:26" local = "17:26" stored. A desk date-filter applied in local time also mis-brackets the boundary.

**Proof recall works when scoped properly:**
- `baker_email_search("Restrukturierung Weippert Grunderwerbsteuer")` → **returns the 01-Jul email** (match_count 3).
- `baker_email_search("Aukera", max=50)` → continuous **16 Jun → 03 Jul** window, **NO gap** — but (correctly) omits the Restrukturierung-family emails that lack the token.

## Q4 — enumerate store vs the window (24 Jun–04 Jul)
`baker_raw_query` on `email_messages`, 24 Jun–05 Jul, Merz/Aukera/Lilienmatt/Annaberg facets → **47 rows, dense and continuous** across both subject families every active day (24, 25, 26, 27, 29, 30, 01, 02, 03). Merz `cm@merz-recht.de` emails specifically on 06-24 (×3), 06-25, **07-01 17:26**, 07-02 (×several), 07-03 (×several). **Nothing missing vs the packet-cited Weippert/Merz 1-Jul letters** — the "Weippert 1-Jul letter" the curated brief cites (#5460/#5465) is the **attachment** to this present 01-Jul Merz email. Gap size = **0 emails**.

## Root cause
Single-counterparty-keyword retrieval **under-recalls a multi-thread matter**. The desk searched the counterparty/dispute term ("Aukera" / the 46/2026 dispute file); the load-bearing email lives in the sibling restructuring thread (06/2026) that shares the matter but not the keyword. No data was lost; no leg failed; the search endpoint behaved correctly.

## Fix proposal (for lead sign-off — no code changed)
1. **Desk-usage fix (primary, zero-code):** query a matter by **multiple facets**, not one counterparty word. `Lilienmatt` (the entity) recalls **both** subject families; add sender `merz-recht.de` and `Annaberg`/`Restrukturierung`. Bake a matter-scoped query recipe into the BB Desk retrieval step.
2. **Product improvements (rank + pick):**
   - (a) `baker_email_search` has **no date-range/thread filter** and returns newest-N (cap 50); on a busy matter, in-window-but-older mail falls off. Add optional `since`/`until` + `thread_id` params.
   - (b) `email_messages` has **no `matter_slug` column** — retrieval is pure keyword. A matter tag (or thread→matter map) enables deterministic "all Lilienmatt mail in window" pulls instead of keyword-guessing. Bigger lift; highest leverage against this class of miss.
   - (c) Surface `received_date` in the desk's **local timezone** (or label UTC explicitly) to kill the 19:26/17:26 confusion.
3. **NOT needed:** no ingestion backfill, no M365-leg fix — the leg is healthy and the email is present.

## Scope
Diagnose-only per dispatch. Read-only queries. No code changed. Deliverable: root cause + gap list (empty) + fix proposal above.
