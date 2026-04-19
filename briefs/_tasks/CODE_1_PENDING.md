# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous:** STEP4-CLASSIFY-IMPL merged at `bc2efa9f`. Director ratified (A) — fold transaction-boundary contract into this brief.
**Task posted:** 2026-04-19 (morning)
**Status:** OPEN — the big one

---

## Task: STEP5-OPUS-IMPL — Claude Opus synthesis + cost gate + transaction contract

**Specs:**
- KBL-B brief §4.6 (state machine, I/O contract)
- KBL-B brief §9 (cost gate, circuit breaker)
- `briefs/_drafts/KBL_B_STEP5_OPUS_PROMPT.md` (B3-authored, B2-APPROVE'd, slug-v9-folded, 7 worked examples @ `fceb22f`)
- B2 Phase-1 burn-in audit @ `e300a49` (YELLOW remediation folded in — see §6 below)

### Why

Step 5 is the highest-stakes + highest-cost step. Real Opus calls. Real €. Director's trust in the Silver→Gold promotion loop depends on the quality of what Opus emits. This PR opens the cost-ledger spigot; every design decision compounds.

### Scope

**IN**

1. **`kbl/anthropic_client.py`** — thin wrapper around the official Anthropic SDK (`anthropic` PyPI package). Surfaces:
   - `call_opus(system: str, user: str, *, max_tokens: int = 4096, extended_thinking: bool = False) -> OpusResponse` where `OpusResponse` is a frozen dataclass with `text`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `cost_usd`, `latency_ms`, `stop_reason`, `model_id`.
   - **Prompt caching enabled.** System block marked `cache_control={"type": "ephemeral"}` — template (§1.2 of B3's prompt) is prompt-cacheable per Anthropic caching rules.
   - Model: `claude-opus-4-7` (1M context). Env override: `KBL_STEP5_MODEL` (default `claude-opus-4-7`; allows burn-in on `claude-sonnet-4-6` if needed).
   - Cost calculation from Anthropic billing response. Do not heuristic-derive — use the `usage` object directly. `cost_usd` from response-level billing.
   - Error surface: `AnthropicUnavailableError(KblError)` net-additive in `kbl/exceptions.py`. Covers HTTP 5xx, 429 rate-limit, connection timeouts, `APIStatusError`. 4xx user-error (malformed request) → `OpusRequestError(KblError)` — distinct, NOT retryable.
   - API key: `ANTHROPIC_API_KEY` env var. Missing → `RuntimeError` at module import (fail-fast; Render deploy catches this at boot).

2. **`kbl/cost_gate.py`** — cost cap + circuit breaker helpers:
   - `can_fire_step5(conn, signal) -> CostDecision` where `CostDecision` is an enum: `FIRE`, `DAILY_CAP_EXCEEDED`, `CIRCUIT_BREAKER_OPEN`. Pre-call gate.
   - Daily cap: `KBL_COST_DAILY_CAP_EUR=50.00` (Director-ratified value; **NOTE brief §9.2 has stale `$15` + `USD` naming — reconcile to EUR and €50 per 2026-04-18 ratification**). Env parse with Decimal, default €50.
   - Daily total query: `SELECT COALESCE(SUM(cost_usd), 0) FROM kbl_cost_ledger WHERE created_at >= <today_00:00_UTC>`. Note: cost column is `cost_usd` — we're treating the value as EUR for Phase 1 (currency-agnostic accounting until Phase 2 reconciles naming). Document this in the module docstring.
   - Estimate function: `_estimate_step5_cost(signal) -> Decimal` — uses signal text length + prompt template length to estimate input tokens, multiply by Opus pricing. Conservative (overestimate) to avoid last-€-call that exceeds cap.
   - Circuit breaker: reads `KBL_CB_CONSECUTIVE_FAILURES` column from a small `kbl_circuit_breaker` table (new migration adds if absent). 3+ consecutive failures = open. Probe every 60s — separate concern, can be a cron job or inline check. Minimal inline version acceptable.
   - Module docstring: circuit breaker trip count is ACROSS-SIGNAL only. In-signal R3 retries (see §3 below) do NOT increment the counter.

3. **`kbl/steps/step5_opus.py`** — the evaluator:

   **Routing by `step_5_decision` (from Step 4):**
   - `SKIP_INBOX` → write deterministic skip stub to `opus_draft_markdown` + advance state. NO Opus call. NO ledger row.
   - `STUB_ONLY` → write deterministic stub body (`status: stub_auto`, `# [stub — low-confidence triage, Director review for promote/ignore]`) + advance state. NO Opus call. NO ledger row.
   - `FULL_SYNTHESIS` → Opus call path.

   **Full synthesis path:**
   - `synthesize(signal_id, conn) -> SynthesisResult` — load signal + all prior-step outputs → build prompt (§1.1 of B3's prompt) → cost gate → Opus call → write draft + ledger row → advance state.
   - State transitions: `awaiting_opus` → `opus_running` → `awaiting_finalize` (success) OR `opus_failed` (retries exhausted) OR `paused_cost_cap` (gate denied).
   - R3 retry ladder (§8 of brief):
     - Retry 1: identical prompt (transient failure recovery)
     - Retry 2: pared prompt (drop `feedback_ledger_recent` block; keep everything else)
     - Retry 3: minimal prompt (drop ledger + hot.md blocks; keep signal + extracted entities + Gold context)
     - After retry 3 fail: `opus_failed` terminal; caller (pipeline_tick) will route to inbox per §7.
   - `AnthropicUnavailableError` triggers R3. `OpusRequestError` (4xx) bypasses R3 and goes straight to `opus_failed` — bad prompt, retrying won't help.

4. **Prompt loader (`kbl/prompts/step5_opus_system.txt` + `kbl/prompts/step5_opus_user.txt`):**
   - Extract the exact `system` and `user` templates from `briefs/_drafts/KBL_B_STEP5_OPUS_PROMPT.md` §1.2 (system) + §1.3 (user) + §3 (worked examples go into the system block for cacheability).
   - File-loaded at module import (Inv 10 compliance). Not regenerated per call.
   - Template placeholders filled via `build_system_prompt()` + `build_user_prompt(signal_text, extracted_entities, primary_matter, related_matters, vedana, triage_summary, resolved_thread_paths, gold_context_by_matter, hot_md_block, feedback_ledger_recent, created_at)`.
   - Signal truncation at 50K chars with `[SIGNAL TRUNCATED @ 50000 chars — see source for full text]` marker per Ex 7 shape.

5. **Migration — `migrations/20260419_step5_signal_queue_opus_draft.sql`:**
   ```sql
   ALTER TABLE signal_queue
     ADD COLUMN IF NOT EXISTS opus_draft_markdown TEXT;
   ```
   No CHECK on this column (free-text markdown). `CREATE TABLE IF NOT EXISTS kbl_circuit_breaker` for the circuit-breaker state if that approach is chosen. Alternative: use `kbl_log` or a settings key-value — designer's choice.

6. **Transaction-boundary contract (Task K YELLOW — folded per Director ratification):**

   **Module-level docstring in `pipeline_tick.py`** (and mirror in each step module's docstring). State the contract explicitly:

   > **Transaction boundary contract.**
   >
   > Each step function (`layer0.evaluate`, `triage.triage`, `resolve.resolve`, `extract.extract`, `classify.classify`, `step5_opus.synthesize`) is **caller-owns-commit**: the step function performs all its DB writes (state UPDATE + cost_ledger INSERT + any column writes) but does NOT call `conn.commit()`. The caller (`pipeline_tick._process_signal`) is responsible for:
   >
   > 1. `BEGIN` (implicit via psycopg2 default)
   > 2. Call the step function
   > 3. On successful return: `conn.commit()` — state + ledger + column writes all land atomically
   > 4. On raised exception: `conn.rollback()` — no partial writes
   > 5. Step functions MAY call `conn.commit()` internally ONLY if they need to preserve a write across a subsequent raise (e.g., the `state='<step>_failed'` flip in the exception handler of Step 1 triage + Step 4 classify — these commit-before-raise so the failure state is durable). This MUST be explicitly documented in the step's docstring.
   >
   > This closes the Inv 2 integration-layer gap surfaced in Task K burn-in audit @ `e300a49`.

7. **`pipeline_tick.py` wire-up (minimum viable):**

   **Not the full orchestrator.** Scope here is minimal so the Step 5 PR stays reviewable: add a `_process_signal(signal_id, conn) -> None` function that implements the transaction-boundary contract for a single signal through Steps 1-5, with explicit commits at step boundaries per §6 above. The existing `pipeline_tick` claim loop can stay a stub or wire in this call if the change is small.
   - **If the wire-up grows past ~100 lines: STOP and split into a follow-up PR.** Flag to AI Head as a B1→AI Head scope redirect. Step 5 PR should not balloon.
   - Steps 6-7 not yet implemented; `_process_signal` stops at `awaiting_finalize` and returns. Follow-up Step 6 PR wires the next hop.

8. **Tests — `tests/test_step5_opus.py` + `tests/test_anthropic_client.py` + `tests/test_cost_gate.py`:**

   - Full coverage of 3 routing paths (SKIP_INBOX + STUB_ONLY + FULL_SYNTHESIS stubs vs Opus call)
   - R3 retry ladder: retry 1 succeeds / retry 2 succeeds / retry 3 succeeds / all retries fail
   - Cost gate decisions: FIRE / DAILY_CAP_EXCEEDED / CIRCUIT_BREAKER_OPEN
   - Circuit-breaker trip + probe-reset cycle
   - `AnthropicUnavailableError` → retry; `OpusRequestError` → no retry, direct fail
   - Prompt caching flag on system block (mock SDK response with `cache_read_tokens > 0`)
   - Transaction-boundary contract: `_process_signal` success path commits once at end; failure path rolls back all writes — use a `MagicMock` conn tracking `.commit()` + `.rollback()` calls and INSERT/UPDATE call order.
   - Signal truncation at 50K chars
   - **CHANDA Inv 1 test:** zero-Gold signal (empty `gold_context_by_matter`) produces valid Opus-callable prompt (doesn't crash, doesn't skip the call)
   - **CHANDA Inv 3 test:** hot.md + feedback_ledger read on every synthesize() call (mirror Step 1's pattern)
   - **CHANDA Inv 8 test:** stub paths (SKIP_INBOX, STUB_ONLY) produce `author: pipeline` + `voice: silver` — never `director` / `gold`
   - Live-API smoke test: `@requires_api_key` pytest mark (skips if `ANTHROPIC_API_KEY` not set) — ONE call to verify real end-to-end on a minimal signal. Keep cost <€0.01.

### Hard constraints

- **`author: pipeline`** + **`voice: silver`** in all Opus outputs (deterministic + stub paths). No Gold emission possible.
- **v9 slugs only** — validation at output parsing time (unknown slug in frontmatter → parse error → counts as R3 retry trigger).
- **Daily cap €50** (Director-ratified; brief §9.2 reconciliation from `$15` is part of this PR).
- **Prompt cache hit rate ≥ 80% in tests** — verify via `cache_read_tokens > 0` on second identical call.
- **No hot.md writes.** Step 5 reads hot.md; never writes to `/Users/dimitry/baker-vault/wiki/hot.md` (Inv 4).

### CHANDA pre-push

- **Q1 Loop Test:** Step 5 reads hot.md + feedback_ledger + Gold context. **All three Legs touched:**
  - **Leg 1:** `load_gold_context_by_matter(primary_matter, vault_path)` called on every FULL_SYNTHESIS. Zero-Gold returns empty string (Inv 1). Explicit test.
  - **Leg 2:** no feedback_ledger WRITE from Step 5 (that's Director-action territory, KBL-C). Read-only.
  - **Leg 3:** hot.md + feedback_ledger READ on every synthesize() call — fresh, no cache. Explicit test.
- **Q2 Wish Test:** serves wish — Opus is the Silver→Gold-track synthesis that Director judges. Cost gate + prompt cache keep cost honest. Wish-aligned.

### Branch + PR

- Branch: `step5-opus-impl`
- Base: `main`
- PR title: `STEP5-OPUS-IMPL: kbl/steps/step5_opus.py + anthropic_client + cost_gate + tx contract`
- Target PR: #14

### Reviewer

B2.

### Timeline

~2-3 hours. Biggest PR of the cascade. Split if you hit 4 hours without clean landing — flag to AI Head as B1→AI Head redirect on scope.

### Dispatch back

> B1 STEP5-OPUS-IMPL shipped — PR #14 open, branch `step5-opus-impl`, head `<SHA>`, <N>/<N> tests green (+live-API smoke if API key present). Prompt cache hit rate <X>%. Transaction-boundary contract documented in pipeline_tick.py + each step module. Ready for B2 review.

### After this task

Next dispatches:
- B2 reviews PR #14 (+ AI Head auto-merges on APPROVE)
- B1 ticket: **STEP6-FINALIZE-IMPL** per B3's spec at `briefs/_drafts/KBL_B_STEP6_FINALIZE_SPEC.md` (after AI Head resolves 8 OQs)
- B1 ticket: **STEP7-COMMIT-IMPL** per KBL-B §4.8
- Then: KBL-C handler tickets (after AI Head ships §4-10 authoring)

---

*Posted 2026-04-19 by AI Head. Director ratified (A) + (2). Cost gate at €50. Transaction-boundary contract folded in per Task K YELLOW remediation.*
