# B2 — Hagenauer Flight Data Preflight (HAG-RG7-001)

- **Brief:** dispatched on the bus (lead #8513, topic `flight/hag-rg7-001`), Director GO 2026-07-10. Mirrors `B2_AI_HOTEL_PREFLIGHT_20260710.md`.
- **Dispatched by:** lead
- **Task class:** diagnostic / read-only sweep. Harness-V2: N/A (report-only, no production code).
- **Date:** 2026-07-10
- **Matter:** `hagenauer-rg7` — RG7 (Mandarin Oriental Apartments, Baden bei Wien) creditor-claim defense against the insolvent GC Hagenauer. Forderungsanmeldung + Beweissicherungsverfahren.
- **Method:** read-only. Email via read-only SQL over `email_messages` (all sources: Gmail / Bluewin / M365-graph). WhatsApp via `GET /api/whatsapp/messages` (contact-scoped). Transcripts via read-only SQL over `meeting_transcripts` (by-slug + full-table keyword fallback). Vault via `wiki/matters/hagenauer-rg7/` (`classifier-keywords.yml`, `02_inventory/source_inventory.md`, `_overview.md`). No writes to any store, vault, or ClickUp.
- **Known-cast anchor:** the vault has **no `_people.md` roster** for this matter (unlike the AI-HTL rooms). The "known cast" was reconstructed from `classifier-keywords.yml` (counterparty group: `hagenauer`, `ofenheimer`, `riel`) + names referenced in `source_inventory.md` / row drafts (Bauer, Edita, Vladimir, Spanyi, Renner, Sähn, Zottmann). This roster gap is itself a finding (see AC3).

---

## Headline (for the census/registry fold)

1. **HIGH — the E+H counsel team is under-rostered.** The vault names only **Ofenheimer**. The actual E+H working team on file `[EH-AT.FID2087]` is **five** people: Ofenheimer (47 emails), **Blaschka Arndt (44)**, Spanyi (14), Renner (4), **Gföllner Irina (1, evidence-preservation, 2026-07-01)**. **Blaschka is the second-heaviest correspondent in the entire matter and is absent from every vault file.** Census must add Blaschka + Gföllner (Spanyi/Renner are already referenced via the 05-22 meeting).
2. **MED/HIGH — the Hagenauer (GC) side has operational correspondents absent from the vault.** `@hagenauer.de`, project ref "1029 RG7": **Sähn Christine (8** — "Financial Close-Out", "open payments") + **Buhl Dominik (1** — "cost overview"). These are the counterparty's own staff and belong in the dispute chronology.
3. **MED — a SEPARATE law firm is on the matter: Nemetschke, Alfred** (`alfred.nemetschke@nhk-rechtsanwaelte.at`, 5 emails, subject "Hagenauer 01" / "Brisen Development / Hagenauer"). Role unresolved — opposing counsel, Insolvenzverwalter-side, or additional Brisen counsel. Census must resolve before the flight relies on the cast.
4. **MED — Thomas Leitner (Brisen internal, 19)** is Brisen's RG7 project/commercial lead (TU/Totalunternehmer agreement, Maximum-Price-Guarantee, financial close-out) and is not in the vault cast.
5. **Transcript tagging is HEALTHY here (contrast AI-HTL).** The `hagenauer-rg7` slug holds **21** correctly-tagged transcripts — the `by-matter/{slug}` endpoint is reliable for this matter. Minor genuine adjacent scatter only: `cupial` (7, related buyer sub-track), `baker-internal` (3), `claimsmax` (1).
6. **LOW (method) — keyword over-match is severe; use the tight AND-gate.** Raw `rg7` = 13,603 (back to 2005), `ofenheimer` = 6,832 (counsel across ALL matters), `hagenauer` = 2,176 (back to 2014 construction). Mirror `classifier-keywords.yml`: counterparty ∩ dispute-context, 2026-only — else the census drowns in RG7 construction history + Ofenheimer's cross-matter traffic + a MO-Vienna PR lane.

---

## AC1 — Per-channel counts + date ranges

### Email — `email_messages` (Gmail + Bluewin + M365/graph merged)

Raw keyword totals (all-time, whole store) — the over-match trap:

| Keyword | Hits | Date span |
|---|---|---|
| rg7 / rg 7 | 13,603 | 2005-08-09 → 2026-07-10 |
| ofenheimer | 6,832 | 2015-01-27 → 2026-07-10 |
| hagenauer | 2,176 | 2014-11-29 → 2026-07-09 |
| riel (substring) | 1,708 | 2007-09-30 → 2026-07-09 |
| cupial | 1,112 | 2021-09-13 → 2026-05-16 |
| insolvenz | 101 | 2016-07-19 → 2026-07-08 |
| beweissicherung | 51 | 2018-10-30 → 2026-07-09 |
| forderungsanmeldung | 44 | 2024-05-28 → 2026-06-12 |
| weiterverrechnungsliste | 29 | 2019-09-30 → 2026-05-28 |
| heidenauer | 1 | 2026-03-04 |

**Tight Hagenauer creditor-claim set** (2026-only, mirroring the classifier AND-gate: counterparty {hagenauer|ofenheimer|forderungsanmeldung} ∩ dispute-context {insolvenz|forderungsanmeldung|beweissicherung|weiterverrechnung|mängel|gewährleistung|schlussabrechnung|konkurs|klagefrist}). Per-sender (sender-side only — see AC3 blind spot):

| Sender | Email | Side / role | n | Sources | Span |
|---|---|---|---|---|---|
| Edita Vallen | edita.vallen@brisengroup.com | Brisen — Weiterverrechnungsliste author | 54 (+7 graph) | email, graph | 2026-01-20 → 07-09 |
| Ofenheimer Alric | a.ofenheimer@eh.at | E+H — Brisen lead counsel | 47 | email, graph | 2026-01-27 → 06-29 |
| **Blaschka Arndt** | **a.blaschka@eh.at** | **E+H counsel team — NOT in vault** | **44** | email, graph | 2026-01-20 → 05-22 |
| Dimitry Vallen (outbound) | dvallen@brisengroup.com / vallen300@gmail.com / dvallen@bluewin.ch | Brisen — Director | ~57 | email, graph, bluewin | 2026-01-20 → 05-26 |
| Thomas Leitner | thomas.leitner@brisengroup.com | **Brisen — RG7 project/commercial lead — NOT in vault** | 22 | email, graph | 2026-01-26 → 05-28 |
| Spanyi Mario | m.spanyi@eh.at | E+H counsel — Beweissicherung | 14 | email, graph | 2026-05-27 → 07-08 |
| **Sähn Christine** | **c.saehn@hagenauer.de** | **Hagenauer (GC) side — NOT in vault** | **8** | email, graph | 2026-01-25 → 05-07 |
| Vladimir Moravcik | vladimir.moravcik@brisengroup.com | Brisen internal | 6 | email, graph | 2026-01-26 → 03-16 |
| **Nemetschke, Alfred** | **alfred.nemetschke@nhk-rechtsanwaelte.at** | **separate law firm — role to verify — NOT in vault** | **5** | email, graph | 2026-03-18 → 03-22 |
| Balazs Csepregi | balazs.csepregi@brisengroup.com | Brisen internal | 5 | email, graph | 2026-01-27 → 03-13 |
| Renner Rene | r.renner@eh.at | E+H counsel | 4 | email, graph | 2026-03-04 → 05-28 |
| Thomas Bauer | bauer@blup.at | Bauer Baumanagement — auditor (Weiterverrechnungsliste) | 3 | email, graph | 2026-03-03 → 03-10 |
| Dennis Egorenkov | dennis.egorenkov@brisengroup.com | Brisen internal | 3 | email, graph | 2026-02-20 → 02-26 |
| **Buhl Dominik** | **d.buhl@hagenauer.de** | **Hagenauer (GC) side — NOT in vault** | 1 | graph | 2026-02-04 |
| **Gföllner Irina** | **i.gfoellner@eh.at** | **E+H counsel — evidence preservation — NOT in vault** | 1 | graph | 2026-07-01 |
| Ingo Holtz / Office Vienna | ingo.holtz@ / office.vienna@brisengroup.com | Brisen internal | 5 | email, graph | 2026-01-26 → 03-09 |
| **Bleed (NOT creditor-claim cast)** | gaisberg.eu (Luger 13 + Trotz 2), yield.at (Assinger 1), gantey.ch (Buchwalder), mohg.com (Schauer 1), observer.at, planserver.pro, kittel-sicher.at, nfra.at | MO-Vienna insolvency PR-correction lane + AO/Aelio/LCG cross-matter + hotel ops | ~25 | graph, email | 2026-01 → 05 |

### WhatsApp — `GET /api/whatsapp/messages` (contact-scoped, 2026-01-01 → 07-10)

| Contact query | n | chat_id | Span |
|---|---|---|---|
| Edita | 117 | 41799439246 (+41 79 CH) | 2026-02-28 → 07-06 |
| Bauer / Leitner / Vladimir / Hagenauer / Ofenheimer / Spanyi / Nemetschke / Blaschka / Riel / Cupial | 0 | — | — |

**WhatsApp is not a correspondence channel for this matter.** Only Edita (Brisen/family) has a thread, and it is whole-thread (mixed topics, not matter-filtered) — the Hagenauer share is a subset. Every external cast member (counsel, auditor, GC staff) returns 0. Contrast AI-HTL, where the deal ran heavily on WA.

### Transcripts — `meeting_transcripts` (by-slug + full-table keyword fallback)

Live `by-matter/{slug}` reality (keyword sweep grouped by current `matter_slug`):

| Slug | n | Read |
|---|---|---|
| **hagenauer-rg7** | **21** | correctly tagged (2026-01-16 → 06-22); `by-matter` endpoint reliable here |
| cupial | 7 | related buyer sub-track (same RG7 project) — census should decide fold-in |
| kitzbuhel-six-senses | 5 | **false positive** — shared German insolvency lexicon (Steininger debt / court valuation), NOT Hagenauer |
| baker-internal | 3 | 1–2 likely genuine Hagenauer discussion mis-tagged (e.g. 05-21 "Project Disputes") |
| austrian-tax / kitz-kempinski | 2 / 2 | false positive (shared lexicon) |
| claimsmax | 1 | ClaimsMax strategy (used for the filing) — adjacent |
| mo-vie-exit | 1 | tangential |

Transcript participant columns are unusable for cast enumeration: Fireflies rows carry only `vallen300@gmail.com` (organizer); Plaud rows carry unlabeled "Speaker 1..N". Named cast comes from email, not transcripts.

---

## AC2 — Distinct-participant list (feeds the researcher census)

| # | Name (canonical) | Side / Role | Email(s) | WA | In vault? |
|---|---|---|---|---|---|
| 1 | Alric Ofenheimer | E+H — Brisen lead counsel | a.ofenheimer@eh.at | — | ✅ (classifier keyword) |
| 2 | **Arndt Blaschka** | **E+H counsel team (file EH-AT.FID2087)** | a.blaschka@eh.at | — | ❌ absent — **44 emails** |
| 3 | Mario Spanyi | E+H counsel — Beweissicherung | m.spanyi@eh.at | — | ✅ (05-22 meeting) |
| 4 | Rene Renner | E+H counsel | r.renner@eh.at | — | ✅ (05-22 meeting) |
| 5 | **Irina Gföllner** | **E+H counsel — evidence preservation** | i.gfoellner@eh.at | — | ❌ absent (July, recent) |
| 6 | Thomas Bauer | Bauer Baumanagement — auditor (Weiterverrechnungsliste F05) | bauer@blup.at | — | ✅ (F05 source) |
| 7 | **Christine Sähn** | **Hagenauer (GC) — commercial / close-out** | c.saehn@hagenauer.de | — | ⚠ referenced once ("Sähn Aktennotiz" R08) but not as a cast entry |
| 8 | **Dominik Buhl** | **Hagenauer (GC) — cost** | d.buhl@hagenauer.de | — | ❌ absent |
| 9 | **Alfred Nemetschke** | **NHK Rechtsanwälte — separate firm, role unresolved** | alfred.nemetschke@nhk-rechtsanwaelte.at | — | ❌ absent |
| 10 | **Thomas Leitner** | **Brisen — RG7 project/commercial lead (TU/GMP)** | thomas.leitner@brisengroup.com | — | ❌ absent |
| 11 | Edita Vallen | Brisen — Weiterverrechnungsliste author | edita.vallen@brisengroup.com | 41799439246@s.whatsapp.net | ✅ (Lane-3 originals) |
| 12 | Vladimir Moravcik | Brisen internal | vladimir.moravcik@brisengroup.com | — | ✅ (dispatch recipient) |
| 13 | Dr. Riel | Insolvenzverwalter — filing recipient | (no direct email in store; in-body ref ×12, 05-21/22) | — | ✅ (classifier keyword; "quiet period") |
| 14 | Dimitry Vallen | Brisen — Director | dvallen@brisengroup.com; vallen300@gmail.com; dvallen@bluewin.ch | (Director) | ✅ |
| — | Balazs Csepregi, Dennis Egorenkov, Ingo Holtz | Brisen internal (support) | *@brisengroup.com | — | partial |

Counterparty entities named in the vault but with ~no direct raw correspondence (research targets, correctly no sender traffic): **Hagenauer GmbH** (as company), **Cupial** (buyer sub-track — heavy pre-2026, tails off 2026-05), **Heidenauer** (separate contractor — 1 email 2026-03-04), subcontractors Pichler/RHTB/S&K/Fuchsberger/Zottmann (appear in claim row drafts, not as email senders).

---

## AC3 — Gaps + risks (rated)

- **HIGH — no `_people.md` roster exists for this matter.** Unlike the AI-HTL rooms (18-person ratified cast), `wiki/matters/hagenauer-rg7/` has no people file. The "known cast" is implicit across `classifier-keywords.yml` + row drafts. This is why the E+H team and GC-side correspondents were never rostered. **Action:** the census should stand up a `_people.md` for this matter as its first product.
- **HIGH — E+H counsel team under-rostered.** Vault names only Ofenheimer; Blaschka (44), Gföllner (1) are absent and Spanyi/Renner are only implicitly present (05-22 meeting). All share file `[EH-AT.FID2087]`. A census that reads only the vault would misattribute ~44 counsel emails to "unknown."
- **MED/HIGH — Hagenauer (GC) side missing.** Sähn (8) + Buhl (1) `@hagenauer.de` ("1029 RG7") are the counterparty's operational staff — load-bearing for the dispute chronology (financial close-out, open payments, cost overview) and absent from the vault.
- **MED — Nemetschke / NHK Rechtsanwälte identity unresolved.** 5 emails, "Hagenauer 01" subject prefix, but a different firm from E+H. Could be opposing/GC counsel, Insolvenzverwalter-side, or additional Brisen counsel. Resolve before the flight cast is trusted.
- **MED — email store is sender-only (no recipient column).** Counterparties Dimitry emailed who never replied (or whose replies weren't ingested) are invisible. Counsel/GC are captured via inbound replies, so the core is covered — but any silent-recipient party is a blind spot.
- **MED — keyword over-match + cross-matter/PR bleed.** `rg7` (13,603, from 2005), `ofenheimer` (6,832, all matters), `hagenauer` (2,176, from 2014). The tight 2026 set still pulls a MO-Vienna PR-correction lane (gaisberg.eu / yield.at — "Mandarin Oriental Vienna is NOT affected by the current insolvency") + AO/Aelio/LCG (gantey.ch). Exclude these from the creditor-claim census; they are reputation/adjacent, not claim cast.
- **LOW — transcript adjacent scatter.** `hagenauer-rg7` (21) is healthy, but `cupial` (7), `baker-internal` (3), `claimsmax` (1) hold genuinely adjacent transcripts; `kitzbuhel-six-senses` (5) / `austrian-tax` (2) are false positives on shared German insolvency vocabulary. The census should keyword-verify before folding non-`hagenauer-rg7` slugs.
- **LOW — Dr. Riel has no inbound raw traffic.** Referenced in-body as Insolvenzverwalter (12 emails, 05-21/22); consistent with the vault "Riel quiet period." Rostered recipient, not a data gap.
- **LOW — WhatsApp near-empty.** Only Edita's whole-thread (117, family/personal). Do not read the 0-counts for external cast as a data gap — this matter simply does not run on WA.

---

## AC4 — Per-store sweep status

| Store | Status | Detail |
|---|---|---|
| Email (`email_messages`) | **Swept fully** | Read-only SQL over full table, all sources (Gmail/Bluewin/graph), all-time + tight-2026 AND-gate set. Per-sender aggregation + role-classifying subject samples for the additions. No errors. |
| WhatsApp (`/api/whatsapp/messages`) | **Swept for the named cast** | 11 contact queries (Bauer, Leitner, Edita, Vladimir, Hagenauer, Ofenheimer, Spanyi, Nemetschke, Blaschka, Riel, Cupial). 1 response with traffic (Edita, 117). Contact-scoped, not a whole-store scan (endpoint requires a contact filter). No errors. |
| Transcripts (`meeting_transcripts`) | **Swept fully** | By-slug counts + full-table keyword fallback (title/summary/full_transcript). Participant columns unusable for cast. No errors. |
| Vault (`wiki/matters/hagenauer-rg7/`) | **Swept for cast anchors** | `classifier-keywords.yml`, `02_inventory/source_inventory.md`, room listing. No `_people.md` exists (finding). Did not read every row draft / curated doc (out of scope for a participant/coverage preflight). |

No store reported "clean" on a skipped scan — every count above traces to an executed query.

---

*Report to lead + researcher on `flight/hag-rg7-001` so researcher reconciles the additions into the HAG-RG7-001 census. Companion to `B2_AI_HOTEL_PREFLIGHT_20260710.md`.*
