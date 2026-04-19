# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (app instance)
**Task posted:** 2026-04-19 (afternoon)
**Status:** OPEN — PR #14 review (big one)

---

## Completed since last dispatch

- Task J — PR #13 S1 delta APPROVE (@ `114a2dc`) ✓ **MERGED `bc2efa9f`**
- Task K — Phase 1 burn-in audit (YELLOW @ `e300a49`) ✓ — tx-boundary contract folded into PR #14 per Director ratification

---

## Task L (NOW): Review PR #14 — STEP5-OPUS-IMPL

**PR:** https://github.com/vallen300-bit/baker-master/pull/14
**Branch:** `step5-opus-impl`
**Head:** `8225d0f`
**Size:** 11 files, +3024 lines. Biggest Phase 1 PR.
**Tests:** 70 new (22 anthropic_client + 23 cost_gate + 25 step5_opus) + 373 kbl-scope green + 1 live-API skip
**Spec:**
- KBL-B §4.6 (state machine, I/O)
- KBL-B §9 (cost gate, circuit breaker)
- `briefs/_drafts/KBL_B_STEP5_OPUS_PROMPT.md` @ `fceb22f` (7 worked examples)
- Dispatch brief @ `5ecaecc` with tx-boundary contract (YELLOW remediation)

### Scope

**IN — surfaces to audit:**

1. **`kbl/anthropic_client.py`** — Opus SDK wrapper
2. **`kbl/cost_gate.py`** — CostDecision enum, daily cap, circuit breaker
3. **`kbl/steps/step5_opus.py`** — 3-path router + R3 ladder
4. **`kbl/prompts/step5_opus_system.txt` + `kbl/prompts/step5_opus_user.txt`** — extracted templates
5. **`migrations/20260419_step5_signal_queue_opus_draft.sql`** — `opus_draft_markdown` column + `kbl_circuit_breaker` table
6. **`kbl/pipeline_tick.py`** — `_process_signal` orchestrator + tx-boundary docstring
7. **`kbl/exceptions.py`** — `AnthropicUnavailableError` + `OpusRequestError` (net-additive)

### Specific scrutiny

#### Opus SDK integration

1. **Model ID correctness** — `claude-opus-4-7` default. Env override `KBL_STEP5_MODEL` works. API key from `ANTHROPIC_API_KEY` env, missing = fail-fast at import (not lazy). Verify both paths.

2. **Prompt caching — the critical verification.** System block must have `cache_control={"type": "ephemeral"}` marker. On second identical call, `cache_read_tokens > 0` — B1 claims this is verified. Re-verify the test actually asserts a positive cache hit (mock SDK response with realistic usage values; verify the cache shape, not just `>0`).

3. **Cost derivation from SDK response** — `cost_usd` must come from Anthropic's billing response, NOT heuristic-derived. Verify the code reads `response.usage` directly (or whatever the SDK attribute is) and does not multiply token counts by hardcoded per-1K pricing.

4. **Error surface split** — `AnthropicUnavailableError` for 5xx/429/timeout (retryable); `OpusRequestError` for 4xx user-error (NOT retryable). Verify:
   - 5xx → Unavailable, triggers R3
   - 429 → Unavailable, triggers R3
   - 4xx (e.g., invalid params, bad API key) → OpusRequestError, bypasses R3 → straight to `opus_failed`
   - Network timeout → Unavailable, triggers R3

#### Cost gate + circuit breaker

5. **Daily cap reconciliation** — brief §9.2 had stale `$15` + `USD` naming. Verify PR #14 uses `KBL_COST_DAILY_CAP_EUR=50.00` (Director-ratified). The `cost_usd` column remains (currency-agnostic accounting for Phase 1); module docstring must explicitly note this.

6. **Daily total query correctness** — `SELECT COALESCE(SUM(cost_usd), 0) FROM kbl_cost_ledger WHERE created_at >= <today_00:00_UTC>`. UTC boundary is critical (Director ratified UTC day). Check the timestamp arithmetic — `datetime.now(UTC).date()` or equivalent, not local-time.

7. **Cost estimation conservatism** — `_estimate_step5_cost(signal)` should overestimate (conservative). Verify the function uses the larger of: (a) signal_text length × input pricing, (b) expected output tokens × output pricing. Never underestimate; a last-€ call that exceeds cap is the failure mode we're preventing.

8. **Circuit breaker — in-signal vs across-signal distinction.** The counter increments only on across-signal first-attempt failures. In-signal R3 retries do NOT count. **Verify explicit test for this** — a signal with 3 R3 retries then success should leave the circuit breaker counter at 0, not 3.

9. **Circuit breaker table shape** — `kbl_circuit_breaker` table created by migration. Verify schema makes sense for the 60s-probe-recovery pattern. If the design uses `kbl_log` or a settings kv instead of a dedicated table, verify the choice is documented.

10. **Recovery probe** — 60s probe. If inline, verify it doesn't block a tick indefinitely. If via cron, verify scheduling works.

#### Step 5 routing

11. **3-path routing correctness:**
    - `SKIP_INBOX` → deterministic skip stub written to `opus_draft_markdown`, NO Opus call, NO cost ledger row, state advances to `awaiting_finalize`
    - `STUB_ONLY` → deterministic `status: stub_auto` stub body, NO Opus call, NO cost ledger row, state advances
    - `FULL_SYNTHESIS` → Opus call path
    - Verify cost ledger row count: 0 on stub paths, 1 on full synthesis (success or final R3 fail)

12. **R3 retry ladder order:**
    - Retry 1: **identical** prompt (transient failure recovery)
    - Retry 2: **pared** prompt (drop feedback_ledger_recent only)
    - Retry 3: **minimal** prompt (drop ledger + hot.md; keep signal + extracted entities + Gold context)
    - After 3 fail: `opus_failed` terminal
    - Verify test for each step of the ladder fires the expected pared/minimal prompt body.

13. **State transitions:** `awaiting_opus` → `opus_running` → `awaiting_finalize` (success) / `opus_failed` (retries) / `paused_cost_cap` (gate). All in 34-value CHECK set? Verify.

#### Prompts

14. **Template faithfulness** — `kbl/prompts/step5_opus_system.txt` and `step5_opus_user.txt` match B3's `KBL_B_STEP5_OPUS_PROMPT.md` §1.2 + §1.3 + §3 (worked examples in system block per cacheability). Diff-compare. Flag any silent drift.

15. **Signal truncation at 50K chars** with `[SIGNAL TRUNCATED @ 50000 chars — see source for full text]` marker per Ex 7 shape. Verify.

16. **Inv 10 compliance** — templates file-loaded at module import, not per-call. Verify explicit test over N calls asserting single read.

#### Transaction-boundary contract (YELLOW remediation)

17. **Docstring correctness** — `pipeline_tick.py` module docstring (+ mirrored in each step module) states the contract per §6 of the dispatch brief. Verify wording matches the 5-point spec:
    - (1) BEGIN (implicit)
    - (2) Call step function
    - (3) On success: `conn.commit()`
    - (4) On exception: `conn.rollback()`
    - (5) Step MAY internally commit ONLY to preserve failure-state writes across a raise — must be documented in that step's docstring.

18. **Code matches contract** — audit `_process_signal`:
    - On success: commits exactly once per step (or once at end of full pipeline per design — B1's choice; verify consistency)
    - On exception: rolls back; no partial writes land
    - Failure-state flip commits (Step 1 + Step 4 parse-error-before-raise) are the ONLY internal commits; verify no drift

19. **Tests with MagicMock conn** — verify `test_*` assertions on `.commit()` and `.rollback()` call counts + order + INSERT/UPDATE call sequences. Should be exhaustive.

#### Pipeline_tick orchestration

20. **100-line guardrail** — B1 reports "~70 new orchestrator lines, under 100 guardrail." Verify the count. If over 100, flag as scope breach.

21. **Steps 1-5 wire-up correctness** — `_process_signal` calls Step 1 → 2 → 3 → 4 → 5 in order. Each step's output is the next's input (signal_queue columns). Verify no steps skipped, no out-of-order calls.

22. **Stops at `awaiting_finalize`** — Step 6/7 not implemented; orchestrator must stop and return after Step 5. Verify no attempt to call Step 6.

#### CHANDA

23. **Q1 Loop Test — all 3 Legs touched:**
    - **Leg 1:** `load_gold_context_by_matter(primary_matter, vault_path)` called on every FULL_SYNTHESIS. Zero-Gold returns empty string without crash (Inv 1). Explicit test.
    - **Leg 2:** Step 5 does NOT write feedback_ledger (KBL-C territory). Verify zero writes.
    - **Leg 3:** hot.md + feedback_ledger READ on every synthesize() call — fresh, no cache. Explicit test.
24. **Q2 Wish Test** — prompt caching + cost gate keep Opus honest; Silver→Gold pipeline intact. Wish-aligned.
25. **Inv 8** — stub paths (SKIP_INBOX, STUB_ONLY) produce `author: pipeline` + `voice: silver`. Never `director` / `gold`. Verify via frontmatter inspection in tests.

#### Live-API smoke test

26. **`@requires_api_key` pytest mark** — skips if `ANTHROPIC_API_KEY` not set. ONE real call on minimal signal, verifies cost <€0.01, cache-shape verification. Verify this exists and is marked correctly.

### Format

`briefs/_reports/B2_pr14_review_20260419.md`
Verdict: APPROVE / REDIRECT / BLOCK

### Timeline

~60-90 min. Biggest surface yet; prompt cache + cost gate + Opus client are all new.

### Dispatch back

> B2 PR #14 review done — `briefs/_reports/B2_pr14_review_20260419.md`, commit `<SHA>`. Verdict: <...>.

On APPROVE: I auto-merge PR #14. Step 5 complete.

---

## Working-tree reminder

Work only in `/tmp/bm-b2`. Never Dropbox paths. Do a fresh clone if your local state is stale (`rm -rf /tmp/bm-b2 && git clone git@github.com:vallen300-bit/baker-master.git /tmp/bm-b2`).

---

*Posted 2026-04-19 by AI Head. PR #14 is the cost-spigot open. Review rigorously — first production Opus cost lands after this merges.*
