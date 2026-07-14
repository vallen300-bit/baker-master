# CODE_4_PENDING — active dispatch mailbox for b4

---
status: LIVE — merged @7d51c2dd, activated all 3 routes on grok-4.5, follow-up PR #565 open
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

STATUS: LIVE on grok-4.5. Main brief MERGED @7d51c2dd (PR #563, rounds 1-4 codex
P1s all fixed). POST_DEPLOY_AC PASS (#11425). Director order #11429 (supersede staged
canary): activated ALL 3 routes immediately.

ACTIVATION (Director order #11429) — DONE + AC3 PASS (#11434):
- Env flip (merge-mode PUT via render_env_guard, never array): GROK45_ENABLED_ROUTES=
  b4_runtime,researcher_channel,researcher_shadow_synth on srv-d6dgsbctgctc73f55730.
- Manual deploy dep-d9b5t8beo5us73e0hjg0 (commit 7d51c2dd) → live.
- AC3: governed route=b4_runtime call → grok-4.5, one audit row (provider=xai,
  outcome=ok), ledger reserve→settle→release (0.001146→0.000906, residual 0.000240),
  settle_ok=true. researcher_channel + researcher_shadow_synth also proven grok-4.5.
- Week ledger 2026-07-13: 3 ok calls, effective_used 0.002160 USD, remaining 149.9978
  (cap 150 / warn 120 / fail-closed intact, ledger untouched).

FOLLOW-UP (owed non-gating, codex #11398) — SHIPPED PR #565 (base main):
lazy client_factory — run_grok_ask builds the client only AFTER route+model
validation, so an unknown route with XAI_API_KEY absent still writes
blocked_route_unknown (fixes the double-fault). 80 pass, 12 skipped. Awaiting
codex normal gate → lead merge.

Ship report: briefs/_reports/B4_grok_4_5_week_trial_20260714.md.

**Prior seat state (all CLOSED 2026-07-13/14):**
- ARM_OUT_OF_BAND_ALARM_1 — shipped + merged (PR #556 @codex-PASS #10635 / lead #10639); semantic consumer micro-lane merged; arm-semantic-enforce gate merged @a089d90 (#11197).
- ARM_CADENCE_LAUNCHD_JOB_1 — PR #553 @cb51bf1b, POST_DEPLOY_AC PASS #10363.
- RESEARCHER_FULL_CAPABILITY_PHASE1_1 — vault PR #196 @71a316b, arc FULLY CLOSED (#11150).
- MOHG keyword-bleed fix — arc closed #11188.
- GROK_4_5 quick-gate PR #560/#559 verify — arm-semantic-enforce PASS/merged #11197.
