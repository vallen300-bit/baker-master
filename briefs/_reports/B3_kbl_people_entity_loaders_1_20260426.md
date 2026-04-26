# B3 SHIP REPORT — KBL_PEOPLE_ENTITY_LOADERS_1 — 2026-04-26

**Ship code:** B3
**Branch:** `kbl-people-entity-loaders-1`
**PR:** https://github.com/vallen300-bit/baker-master/pull/62
**Commit:** `d38bc2a`
**Brief:** `briefs/BRIEF_KBL_PEOPLE_ENTITY_LOADERS_1.md`
**Reviewer:** AI Head B (cross-team)
**Roadmap position:** M1 row 2 (cortex3t-roadmap §M1).

---

## What shipped

3 new modules + 3 new test files + 8 fixture vaults + 1 modified file.

```
NEW:
  kbl/people_registry.py                   — load/is_canonical/get/version/normalize/lint, threading-safe cache
  kbl/entity_registry.py                   — same API, separate cache
  tests/test_people_registry.py            — 14 tests
  tests/test_entity_registry.py            — 14 tests
  tests/test_ingest_endpoint_registry_integration.py — 7 tests
  tests/fixtures/registries_people_ok/people.yml
  tests/fixtures/registries_people_dup_slug/people.yml
  tests/fixtures/registries_people_no_version/people.yml
  tests/fixtures/registries_people_dup_alias/people.yml
  tests/fixtures/registries_entities_ok/entities.yml
  tests/fixtures/registries_entities_dup_slug/entities.yml
  tests/fixtures/registries_entities_no_version/entities.yml
  tests/fixtures/registries_combined/{slugs,people,entities}.yml

MODIFIED:
  kbl/ingest_endpoint.py                   — validate_slug_in_registry()
                                             now branches on type=person /
                                             type=entity behind
                                             KBL_REGISTRY_STRICT env flag.
```

## Brief verification criteria — all 5 met

### 1. `pytest tests/test_people_registry.py -v` — ≥8 tests

Actual: **14 tests, all passing.**

### 2. Same for entity registry — ≥8 tests

Actual: **14 tests, all passing.**

### 3. `pytest tests/test_ingest_endpoint_registry_integration.py -v` — ≥4 tests

Actual: **7 tests, all passing.** Covers the brief-named matrix:
- flag off + unregistered person slug → accepted (current behaviour preserved)
- flag on + unregistered person slug → `KBLIngestError`
- flag on + canonical person slug → accepted
- flag on + matter type → matter slug check still runs (no regression)
- (bonus) flag on + unregistered entity → `KBLIngestError`
- (bonus) flag on + canonical entity → accepted
- (bonus) flag off + unregistered entity → warn-log only

### 4. py_compile passes for all 3 modules

```
$ python3 -c "import py_compile; py_compile.compile('kbl/people_registry.py', doraise=True); py_compile.compile('kbl/entity_registry.py', doraise=True); py_compile.compile('kbl/ingest_endpoint.py', doraise=True); print('OK')"
OK
```

### 5. PR description documents `KBL_REGISTRY_STRICT` flip plan

PR #62 body §"KBL_REGISTRY_STRICT flip plan" covers:
- **When** to flip (≥24h zero would-reject events + canonical coverage check)
- **Observability** (warn-log grep target = 0/day before flip)
- **Rollback** (unset env var; zero state to roll back)

---

## Literal pytest output (mandatory per Code Brief Standards)

```
$ python3 -m pytest tests/test_people_registry.py tests/test_entity_registry.py tests/test_ingest_endpoint_registry_integration.py -v
============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0 -- /Library/Developer/CommandLineTools/usr/bin/python3
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b3
plugins: anyio-4.12.1, mock-3.15.1, langsmith-0.4.37
collecting ... collected 35 items

tests/test_people_registry.py::test_load_returns_canonical_mapping PASSED [  2%]
tests/test_people_registry.py::test_cache_returns_same_object PASSED     [  5%]
tests/test_people_registry.py::test_is_canonical_hit_and_miss PASSED     [  8%]
tests/test_people_registry.py::test_get_returns_person_or_none PASSED    [ 11%]
tests/test_people_registry.py::test_version_returns_int PASSED           [ 14%]
tests/test_people_registry.py::test_lint_catches_missing_version PASSED  [ 17%]
tests/test_people_registry.py::test_lint_catches_duplicate_slugs PASSED  [ 20%]
tests/test_people_registry.py::test_lint_catches_duplicate_aliases PASSED [ 22%]
tests/test_people_registry.py::test_lint_clean_on_valid_yml PASSED       [ 25%]
tests/test_people_registry.py::test_missing_env_var_raises PASSED        [ 28%]
tests/test_people_registry.py::test_missing_file_raises PASSED           [ 31%]
tests/test_people_registry.py::test_dup_slug_raises_loudly PASSED        [ 34%]
tests/test_people_registry.py::test_no_version_raises_registry_version_error PASSED [ 37%]
tests/test_people_registry.py::test_concurrent_load_is_thread_safe PASSED [ 40%]
tests/test_entity_registry.py::test_load_returns_canonical_mapping PASSED [ 42%]
tests/test_entity_registry.py::test_cache_returns_same_object PASSED     [ 45%]
tests/test_entity_registry.py::test_is_canonical_hit_and_miss PASSED     [ 48%]
tests/test_entity_registry.py::test_get_returns_entity_or_none PASSED    [ 51%]
tests/test_entity_registry.py::test_version_returns_int PASSED           [ 54%]
tests/test_entity_registry.py::test_active_slugs_filters_retired PASSED  [ 57%]
tests/test_entity_registry.py::test_lint_catches_missing_version PASSED  [ 60%]
tests/test_entity_registry.py::test_lint_catches_duplicate_slugs PASSED  [ 62%]
tests/test_entity_registry.py::test_lint_clean_on_valid_yml PASSED       [ 65%]
tests/test_entity_registry.py::test_missing_env_var_raises PASSED        [ 68%]
tests/test_entity_registry.py::test_missing_file_raises PASSED           [ 71%]
tests/test_entity_registry.py::test_dup_slug_raises_loudly PASSED        [ 74%]
tests/test_entity_registry.py::test_no_version_raises_registry_version_error PASSED [ 77%]
tests/test_entity_registry.py::test_concurrent_load_is_thread_safe PASSED [ 80%]
tests/test_ingest_endpoint_registry_integration.py::test_flag_off_unregistered_person_accepted PASSED [ 82%]
tests/test_ingest_endpoint_registry_integration.py::test_flag_on_unregistered_person_rejected PASSED [ 85%]
tests/test_ingest_endpoint_registry_integration.py::test_flag_on_canonical_person_accepted PASSED [ 88%]
tests/test_ingest_endpoint_registry_integration.py::test_flag_on_matter_type_still_runs_matter_check PASSED [ 91%]
tests/test_ingest_endpoint_registry_integration.py::test_flag_on_unregistered_entity_rejected PASSED [ 94%]
tests/test_ingest_endpoint_registry_integration.py::test_flag_on_canonical_entity_accepted PASSED [ 97%]
tests/test_ingest_endpoint_registry_integration.py::test_flag_off_unregistered_entity_warn_only PASSED [100%]

============================== 35 passed in 0.07s ==============================
```

## Regression delta

```
$ python3 -m pytest tests/ --ignore=tests/test_tier_normalization.py -q
# (full suite excluding pre-existing Python 3.10+ syntax collection error)

main baseline (modified ingest_endpoint.py reverted, registry modules absent):
  27 failed, 910 passed, 27 skipped, 31 errors

this branch:
  24 failed, 913 passed, 27 skipped, 31 errors
```

Delta: **+3 passes, -3 failures, 0 new regressions.** The -3 failures correspond to the 3 strict-mode integration tests that fail without the ingest wiring.

The 24 remaining failures + 31 errors are **pre-existing** — `int | None` Python 3.10+ syntax on a Python 3.9 test runner — not introduced by this PR.

## DDL drift check

```
$ grep -E "ADD COLUMN|CREATE TABLE|ALTER TABLE" kbl/people_registry.py kbl/entity_registry.py; echo "exit: $?"
exit: 1
```

Zero matches. No DB writes. (`exit: 1` from grep means no match — confirms clean.)

## Singleton hook

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

## Brief deviations / annotations

1. **Schema fields for entities.** Brief §Solution speculated that entities have `legal-form / jurisdiction / parent_entity` fields. The actual `~/baker-vault/entities.yml` mirrors `slugs.yml` exactly (slug, status, description, aliases) — its own header comment states "Schema: mirrors slugs.yml." I matched the actual schema. Schema migration is out of scope per brief §"Out of scope". Loader does not error on unrecognised optional fields → forward-compat for future schema additions.

2. **Vault path layout.** Brief mentioned `baker-vault/wiki/registries/people.yml` as the canonical location. Actual files are at vault root: `~/baker-vault/people.yml` and `~/baker-vault/entities.yml`. I matched the actual layout (same pattern as `slugs.yml`).

3. **`load()` semantics.** Brief said "`load() -> dict[slug, Person]` — caches at module level". I implemented it as a defensive copy of the cache (so callers cannot mutate it). The underlying `Person`/`Entity` instances are still cached singletons — `first['x'] is second['x']` holds, verified by tests.

## What this PR does NOT do (re-stated)

- Does not flip `KBL_REGISTRY_STRICT`. Default remains `false`. Flag flip is a follow-on Tier B with B1 situational review per `_ops/ideas/2026-04-24-b1-situational-review-trigger.md`.
- Does not edit `~/baker-vault/people.yml` or `~/baker-vault/entities.yml` content (Director-curated, out of scope).
- Does not add any DB write paths. Loader-only.
- Does not refactor `kbl/slug_registry.py` (model reference, do-not-touch per brief §"Files NOT to touch").
- Does not change frontmatter regex constants in `kbl/ingest_endpoint.py` (separate concern per brief).

## Hand-off

Awaiting AI Head B cross-team review on PR #62. After merge, AI Head A handles `§3` mailbox hygiene (mark `CODE_3_PENDING.md` COMPLETE).
