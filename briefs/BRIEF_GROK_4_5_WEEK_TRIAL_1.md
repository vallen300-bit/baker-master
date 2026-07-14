# BRIEF: GROK_4_5_WEEK_TRIAL_1 — Option A build (Director-ratified 2026-07-14)

> Consolidated spec corpus for b4 (bus reads are recipient-scoped — #11258 blocker fix).
> Sources reproduced verbatim below (bus previews; #11199 tail truncated in capture — binding
> constraints restated in §Rulings): work order #11199 (codex, Director-CONFIRMED in chat),
> phase-1 inventory #11204 (deputy-codex), phase-2 design #11213 (deputy-codex, Option A ratified).
> Lead dispatch #11256 remains the 5-requirement build order. Gate: b4 G1 -> codex cross-vendor -> lead merge -> staged activation per-route on lead GO.

## LEAD RULINGS on the two open design points (#11258)

**(1) Weekly reservation ledger — persistence shape (RULED):** new migration, table `xai_week_ledger`:
`(id, week_start DATE, route TEXT, kind TEXT CHECK (kind IN ('reserve','settle','release')), amount_usd NUMERIC NOT NULL, request_ref TEXT, created_at TIMESTAMPTZ DEFAULT NOW())`.
Remaining budget = cap − (settled_this_week + open_reserves), computed in ONE transaction with a pg advisory lock keyed on week_start (no in-memory state — order requirement). Reserve BEFORE the call (conservative: max_in + max_out + tool allowance); settle actual + release residual after response; a crashed call's stale reserve expires via a bounded TTL sweep (30 min) — note it in the audit log when swept. Cap 150 USD / warn 120 / hard-block at cap. Do NOT overload api_cost_log for reservations; DO settle actuals into api_cost_log as today (source=grok_realtime) with cost_usd_override from the xAI payload.

**(2) Per-role route flag — mechanism (RULED):** single env `GROK45_ENABLED_ROUTES` = comma-separated route keys (e.g. `b4_runtime,researcher_channel,researcher_shadow_synth`). Default unset = ALL OFF. Each route checks membership at call time. Matches the repo's env-flag idiom; one Render PUT per activation step (remember: env PUT needs a manual deploy — item-A lesson).

## SCOPE ADDITION — researcher (Director GO, chat 2026-07-14 ~13:15Z)

- **researcher_channel:** upgrade the researcher fan-out Grok channel default grok-4.3 -> grok-4.5 WHEN the route flag lists it (exact-model allowlist applies).
- **researcher_shadow_synth:** SHADOW A/B at the synthesizer level — on each fan-out synthesis, ALSO run a grok-4.5 synthesis over the same evidence packs; store the pair for comparison; the DELIVERED report stays Opus 4.8 (#1369 ratified rule intact — shadow only). Label shadow artifacts clearly; shadow spend rides the same weekly ledger.

---

## SOURCE: work order #11199 (codex; Director-confirmed; tail truncated in capture)

DIRECTOR WORK ORDER — execute a 7-day controlled Grok 4.5 trial.

Scope: switch CM-1, CM-2, Librarian, and B4 to the exact xAI model `grok-4.5` for their normal runtime work. For B4 this replaces Opus 4.8; for CM-1/CM-2/Librarian it replaces their present Sonnet route. Do not use Grok 4.3, grok-code-fast-1, or another lower Grok model.

Before activation: inventory every affected route and record its current model, baseline behaviour/cost, and rollback setting. Migrate and validate one independent route at a time: provider ↔ exact model ↔ response/tool-call/schema handling. Preserve prompts, tools, permissions, and approval boundaries.

Trial controls: combined xAI cap is $150 for the full week; warn at $120 and block new Grok calls at $150 using conservative per-request budget reservation. Log exact provider/model, tokens, estimated spend, route, tool/schema result, and outcome. No automatic fallback to another Grok or Claude model; fail loud with route, cause, and spend state. Retain a manual rollback configuration only.

Director accepts xAI processing of business/matter data for this trial. Never send credentials, API keys, passwords, tokens, or control-plane secrets.

Success evidence: accepted task completion, tests/reviewer-reject rate, correction cycles, tool/schema failures, elapsed time, and cost per accepted task, compared with the baseline. Trial ends seven days after live activation; restore previous default routes unless Director explicitly continues it. Send Director a short day-7 report with route inventory, results, spend, defects, and GO/NO-GO recommendation. Do not commit, push, or change provider billing without separate authorization.

---

## SOURCE: phase-1 inventory #11204 (deputy-codex)

GROK_4_5_WEEK_TRIAL phase-1 inventory COMPLETE — inventory only; no activation, no xAI call, no credentials handled. ROUTES: CM-1 — actual launcher ~/.zshrc:40 and ~/bm-CM-1/.claude/settings.json:182 both pin claude-sonnet-4-6[1m]; role doc conflicts/stale at ~/bm-CM-1/CLAUDE.md:5,48 claiming Haiku. Baseline behavior: CM worker, judgment bounces; cost reference Sonnet /M input, /M output in orchestrator/cost_monitor.py:32. CM-2 — ~/.zshrc:41 + ~/bm-CM-2/.claude/settings.json:126 pin claude-sonnet-4-6[1m; same CM behavior/cost. Librarian — ~/.zshrc:54 explicitly claude-sonnet-4-6[1m; registry AG-209 runtime terminal-claude-sonnet; retrieval-only/find-quote-receipt, no interpretation. b4 — ~/.zshrc:36 has NO model flag; picker is ambient. Baker code defaults claude-opus-4-8 via bm-b4/config/settings.py:67,535 and kbl/anthropic_client.py:57, with KBL_ANTHROPIC_MODEL and KBL_STEP5_MODEL overrides; cost reference Opus / per M. No CM/Librarian/b4 LaunchAgent model surface found. ROLLBACK: CM/Librarian restore their ~/.zshrc --model pins/settings; b4 restore KBL_* env overrides to claude-opus-4-8; trial route needs a new feature/config flag because no current Grok route exists in these seats. EXISTING GROK: baker-master kbl/grok_client.py defaults grok-4.3, /v1/responses, XAI_API_KEY env only, no automatic fallback; tools/grok.py returns explicit errors and pre-checks the global daily breaker, then logs source=grok_realtime, model, tokens, matter_slug. Existing cost controls are global daily EUR tiers 30/60/80 and hard-stop 100 in orchestrator/cost_monitor.py:56-66, not an xAI weekly reservation. CONTROLS GAPS / NEW CODE: (1) exact grok-4.5 allowlist/route mapping — current ask model is caller-overridable and default is grok-4.3; no grok-4.5 MODEL_COSTS entry, so cost_monitor would fall to DEFAULT_COSTS / if uncorrected; (2) combined xAI weekly cap + warn + hard-block with conservative pre-call reservation — absent; numeric cap/warn/hard values were blank in received dispatch and need lead clarification before activation; (3) per-call audit currently lacks explicit provider/route/tool-schema/result/outcome and does not pass Grok payload cost_usd as cost_usd_override; new logging fields/code needed; (4) fail-loud/no-auto-fallback behavior exists, but route+cause+spend must be added to the error/audit record. Phase-1 conclusion: route inventory and rollback map ready; activation remains separate lead GO, one route at a time.

---

## SOURCE: phase-2 design #11213 (deputy-codex; Option A = ratified scope)

PHASE-2 DESIGN VERDICT — RECOMMEND A NOW, C ROADMAP; DO NOT BUILD B YET. Bottom line: Option A is the only proportionate first trial; it exercises Baker-runtime Grok calls with reversible controls, while explicitly NOT claiming to switch the interactive Claude seats. A) Baker-runtime route: add exact model allowlist grok-4.5, provider pricing, atomic weekly reservation ledger ( warning /  hard-block), and structured per-call audit. Effort: ~2–3 engineer-days including tests. Risk: low/medium; smallest blast radius, reuses kbl/grok_client + existing cost gate, but CM-1/CM-2/Librarian remain Claude Code Sonnet seats. Activation can be one Baker route at a time behind default-OFF config; rollback is the route flag. B) Anthropic-compatible proxy: literal seat switch through base URL, but proxy must translate Claude Code streaming, tool schemas/results, context, usage, errors, and auth to xAI Responses API. Effort: ~7–12 engineer-days plus staging/shadow conformance. Risk: high; new critical data path, prompt/tool incompatibility, proxy outage, and secret-boundary complexity. No fallback remains a hard requirement. C) Hybrid: A for b4/runtime evidence now, B only after proxy shadow-mode proves protocol parity. Effort: A plus B; risk remains B's risk for CM/Librarian. CONTROLS DESIGN: reserve before call using max input + max output + tool/search allowance; atomically reject when weekly reserved+request > ; settle actual provider spend after response and release unused reservation; warn at . Persist reservations, never in memory. Log provider=xai, exact model, route, tokens in/out, reserved USD, actual USD, tool-schema version/hash, result/outcome, and error class; never prompt bodies or secrets. Existing code has daily global EUR tiers/hard-stop and basic Grok logging, but no weekly reservation, no grok-4.5 allowlist/pricing, and no route/tool/outcome fields. Existing gork client retries bounded 429 transport failures; that is not model fallback; final errors must include route+cause+spend. IMPORTANT: verify grok-4.5 provider pricing before activation; do not reuse grok-4.3 rates by assumption. SCOPE: Phase 2 design only, no activation performed.
