# B4 ship report — BRIEF_DOSSIER_ROOM_READ_1 (Rev 3)

- **Brief commit:** 9127e81 (canonical brief body)
- **Dispatch:** cowork-ah1, bus #1387, mailbox CODE_4_PENDING.md frontmatter
  `dispatched_by: cowork-ah1`, `reply_to: cowork-ah1`
- **Branch:** `b4/dossier-room-read`
- **Status:** PR not yet opened — per brief "Do NOT commit/push until AH1 authorizes"
- **Author:** B4

## What shipped

Slug-resolved curated-room pre-read for Baker's dossier engine. Three lifts:

1. **`kbl/curated_wiki_reader.py`** — added `read_room(slug, authoritative=…)`
   that returns a formatted ground-truth digest. Reuses the existing
   containment + char-cap pattern via a new `_read_capped_text` helper.
   Overview-first (`02_inventory/*room-structure-overview.md`); falls back to
   `00_originals/` filename listing (names only, never bodies) + `03_source_summaries/`
   bodies + `curated/*.md`. Expands `touches_siblings:` frontmatter into named
   siblings' curated + summaries, **gated to the slug-family** (first hyphen
   segment) so resolution + sibling-read cannot cross matters. Caps: ≤8 files /
   ≤32K chars / 8K per file; on overflow, appends `[room digest truncated: N
   files omitted]`. Authoritative vs weak header header picked by the caller.

2. **`orchestrator/research_executor.py`** —
   - Added `matter_slug` to `_get_proposal`'s SELECT (Codex C1).
   - Added strict-precedence resolver `_resolve_matter_slug` returning
     `(canonical_slug, path)` where `path ∈ {explicit, alias, grep, none}`.
     - Step 1 (`explicit`): proposal column wins, normalised, authoritative.
     - Step 2 (`alias`): exact canonical OR composite (hyphenated) alias hit
       in subject+context. **Single-token aliases REJECTED** — bare "MOHG"
       never resolves authoritatively (Codex C2 regression).
     - Step 3 (`grep`): one pass over `wiki/matters/*/cortex-config.md`
       frontmatter (≤4KB cap) + `_people.md` only. Never reads room bodies.
       Returns single top-scorer or None (ties fail closed).
     - Step 4: None / authoritative header reserved for steps 1-2.
   - Added `_resolve_and_prepend_room` as the single call-site seam in
     `execute_research_dossier` (between source-text fetch and `_run_specialists`).
   - Runtime kill-flag at call-site: `get_preferences(category='feature_flags',
     pref_key='dossier_room_read_enabled')`. **DB-backed**, not env-var; fail-
     open on flag-check error (default enabled).
   - Structured per-attempt log: `path=… room_found=… slug=… digest_chars=…
     est_tokens=…` (D3 observability + D4 cost metering).

3. **`tests/test_dossier_room_read.py`** — 24 new tests covering both surfaces:
   read_room body order, header gating, sibling family gate, caps, slug
   validation; resolver precedence (explicit > alias > metadata > none);
   generic-token rejection (C2 regression); explicit-column dominance (C1);
   metadata reads frontmatter + _people only (C3); kill-flag enabled/disabled/
   error paths; `_get_proposal` SQL-assertion (Lesson #42 fake-cursor pattern).

## Acceptance criteria verification (v2 — codex-amended)

| AC | Result | Evidence |
|---|---|---|
| 1. py_compile both files | ✅ | Output below |
| 2. /security-review on new path joins | ✅ self-audit; flagged for AH1 mandatory pass | All new joins use `resolve()` → `str().startswith(root + os.sep)` → `.is_file()` (identical to pre-existing `read_curated` pattern). Symlink escape defended at directory AND file level. Regression: existing `test_symlink_escape_rejected` + `test_file_level_symlink_escape_rejected` still pass. |
| 3. C2 collision regression (Bick/MOHG no explicit → NOT mo-vie-am, NOT authoritative) | ✅ | `test_resolver_rejects_generic_single_token_alias_regression` — asserts `(slug, path) != ('mo-vie-am', 'alias')` |
| 4. C1 SELECT includes matter_slug; explicit dominates | ✅ | `test_get_proposal_select_includes_matter_slug` (SQL-string assertion) + `test_resolver_explicit_dominates_context_guess` |
| 5. C3 metadata reads frontmatter + _people only, never bodies | ✅ | `test_resolver_metadata_lookup_reads_only_frontmatter_and_people` (plants body-only sentinel; asserts no resolution) |
| 6. Authoritative header on steps 1-2 only; metadata → weak; unresolved fail closed | ✅ | `test_read_room_authoritative_vs_weak_header` + `test_resolver_metadata_fallback_is_non_authoritative` + `test_resolver_unresolved_fails_closed` |
| 7. Final-prompt budget assert (digest ≤8K tokens ≈ 32K chars) | ✅ | `test_final_prompt_budget_within_cap` + `test_read_room_total_char_cap_enforced` |
| 8. Structured log per path + room_found; digest-size log; runtime kill-flag at call-site (not env) | ✅ | `_resolve_and_prepend_room` emits 4 log paths (killflag-disabled / unresolved / empty-room / injected); kill-flag is `get_preferences('feature_flags','dossier_room_read_enabled')` queried at the call-site; `test_kill_flag_*` cover enable/disable/error |
| 9. Integration: Bick → nvidia-mohg via explicit; no-room regression; slug-family span; error-injection | ✅ | `test_resolver_explicit_dominates_context_guess` + `test_read_room_returns_empty_when_room_missing` + `test_read_room_expands_touches_siblings_within_family` + `test_read_room_ignores_touches_siblings_outside_family` + fault-tolerant wrappers around read_room / kill-flag |
| 10. Deterministic instruction-string assertion (not LLM surface behavior) | ✅ | `ROOM_INSTRUCTION` is a module-level constant; tests assert header constants present, not specialist output |
| 11. Lessons #17/#34/#42/#44/#51 applied | ✅ | #17 (signatures verified inline — `_get_proposal`, `slug_registry.normalize`/`aliases_for`/`canonical_slugs`, `read_curated`); #34/#42 (SQL-assertion fake-cursor for the SELECT change); #44/#51 (call-site + signature greps before coding) |

## Literal pytest output (47 GREEN — new file + regression of sibling file)

```
$ .venv-test/bin/python3 -m pytest tests/test_dossier_room_read.py tests/test_curated_wiki_reader.py -v --tb=short
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b4
collected 47 items

tests/test_dossier_room_read.py::test_read_room_returns_empty_when_room_missing PASSED [  2%]
tests/test_dossier_room_read.py::test_read_room_prefers_overview_when_present PASSED [  4%]
tests/test_dossier_room_read.py::test_read_room_lists_originals_and_reads_summaries_when_no_overview PASSED [  6%]
tests/test_dossier_room_read.py::test_read_room_authoritative_vs_weak_header PASSED [  8%]
tests/test_dossier_room_read.py::test_read_room_expands_touches_siblings_within_family PASSED [ 10%]
tests/test_dossier_room_read.py::test_read_room_ignores_touches_siblings_outside_family PASSED [ 12%]
tests/test_dossier_room_read.py::test_read_room_total_char_cap_enforced PASSED [ 14%]
tests/test_dossier_room_read.py::test_read_room_file_cap_enforced PASSED [ 17%]
tests/test_dossier_room_read.py::test_read_room_invalid_slug_returns_empty PASSED [ 19%]
tests/test_dossier_room_read.py::test_read_room_no_vault_env_returns_empty PASSED [ 21%]
tests/test_dossier_room_read.py::test_resolver_explicit_dominates_context_guess PASSED [ 23%]
tests/test_dossier_room_read.py::test_resolver_explicit_normalises_alias_to_canonical PASSED [ 25%]
tests/test_dossier_room_read.py::test_resolver_rejects_generic_single_token_alias_regression PASSED [ 27%]
tests/test_dossier_room_read.py::test_resolver_accepts_composite_alias_authoritative PASSED [ 29%]
tests/test_dossier_room_read.py::test_resolver_accepts_exact_canonical_authoritative PASSED [ 31%]
tests/test_dossier_room_read.py::test_resolver_metadata_fallback_is_non_authoritative PASSED [ 34%]
tests/test_dossier_room_read.py::test_resolver_metadata_lookup_reads_only_frontmatter_and_people PASSED [ 36%]
tests/test_dossier_room_read.py::test_resolver_unresolved_fails_closed PASSED [ 38%]
tests/test_dossier_room_read.py::test_resolver_explicit_invalid_falls_through_to_alias PASSED [ 40%]
tests/test_dossier_room_read.py::test_get_proposal_select_includes_matter_slug PASSED [ 42%]
tests/test_dossier_room_read.py::test_kill_flag_disabled_skips_room_read PASSED [ 44%]
tests/test_dossier_room_read.py::test_kill_flag_default_enabled_when_pref_missing PASSED [ 46%]
tests/test_dossier_room_read.py::test_kill_flag_fault_tolerant_on_pref_error PASSED [ 48%]
tests/test_dossier_room_read.py::test_final_prompt_budget_within_cap PASSED [ 51%]
tests/test_curated_wiki_reader.py::test_rejects_empty_slug PASSED        [ 53%]
tests/test_curated_wiki_reader.py::test_rejects_path_traversal_slug PASSED [ 55%]
tests/test_curated_wiki_reader.py::test_rejects_slug_with_slash PASSED   [ 57%]
tests/test_curated_wiki_reader.py::test_rejects_uppercase_slug PASSED    [ 59%]
tests/test_curated_wiki_reader.py::test_rejects_unknown_slug PASSED      [ 61%]
tests/test_curated_wiki_reader.py::test_rejects_unsafe_filename PASSED   [ 63%]
tests/test_curated_wiki_reader.py::test_raises_when_vault_env_unset PASSED [ 65%]
tests/test_curated_wiki_reader.py::test_reads_curated_files PASSED       [ 68%]
tests/test_curated_wiki_reader.py::test_missing_files_skipped_not_errored PASSED [ 70%]
tests/test_curated_wiki_reader.py::test_missing_dir_returns_empty PASSED [ 72%]
tests/test_curated_wiki_reader.py::test_char_cap_truncates_with_marker PASSED [ 74%]
tests/test_curated_wiki_reader.py::test_zero_char_cap_disables_truncation PASSED [ 76%]
tests/test_curated_wiki_reader.py::test_frontmatter_without_last_curated_returns_none PASSED [ 78%]
tests/test_curated_wiki_reader.py::test_no_frontmatter_returns_none PASSED [ 80%]
tests/test_curated_wiki_reader.py::test_symlink_escape_rejected PASSED   [ 82%]
tests/test_curated_wiki_reader.py::test_file_level_symlink_escape_rejected PASSED [ 85%]
tests/test_curated_wiki_reader.py::test_rejects_dot_only_filename PASSED [ 87%]
tests/test_curated_wiki_reader.py::test_format_for_prompt_empty_on_no_files PASSED [ 89%]
tests/test_curated_wiki_reader.py::test_format_for_prompt_emits_labels PASSED [ 91%]
tests/test_curated_wiki_reader.py::test_format_for_prompt_swallows_invalid_slug PASSED [ 93%]
tests/test_curated_wiki_reader.py::test_load_curated_wiki_context_iterates_pm_registry_matters PASSED [ 95%]
tests/test_curated_wiki_reader.py::test_load_curated_wiki_context_unknown_pm_returns_empty PASSED [ 97%]
tests/test_curated_wiki_reader.py::test_load_curated_wiki_context_pm_without_curated_config_returns_empty PASSED [100%]

============================== 47 passed in 0.24s ==============================
```

Full repo run: **84 failed, 2403 passed, 106 skipped** — all 84 failures are
PRE-EXISTING (require live PG, MagicMock-pollution from `test_ai_head_weekly_audit`,
or `_archive/02_working/` paths that don't exist). Zero of them are in the
files I changed. Baseline measured against `main`@a237be5.

## Deviations from brief

1. **Bootstrap CREATE TABLE in `orchestrator/research_trigger.py` does NOT
   include `matter_slug`.** Brief Codex C1 finding: prod has the column;
   the only in-repo bootstrap path (`_ensure_research_proposals_table`,
   `research_trigger.py:41`) omits it. I did **not** modify research_trigger.py
   because the brief's `Files Modified` lists exactly two (`kbl/curated_wiki_reader.py`
   + `orchestrator/research_executor.py`). Test path uses fake cursor (no DB
   hit). Production path: works (column exists per Codex verification). Drift
   open as FAST-FOLLOW.

2. **No migration file added** for the same drift. Brief did not request one.

## FAST-FOLLOW (post-merge, non-blocking)

- **AC8 — researcher bus post.** Per brief AC8: bus researcher with commit
  hash + ack request after merge for rubric-integrity follow-up. I will queue
  this after AH1 authorises merge.
- **D5 prod vault confirmation.** Confirm `BAKER_VAULT_PATH` in prod points at
  a LIVE desk-curated copy, not a deploy-time snapshot. `format_for_prompt`
  already runs in prod via `capability_runner` — likely solved; confirm + note.
- **Bootstrap drift close.** Add `matter_slug TEXT` to
  `_ensure_research_proposals_table` CREATE TABLE + idempotent ALTER + new
  migration `migrations/20260530_research_proposals_matter_slug.sql`. Closes
  the in-repo drift Codex flagged.
- **D5-stretch provenance line** ("Curated room consulted: <slug>") in the
  dossier output. Brief defers — currently under Do-Not-Touch.

## Files changed

```
 kbl/curated_wiki_reader.py        | 334 ++++++++++++++++++++++++++++++++++-
 orchestrator/research_executor.py | 356 +++++++++++++++++++++++++++++++++++++-
 tests/test_dossier_room_read.py   | 419 +++++++++++++++++++++++++++++++++++++ (new)
 3 files changed
```

## Awaiting

- AH1 (cowork-ah1) authorisation to commit + push + open PR.
- AH1 decision on /security-review skill pass (AC2). Self-audit clean; pattern
  identical to pre-existing reviewed code.
- AH1 decision on drift-close FAST-FOLLOW (bootstrap + migration in this PR,
  or follow-up brief).
