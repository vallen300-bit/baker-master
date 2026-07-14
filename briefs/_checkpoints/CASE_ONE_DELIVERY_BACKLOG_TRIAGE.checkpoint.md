# CHECKPOINT — CASE_ONE delivery-backlog-triage queue (deputy)

seat: deputy (AH2, Claude Opus 4.8, 1M) — fresh seat, resumed lead #11022 6-item queue
updated: 2026-07-14 ~10:23Z
source-of-truth queue: vault branch deputy/checkpoint-11022-workqueue @bd4c801 (`_ops/agents/aihead2/session-checkpoint-2026-07-14-delivery-triage.md`)

## Seat identity (resolved)
Fresh seat = CANONICAL (lead #11052: original pid 16839 DEAD; #11047 stand-down SUPERSEDED). No duplicate.

## DONE (do NOT redo)
- **(2) 16-thread triage** — reported #11056; corrected #11069; lead accepted #11071. Net open lead decisions = ZERO (aircon #10155 closed; #10236→b1 Option A; BB-AUK #11073 disposed as ARM infra mis-routes; #10433 watermark-rider flagged, lead gets deputy-codex confirm).
- **(3) PR #557 verify** — verdict #11062: #557 is client-read-only, does NOT cover delivered_at-NULL receipt drops (separate gap). Lead accepted.
- **(4) B-tune brief** — BRIEF_CASE_ONE_BTUNE_STARTED_SLO_TERMINAL_1 + companion BRIEF_CLIENT_STARTED_EMISSION_1. Amended per lead #11076 (supersedes note / kill-switch default-OFF + 5-step arming ladder / companion+rubric9). Lead PASS #11092; MERGED to main @48e84ec7.
- **(5) A-clear** — path-1 epoch bump confirmed (semantic_delivery_evaluator epoch-gated). Lead set BRISEN_LAB_RECEIPT_EPOCH=2026-07-14T08:00:00Z (#11110). Audit artifact briefs/_reports/A_CLEAR_AUDIT_2026-07-14.md @7ea3637 (114 IDs).
- **(6) HV2-BL-001** — REMOVED from queue → deputy-codex (#11057).

## DONE since first checkpoint
- **(A) POST_DEPLOY_AC epoch flip = PASS-with-finding** (verdict #11157, ACCEPTED #11158). Render env PUT does NOT auto-deploy (root cause of ~25min stall; lead manual-deployed dep-d9b0unt8). receipt_epoch flipped to 2026-07-14T08:00:00Z; obligations 170→17; undelivered 7→1. **Finding-3 leak CONFIRMED:** 7 pre-cutoff ids (10380/10503/10970/10988/10990/10996/10999) leaked via drain-time backfilled receipts → RATIFIED to fold into RECEIPT_WRITE_DURABILITY_1 (anchor filter on message created_at). Logged in A_CLEAR_AUDIT_2026-07-14.md @753e788.
- **(B) PR #142 correctness gate = PASS** (verdicts #11126/#11132/#11149/#11157). Coherence (exclude ratify_required) CHANGE-REQ ratified → deputy-codex fixed @a2d5cf8 (dispatch-only predicate + regression test) → I re-verified PASS. Kill-switch default-OFF, receipt_missing bucket, rubric-complete tests, schema (finding-6) all PASS. **Lead MERGED @9c8e689 switch-OFF (#11158); ENFORCE arming HELD for drill gate.**

## PENDING (owned)
- **AUTHORING QUEUE (lead #11158) — ✅ BOTH DRAFTED + POSTED TO LEAD #11200 @b39e5c7 (2026-07-14 ~11:36Z), awaiting lead line-read:**
  1. **FLEET_DEPLOY_PARITY_1** ✅ authored `briefs/BRIEF_FLEET_DEPLOY_PARITY_1.md`. baker-master host-side: `--check` repo↔deployed sha256 parity (gap = `install_arm_alarm_job.sh:55-58` proves parse not match) + `arm_fleet_manifest.json` + read-only `arm_fleet_parity.sh` (missing=RED) + F3 db_unreachable/DEGRADED→RED-with-names (findings 1/2/8) + F4 MISSING_IS_RED ladder flip (finding-4) gated on two-sided drill.
  2. **RECEIPT_WRITE_DURABILITY_1** ✅ authored `briefs/BRIEF_RECEIPT_WRITE_DURABILITY_1.md`. brisen-lab: R1 bounded idempotent retry on `record_delivery_receipts_sync` (db.py:1079) over F-503/E1 class + fail-loud drop log (closes #557 delivered_at-NULL gap); R2 swap 3 epoch filters `r.posted_at`→`m.created_at` (semantic_delivery_evaluator.py:379/403/434, m already joined) fixing finding-3 leak (7 IDs).
  3. **DEFAULT_FLIGHT_INFRA_FILTER_1** (lead #11221, acked — bumped as brief #3; AUTHOR AFTER lead reviews #1+2). 3rd occurrence #11218: ARM recovery email mis-minted via **participant-identity path + default-flight fallback** ("keyword fix can't touch this path"). Spec direction (lead): infra-sender/subject filter UPSTREAM of mint (ARM/watchdog/canary subjects + self-originated ops mail), OR default unmatched infra → a review lane that is NOT a real matter flight. **Scoped (ready to author):** `orchestrator/airport_ticketing_bridge.py` — `_DEFAULT_FLIGHT="aukera-annaberg-financing"` (:61), env fallback `:759`, participant-identity fetch lane BOX5_GATE2 (:194/:445/:971/:1951-1963 — routing defaults downstream to _DEFAULT_FLIGHT). Prior family: BB-AUK-001 mis-route #10554/#10597/#10653 + b1 #10236.
  - **NEXT on this queue:** await lead review of #11200 → on PASS, lead assigns builders (cross-vendor codex correctness gate before merge, #9255) → deputy runs live AC + POST_DEPLOY_AC_VERDICT v1 as bus-health owner. Then author brief #3. ⚠️ Watch: `a089d90` #560 ARM semantic ENFORCE gate landed meanwhile — adjacent to FLEET_DEPLOY F3/F4; flagged to lead, confirm no scope overlap.
- **(C) Correctness gate b1 client-started-emission** — BLOCKED: no PR pushed yet (only @27857c18 WIP ref, not fetchable). Gate when b1 pushes. Cross-vendor (I authored the brief). b1 scope confirmed dispatch-only (correct side of the coherence issue).
- **Finding-9 (Monday-audit watch):** tomorrow's credential rescan is CONDITIONAL — flag in the Mon 09:30Z Harness-V2/gold-audit run.

## Mechanics / discipline
- Bus read-path FLAPS (F-503/E27): retry check_inbox 3-4x; full bodies via unread-window fetch loop (since=<recent> limit=500 unread=true); ack POST /msg/<id>/ack (retry on 000/503). Reply-to-sender (lead) on all verdicts.
- Vault writes: shared ~/baker-vault stays on main; isolated worktree only (#157).
- brisen-lab clone for diffs: ~/bm-b3-brisen-lab (git checkout origin/main -- <file>).
- No raw SQL against bus DB (lead #11101).

## Bus refs
Seat-resolve #11052 · triage #11056/#11069/#11071 · PR557 #11062 · brief PASS #11092 · A-clear ruling #11101 / executed #11110 / report #11108 · coherence flag #11124 / verdict #11126.
