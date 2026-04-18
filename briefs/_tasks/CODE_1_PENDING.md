# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous:** PR #8 STEP1-TRIAGE-IMPL merged at `6382ee50` (final pipeline PR of the 5-way cascade). All 5 KBL-B Phase 1 PRs on main.
**Task posted:** 2026-04-18 (late evening)
**Status:** OPEN — Director ratified (A) Step 4 classifier next

---

## Task: STEP4-CLASSIFY-IMPL — Deterministic policy classifier

**Spec:** KBL-B §4.5 (lines 386-403 of `briefs/_drafts/KBL_B_PIPELINE_CODE_BRIEF.md`).

### Why

Step 4 is the last deterministic stage before Step 5 (Opus synthesis). It reads 4 columns already populated by Steps 1-3 (`triage_score`, `primary_matter`, `related_matters`, `resolved_thread_paths`) and writes a single decision column (`step_5_decision`) that gates whether Step 5 calls Opus or writes a deterministic stub. No model call, no cost ledger — pure Python policy evaluation.

### Scope

**IN**

1. **`migrations/20260418_step4_signal_queue_step5_decision.sql`** — idempotent:
   ```sql
   ALTER TABLE signal_queue
     ADD COLUMN IF NOT EXISTS step_5_decision TEXT;
   ```
   No CHECK constraint on this column yet (enum enforced in Python — avoids double-source-of-truth problem you can revisit in Phase 2 with the §5.1 two-track migration).

2. **`kbl/steps/step4_classify.py`** — the classifier:
   - `ClassifyDecision` enum (`StrEnum` subclass): `FULL_SYNTHESIS`, `STUB_ONLY`, `CROSS_LINK_ONLY`, `SKIP_INBOX`. Note: `CROSS_LINK_ONLY` is in the enum for Phase 2 completeness but **no decision rule currently maps to it** — document this in the enum docstring + flag the unreachable path in the classifier.
   - `classify(signal_id: int, conn) -> ClassifyDecision` — full pipeline: load row, apply decision table (below), write `step_5_decision`, advance state, return decision.
   - State transitions: `awaiting_classify` → `classify_running` → `awaiting_opus` (all in CHECK set post-PR-#12).
   - Failure path: any unexpected condition → `classify_failed` (in CHECK set) + raise `ClassifyError` (new in `kbl/exceptions.py`).

3. **Decision table (§4.5 verbatim):**

   | Order | Condition (Python) | Decision |
   |---|---|---|
   | 1 | `primary_matter not in allowed_scope` | `SKIP_INBOX` + Layer 2 INFO log |
   | 2 | `triage_score < THRESHOLD + NOISE_BAND` (default 40 + 5 = 45) | `STUB_ONLY` |
   | 3 | `resolved_thread_paths == []` AND `related_matters == []` | `FULL_SYNTHESIS` (new arc) |
   | 4 | `resolved_thread_paths == []` AND `related_matters != []` | `FULL_SYNTHESIS` + cross-link flag for Step 6 |
   | 5 | `resolved_thread_paths != []` | `FULL_SYNTHESIS` (continuation) |

   **First-match-wins** — evaluate in this exact order. Rule 6 from brief (`triage_score < THRESHOLD`) is unreachable because Step 1 already routed low-score signals to `routed_inbox`; raise `RuntimeError` if encountered (assertion for pipeline correctness).

4. **Allowed-scope derivation (Director ratification — 2026-04-18):**
   - `allowed_scope` = union of:
     - `KBL_MATTER_SCOPE_ALLOWED` env var (comma-separated; optional override)
     - ACTIVE matters parsed from `~/baker-vault/wiki/hot.md`
   - **Default behavior when env unset:** derive purely from hot.md ACTIVE block. This is the ratified pattern — NO hardcoded allowlist. Env exists only as an override for edge cases (testing, rollout drills).
   - Helper: `_load_allowed_scope() -> frozenset[str]` — reads hot.md via `kbl.loop.load_hot_md()` (PR #6), extracts `**<slug>**:` lines from `## Actively pressing` block, unions with env override if set.
   - Cache per classify() call — not module-level (hot.md may update between invocations; CHANDA Inv 3 applies).

5. **Cross-link flag for Step 6 (Rule 4):** encode as a JSONB hint on `signal_queue` — don't introduce a new column. Use `signal_queue.extracted_entities` JSONB (already exists per PR #11) with a sentinel key, OR add a new small column `cross_link_hint BOOLEAN DEFAULT FALSE`. **Recommendation: new column** — cleaner, queryable, explicit semantic. Migration adds it alongside `step_5_decision`.

6. **Environment variables:**
   - `KBL_PIPELINE_TRIAGE_THRESHOLD` (already exists from Step 1; default 40) — read same env, don't duplicate
   - `KBL_STEP4_NOISE_BAND` — default 5; int parse with fallback
   - `KBL_MATTER_SCOPE_ALLOWED` — optional; empty string = unset = derive from hot.md only

7. **`kbl/exceptions.py`** — add `ClassifyError(KblError)` (net-additive alongside existing errors). Subclass docstring explains it's raised only on unexpected condition (e.g., `triage_score < THRESHOLD` at Step 4 entry, which Step 1 should have prevented).

8. **Logging (§4.5):**
   - Layer 2 gate block (Rule 1 fires): `INFO`, `component='classify'`, `message=f'layer2_blocked: primary_matter={pm!r} not in allowed={sorted(allowed_scope)}'`.
   - No other per-call log. Rule 2-5 are expected paths.

9. **Tests** — `tests/test_step4_classify.py`:
   - **Decision-table coverage:** 5 tests, one per rule (+ the unreachable assertion)
   - **Allowed-scope derivation:** 4 tests — hot.md only, env override only, union, both empty (everything goes `SKIP_INBOX`)
   - **Inv 3 compliance:** `_load_allowed_scope` reads hot.md on EVERY classify() call, NOT cached module-level. Explicit `@patch` call-count assertion over 3 successive invocations (mirrors Step 1's `test_triage_invocation_reads_hot_md_and_ledger_once`).
   - **Cross-link hint:** Rule 4 sets `cross_link_hint=TRUE`, Rule 3 sets it `FALSE`. SQL write verified in test.
   - **State-machine:** `awaiting_classify` → `classify_running` → `awaiting_opus` on success; `classify_failed` on `ClassifyError`. Verify each status value is in the 34-value CHECK set.
   - **Env parsing robustness:** `KBL_STEP4_NOISE_BAND=abc` → fallback to 5 with WARN; `KBL_MATTER_SCOPE_ALLOWED=""` → empty override (hot.md is sole source).
   - `@requires_db` live-PG round-trip: classify against real PG signal row, verify column write + CHECK-constraint compliance end-to-end.

### CHANDA pre-push

- **Q1 Loop Test:** Step 4 reads hot.md on every classify() call via `_load_allowed_scope`. **This is a Leg 3 read surface** — same invariant as Step 1. Explicit test asserts fresh-read per invocation. Pass.
- **Q2 Wish Test:** serves wish — Director's hot.md ACTIVE set is the authoritative filter for which signals cost Opus tokens. Convenience co-aligned (deterministic policy gates the expensive model call). Pass.
- **Inv 3 preserved:** `_load_allowed_scope()` reads hot.md on each call, not cached.
- **Inv 6 preserved:** Step 4 always advances; never skips Step 6 downstream.
- **Inv 10 preserved:** no prompt; enum + table are stable code.

### Branch + PR

- Branch: `step4-classify-impl`
- Base: `main`
- PR title: `STEP4-CLASSIFY-IMPL: kbl/steps/step4_classify.py + deterministic policy classifier`
- Target PR: #13 (or next available)

### Reviewer

B2.

### Timeline

~45-60 min (smaller than Step 1-3 because no Ollama, no Voyage, no prompt template — pure Python policy + hot.md reader + 1 migration + tests).

### Dispatch back

> B1 STEP4-CLASSIFY-IMPL shipped — PR #<N> open, branch `step4-classify-impl`, head `<SHA>`, <N>/<N> tests green. Ready for B2 review.

### After this task

Next dispatch to you: **STEP5-OPUS-IMPL** — the Opus synthesis stage. Large task (~2-3 hours). Spec in KBL-B §4.6 + `briefs/_drafts/KBL_B_STEP5_OPUS_PROMPT.md` (B3-authored, APPROVE'd, slug-v9-folded at `50167a1`). Depends on this PR + `load_gold_context_by_matter` (PR #9 merged).

OR: **OLLAMA-CLIENT-REFACTOR-1** (lift shared helper per PR #11 N1) — optional cleanup, ~20 min.

---

*Posted 2026-04-18 (late evening) by AI Head. Director ratified (A). All 5 Phase 1 PRs merged; Step 4 is the last deterministic step before Opus.*
