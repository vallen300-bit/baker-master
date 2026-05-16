---
brief_id: AO_PM_READ_CURATED_WIKI_1
brief: briefs/BRIEF_AO_PM_READ_CURATED_WIKI_1.md
worker: b1
ship_date: 2026-05-16
branch: b1/ao-pm-read-curated-wiki-1
pr: pending — opened in same turn as this report
status: SHIPPED — awaiting AH2 cross-lane + /security-review + AH1 sign-off
tier: B
trigger_class: MEDIUM (capability read-path; /security-review required — slug-input filesystem read)
---

# B1 Ship Report — AO_PM_READ_CURATED_WIKI_1

## What shipped

Option B (recommended in brief): AO-PM context-builder reads curated wiki at runtime and injects it alongside `pm_project_state.state_json`, with an explicit conflict-resolution directive that the curated wiki is authoritative on dated facts.

No schema change. No write-path change. Additive read-path only.

## Files

**New (2):**
- `kbl/curated_wiki_reader.py` (~180 lines) — slug-sanitized + path-resolution-checked reader. Two-gate slug validation: regex `^[a-z0-9-]+$` + `slug_registry.normalize() is not None` (slugs.yml allow-list). Frontmatter `last_curated_at` parsed without PyYAML dep. Char cap default 8K per file (~2K tokens). String-prefix containment check on resolved paths defeats symlink escape.
- `tests/test_curated_wiki_reader.py` (~200 lines, 21 tests) — slug validation, traversal/symlink defenses, frontmatter parse, char-cap, graceful no-op, capability_runner integration via `CapabilityRunner.__new__` (skips anthropic-client construction).

**Modified (1):**
- `orchestrator/capability_runner.py` — added `curated_wiki_matters: [capital-call, oskolkov, hagenauer-rg7, aukera]` to `PM_REGISTRY["ao_pm"]`; new method `_load_curated_wiki_context(pm_slug)` iterates that list via `kbl.curated_wiki_reader.format_for_prompt`; injected into `_build_system_prompt` right after `# LIVE STATE` block, plus a `## CURATED-VS-STATE CONFLICT RULE` directive that tells Opus to prefer curated wiki when state_json disagrees on a dated fact.

## Acceptance criteria — verification

| # | Criterion | Status |
|---|---|---|
| 1 | AO-PM cites `wiki/matters/capital-call/curated/02_money.md` for April tranche question | ✅ smoke test against real baker-vault confirms `RECEIVED 24-28 Apr` reaches the prompt block (see "Smoke test" below); Director-runnable verbal probe deferred to post-deploy per brief Ship gate #5 |
| 2 | MOVIE-AM question pulls fresh wiki content if available; graceful no-op if not | ✅ MOVIE-AM not in scope per brief (Out of scope §1); reader correctly returns `[]` for missing dirs |
| 3 | Conflict case names wiki source + flags state_json as stale | ✅ prompt directive added; tells Opus to cite wiki path + state_json date explicitly |
| 4 | Unit test: mock wiki + state_json, assert wiki appears in prompt | ✅ `test_load_curated_wiki_context_iterates_pm_registry_matters` passes |
| 5 | Integration test (DB-gated): real AO-PM call returns wiki-sourced content | ⚠️ deferred — would require live anthropic call + DB state; AH1 to run as post-merge probe per brief Ship gate #5 (acceptable per brief acceptance #5 wording "Integration test (DB-gated)") |

## Test run (literal pytest output)

Local: Python 3.12.12 via `/opt/homebrew/bin/python3.12` (project deploys on 3.11+; local 3.9 cannot load `conftest.py` due to PEP 604 `int | None` usage in `memory/store_back.py`).

```
$ BAKER_VAULT_PATH=/tmp/empty_for_test python3.12 -m pytest tests/test_curated_wiki_reader.py -v

============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
collected 21 items

tests/test_curated_wiki_reader.py::test_rejects_empty_slug PASSED        [  4%]
tests/test_curated_wiki_reader.py::test_rejects_path_traversal_slug PASSED [  9%]
tests/test_curated_wiki_reader.py::test_rejects_slug_with_slash PASSED   [ 14%]
tests/test_curated_wiki_reader.py::test_rejects_uppercase_slug PASSED    [ 19%]
tests/test_curated_wiki_reader.py::test_rejects_unknown_slug PASSED      [ 23%]
tests/test_curated_wiki_reader.py::test_rejects_unsafe_filename PASSED   [ 28%]
tests/test_curated_wiki_reader.py::test_raises_when_vault_env_unset PASSED [ 33%]
tests/test_curated_wiki_reader.py::test_reads_curated_files PASSED       [ 38%]
tests/test_curated_wiki_reader.py::test_missing_files_skipped_not_errored PASSED [ 42%]
tests/test_curated_wiki_reader.py::test_missing_dir_returns_empty PASSED [ 47%]
tests/test_curated_wiki_reader.py::test_char_cap_truncates_with_marker PASSED [ 52%]
tests/test_curated_wiki_reader.py::test_zero_char_cap_disables_truncation PASSED [ 57%]
tests/test_curated_wiki_reader.py::test_frontmatter_without_last_curated_returns_none PASSED [ 61%]
tests/test_curated_wiki_reader.py::test_no_frontmatter_returns_none PASSED [ 66%]
tests/test_curated_wiki_reader.py::test_symlink_escape_rejected PASSED   [ 71%]
tests/test_curated_wiki_reader.py::test_format_for_prompt_empty_on_no_files PASSED [ 76%]
tests/test_curated_wiki_reader.py::test_format_for_prompt_emits_labels PASSED [ 80%]
tests/test_curated_wiki_reader.py::test_format_for_prompt_swallows_invalid_slug PASSED [ 85%]
tests/test_curated_wiki_reader.py::test_load_curated_wiki_context_iterates_pm_registry_matters PASSED [ 90%]
tests/test_curated_wiki_reader.py::test_load_curated_wiki_context_unknown_pm_returns_empty PASSED [ 95%]
tests/test_curated_wiki_reader.py::test_load_curated_wiki_context_pm_without_curated_config_returns_empty PASSED [100%]

============================== 21 passed in 0.19s ==============================
```

Adjacent suites (no regressions):

```
$ python3.12 -m pytest tests/test_capability_threads.py tests/test_pm_state_write.py tests/test_pm_extraction_robustness.py

================== 21 passed, 1 skipped, 3 warnings in 0.23s ===================
```

(1 skipped = `test_capability_threads_ddl_applied` — DB-gated, skips cleanly without `TEST_DATABASE_URL`.)

## Smoke test — real baker-vault

`BAKER_VAULT_PATH=/Users/dimitry/baker-vault python3.12 -c "from kbl.curated_wiki_reader import format_for_prompt; print(format_for_prompt('capital-call'))"` returns the labelled curated content with `last_curated_at: 2026-05-01-Q4-Q10-cascade` and the literal string `RECEIVED 24-28 Apr 2026`. Acceptance #1 confirmed at the prompt-builder layer.

## Security review hand-off

`/security-review` is REQUIRED before merge per brief §"Ship gate" #3. Specific defenses to verify:

1. **Slug input — regex gate**: `^[a-z0-9-]+$` in `_SLUG_PATTERN`. Tests cover empty / `../` / `/` / uppercase / unknown.
2. **Slug input — allow-list gate**: `slug_registry.normalize(slug) is not None`. Tests cover bogus slugs not in `slugs.yml`.
3. **Filename input — regex gate**: `^[A-Za-z0-9_.-]+\.md$` in `read_curated`. Tests cover `../escape.md`.
4. **Path resolution — containment check**: resolved curated dir must string-prefix-match the resolved `wiki/matters/` root. Test `test_symlink_escape_rejected` confirms a symlinked matter dir pointing outside the vault is rejected.
5. **No write paths added.** Module is read-only.
6. **No new env vars.** Reuses existing `BAKER_VAULT_PATH`.
7. **No DB connections.** Pure filesystem.
8. **Graceful no-op on failure.** `format_for_prompt` swallows `CuratedWikiError` and returns `""` — caller cannot crash on bad slug input from PM_REGISTRY config (defense-in-depth).

## Out of scope (per brief)

- MOVIE-AM curated read-path (follow-up brief once AO-PM proven).
- Cortex Phase 2 sense → 3a re-extraction (RA-23 path, not this tactical bridge).
- Token-budget tuning beyond `~2K tokens per file` default.
- Backfill into state_json (brief explicitly says don't sync wiki → DB).

## Reviewer notes — AH2 cross-lane

Injection point: `orchestrator/capability_runner.py:1133` `_build_system_prompt`, after `# LIVE STATE` block. The conflict-resolution directive is inline with the curated wiki block (not factored to a helper) — kept it that way so the directive travels with the block it governs; happy to factor on request.

PM_REGISTRY: added `curated_wiki_matters` only to `ao_pm`. `movie_am` deliberately unset (brief Out of scope §1). A future MOVIE-AM follow-up brief flips the key on; no other code change needed.

## Branch + commit

- Branch: `b1/ao-pm-read-curated-wiki-1`
- Mailbox claim commit: `2845c0b`
- Implementation commit: pending in same turn as this report
- PR: opened in same turn as this report
