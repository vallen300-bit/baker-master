---
brief_id: AO_FLIGHT_IDENTITY_RECONCILE_1
attempt: 2
status: DELIVERED — 5 ACs done/reported; AC1 escalated to lead, awaiting slug-unification decision
dispatched_by: lead
reply_to: lead + ao-desk (bus topic baker-os-v2/b4-ao-data-preflight)
priority: P1 — blocks B6 AO flight launch
created: 2026-07-07
updated: 2026-07-07
---

# Checkpoint — AO_FLIGHT_IDENTITY_RECONCILE_1 (attempt 2)

Successor: if resuming, the arc is DELIVERED — do NOT redo the prod writes. Only open work is
lead's AC1 decision (see §2). If lead has answered AC1, execute that decision.

## 1. What's done (all verified, prod writes are idempotent-safe on re-run)
- **AC2 PASS** — matter_registry id=15 reshaped: 5->12 people (dropped Edita+Siegfried), 15->42 keywords
  (crossroad RG7/LCG/Baden/Lilienmatt/Annaberg/Balgerstrasse removed), projects->['ao']. Verified.
- **AC4 PASS** — 14 bluewin future-dated rows (all 2035-07-28) clamped to ingested_at (2026-06-10).
  0 future rows remain any source. 14 ids logged in report.
- **AC3 PASS(gap)** — version-stamp insertion point = airport_ticketing_bridge.py:1546-1572; cols exist
  (DDL L1027-28) but absent from INSERT; no version source in lane -> follow-up brief.
- **AC5 PASS(report)** — 24/143 lilienmatt-suspected tickets ref AO principals (Pohanis-dominated);
  leak is ticketing desk-config layer (suspected_matter_slug=_MATTER_ENV), not matter_registry.
- Report: briefs/_reports/B1_AO_FLIGHT_IDENTITY_RECONCILE_1_20260707.md (branch b1/ao-flight-identity-reconcile, pushed).
- Bus: claim #6284; b2 coord #6319 (b2 reply #6320 confirms target='ao', converged); final verdicts lead #6321 + ao-desk #6322.

## 2. Open work — AC1 only (awaiting lead)
- **AC1 PARTIAL/ESCALATED.** H1 slug fragmented across 3 tables: documents=511 'Oskolkov-RG7',
  baker_insights=3 'oskolkov', meeting_transcripts=1 'ao' (canonical; b2 backfilling to 'ao').
- Editing cortex-config.md to 'ao' ALONE would break the 511-doc retrieval -> escalated, not guess-edited.
- DECISIONS from lead: (a) target slug 'ao' all stores? (b) owner of documents/baker_insights re-tag +
  the Tier-B cortex-config.md edit (AH1-owned per write-split)? (c) sequence vs b2's transcript backfill.
- When lead answers YES to unify on 'ao': the re-tag is
  `UPDATE documents SET matter_slug='ao' WHERE matter_slug='Oskolkov-RG7'` (511) +
  `UPDATE baker_insights SET matter_slug='ao' WHERE matter_slug='oskolkov'` (3), THEN align
  cortex-config.md (L4/L55/L139-140) + classifier label map tools/document_pipeline.py:118. Do NOT edit
  cortex-config (Tier-B) without AH1 sign-off. Do NOT touch slugs.yml or meeting_transcripts (b2).

## 3. Lead rulings already folded (do not re-litigate)
- H1 slug canonical = 'ao'; 'oskolkov' alias only; vault folder wiki/matters/oskolkov/ path UNCHANGED.
- Fireflies disabled by design (PR #341, Plaud-only). Sudomoyeva identity -> ao-desk. Transcripts backfill -> b2.

## 4. Key facts (warm)
- matter_registry id=15 AFTER: 12 people, 42 keywords, projects=['ao']; matter_name kept 'Oskolkov-RG7'
  (rename risks name-keyed lookups; flagged cosmetic).
- Tier (name-trigger vs coverage) NOT representable in matter_registry (symmetric people/keywords consumption,
  retriever.py:1409-1459 + scan_prompt.py:244-279); tier lives in box5/project_registry lane (B6 config).
- Crossroad RG7/LCG/Annaberg/Balgerstrasse lack clean sibling keyword homes — dropped from AO, flagged for lead
  (cross-desk add needs owner nod). lilienmatt/baden-baden/mandarin already in id=4/8/6-7.
- Substring-noise WATCH: AO keywords incl short tokens AO/Eli/Ania/George/Anna/Masha (over-match risk).

## 5. Next concrete step
1. Read bus for lead's AC1 answer (topic baker-os-v2/b4-ao-data-preflight).
2. If answered: execute the re-tag per §2 (coordinate cortex-config Tier-B ownership with AH1/lead).
3. If not answered: idle — arc is otherwise complete. No prod writes to redo.
