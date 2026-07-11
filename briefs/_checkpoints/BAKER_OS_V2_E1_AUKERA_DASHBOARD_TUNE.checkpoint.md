---
brief_id: BAKER_OS_V2_E1_AUKERA_DASHBOARD_TUNE
attempt: 2
owner: b2
dispatched_by: lead
work_target: baker-vault (STAYS ON main — branch-lock rule #5857; do NOT branch the shared vault)
work_file: ~/baker-vault/_ops/build/baker-os-v2/05_outputs/flight-dashboards/BB-AUK-001/dashboard-v1-pattern-d.html
updated: 2026-07-07
---

# E1 Aukera flight-dashboard TEMPLATE pass — checkpoint

## STATUS: DONE — content 12/12 + v9 language pass (arc complete; awaiting any further review)
- v7 (10/12): vault commit **fdd6518** → Page v7. Ship #5991.
- v8 (2/2 parked closed): cowork-ah1 ruling #5993 folded → vault commit **1214d8e**, Page v8. Closure #6014/#6015.
- v9 (rule-10c language pass): cowork-ah1 #6096 (Director walls-of-text complaint) → vault commit **868b66d** (pushed origin/main), Page v9.
  8 flagged business-page walls + MRCI note bulletized (one thought per bullet); 3 more unflagged walls caught via DOM scan; SWITCH + MRCI stamp tightened; 2 rule-10b abbrev cleanups. Language only — figures preserved. Ship #6109 (cowork-ah1), #6110 (lead).
- Verified each pass in Chrome (render + DOM sentence-count scan → 0 business walls + layout); tag balance clean; no German/abbrev leak.
- Resume/gap marker: #5982. Nothing open on this arc.

## What's done
- Attempt 1 (session #5925) posted a respawn but NEVER committed a checkpoint or the
  b2/e1-aukera-dashboard-tune branch — both were lost. This attempt-2 checkpoint fixed that gap.
- Read both governing inputs: BB desk findings memo + verbatim loan-cost tile lock.
- Applied 10/12: NOISE-2 (rule-7 loan-cost verbatim reframe, all instances), MISSING-1 (as-of
  anchors), MISSING-5/NOISE-4 (LTV revision-pending badge + basis note), NOISE-1 (comms counts
  desk-estimated badge), NOISE-5 (Engine-Lab snapshot label), MISSING-4 (new What-changed matter
  feed on Overview), MISSING-6 (writer stamps), NOISE-3 (2+1-year gloss), NOISE-6 (countdown softened).
- PARKED for cowork-ah1 ruling: MISSING-2 (section-4 boarding counter — live vs '0 not built'),
  MISSING-3 (section-5b research rows — add vs honest-empty).

## What's left (the 12 content findings to apply to dashboard-v1-pattern-d.html)
MISSING (6): 1[HIGH] rule-9a family+version on KPI tile receipts; 2[HIGH] section-4 honest
"0 — not built (step-2)" boarding counter (confirm w/ cowork-ah1 if collapsed into Engine Lab);
3[MED] section-5b research-received row (b3 sweep + ESG) or keep honest-empty; 4[MED] section-6
Director-facing "What changed this week" matter-event feed on Overview (distinct from Engine-Lab
build feed); 5[MED] rule-9c STALE/revision-pending badge on LTV + collateral tiles; 6[LOW] rule-4
updated-by actor on Overview attention + KPI cards.
NOISE (6): 1[HIGH] rule-5 hand-typed comms msg/urgent counts — badge "desk-estimated, not ledger";
2[HIGH] loan-cost tile — RENDER VERBATIM from corrected block (below); 3[MED] rule-10b gloss
"2+1-year term" once; 4[MED] LTV basis note on KPI tile (37% on 33.1M secured, not 38.6M whole);
5[LOW] Engine-Lab ticket counts label "snapshot — live query in step-2"; 6[LOW] soften countdown
to "may slip — see land register".

## Key paths
- Work file: dashboard-v1-pattern-d.html (Page v6, ~75KB)
- Findings: _ops/build/baker-os-v2/05_outputs/flight-dashboards/BB-AUK-001/E1-content-pass-findings-bbdesk-20260706.md
- VERBATIM tile: .../decide-now-loan-cost-tile-CORRECTED-bbdesk-20260706.md (render exactly, do NOT re-derive numbers)
- Rules: .../content-contract-v2.md (v2.4, rules 1-11)
- Spec-change (open/go/attention cards): .../spec-change-open-go-attention-cards-cowork-ah1-20260706.md

## Next concrete step
Read content-contract-v2.md + dashboard-v1-pattern-d.html structure; then apply NOISE-2 (verbatim
loan-cost tile) first (highest severity rule-7), then MISSING-1 + NOISE-1 (receipt/ledger integrity),
then the rest. Commit vault edits atomically on main (branch-lock). Two scope-confirm items for
cowork-ah1/lead: MISSING-2 (section-4 surface) + MISSING-3 (5b research rows).
