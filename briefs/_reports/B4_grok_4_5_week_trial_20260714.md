# B4 Ship Report — GROK_4_5_WEEK_TRIAL_1

- **Brief:** `briefs/BRIEF_GROK_4_5_WEEK_TRIAL_1.md` (bus #11256, lead; rulings #11260; Director-ratified Option A)
- **Branch/PR:** `b4/grok-4-5-week-trial` → **PR #563** (base main) @898e0c8a
- **Date:** 2026-07-14
- **Dispatcher / reply target:** lead
- **Gate:** b4 build → codex cross-vendor review → lead merge → staged per-route activation

## Done rubric (answers, not "tests passed")

| Requirement (#11256) | Status | Evidence |
|---|---|---|
| 1. Exact-model allowlist grok-4.5, no fallback, fail loud w/ route+cause+spend | DONE | `xai_trial_route.run_grok_ask` — model≠grok-4.5 raises `model_not_allowed`; call failure releases reserve + raises `grok_call_failed` (no retry/downgrade). Tests `test_model_not_allowed_fails_loud`, `test_call_failure_releases_reservation`. |
| 2. MODEL_COSTS grok-4.5 real xAI pricing | DONE | `cost_monitor.py` `"grok-4.5": {input 2.00, output 6.00}` — VERIFIED against official xAI docs 2026-07-14 (docs.x.ai/developers/models). Not the 4.3 rate. |
| 3. Weekly reservation ledger: cap 150 / warn 120 / hard-block; conservative pre-call reserve; settle+release; persisted | DONE | `xai_week_ledger.py` + migration `20260714a`. Remaining = cap−(settled+open_reserves) in ONE txn under pg advisory lock on week_start. 30-min TTL sweep. Fail-CLOSED on error. 9 live-PG tests green. |
| 4. Per-call audit: provider/model/route/tokens/est+actual spend/tool-schema/outcome | DONE | `xai_call_audit` table + `_write_audit`; one row per attempt incl. blocked/error. Never prompt bodies/secrets. |
| 5. Route flag default-OFF per role; activation one route at a time | DONE | env `GROK45_ENABLED_ROUTES` comma-list, unset = ALL OFF. `tools/grok.py` gates trial path on `is_route_enabled`. |

## Design decisions (in-role, reversible — surfaced for review)
- **Ledger accounting identity:** open_reserves = Σreserve − Σsettle − Σrelease; effective_used = Σreserve − Σrelease. Settle writes actual + releases residual, so a fully-settled ref nets zero hold. Crashed ref (reserve only) stays held until TTL sweep releases it.
- **actual_usd = max(payload cost_usd, tokens×grok-4.5 rate).** `grok_client._cost_usd_from_usage` falls back to the grok-4.3 token rate when xAI omits cost ticks — that would UNDER-bill 4.5. Flooring on the 4.5 rate ensures the cap is never undercounted; the payload wins when it's higher (authoritative ticks incl. surcharges).
- **Fail-closed reserve, fail-open audit/log.** A cost cap must degrade closed (deny on ledger error); audit/cost-log failures are non-fatal (never block a real call). Opposite polarities on purpose.
- **grok-4.5 is trial-only.** Raw `model=grok-4.5` on the normal path is rejected so no grok-4.5 spend escapes the weekly ledger.
- **New `xai_call_audit` table (not extending api_cost_log).** Keeps the hot daily cost path unchanged (smallest blast radius, Option-A ethos); actuals still settle into api_cost_log via cost_usd_override.

## Scope boundary flagged
Researcher fan-out is **agent-side** (researcher SKILL, not baker-master). This PR is the baker-master **substrate** that governs any Grok call tagged with an enabled trial route (recognizes all 3 route keys). The researcher passing `route=researcher_channel` and running the shadow synth is a **separate researcher lane** — not in this baker-master build.

## Tests
- `tests/test_xai_trial_route.py` — 15 unit (route flag, allowlist, reserve math, actual-USD floor, orchestration, dispatcher guards).
- `tests/test_xai_week_ledger.py` — 3 unit + 9 live-PG (reserve/settle/release, cap hard-block, warn, stale sweep, no double-sweep).
- Local run: `24 passed` (live-PG against local Postgres scratch DB `baker_ledger_scratch`; 2 mcp-dep dispatcher tests skip locally, run in CI). Singleton guard OK. All touched files compile-clean.

## POST_DEPLOY_AC plan (emit verdict to lead after merge+deploy)
1. Tables `xai_week_ledger` + `xai_call_audit` exist in prod (store_back bootstrap on boot).
2. `GROK45_ENABLED_ROUTES` unset ⇒ trial inert: `baker_grok_ask` still serves grok-4.3; raw `model=grok-4.5` rejected.
3. On first route activation (lead GO, env PUT + manual deploy): one governed call reserves→settles, writes an `xai_call_audit` row, mirrors into `api_cost_log`; weekly remaining math correct.

## Activation runbook (staged, lead-owned)
- Set `GROK45_ENABLED_ROUTES=b4_runtime` via single-key Render env PUT (`tools.render_env_guard.safe_env_put` — never array PUT) + **manual deploy** (env PUT alone does not restart).
- Add routes one at a time (`,researcher_channel`, `,researcher_shadow_synth`) on subsequent GOs.
- Rollback = remove the route from the env list (+ deploy). Optional caps via `BAKER_XAI_WEEKLY_CAP_USD` / `_WARN_USD` / `BAKER_XAI_RESERVE_TTL_MIN`.
