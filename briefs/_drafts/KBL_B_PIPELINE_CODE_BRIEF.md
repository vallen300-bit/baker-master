# KBL-B Pipeline — Code Brief (SKELETON / DRAFT)

**Status:** SKELETON — §1-3 only. §4-N await closure of D1 retry + SLUGS-1 merge.
**Author:** AI Head
**Date:** 2026-04-17
**Purpose of skeleton:** surface architecture decisions early so Director can redirect scope before per-step detail is written. Full per-step I/O contracts, prompts, error matrix, and test plan land after B2 + B3 reports close the loop.

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

**Mechanism (proposal — open for scrutiny):**
- Full-text similarity search over existing `wiki/<primary_matter>/*.md` using embeddings (Voyage AI voyage-3, already in Baker stack)
- Top-3 neighbors with similarity ≥ threshold → declare thread match, pass neighbor paths to Step 3
- No match → new thread, Step 3 starts from empty context

**Alternative considered:** pure lexical matching (title keywords + timestamps). Rejected: too brittle on transcripts.

**Output:** `signal_queue.resolved_thread_paths JSONB` (new column, see §3). `kbl_cost_ledger` row: step='resolve', cost_usd= (Voyage embedding cost, ~$0.00005/signal).

**Open question:** do we need a dedicated `kbl_threads` table, or is `wiki/<matter>/` tree + embeddings sufficient? **Preference:** no new table — keep the vault as source of truth.

### Step 3 — `extract` (structured entity extraction)

**Purpose:** Pull structured facts from raw content: named entities (people, companies, monetary figures), dates/deadlines, action items, reference numbers (contract IDs, invoice numbers, case numbers).

**Model:** Local LLM (same as triage — Gemma/Qwen). Separate prompt from triage to keep each step focused.

**Why not fold into Triage:** Step 1 must be *fast* (it's on the critical path for every signal, including ones that get dropped at Layer 2). Extraction is expensive JSON scaffolding. Splitting = 2x prompt cost on surviving signals but 0 cost on dropped ones.

**Output:** `signal_queue.extracted_entities JSONB` — structured payload. Schema: `{"people": [...], "orgs": [...], "money": [...], "dates": [...], "references": [...], "action_items": [...]}`.

**Failure modes:** same as Step 1.

### Step 4 — `classify` (routing + arc detection)

**Purpose:** Decide whether this signal warrants Step 5 (heavy Opus synthesis) or lighter handling. Detects:

- **Arc continuation:** existing thread update → Step 5 updates existing wiki entry
- **New arc:** new thread → Step 5 creates new wiki entry
- **Noise-that-survived:** signal passed triage but is still low-value → skip Step 5, write stub only
- **Multi-matter:** if `related_matters[]` non-empty and Step 5 should cross-link

**Layer 2 gate fires here:** if `primary_matter ∉ KBL_MATTER_SCOPE_ALLOWED` → route to inbox, skip Step 5. Phase 1 = `[hagenauer-rg7]` only.

**Model:** Local LLM again (reuses triage/extract context + output). Small decision prompt.

**Output:** `signal_queue.step_5_decision TEXT` ∈ `{'full_synthesis', 'stub_only', 'cross_link_only', 'skip_inbox'}`.

### Step 5 — `opus_step5` (the heavy one)

**Purpose:** Claude Opus reads the signal + thread context + extracted entities and synthesizes a wiki-entry draft in Markdown + frontmatter.

**Model:** `claude-opus-4-7` (1M context). Prompt includes:
- Signal raw content
- Top-3 neighbor wiki entries (from Step 2)
- Extracted entities (from Step 3)
- Any existing entry being updated (if arc continuation)

**Cost control:**
- Pre-call estimate via `kbl_cost_ledger.estimate_before_call(signal_id, step='opus_step5')` — if projected daily total exceeds `KBL_COST_DAILY_CAP_USD=15`, circuit breaker trips, signal re-queues for next day
- Prompt-caching on system prompt + stable context (slug list, vedana rules)
- Retry ladder on 529/overloaded: temp=0 retry, pared prompt retry, then fail

**Output:** `signal_queue.opus_draft_markdown TEXT` + `kbl_cost_ledger` row with actual tokens + cost.

**Failure modes:**
- Cost cap hit mid-day → circuit breaker → status `paused_cost_cap`, re-queue tomorrow
- Anthropic unavailable → R3 retry ladder, then `status=opus_failed`, route to inbox with log
- Output doesn't parse as valid frontmatter + body → 1 retry, then inbox

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

## Asks of Director (before §4+ is written)

1. **Ratify §1.2 (scope)** — KBL-C handlers + ayoniso alerts are OUT. Confirm or redirect.
2. **Ratify §2 flow** — 8 steps as described, no folding/splitting. Confirm or redirect.
3. **Decide on §3.2 status collapse** — `stage` + `state` split vs single 24-value CHECK. AI Head prefers collapse. One-line confirmation enough.
4. **Decide on §3.3 `kbl_pipeline_run` table** — include in KBL-B or defer to KBL-C dashboard ticket? AI Head prefers: include in KBL-B (data must land before dashboard can read it).

These four calls unblock ~1000 more lines of brief. Per-step prompt design (§6) also wants your read on how aggressive to be about prompt caching — but that's after D1 retry.

---

*Prepared 2026-04-17 by AI Head as skeleton. Not for dispatch to B1/B2. Awaits Director redirect before per-step detail.*
