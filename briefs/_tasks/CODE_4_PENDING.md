# CODE_4_PENDING — active dispatch mailbox for b4

---
status: MERGED — POST_DEPLOY_AC PASS (awaiting lead per-route activation GO)
brief_id: GROK_4_5_WEEK_TRIAL
to: b4
from: lead (bus dispatch #11256, Director-ratified Option A)
dispatched_by: lead
dispatched_at: 2026-07-14
reply_target: lead (ack/start/ship/blocker all to lead)
task_class: baker-runtime infra — trial model route with cost governance
gate_plan: build -> G1 -> codex cross-vendor review -> lead merge -> staged activation (route flag default-OFF, lead GO one route at a time)
harness_v2: applies
recommended_effort: high
spec_corpus: bus #11199 (work-order constraints, binding) + #11204 (deputy-codex phase-1 inventory) + #11213 (phase-2 Option-A design) — NOT in b4 mailbox; relay requested from lead #11258
---

# ACTIVE: GROK_4_5_WEEK_TRIAL — dispatch to b4 (bus #11256, lead)

One-week trial of grok-4.5 on Baker-runtime calls, with hard cost governance.
Interactive CM-1/CM-2/Librarian seats stay Sonnet — this trials Baker-runtime
calls only; b4-role runtime is the first activation candidate.

BUILD (5 requirements per #11256):
1. Exact-model allowlist `grok-4.5` for the trial route — no 4.3 fallback, no
   auto-fallback anywhere; fail loud with route + cause + spend.
2. MODEL_COSTS entry for grok-4.5 (real xAI pricing — verify current) so
   cost_monitor prices it correctly.
3. Weekly xAI reservation ledger: cap 150 USD, warn 120, hard-block at cap;
   conservative pre-call reservation (max-in + max-out + tool allowance);
   settle + release after response; PERSISTED (not in-memory).
4. Per-call audit fields: provider=xai, exact model, route, tokens in/out,
   est + actual spend, tool/schema result, outcome.
5. Route flag default-OFF per role — activation = lead GO one route at a time.

STATUS: RE-SHIPPED round 4 — PR #563 (base main). Codex round-4 FAIL #11381 (one
P1): round-3's unknown-route rejection returned early at the dispatcher, skipping
run_grok_ask, so the blocked_route_unknown xai_call_audit row was never written —
zero audit rows on a rejected attempt, violating requirement #4 (one row per attempt
incl. blocked/error). FIXED @1ea845c1: rejection centralized through run_grok_ask —
dispatcher enters the governor for an ENABLED or UNKNOWN route; run_grok_ask writes
exactly one audit row (matter_slug preserved) + raises, surfaced loud, no fallback;
known-but-disabled stays designed grok-4.3 fallthrough (no row); no-route untouched.
Regression extended with audit-row assertion; verified it FAILS on round-3 code.
FREEZE DISCIPLINE (lead #11385, 2nd occurrence): after posting SHIP this round, ZERO
pushes until lead's verdict relay. Prior rounds: round-3 unknown-route downgrade
#11369 @ad773fa1; round-2 P1-3/P1-4/P2 @a9528884→#11338; round-1 2 P1s @e3210423.
All 5 requirements built + researcher substrate. 77 pass, 12 skipped across the 4
grok/xai suites (python3.12). Ship report:
briefs/_reports/B4_grok_4_5_week_trial_20260714.md.

MERGED @7d51c2dd → main (lead #11420). Codex round-5 residual (#11398: with
XAI_API_KEY absent, unknown-route rejection dies at _get_client() before the
blocked_route_unknown audit writes — zero rows on that double-fault) WAIVED as
merge-gating by Director authority (visibility-only, double-fault-only, money path
verified over 4 rounds).

POST_DEPLOY_AC vs live main @7d51c2dd: PASS.
- AC1 (tables exist in prod): xai_call_audit + xai_week_ledger both present.
- AC2 (trial inert, no route enabled): prod baker_grok_ask rejects raw model=grok-4.5
  with the trial-only error (proves new dispatcher code live); normal call serves
  grok-4.3 (cost $0.0003); inert path wrote 0 audit + 0 ledger rows.
- AC3 (first governed reserve→settle+audit row): deferred to lead per-route
  activation GO — no route flips before that.

OWED (non-gating, this week; normal gate): validate/reject+audit BEFORE client
construction (lazy client or pre-_get_client validation) so an unknown route with
XAI_API_KEY absent still writes the blocked_route_unknown row, plus the missing-key
unknown-route regression codex specified (#11398).

**Prior seat state (all CLOSED 2026-07-13/14):**
- ARM_OUT_OF_BAND_ALARM_1 — shipped + merged (PR #556 @codex-PASS #10635 / lead #10639); semantic consumer micro-lane merged; arm-semantic-enforce gate merged @a089d90 (#11197).
- ARM_CADENCE_LAUNCHD_JOB_1 — PR #553 @cb51bf1b, POST_DEPLOY_AC PASS #10363.
- RESEARCHER_FULL_CAPABILITY_PHASE1_1 — vault PR #196 @71a316b, arc FULLY CLOSED (#11150).
- MOHG keyword-bleed fix — arc closed #11188.
- GROK_4_5 quick-gate PR #560/#559 verify — arm-semantic-enforce PASS/merged #11197.
