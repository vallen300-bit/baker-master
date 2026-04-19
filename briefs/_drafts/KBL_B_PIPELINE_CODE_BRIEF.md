# KBL-B Pipeline — Code Brief (SKELETON / DRAFT)

**Status:** §1-5 **RATIFIED**. §6-13 authoring in progress. REDIRECT fold complete across §1.3, §1.4, §2, §3.2, §4.7, §5.2, §5.5, §6, §8.
**Author:** AI Head
**Date:** 2026-04-17 (original), 2026-04-18 (REDIRECT fold + amendments)
**Purpose of skeleton:** surface architecture decisions early so Director can redirect scope before per-step detail is written.

**Amendments 2026-04-18:**

- §2 Step 2 — resolver is now **source-specific** (email/WA use metadata, transcripts/Scan use embeddings). Removes unnecessary Voyage dependency on email/WA hot path.
- §2 Step 4 — **no LLM call**. Deterministic policy step derived from Step 1+2 outputs. Step name preserved for `kbl_cost_ledger.step` enum parity; prompt/retry/cost-row collapse to no-op.
- §2 Step 5 — **cost-cap and circuit-breaker separated**. Per-signal cost-cap defer (`paused_cost_cap`) is distinct from global circuit breaker (KBL-A §1062).
- §2 Step 4 — Layer 2 enforcement location reconciled: canonical location = inside `_decide_step5_path()` at the Step 4→5 boundary (§1.2's "1-line env check at Step 5 entry" is the implementation shorthand).
- **§2 Step 6 REDIRECT (per B2 scope-challenge verdict, Director pre-ratified)** — `sonnet_step6` is now `finalize`, deterministic Python, no LLM call. Four jobs: metadata augmentation (code), cross-link stubs (code, decision lives at Step 1), Pydantic frontmatter validation (code; failure → Opus R3 retry, not Sonnet repair), prose polish (DELETED; re-introduce only if Phase-1 burn-in shows >5% "needs editing"). Blast radius: §1.3, §1.4, §2, §3.2, §4.7, §5.2, §5.5, §6, §8 all updated. `sonnet_step6` enum value in `kbl_cost_ledger.step` preserved but unused (preserves option to re-introduce without schema migration).
- CHANDA fold: §1.3 taxonomy refined (Steps 1/3/5 are LLM; Steps 0/2/4/6/7 are deterministic).

**Deferred to §5+ AI Head judgment** (fast-path per Director 2026-04-18):
- ~~S1 Step 6 Sonnet opt-in flag~~ — superseded by REDIRECT (no Sonnet call; `sonnet_step6` enum preserved for future re-introduction per B2's option-preservation note)
- S3 status-collapse migration spec (two-track applied in §5)
- S4 TOAST hygiene on `opus_draft_markdown` / `final_markdown` post-commit — applied in §4.9

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
layer0 → triage → resolve → extract → classify → opus_step5 → finalize → claude_harness (commit)
```

**Step 6 REDIRECTED (2026-04-18 per B2 scope-challenge verdict):** `sonnet_step6` is now `finalize` — a deterministic post-Opus finalization step with no LLM call. Taxonomy: Steps 1/3/5 are LLM (Gemma/Gemma/Opus); Steps 0/2/4/6/7 are deterministic Python. The pipeline is 8 steps but 3 of them touch an LLM, not 5.

Plus `ayoniso` (alerts) runs async off Step 6 — **that's KBL-C**, not KBL-B.

### 1.4 Ratified decisions KBL-B inherits (don't re-open)

- **D1:** Model for Step 1 (Triage) — Gemma 4 8B or Qwen 2.5 14B cold-swap (retry pending)
- **D2:** Gold promotion via `gold_promote_queue` PG table + Mac Mini cron drain
- **D3:** 3-layer matter scoping — Layer 0 per-source filter + Layer 1 classifier + Layer 2 ALLOWED_MATTERS gate at Step 5
- **D5:** Serial `claude -p` harness via flock mutex
- **D14:** Cost tracking via `kbl_cost_ledger` + daily cap `KBL_COST_DAILY_CAP_USD=15` + circuit breaker
- **D15:** Logging — local rotating + PG WARN+ + alert dedupe + heartbeat
- **R3:** Retry ladder for Opus Step 5 (Anthropic 529/overloaded: temp=0 first retry, pared prompt on second). Now also carries the frontmatter-validation-failure case (post-REDIRECT Step 6 raises `FinalizationError` on malformed frontmatter → triggers Opus R3 retry on Step 5, not a Sonnet repair pass).
- **Cost ledger enum:** `layer0 | triage | resolve | extract | classify | opus_step5 | sonnet_step6 | claude_harness | ayoniso` — `sonnet_step6` enum value preserved but unused post-REDIRECT (B2's note: preserves option to re-introduce without schema migration if Phase-1 burn-in reveals Opus drafts need polish).
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

### Step 6 — `finalize` (deterministic finalization — NO LLM CALL)

**REDIRECTED 2026-04-18 (per B2 scope-challenge verdict, Director pre-ratified):** Step 6 was originally specified as a Sonnet 4.6 polish pass but analysis showed three of its four jobs (metadata augmentation, cross-link writing, frontmatter schema validation) are pure-deterministic code, and the fourth (prose polish) lacks evidence that Opus 4.7 drafts need it. Collapsing to deterministic code removes one Anthropic dependency surface, saves ~5-10¢/signal on `full_synthesis` signals, and drops Phase 1 ship date.

**Purpose:** Take Opus's draft and produce the vault-canonical form — split frontmatter from body, augment with deterministic metadata, validate via Pydantic, compute target vault path, emit cross-link stubs.

**Model:** none. Pure Python.

**Cost:** 0 tokens, 0 USD. `kbl_cost_ledger` emits no row for this step.

**Mechanism:**

```python
def step6_finalize(signal: SignalRow) -> tuple[str, str]:
    """Returns (final_markdown, target_vault_path). Raises FinalizationError on schema failure."""
    frontmatter_dict, body = _split_opus_draft(signal.opus_draft_markdown)
    frontmatter_dict.update({
        "signal_id": signal.id,
        "source": signal.source,
        "primary_matter": signal.primary_matter,
        "related_matters": signal.related_matters,
        "vedana": signal.vedana,
        "triage_score": int(signal.triage_score),
        "triage_confidence": float(signal.triage_confidence),
        "created_at": signal.created_at.isoformat(),
        "source_id": _extract_source_id(signal),
        "author": "pipeline",
    })
    validated = WikiFrontmatter.model_validate(frontmatter_dict)  # raises ValidationError on malformed
    target_path = _compute_target_vault_path(signal)  # wiki/<matter>/YYYYMMDD_<slug>.md
    final_markdown = _render(validated, body)
    _write_cross_link_stubs(signal.related_matters, target_path)  # idempotent per related_matters entry
    return final_markdown, target_path
```

**Four jobs — where they actually live:**

| Job | Handler | Note |
|---|---|---|
| Metadata (source_id, timestamps, author='pipeline') | deterministic Python | no LLM judgment available |
| `related_matters[]` cross-links | deterministic writer to `wiki/<matter>/_links.md` | **cross-link decision** lives at Step 1; Step 6 just writes stubs |
| Frontmatter schema validation | Pydantic `WikiFrontmatter.model_validate()` | on failure → raise `FinalizationError` → upstream triggers Opus R3 retry on Step 5 |
| Prose polish on Opus body | **DELETED** | no evidence Opus 4.7 drafts need polish; re-introduce only if Phase 1 burn-in shows >5% of wiki entries marked "needs editing" |

**Output:** `signal_queue.final_markdown TEXT` + `signal_queue.target_vault_path TEXT` (e.g., `wiki/hagenauer-rg7/2026-04-17_ofenheimer-demand-letter.md`). Also appends cross-link stubs to `wiki/<matter>/_links.md` for each entry in `related_matters`, idempotent (dedupe by source signal_id within the file).

**Failure modes:**
- **Malformed frontmatter from Opus** → `FinalizationError`; Step 5 state flips back to `opus_failed`, Opus R3 retry ladder fires (not Sonnet repair). If still malformed after 3 Opus retries → `finalize_failed`, route to inbox.
- **Cross-link write fails (IO/permission)** → `finalize_failed`, log + alert. No retry — baker-vault write problem needs operator attention.

**Latency:** ~50-200ms (fastest step in the pipeline by 2 orders of magnitude vs Step 5 Opus call).

**Cross-link semantic ownership:** the *decision* "should this signal cross-link to Hagenauer?" is made in Step 1 (Gemma triage, `related_matters[]` output). Step 6 is a templated writer, not a re-evaluator. This is why post-REDIRECT Step 1 prompt carries explicit cross-matter elevation responsibility (see `KBL_B_STEP1_TRIAGE_PROMPT.md` §1.2 post-REDIRECT amend at commit `d7db987`).

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
'awaiting_finalize', 'finalize_running', 'finalize_failed',
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

## 4. Per-step I/O contracts

Each step reads named columns from `signal_queue`, writes named columns, emits 0-1 `kbl_cost_ledger` rows, emits 0-N `kbl_log` rows. Contracts here are the interface; §6 covers prompts, §7 covers error semantics.

Naming convention: inputs are columns already populated by prior steps; outputs are columns this step writes. Unless noted, all writes happen in a single transaction with `stage`+`state` advance (§5).

### 4.0 Data-shape note (applies to §4.1-4.8)

Per `memory/store_back.py:6326-6363`, source-specific fields live in `signal_queue.payload JSONB`, NOT as direct columns. Throughout §4, references like "`subject`" or "`chat_id`" mean **`payload->>'subject'`**, **`payload->>'chat_id'`** etc. (email headers: `payload->>'email_message_id'`, `payload->>'in_reply_to'`, `payload->'references'`; WhatsApp: `payload->>'chat_id'`, `payload->>'sent_at'`, `payload->>'sender_phone'`; meeting: `payload->>'title'`). Direct columns on `signal_queue` remain: `id`, `source`, `raw_content`, `primary_matter`, `related_matters`, `triage_confidence`, `triage_score`, `vedana`, `started_at`, plus the new KBL-B columns (§3.1) and the `stage`+`state` columns (§5.2).

**Corrected per B2 blocker B3** — prior contracts listed these as direct columns, which would silently read NULL. §6 prompt builders must use JSONB accessors.

### 4.1 Step 0 — `layer0`

**Reads:** `source`, `raw_content`, `payload->>'sender'`, `payload->>'recipients'`, `payload->>'chat_id'`, `payload->>'subject'` (source-dependent).
**Writes:** `stage='layer0'`, `state='done'` + route-forward, OR `state='dropped_layer0'` terminal.
**Ledger:** none (deterministic, zero cost).
**Log:** on drop only — `component='layer0'`, `level='INFO'`, `message=<rule name that fired>`.
**Invariant:** a signal never re-enters Step 0 after exiting.

### 4.2 Step 1 — `triage`

**Reads:** `raw_content`, `source`, `payload->>'subject'` (hint for email).
**Writes:** `primary_matter TEXT` (nullable), `related_matters JSONB` (default `[]`), `vedana TEXT` ∈ `{opportunity, threat, routine}`, `triage_confidence NUMERIC(3,2)`, `triage_score NUMERIC(5,2)`.
**Ledger:** one row, `step='triage'`, `model=ollama_gemma4` (or qwen on fallback), `input_tokens`, `output_tokens`, `cost_usd=0` (local), `latency_ms`.
**Log:** on retry / normalize-miss / fallback-activation only.
**Invariant:** post-write, `vedana IS NOT NULL` AND `triage_score IS NOT NULL`. `primary_matter` may be NULL (valid signal of "no matter applies"), in which case `related_matters = '[]'::jsonb`.
**Routing:** `triage_score < KBL_PIPELINE_TRIAGE_THRESHOLD` (default 40) → `state='routed_inbox'` terminal, `target_vault_path='wiki/_inbox/<yyyymmdd>_<signal_id_short>.md'`.

### 4.3 Step 2 — `resolve`

**Reads:** `source`, `primary_matter`, plus source-dependent metadata (all via `payload JSONB`):
- email: `payload->>'email_message_id'`, `payload->>'in_reply_to'`, `payload->'references'`, `payload->>'sender'`, `payload->'recipients'`, `payload->>'subject'`
- whatsapp: `payload->>'chat_id'`, `payload->>'sent_at'`, `payload->>'sender_phone'`
- meeting: `raw_content`, `payload->>'title'`
- scan: `raw_content`, `payload->>'director_context_hint'`

**Writes:** `resolved_thread_paths JSONB` = list of vault-relative paths (e.g., `["wiki/hagenauer-rg7/2026-04-03_ofenheimer-letter.md"]`). Empty array = new thread.
**Ledger:** email/WA = no row (metadata only, zero cost). Transcript/Scan = one row, `step='resolve'`, `model='voyage-3'`, `input_tokens` (approx from chars/4), `cost_usd ≈ 0.00005`.
**Log:** when embedding API is unavailable for transcript/scan → degraded mode (empty resolve, log `level='WARN'`, proceed as new thread).
**Invariant:** `resolved_thread_paths` is always an array (never NULL). Paths are vault-relative, always start with `wiki/`.

### 4.4 Step 3 — `extract`

**Reads:** `raw_content`, `source`, `primary_matter`, `resolved_thread_paths` (for context).
**Writes:** `extracted_entities JSONB` with schema:

```json
{
  "people":       [{"name": "...", "role": "...", "company": "..."}],
  "orgs":         [{"name": "...", "type": "law_firm|bank|..."}],
  "money":        [{"amount": 100000, "currency": "EUR", "context": "..."}],
  "dates":        [{"date": "2026-04-30", "event": "...", "iso8601": true}],
  "references":   [{"type": "contract|invoice|case", "id": "..."}],
  "action_items": [{"actor": "...", "action": "...", "deadline": "..."}]
}
```

All sub-keys are arrays (possibly empty). Unparseable fields → drop from output, not set to NULL/missing.

**Ledger:** one row, `step='extract'`, `model=ollama_gemma4`, tokens, `cost_usd=0`, `latency_ms`.
**Log:** on retry / malformed JSON only.
**Invariant:** `extracted_entities` is always a JSON object with all 6 keys present, values are arrays.

### 4.5 Step 4 — `classify` (deterministic policy)

**Reads:** `triage_score`, `primary_matter`, `related_matters`, `resolved_thread_paths`.
**Writes:** `step_5_decision TEXT` ∈ `{'full_synthesis', 'stub_only', 'cross_link_only', 'skip_inbox'}`.
**Ledger:** none (no model call).
**Log:** only on Layer 2 gate block → `level='INFO'`, `message='layer2_blocked: primary_matter=<X> not in allowed=[<Y>]'`.
**Decision table:**

| Condition (Python) | Decision |
|---|---|
| `primary_matter not in env.KBL_MATTER_SCOPE_ALLOWED` | `skip_inbox` |
| `triage_score < THRESHOLD + NOISE_BAND` (e.g., 40-45) | `stub_only` |
| `resolved_thread_paths == []` AND `related_matters == []` | `full_synthesis` (new arc, single matter) |
| `resolved_thread_paths == []` AND `related_matters != []` | `full_synthesis` + flag for cross-links in Step 6 |
| `resolved_thread_paths != []` | `full_synthesis` (continuation, Step 5 updates existing entry) |
| edge: `triage_score < THRESHOLD` | unreachable — Step 1 already routed this to inbox |

**Invariant:** `step_5_decision` set before Step 5 is claimable.

### 4.6 Step 5 — `opus_step5`

**Reads:** all prior-step outputs + `step_5_decision`. If `decision='skip_inbox'` or `'stub_only'`, Step 5 does NOT call Opus — writes a stub `opus_draft_markdown` deterministically and advances. Opus call only on `full_synthesis`.
**Writes:** `opus_draft_markdown TEXT`.
**Ledger:** one row on Opus call. `step='opus_step5'`, `model='claude-opus-4-7'`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `cost_usd` (from Anthropic response billing), `latency_ms`.
**Log:** on retry / cost-cap defer / circuit breaker trip.
**Invariant:** exactly one of `opus_draft_markdown IS NOT NULL` OR `state='paused_cost_cap'` OR `state='failed'`.
**Cost gate:** see §9.

### 4.7 Step 6 — `finalize` (deterministic, post-REDIRECT 2026-04-18)

**Reads:** `opus_draft_markdown`, `primary_matter`, `related_matters`, `vedana`, `triage_score`, `triage_confidence`, `created_at`, `source`, `payload` (for source-specific IDs), `step_5_decision`.
**Writes:** `final_markdown TEXT`, `target_vault_path TEXT`.
**Side-effects:** appends cross-link stub to `wiki/<m>/_links.md` for each `m in related_matters`, idempotent by source signal_id within the file.
**Ledger:** no row (no model call).
**Log:** on Pydantic validation failure (`level='WARN'`, `component='finalize'`, `message=<failed field + reason>`). On cross-link write failure (`level='ERROR'`, `component='finalize'`, `message='cross-link write failed: <path>'`).
**Invariant:** `final_markdown` is YAML-frontmatter + Markdown body, Pydantic-validated. `target_vault_path` starts with `wiki/` and ends `.md`. `author: pipeline` always (Silver → Director-promoted Gold per Inv 8).
**Failure path:** `FinalizationError` raised → signal flips to `opus_failed`, Opus R3 retry fires (§8). After 3 failed Opus retries → `finalize_failed`, route to inbox.

### 4.8 Step 7 — `claude_harness` (commit)

**Reads:** `final_markdown`, `target_vault_path`, `related_matters` (for cross-link commit message).
**Writes:** `state='done'`, `committed_at TIMESTAMPTZ`, `commit_sha TEXT`.
**Side-effect:** writes file to baker-vault local clone at `target_vault_path`, `git commit` with identity `Baker Pipeline <pipeline@brisengroup.com>`, `git push origin main` under `flock` mutex (D5).
**Ledger:** none (no model call; `claude -p` harness if needed for commit message synthesis charges to `step='claude_harness'` — one row with tokens/cost — else no row).
**Log:** on rebase retry / push conflict.
**Invariant:** `committed_at` + `commit_sha` both set OR both NULL. Never half-committed.

### 4.9 Post-commit TOAST cleanup (S4 from B2 review)

After Step 7 sets `state='done'`, a follow-up write within the same transaction nulls `opus_draft_markdown` and `final_markdown`:

```sql
UPDATE signal_queue
SET opus_draft_markdown = NULL,
    final_markdown = NULL
WHERE id = <signal_id> AND state = 'done';
```

Canonical content lives in the vault at `target_vault_path` from this point. PG intermediate copies are debug-only; dropping them frees TOAST storage immediately.

---

## 5. Status-column collapse — two-track migration

### 5.1 Design (ratified §3.2 principle + AI Head picks two-track per B2 S3)

**Keep legacy `status` column unchanged.** KBL-A's existing 8-value CHECK stays in place. All existing pre-KBL-B rows continue using `status` with current semantics.

**Add `stage` + `state` columns** for KBL-B pipeline rows. New KBL-B writes populate both; `status` gets a compatibility mirror (see §5.3).

**Deprecate after Phase 2 burn-in:** once Phase 2 is stable, drop `status` and its CHECK constraint in a cleanup migration. Target: ≥3 months post-Phase 1 go-live.

### 5.2 Schema — `stage` + `state` columns

```sql
-- Stage: which pipeline step the signal is currently at or most-recently completed
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS stage TEXT;
ALTER TABLE signal_queue ADD CONSTRAINT chk_signal_queue_stage
  CHECK (stage IS NULL OR stage IN (
    'layer0', 'triage', 'resolve', 'extract', 'classify',
    'opus_step5', 'finalize', 'claude_harness'
  ));

-- State: within a stage, what's happening
ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS state TEXT;
ALTER TABLE signal_queue ADD CONSTRAINT chk_signal_queue_state
  CHECK (state IS NULL OR state IN (
    'awaiting',            -- queued, not yet claimed
    'running',             -- worker is actively processing
    'done',                -- stage completed, either terminal or ready for next stage
    'failed',              -- stage failed, terminal unless retried manually
    'dropped_layer0',      -- terminal — dropped by deterministic Layer 0 rule
    'routed_inbox',        -- terminal — routed to wiki/_inbox/ (low triage, layer2 block, unparseable)
    'paused_cost_cap',     -- paused — per-signal daily cost cap exceeded, re-queues next UTC day
    'paused_circuit_brkr'  -- paused — global circuit breaker open, re-entered on recovery
  ));

-- Compound index for worker claim query
CREATE INDEX IF NOT EXISTS idx_signal_queue_stage_state
  ON signal_queue (stage, state)
  WHERE state IN ('awaiting', 'paused_cost_cap', 'paused_circuit_brkr');
```

### 5.3 Compatibility mirror

KBL-B writes both `status` (legacy) and `stage`+`state` (new) on every transition for the compatibility window. Mirror table:

KBL-A `signal_queue.status` CHECK allows: `pending, processing, done, failed, classified-deferred, cost-deferred, failed-reviewed, dropped` (per KBL-A §290-292). The mirror MUST stay within that set.

| KBL-B (stage, state) | Mirror `status` value | Notes |
|---|---|---|
| any stage, `awaiting` | `pending` | claimable |
| any stage, `running` | `processing` | in-flight |
| `claude_harness`, `done` | `done` | terminal success |
| any stage, `failed` | `failed` | terminal failure |
| any stage, `dropped_layer0` | `dropped` | already in CHECK set |
| any stage, `routed_inbox` | `classified-deferred` | maps to existing "classifier routed it aside" value |
| any stage, `paused_cost_cap` | `cost-deferred` | existing value, semantic match |
| any stage, `paused_circuit_brkr` | `processing` | circuit-pause is transient, not deferral — stays claimable-looking to legacy code |

Corrected (B2 blocker B2): the prior draft used `inbox` and `deferred` strings not in the CHECK set — every mirrored UPDATE for ~30%+ of signals would have failed. Remap to existing CHECK values above. No migration / no CHECK expansion needed.

Existing queries like `WHERE status='pending'` continue to find claimable rows, including new KBL-B ones. Any KBL-A code that filters by `status` keeps working.

### 5.4 Worker claim query

New KBL-B worker claims by `(stage, state)`, not `status`:

```sql
WITH next AS (
  SELECT id FROM signal_queue
  WHERE stage = $1           -- e.g., 'triage'
    AND state = 'awaiting'
  ORDER BY started_at NULLS FIRST, id
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
UPDATE signal_queue
SET state = 'running', started_at = NOW()
FROM next WHERE signal_queue.id = next.id
RETURNING signal_queue.*;
```

Each stage has its own worker-loop invocation. Serial per stage per tick (D5 flock).

### 5.5 `next_stage` derivation

Rather than a `next_stage TEXT` column (which denormalizes and can drift), compute next stage in Python via a pure function:

```python
NEXT_STAGE = {
    'layer0': 'triage',
    'triage': 'resolve',
    'resolve': 'extract',
    'extract': 'classify',
    'classify': 'opus_step5',
    'opus_step5': 'finalize',
    'finalize': 'claude_harness',
    'claude_harness': None,  # terminal
}

TERMINAL_STATES = {'dropped_layer0', 'routed_inbox', 'failed'}

def advance_stage(current: str, state: str) -> tuple[str | None, str]:
    """Return (next_stage, next_state) given current stage and state after completion.

    A signal can terminate at any stage (layer0 drop, triage routes to inbox, opus fails, etc.),
    not only at claude_harness. Terminal states stick to their current stage.
    """
    # Terminal at any stage — signal ends here
    if state in TERMINAL_STATES:
        return (None, state)
    # Final-stage completion terminates
    if current == 'claude_harness' and state == 'done':
        return (None, state)
    # Paused states hold at current stage, re-entered by same worker
    if state in ('paused_cost_cap', 'paused_circuit_brkr'):
        return (current, state)
    # Normal stage advance
    if state == 'done':
        return (NEXT_STAGE[current], 'awaiting')
    raise ValueError(f"unexpected (stage={current}, state={state})")
```

### 5.6 Migration — no backfill

KBL-A's existing rows do NOT get `stage` or `state` populated. They stay NULL forever and are handled via the `status` column as before. Only rows inserted post-KBL-B deploy receive the new columns.

No backfill SQL, no downtime window, no double-ingestion risk. Two-track from day one.

### 5.7 Deprecation (Phase 2 close-out item)

Target date: ≥3 months post Phase 1 go-live. At deprecation:

1. Verify no KBL-A code path still reads `status` column
2. Drop `status` column + CHECK
3. Drop compatibility-mirror writes in KBL-B code
4. Flagged in decisions doc for close-out

---

## 6. Prompt templates

Post-REDIRECT, the pipeline has **3 LLM prompts** (not 4). No prompt for Step 4 (deterministic policy) or Step 6 (deterministic finalization).

- **§6.1 Step 1 — `triage`** — Gemma 4 8B. Draft + reviews folded. Canonical source: `briefs/_drafts/KBL_B_STEP1_TRIAGE_PROMPT.md` (B3-authored, three review cycles through B2). Template text extracted to `kbl/prompts/step1_triage.txt` (PR #8).
- **§6.2 Step 3 — `extract`** — Gemma 4 8B. Canonical source: `briefs/_drafts/KBL_B_STEP3_EXTRACT_PROMPT.md` (B3-authored, B2-reviewed READY).
- **§6.3 Step 5 — `opus_step5`** — Claude Opus 4.7 (1M). Canonical source: `briefs/_drafts/KBL_B_STEP5_OPUS_PROMPT.md` (B3-authored, B2-reviewed REDIRECT → S1 applied at `02e5063` → pending B2 APPROVE delta). IS Leg 1 — reads `gold_context_by_matter` on every full_synthesis call; zero-Gold = valid first entry per Inv 1.
- **§6.4 No prompt for Step 6** — deterministic `step6_finalize()` per §4.7 REDIRECT. If Phase-1 burn-in surfaces >5% "needs editing" on Director review, re-introduce a Sonnet polish prompt here (the `sonnet_step6` cost-ledger enum is preserved for that option; B2's note).

## 7. Error matrix

Every failure maps to exactly one recovery action. Ambiguity = design bug.

| Step | Failure | Detection | Log | Recovery | Terminal |
|---|---|---|---|---|---|
| Layer 0 | YAML malformed | `Layer0RulesError` at load | ERROR | halt tick, alert operator | N |
| Layer 0 | hash-store DB unreachable | PG raise | ERROR | fail-CLOSED (drop to review queue) | per-signal |
| Triage | Ollama unreachable | HTTP timeout | ERROR | Qwen availability-fallback; both down → `paused_circuit_brkr` | N |
| Triage | Gemma JSON unparseable | `TriageParseError` | WARN | R3 retry (pared prompt); 2 failures → inbox | Y after R3 |
| Triage | Slug not in registry | `normalize()` None | INFO | `primary_matter=null` → inbox | Y |
| Resolve (email/WA) | Metadata unparseable | `ResolverError` | WARN | empty `resolved_thread_paths` (new arc) | N |
| Resolve (transcript/scan) | Voyage unreachable | HTTP timeout | WARN | degraded: empty paths + mark for review; no circuit trip | N |
| Extract | Gemma JSON unparseable | `ExtractParseError` | WARN | R3 retry; 2 failures → empty entities + continue | N |
| Classify | Missing upstream field | Python raise | ERROR | halt tick (programming bug) | N |
| Opus Step 5 | Anthropic 529 / overloaded | HTTP 529 | WARN | R3 ladder: temp=0, pared prompt, fail; 3 consecutive across signals → circuit trip | Y after R3 |
| Opus Step 5 | Cost cap projected | pre-call estimate | INFO | `paused_cost_cap`, re-queue next UTC day | N |
| Opus Step 5 | Circuit breaker open | runtime state | INFO | signal returns to claimable pool; tick exits | N |
| Opus Step 5 | Output malformed | split fails in Step 6 | WARN | flip to `opus_failed`, R3 retry (not Sonnet — REDIRECT) | Y after R3 |
| Finalize (Step 6) | Pydantic validation | `FinalizationError` | WARN | flip Step 5 → `opus_failed`, Opus R3; 3 failures → `finalize_failed` → inbox | Y after R3 |
| Finalize (Step 6) | Cross-link write IO | OSError | ERROR | `finalize_failed` + alert (vault permission issue) | Y |
| Commit (Step 7) | git push conflict | non-zero exit | WARN | rebase + retry once; second → fail | Y after 1 |
| Commit (Step 7) | Permission denied | non-zero exit | ERROR | halt tick, credentials expired | N |
| Commit (Step 7) | flock timeout | lock not acquired | WARN | re-queue signal; next tick retries | N |

Every per-signal-terminal (Y) failure routes the signal to `wiki/_inbox/` with a stub explaining why. Director sees via Ayoniso (KBL-C) or inbox review.

## 8. Model config + retry ladder

- **Ollama HTTP settings** — Mac Mini local. `POST /api/generate` with `model=gemma2:8b`, `format=json`, `options={"seed": 42, "temperature": 0}`. Timeout 30s. Used by Step 1 + Step 3.
- **Anthropic Opus** — `claude-opus-4-7` (1M context). Prompt-caching on system prompt + stable context. Used by Step 5 only.
- ~~Anthropic Sonnet~~ — **NOT USED** post-REDIRECT. `claude-sonnet-4-6` is not called by any KBL-B pipeline step. If reintroduced (per B2 option-preservation), config goes here.
- **R3 retry ladder** (applies to Opus Step 5):
  1. First try: normal temp (default), full context
  2. On 529 / overloaded / RateLimitError → retry with `temperature=0`
  3. On second failure → retry with pared prompt (drop `gold_context_by_matter` to top-1 Gold entry only)
  4. Third failure → signal flips to `opus_failed`, routes to inbox
- **R3 also carries frontmatter-validation-failure (post-REDIRECT):** Step 6 `FinalizationError` triggers Opus R3 retry on Step 5, not a Sonnet repair pass. After 3 Opus retries → `finalize_failed`, route to inbox.
- **Retry counters** contribute to Anthropic-side circuit-breaker-consecutive-failure count (D14).

## 9. Cost-control integration

### 9.1 Ledger write rules (post-REDIRECT)

| Step | Model | Rows per signal | Cost |
|---|---|---|---|
| triage | gemma2:8b local | 1 | $0 (tokens logged for instrumentation) |
| resolve | Voyage (transcripts/scan only) | 0-1 | ~$0.00005 when fires |
| extract | gemma2:8b | 1 | $0 |
| opus_step5 | claude-opus-4-7 | 1 on `full_synthesis`, 0 on stub/skip | variable, billed from Anthropic response |
| claude_harness | `claude -p` (optional commit-message synthesis) | 0-1 | ~$0.001 when fires |

Steps 0/2-metadata/4/6 write **zero** ledger rows. The `sonnet_step6` enum value stays in the CHECK constraint — unused post-REDIRECT, preserves re-introduction option without migration.

### 9.2 Daily cap enforcement (per-signal)

Step 5 entry checks projected-total against `KBL_COST_DAILY_CAP_USD=15`. On exceed: `state='paused_cost_cap'`, re-entered next UTC day by the pipeline tick.

```python
def _can_fire_step5(conn, signal) -> bool:
    today = datetime.now(UTC).date()
    today_total = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM kbl_cost_ledger WHERE created_at >= %s", (today,)
    ).scalar()
    projected = today_total + _estimate_step5_cost(signal)
    return projected <= Decimal(os.environ.get('KBL_COST_DAILY_CAP_USD', '15.00'))
```

### 9.3 Global circuit breaker (KBL-A §1062)

Separate from per-signal cost cap. Trips on 3+ consecutive Anthropic-side first-attempt failures across signals (in-signal R3 retries do NOT count). Recovery: probe every 60s; success → reset + flip `anthropic_circuit_open='false'`.

### 9.4 Scheduler wiring env vars (PR #18 — KBL_PIPELINE_SCHEDULER_WIRING)

Render runs `kbl.pipeline_tick.main` via APScheduler (registered in `triggers/embedded_scheduler.py`). Two knobs control when the job fires and whether `main()` does any work.

| Env | Default | Purpose |
|---|---|---|
| `KBL_FLAGS_PIPELINE_ENABLED` | `"false"` | Opt-in gate. `main()` returns 0 immediately unless this equals `"true"` (case-insensitive). Any typo keeps the pipeline disabled. Flip on Render to enter shadow mode. |
| `KBL_PIPELINE_TICK_INTERVAL_SECONDS` | `120` | APScheduler `IntervalTrigger` seconds. `max_instances=1` + `coalesce=True` guarantee no overlap at any interval. Values below 30 s are clamped to 30 s at registration time (log WARN). Malformed value falls back to the 120 s default. |

Mac Mini does NOT read these envs — its `poller.py` imports `kbl.steps.step7_commit.commit` directly and only processes `awaiting_commit` rows. Step 7 / Mac Mini is unaffected by the Render flag.

## 10. Testing plan

- **Per-step unit tests** — tests land alongside impl (see PR #7 LAYER0-IMPL, PR #8 STEP1-TRIAGE-IMPL, PR #9 LOOP-GOLD-READER-1).
- **End-to-end fixture** — 10 labeled signals + 4 synthetic (fixtures #1-14) per `briefs/_drafts/KBL_B_TEST_FIXTURES.md`. Post-REDIRECT: fixture rows show `step_6_runs: yes, no_llm: true` (not `step_6_sonnet_fires: no`).
- **Loop-compliance hard assertions** — each fixture asserts `hot_md_loaded`, `feedback_ledger_queried`, `gold_context_by_matter_loaded` (Inv 1). Fixtures #11-#14 exercise elevation / ledger correction / zero-Gold / cross-matter elevation behaviors.
- **Shadow-mode run semantics** — §12 covers. Pipeline runs with `pipeline_enabled=true` but vault writes go to `wiki/_shadow/` subtree; Director reviews before production flag flip.

## 11. Observability

### 11.1 `kbl_log` row spec

Every Python step writes `kbl_log` rows on WARN + ERROR. Schema (KBL-A): `(id, created_at, level, component, message, signal_id, payload JSONB)`. Per-step `component` strings: `layer0`, `triage`, `resolve`, `extract`, `classify`, `opus_step5`, `finalize`, `claude_harness`. Dashboard rollups group by `component`.

### 11.2 `kbl_pipeline_run` rollup

Per-tick row (KBL-A §3.3):

```sql
kbl_pipeline_run (run_id, started_at, ended_at, signals_claimed, signals_completed,
                  signals_failed, circuit_breaker_tripped BOOL)
```

### 11.3 Dashboard-ready metrics (KBL-C consumes)

Per-step latency p50/p95/p99 and error rate. **`finalize_latency_ms`** is a new post-REDIRECT metric — expected p95 ≤ 200ms; alert if p95 > 500ms (signals Pydantic thrashing or cross-link IO pathology). **No `sonnet_step6` metrics** (step doesn't fire an LLM). Cost metrics: daily Opus spend vs `KBL_COST_DAILY_CAP_USD`, cost-cap-deferred signal count, circuit-breaker trips per day.

## 12. Rollout sequence

1. **Schema migrations apply** — PR #5 (loop infra) + PR #8 (Step 1 signal_queue columns) already merged. Any residual §3 additions land in a cleanup migration.
2. **Loader + helper PRs land** — PR #4 (Layer 0 loader) ✓, PR #6 (loop helpers) ✓, PR #9 (Gold reader) ✓. PR #7 (Layer 0 evaluator) pending phone-fix delta re-verify.
3. **Step impls land in dependency order** — Step 0 ✓ (PR #7), Step 1 ✓ (PR #8), Step 2 → Step 3 → Step 4 → Step 5 → Step 6 (small, deterministic) → Step 7.
4. **Shadow mode burn-in** — `KBL_PIPELINE_WRITE_TARGET=shadow` env var; writes go to `wiki/_shadow/<matter>/` subtree. Director reviews N days before production flag flip.
5. **Flip to production** — `pipeline_enabled=true` + `KBL_PIPELINE_WRITE_TARGET=production`; Phase 1 scoping via `KBL_MATTER_SCOPE_ALLOWED=[hagenauer-rg7]`.
6. **Phase 1 monitor** — D1 gate holds (88% vedana / 76% matter); cost cap respected; circuit breaker trips <1/day across burn-in week.
7. **Phase 2 gate** — re-run D1 eval on live Phase 1 data; if accuracy holds at 88v/76m or better, expand `KBL_MATTER_SCOPE_ALLOWED`.

## 13. Acceptance criteria

Phase 1 go-live is declared achieved when ALL of:

- End-to-end fixture (14 signals per `KBL_B_TEST_FIXTURES.md`) passes pytest with hard-asserts on loop compliance (`hot_md_loaded`, `feedback_ledger_queried`, `gold_context_by_matter_loaded`)
- Shadow-mode N-day run produces zero Director-flagged "silent drop" or "silent contradiction" cases
- Opus Step 5 cost per `full_synthesis` signal, p95 ≤ $0.25
- `finalize_latency_ms` p95 ≤ 500ms
- Circuit breaker trips per day ≤ 1 across shadow-mode week
- Zero CHANDA Inv 1 / Inv 3 / Inv 10 violations in the shadow log (zero-Gold cases explicitly logged as Inv 1 compliance, not errors)
- Cost-cap defer + next-day re-entry tested at least once (synthetic pre-seed fixture #10)

Phase 2 gate (separate): re-run D1 eval on live Phase 1 data; if accuracy holds at 88v/76m or better, expand `KBL_MATTER_SCOPE_ALLOWED` beyond hagenauer-rg7.

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
