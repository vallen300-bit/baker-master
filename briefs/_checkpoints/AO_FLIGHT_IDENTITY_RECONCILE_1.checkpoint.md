---
brief_id: AO_FLIGHT_IDENTITY_RECONCILE_1
attempt: 2
status: IN_PROGRESS — AC2+AC4 done; AC1 re-tag scoped to b1 (lead #6325); guard fired -> split proposal awaiting lead ratify (#6331)
dispatched_by: lead
reply_to: lead + ao-desk (bus topic baker-os-v2/b4-ao-data-preflight)
priority: P1 — blocks B6 AO flight launch
created: 2026-07-07
updated: 2026-07-07
---

# Checkpoint — AO_FLIGHT_IDENTITY_RECONCILE_1 (attempt 2)

Successor: DELIVERED core (AC2/AC4 prod writes verified, idempotent-safe). Do NOT redo them.
AC1 re-tag is now b1's (lead #6325 extended Files-Modified). Guard fired — NOT yet executed.
Continue from §2 once lead ratifies the split (#6331).

## 1. Done + verified (idempotent-safe)
- AC2 PASS: matter_registry id=15 -> 12 people (dropped Edita+Siegfried), crossroad keywords removed, projects ['ao'].
- AC4 PASS: 14 bluewin future rows clamped to ingested_at; 0 future remain. Ids in report.
- AC3 PASS(gap): version-stamp insertion point airport_ticketing_bridge.py:1546-1572; no version source -> follow-up.
- AC5 PASS(report): boundary leak is ticketing desk-config layer, not registry.
- Report: briefs/_reports/B1_AO_FLIGHT_IDENTITY_RECONCILE_1_20260707.md (merged PR #477, lead #6325).
- Bus: claim #6284; b2 #6319/#6320 (converged target='ao'); verdicts lead #6321 + ao-desk #6322; lead AC1 GO #6325; split proposal #6331.

## 2. OPEN — AC1 slug re-tag (b1-owned per lead #6325), awaiting lead ratify of split (#6331)
Lead #6325 ruling: target='ao' all stores; documents+baker_insights re-tag = b1; cortex-config = lead (Tier-B, fires LAST);
sequence b2-transcripts -> b1-retag -> lead-cortex-config. GUARD: 511 is legacy COMBINED, sample-first.

**GUARD RESULT (done):** documents 511 = MIXED, ~59% AO-pure -> NOT bulk re-tagging. Proposed deterministic
source_path split to lead #6331 (buckets, sums to 511):
  6_ao=301->ao | 7_rg7_project=54->hagenauer OR new 'rg7' slug (lead decides) | 4_movie=46->mo-vie |
  3_baden_baden=39->baden-baden | 1_hagenauer=17->hagenauer | 2_kitzbuhel_steininger=10->kitzbuhel-alp |
  5_epi_financing=7->tbd | 8_unclassified_manual=37->2nd-pass.
  On lead ratify: `UPDATE documents SET matter_slug=<target> WHERE matter_slug='Oskolkov-RG7' AND <bucket path markers>`
  per bucket, RETURNING ids -> log each bucket's id list. Send bucket 8 to manual, don't guess.

**baker_insights x3 CONFLICT (held):** id 270/271/272 tagged 'oskolkov' are Lilienmatt/MRCI (Baden-Baden) subject,
surfaced via AO WhatsApp. Manifest EXCLUDES Lilienmatt from AO. Re-tag to 'ao' re-introduces crossroad -> b1
recommended baden-baden, NOT ao. Awaiting lead call (#6331). Do NOT re-tag to 'ao'.

**cortex-config.md** = lead's (Tier-B), fires last. Do NOT edit. **slugs.yml** forbidden. **meeting_transcripts** = b2.
Classifier label map tools/document_pipeline.py:118 ('Oskolkov'->'Oskolkov-RG7') needs alignment AFTER re-tag (flag to lead).

## 3. Next concrete step
1. Read bus (topic baker-os-v2/b4-ao-data-preflight) for lead's reply to #6331 (ratify split markers + rg7/epi targets + insights call).
2. Execute the ratified documents split per bucket (logged id lists) + insights per lead's decision.
3. Flag document_pipeline.py:118 label-map alignment. Then final verdict to lead+ao-desk; hand cortex-config to lead.
4. If no reply: idle — nothing to redo; core AC2/AC4 already live.
