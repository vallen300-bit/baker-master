# A-CLEAR AUDIT — Case One delivery-backlog overhang

**Date:** 2026-07-14  ·  **Owner:** deputy (AH2, bus-health owner)  ·  **Authorized:** lead #11101 (GO #11092/#11098-#11101)

## Mechanism (path 1 — epoch bump, zero row mutation)
`semantic_delivery_evaluator.py` obligations + undelivered checks are receipt-epoch-anchored: `resolve_receipt_epoch` (L301) honors the env override; `gather_db_evidence` obligations query filters `r.posted_at >= epoch` (and the undelivered query the same). A-clear executed by bumping Render env `BRISEN_LAB_RECEIPT_EPOCH=2026-07-14T08:00:00Z` (lead lane). No rows mutated; no acks forged; no SQL run.

## Ratified clear-set predicate (lead #11101)
`kind=dispatch AND execute_obligation=TRUE AND acknowledged_at IS NULL AND deleted_at IS NULL AND created_at < 2026-07-14T08:00:00Z`; `kind=ratify_required` EXCLUDED (open Director questions stay honest).

## Excluded (epoch-cleared) IDs as observed — 114 rows
Observed manifestation in the merged delivery-status dataset (554 unique rows, windows to 2026-07-14T09:54Z). The epoch bump is timestamp-authoritative — any pre-cutoff tracked dispatch is excluded whether or not it appears below. ratify_required count in set = 0 (verified).

| message_id | to | kind | posted_at | topic |
|---|---|---|---|---|
| 10079 | deputy | dispatch | 2026-07-13T16:22:33 | gate-2/p2-liveness-lifecycle-regate |
| 10101 | baden-baden-desk | dispatch | 2026-07-13T16:22:33 | airport-ticketing/BB-AUK-001 |
| 10112 | deputy | dispatch | 2026-07-13T16:22:33 | reply/10111-rulings |
| 10117 | lead | dispatch | 2026-07-13T16:22:33 | status/f503b-classified-poolsat-clone-sweep-out |
| 10118 | b3 | dispatch | 2026-07-13T16:22:33 | reply/10114-redeployed |
| 10143 | lead | dispatch | 2026-07-13T16:22:33 | post-deploy-ac/step2-require-envelope-id-pass |
| 10155 | lead | dispatch | 2026-07-13T16:22:33 | airport-ticketing/dorotheergasse-aircon-urgent |
| 10160 | deputy | dispatch | 2026-07-13T16:22:33 | dispatch/researcher-tranche3-item10-fix-routing |
| 10172 | b2 | dispatch | 2026-07-13T16:22:33 | dispatch/case-one-p5-delivery-confirmation-build |
| 10176 | lead | dispatch | 2026-07-13T16:22:33 | gate/item10-clear-to-merge |
| 10178 | deputy | dispatch | 2026-07-13T16:22:33 | dispatch/e23-close-pin-enforcement-scope-add |
| 10180 | deputy | dispatch | 2026-07-13T16:22:33 | dispatch/item12-retarget-laptop-launchd |
| 10191 | b4 | dispatch | 2026-07-13T16:22:33 | dispatch/case-one-e23-build |
| 10195 | b2 | dispatch | 2026-07-13T16:22:33 | dispatch/p5-delivery-confirmation-refire |
| 10211 | deputy | dispatch | 2026-07-13T16:22:33 | ship/case-one-p5-delivery-confirmation |
| 10224 | b2 | dispatch | 2026-07-13T16:22:33 | request-changes/case-one-p5 |
| 10230 | lead | dispatch | 2026-07-13T16:22:33 | ship/arm-clog-client-fix-package-review |
| 10236 | lead | dispatch | 2026-07-13T16:22:33 | scope-ambiguity/ticketing-bridge-eli-joseph-rero |
| 10252 | codex | dispatch | 2026-07-13T16:22:33 | gate-request/ticketing-ao-reroute |
| 10275 | lead | dispatch | 2026-07-13T16:22:33 | post-deploy-ac/ticketing-ao-identity-reroute |
| 10325 | deputy | dispatch | 2026-07-13T16:22:33 | dispatch/arm-custodian-impl-items-1 |
| 10328 | baden-baden-desk | dispatch | 2026-07-13T16:22:33 | airport-ticketing/BB-AUK-001 |
| 10332 | researcher | dispatch | 2026-07-13T16:22:33 | dispatch/bus-revamp-research-3q |
| 10334 | dispatcher | dispatch | 2026-07-13T16:22:33 | airport-checkin/BB-AUK-001 |
| 10337 | deputy | dispatch | 2026-07-13T16:22:33 | dispatch/deputy-role-builder-revamp-queue |
| 10344 | deputy-codex | dispatch | 2026-07-13T16:22:33 | dispatch/arm-model-bounce-opus48 |
| 10363 | deputy-codex | dispatch | 2026-07-13T16:22:33 | post-deploy-ac/arm-cadence-launchd-job-1 |
| 10366 | deputy | dispatch | 2026-07-13T16:22:33 | status/ah2-builder-pinned-handover |
| 10383 | lead | dispatch | 2026-07-13T16:22:33 | arm-flag/general |
| 10413 | lead | dispatch | 2026-07-13T16:22:33 | dispatch/plan-v3-b1-a1-a2 |
| 10421 | lead | dispatch | 2026-07-13T16:52:17 | ship/brisen-lab-canary-cron-1 |
| 10424 | lead | dispatch | 2026-07-13T16:52:17 | reply/charter-A-hold-third-ruling |
| 10433 | b3 | dispatch | 2026-07-13T16:32:13 | scope-ruling-implemented/bus-health-auth-waterma |
| 10481 | researcher | dispatch | 2026-07-13T16:23:53 | dispatch/substack-channel-live |
| 10485 | researcher | dispatch | 2026-07-13T16:28:41 | dispatch/substack-paid-verified |
| 10487 | cowork-ah1 | dispatch | 2026-07-13T16:29:12 | ship/researcher-substack-access-closed |
| 10491 | lead | dispatch | 2026-07-13T16:35:19 | review/pr555-alarm-delivery-fix |
| 10501 | b2 | dispatch | 2026-07-13T16:38:20 | dispatch/researcher-full-reach-cage-widen-1 |
| 10519 | lead | dispatch | 2026-07-13T16:46:08 | ship/pr129-fix-round |
| 10523 | lead | dispatch | 2026-07-13T16:46:56 | researcher-access-lift |
| 10528 | lead | dispatch | 2026-07-13T16:49:25 | researcher-access-lift |
| 10531 | b3 | dispatch | 2026-07-13T16:50:34 | dispatch/pr129-merged-fold3-relay |
| 10533 | deputy-codex | dispatch | 2026-07-13T16:51:17 | dispatch/pr129-deploy-watch |
| 10542 | lead | dispatch | 2026-07-13T16:56:32 | dispatch/pr130-full-sweep-order |
| 10545 | deputy-codex | dispatch | 2026-07-13T17:06:54 | dispatch/plan-v3-b1-a1-a2 |
| 10550 | lead | dispatch | 2026-07-13T16:59:50 | ship/fleet-preflight-gate-1 |
| 10553 | b1 | dispatch | 2026-07-13T17:05:38 | dispatch/pr130-ruling-option-a |
| 10554 | lead | dispatch | 2026-07-13T17:05:53 | airport-ticketing/aukera-annaberg-financing |
| 10555 | deputy-codex | dispatch | 2026-07-13T17:06:20 | dispatch/alarm-fire-email-gap-plus-b1-roll |
| 10568 | lead | dispatch | 2026-07-13T17:11:44 | dispatch/alarm-fire-email-gap-plus-b1-roll |
| 10582 | lead | dispatch | 2026-07-13T17:16:36 | dispatch/alarm-fire-email-gap-plus-b1-roll |
| 10597 | lead | dispatch | 2026-07-13T17:26:02 | airport-ticketing/aukera-annaberg-financing |
| 10605 | deputy | dispatch | 2026-07-13T17:32:48 | dispatch/pr194-merged-night-orders |
| 10607 | lead | dispatch | 2026-07-13T17:31:29 | heartbeat/bus-read-path-false-empty-fix-1 |
| 10622 | deputy | dispatch | 2026-07-13T17:40:05 | dispatch/intent-types-rotate-now-extend-p3 |
| 10623 | lead | dispatch | 2026-07-13T17:42:31 |  |
| 10639 | b4 | dispatch | 2026-07-13T18:15:22 | ship/arm-alarm-semantic-consumer |
| 10650 | deputy-codex | dispatch | 2026-07-13T19:58:04 | dispatch/dispatcher-follow-ups |
| 10651 | lead | dispatch | 2026-07-13T19:58:54 | dispatch/dispatcher-follow-ups |
| 10653 | lead | dispatch | 2026-07-13T20:00:01 | airport-ticketing/aukera-annaberg-financing |
| 10660 | deputy-codex | dispatch | 2026-07-13T20:04:19 | dispatch/alarm-1953z-diagnosis |
| 10661 | lead | dispatch | 2026-07-13T20:04:35 | dispatch/alarm-1953z-diagnosis |
| 10663 | lead | dispatch | 2026-07-13T20:07:49 | status/intent-types-spec-routed |
| 10664 | lead | dispatch | 2026-07-13T20:07:56 | ack/researcher-full-capability-phase1 |
| 10667 | b3 | dispatch | 2026-07-13T20:12:17 | ship/fleet-preflight-gate-1 |
| 10677 | lead | dispatch | 2026-07-13T20:17:43 | arm-flag/general |
| 10678 | researcher | dispatch | 2026-07-13T20:19:49 | probe/gemma-route-researcher-seat |
| 10680 | b1 | dispatch | 2026-07-13T20:24:23 | case-one/plan-v3-a1-status |
| 10688 | lead | dispatch | 2026-07-13T20:26:49 | case-one/dispatcher-status |
| 10704 | lead | dispatch | 2026-07-13T20:34:37 | case-one/preflight-gate-status |
| 10711 | b3 | dispatch | 2026-07-13T20:41:10 | case-one/intent-types-build |
| 10713 | lead | dispatch | 2026-07-13T20:44:52 | case-one/intent-types-build |
| 10716 | b1 | dispatch | 2026-07-13T20:45:52 | codex-verify/e27-read-path |
| 10720 | lead | dispatch | 2026-07-13T20:49:01 |  |
| 10723 | lead | dispatch | 2026-07-13T20:56:43 | case-one/plan-v3-a1-status |
| 10725 | b3 | dispatch | 2026-07-13T20:58:09 | case-one/intent-types-build |
| 10744 | codex | dispatch | 2026-07-13T21:16:26 | review/pr-133 |
| 10746 | b3 | dispatch | 2026-07-13T21:17:58 | case-one/intent-types-build |
| 10751 | b1 | dispatch | 2026-07-13T21:19:40 | codex-verify/daemon-attributed-emission |
| 10754 | lead | dispatch | 2026-07-13T21:21:42 | case-one/daemon-attributed-emission |
| 10770 | b3 | dispatch | 2026-07-13T21:30:12 | case-one/attribution-echo-hygiene |
| 10777 | lead | dispatch | 2026-07-13T21:33:09 | case-one/attribution-echo-hygiene |
| 10780 | lead | dispatch | 2026-07-13T21:44:08 | case-one/attribution-echo-hygiene |
| 10787 | b2 | dispatch | 2026-07-13T23:07:08 | case-one/semantic-evaluator-status |
| 10788 | lead | dispatch | 2026-07-13T23:07:47 | case-one/dispatcher-status |
| 10800 | codex | dispatch | 2026-07-13T23:12:20 | gate/pr196-researcher-full-capability-phase1 |
| 10801 | lead | dispatch | 2026-07-13T23:12:24 | ship/researcher-full-capability-phase1 |
| 10825 | lead | dispatch | 2026-07-13T23:29:29 | findings/ecb13026-b067-46e4-8802-fe7f49bdff24 |
| 10830 | arm | dispatch | 2026-07-13T23:31:07 | case-one/ladder-rescan |
| 10835 | lead | dispatch | 2026-07-13T23:38:31 | case-one/ladder-rescan |
| 10839 | deputy-codex | dispatch | 2026-07-13T23:37:52 | case-one/dispatcher-status |
| 10840 | b1 | dispatch | 2026-07-13T23:39:22 | case-one/ladder-rescan |
| 10846 | b2 | dispatch | 2026-07-13T23:47:08 | case-one/semantic-evaluator-status |
| 10878 | b2 | dispatch | 2026-07-14T05:59:47 | gate-request/semantic-delivery-evaluator-1 |
| 10884 | lead | dispatch | 2026-07-14T06:02:49 | case-one/semantic-evaluator-status |
| 10885 | codex-arch | dispatch | 2026-07-14T06:02:37 | g0/bus-intent-types-1 |
| 10888 | lead | dispatch | 2026-07-14T06:06:13 | g0/bus-intent-types-1-ruling |
| 10893 | deputy | dispatch | 2026-07-14T06:06:17 | g0/bus-intent-types-1 |
| 10898 | lead | dispatch | 2026-07-14T06:07:51 | g0/bus-intent-types-1-ruling |
| 10900 | b3 | dispatch | 2026-07-14T06:07:59 | case-one/lifecycle-insert-attribution |
| 10921 | lead | dispatch | 2026-07-14T06:22:09 | ship/lifecycle-insert-attribution-1-item2 |
| 10922 | b4 | dispatch | 2026-07-14T06:22:44 | gate/pr196-researcher-full-capability-phase1 |
| 10923 | b3 | dispatch | 2026-07-14T06:23:52 | ship/lifecycle-insert-attribution-1-item2 |
| 10924 | deputy | dispatch | 2026-07-14T06:24:20 | g0/bus-intent-types-1-ruling |
| 10926 | lead | dispatch | 2026-07-14T06:25:54 | ship/client-authoritative-read-contract-1 |
| 10927 | codex-arch | dispatch | 2026-07-14T06:26:13 | gate/pr196-researcher-full-capability-phase1 |
| 10929 | codex-arch | dispatch | 2026-07-14T06:26:38 | g0/bus-intent-types-1 |
| 10931 | lead | dispatch | 2026-07-14T06:27:08 | ship/researcher-full-capability-phase1 |
| 10933 | codex-arch | dispatch | 2026-07-14T07:49:45 | g0/bus-intent-types-1 |
| 10941 | lead | dispatch | 2026-07-14T06:30:33 | case-one/semantic-evaluator-status |
| 10956 | b4 | dispatch | 2026-07-14T07:50:15 | gate/pr196-researcher-full-capability-phase1 |
| 10957 | lead | dispatch | 2026-07-14T07:51:11 | g0/bus-intent-types-1-ruling |
| 10962 | lead | dispatch | 2026-07-14T07:54:54 | review/pr-139 |
| 10965 | b2 | dispatch | 2026-07-14T07:59:22 | gate-request/semantic-delivery-evaluator-1 |

**Count by recipient:** lead=50, deputy=13, b3=10, b2=8, deputy-codex=8, b1=5, b4=4, researcher=4, codex-arch=4, codex=3, baden-baden-desk=2, dispatcher=1, cowork-ah1=1, arm=1

## POST_DEPLOY_AC (epoch cutover dep-d9b0unt8, 2026-07-14 ~10:34Z)
Env applied after manual redeploy (Render env PUT does NOT auto-deploy — root cause of the ~25min stall, lead #11135). **Result: PASS-with-finding.**
- receipt_epoch flipped `2026-07-13T16:22:33Z` → `2026-07-14T08:00:00Z`.
- obligation_ack_coherence: 170 → **17**; undelivered_post_epoch: 7 → **1**. A-clear mechanism works.
- **Finding-3 leak CONFIRMED (codex-arch #11125):** 7 pre-cutoff messages leaked past the 08:00Z filter via backfilled receipts (receipt `posted_at` = drain-time NOW, not original message time): **ids 10380, 10503, 10970, 10988, 10990, 10996, 10999** (all <11000; delivery posted_at ≥ 08:00Z). Pre-cutoff status inferred from monotonic serial IDs (no raw SQL per #11101).
- Recommendation: fold into `RECEIPT_WRITE_DURABILITY_1` — anchor the epoch/obligation filter on message `created_at`, not drain-time receipt `posted_at`. Low urgency (switch OFF; count honest at 17).
