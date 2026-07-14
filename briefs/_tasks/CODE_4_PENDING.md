# CODE_4_PENDING — active dispatch mailbox for b4

---
status: ACTIVE
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

STATUS: RE-SHIPPED round 3 — PR #563 (base main), head FROZEN @ad773fa1. Codex
round-3 FAIL #11369 (one residual P1): unknown route bypassed the PRODUCTION
dispatcher — GROK45_ENABLED_ROUTES=bogus_route + route=bogus_route silently called
grok-4.3 (silent downgrade). is_route_enabled() returns False for an unknown route,
so tools/grok.py fell through to the normal grok-4.3 path; run_grok_ask's own
unknown-route rejection was never reached. FIXED @ad773fa1: dispatcher now rejects
an unknown route LOUD (route_unknown) before the governed branch; known-but-disabled
still falls through to grok-4.3 (designed, kept); no-route path untouched. Added
is_route_known() helper + dispatcher-level regression via the tools/grok.py entry
(verified it FAILS without the guard). Round-2 P1-3/P1-4/P2 fixed @a9528884→#11338;
round-1 2 P1s @e3210423. All 5 requirements built + researcher substrate. 77 pass,
12 skipped across the 4 grok/xai suites (python3.12). Ship report:
briefs/_reports/B4_grok_4_5_week_trial_20260714.md. Awaiting codex re-gate →
lead merge → POST_DEPLOY_AC.

**Prior seat state (all CLOSED 2026-07-13/14):**
- ARM_OUT_OF_BAND_ALARM_1 — shipped + merged (PR #556 @codex-PASS #10635 / lead #10639); semantic consumer micro-lane merged; arm-semantic-enforce gate merged @a089d90 (#11197).
- ARM_CADENCE_LAUNCHD_JOB_1 — PR #553 @cb51bf1b, POST_DEPLOY_AC PASS #10363.
- RESEARCHER_FULL_CAPABILITY_PHASE1_1 — vault PR #196 @71a316b, arc FULLY CLOSED (#11150).
- MOHG keyword-bleed fix — arc closed #11188.
- GROK_4_5 quick-gate PR #560/#559 verify — arm-semantic-enforce PASS/merged #11197.
