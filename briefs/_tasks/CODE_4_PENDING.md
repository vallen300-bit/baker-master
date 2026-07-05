# CODE_4_PENDING — active dispatch mailbox for b4

**ACTIVE: BB_AUK_001_AUDIT_ROUND2_DASHBOARD_UPDATE_1 — STAGE 2** (dispatched bus #5586, stage-2 GO #5635, re-pin #5637, 2026-07-05)

Task: fold b3's Aukera sweep results (bus #5630/#5632, report `briefs/_reports/B3_AUKERA_FLIGHT_MANUAL_SWEEP_1_2026-07-05.md`) into the CEO dashboard
`~/baker-vault/_ops/build/baker-os-v2/05_outputs/flight-dashboards/BB-AUK-001/dashboard-v1-pattern-d.html`.

- Pull vault main first — file took a Director-ordered Page-v2 UI revision (@d658b7b). CONTENT nodes only; keep layout.
- Loan-cost tile: ~EUR 1.66M PROVISIONAL (1,479,416 reserve + 184,650 structuring; v26 coupon BLANK — render "rate pending", never a fixed rate).
- Blockers from D2: signing (~10 Jul) 9 items, RETT ~EUR 2M lead ("zwingend vor Unterschrift", 14-day criminal-report trap); drawdown (~20 Jul) 5 items, Skliar 457.8K + Grundbuch 3-5mo lead.
- Contract v2.1/2.2 rules: verbatim anchor per claim, direction check, as-of doc version+date per tile.
- Stamp "desk validation pending" — desk (baden-baden-desk) validates after; NOT final-final.
- Vault commits are lead's — hand diffs to lead (bus topic `baker-os-v2/audit-round-2`).

**SUPERSEDED / DO NOT REDO:** BOX5_OUTBOUND_CORRELATION_FIX_1 — SHIPPED, PR #448 MERGED 2026-07-01 (verified in main per bus #5548).

Harness-V2: N/A — content-update task fully specified above + in bus thread; no production code.
