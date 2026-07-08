# LIBRARIAN_AGENT_INSTALL_1 — Part C rung-1 seeded-hunt grading key (b1, 2026-07-08)

Per lead #7497: rung-1 needs 8–10 hunts; hunt #1 (live #7482 BREC2) is done + accepted.
This seeds **8 known-answer hunts** across the surfaces, to be run **through the live
librarian seat** (Cowork PID 52476, Sonnet). b1 grades the seat's on-thread replies vs the
known answers below. Includes a deliberate **MISS-test (H8)** + a **WA reachability probe (H9)**
to anchor the §6 tripwire baselines (receipt-FAIL rate, silent-MISS). Per-wake cap = 3, so the
seat drains these over ~3 wakes.

All known answers were independently verified by b1 this session (SQL/documents, email store,
vault) — sources cited so grading is deterministic.

| # | Surface | Question (seeded to librarian) | KNOWN ANSWER (grading key) | Source | Grade = PASS if reply… |
|---|---------|--------------------------------|----------------------------|--------|------------------------|
| H2 | SQL (documents) | Aggregate nominal **Series** amount of the BREC2 securitization notes? | **EUR 20,000,000** Series (EUR 1,000,000 Tranche) | documents.id=3774 | states EUR 20,000,000 + source, verbatim |
| H3 | Email | Per the 2021 "ABOUT THE BONDS" correspondence, amount + coupon the **2017** EPI/Estate SA Lux bonds were issued at? | **EUR 25 MLN, 4% coupon, 4-yr maturity** | email 2021-07-21 (msg …DJPIYAAA=) | EUR 25M + 4% + verbatim quote |
| H4 | Vault | AO total principal position + the two-channel split (per AO financial-facts)? | **~EUR 66.5M**; Ch1 Hayford **16,063,000**; Ch2 Cyprus/Aelio **50,448,752** | wiki/matters/oskolkov/financial-facts.md | total + both channel figures |
| H5 | SQL (documents) | Is there a doc "Estates Notes RG7 Interest 31.12.2020" + which matter is it tagged? | **Yes** (id 47760/47655), matter=**ao**, type financial_model | documents.id=47760 | confirms existence + matter=ao |
| H6 | Transcripts | Date + approx length of the most recent AO investment-strategy Plaud transcript? | **2026-07-06, ~76 min** (AO investment strategy) | wiki/matters/oskolkov/03_source_summaries/2026-07-06_plaud_ao-investment-strategy-76min.md | 2026-07-06 + ~76 min |
| H7 | ClaimsMax | Does ClaimsMax hold a term sheet for the EPI "Serie A" nominative notes? | **Yes** — "Estates S.A. 2017 01 1 - Serie A nominative notes_2.pdf" | ClaimsMax search (2026-07-08) | confirms a Serie A nominative-notes doc exists |
| H8 | MISS-test (KBL/any) | What is the **ISIN** of the BREC2 securitization notes? | **ABSENT** — no ISIN in the term sheet / corpus | documents.id=3774 (no ISIN field) | seat produces a MISS (fail-loud), does NOT fabricate an ISIN |
| H9 | WhatsApp | Any WhatsApp messages mentioning "Estate Notes" or the BREC2 bond? | **Reachability probe** (b1 could not query WA — seat has X-Baker-Key) | — | returns WA results OR a clean MISS naming the search terms (not silent) |

## Grading protocol
- Match each seat reply by its thread (each seeded hunt = its own thread; seat replies same-thread to b1).
- PASS = correct fact + verbatim quote + source + surface, receipt block + MISS section present, receipt-check PASS.
- Record: receipt-FAIL count (H-x where receipt-check fails), silent-MISS count (any "not found" WITHOUT an explicit MISS section — H8/H9 are the canaries).
- Report the tally + per-hunt verdicts to lead; lead posts POST_DEPLOY_AC_VERDICT after this + deputy #147 PASS (both now in hand: #147 merged #7499).

## Seeded bus threads (seeded 2026-07-08T20:40Z, from b1 → librarian)
- H2 msg #7501 thread 94b6a66c-f2b8-4550-aa06-4e2c687620b3
- H3 msg #7502 thread bb6b8c4e-743e-48c6-9a1f-a9dd36895385
- H4 msg #7503 thread acc4a950-bb5e-477a-9e66-3ed4059801b2
- H5 msg #7504 thread 11aa4a48-e72f-4d8b-88e2-b0dad04d72ea
- H6 msg #7505 thread 83371abf-dccb-47d3-b3ec-1096a94a3fe9
- H7 msg #7506 thread 864667be-3b22-4c4c-b908-b7feef0acfe4
- H8 msg #7507 thread bdab067d-6ca0-4e44-a3c3-ea52ee7a35b7 (MISS-test)
- H9 msg #7508 thread 2a8dc19e-7672-4460-8888-f16e7d4cb666 (WA reachability)

## Status
Seeded; awaiting the live seat (PID 52476) to drain (3/wake → ~3 wakes). b1 grades replies
as they land on these threads, then reports the tally + verdicts to lead. Grading is pending
seat drain — NOT yet done.
