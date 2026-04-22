---
title: "B3 review — PR #36 STEP5_STUB_SCHEMA_CONFORMANCE_AUDIT_1"
pr_url: https://github.com/vallen300-bit/baker-master/pull/36
reviewer: Code Brisen #3
reviewed: 2026-04-22
verdict: APPROVE
head_sha: 9703745
baseline_sha: b73fb49
author: B1
branch: step5-stub-schema-conformance-audit-1
---

# Verdict: APPROVE — Tier A auto-merge greenlit

B1's audit kills the whole Step 5 stub → Step 6 Pydantic drift class structurally. All 8 focus items green, zero gating nits, regression delta reproduced exactly (+29 passed, 0 regressions, identical pre-existing failure set).

Two non-blocking N-nits parked for a later unification pass (neither introduced by this PR — both pre-existing code smells surfaced during review).

## Per focus item

### 1. ✅ Axis 1/2 helper correctness

Read all 4 new helpers end-to-end:

**`_normalize_stub_inputs` (step5_opus.py:426):**
- (a) Enforces: slug-registry membership (primary + related via `active_slugs()`), §4.2 null-primary ⇒ empty-related, no-primary-in-related order-preserving dedupe, vedana Literal coercion to `"routine"`. All 4 listed invariants covered.
- (b) Order: slug filter runs BEFORE §4.2 check — critical, because the registry can *cause* primary to drop to None, which then triggers §4.2. Dedupe runs AFTER §4.2 — no-op when §4.2 hit; otherwise primary seeded into `seen` prevents echo. Order is correct.
- (c) No dead branches. `seen.add(primary)` guarded by `if primary is not None`.
- (d) Idempotent — re-running on already-normalized inputs produces identical output (filter is stable, dedupe is order-preserving, vedana check is single-pass).
- (e) Deterministic — `[s for s in inputs.related_matters if s in active]` preserves producer order; dedupe preserves first-occurrence order. No dict-iteration dependency.

**`_normalize_stub_title` (step5_opus.py:481):**
- Strip → rstrip trailing `.` / ws → fallback-if-empty → cap 160 → re-trim → fallback again. Order correct; double-guard on empty after re-trim covers pathological "159 chars then a period" case. Idempotent.

**`_pad_stub_body` (step5_opus.py:497):**
- Only pads when `len(body) < 300`. While-loop guards against zero-length filler via `if filler.strip()`. Idempotent: already-padded body returns unchanged.
- **N2 (cosmetic)**: `needed = _STUB_BODY_MIN_CHARS - len(body)` is computed then immediately `del needed`'d — leftover from an earlier implementation. Non-blocking, but trivially removable in a later pass.

**`_cap_stub_body` (step5_opus.py:518):**
- Caps at 600 with ellipsis reserve (3 chars), prefers word boundary within 80 chars of the cut. Idempotent: body ≤ 600 returns unchanged.

**Validator coverage map** (grep of `@field_validator` / `@model_validator` / `_validate_slug_against_registry` in `kbl/schemas/silver.py`):

| Validator | Line | Audit coverage |
|-----------|------|----------------|
| `_amount_positive` (MoneyMention) | 101 | N/A — stub never emits money |
| `_title_shape` | 160 | `_normalize_stub_title` |
| `_created_utc` | 172 | `_iso_utc_now` (pre-existing) |
| `_deadline_iso_date` | 181 | N/A — stub never emits deadline |
| `_money_cap` | 192 | N/A |
| `_thread_continues_paths` | 199 | N/A |
| `_no_primary_in_related` | 214 | `_normalize_stub_inputs` dedupe |
| `_null_primary_implies_empty_related` (§4.2) | 231 | `_normalize_stub_inputs` forcing |
| `MatterSlug` registry | 53 | `_normalize_stub_inputs` active-filter |
| `_body_length` | 261 | `_pad_stub_body` floor + body filler prose |
| `_no_gold_self_promotion` | 271 | Filler prose scrubbed, test #16 locks |
| `_stub_status_matches_shape` | 285 | `_cap_stub_body` ceiling |
| `_excerpt_length` (CrossLinkStub) | 330 | N/A — stub writers don't emit cross-links |

Coverage is comprehensive. B1's Axis 2 matrix (ship report §3) accurately enumerates every cross-field validator.

### 2. ✅ Axis 3 fresh-connection pattern

`_route_validation_failure` (step6_finalize.py:720) — release-clean:

- Outer `try / except Exception as e` catches any failure from the inner block (including `get_conn()` itself failing). Logs to stderr + returns. Never masks the caller's re-raise.
- Inner `with get_conn() as fresh_conn:` context manager guarantees close.
- Inner `try / except` rolls back on error before re-raising so the fresh connection is left clean-closed.
- Signature change `(conn, row, *, error_count)` → `(row, *, error_count)` applied uniformly at all 4 call sites (finalize.py:612/635/642/663).

**Retry-bump idempotency:** `_increment_retry_count` is a straight `UPDATE ... SET retry = retry + 1 RETURNING retry`; each call does exactly one bump and commits. This is semantically correct — the retry counter IS the budget, and each failed finalize *should* bump it. The error handler invokes it exactly once per finalize() call (always paired with a subsequent `raise`), so no double-bump within a single invocation is possible.

**N1 (pre-existing, not introduced by this PR)**: the `error_count` parameter is received but never referenced in the new body — same as in the pre-fix version. B1 preserved it for call-site compatibility. Cleanup for a later unification brief; non-blocking.

### 3. ✅ Axis 4 test coverage quality

23 named tests + 8 parametrized sub-cases = **29 total leaf tests**, matching B1's ship report.

Quality review:
- Every assert pins a specific value, not `is not None` or presence-only checks. Examples: test #5 asserts `fm["related_matters"] == [_MOVIE, _GAMMA]` (order-preserving, primary stripped, dup removed) — would fail on *any* drift of filter order, dedupe, or slug stripping. Test #23 asserts `opus_failed_updates = [c for c in fresh._calls if c[1] == ("opus_failed", 9003)]` and `opus_failed_updates` truthy — pins both the state value AND the parameterized signal_id on the right conn.
- Known-bad shapes from error logs covered:
  - ✅ null-primary + non-empty related_matters (tests #3, #4)
  - ✅ empty stub body (tests #13, #14)
  - N/A bare-int source_id (covered by PR #35 regression already on file)
  - N/A colon-in-title (covered by PR #34 regression; PR #35 re-review retained the assertion)
- End-to-end coverage via `_yaml_roundtrip_then_validate`: 14 of 23 named tests run Step 5 stub → YAML parse → Step 6 telemetry inject → `SilverDocument.model_validate`. Any cross-field validator regression fires here.
- Axis 3 tests use three distinct patterns: isolation (fresh conn called), fault-tolerance (no re-raise when fresh-conn fails), end-to-end (dead main conn → fresh still records).

Confirmed by running the trifecta:

```
$ python3 -m pytest tests/test_step5_opus.py \
    tests/test_step5_stub_schema_conformance_audit.py \
    tests/test_step6_finalize.py
107 passed, 2 skipped in 0.61s
```

### 4. ✅ Axis 5 prompt-template edits

**User prompt (`step5_opus_user.txt`):** `signal_id: {signal_id}` placed at the TOP of the `## Signal triage output` section, column-aligned with `primary_matter`, `matter purpose`, etc. Not buried, not ambiguous. Renders Opus the DB-authoritative value before any other field.

**System prompt (`step5_opus_system.txt`):** New `### Frontmatter cross-field invariants (these cause Step 6 to reject the draft)` section placed directly after "Optional frontmatter keys". Four bullets:
1. Null primary ⇒ empty related (§4.2 explicit)
2. Primary not in related ("OTHER matters" clarification)
3. Title shape (≤160, non-empty, no trailing period)
4. source_id as STRING ("wrap it in quotes — Pydantic rejects unquoted integers")

Phrasing is imperative, names the failure mode up front, unambiguous. Bullet 4 explicitly references Pydantic behavior so Opus can reason about *why* the constraint exists.

Wiring verified at `_build_user_prompt` line 785: `signal_id=inputs.signal_id` passed to `.format()`. Test #19 (`test_build_user_prompt_renders_signal_id_without_keyerror`) guards against accidental removal.

### 5. ✅ Full-repo regression delta — reproduced exactly

Reproduced both runs locally:

```
Baseline b73fb49 (dispatch commit):
  22 failed, 719 passed, 21 skipped, 6 warnings, 12 errors in 13.87s

PR head 9703745:
  22 failed, 748 passed, 21 skipped, 6 warnings, 12 errors in 14.17s
```

**Delta: +29 passed, 0 new failures, 0 new errors, 0 net skips.** Matches B1's claim exactly.

Pre-existing failure/error SET identical — verified by:

```
$ cmp -s /tmp/baseline_fails.txt /tmp/pr36_fails.txt && echo IDENTICAL
IDENTICAL
```

Both runs produce the same 22 `FAILED ` + 12 `ERROR ` test identifiers (44 total lines after grep's multi-line catch), zero drift. All pre-existing failures concentrated in: `test_1m_storeback_verify.py`, `test_clickup_*`, `test_mcp_vault_tools.py`, `test_migration_runner.py`, `test_dashboard_kbl_endpoints.py`, `test_scan_endpoint.py`, `test_scan_prompt.py` — all Python 3.9 `int | None` syntax issues or missing env secrets, confirmed unrelated to the audit surface.

### 6. ✅ No ship-by-inspection

Ship report §10.2 carries the full `pytest` output for both the blast-radius sweep and the full-repo run. §10.1 additionally carries the blast-radius command + output. §10.3 shows `py_compile` syntax-check output. `feedback_no_ship_by_inspection.md` honored.

### 7. ✅ Scope discipline — confined to allowed set

Touched files (9):

```
briefs/_reports/B1_step5_stub_schema_conformance_audit_20260422.md  (new)
briefs/_tasks/CODE_3_PENDING.md                                     (dispatch)
kbl/prompts/step5_opus_system.txt                                   (+7 lines)
kbl/prompts/step5_opus_user.txt                                     (+1 line)
kbl/steps/step5_opus.py                                             (+237 lines)
kbl/steps/step6_finalize.py                                         (+84 lines)
tests/test_step5_opus.py                                            (updated fixture)
tests/test_step5_stub_schema_conformance_audit.py                   (new, 667 lines)
tests/test_step6_finalize.py                                        (added helper)
```

Every file is in the allowed set. **Zero changes to:** `kbl/schemas/silver.py` (confirmed unchanged — any schema change would have required a dedicated brief), `kbl/bridge/`, `kbl/pipeline_tick.py`, `kbl/steps/step1_triage.py`, `step2_resolve.py`, `step3_extract.py`, `step4_classify.py`, `step7_commit.py`, `claim_one_signal`. Clean scope.

### 8. ✅ Post-merge recovery SQL — sane, correctly Tier B

```sql
SELECT id, status, stage FROM signal_queue
WHERE status = 'finalize_running' AND final_markdown IS NULL;

UPDATE signal_queue
SET status = 'awaiting_finalize', started_at = NULL
WHERE status = 'finalize_running' AND final_markdown IS NULL;
```

- Pre-flight SELECT gives the Director a count before the UPDATE — good practice for deviating Tier B.
- `stage` column existence confirmed via `memory/store_back.py:6217` bootstrap (`stage TEXT`).
- WHERE clause is precise: only targets rows stranded at `finalize_running` WITH `final_markdown IS NULL` — won't touch rows that actually completed.
- Sets `started_at = NULL` so the retry pickup logic runs cleanly.
- Correctly flagged Tier B (deviates from the standing Tier A recovery pattern which targets `opus_failed`/`finalize_failed`).

Not gating the APPROVE per dispatch §8.

## Non-blocking N-nits (parked, both pre-existing)

- **N1**: `error_count` parameter of `_route_validation_failure` is unreferenced in the function body. Was also unused in the pre-fix version. Preserved by B1 for call-site signature compatibility. Clean-up candidate for a later unification brief.
- **N2**: `needed = _STUB_BODY_MIN_CHARS - len(body)` in `_pad_stub_body` is computed and then `del needed`'d — leftover from an earlier implementation. Cosmetic.

## Path forward

Tier A auto-merge proceeds. Post-merge recovery SQL → Tier B, AI Head authorizes with Director separately per §8. Render auto-deploy ≤3 min; then one pipeline_tick cycle (~120 s); then verify:
- `signal_queue` rows advance through `awaiting_commit`;
- Zero new `kbl_log` ERROR rows matching `component='finalize' AND message LIKE '%connection already closed%'`;
- `finalize_retry_count` shows natural 0/1/2 distribution — none stuck at 0 in a terminal-failed state.

Gate 1 closes on ≥5-10 signals reaching `awaiting_commit` cleanly. This PR should kill the whole class.

— B3
