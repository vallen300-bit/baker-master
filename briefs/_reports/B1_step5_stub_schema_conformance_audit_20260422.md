# B1 Ship Report — STEP5_STUB_SCHEMA_CONFORMANCE_AUDIT_1

**From:** Code Brisen #1
**To:** AI Head (cc B3 for review, cc Director for Gate 1)
**Date:** 2026-04-22
**Brief:** `briefs/_tasks/CODE_1_PENDING.md` (dispatch commit `b73fb49`)
**Branch:** `step5-stub-schema-conformance-audit-1`
**Reviewer:** B3
**Effort:** L, inside 4-h timebox
**Unblocks:** Cortex T3 Gate 1 (≥5-10 signals reaching terminal stage cleanly)

---

## 1. Summary

Director called "audit" over "patch" after five PRs (#30-#35) failed to
kill the Step 5 stub → Step 6 Pydantic drift class, and the 6th failure
just surfaced (`§4.2 null primary + non-empty related`). This sweep
goes end-to-end: every `SilverFrontmatter` / `SilverDocument` validator
is now satisfied structurally by both stub writers under every
pathological input I can construct; the error-handler cascade that
strands rows on a dead pipeline conn is fixed; Axis 5 (`signal_id`
placeholder) is in the Opus user prompt; and 29 regression tests lock
the whole thing.

No single-line patch. No "by inspection" claims — full `pytest` run
captured at the end.

## 2. Field conformance matrix (Axis 1)

Per-field alignment between stub writer output and `SilverFrontmatter`
/ `SilverDocument`. **Status** column: ✅ pre-audit compliant,
🔧 producer-side fix in this audit, 🔨 schema-force-set at Step 6.

| Field | Stub writer emits | Schema type | Coerces? | Audit status |
|-------|-------------------|-------------|----------|--------------|
| `title` | str (literal or `triage_summary[:60]`) | `str` (≤160, non-empty, no trailing `.`) | — | 🔧 `_normalize_stub_title` rstrips period/ws, falls back if empty, caps at 160 |
| `voice` | `"silver"` | `Literal["silver"]` | — | ✅ |
| `author` | `"pipeline"` | `Literal["pipeline"]` | — | ✅ |
| `created` | str `YYYY-MM-DDTHH:MM:SSZ` | `datetime` (tz-aware, UTC) | Pydantic v2 parses ISO `Z` suffix → UTC-aware `datetime` | ✅ |
| `source_id` | `str(inputs.signal_id)` | `str` | v2 rejects `int → str` | ✅ (producer cast per PR #35) + 🔨 Step 6 force-set |
| `primary_matter` | `Optional[str]` | `Optional[MatterSlug]` (regex + ACTIVE registry) | — | 🔧 non-active slugs demoted to `None` |
| `related_matters` | `list[str]` | `List[MatterSlug]` | — | 🔧 filtered to ACTIVE set; primary de-duped; forced `[]` when primary is null |
| `vedana` | str | `Literal["threat","opportunity","routine"]` | — | 🔧 invalid coerced to `"routine"` |
| `triage_score` | NOT set by producer | `int` 0-100 (required) | — | 🔨 Step 6 injects from `signal_queue.triage_score` (pre-existing) |
| `triage_confidence` | NOT set by producer | `float` 0-1 (required) | — | 🔨 Step 6 injects from `signal_queue.triage_confidence` (pre-existing) |
| `thread_continues` | NOT set by producer | `List[str]` (wiki/*.md) | default `[]` | ✅ |
| `deadline` | NOT set by producer | `Optional[str]` (YYYY-MM-DD) | default `None` | ✅ |
| `money_mentioned` | NOT set by producer | `List[MoneyMention]` (≤3) | default `[]` | ✅ |
| `status` | `"stub_auto"` | `Optional[Literal["stub_auto","stub_cross_link","stub_inbox"]]` | — | ✅ |

FULL_SYNTHESIS path: whatever Opus emits flows into Step 6's parse →
Pydantic validate → retry ladder. The new system-prompt section
(`§4.2` invariant + title rules + quote `source_id`) plus the new
`{signal_id}` user placeholder give Opus the full contract. Step 6's
`source_id` force-override remains as belt-and-suspenders.

## 3. Invariant matrix (Axis 2) — per-branch satisfaction proof

| Invariant | Source | SKIP_INBOX stub | STUB_ONLY stub | FULL_SYNTHESIS |
|-----------|--------|-----------------|----------------|----------------|
| `_title_shape` (≤160, non-empty, no trailing `.`) | `silver.py:158` | hardcoded 43-char title, no `.` | `_normalize_stub_title` strips `.` + ws, 160 cap, fallback when empty | system prompt §Output format §cross-field invariants + Opus self-check |
| `_created_utc` (tz-aware UTC) | `silver.py:170` | `_iso_utc_now` emits `...Z` | same | Opus renders from `{iso_now}` — stable ISO-8601 Z suffix |
| `_deadline_iso_date` (YYYY-MM-DD) | `silver.py:179` | N/A — not emitted | N/A | Opus prompt §Optional — `YYYY-MM-DD` format explicit |
| `_money_cap` (≤3 entries) | `silver.py:190` | N/A | N/A | Opus prompt §Optional — "up to 3 most material figures" |
| `_thread_continues_paths` (`wiki/*.md`) | `silver.py:197` | N/A | N/A | Opus prompt §Body — paths drawn from `resolved_thread_paths` input which is already `wiki/*.md` shaped |
| `_no_primary_in_related` | `silver.py:213` | `_normalize_stub_inputs` dedupes | same | system prompt §cross-field invariants: "primary not in related" |
| `_null_primary_implies_empty_related` (§4.2) | `silver.py:230` | forces `related=[]` when primary None | same | system prompt §cross-field invariants: "null primary ⇒ related is []" |
| `MatterSlug` regex + ACTIVE membership | `silver.py:50-70` | filters to `active_slugs()` | same | Opus constrained by prompt + live signal input (slugs already flow from Step 1's active-set classifier) |
| `_body_length` 300 ≤ len ≤ 8000 | `silver.py:261` | `_pad_stub_body` floors at 300 | same | system prompt §Hard constraints: 300-800 tokens body |
| `_no_gold_self_promotion` (R18) | `silver.py:270` | filler prose rephrased to not contain `voice: gold` / `author: director` literals | same | system prompt rule F1/F2 prohibits, Opus self-check reinforces |
| `_stub_status_matches_shape` (status set ⇒ body ≤600) | `silver.py:284` | `_cap_stub_body` caps at 600 | same | N/A — FULL_SYNTHESIS never sets `status` |
| Provenance gate (`status` set iff stub decision) | `step6_finalize.py:542` | always `stub_auto` | always `stub_auto` | Opus never emits `status`; enforced by `_assert_status_provenance` |
| `voice: Literal["silver"]` (Inv 8) | `silver.py:136` | hardcoded `"silver"` | same | Opus prompt F1 + structural reject at validate |
| `author: Literal["pipeline"]` (Inv 4) | `silver.py:137` | hardcoded `"pipeline"` | same | Opus prompt F2 + structural reject at validate |

## 4. Error-handler robustness fix (Axis 3)

**Pre-audit cascade:**

1. Step 5 FULL_SYNTHESIS holds the pipeline conn idle for 10-30 s per
   Opus round-trip while the R3 ladder runs.
2. Neon's server-side pooler occasionally silently resets long-idle
   SSL connections. On the return trip, psycopg2 raises
   `OperationalError: SSL connection has been closed unexpectedly`.
3. Step 6's `_fetch_signal_row` + `_mark_running` run on the now-dead
   conn; *sometimes* they catch the SSL teardown on first use, more
   often the kernel-level reset surfaces only on the next write.
4. Pydantic validation fails → `_route_validation_failure(conn, ...)`
   is called.
5. `_increment_retry_count(conn, ...)` raises
   `InterfaceError: connection already closed`.
6. The outer `except Exception: raise` in `pipeline_tick` propagates,
   but the row's state was never flipped — **stranded at
   `finalize_running` silently.** Recovery requires manual UPDATE.

**Post-audit:**

`_route_validation_failure` now opens a **fresh short-lived connection
via `kbl.db.get_conn()`** and routes the retry-bump UPDATE + terminal
state flip + commit through that connection. Whatever happened to the
outer pipeline conn — SSL reset, poisoned `INFAILEDSQLTRANSACTION`,
Neon pool evict — the fresh conn is clean.

Fault-tolerant envelope wraps the fresh-conn block so if the fresh
connection ALSO fails (DB entirely down), the error handler logs to
stderr and returns — the caller's re-raise of `ValidationError`
/ `FinalizationError` is never masked by a second exception.

Call sites updated (lines 612/635/642/663 of `step6_finalize.py`):
signature `_route_validation_failure(conn, row, error_count=...)` →
`_route_validation_failure(row, error_count=...)`.

**Regression gates:** `test_step5_stub_schema_conformance_audit.py::
test_route_validation_failure_uses_fresh_conn_for_state_writes`,
`test_route_validation_failure_swallows_fresh_conn_exception`,
`test_finalize_with_dead_primary_conn_still_records_failure_on_fresh_conn`.

## 5. Opus prompt surfacing (Axis 5)

### 5.1 User prompt — `signal_id` placeholder

`kbl/prompts/step5_opus_user.txt` gained one line:

```
signal_id:       {signal_id}
```

Wired into `_build_user_prompt` (`step5_opus.py:~600`):

```python
return template.format(
    signal_id=inputs.signal_id,
    ...
)
```

Pre-audit the template had no `{signal_id}` placeholder and Opus had
to guess the source_id from context; Step 6's override was the only
guard. Belt-and-suspenders stays.

### 5.2 System prompt — §4.2 + title + source_id explicit

Added a new block after §Frontmatter optional keys:

```markdown
### Frontmatter cross-field invariants (these cause Step 6 to reject the draft)

- **Null primary ⇒ empty related.** If `primary_matter` is `null`,
  `related_matters` MUST be `[]`. A null-matter signal cannot carry
  cross-links (Step 6 §4.2 invariant).
- **Primary not in related.** `related_matters` MUST NOT contain
  `primary_matter`. ...
- **Title shape.** `title` must be ≤160 chars, non-empty after
  whitespace trim, and MUST NOT end with a period.
- **source_id is the signal_id value.** Emit the `signal_id` from
  the input block verbatim as a STRING (wrap it in quotes — Pydantic
  rejects unquoted integers). ...
```

The Opus self-check at the bottom of the system prompt already lists
"9 required keys present, `voice: silver`, `author: pipeline`" — the
new block slots in as the cross-field companion.

## 6. Test coverage matrix (Axis 4)

| # | Test | Field / Invariant | Expected |
|---|------|-------------------|----------|
| 1 | `test_skip_inbox_stub_validates_with_primary_slug_and_empty_related` | happy: primary + related=[] | validates |
| 2 | `test_stub_only_stub_validates_with_primary_slug_and_empty_related` | happy | validates |
| 3 | `test_stub_with_null_primary_forces_empty_related_skip_inbox` | §4.2 + skip_inbox | related forced [] |
| 4 | `test_stub_with_null_primary_forces_empty_related_stub_only` | §4.2 + stub_only | related forced [] |
| 5 | `test_stub_dedupes_primary_out_of_related` | no-primary-in-related | dedup |
| 6 | `test_stub_filters_retired_related_slug_through_registry` | slug registry | retired dropped |
| 7 | `test_stub_demotes_retired_primary_to_null_which_empties_related` | slug registry + §4.2 cascade | primary→None, related=[] |
| 8 | `test_stub_only_title_strips_trailing_period` | `_title_shape` trailing `.` | stripped |
| 9 | `test_stub_only_title_falls_back_when_summary_is_punctuation_only` | `_title_shape` empty | fallback used |
| 10 | `test_normalize_stub_title_caps_at_160_chars` | `_title_shape` 160 cap | capped |
| 11 | `test_stub_coerces_invalid_vedana_to_routine` (5 bad values) | vedana Literal | "routine" |
| 12 | `test_stub_preserves_valid_vedana` (3 valid values) | vedana Literal | preserved |
| 13 | `test_skip_inbox_stub_body_meets_300_char_floor` | `_body_length` min | ≥300 |
| 14 | `test_stub_only_stub_body_meets_300_char_floor_even_with_empty_triage` | `_body_length` min | ≥300 |
| 15 | `test_stub_body_stays_under_600_char_ceiling` | `_stub_status_matches_shape` | ≤600 |
| 16 | `test_stub_bodies_never_emit_forbidden_gold_self_promotion_markers` | R18 body markers | no literals |
| 17 | `test_normalize_stub_inputs_returns_three_tuple` | helper unit | shape |
| 18 | `test_opus_user_prompt_template_contains_signal_id_placeholder` | Axis 5 template | placeholder exists |
| 19 | `test_build_user_prompt_renders_signal_id_without_keyerror` | Axis 5 wiring | no KeyError |
| 20 | `test_opus_system_prompt_names_null_primary_implies_empty_related_invariant` | Axis 5 system prompt | §4.2 surfaced |
| 21 | `test_route_validation_failure_uses_fresh_conn_for_state_writes` | Axis 3 | writes on fresh conn |
| 22 | `test_route_validation_failure_swallows_fresh_conn_exception` | Axis 3 fault-tolerance | no re-raise |
| 23 | `test_finalize_with_dead_primary_conn_still_records_failure_on_fresh_conn` | Axis 3 E2E | fresh commits |

29 test cases total (parametrized `vedana` adds 8 sub-cases).

## 7. Files changed

| File | Change |
|------|--------|
| `kbl/steps/step5_opus.py` | New helpers `_normalize_stub_inputs`, `_normalize_stub_title`, `_pad_stub_body`, `_cap_stub_body`. Constants `_STUB_BODY_MIN_CHARS=300`, `_STUB_BODY_MAX_CHARS=600`, `_VALID_VEDANA`. Stub builders rewritten to go through normalization. Stub body filler prose added (phrased to avoid R18 forbidden markers). `_build_user_prompt` now passes `signal_id` to `.format()`. |
| `kbl/steps/step6_finalize.py` | Added `import sys`, `from kbl.db import get_conn`. `_route_validation_failure` rewritten: drops `conn` parameter, opens fresh conn via `get_conn()`, fault-tolerant stderr envelope. All 4 call sites in `finalize()` updated. |
| `kbl/prompts/step5_opus_user.txt` | One new line: `signal_id:       {signal_id}`. |
| `kbl/prompts/step5_opus_system.txt` | New section: "Frontmatter cross-field invariants" with §4.2 + no-primary-in-related + title shape + source_id string rule. |
| `tests/test_step5_opus.py` | `test_stub_only_stub_frontmatter_survives_pathological_triage_summary` updated: related now filtered through ACTIVE registry (old assertion was testing a schema-violating shape). |
| `tests/test_step6_finalize.py` | Added `_patch_get_conn_to(conn)` helper + 4 call-site updates to route fresh-conn writes back to the same tracking mock. |
| `tests/test_step5_stub_schema_conformance_audit.py` | **NEW** — 29 regression tests (matrix §6). |

## 8. Not changed

- `kbl/pipeline_tick.py` — transaction boundary contract untouched; the
  long-Opus-call-kills-conn pattern still exists but Axis 3 now handles
  it gracefully. The **better** fix is to break Step 5 + Step 6 onto
  separate connections (so Neon idle reap on the Step 5 conn never
  reaches Step 6), but that's a larger tx-contract refactor —
  out of scope here. Flagged for a follow-up brief.
- `kbl/schemas/silver.py` — no schema changes. All existing
  invariants stay; stubs now comply with them instead of drifting.
- Bridge, step 1-4, step 7 — untouched.
- Claim transactionality / stranding fix — separate brief queued
  post-Gate-1 per original scope line.

## 9. Deviations from brief

1. **Filler prose scrubbed of forbidden literals.** First draft of the
   stub filler included the phrases `` `voice: gold` `` + `` `author:
   director` `` as Director-facing instructions — which are precisely
   the R18 forbidden body markers (`SilverDocument._no_gold_self_promotion`).
   Test run exposed this; rephrased to describe the promotion action
   without quoting the literals.
2. **Test-harness patch.** Existing Step 6 tests asserted on
   `conn.commit.call_count == 1` against the outer mock conn — which
   under the new architecture commits zero times (fresh conn commits
   instead). Rather than rewrite each assertion to track the fresh
   conn, added a helper `_patch_get_conn_to(conn)` that routes
   `get_conn()` back to the same tracking mock. Existing assertions
   continue to hold verbatim; new Axis 3 tests use separate fresh-conn
   mocks to prove isolation.
3. **"Pathological triage summary" test swap.** Old fixture passed
   `related_matters=[_VALID_SLUG, "mo_vie"]` where `mo_vie` is not an
   active slug AND `_VALID_SLUG` was also the primary. Post-audit
   both get filtered out — assertion changed from 2 items (which
   would have failed Pydantic anyway) to the correct 1-item
   deduped+filtered list.

## 10. Pre-merge verification

### 10.1 Blast-radius test sweep

```
$ python3 -m pytest tests/test_step1_triage.py tests/test_step2_resolve.py \
    tests/test_step3_extract.py tests/test_step4_classify.py \
    tests/test_step5_opus.py tests/test_step5_stub_schema_conformance_audit.py \
    tests/test_step6_finalize.py tests/test_silver_schema.py \
    tests/test_bridge_pipeline_integration.py tests/test_pipeline_tick.py \
    tests/test_slug_registry.py -v

======================= 349 passed, 11 skipped in 0.82s ========================
```

11 skipped = live-PG round-trip tests gated on `TEST_DATABASE_URL` +
`NEON_API_KEY` (no credentials in local env). Structurally validated
via collection; will run on CI / live-PG.

### 10.2 Full repo pytest run

```
$ python3 -m pytest --ignore=tests/test_tier_normalization.py
...
====== 22 failed, 748 passed, 21 skipped, 5 warnings, 12 errors in 9.29s =======
```

`test_tier_normalization.py` excluded at collection — import-time
`int | None` Python-3.10 syntax under Python 3.9. Pre-existing and
unrelated to this audit (confirmed by `git stash -u` baseline run on
`b73fb49`: **same 22 failed / 12 errors, 719 passed before; 748
passed after → +29 new passing tests, zero regressions**).

All 22 failures + 12 errors are in:
- `test_1m_storeback_verify.py` — `ModuleNotFoundError` (unrelated)
- `test_clickup_*` — TypeError / Qdrant API drift (unrelated)
- `test_mcp_vault_tools.py` — `ModuleNotFoundError` (unrelated)
- `test_migration_runner.py`, `test_dashboard_kbl_endpoints.py`,
  `test_scan_endpoint.py`, `test_scan_prompt.py` — Python 3.9 `int |
  None` incompat (unrelated)

Full output archived at `/tmp/audit_full_pytest.txt` +
`/tmp/audit_blast_pytest.txt` on Mac Mini — attach on request.

### 10.3 Syntax check

```
$ python3 -c "import py_compile; \
    py_compile.compile('kbl/steps/step5_opus.py', doraise=True); \
    py_compile.compile('kbl/steps/step6_finalize.py', doraise=True); \
    print('OK')"
OK
```

## 11. Deploy + verification (post-merge)

1. AI Head merges baker-master PR on B3 APPROVE (Tier A auto-merge).
2. Render auto-deploys (~3 min).
3. Recovery UPDATE pending Director auth (separate brief — the
   currently-stranded rows at `finalize_running` need a state reset
   before they'll get another pass):

   ```sql
   -- pre-flight (expect N>0)
   SELECT id, status, stage FROM signal_queue
   WHERE status = 'finalize_running' AND final_markdown IS NULL;

   -- recovery (Director auth required)
   UPDATE signal_queue
   SET status = 'awaiting_finalize',
       started_at = NULL
   WHERE status = 'finalize_running' AND final_markdown IS NULL;
   ```

4. Wait one `kbl_pipeline_tick` cycle (~120 s).
5. Verify:
   - `signal_queue` rows advancing through `awaiting_commit`.
   - `kbl_log` has ZERO new ERROR rows with `component='finalize'`
     and `message LIKE '%connection already closed%'`.
   - `signal_queue.finalize_retry_count` shows natural retry counts
     (0/1/2) — none stuck at 0 with status in a terminal-failed
     state.

Gate 1 closes when ≥5-10 signals reach `awaiting_commit` without
Pydantic validation drift.

## 12. Paper trail

- Commit: see `git log -1` on `step5-stub-schema-conformance-audit-1`.
- Baker decision to be logged via `mcp__baker__baker_store_decision`
  post-deploy sanity.
- Feedback memory ratified on 2026-04-21 (full `pytest` output
  required in ship reports) — honored via §10.2.

— B1
