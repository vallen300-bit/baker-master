---
report: ship
brief_id: BAKER_OS_V2_E1_AUKERA_DASHBOARD_TUNE
by: b2
dispatched_by: lead
date: 2026-07-07
status: SHIPPED (10/12 applied; 2 parked for cowork-ah1 ruling)
vault_commit: fdd6518 (main, pushed origin/main)
work_file: _ops/build/baker-os-v2/05_outputs/flight-dashboards/BB-AUK-001/dashboard-v1-pattern-d.html (Page v7)
ship_bus: "#5991"
resume_gap_bus: "#5982"
---

# B2 ship report — E1 Aukera flight-dashboard TEMPLATE pass

## What shipped
Applied 10 of 12 Baden-Baden desk content-pass findings (`E1-content-pass-findings-bbdesk-20260706.md`)
to the BB-AUK-001 Aukera flight dashboard, plus the verbatim loan-cost tile lock
(`decide-now-loan-cost-tile-CORRECTED-bbdesk-20260706.md`). Single-file atomic commit on vault main
per branch-lock rule (#5857); pushed to origin/main.

### Findings applied
- **NOISE-2 [HIGH, rule 7]** — loan-cost tile corrected to BB desk's verbatim lock: ≈1.66M reframed as
  "upfront only; all-in still OPEN (quarterly coupon rate blank + 1.116× exit make-whole not added)"
  in every instance — KPI tile, overview decision subline, decision-detail bullet, CONTINUE/SWITCH/DESK-VIEW
  options, financials popover + financials table row. The "All-in loan cost" string is removed. Numbers
  not re-derived (per the render-verbatim instruction).
- **MISSING-1 [HIGH, rule 9a]** — as-of doc-family + version anchors added to KPI tile receipts
  (loan cost → "Loan agreement v26 · 2 Jul"; self-fund → "Brandner cash-flow email · 17 Jun"; LTV → Colliers + Annex 4).
- **MISSING-5 [MED, rule 9c] + NOISE-4 [MED]** — LTV + collateral tiles carry a "REVISION PENDING" amber
  badge (Colliers page 29 mid-revision) and the "EUR 33.1M secured (17 units), not the EUR 38.6M whole
  portfolio" basis note on the KPI tile (previously only in the popover).
- **NOISE-1 [HIGH, rule 5]** — comms per-sender msg/urgent counts badged "desk-estimated (4 Jul), not the
  live ledger; machine ticket-count query lands in step-2" (they drift from the airport_tickets ledger).
- **NOISE-5 [LOW]** — Engine-Lab ticket counts labelled "Snapshot — machine-queried 4 Jul 22:42 (2 days old);
  live query lands in step-2".
- **MISSING-4 [MED, rule 6]** — new Director-facing "What changed this week" matter-event feed added to
  Overview (6 events, newest first, each with receipt), distinct from the Engine-Lab build feed.
- **MISSING-6 [LOW, rule 4]** — writer stamps added to the Overview "Key numbers" and "Needs attention" cards.
- **NOISE-3 [MED, rule 10b]** — "2+1-year term" glossed ("a 2-year term plus a 1-year extension option").
- **NOISE-6 [LOW]** — countdown softened: "Signing targeted ≈10 Jul (verbal; may slip — land-register entry
  now 2–6 months out)".
- Added a Page v7 entry to the build/audit trail. Fixed one rule-10a term I introduced (Anlage → Annex).

## Verification
- Rendered in Chrome (file://) and full-page screenshot reviewed — all edits display in the page grammar;
  no layout breakage.
- Tag balance: div 203/203, section 9/9, li 148/148.
- Rule-7 sanity grep: no residual "All-in loan cost"; "upfront" framing present in 8 places.
- Rule-10a grep: no German terms/diacritics in rendered content.

## Parked for cowork-ah1 ruling (2 — genuine scope questions, not template-mechanical)
- **MISSING-2 — section-4 boarding/outbound counter.** Contract wants the honest "0 — not built (step-2)"
  string, but Engine Lab currently shows "20 receipts, 1 claimed" as if the onward-journey lane is live since
  4 Jul. Confirm whether that lane is genuinely live (keep 20) or a mock that should read "0 — not built
  (step-2)". Reversing a "live" claim to 0 is direction-shaped, so not guessed.
- **MISSING-3 — section-5b research received.** Add the b3 flight-manual sweep + ESG questionnaire read as 5b
  rows, or keep the honest-empty if cowork-ah1 rules these desk-internal, not "research received".

## Housekeeping
- My prior respawn (#5925) named a checkpoint + branch `b2/e1-aukera-dashboard-tune` that were never
  committed — both absent from bm-b2 and baker-vault. Flagged on the bus (#5982); attempt-2 checkpoint now written.
- `briefs/_tasks/CODE_2_PENDING.md` is stale (shows CORRELATION_ID_PRIMITIVE_1 MERGED, not this E1 lane).
