# PR #8 Combined S1+S2 Delta Review (B2 — Task H, final pipeline PR)

**From:** Code Brisen #2
**To:** AI Head
**Re:** [`briefs/_tasks/CODE_2_PENDING.md`](../_tasks/CODE_2_PENDING.md) Task H — PR #8 combined delta review
**PR:** https://github.com/vallen300-bit/baker-master/pull/8
**Branch:** `step1-triage-impl`
**Head reviewed:** `7d0d67b` (merge commit resolving exceptions.py + slugs.yml additive conflicts via union)
**Parents:** `c738052` (PR8-S1 rename) + `db807f0` (main after PR #7/#10/#11/#12)
**Prior reviews:** `85a759f` (initial REDIRECT, 2 should-fix + 4 nice-to-have), `1feebf7` (PR #12 review cited `routed_inbox` as canonical, option b ratified)
**Mergeable:** `MERGEABLE` per `gh pr view 8`
**Date:** 2026-04-18
**Time:** ~25 min

---

## 1. Verdict

**APPROVE.** S1 rename is crisp and complete; S2 state-leak fix lands cleanly with coherent three-test cluster; merge-commit resolution holds union semantics with zero code drift; all CHANDA Inv 3 contracts explicitly tested. Ready to auto-merge as the final pipeline PR.

One nice-to-have: stale `awaiting_inbox_route` references in `briefs/_tasks/CODE_1_PENDING.md:27,38` (B1's dispatch mailbox — not production). Non-blocking.

---

## 2. Blockers

**None.**

---

## 3. Should-fix

**None.**

---

## 4. Nice-to-have

### N1 — Stale `awaiting_inbox_route` in B1 dispatch mailbox

`briefs/_tasks/CODE_1_PENDING.md` still contains the pre-rename state name on two lines:

```
27:   - State transitions: `awaiting_triage` → `triage_running` → `awaiting_resolve` OR `awaiting_inbox_route` (if triage_score < `KBL_PIPELINE_TRIAGE_THRESHOLD`, default 40)
38:   - Triage-threshold gating: score < 40 → state `awaiting_inbox_route`; score >= 40 → `awaiting_resolve`
```

The file is B1's historical task-language cache, not production code or tests. Pre-rename dispatches are expected to carry the old term. Fix if you're cleaning up before Phase 2; otherwise harmless — the only risk is a future B1 re-read picking up the stale term, which this report documents.

---

## 5. S1 rename audit — `awaiting_inbox_route` → `routed_inbox`

### 5.1 Production + test surface: zero survivors

`git grep 'awaiting_inbox_route' kbl/ tests/` on head `7d0d67b` returns **zero** matches. Complete.

### 5.2 Semantic strengthening — terminal-state contrast explicit

Beyond a mechanical rename, B1 upgraded the docstring + inline commentary to make the terminal semantic explicit. Three sites worth flagging as real improvements:

| Location | Before (067e29c) | After (c738052) |
|---|---|---|
| Module docstring state-diagram | `\\-> awaiting_inbox_route` | `\\-> routed_inbox (terminal)` + 4-line block contrasting terminal vs `awaiting_*` pre-claim holds |
| `_ROUTED_INBOX_STATE` constant comment | implicit | "Terminal inbox state per §4.2. Used for both low-triage-score routing AND retries-exhausted stub routing — both outcomes put the signal on the Director's inbox surface" |
| `_next_state_for` | bare function | Added docstring: "Low-score → terminal ``routed_inbox``; threshold or above → ``awaiting_resolve`` for Step 2 pickup. Boundary is inclusive." |

The terminal-vs-pre-claim-hold contrast was implicit in my PR #8 initial review and PR #12 review Option-b recommendation; B1 surfaced it explicitly. Good.

### 5.3 Brief §4.2 alignment

`briefs/_drafts/KBL_B_PIPELINE_CODE_BRIEF.md`:
- Line 251: `'completed', 'dropped_layer0', 'routed_inbox'` — terminal class
- Line 301: `state='routed_inbox' terminal, target_vault_path='wiki/_inbox/<yyyymmdd>_<signal_id_short>.md'`
- Line 497: `TERMINAL_STATES = {'dropped_layer0', 'routed_inbox', 'failed'}`

PR #8 head matches exactly. ✓

### 5.4 CHECK set + store_back sync (post-PR #12)

| Location | Line | Value |
|---|---|---|
| `migrations/20260418_expand_signal_queue_status_check.sql:56` | in §Step 1 block | `'routed_inbox',` ✓ |
| `memory/store_back.py:6423` | `_ensure_signal_queue_additions()` | `'routed_inbox',` ✓ |

Both locations hold the canonical post-rename name. The PR #12 sync-guard test catches drift; this re-cite confirms the path B1 went down (option b — value rename in the brief-level canonical set, not a second CHECK-expand migration) landed consistently.

### 5.5 Test assertions — all three assertion sites renamed

| Test | Line | New assertion |
|---|---|---|
| `test_triage_routes_low_score_to_inbox` | 567 | `assert "routed_inbox" in params` |
| `test_triage_threshold_env_override` | 584 | `assert "routed_inbox" in params` + comment "50 < 70 → terminal inbox state" |
| `test_triage_parse_error_retries_exhausted_writes_stub` | 690 | `assert "routed_inbox" in params` + "(§4.2 canonical name; not a pre-claim hold)" |

Three sites, three renames. No orphans.

---

## 6. S2 delta audit — state-leak fix

### 6.1 Retry-budget + pared-prompt machinery

| Item | Location | Verdict |
|---|---|---|
| `_RETRY_BUDGET = 1` | `kbl/steps/step1_triage.py:96` | ✓ 2 Ollama calls max (initial + 1 retry) |
| `_LEDGER_PARED_MARKER = "[LEDGER OMITTED — R3 retry]"` | :97 | ✓ marker present in prompt; tests assert it surfaces |
| `_build_pared_prompt(signal_text, slug_glossary, hot_md_block)` | :206 | ✓ caller passes pre-computed blocks; does NOT re-read hot.md/ledger |
| Drops ledger only; keeps glossary + hot.md + signal | :226-230 | ✓ `test_pared_prompt_omits_ledger` asserts marker in, ledger content out |

### 6.2 Retries-exhausted path — stub + route

| Field | Value | Verdict |
|---|---|---|
| `primary_matter` | `None` | ✓ |
| `related_matters` | `()` | ✓ |
| `vedana` | `None` | ✓ (TriageResult.vedana widened to `Optional[str]` at :115) |
| `triage_score` | `0` | ✓ |
| `triage_confidence` | `0.0` | ✓ |
| `summary` | `"parse_failed"` | ✓ (from `_STUB_SUMMARY` :99) |
| Next state | `_ROUTED_INBOX_STATE` ("routed_inbox") | ✓ terminal |
| Cost rows written | 2, both `success=False` | ✓ asserted in test |
| `TriageParseError` escapes? | **No** — explicit `test_triage_parse_error_does_not_raise_past_retry_budget` omits `pytest.raises` | ✓ |

### 6.3 Happy-retry path — first fails, second succeeds

`test_triage_parse_error_first_attempt_triggers_retry`:

| Assertion | Verified |
|---|---|
| `m_call.call_count == 2` | ✓ |
| Second-call prompt contains `[LEDGER OMITTED — R3 retry]` | ✓ via `m_call.call_args_list[1]` |
| Exactly TWO cost rows (F, then T) | ✓ order-preserving check on `cost_rows[0][1][-1] is False`, `cost_rows[1][1][-1] is True` |
| Exactly ONE result UPDATE (the winning attempt) | ✓ `len(update_rows) == 1` |
| Score-based routing (55 ≥ 40 → `awaiting_resolve`) | ✓ |

### 6.4 Inv 3 preservation — **Leg 3 critical** re-verify

**The anchor test**: `test_triage_invocation_reads_hot_md_and_ledger_once` (line 223). Runs two scenarios:

1. **Happy path** (valid first response, no retry needed): asserts `m_hot.call_count == 1 AND m_ledger.call_count == 1`.
2. **Retries-exhausted path** (both attempts unparseable): asserts the SAME single-read contract on `m_hot2.call_count == 1 AND m_ledger2.call_count == 1`.

The architectural move that makes Inv 3 work cleanly: `_read_prompt_inputs(conn)` is called ONCE in `triage()` (line 629), yielding `(glossary, hot_md_block, ledger_block)`. The retry path calls `_build_pared_prompt(signal_text, glossary, hot_md_block)` which is a pure render helper — it does NOT touch `load_hot_md` or `load_recent_feedback`. A companion test `test_pared_prompt_does_not_read_hot_md_or_ledger` (line 206) verifies that too via `@patch` call-count == 0.

CHANDA Inv 3 contract: **"hot.md + feedback_ledger read on EVERY `triage()` call, not cached across invocations"** → satisfied per-invocation, not per-prompt-build. Retries share the already-fresh values rather than skipping them or double-reading. ✓

### 6.5 Transport errors don't count against the parse budget

`test_triage_ollama_unreachable_still_propagates` (line 708) confirms `OllamaUnavailableError` re-raises unchanged. Parse-retry budget reserved for malformed model output only. Matches task contract:

```
_RETRY_BUDGET = 1
Transport failures are NOT counted against the parse-retry budget
```

### 6.6 Test count delta

| Base (4918b52) | Head (7d0d67b) | Delta |
|---|---|---|
| 44 test functions | 51 test functions | +7 |

Matches B1's PR description exactly. The 7 new tests:

1. `test_pared_prompt_omits_ledger`
2. `test_pared_prompt_escapes_quotes_and_truncates`
3. `test_pared_prompt_does_not_read_hot_md_or_ledger`
4. `test_triage_invocation_reads_hot_md_and_ledger_once`
5. `test_triage_parse_error_first_attempt_triggers_retry`
6. `test_triage_parse_error_retries_exhausted_writes_stub` (replaces the pre-fix `test_triage_parse_error_writes_failure_ledger_row_and_raises`)
7. `test_triage_parse_error_does_not_raise_past_retry_budget`
8. `test_triage_ollama_unreachable_still_propagates`

(That counts 8 new + 1 replaced = net +7. Check.)

---

## 7. Merge-commit resolution audit (`7d0d67b`)

AI Head resolved two additive conflicts via union. Verified both hold without code drift:

### 7.1 `kbl/exceptions.py` — superset adoption

| Parent | Classes present |
|---|---|
| PR #8 branch (c738052) | `KblError`, `TriageParseError`, `OllamaUnavailableError` |
| main (db807f0) | `KblError`, `TriageParseError`, `OllamaUnavailableError`, `VoyageUnavailableError` (PR #7), `ResolverError` (PR #10), `ExtractParseError` (PR #11) |
| **Merge (7d0d67b)** | **All 6 classes — identical to main** |

`git diff main..7d0d67b -- kbl/exceptions.py` produces **zero diff**. Clean union. Same pattern AI Head resolved for PR #11 per task brief line 19 ("additive conflict resolved by AI Head"). ✓

### 7.2 `tests/fixtures/vault_layer0/slugs.yml` — broader-comment adoption

Comment block divergence only; YAML matter data (`ao`, `movie`, `gamma` + aliases) is byte-identical across both parents. The merge kept PR #8's comment:

```
# Shared fixture vault for Layer 0 + Step 1 evaluator tests.
# - `ao` (2 chars canonical) — short-slug alias-required topic override
# - `movie` (5 chars canonical) — MO Vienna, aliases for topic override
# - `gamma` — no aliases; used as negative test + step 1 related-matter tests
```

Correct choice: PR #8's comment is the accurate superset (fixture is now shared by Step 1 too, per the added `related-matter tests` note). Taking main's narrower comment ("Layer 0 evaluator short-slug tests") would have been a regression in accuracy. ✓

### 7.3 Content integrity on the merge commit

Spot-checked at `7d0d67b`:

- `kbl/steps/step1_triage.py` — `_RETRY_BUDGET = 1` @ :96, `_ROUTED_INBOX_STATE = "routed_inbox"` @ :102, `_build_pared_prompt` @ :206, `_read_prompt_inputs` @ :570, `_build_stub_result` @ :591, `_write_triage_result(conn, signal_id, stub, _ROUTED_INBOX_STATE)` @ :658. All intact.
- `tests/test_step1_triage.py` — all 7 new test functions present + 3 rename sites confirmed.
- Zero `awaiting_inbox_route` in `kbl/` or `tests/`.

No drift introduced by the merge. The conflict resolution is a pure union with no transitive edits to pipeline code. ✓

---

## 8. CHANDA audit

### Q1 Loop Test — Leg 3 surface (Step 1 integration)

**Touched. Re-verified with rigor per task brief.**

- **Leg 1 (Gold-read):** N/A this PR — no Gold context fetched in Step 1 (per brief §4.2, Gold is Step 2+ territory).
- **Leg 2 (ledger-write):** touched via `_write_cost_ledger` on every attempt (both success=True and success=False rows written). No regression — same ledger-write pattern as base; retry adds one additional success=False row per failed attempt.
- **Leg 3 (Step 1 integration):** the central axis of this PR. `_read_prompt_inputs(conn)` executes fresh `load_hot_md()` + `load_recent_feedback(conn, limit=20)` + `_build_glossary()` once per `triage()` call. Both happy + retries-exhausted paths preserve the one-read-per-invocation contract. Retry reuses the `(glossary, hot_md_block)` values via `_build_pared_prompt` without re-reading. The explicit assertion test (§6.4 above) is the Inv 3 anchor.

### Q2 Wish Test — convenience drift

No drift. The rename makes §4.2 terminal semantics honest (a name starting with `awaiting_*` implied a pending-claim that never materializes — confusing). The retry + stub-and-route pattern prevents silent stalls on parse failure (Director sees `parse_failed` rows in inbox, not signals stuck in `triage_running`). Both moves are wish-aligned: the pipeline flows to completion, nothing stalls, nothing silently drops.

### Per-invariant check

| Invariant | Status |
|---|---|
| Inv 1 (zero-Gold) | Unaffected. `_HOT_MD_FALLBACK`, `_LEDGER_FALLBACK` preserved; empty/unavailable inputs still render fallback strings |
| Inv 3 (fresh reads per invocation) | **Explicitly re-certified** via anchor test on both paths |
| Inv 9 (Mac Mini single writer) | Unaffected (schema write path unchanged; PR #12 already handled) |
| Inv 10 (Gold file-loaded once, no self-modification) | Preserved — `_load_template()` cached at module scope; explicit test `test_template_file_exists_and_has_all_placeholders` |

---

## 9. Unblock status (post-PR #12 merge)

Per task brief §5 ("PR #8 now mergeable against new main"):

- PR #12 merged ✓ (CHECK set with `routed_inbox` live on main)
- PR #7 merged ✓
- PR #10 merged ✓
- PR #11 merged ✓
- PR #8 head `7d0d67b` reports `mergeable: MERGEABLE` via `gh` ✓

Previous CONFLICTING state (at `c738052`) resolved by the merge commit. Ready to auto-merge.

---

## 10. Summary

- **Verdict:** APPROVE.
- **Blockers:** 0.
- **Should-fix:** 0.
- **Nice-to-have:** 1 (N1 — stale `awaiting_inbox_route` in `CODE_1_PENDING.md:27,38`; dispatch-mailbox residue, non-production).
- **S1 rename:** complete. Zero survivors in production code + tests. Terminal-state semantic made explicit in docstring + inline commentary. Brief §4.2 alignment exact.
- **S2 state-leak fix:** retry budget + pared prompt + stub-and-route + Inv 3 single-read anchor — all seven new tests coherent and assertion-rigorous.
- **Merge-commit integrity:** pure union resolution for `kbl/exceptions.py` (6-class superset matches main exactly) + `tests/fixtures/vault_layer0/slugs.yml` (broader comment retained); step1_triage.py and test file unchanged on merge.
- **CHANDA Leg 3:** Inv 3 re-certified via explicit `@patch` call-count test on both happy + retries-exhausted paths.
- **Ready to auto-merge** as final pipeline PR per task brief §5.

This closes the three-cycle arc on Step 1 cleanly: feat → S1 + S2 (REDIRECT at `85a759f`) → combined S1 rename + S2 state-leak fix (APPROVE at this report).

---

*Reviewed 2026-04-18 by Code Brisen #2. Files @ `7d0d67b` (merge commit). Cross-referenced against `main` CHECK set (`migrations/20260418_expand_signal_queue_status_check.sql`), brief §4.2, prior reviews `85a759f` + `1feebf7`. Scope: S1 rename + S2 delta + merge integrity. ~25 min.*
