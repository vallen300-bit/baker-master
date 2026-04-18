# KBL-B Pipeline — Code Brief (SKELETON / DRAFT)

**Status:** SKELETON — §1-3 only. §4-N await Director ratification.
**Author:** AI Head
**Date:** 2026-04-17 (original), 2026-04-18 (amendments applied)
**Purpose of skeleton:** surface architecture decisions early so Director can redirect scope before per-step detail is written.

**Amendments 2026-04-18 (post B2 review at commit `abcae4a`):**

- §2 Step 2 — resolver is now **source-specific** (email/WA use metadata, transcripts/Scan use embeddings). Removes unnecessary Voyage dependency on email/WA hot path.
- §2 Step 4 — **no LLM call**. Deterministic policy step derived from Step 1+2 outputs. Step name preserved for `kbl_cost_ledger.step` enum parity; prompt/retry/cost-row collapse to no-op.
- §2 Step 5 — **cost-cap and circuit-breaker separated**. Per-signal cost-cap defer (`paused_cost_cap`) is distinct from global circuit breaker (KBL-A §1062).
- §2 Step 4 — Layer 2 enforcement location reconciled: canonical location = inside `_decide_step5_path()` at the Step 4→5 boundary (§1.2's "1-line env check at Step 5 entry" is the implementation shorthand).

**Deferred from B2 review to §5+ AI Head judgment** (fast-path per Director 2026-04-18):
- S1 Step 6 Sonnet opt-in flag
- S3 status-collapse migration spec (will pick two-track per B2's lean in §5)
- S4 TOAST hygiene on `opus_draft_markdown` / `final_markdown` post-commit

**Reading time:** ~10 minutes.

---

## 1. Purpose + Scope

### 1.1 What KBL-B is

KBL-B implements the **8-step pipeline** that turns a raw signal (email / WhatsApp / meeting transcript / Scan query) into a compiled-wiki entry under `baker-vault/wiki/<matter>/`. KBL-A gave us the skeleton (schema, runtime, config, cost ledger, logging). KBL-B gives us the brain.

This is the largest brief in the Cortex 3T series by code volume and model-call complexity. Realistic estimate: ~2000-3000 lines of Python across `kbl/steps/*.py`, ~600 lines of schema/migrations, ~400 lines of tests.

### 1.2 What KBL-B is NOT

- **Not KBL-C.** Interface layer (WhatsApp user-facing handlers, ayoniso alert dispatch, dashboard) is out of scope. KBL-B produces wiki entries; KBL-C surfaces them.
- **Not model selection.** D1 decides Gemma vs Qwen; this brief assumes whichever wins D1 retry. Skeleton written model-agnostic.
- **Not slug registry.** SLUGS-1 owns `baker-vault/slugs.yml` + `kbl.slug_registry`. KBL-B consumes the registry; does not redefine slugs.
- **Not Gold promotion.** Gold-promote worker (`kbl-gold-drain.sh`) is KBL-A. KBL-B writes the initial wiki entries; Director promotes via WA reply → KBL-C → `gold_promote_queue`.
- **Not Layer 2 ALLOWED_MATTERS enforcement.** That's a 1-line env-var check at Step 5 entry. Already specified in KBL-A brief §485. KBL-B wires it, does not design it.

### 1.3 Canonical 8 steps (from `DECISIONS_PRE_KBL_A_V2.md` §732)

```
layer0 → triage → resolve → extract → classify → opus_step5 → sonnet_step6 → claude_harness (commit)
```

Plus `ayoniso` (alerts) runs async off Step 6 — **that's KBL-C**, not KBL-B.

### 1.4 Ratified decisions KBL-B inherits (don't re-open)

- **D1:** Model for Step 1 (Triage) — Gemma 4 8B or Qwen 2.5 14B cold-swap (retry pending)
- **D2:** Gold promotion via `gold_promote_queue` PG table + Mac Mini cron drain
- **D3:** 3-layer matter scoping — Layer 0 per-source filter + Layer 1 classifier + Layer 2 ALLOWED_MATTERS gate at Step 5
- **D5:** Serial `claude -p` harness via flock mutex
- **D14:** Cost tracking via `kbl_cost_ledger` + daily cap `KBL_COST_DAILY_CAP_USD=15` + circuit breaker
- **D15:** Logging — local rotating + PG WARN+ + alert dedupe + heartbeat
- **R3:** Retry ladder for Opus Step 5 / Sonnet Step 6 (Anthropic 529/overloaded: temp=0 first retry, pared prompt on second)
- **Cost ledger enum:** `layer0 | triage | resolve | extract | classify | opus_step5 | sonnet_step6 | claude_harness | ayoniso`
- **Triage threshold:** `KBL_PIPELINE_TRIAGE_THRESHOLD=40` gates Step 2+ (below → route to `wiki/_inbox/`)

---

## 2. 8-step flow summary

One paragraph per step. I/O contracts (precise JSON schemas per step) land in §5 (later).

### Step 0 — `layer0` (per-source deterministic filter)

**Purpose:** Drop obvious noise before any LLM touches it. 10-30% of signals drop here (not the 30-50% earlier estimated — per R2 recalibration).

**Per-source rules** (ratified D3 §247):

- **Email:** sender allowlist + blocklist; unsubscribe-pattern detection; LinkedIn/newsletter auto-drop; Baker self-analysis dedupe (recent B3 labeling surfaced 7 duplicates in 50 signals — real problem)
- **WhatsApp:** group vs DM split; automated-number blocklist; forwarded-chain detection
- **Meeting transcripts:** minimum content threshold (skip garbled or <N-word transcripts); internal-only meetings pattern match
- **Scan queries:** Director's own queries never Layer-0 drop; pass-through

**Output:** `signal_queue.status = 'dropped_layer0'` with `kbl_log` row explaining which rule fired, or `status = 'awaiting_triage'` with `started_at` set.

**Model calls:** 0. Pure deterministic Python.

**Cost:** 0.

### Step 1 — `triage` (local LLM classifier — D1 target)

**Purpose:** Assign `primary_matter` + `related_matters` + `vedana` + `triage_score` (0-100). This is what the D1 eval measures.

**Model:** Gemma 4 8B (primary) or Qwen 2.5 14B (cold-swap fallback) — via Mac Mini Ollama HTTP API. Post D1 retry we know which.

**Prompt:** Uses `kbl.slug_registry.active_slugs()` for matter enum + Director's vedana rules (already in `run_kbl_eval.py` post-SLUGS-1). Production prompt is a thin wrapper around the eval prompt.

**Threshold:** `triage_score ≥ KBL_PIPELINE_TRIAGE_THRESHOLD` (default 40) → proceed to Step 2. Below threshold → route to `wiki/_inbox/` as low-confidence, stop pipeline.

**Output:** `signal_queue` columns populated (`primary_matter`, `related_matters`, `triage_confidence`); `kbl_cost_ledger` row with step='triage', cost_usd=0 (local).

**Failure modes:**
- Ollama unreachable → circuit breaker trip (KBL-A wired); signal re-queues, pipeline paused
- Invalid JSON from model → 1 retry with pared prompt (R3 ladder); still invalid → status `triage_invalid`, route to inbox
- Model returns slug not in registry → `slug_registry.normalize()` returns None → treated as `primary_matter=null` → inbox route

### Step 2 — `resolve` (entity + thread resolution)

**Purpose:** Identify whether this signal is part of an existing "thread" (e.g., a multi-email chain about `hagenauer-rg7`, an ongoing dispute arc) or starts a new one. Without this, Step 5 rewrites context the wiki already has.

**Mechanism — source-specific resolver pattern (per B2 review S2):**

| Source | Resolver | Rationale |
|---|---|---|
| Email | `In-Reply-To` / `References` headers + Subject `Re:` chain + sender/recipient set | Email threading is solved metadata; embeddings are waste |
| WhatsApp | Group/chat ID + last-N-message sliding window per matter | Chat-thread membership is structural |
| Meeting transcript | Embeddings (Voyage AI voyage-3) over `wiki/<matter>/*.md`, top-3 with similarity ≥ threshold | Lexical is brittle on transcripts; no Re: chain |
| Scan query | Embeddings over recent wiki entries under Director's matter context | Free-form, no metadata anchor |

Implementation: a `Resolver` strategy dispatched by `signal.source`. Concrete impl in §4.

**Output:** `signal_queue.resolved_thread_paths JSONB` (new column, see §3). `kbl_cost_ledger` row: step='resolve', cost_usd = 0 for email/WA (metadata-only), ~$0.00005 for transcript/scan (Voyage embedding).

**Operational implications:**
- Email/WA: zero external-dependency hops. No Voyage-down stall risk.
- Transcript/Scan: inherits Voyage availability; degraded mode = skip resolve, start fresh thread. KBL-B §7 spec'd.

**Closed:** no `kbl_threads` table. `wiki/<matter>/` filesystem tree + source-specific resolvers = source of truth. (Per B2 N2.)

### Step 3 — `extract` (structured entity extraction)

**Purpose:** Pull structured facts from raw content: named entities (people, companies, monetary figures), dates/deadlines, action items, reference numbers (contract IDs, invoice numbers, case numbers).

**Model:** Local LLM (same as triage — Gemma/Qwen). Separate prompt from triage to keep each step focused.

**Why not fold into Triage:** Step 1 must be *fast* (it's on the critical path for every signal, including ones that get dropped at Layer 2). Extraction is expensive JSON scaffolding. Splitting = 2x prompt cost on surviving signals but 0 cost on dropped ones.

**Output:** `signal_queue.extracted_entities JSONB` — structured payload. Schema: `{"people": [...], "orgs": [...], "money": [...], "dates": [...], "references": [...], "action_items": [...]}`.

**Failure modes:** same as Step 1.

### Step 4 — `classify` (deterministic policy step — NO LLM CALL)

**Revised per B2 review blocker B1 (2026-04-18):** this step was originally specified as an LLM call but every decision it makes is derivable from Step 1+2 outputs via deterministic Python. Keeping the step name for parity with the ratified `kbl_cost_ledger.step` enum (D14 §732), but eliminating the model call, prompt, retry ladder, and cost-ledger row.

**Purpose:** Decide whether this signal warrants Step 5 (heavy Opus synthesis) or lighter handling. Decisions are fully derivable from prior-step outputs:

| Decision | Derivation (deterministic Python) |
|---|---|
| **Arc continuation** | Step 2 output `resolved_thread_paths` is non-empty ⇒ continuation |
| **New arc** | `resolved_thread_paths` is empty ⇒ new arc |
| **Noise-that-survived** | Step 1 `triage_score` within N points of threshold (e.g., 40-45) ⇒ low-value, write stub only |
| **Multi-matter** | Step 1 `related_matters[]` non-empty ⇒ Step 5 emits cross-links |
| **Layer 2 gate** | Env check: `primary_matter ∉ KBL_MATTER_SCOPE_ALLOWED` ⇒ route to `wiki/_inbox/`, skip Step 5 |

**Implementation:** a `_decide_step5_path(signal_queue_row) → Step5Decision` function invoked at the head of Step 5 (or end of Step 3). Collapses to `if/elif/else` — no prompt, no model call.

**Model:** none. Policy-only.

**Cost:** zero tokens, zero USD. `kbl_cost_ledger` emits no row for this step.

**Output:** `signal_queue.step_5_decision TEXT` ∈ `{'full_synthesis', 'stub_only', 'cross_link_only', 'skip_inbox'}` — set by the policy function, still persisted for observability.

**Failure modes:** none (deterministic). Input validation failures (e.g., `triage_score` somehow NULL despite Step 1 success) raise programming-error exception, alert via `kbl_log`.

**Layer 2 enforcement location — reconciled (per B2 N1):** §1.2 and §2 Step 4 both reference Layer 2. Canonical location = here, at the classify step. §1.2's "1-line env check at Step 5 entry" is the implementation shorthand; physically, the check runs inside `_decide_step5_path()` which sits at the Step 4→5 boundary.

### Step 5 — `opus_step5` (the heavy one)

**Purpose:** Claude Opus reads the signal + thread context + extracted entities and synthesizes a wiki-entry draft in Markdown + frontmatter.

**Model:** `claude-opus-4-7` (1M context). Prompt includes:
- Signal raw content
- Top-3 neighbor wiki entries (from Step 2)
- Extracted entities (from Step 3)
- Any existing entry being updated (if arc continuation)

**Cost control (two distinct mechanisms — revised per B2 blocker B2):**

- **Per-signal cost-cap defer** (`kbl_cost_ledger.estimate_before_call`): pre-call estimate against running daily total. If projected total > `KBL_COST_DAILY_CAP_USD=15`, **this signal's Step 5 does not fire**, signal transitions to `paused_cost_cap`, automatically re-queues next day. This is a **per-signal defer**, not a global pause.
- **Global circuit breaker** (D14, KBL-A §1062): trips on 3+ consecutive Anthropic-side failures (502/529/overloaded). Sets `kbl_runtime_state.anthropic_circuit_open='true'`, **halts the entire pipeline** until a recovery probe succeeds. This is a **global pause**, not per-signal.

These are separate KBL-A mechanisms, separately wired, with different re-entry conditions. §7 (error matrix) and §9 (cost-control integration) must keep them distinct.

Prompt-caching on system prompt + stable context (slug list, vedana rules) applies in both cases.

Retry ladder (R3) on 529/overloaded within a single signal: temp=0 retry, pared prompt retry, then fail-this-signal. Three retries within one signal contribute to circuit-breaker-consecutive-failure count.

**Output:** `signal_queue.opus_draft_markdown TEXT` + `kbl_cost_ledger` row with actual tokens + cost.

**Failure modes (disjoint):**
- **Per-signal cost cap** → state = `paused_cost_cap`, re-queue next day (no circuit breaker involvement)
- **Anthropic unavailable (Nth consecutive)** → global circuit breaker trips → pipeline paused, signal returns to claimable pool pending recovery
- **Anthropic unavailable (within retry ladder, signal-specific)** → R3 retry ladder; if still failing after 3 tries → `opus_failed`, route to inbox with log (does NOT trip circuit breaker unless pattern repeats across signals)
- **Output doesn't parse as valid frontmatter + body** → 1 retry (pared prompt), then inbox

### Step 6 — `sonnet_step6` (refine + frontmatter + cross-links)

**Purpose:** Sonnet 4.6 (cheaper than Opus) polishes Opus's draft — fixes frontmatter, adds `related_matters[]` cross-links, validates tone/style, adds vault-canonical metadata (source IDs, timestamps, author='pipeline').

**Model:** `claude-sonnet-4-6`.

**Why a second pass:** Opus produces content; Sonnet produces vault-canonical form. Splitting keeps Opus focused on reasoning (expensive) and Sonnet on structural polish (cheap).

**Output:** `signal_queue.final_markdown TEXT` + `signal_queue.target_vault_path TEXT` (e.g., `wiki/hagenauer-rg7/2026-04-17_ofenheimer-demand-letter.md`).

### Step 7 — `claude_harness` (commit)

**Purpose:** Write `final_markdown` to `target_vault_path` in the baker-vault git tree, commit with Pipeline identity, push to `main`.

**Mechanism (D5):** Serial via `flock` mutex — one pipeline tick holds the lock, writes, commits, pushes, releases. Prevents concurrent push conflicts with Gold-promote worker.

**Commit identity:** `Baker Pipeline <pipeline@brisengroup.com>` (not Director). Gold-promote later flips `author: director` frontmatter + re-commits with Director identity.

**Output:** `signal_queue.status = 'completed'`; `signal_queue.committed_at` timestamp; `signal_queue.commit_sha`.

**Failure modes:**
- Push conflict (someone else committed since we pulled) → rebase + retry, then fail
- Permission denied (baker-vault creds expired) → alert, pause pipeline

---

## 3. Schema touches (new columns + tables needed beyond KBL-A)

### 3.1 Extend `signal_queue` (KBL-A already added `primary_matter`, `related_matters`, `triage_confidence`, `started_at`)

Adding per-step output columns for checkpoint/resume semantics — if pipeline crashes at Step 5, we don't redo Steps 1-4 on recovery.

```sql
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS vedana TEXT;
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS triage_score NUMERIC(5,2);
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS resolved_thread_paths JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS extracted_entities JSONB;
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS step_5_decision TEXT;
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS opus_draft_markdown TEXT;
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS final_markdown TEXT;
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS target_vault_path TEXT;
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS committed_at TIMESTAMPTZ;
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS commit_sha TEXT;
```

Total: 10 new columns on `signal_queue`.

### 3.2 Expand `signal_queue.status` CHECK constraint

KBL-A brief §1612 defined the first-tier statuses. KBL-B adds per-step states for observability + resumability.

**New statuses:**

```
'awaiting_triage', 'triaging', 'triage_failed', 'triage_invalid',
'awaiting_resolve', 'resolving', 'resolve_failed',
'awaiting_extract', 'extracting', 'extract_failed',
'awaiting_classify', 'classifying', 'classify_failed',
'awaiting_opus', 'opus_running', 'opus_failed', 'paused_cost_cap',
'awaiting_sonnet', 'sonnet_running', 'sonnet_failed',
'awaiting_commit', 'committing', 'commit_failed',
'completed', 'dropped_layer0', 'routed_inbox'
```

That's 24 statuses — nontrivial. **Open design question for §5:** do we collapse this into two columns — `stage` (`layer0|triage|resolve|...|commit`) + `state` (`awaiting|running|failed|done`) — to reduce the CHECK-constraint sprawl? Preference: yes, do the collapse. 9 × 4 = 36 Cartesian but CHECK is simpler.

### 3.3 Optional new table — `kbl_pipeline_run` (observability)

Each time the pipeline tick fires, record: `run_id, started_at, ended_at, signals_claimed, signals_completed, signals_failed, circuit_breaker_tripped BOOL`. Feeds KBL-C dashboard later.

Estimate: ~8 rows/hour at 2-min cron. Cheap.

### 3.4 Indexes

- `CREATE INDEX idx_signal_queue_stage ON signal_queue (stage)` (assuming collapse)
- `CREATE INDEX idx_signal_queue_committed_at ON signal_queue (committed_at DESC)` — dashboard query
- `CREATE INDEX idx_signal_queue_resolved_thread_paths_gin ON signal_queue USING gin (resolved_thread_paths)` — for "what other signals resolved to this thread" queries

### 3.5 No new FKs

All per-step data lives on `signal_queue`. Existing FKs from `kbl_cost_ledger.signal_id` and `kbl_log.signal_id` into `signal_queue.id` cover observability.

---

## 4-N. Pending (will land after B2/B3 reports)

Section outline, drafted but empty:

- **§4 Per-step I/O contracts** — precise JSON schemas, field types, null-handling rules per step
- **§5 Status-column collapse design** — if §3.2 ratified, explicit stage+state table
- **§6 Prompt templates** — triage, extract, classify, opus_step5, sonnet_step6 (5 prompts)
- **§7 Error matrix** — per-step × per-failure-mode × recovery-action grid
- **§8 Model config + retry ladder wiring** — temps, token budgets, R3 retry sequence concrete
- **§9 Cost-control integration** — pre-call estimate, circuit breaker trip conditions, daily cap behavior
- **§10 Testing plan** — unit (per step), integration (end-to-end 10-signal fixture), shadow-mode run
- **§11 Observability** — what kbl_log rows to emit per step, what metrics to emit
- **§12 Rollout sequence** — shadow mode → flag flip → Phase 1 Hagenauer-only burn-in
- **§13 Acceptance criteria** — numerical thresholds for declaring KBL-B done

---

## Asks of Director (amended post-B2 review, 2026-04-18)

B2 voted on the original 4 asks: **Ask 1 YES, Ask 2 REDIRECT (blockers now applied above), Ask 3 YES with migration spec, Ask 4 INCLUDE**. AI Head applied B2's 2 blockers + S2 + N1 inline above per Director's fast-path directive. Remaining calls:

1. **Ratify §1.2 scope (KBL-C out)** — AI Head + B2 both YES. One-word confirm to lock.
2. **Ratify §2 flow as amended** — Step 2 source-specific, Step 4 deterministic policy, Step 5 cost-cap/circuit-breaker split. 8-step taxonomy preserved. One-word confirm to lock.
3. **Ratify §3.2 status collapse (principle) + AI Head picks migration approach** — B2 + AI Head agree on two-track (keep legacy `status` for existing rows; add `stage`+`state` for KBL-B pipeline writes; deprecate `status` after Phase 2 burn-in). AI Head writes the migration SQL in §5.
4. **Ratify §3.3 `kbl_pipeline_run` table — include in KBL-B** — AI Head + B2 both YES. One-word confirm.

These four calls unblock ~1500 more lines of brief (§4-13 in full, including per-step I/O contracts, prompts, error matrix, test plan, rollout).

---

*Prepared 2026-04-17 by AI Head as skeleton. Amended 2026-04-18 with B2 blockers applied inline. Awaits Director ratification before per-step detail.*
