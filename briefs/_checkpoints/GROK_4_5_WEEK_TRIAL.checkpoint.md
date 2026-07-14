# CHECKPOINT: GROK_4_5_WEEK_TRIAL

attempt: 2
brief_id: GROK_4_5_WEEK_TRIAL_1
branch: b4/grok-4-5-week-trial
dispatched_by: lead (bus #11256); binding spec briefs/BRIEF_GROK_4_5_WEEK_TRIAL_1.md @967a5c7; rulings #11260
updated: 2026-07-14

## Round 2 — RE-SHIPPED with P1-3 / P1-4 / P2 fixes (codex re-gate FAIL #11331 → order #11338)
- Aligned this seat to reviewed PR head a9528884 (dropped a content-identical parallel local commit line 07a6ebd3; verified only unrelated ARM scripts differed, GROK files byte-identical). Head-freeze discipline per #11338.
- P1-3 (UTC week rollover): xai_trial_route.run_grok_ask captures reserve_week once (ledger.week_start()) and threads it through reserve/settle/release. 2 regressions.
- P1-4 (idempotent settle): ledger.settle() checks _has_settle under the per-week lock → no-op (reason=already_settled) on retry-after-lost-ack; partial unique index uq_xai_week_ledger_settle_ref added to migration 20260714a + ensure_ DDL. 2 regressions.
- P2 (unknown routes): is_route_enabled enforces KNOWN_ROUTES; run_grok_ask rejects unknown route loud (route_unknown, distinct from route_disabled) + audit row. 2 regressions.
- Tests: 30 pass, 2 skipped on fresh Postgres scratch (24 prior + 6 new). Singleton guard OK. Compile-clean.
- NEXT: freeze head at re-ship post to lead → codex re-gate → lead merge → POST_DEPLOY_AC.

## What's done — round 1 (PR #563 @e3210423)
- ACK'd #11256 + #11260. Pulled brief. Built all 5 requirements + researcher-substrate.
- Files: cost_monitor grok-4.5 entry; migration 20260714a + xai_week_ledger.py; xai_trial_route.py; tools/grok.py route arg; store_back bootstrap.
- Tests: 24 pass (15 unit + 9 live-PG vs local scratch DB). Singleton guard OK.
- PR #563 opened base main. Ship report briefs/_reports/B4_grok_4_5_week_trial_20260714.md.
- NEXT: bus ship post to lead → codex cross-vendor gate → lead merge → POST_DEPLOY_AC. If codex REQUEST_CHANGES: address on new commit (never amend), re-push, reply on thread.
- codex FAIL #11309 (2 P1s) FIXED @e3210423: P1-1 settle top-up when actual>held (cap counts overspend); P1-2 settle-failure retry+retain+audit=settle_failed. +3 regressions. 24 tests pass fresh PG. Re-ship posted lead.
- grok-4.5 pricing VERIFIED via official xAI docs: $2.00/M in, $6.00/M out; model id exactly `grok-4.5`.

## Binding design (from lead rulings #11260)
1. Weekly ledger = new table `xai_week_ledger` (id, week_start DATE, route TEXT, kind CHECK IN('reserve','settle','release'), amount_usd NUMERIC, request_ref TEXT, created_at). Remaining = cap − (settled_this_week + open_reserves), computed in ONE txn under pg advisory lock keyed on week_start. Reserve BEFORE call (conservative max_in+max_out+tool allowance); settle actual + release residual after; stale reserve TTL sweep 30min (audit-note on sweep). Cap 150 / warn 120 / hard-block at cap. Do NOT overload api_cost_log for reservations; DO settle actuals into api_cost_log (source=grok_realtime, cost_usd_override from xAI payload).
2. Route flag = single env `GROK45_ENABLED_ROUTES` comma-list (b4_runtime,researcher_channel,researcher_shadow_synth). Unset = ALL OFF. Membership check at call time.
- Exact-model allowlist grok-4.5 on trial routes; NO fallback (no 4.3, no Claude); fail loud with route+cause+spend.
- Per-call audit: provider=xai, model, route, tokens in/out, reserved_usd, est_usd, actual_usd, tool/schema result, outcome, error_class. NEVER prompt bodies or secrets.
- SCOPE: researcher fan-out is AGENT-SIDE (researcher SKILL, not baker-master). b4 builds the baker-master SUBSTRATE (route-aware grok-4.5 path + ledger + audit recognizing all 3 route keys). Researcher passing route=researcher_channel / running shadow_synth = separate researcher lane. Flag this in ship report.

## Key files / anchors
- orchestrator/cost_monitor.py:26 MODEL_COSTS (add grok-4.5); calculate_cost_eur:174; log_api_cost:219 (has cost_usd_override); check_circuit_breaker:579 (daily, separate).
- store_back _ensure_cost_and_metrics_tables:411 — add ensure_xai_week_ledger_tables here.
- tools/grok.py:254 dispatch_grok; _log_grok_cost:358 (currently no override). baker_grok_ask model default grok-4.3 at :314.
- kbl/grok_client.py:92 _DEFAULT_MODEL; ask:234; _cost_usd_from_usage:565 HARDCODES grok-4.3 rate as token fallback (undercounts 4.5 unless xAI returns cost_in_usd_ticks) → settle path must price 4.5 via MODEL_COSTS or ticks.
- Migration format: migrations/<YYYYMMDD><letter>_name.sql, BEGIN;...COMMIT;. Latest 20260708a.
- Perplexity allowlist pattern to mirror: tools/perplexity.py:86-98 (PERPLEXITY_MODELS frozenset + schema enum + pre-dispatch check).

## Plan (task list mirrors)
1. MODEL_COSTS grok-4.5 entry. 2. Migration xai_week_ledger + xai_call_audit. 3. orchestrator/xai_week_ledger.py (reserve/settle/release/sweep/remaining under advisory lock). 4. orchestrator/xai_trial_route.py (route flag + allowlist + audit) wired into tools/grok.py dispatch. 5. Tests (unit no-DB + live-PG auto-skip). 6. Ship PR->G1->codex->lead merge->staged activation.

## Gate plan
b4 build -> G1 (self pytest green) -> codex cross-vendor review -> lead merge -> staged activation per-route on lead GO (env PUT + manual deploy). Harness-V2 applies; emit POST_DEPLOY_AC_VERDICT.

## Next concrete step
Write orchestrator/xai_week_ledger.py + migration, then the trial-route module, then tests. cost_monitor grok-4.5 entry is the trivial first edit.
