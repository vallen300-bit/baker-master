# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (app instance)
**Task posted:** 2026-04-18 (late)
**Status:** OPEN — two reviews in queue

---

## Completed since last dispatch

- Task A — PR #7 review (REDIRECT → phone-delta APPROVE @ `6fb6c89`) ✓
- Task B — STEP5-OPUS-PROMPT review (REDIRECT → S1 delta APPROVE @ `b7c0b0c`) ✓
- Task C-delta-phone — PR #7 S1 fix re-verify ✓
- Task C-new — PR #9 LOOP-GOLD-READER-1 (APPROVE) ✓
- Task C-delta — STEP5-OPUS S1 APPROVE ✓
- Task D — REDIRECT fold (APPROVE @ `f712647`) ✓
- Task E — PR #10 STEP2-RESOLVE-IMPL (REDIRECT @ `7059ce3`, pipeline-wide S1) ✓

Your S1 from Task E is with Director. AI Head ratification of remediation path pending.

---

## Task F (now): Review PR #11 — STEP3-EXTRACT-IMPL

**PR:** https://github.com/vallen300-bit/baker-master/pull/11
**Branch:** `step3-extract-impl`
**Head:** `ee7036a`
**Tests:** 47/47 new green per B1 PR description

### Scope

**IN**
- `kbl/prompts/step3_extract.txt` — template matches `briefs/_drafts/KBL_B_STEP3_EXTRACT_PROMPT.md` (Inv 10: file-loaded once, no self-modification)
- `kbl/steps/step3_extract.py` — `build_prompt` / `parse_gemma_response` / `call_ollama` / `extract` / `ExtractedEntities` dataclass
- `kbl/exceptions.py` — `ExtractParseError` added net-additively alongside PR #8/#10 variants (B1 notes coexistence — verify no regression)
- `migrations/20260418_step3_signal_queue_extracted_entities.sql` — idempotent `ADD COLUMN IF NOT EXISTS extracted_entities JSONB` + GIN index
- **State transitions:** `awaiting_extract` → `extract_running` → `awaiting_classify` (success OR retries-exhausted) or `extract_failed` (Ollama unreachable)
- **R3 retry policy:** malformed top-level JSON → retry once; second failure → empty stub + `success=False` cost row + advance to `awaiting_classify` (pipeline keeps flowing)
- **Sub-field drop rules:** non-numeric money amount / unknown currency / non-ISO date / bool amount / empty names → drop silently
- **Director self-reference strip:** `Dimitry Vallen` from people array, `Brisen`/`Brisengroup` from orgs array
- **Cost ledger:** `step='extract'`, `model='gemma2:8b'`, `cost_usd=0`, `success=True`/`False` on parse outcome

### Specific scrutiny

1. **S1-class status writes (CRITICAL):** PR #11 introduces `extract_running` / `extract_failed` state writes. Confirm these violate the live KBL-A `signal_queue.status` CHECK constraint in the same pattern as PR #7/#8/#10. If yes, mark inherits the pipeline-wide S1 — not PR-intrinsic blocker but flagged for the same migration unblock.
2. **Ollama client drift:** B1 notes `call_ollama` mirrors `step1_triage.call_ollama` byte-for-byte except `num_predict=1024`. Verify no silent drift (endpoint, timeout, seed, temperature, error surface). Flag if duplicated code will cause maintenance gap when shared `kbl/ollama.py` refactor lands.
3. **R3 retry semantics:** two calls max (1 initial + 1 retry). Verify no off-by-one (3 calls accidentally) and that `kbl_cost_ledger` gets ONE row per `extract` invocation, not one per attempt.
4. **Partial-JSON handling:** missing sub-keys default to `[]`, not NULL. Verify `ExtractedEntities.to_dict()` always yields all 6 keys.
5. **Director self-reference strip correctness:** case-insensitive? Does `dimitry vallen` (lowercase) get stripped? `BrisenGroup` (mixed case)?
6. **Inv 10 template stability:** verify explicit test that re-invoking `build_prompt` twice reads the same cached template (no per-call file re-read).
7. **CHANDA Q1/Q2 citation** in pre-push — verify B1 did the self-check.

### Format

`briefs/_reports/B2_pr11_review_20260418.md`
Verdict: APPROVE / REDIRECT (inline-appliable fixes) / BLOCK

### Timeline

~30-40 min.

---

## Task C (still pending): Review PR #8 — STEP1-TRIAGE-IMPL

**PR:** https://github.com/vallen300-bit/baker-master/pull/8
**Branch:** `step1-triage-impl`
**Head:** `4918b52`
**Tests:** 44/44 new green + 1 live-PG skip

### Scope

**IN**
- `kbl/prompts/step1_triage.txt` — template extract matches `KBL_B_STEP1_TRIAGE_PROMPT.md` §1.1 (Inv 10 compliance)
- `kbl/steps/step1_triage.py` — `build_prompt` / `parse_gemma_response` / `normalize_matter` / `call_ollama` / `triage` / `TriageResult`
- `kbl/exceptions.py` — `TriageParseError` + `OllamaUnavailableError`
- `migrations/20260418_step1_signal_queue_columns.sql` — idempotent `ADD COLUMN` ×6
- **State transitions:** `awaiting_triage` → `triage_running` → `awaiting_resolve` OR `awaiting_inbox_route` based on threshold (inherits S1)
- **CHANDA Inv 3:** hot.md + feedback_ledger read on EVERY call (not cached across invocations)
- **CHANDA Inv 1:** zero-Gold / zero-hot.md / zero-ledger renders fallback strings, not crash
- **Cost ledger:** `step='triage'`, `model='gemma2:8b'`, `cost_usd=0.0`

### Specific scrutiny

1. `call_ollama` error paths — DB-conn-lost / Ollama timeout / malformed response
2. `parse_gemma_response` — accepts both `null` and string `"null"` for primary_matter (Gemma inconsistency)
3. Triage threshold: `KBL_PIPELINE_TRIAGE_THRESHOLD=40` default. `triage_score == 40` inclusive or exclusive of PASS?
4. Cross-matter elevation: does `triage()` consume hot.md to adjust score, or is that prompt-side?
5. Env var naming: `KBL_STEP1_LEDGER_LIMIT` canonical — consistent use
6. **S1-class status writes:** `triage_running` violates live CHECK constraint — flag as inherits pipeline-wide S1

### Format

`briefs/_reports/B2_pr8_review_20260418.md`
Verdict: APPROVE / REDIRECT / BLOCK

### Timeline

~30-40 min.

---

## Parallel state

- **B1:** idle since PR #11 ship. Awaits migration decision + next dispatch.
- **B3:** idle (standdown posture).
- **AI Head:** Director decision pending on PR #10 S1 remediation; KBL-C §4-10 authoring queued.

### Dispatch back (after each task)

> B2 PR #11 review done — `briefs/_reports/B2_pr11_review_20260418.md`, commit `<SHA>`. Verdict: <...>.
> B2 PR #8 review done — `briefs/_reports/B2_pr8_review_20260418.md`, commit `<SHA>`. Verdict: <...>.

---

*Posted 2026-04-18 (late) by AI Head. Run these in series; either order is fine.*
