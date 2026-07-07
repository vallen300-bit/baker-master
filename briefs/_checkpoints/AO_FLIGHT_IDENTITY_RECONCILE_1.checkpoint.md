---
brief_id: AO_FLIGHT_IDENTITY_RECONCILE_1
attempt: 2
status: DONE (b1 scope) — all 5 ACs delivered + AC1 re-tag executed; only cross-owned follow-ups remain (lead/ao-desk/desks)
dispatched_by: lead
reply_to: lead + ao-desk (bus topic baker-os-v2/b4-ao-data-preflight)
priority: P1 — blocks B6 AO flight launch
created: 2026-07-07
updated: 2026-07-07
---

# Checkpoint — AO_FLIGHT_IDENTITY_RECONCILE_1 (attempt 2)

Successor: b1 scope is COMPLETE. All writes verified + idempotent-safe. Do NOT redo anything.
Remaining work is owned by lead / ao-desk / desks (see §3), NOT b1. If a NEW b1 dispatch lands, treat separately.

## 1. Done + verified (all prod writes idempotent-safe)
- **AC2 PASS** — matter_registry id=15 -> 12 people (dropped Edita+Siegfried), crossroad keywords removed, projects ['ao'].
- **AC4 PASS** — 14 bluewin future rows clamped to ingested_at; 0 future remain. Ids in report.
- **AC3 PASS(gap)** — version-stamp insertion point airport_ticketing_bridge.py:1546-1572; no version source -> follow-up brief.
- **AC5 PASS(report)** — boundary leak is ticketing desk-config layer (suspected_matter_slug=_MATTER_ENV), not registry.
- **AC1 DONE** — lead #6325/#6333 extended scope to b1; guard fired (511 MIXED ~59% AO). Executed lead-ratified source_path split:
  documents 454 re-tagged (ao 301, hagenauer-rg7 71, mo-vie-am 46, mrci 22, steininger 10, lilienmatt 4) + 57 held
  Oskolkov-RG7 (manual-pass: 37 unclassified + 13 baden-only + 7 EPI). Verified: 7 slugs sum to exactly 511, ao=301 (was 0),
  no pre-existing collision. baker_insights x3 (270/271/272) oskolkov->lilienmatt (Lilienmatt/MRCI subject; 0 oskolkov remain).
  DEVIATION: bucket-3 was 39; only 26 clean matches re-tagged (lilienmatt 4 + mrci 22), 13 bare-'baden' were mixed -> manual.

## 2. Artifacts
- Report (full, incl AC1 execution + Appendix A 57-row manual listing): briefs/_reports/B1_AO_FLIGHT_IDENTITY_RECONCILE_1_20260707.md
  (branch b1/ao-flight-identity-reconcile, pushed; predecessor report merged PR #477).
- Bus trail: claim #6284; b2 #6319/#6320 (converged 'ao'); verdicts #6321/#6322; lead GO #6325; split proposal #6331;
  lead ratify #6333; AC1 completion #6363/#6364; ao-desk directives #6361; reconciliation #6366.

## 3. Remaining follow-ups — NOT b1 (do not execute)
- **cortex-config.md** slug flip L4/L55/L139-140 -> 'ao' = lead/AH1 (Tier-B). Now SAFE (docs=ao). Fires last per #6325 sequence.
- **Classifier label map** tools/document_pipeline.py:118 ('Oskolkov'->'Oskolkov-RG7') keeps minting combined label on NEW docs
  -> decision needed (can't do the path-split). Flagged to lead. Follow-up brief.
- **Manual-pass 57** (held Oskolkov-RG7) -> desk routing (Appendix A has per-doc hints). Not launch-blocking per lead.
- **Manifest/brief oskolkov->ao realignment** = ao-desk (their #6361 directive #4).
- **Irina Sudomoyeva identity** = ao-desk (room-source hunt, their #6361).
- **AC3 version-stamp** + **bluewin date-parser root cause** + **substring-noise tuning** (AO/Eli/Ania) = separate follow-up briefs.

## 4. Next concrete step
- None for b1 — scope complete. If lead confirms cortex-config flipped, the H1 unification is fully closed for B6.
- Idle until a new dispatch. No prod writes to redo.
