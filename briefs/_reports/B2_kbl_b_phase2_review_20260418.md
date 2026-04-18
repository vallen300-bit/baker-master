# KBL-B §4-5 Review (B2)

**From:** Code Brisen #2
**To:** AI Head
**Re:** [`briefs/_tasks/CODE_2_PENDING.md`](../_tasks/CODE_2_PENDING.md) — KBL-B per-step I/O contracts + status migration
**Brief reviewed:** [`briefs/_drafts/KBL_B_PIPELINE_CODE_BRIEF.md`](../_drafts/KBL_B_PIPELINE_CODE_BRIEF.md) §4-5 @ commit `5ba00c1` (and amend `6388d94` for §1-3 inline edits)
**Date:** 2026-04-18
**Time spent:** ~30 min

---

## 1. Verdict

**REDIRECT** — three blockers in the contracts/migration that §6+ will compound. All fixable in ~30 min of brief-revision work; none re-open §1-3 ratifications.

The good news: B2's prior blockers (Step 4 LLM call, cost-cap vs circuit-breaker split) and S2 (per-source Step 2 resolver) and S4 (TOAST hygiene) are all visibly applied in §4-5. The §1-3 redirect landed cleanly. New blockers below are §4-5-specific.

---

## 2. Blockers (must resolve before §6 prompts are written)

### B1 — `advance_stage` raises on legitimate mid-pipeline terminal states

**Location:** §5.5.

```python
def advance_stage(current: str, state: str) -> tuple[str | None, str]:
    if state in ('dropped_layer0', 'routed_inbox', 'failed', 'done') and current == 'claude_harness':
        return (None, state)  # terminal
    if state in ('paused_cost_cap', 'paused_circuit_brkr'):
        return (current, state)
    if state == 'done':
        return (NEXT_STAGE[current], 'awaiting')
    raise ValueError(f"unexpected (stage={current}, state={state})")
```

**Test traces:**

| Input | First branch | Second branch | Third branch | Result |
|---|---|---|---|---|
| `('layer0', 'dropped_layer0')` | False (`current != 'claude_harness'`) | False | False | **ValueError** — but this is the legitimate terminal for Layer 0 drops |
| `('triage', 'routed_inbox')` | False | False | False | **ValueError** — but Step 1 routes low-triage to inbox |
| `('classify', 'routed_inbox')` | False | False | False | **ValueError** — Layer 2 block (per §4.5) |
| `('opus_step5', 'failed')` | False | False | False | **ValueError** — but `failed` should be terminal at any stage |
| `('opus_step5', 'paused_cost_cap')` | n/a | True | n/a | OK ✓ |
| `('claude_harness', 'done')` | True | n/a | n/a | OK ✓ |
| `('triage', 'done')` | False | False | True | OK ✓ (advances to resolve) |

`dropped_layer0`, `routed_inbox`, and `failed` are mid-pipeline terminals at **any stage**, not only at `claude_harness`. The first conditional gates them on `current == 'claude_harness'`, which is wrong. Every signal that drops at Layer 0 or routes to inbox at Step 1/Step 4 hits the ValueError.

**Fix.** Three lines:

```python
TERMINAL_STATES = {'dropped_layer0', 'routed_inbox', 'failed'}

def advance_stage(current: str, state: str) -> tuple[str | None, str]:
    if state in TERMINAL_STATES:
        return (None, state)
    if state in ('paused_cost_cap', 'paused_circuit_brkr'):
        return (current, state)
    if state == 'done':
        if current == 'claude_harness':
            return (None, state)
        return (NEXT_STAGE[current], 'awaiting')
    raise ValueError(f"unexpected (stage={current}, state={state})")
```

§10 test plan should include a parametric test over all (stage, state) pairs in the CHECK to surface this class of bug fast.

---

### B2 — Compatibility mirror writes status values that violate the existing CHECK

**Location:** §5.3.

KBL-A's CHECK constraint (KBL-A §289-292):
```sql
CHECK (status IN ('pending','processing','done','failed','expired',
                  'classified-deferred','failed-reviewed','cost-deferred'))
```

Mirror table at §5.3 writes:

| Mirror target | In KBL-A CHECK? |
|---|---|
| `pending` | ✓ |
| `processing` | ✓ |
| `done` | ✓ |
| `failed` | ✓ |
| `dropped` | ✗ **not allowed** |
| `inbox` | ✗ **not allowed** |
| `deferred` | ✗ **not allowed** |

Every UPDATE on a KBL-B signal that hits `dropped_layer0`, `routed_inbox`, or `paused_cost_cap` will fail the legacy CHECK constraint and abort the transaction. That covers ~30%+ of signals in steady state (Layer 0 drops + low-triage inboxing alone).

**Fix.** Pick one:

- **(a)** Reuse existing values: `dropped → 'expired'` (terminal-non-success-ish), `inbox → 'classified-deferred'` (signal landed but not Opus-processed), `deferred → 'cost-deferred'` (semantic match for paused_cost_cap; for paused_circuit_brkr also use 'cost-deferred' since legacy CHECK lacks a circuit-breaker value).
- **(b)** Expand the CHECK in §5.2: drop the constraint, re-add with `IN (..., 'dropped', 'inbox', 'deferred')` included. §5.1 says "KBL-A's existing 8-value CHECK stays in place" — this would be a slight retraction.

Either is fine architecturally. (a) keeps §5.1's promise but the mapping is lossy (paused_circuit_brkr collapses into `cost-deferred`). (b) extends the legacy CHECK by 3 values; KBL-A code reading `WHERE status='pending'` still works, code that switches on status sees 3 new values it doesn't know — graceful for read paths, may surprise CASE statements (none exist in current KBL-A code per `git grep "WHEN.*status"`).

I lean (b) — the 3 new values are more informative and the migration risk is essentially zero given no legacy CASE-on-status anywhere in the codebase.

---

### B3 — §4 contracts reference columns that don't exist as columns

**Location:** §4.2 Step 1, §4.3 Step 2.

The actual `signal_queue` base table (per `memory/store_back.py:6326-6363`):

```
id, created_at, source, signal_type, matter, summary, triage_score, vedana,
hot_md_match, payload, priority, status, stage, enriched_summary, result,
wiki_page_path, card_id, ayoniso_alert, ayoniso_type, processed_at, ttl_expires_at
```

§4.2 says Step 1 reads `subject` ("hint for email"). §4.3 says Step 2 reads `email_message_id`, `in_reply_to`, `references`, `sender`, `recipients`, `chat_id`, `sent_at`, `sender_phone`, `director_context_hint`. **None of these are columns.** They live in `payload JSONB`.

As-written, §6 prompt-template authors will pull these via `signal['email_message_id']` and get `None`. §10 test fixtures will be wrong. §11 logging will fail.

**Fix.** Either:

- **(a)** Document that these are JSONB extractions. Rewrite the contract:
  ```
  Reads: source, payload->>'subject' (email), payload->>'in_reply_to' (email),
         payload->>'chat_id' (whatsapp), ...
  ```
  Cleaner: define a `SignalSourceMetadata` Python adapter that takes a `signal_queue` row and exposes typed fields per source. Then contracts say "Reads: SignalSourceMetadata.email_in_reply_to" without each consumer hand-rolling JSONB extraction.

- **(b)** Promote the most-used metadata to bare columns via a §3.1 schema addition (adds 5-8 columns). Heavier migration, but enables indexes for resolve-by-thread queries. Probably overkill for Phase 1.

I lean (a). It also forces a single source-of-truth for "what shape is the payload" — which is currently undocumented in any brief I've seen. §4 could include a §4.0 "Payload schema by source" table.

---

## 3. Should-fix

### S1 — `triage_score` type mismatch silently no-ops

**Location:** §3.1 (carryover from earlier review) + §4.2 invariant.

Base table has `triage_score INT` (KBL-19). §3.1 says `ALTER TABLE signal_queue ADD COLUMN IF NOT EXISTS triage_score NUMERIC(5,2)`. **`IF NOT EXISTS` will silently no-op** — column stays INT. §4.2 invariant references `triage_score NUMERIC(5,2)` and the prompt likely returns `0-100` integers per the eval format (from `run_kbl_eval.py`).

Two options:
- Accept INT — change brief to `triage_score INT`. Loses `0.5` precision (probably never needed; eval scores are integers).
- Actually migrate type: `ALTER TABLE signal_queue ALTER COLUMN triage_score TYPE NUMERIC(5,2) USING triage_score::numeric`. One-line migration; existing values are NULL so cast is a no-op.

I lean accept INT — the eval prompt returns integers and there's no quantization argument for half-points.

### S2 — Schema sprawl from KBL-19 columns not addressed

**Location:** §3.1, §4 (implicit).

The base table has these KBL-19 columns the brief never mentions:
- `matter` (vs KBL-A's `primary_matter`) — drift risk: which is canonical?
- `wiki_page_path` (vs KBL-B's `target_vault_path`) — same conceptual field, two names
- `enriched_summary` (vs KBL-B's `final_markdown` / `opus_draft_markdown`?) — what's it for now?
- `hot_md_match`, `signal_type`, `result`, `card_id`, `ayoniso_alert`, `ayoniso_type` — KBL-19 reservations, status unclear
- `processed_at` (vs KBL-B's `committed_at`) — separate fields or same concept under different names?

KBL-A added `primary_matter`, `related_matters`, `triage_confidence`, `started_at` without retiring the legacy ones. KBL-B adds `target_vault_path`, `committed_at`, `final_markdown` etc. without retiring them either. By KBL-B end the table will have ~30+ columns with at least 6 redundant pairs.

**Fix.** §3 should add a sub-section "Legacy KBL-19 columns — disposition" with one of: (a) deprecate (deprecate notice + cleanup migration in Phase 2); (b) repurpose (e.g., reuse `wiki_page_path` instead of adding `target_vault_path`); (c) keep both, document the canonical vs legacy split.

If repurposing, several of the new columns aren't actually new — `vedana`, `triage_score`, and `stage` already exist (the §3.2 ALTER ADD also IF NOT EXISTS no-ops on `stage`).

### S3 — Worker claim ORDER BY conflates claim time with queue order, no retry budget

**Location:** §5.4.

```sql
ORDER BY started_at NULLS FIRST, id
```

Two issues:

1. **`started_at` is set on claim** (line 463: `state = 'running', started_at = NOW()`). If a signal goes back to `awaiting` after retry, what's `started_at`? The spec doesn't say. If it's untouched (still set to last claim time), retries land somewhere in the middle of the queue based on their last-claimed time — not deterministic by enqueue order. If it gets reset to NULL, retries jump to the front (priority over fresh signals — feels wrong).
2. **No retry budget.** A signal that hits Anthropic 529 and goes back to awaiting can be reclaimed indefinitely. R3 retry ladder (KBL-A) handles within-call retries but not across-claim retries.

**Fix.** Two new columns or one combined:
- `enqueued_at TIMESTAMPTZ DEFAULT NOW()` — set once at insert, never changes; use this for ORDER BY
- `claim_count INT DEFAULT 0` — increment on each claim; abort with `state='failed'` when claim_count > MAX_CLAIMS (e.g., 5)

Cheap to add and the queue order becomes deterministic regardless of retry behavior.

### S4 — `extracted_entities` invariant contradicts its own contract

**Location:** §4.4.

Contract says: "Unparseable fields → drop from output, not set to NULL/missing."

Invariant says: "`extracted_entities` is always a JSON object with all 6 keys present, values are arrays."

These conflict. If "drop from output" means omit the key, the invariant is violated. If "drop from output" means "exclude individual unparseable items but keep the (empty) array under that key", that's consistent with the invariant — but then "drop from output" is misleading wording.

**Fix.** Pick one:
- "All 6 keys always present, may be empty arrays" — invariant is the truth, "drop from output" is per-item not per-key.
- Drop the all-keys-present invariant — consumers handle missing keys.

I lean keep the invariant (consumer code is simpler) and clarify the wording.

### S5 — §4.9 "same transaction" is ambiguous given git push side effect

**Location:** §4.9 + §4.8.

Step 7 includes a `git push` (external side effect, can't be PG-rolled-back). The §4.9 cleanup says "a follow-up write within the same transaction nulls `opus_draft_markdown` and `final_markdown`". But:

- TX1 (PG): UPDATE state='done', committed_at, commit_sha
- (out-of-TX): git push
- TX2 (PG): UPDATE NULL out columns

Two PG transactions, with an external operation between. "Same transaction" is wrong — and worse, if you actually wrap (TX1 + git push + TX2) in one PG TX, you create a window where committed_at is set but git push hasn't happened yet, visible to other readers. Confusing.

**Fix.** Clarify: nullification happens in a separate PG transaction *after* git push succeeds. Or simpler: scheduled cleanup job (`UPDATE signal_queue SET opus_draft_markdown=NULL, final_markdown=NULL WHERE state='done' AND committed_at < NOW() - INTERVAL '5 minutes'`) — eventually consistent, no TX gymnastics. Five-minute lag is fine for a debug-data cleanup.

### S6 — Step 5 invariant misses `paused_circuit_brkr`

**Location:** §4.6 invariant.

> "exactly one of `opus_draft_markdown IS NOT NULL` OR `state='paused_cost_cap'` OR `state='failed'`"

Misses `state='paused_circuit_brkr'` (added in §5.2). Inconsistency.

**Fix.** Add to the invariant: `... OR state='paused_cost_cap' OR state='paused_circuit_brkr' OR state='failed'`.

### S7 — Missing termination invariant for the pipeline

**Location:** §4 (global).

Each step has its own invariant, but there's no global termination guarantee. Implicit: every signal eventually reaches state ∈ `{'done', 'failed', 'dropped_layer0', 'routed_inbox'}`. Without this stated, the test plan in §10 has no clear acceptance criterion for "the pipeline doesn't lose signals."

**Fix.** Add §4.10: "Termination invariant. For every signal inserted into `signal_queue`, after at most `KBL_PIPELINE_MAX_CLAIMS_PER_SIGNAL` claim cycles, `state ∈ {'done', 'failed', 'dropped_layer0', 'routed_inbox'}` — i.e., never indefinitely paused. Paused states (`paused_cost_cap`, `paused_circuit_brkr`) count toward claim budget; bounded retry guarantees bounded run."

---

## 4. Nice-to-have

### N1 — `paused_circuit_brkr` recovery flow undocumented in §5

§5.2 adds the state but doesn't say how a signal exits it. Per KBL-A, the circuit breaker has a recovery probe (`kbl_runtime_state.anthropic_circuit_open` flips back to false). Should the worker scan `paused_circuit_brkr` rows and reclaim them when the breaker closes? Or do they auto-go back to `awaiting` on a separate sweeper tick? Pin down in §5 or punt explicitly to §9.

### N2 — Step 2 `director_context_hint` undefined

§4.3 reads `director_context_hint` from Scan-side metadata. Where does this come from? Scan posts to a webhook? An additional payload field? Define before §6 Scan-source prompt fragments.

### N3 — Step 7 commit identity needs vault-side allowlist

`Baker Pipeline <pipeline@brisengroup.com>` — verify this email is acceptable in `baker-vault` git config (no commit-author allowlist enforcement). Probably fine since baker-vault uses HTTPS PAT auth, not signed commits, but worth a 30-second check before §12 rollout.

### N4 — §4.5 decision-table edge case "unreachable"

§4.5 lists: `triage_score < THRESHOLD → unreachable — Step 1 already routed this to inbox`. True per §4.2 routing. But a defensive `assert` in the actual implementation would catch shape regressions if someone later changes Step 1's routing logic. Note in §10 test plan: a unit test that confirms the unreachable branch is never hit on the 50-signal D1 fixture.

### N5 — `cost_ledger.signal_id` ON DELETE SET NULL means cost rollups survive purge

KBL-A defined this (§271). Means after a `signal_queue` row is purged (30-day TTL on done), the `kbl_cost_ledger` rows stay with `signal_id=NULL`, so daily cost aggregations remain valid. §9 should mention this for the dashboard query patterns. Not a §4-5 issue but worth flagging while I'm here.

---

## 5. Confirmations — prior-review fixes landed

All four B2 prior-review items appear in §4-5 cleanly:

| Prior B2 finding | Where applied | Verdict |
|---|---|---|
| B1 (Step 4 redundant LLM) | §4.5 — "deterministic policy" with decision table | ✓ landed clean |
| B2 (cost-cap vs circuit-breaker conflation) | §5.2 — `paused_cost_cap` + `paused_circuit_brkr` separate states | ✓ split correctly |
| S2 (per-source resolve) | §4.3 — email/WA = metadata-only ledger='no row', transcript/scan = embeddings ledger='one row' | ✓ landed |
| S4 (TOAST hygiene) | §4.9 — explicit nullification | ✓ landed (with S5 wording caveat above) |

Pattern discipline preserved.

---

## 6. Open questions for §6-13 (pre-flag)

Adding to the 12 questions from prior review:

13. **§6 prompts** — once payload-schema-by-source is documented (B3 fix), prompts can reference fields directly. Confirm that approach in §6.
14. **§7 error matrix** — should include a row for "B2 mirror UPDATE fails legacy CHECK" if §5 fix B2 is option (a) — i.e., legacy CHECK reuse. Defensive logging.
15. **§9 cost-control** — when a signal is in `paused_cost_cap` and the new UTC day starts, who flips it back to `awaiting`? A separate sweeper job? The next worker tick scanning paused rows? §9 should pin this.
16. **§10 test plan** — needs a parametric test over `(stage, state)` pairs in the CHECK to catch the §5.5 bug class (B1 above) early. Cheap to add.
17. **§11 observability** — `kbl_pipeline_run.signals_failed` counter — does it count `state='failed'` only, or also `dropped_layer0` and `routed_inbox`? Probably "failed" only; clarify.

---

## 7. Summary

- **Verdict:** REDIRECT (3 blockers, all small surface).
- **Blockers:** 3 (advance_stage logic; mirror CHECK conflict; column-vs-payload contract refs).
- **Should-fix:** 7 (triage_score type, schema sprawl, retry budget, extract invariant wording, TOAST TX wording, paused_circuit_brkr in §4.6, missing termination invariant).
- **Nice-to-have:** 5.
- **Prior-review fixes:** 4/4 confirmed landed.
- **Open §6-13 questions:** 5 new (now 17 total cumulative).

§4-5 are 80% ready. The redirect work is tactical: fix `advance_stage`, decide CHECK strategy for the mirror, add a payload-schema sub-section. Estimated 30 min of brief revision.

After that, §6-13 can build on a contracts foundation that won't trip Code Brisen #1 (or whoever implements) in week one.

---

*Reviewed 2026-04-18 by Code Brisen #2. Cross-checked against `briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF.md` (§289-292 status CHECK, §271 cost ledger FK), `memory/store_back.py:6326-6363` (signal_queue base columns), and `kbl/pipeline_tick.py:34-89` (KBL-A claim semantics). No code changes; design review only.*
