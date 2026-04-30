# B4 Ship Report — CORTEX_BOOTSTRAP_MATTER_1

**Brief:** `briefs/BRIEF_CORTEX_BOOTSTRAP_MATTER_1.md`
**Branch:** `feature/cortex-bootstrap-matter-1`
**Builder:** B4 (Code Brisen #4)
**Tier:** A (AI Head A merges on green)
**Status:** READY FOR REVIEW — pytest 41/41 green, all 8 verification criteria met.
**Date:** 2026-04-30

## Summary

Built generic matter scaffolding generator generalising
`scripts/bootstrap_hagenauer_wiki.py` to any matter slug. Two scripts:

1. **`scripts/bootstrap_matter.py`** — reads input YAML at
   `briefs/_inputs/bootstrap_<slug>.yml`, emits 7 .md files +
   `curated/.gitkeep` under
   `vault_scaffolding/live_mirror/v1/matters/<slug>/`. Frontmatter on
   every emitted .md is VAULT.md §2-compliant and validates via
   `kbl.ingest_endpoint.validate_frontmatter`. `cortex-config.md`
   carries both VAULT §2 keys (so validate passes) AND the
   Cortex-specific schema (`matter_slug`, `autonomy_level`,
   `sense_sources`, `trigger_patterns`, `default_specialists`,
   `auto_trigger`, `counterparty_iteration_horizon`, …) consumed
   by `triggers/cortex_pre_review_gate`.

2. **`scripts/bootstrap_entities.py`** — reads
   `briefs/_inputs/bootstrap_entities_<batch>.yml`, validates each
   row (slug uniqueness vs canonical+aliases in current `entities.yml`,
   intra-batch dedup, status enum, description ≥10 chars), stages
   timestamped append-batch under
   `vault_scaffolding/live_mirror/v1/entities.yml.append-batch-<label>-<ts>.yml`.
   Bumps `version` + carries Mac Mini merge instructions.

Both scripts: idempotent (default fail-on-collision; `--force` for matter
overwrite), `--dry-run` flag, CHANDA #9 stage-only (no direct
`baker-vault/` writes).

Test fixture: `briefs/_inputs/bootstrap_capital_call.yml` populated
from V8 Q29 Director ratification (2026-04-30) — first real consumer
matter (EUR 7M call to AO via Aelio, phased Apr/May/Jun
2.5M/2.5M/2M).

## Files created

```
briefs/_inputs/.gitkeep
briefs/_inputs/bootstrap_capital_call.yml
scripts/bootstrap_matter.py
scripts/bootstrap_entities.py
tests/test_bootstrap_matter.py
tests/test_bootstrap_entities.py
briefs/_reports/B4_cortex_bootstrap_matter_1_20260430.md  (this file)
```

## Verification criteria — all 8 met

### 1. Dry-run lists ≥7 files; emits 0

```
$ .venv-b3/bin/python scripts/bootstrap_matter.py --dry-run \
    --input briefs/_inputs/bootstrap_capital_call.yml \
    --vault-root /Users/dimitry/baker-vault \
    --out-root /tmp/cc_dryrun

[DRY-RUN] Would emit 8 files under /tmp/cc_dryrun:
  - cortex-config.md
  - _overview.md
  - _index.md
  - agenda.md
  - state.md
  - gold.md
  - proposed-gold.md
  - curated/.gitkeep
```

8 ≥ 7 ✅. Listing matches the brief schema (7 .md + curated/.gitkeep).
Filesystem confirms zero files written:

```
$ ls /tmp/cc_dryrun
ls: /tmp/cc_dryrun: No such file or directory
```

### 2. Real run emits exactly 7 .md + curated/.gitkeep

```
$ .venv-b3/bin/python scripts/bootstrap_matter.py \
    --input briefs/_inputs/bootstrap_capital_call.yml \
    --vault-root /Users/dimitry/baker-vault \
    --out-root /tmp/cc_realrun --today 2026-04-30
[OK] Emitted 8 skeleton files under /tmp/cc_realrun

$ find /tmp/cc_realrun -type f | sort
/tmp/cc_realrun/_index.md
/tmp/cc_realrun/_overview.md
/tmp/cc_realrun/agenda.md
/tmp/cc_realrun/cortex-config.md
/tmp/cc_realrun/curated/.gitkeep
/tmp/cc_realrun/gold.md
/tmp/cc_realrun/proposed-gold.md
/tmp/cc_realrun/state.md
```

### 3. Re-running without `--force` fails

Covered by `test_default_overwrite_fails` (asserts SystemExit code 1
with the explicit "Pass --force to overwrite" stderr message).

### 4. Every emitted .md frontmatter passes `validate_frontmatter`

Covered by `test_emitted_frontmatter_passes_kbl_validation` (in-process
loop calls `validate_frontmatter` on each of 7 files). Spot-check on
the capital-call output:

```
OK  _index.md          type=matter  slug=capital-call
OK  _overview.md       type=matter  slug=capital-call-overview
OK  agenda.md          type=matter  slug=capital-call-agenda
OK  cortex-config.md   type=matter  slug=capital-call
OK  gold.md            type=matter  slug=capital-call-gold
OK  proposed-gold.md   type=matter  slug=capital-call-proposed-gold
OK  state.md           type=matter  slug=capital-call-state
```

### 5. Negative input cases (≥5)

`test_bootstrap_matter.py` carries 10 negative cases:

- `test_validate_input_rejects_missing_required_field`
- `test_validate_input_rejects_non_kebab_slug`
- `test_validate_input_rejects_invalid_regex`
- `test_validate_input_rejects_bad_autonomy_enum`
- `test_validate_input_rejects_bad_horizon_enum`
- `test_validate_input_rejects_empty_primary_entities`
- `test_validate_input_rejects_empty_trigger_patterns`
- `test_validate_input_rejects_bad_ratified_date`
- `test_validate_input_rejects_bad_entity_slug`
- `test_validate_input_rejects_collision_with_existing_vault_dir`

### 6. `bootstrap_entities.py` end-to-end

- Stage with version bump:
  `test_real_run_stages_batch_with_version_bump` (asserts `version: 6`
  after a v=5 vault, batch filename pattern, Mac Mini merge header).
- Refuses duplicates:
  `test_rejects_duplicate_slug_against_canonical`,
  `test_rejects_duplicate_slug_against_alias`,
  `test_rejects_intra_batch_duplicate`,
  `test_rejects_alias_collision_with_existing_canonical`.
- Idempotency-after-merge:
  `test_idempotency_re_run_after_merge_fails` simulates the Mac
  Mini merge by rebuilding the vault with the new entity present, then
  re-runs the same batch input → fails with `already in entities.yml`.

### 7. `capital-call` fixture present

`briefs/_inputs/bootstrap_capital_call.yml` populated from V8 Q29
ratification 2026-04-30. Carries entities (primary: brisen-capital-sa;
counterparties: andrey-oskolkov + aelio-holding-ltd; adjacent:
oskolkov + hagenauer-rg7 + movie), 5 trigger regex patterns, full
phasing breakdown in `notes`, project-structure markdown, counterparty
topology table.

### 8. Total test count ≥20

**41 tests total**, all green:

- `tests/test_bootstrap_matter.py`: 26 tests
- `tests/test_bootstrap_entities.py`: 15 tests

41 ≥ 20 ✅.

## Literal pytest output

```
$ .venv-b3/bin/python -m pytest tests/test_bootstrap_matter.py tests/test_bootstrap_entities.py -v

============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0 -- /Users/dimitry/bm-b4/.venv-b3/bin/python
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b4
plugins: langsmith-0.7.33, asyncio-1.3.0, anyio-4.13.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 41 items

tests/test_bootstrap_matter.py::test_apply_defaults_fills_missing_fields PASSED [  2%]
tests/test_bootstrap_matter.py::test_apply_defaults_input_wins_on_collision PASSED [  4%]
tests/test_bootstrap_matter.py::test_validate_input_accepts_minimal_valid_config PASSED [  7%]
tests/test_bootstrap_matter.py::test_validate_input_rejects_missing_required_field PASSED [  9%]
tests/test_bootstrap_matter.py::test_validate_input_rejects_non_kebab_slug PASSED [ 12%]
tests/test_bootstrap_matter.py::test_validate_input_rejects_invalid_regex PASSED [ 14%]
tests/test_bootstrap_matter.py::test_validate_input_rejects_bad_autonomy_enum PASSED [ 17%]
tests/test_bootstrap_matter.py::test_validate_input_rejects_bad_horizon_enum PASSED [ 19%]
tests/test_bootstrap_matter.py::test_validate_input_rejects_empty_primary_entities PASSED [ 21%]
tests/test_bootstrap_matter.py::test_validate_input_rejects_empty_trigger_patterns PASSED [ 24%]
tests/test_bootstrap_matter.py::test_validate_input_rejects_bad_ratified_date PASSED [ 26%]
tests/test_bootstrap_matter.py::test_validate_input_rejects_bad_entity_slug PASSED [ 29%]
tests/test_bootstrap_matter.py::test_validate_input_rejects_collision_with_existing_vault_dir PASSED [ 31%]
tests/test_bootstrap_matter.py::test_emitted_frontmatter_passes_kbl_validation PASSED [ 34%]
tests/test_bootstrap_matter.py::test_emit_creates_curated_gitkeep PASSED [ 36%]
tests/test_bootstrap_matter.py::test_emit_marks_director_content_on_appropriate_files PASSED [ 39%]
tests/test_bootstrap_matter.py::test_cortex_config_carries_cortex_schema_keys PASSED [ 41%]
tests/test_bootstrap_matter.py::test_dry_run_emits_zero_files PASSED     [ 43%]
tests/test_bootstrap_matter.py::test_default_overwrite_fails PASSED      [ 46%]
tests/test_bootstrap_matter.py::test_force_overwrite_succeeds_and_restamps PASSED [ 48%]
tests/test_bootstrap_matter.py::test_input_with_missing_required_field_returns_2 PASSED [ 51%]
tests/test_bootstrap_matter.py::test_nonexistent_input_file_returns_2 PASSED [ 53%]
tests/test_bootstrap_matter.py::test_capital_call_fixture_dry_run PASSED [ 56%]
tests/test_bootstrap_matter.py::test_capital_call_fixture_emits_full_skeleton PASSED [ 58%]
tests/test_bootstrap_matter.py::test_no_baker_vault_writes_in_script_text PASSED [ 60%]
tests/test_bootstrap_matter.py::test_script_runs_end_to_end_via_subprocess PASSED [ 63%]
tests/test_bootstrap_entities.py::test_dry_run_validates_and_prints_intent PASSED [ 65%]
tests/test_bootstrap_entities.py::test_real_run_stages_batch_with_version_bump PASSED [ 68%]
tests/test_bootstrap_entities.py::test_dry_run_bypasses_out_root_existence PASSED [ 70%]
tests/test_bootstrap_entities.py::test_rejects_duplicate_slug_against_canonical PASSED [ 73%]
tests/test_bootstrap_entities.py::test_rejects_duplicate_slug_against_alias PASSED [ 75%]
tests/test_bootstrap_entities.py::test_rejects_intra_batch_duplicate PASSED [ 78%]
tests/test_bootstrap_entities.py::test_rejects_bad_status_enum PASSED    [ 80%]
tests/test_bootstrap_entities.py::test_rejects_short_description PASSED  [ 82%]
tests/test_bootstrap_entities.py::test_rejects_non_kebab_slug PASSED     [ 85%]
tests/test_bootstrap_entities.py::test_rejects_alias_collision_with_existing_canonical PASSED [ 87%]
tests/test_bootstrap_entities.py::test_rejects_missing_input PASSED      [ 90%]
tests/test_bootstrap_entities.py::test_rejects_empty_batch PASSED        [ 92%]
tests/test_bootstrap_entities.py::test_rejects_missing_entities_yml PASSED [ 95%]
tests/test_bootstrap_entities.py::test_idempotency_re_run_after_merge_fails PASSED [ 97%]
tests/test_bootstrap_entities.py::test_no_db_or_vault_writes_in_script_text PASSED [100%]

============================== 41 passed in 0.14s ==============================
```

Precedent suite (`tests/test_bootstrap_hagenauer_wiki.py`, 10/10) re-run
clean — no regression.

## No DB writes — DDL drift check

```
$ grep -nE "INSERT|UPDATE|DELETE|conn\.|cursor\.|execute\(" \
    scripts/bootstrap_matter.py scripts/bootstrap_entities.py
$ echo "GREP_EXIT=$?"
GREP_EXIT=1
```

Zero matches. Both scripts are pure file emitters (read input YAML +
`yaml.safe_dump` → file) — no Postgres, no Qdrant, no API calls.

## Singleton + import smoke

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.

$ .venv-b3/bin/python -c "import scripts.bootstrap_matter, scripts.bootstrap_entities; print('imports OK')"
imports OK
```

## Diff summary — staged `capital-call/`

After `python scripts/bootstrap_matter.py --input briefs/_inputs/bootstrap_capital_call.yml --out-root /tmp/cc_realrun --today 2026-04-30`:

| File | Bytes | Notes |
|---|---|---|
| `cortex-config.md` | 3607 | VAULT §2 + Cortex schema + body sections from input |
| `_overview.md`     |  415 | scaffold w/ Core entities + Scope notes + NEEDS marker |
| `_index.md`        |  810 | TOC pointing at all 7 files + curated/ |
| `agenda.md`        |  358 | scaffold w/ Active items + Parked/dormant + NEEDS marker |
| `state.md`         |  353 | scaffold (Cortex live-state file per architecture §2.1) |
| `gold.md`          |  326 | scaffold (`voice: gold`, Director-only section) |
| `proposed-gold.md` |  467 | scaffold (`voice: gold`, Director Gold + Proposed split) |
| `curated/.gitkeep` |    0 | placeholder for Phase-2 specialist outputs |

`cortex-config.md` carries the full Cortex schema verbatim from input
(matter_slug, autonomy_level, sense_sources, entities, trigger_patterns,
default_specialists, specialist caps, auto_trigger thresholds,
games_relevant flag, counterparty_iteration_horizon, reputation_stake,
observed_strategy, state/gold/curated pointers) — re-readable by
`triggers/cortex_pre_review_gate._read_cost_estimate` and
`matter_notification_deferred` line-based parsers without modification.

## Architectural ambiguity — V2 follow-up?

**Brief flagged:** "script generates `cortex-config.md` body sections
from input free-text markdown blocks. Director may want a stricter
schema (e.g., counterparty topology as structured YAML rendered to a
table) in V2."

**V1 decision:** free-text passthrough for `project_structure`,
`counterparty_topology`, `notes`. Each block falls back to
`[NEEDS_DIRECTOR_CONTENT]` if absent from input.

**Test fixture observation (capital-call):**

- `project_structure`: bullet-list markdown — clean, readable, matches
  shape used in `mrci/cortex-config.md`.
- `counterparty_topology`: pipe-separated markdown table — equivalent
  to MRCI's hand-written table. Matched 1:1.
- `notes`: free-form prose with sub-headings. Carries Director-locked
  phasing, game-theoretic frame, bridge-to-other-matters — three
  semantic clusters that MRCI also carries as separate H2 sections in
  body, not frontmatter.

**Verdict:** No divergence in the test fixture. V1 free-text passthrough
is sufficient. **V2 structured-schema NOT required** until a future
matter shows divergence in body shape (most likely candidate: a matter
with multiple counterparty groups requiring per-group iteration-horizon
overrides as YAML, not prose).

Recommendation: keep V1, revisit if a Wave 4+ matter ships and
prefers structured topology rendering.

## Lessons referenced

- `tasks/lessons.md` Lesson #8 ("Compile-clean ≠ done. Exercise the
  actual flow before reporting"): satisfied — every test exercises
  the actual `main(...)` entrypoint with real I/O, not just imports.
  The `capital-call` fixture is also dry-run + real-run end-to-end
  in two separate test cases.
- `feedback_no_ship_by_inspection.md`: literal pytest output captured
  above (not paraphrased) and the dry-run + real-run shell output
  preserved verbatim.

## Out of scope (not done)

- `baker-vault/wiki/matters/capital-call/` → Mac Mini mirrors via
  CHANDA #9 pipeline from staged `vault_scaffolding/live_mirror/v1/`.
- `baker-vault/slugs.yml` slug for `capital-call` matter context →
  already present (action-type slug from version-7 add); the script
  warns if a future matter slug is absent so AI Head A can open the
  separate-repo PR before Mac Mini mirror.
- `briefs/_inputs/bootstrap_entities_<batch>.yml` for capital-call
  entities → not required (all referenced slugs already canonical
  per `_load_known_slugs` lookup).

## Branch + PR readiness

- Branch: `feature/cortex-bootstrap-matter-1`
- 7 files added (5 source + 1 fixture + 1 report); 0 files modified.
- No DB migrations.
- No env vars added.
- No production code paths touched (`outputs/dashboard.py`,
  `triggers/`, `kbl/`, `orchestrator/` all read-only references).

Ready for AI Head A `/security-review` + Tier-A merge.
