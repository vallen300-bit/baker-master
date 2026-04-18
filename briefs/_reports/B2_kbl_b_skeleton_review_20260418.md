# KBL-B Skeleton Structural Review (B2)

**From:** Code Brisen #2
**To:** AI Head
**Re:** [`briefs/_tasks/CODE_2_PENDING.md`](../_tasks/CODE_2_PENDING.md) — KBL-B §1-3 structural scrutiny before Director ratification
**Skeleton reviewed:** [`briefs/_drafts/KBL_B_PIPELINE_CODE_BRIEF.md`](../_drafts/KBL_B_PIPELINE_CODE_BRIEF.md) @ commit `fb334f5`
**Date:** 2026-04-18
**Time spent:** ~35 min

---

## 1. Verdict

**REDIRECT NEEDED** — but on a small surface. §1 and §3 are largely sound; §2 has three step-decomposition issues worth resolving before §4-13 lands on top.

The blockers below are not "rip up the architecture" — they're "lock down ambiguities now so the §4+ author isn't compounding wrong defaults." Total redirect work is ~30 min of skeleton revision plus one Director ratification call.

---

## 2. Blockers (category errors)

### B1 — Step 4 (`classify`) is a redundant LLM call

**Location:** §2 Step 4.

The brief defines Step 4 as: "Decide whether this signal warrants Step 5 (heavy Opus synthesis) or lighter handling." It then enumerates four decisions:

| Step 4 decision | Where the data already exists |
|---|---|
| **arc continuation** | Step 2 output: non-empty `resolved_thread_paths` ⇒ continuation, by definition |
| **new arc** | Step 2 output: empty `resolved_thread_paths` ⇒ new arc, by definition |
| **noise-that-survived** | Step 1 output: `triage_score` close to threshold ⇒ low-value (deterministic numeric check) |
| **multi-matter** | Step 1 output: `related_matters[]` non-empty ⇒ multi-matter (deterministic list check) |
| **Layer 2 gate** | Brief's own §1.2 says "1-line env-var check at Step 5 entry" — not LLM work |

Every decision Step 4 makes is **inferable from Step 1+2 outputs via deterministic Python**. The brief itself describes Step 4 as a "small decision prompt" — that's the smell. If a "small decision prompt" doesn't read any new content, only restates what prior steps already structured, it's not doing semantic work.

**Why this is a blocker, not a should-fix:** if §4-13 is written assuming Step 4 is an LLM call, you get:
- A prompt to maintain in §6
- A retry/failure mode in §7
- A cost-ledger row even though local models are "free" (still latency cost: ~2s/signal × 50/day = ~2 min/day cumulative latency on a serial pipeline)
- A schema column (`step_5_decision TEXT`) that's actually a derived value
- Test scaffolding for a step whose logic is `if/elif/else`

**Fix.** Two acceptable shapes:
- **(a)** Drop Step 4 as a discrete pipeline step. Move the decision into a `_decide_step5_path()` Python function that runs at the head of Step 5 (or end of Step 3). The 4-value decision becomes a derived column or a runtime variable.
- **(b)** Keep Step 4 in the 8-step taxonomy for parity with the ratified `cost_ledger.step` enum (§D14), but mark it as "deterministic-only, no model call" — a Python policy step. Then prompts/retries/cost-ledger semantics for it collapse to no-op.

Either choice is fine for the architecture; **choose explicitly before §4+** so §6 (prompts) and §7 (error matrix) are written against the right step count.

The cost-ledger enum already lists `classify` (§DECISIONS_PRE_KBL_A_V2 line 732), so dropping it would touch ratified text. Option (b) is the lower-blast-radius fix — keep the name, drop the model call.

---

### B2 — `paused_cost_cap` vs circuit breaker is double-counted

**Location:** §2 Step 5 failure modes, §3.2 status list.

The brief says:
> "Cost cap hit mid-day → circuit breaker → status `paused_cost_cap`, re-queue tomorrow"

But these are **two different mechanisms** in KBL-A:
- **Circuit breaker** (D14, KBL-A §1062): trips on 3+ consecutive Anthropic failures (502/529), sets `kbl_runtime_state.anthropic_circuit_open='true'`, halts the entire pipeline until a recovery probe succeeds.
- **Daily cost cap** (D14, `KBL_COST_DAILY_CAP_USD=15`): per-signal pre-call estimate against ledger sum; if projected total > cap, that single Step 5 call doesn't fire, signal re-queues for next day.

The first is a global pipeline pause; the second is a per-signal defer. They have different semantics, different re-entry conditions, different `kbl_log` shapes. Conflating them in the brief means §7 (error matrix) and §9 (cost-control integration) will get the recovery logic wrong.

**Fix.** Two-line clarification in §2 Step 5: separate "Anthropic-side failure → circuit breaker" from "Estimate exceeds cap → `paused_cost_cap`, deferred". §5 should pin down whether `paused_cost_cap` is a `state` value or its own status (collapse design implication — see §3 Q3 vote below).

---

## 3. Should-fix (structural tightenings)

### S1 — Step 6 (Sonnet polish) lock-in vs. opt-in

**Location:** §2 Step 6.

The brief justifies splitting Opus and Sonnet because "Opus produces content; Sonnet produces vault-canonical form." Defensible, but borderline:

- **Cost saving** is real but small: Sonnet 4.6 at ~$3/M input ÷ Opus at ~$15/M = 5x cheaper for the polish pass. On ~1-3K tokens of polishing work × 50 signals/day, saving = ~$0.50-1.00/day. Daily cap is $15. So Step 6 saves ~3-7% of cap.
- **Architectural cost** is real and recurring: extra prompt to maintain (§6), extra failure mode (§7), extra schema column (`final_markdown` vs `opus_draft_markdown`), extra retry path, extra latency.
- **Quality argument** (Opus reasons, Sonnet formats) is plausible but unverified. Could be tested cheaply in shadow mode by running both shapes ("Opus alone" vs "Opus → Sonnet") on the same 50 signals.

**Fix.** Don't lock in. Make Step 6 opt-in via env flag `KBL_STEP6_SONNET_ENABLED=true|false` (default `true` to preserve current design). Director can A/B in shadow mode. This costs you 5 lines of code in §8 (model config wiring) and gains future-Director optionality. If you ratify §2 as "8 steps no folding," the flag retrofit becomes a follow-up — cheap to do later but cheaper to bake in now.

---

### S2 — Step 2 (`resolve`) should be source-specific, not uniform embeddings

**Location:** §2 Step 2.

The brief: "Full-text similarity search over existing `wiki/<primary_matter>/*.md` using embeddings (Voyage AI voyage-3)." Rejected lexical because "too brittle on transcripts."

That justification is right for transcripts, wrong for the other two sources:

| Source | Best resolution mechanism | Why |
|---|---|---|
| Email | `In-Reply-To` / `References` headers + Subject `Re:` chain + sender/recipient set | Email threading is a solved problem; metadata is authoritative. Embeddings are overkill. |
| WhatsApp | Group ID / chat ID + last-N-message sliding window per matter | Chat-thread membership is structural, not semantic. |
| Meeting transcripts | Embeddings (lexical brittle, no Re: chain) | Brief is right here. |
| Scan queries | Director's own context — embeddings against recent wiki entries | Brief is right. |

**Why this matters for §3:**
- Voyage cost is negligible per call (~$0.00005), so this isn't a money issue
- It IS a hot-path latency issue: embedding API call adds ~50-200ms per signal. On Email/WA, that's pure waste
- It also creates an unnecessary external-dependency hop on the critical path: if Voyage AI is down, Email/WA pipelines stall when they don't need to

**Fix.** §2 Step 2 should describe Resolve as a strategy pattern with per-source resolvers. Three lines in the skeleton; concrete impl lands in §4. The brief already has §1.4 listing source-specific Layer 0 rules — Step 2 should follow the same per-source shape.

---

### S3 — Status collapse (§3.2) ratification needs migration spec, not just yes/no

**Location:** §3.2.

Collapse `status` (24 values) → `stage` (10) + `state` (4) is **directionally right**, but ratifying it as "just do it" without a migration plan creates a data-shape problem that §5 will inherit:

KBL-A is already deployed with `status` populated for live rows. Existing values like `'pending'`, `'processing'`, `'done'`, `'classified-deferred'`, `'failed-reviewed'`, `'cost-deferred'` (per KBL-A §290-292) **don't map cleanly to (stage, state)** pairs:

| Existing `status` | Cleanest (stage, state) target | Drift risk |
|---|---|---|
| `pending` | (`layer0`, `awaiting`) | OK if Layer 0 always runs first |
| `processing` | ??? | which stage? `triage`? `extract`? |
| `done` | (`commit`, `done`) | OK |
| `classified-deferred` | (`classify`, `done`) + side flag? | Loses the "deferred" semantic |
| `failed-reviewed` | (`?`, `failed`) + reviewed flag? | Drops orthogonal signal |
| `cost-deferred` | (`opus_step5`, `paused_cost_cap`) | "Paused" needs to be a state value |

Naive collapse loses orthogonal data (`reviewed`, `deferred`). The right move is one of:
- **(a) Migration with explicit value mapping** — 6×24 mapping table in §5, backfill SQL, downtime window
- **(b) Two-track** — keep `status` for legacy, add `stage`+`state` for KBL-B-pipeline rows. New writes use new columns; old reads continue working. Drop `status` after a deprecation window.

Either is fine. **Don't ratify Q3 as "yes" without picking (a) or (b).** I lean (b) — lower blast radius, no backfill risk.

---

### S4 — Schema TOAST hygiene for markdown columns

**Location:** §3.1.

Two new columns are TEXT for full markdown: `opus_draft_markdown`, `final_markdown`. PostgreSQL TOASTs them transparently, but they bloat row size for any `SELECT *` query. After commit, the canonical form lives in `baker-vault/wiki/` so the PG copies are intermediate.

**Fix.** Add to §3.1 a one-line note: after `committed_at` is set, NULL out `opus_draft_markdown` and `final_markdown`. Frees TOAST storage immediately, doesn't wait for the 30-day TTL on `done` rows. Keeps debugging info during pipeline run, drops it once the wiki entry is canonical.

This is also implicit guidance to §10 (test plan): test that intermediate columns are correctly nulled post-commit.

---

## 4. Nice-to-have

### N1 — Layer 2 enforcement location ambiguity

§1.2 says Layer 2 ALLOWED_MATTERS is a "1-line env-var check at Step 5 entry." §2 Step 4 says "Layer 2 gate fires here."

Pick one. They're describing the same check; the brief says it twice and the locations don't agree. Probably an artifact of writing §1 then §2. Reconcile in skeleton revision pass.

### N2 — `kbl_threads` table — don't build it

The brief asks (§2 Step 2 "Open question") whether to add a `kbl_threads` table. **No** — `wiki/<matter>/` filesystem tree + embeddings is the source of truth. A `kbl_threads` table would be derived state that drifts. Keep the vault canonical.

This is a non-issue but worth resolving in skeleton so §3 doesn't sprout it.

### N3 — JSONB → dedicated columns for `extracted_entities`

Brief asks: should `primary_money_amount NUMERIC` / `primary_deadline TIMESTAMPTZ` be promoted out of JSONB?

**No, not yet.** Promote when actual queries demand them (likely KBL-C dashboard filters). The "primary money" concept is also leaky — a contract amendment legitimately lists 5 figures; "primary" requires extraction logic to pick one. Defer until a query exists that needs it. JSONB + `jsonb_path_ops` GIN index handles ad-hoc filtering fine for Phase 1.

### N4 — GIN index on `resolved_thread_paths` is fine

Brief asks whether GIN on JSONB performs for the queries we'd run. Yes for `@>` containment ("which signals resolved to this thread path"). The alternative normalized lookup table (`signal_thread_paths(signal_id, thread_path)`) is faster on read but adds a table + sync logic. Defer normalization until dashboard queries are slow (which they won't be at Phase 1 volumes).

### N5 — Stale doc reference

§1.4 references "§DECISIONS_PRE_KBL_A_V2.md §732" for the 8-step canonical list. Verified — line 732 is the cost-ledger `step` enum which lists exactly the 8 steps + ayoniso. Reference is correct. (Just confirming since these line refs rot fast.)

### N6 — Estimate "~2000-3000 lines of Python" plausibility

KBL-A landed at ~1700 lines of Python + ~600 of schema/migrations + ~400 of tests, per repo state. KBL-B has more steps and more model integrations but each step is structurally simpler than KBL-A's runtime+ledger+circuit-breaker triumvirate. **2000-3000 feels right; possibly 2500 ± 500.** Plausible.

---

## 5. The 4 ratification asks — my votes

### Ask 1 — Ratify §1.2 scope (KBL-C handlers + ayoniso OUT)

**Vote: YES.**

Scope boundary is clean. KBL-B produces wiki entries; KBL-C surfaces them via WA/dashboard/ayoniso. The split matches D2 (Gold promotion in KBL-A) and the ratified pipeline taxonomy. The only ambiguity is the Layer 2 enforcement location (see N1) — N1 fix is internal to §1+§2 wording, not a scope-line shift.

### Ask 2 — Ratify §2 flow (8 steps, no folding/splitting)

**Vote: REDIRECT.**

Three changes wanted before §4-13 lands:
- **Step 4 (classify)** — drop the LLM call, keep the step name as a deterministic policy step (B1 above)
- **Step 6 (sonnet polish)** — env-flag opt-in not hardcoded (S1 above)
- **Step 2 (resolve)** — source-specific resolver pattern (S2 above)

These are not "rip up the 8 steps" — the taxonomy stays. They're "lock down step semantics so §6 prompts are written against the right model-call count."

If Director ratifies "8 steps locked, address B1/S1/S2 in §5+," that's also acceptable — same destination, slower path.

### Ask 3 — §3.2 status collapse (`stage` + `state`)

**Vote: YES IN PRINCIPLE — with explicit migration spec required in §5.**

Direction is right: 24-value CHECK is unwieldy and loses orthogonal information (e.g., `failed-reviewed` mixes failure with review state). But ratifying as "just do it" without picking the migration shape (full backfill vs two-track legacy+new) creates a known-unknown that §5 has to resolve under time pressure.

My weak preference: **two-track**. Keep `status` for legacy compat (existing 8-value CHECK stands), add `stage`+`state` columns for KBL-B-pipeline rows. New code reads/writes new columns; old code keeps working. Deprecate `status` after Phase 2 burn-in.

### Ask 4 — §3.3 `kbl_pipeline_run` observability table

**Vote: INCLUDE in KBL-B.**

Three reasons:
- Cost is essentially zero (~70K rows/year at 8/hour)
- Shadow-mode validation (§12 will need this) requires the metrics layer to exist before dashboard ships, so KBL-C can query historical data on day one
- Without `kbl_pipeline_run`, debugging "why did the pipeline only complete 30 of 50 signals last night" requires reconstructing from `kbl_log` — possible but painful

The table is small and bounded; defer-to-KBL-C is the wrong trade.

---

## 6. Open architectural questions to flag for §4-13

Pre-flagging so the §4-13 author has reader context queued. None of these are blockers for §1-3 ratification.

1. **§5 — Claim semantics under (stage, state) collapse.** KBL-A's claim query is `WHERE status='pending' FOR UPDATE SKIP LOCKED`. Post-collapse, what's the equivalent? `WHERE state='awaiting' AND stage=<next_for_this_signal> FOR UPDATE SKIP LOCKED`? How does the worker know which stage is "next"? Implicit in row order, or explicit `next_stage` column?

2. **§5 — Migration spec for existing `status` rows.** Per S3 above. Pick (a) backfill or (b) two-track and write the SQL.

3. **§6 — Prompt-caching strategy across local-LLM steps.** Triage, extract, classify (if kept) all use the same Gemma/Qwen instance. Anthropic prompt caching doesn't apply to Ollama. Is there a local equivalent worth wiring (KV cache reuse via Ollama context preservation)? If not, document explicitly so §6 doesn't waste effort.

4. **§7 — Per-signal global retry cap.** If Step 1 fails 3x and Step 5 fails 3x for the same signal, total retry cost = 6 calls. What's the global cap per signal-pipeline-run? `KBL_PIPELINE_MAX_RETRIES_PER_SIGNAL=8`?

5. **§8 — Token budget per Opus call.** D14 caps daily aggregate; is there a per-call cap to avoid runaway prompts (e.g., a thread with 50 neighbor entries blows the input window)? Suggest `KBL_OPUS_MAX_INPUT_TOKENS=200000` or similar guardrail.

6. **§9 — `kbl_cost_ledger.estimate_before_call` API.** Does this helper exist in KBL-A, or does §9 design it? If KBL-A, link the existing function. If new, define interface.

7. **§10 — Test fixture determinism.** End-to-end 10-signal fixture needs Ollama + Anthropic stubbed deterministically. Replay recorded responses (per-signal JSON fixtures), or live-call with `temperature=0`? Recorded is faster + more reliable; live is closer to prod. Pick.

8. **§11 — Per-step `kbl_log` row spec.** What level/component/message shape per step? Likely a 9-row table in §11 (one per step + one per failure mode).

9. **§12 — Shadow mode mechanics.** Does the pipeline run end-to-end and write to `baker-vault/wiki/_shadow/<matter>/`, or does it run but suppress vault commits, only landing in PG? The first lets Director eyeball the wiki entries; the second is purer no-side-effects.

10. **§13 — "KBL-B done" numerical thresholds.** % signals completing pipeline? % matching Director-labeled outcomes from D1 set? Cost/signal target (mean and p95)? Latency target (mean signal end-to-end)?

11. **`paused_cost_cap` vs circuit breaker semantics.** Per B2 above — pin down which mechanism handles which failure shape, and whether `paused_cost_cap` is a `state` value or a separate `status` value (collapse design implication).

12. **`kbl_pipeline_run` columns.** Brief lists `run_id, started_at, ended_at, signals_claimed, signals_completed, signals_failed, circuit_breaker_tripped`. Worth adding: `total_cost_usd` (rolled up from `kbl_cost_ledger`), `mean_signal_latency_s`. Both are dashboard-essentials; cheap to capture at run-end.

---

## 7. Summary

- **Verdict:** REDIRECT NEEDED (small surface — §2 step semantics).
- **Blockers:** 2 (Step 4 redundancy; cost-cap vs circuit-breaker conflation).
- **Should-fix:** 4 (Step 6 opt-in; per-source Step 2; status collapse migration spec; TOAST hygiene).
- **Nice-to-have:** 6.
- **Ratification votes:** **Ask 1 YES**, **Ask 2 REDIRECT**, **Ask 3 YES with migration spec**, **Ask 4 INCLUDE**.
- **Open §4-13 questions:** 12 pre-flagged for downstream reader context.

§1 and §3 are largely sound. §2 needs one Director call (lock 8 steps as taxonomy + agree to fold Step 4's LLM-call out + Step 6 opt-in) before §4-13 should be written. That call probably takes 5 minutes once Director sees this report alongside yours.

The skeleton's biggest strength: it's honest about what it's deferring. §4-13 outlines are explicitly empty rather than half-written. That's the right shape for "let's catch category errors first."

---

*Reviewed 2026-04-18 by Code Brisen #2. Skeleton at `briefs/_drafts/KBL_B_PIPELINE_CODE_BRIEF.md` @ `fb334f5`. Cross-checked against `briefs/DECISIONS_PRE_KBL_A_V2.md` (D3 §247, D14, cost-ledger enum §732) and `briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF.md` (signal_queue schema §279-297, status CHECK §289-292, circuit breaker §1062). No code changes; design review only.*
