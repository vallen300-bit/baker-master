# Matter_slug ratifications — Director-ratified 2026-05-13

Source: `briefs/_reports/B3_backfill_matter_slug_20260513T075050Z.md` (b3 PR #200 dry-run, 33 M-bucket rows).
Captured via Chrome MCP from Director's live Triaga session at
`/Users/dimitry/Vallen Dropbox/Dimitry vallen/_01_INBOX_FROM_CLAUDE/2026-05-13-AH1-matter-slug-ratification-triage.html`.

**Breakdown of Director's 33 picks:**
- (a) Ratify as proposed: 1 row → claimsmax
- (b) Drop (leave NULL): 14 rows → 1407, 1420, 1427, 1429, 1438, 1449, 1464, 1466, 1468, 1473, 1479, 1482, 1483, 1486 (incl. Cupial settlement — Director flagged: closed item should never have surfaced)
- (c) Remap to specific canonical slug: 18 rows (see table below)

**Apply set: 19 rows** (1 ratify + 18 remap). The 14 drops are excluded entirely — those deadlines remain `matter_slug IS NULL` so the next backfill iteration won't re-surface them after the noise-filter brief lands.

---

## Bucket M (Matched) — 19 rows

| id | description | matter_name raw → canonical slug | source_type | reason |
|---:|---|---|---|---|
| 424 | Borrower must sign the Facility Agreement or Break-up Fee of EUR 75,000 becomes | Director-remapped → annaberg | email | Director remap 2026-05-13 |
| 433 | Restructure AO's interest (Annaberg-related financing) | Director-remapped → annaberg | email | Director remap 2026-05-13 |
| 441 | TenderMax feasibility spike -- ingest section of MO brand standards through Clai | Director-ratified → claimsmax | cowork_session | Director ratify-as-proposed 2026-05-13 |
| 1033 | Patrick Piras will resign as director and coordinator of Sunny Immo Eurl and Fir | Director-remapped → cap-ferrat | email | Director remap 2026-05-13 |
| 1317 | Tax and legal administration of French company starting | Director-remapped → cap-ferrat | email | Director remap 2026-05-13 |
| 1329 | File claims with insolvency administrator for hagenauer Austria GmbH & Co KG | Director-remapped → hagenauer-rg7 | email | Director remap 2026-05-13 |
| 1330 | Attend assessment and reporting hearing for hagenauer Austria GmbH & Co KG at Co | Director-remapped → hagenauer-rg7 | email | Director remap 2026-05-13 |
| 1344 | Aukera EUR 15M term sheet execution deadline -- Lilienmatt/Annaberg restructurin | Director-remapped → lilienmatt | cowork_session | Director remap 2026-05-13 |
| 1346 | Lilienmatt Transparenzregister update -- must be filed within 2 weeks of share t | Director-remapped → lilienmatt | cowork_session | Director remap 2026-05-13 |
| 1357 | news to AO re developing press story around HAG insolvency | Director-remapped → ao | dashboard | Director remap 2026-05-13 |
| 1358 | info re La Plana Villa from UBS bank | Director-remapped → ao | dashboard | Director remap 2026-05-13 |
| 1366 | Inform AO about €2,000 cash. | Director-remapped → ao | dashboard | Director remap 2026-05-13 |
| 1406 | Slack subscription renewal. BrisenGroup's subscription for 2 active users will a | Director-remapped → baker-internal | email | Director remap 2026-05-13 |
| 1416 | Issue Drawdown Request No. 3 to AO (EUR 2M) under AO-LCG Loan Agreement | Director-remapped → ao | cowork_session | Director remap 2026-05-13 |
| 1417 | HARD BACKSTOP: Participation Agreement (LCG-Aelio) must be signed -- governance | Director-remapped → ao | cowork_session | Director remap 2026-05-13 |
| 1474 | AO: return of 650,000 from taxes re Lana issue, e mail expected from Merz | Director-remapped → ao | dashboard | Director remap 2026-05-13 |
| 1522 | Baden-Baden Desk — Thursday consolidated review session (5 open threads: Weipper | Director-remapped → lilienmatt | cowork_session | Director remap 2026-05-13 |
| 1523 | Skliar+Derkachova €500-588K Lilienmatt loan maturity — hard counterparty deadlin | Director-remapped → mrci | cowork_session | Director remap 2026-05-13 |
| 1526 | [MOVIE DESK/Tasks & Debriefs] Debrief Director: MOHG senior meeting outcomes | Director-remapped → mo-vie-am | clickup | Director remap 2026-05-13 |

## Bucket U (Dropped — leave NULL) — 14 rows

These rows Director explicitly classified as noise; the next backfill iteration must exclude them via source-type blacklist + classifier-confidence threshold (next brief).

| id | description | source_type | drop reason |
|---:|---|---|---|
| 1407 | Slack subscription renewal | email | SaaS subscription, not a matter |
| 1420 | Delivery of Rode Rode Wireless Micro Lightning Black | email | hardware delivery |
| 1427 | Celebrate Baghera/wines 10th anniversary with two special sales | email | wine event |
| 1429 | 20% discount on TCS Cyber Protection for TCS members | email | insurance ad |
| 1438 | Make payment to American Express to avoid a late fee. | email | credit card payment |
| 1449 | Seminar on how to determine and verify the effective domicile, registered office | email | marketing seminar |
| 1464 | Register for and attend the 'Speicher optimieren in Krisenzeiten' webcast | email | webcast |
| 1466 | Attend meeting to discuss April/YTD and Forecast through summer | email | generic forecast meeting |
| 1468 | Attend or be aware of the AML analysis course/event on transactions and contract | email | training event |
| 1473 | Special subscription offer for Bloomberg.com expires | email | Bloomberg ad |
| 1479 | Subscribe to Bloomberg.com to get 60% off the first year | email | Bloomberg ad |
| 1482 | Register for the OPIO VALBONNE CLASSIC by JOHN TAYLOR golf event | email | golf event registration |
| 1483 | Participate in the OPIO VALBONNE CLASSIC by JOHN TAYLOR golf event. | email | golf event participation |
| 1486 | Cupial settlement chase — confirm settlement mode (cash / set-off / payment plan | cowork_session | Director note: closed item — status leak, should never have surfaced |
