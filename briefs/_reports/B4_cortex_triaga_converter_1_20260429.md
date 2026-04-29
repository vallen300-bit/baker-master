# SHIP REPORT — B4 / CORTEX_TRIAGA_CONVERTER_1

**Date:** 2026-04-29
**Builder:** B4 (`~/bm-b4`)
**Wave:** 1 / Track 5c (V3 rev 4 roadmap; sibling of Track 5b regen — PR #86)
**Branch:** `b4/cortex-triaga-converter-1`
**Spec:** `baker-vault/_ops/processes/cortex-priorities-schema.md` (spec_version: 1, ratified 2026-04-29)
**Source export:** `_01_INBOX_FROM_CLAUDE/2026-04-29-b1-brisen-triage-ratified-export.md` (41-item ratified Triaga)

---

## What shipped

`scripts/triaga_to_priorities.py` — converter that parses a Director-ratified
Triaga export markdown and emits `baker-vault/wiki/_priorities.yml` conforming
to the Track-5b schema. Public entry point per brief:

```python
triaga_export_to_priorities(export_md_path, out_yml_path)
```

Plus optional kwargs (`ratified_at`, `source_inbox`, `archive_copy`,
`combined_slugs_by_ref`, `duplicate_folds`) for test injection + future
ratification rounds.

### Files added

- `scripts/triaga_to_priorities.py` — 410 LOC. Parser → normalizer → schema
  emitter. Exposes `parse_export`, `normalize_slug_field`, `to_priorities_dict`,
  `render_yaml`, `triaga_export_to_priorities`, `main` (CLI).
- `tests/test_triaga_to_priorities.py` — 16 tests covering all brief criteria.
- `scripts/test_data/sample_triaga_export.md` — minimal 5-item fixture
  (3 Active / 1 Completed / 1 Dismissed) covering each section.

### Behavior summary

| Concern | Handling |
|---|---|
| Slug field `[private-assets — slug TBD]` | Strip brackets + `— slug TBD` / `— see note` suffix; emit bare slug |
| Multi-slug `lilienmatt+annaberg+aukera` | Split on `+` / `/` → list, primary first |
| Combined slug Q33 `nvidia + corinthia` | Override → single string `nvidia-corinthia` (Director intent: one origination matter) |
| Duplicate Q19 → Q33 | Dropped from `matters[]` per export's own B1 note |
| Q23 partial-ratification (`CATEGORY: PENDING`) | Emitted as `category: pending`; bumps `provenance.partial_count`; regen passes through (no validation rejection) |
| Active without WHEN/IMPORTANCE/CATEGORY | `ValueError` (malformed-row error path) |
| Unknown WHEN / status / IMPORTANCE | `ValueError` |
| Empty Dismissed/Completed sections | Emitted as explicit `dismissed: []` / `completed: []` for stable diffs |

Module-level constants `COMBINED_SLUGS_BY_REF` + `DUPLICATE_FOLDS` are exposed
so future Triaga rounds can extend without code edits (caller passes overrides
to `triaga_export_to_priorities`).

---

## QC outputs

### §0 — Test suite, literal stdout

```
$ .venv-b3/bin/pytest tests/test_triaga_to_priorities.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0 -- /Users/dimitry/bm-b3/.venv-b3/bin/python3.12
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b4
plugins: langsmith-0.7.33, anyio-4.13.0
collecting ... collected 16 items

tests/test_triaga_to_priorities.py::test_sample_fixture_roundtrip PASSED [  6%]
tests/test_triaga_to_priorities.py::test_zero_dismissed_emits_empty_list PASSED [ 12%]
tests/test_triaga_to_priorities.py::test_multi_slug_plus_separator PASSED [ 18%]
tests/test_triaga_to_priorities.py::test_multi_slug_plus_with_spaces PASSED [ 25%]
tests/test_triaga_to_priorities.py::test_multi_slug_slash_separator PASSED [ 31%]
tests/test_triaga_to_priorities.py::test_q33_nvidia_corinthia_combined_slug PASSED [ 37%]
tests/test_triaga_to_priorities.py::test_combined_slug_override_can_be_disabled PASSED [ 43%]
tests/test_triaga_to_priorities.py::test_q19_folds_into_q33 PASSED       [ 50%]
tests/test_triaga_to_priorities.py::test_dup_fold_can_be_disabled PASSED [ 56%]
tests/test_triaga_to_priorities.py::test_q37_bora_bora_bracket_strips_to_philippe_soulier PASSED [ 62%]
tests/test_triaga_to_priorities.py::test_bracketed_see_note_stripped PASSED [ 68%]
tests/test_triaga_to_priorities.py::test_malformed_missing_meta_line_raises PASSED [ 75%]
tests/test_triaga_to_priorities.py::test_malformed_unknown_status_raises PASSED [ 81%]
tests/test_triaga_to_priorities.py::test_malformed_active_missing_when_raises PASSED [ 87%]
tests/test_triaga_to_priorities.py::test_unknown_when_raises PASSED      [ 93%]
tests/test_triaga_to_priorities.py::test_chain_converter_output_feeds_regen PASSED [100%]

============================== 16 passed in 0.04s ==============================
```

Round-trip soundness is asserted in-suite by `test_chain_converter_output_feeds_regen`:
fixture → converter → `_priorities.yml` → `regen_hot_md(write=False)` →
validation_passed=True + non-empty `hot.md` containing the expected section
markers and matter slugs (no inspection-only claims; literal asserts).

Sibling-suite check (regen tests still green; converter changes did not
regress B3's PR #86 test_regen_hot_md.py):

```
$ .venv-b3/bin/pytest tests/test_triaga_to_priorities.py tests/test_regen_hot_md.py
36 passed in 0.12s
```

### §1 — Real-world dry-run on the 41-item ratified export

Pipeline:

```
$ rm -rf /tmp/b4_dryrun && mkdir -p /tmp/b4_dryrun/vault/wiki
$ cp /Users/dimitry/baker-vault/slugs.yml /tmp/b4_dryrun/vault/slugs.yml
$ .venv-b3/bin/python3 scripts/triaga_to_priorities.py \
      --export "/Users/dimitry/Vallen Dropbox/Dimitry vallen/_01_INBOX_FROM_CLAUDE/2026-04-29-b1-brisen-triage-ratified-export.md" \
      --out /tmp/b4_dryrun/vault/wiki/_priorities.yml -v
OK: wrote /tmp/b4_dryrun/vault/wiki/_priorities.yml \
   (40 items: 30 Active · 5 Completed · 5 Dismissed · 1 Partial)
```

Counts reconcile against the export header (41 ratified · 31 Active ·
5 Completed · 5 Dismissed): 41 → 40 items because Q19 folds into Q33;
31 → 30 Active for the same reason. Q23 lands as the 1 Partial (category:
pending). Completed (Q3, Q4, Q8, Q22, Q24) and Dismissed (Q5, Q28, Q31, Q34,
Q40) match the export's own §Counts block.

Then pipe through B3's regen `--check`:

```
$ .venv-b3/bin/python3 scripts/regen_hot_md.py --vault /tmp/b4_dryrun/vault --check -v
OK: no drift; slug registry validates
EXIT=0
```

And full regen (writes hot.md):

```
$ .venv-b3/bin/python3 scripts/regen_hot_md.py --vault /tmp/b4_dryrun/vault -v
OK: hot.md rewritten (30 matters); slugs.yml mutations: 0; proposed-gold appends: 0
EXIT=0
```

Re-run `--check` after generation → no drift (idempotence holds end-to-end):

```
$ .venv-b3/bin/python3 scripts/regen_hot_md.py --vault /tmp/b4_dryrun/vault --check
OK: no drift; slug registry validates
EXIT=0
```

`hot.md` byte count + tip:

```
$ wc -c /tmp/b4_dryrun/vault/wiki/hot.md
    4388 /tmp/b4_dryrun/vault/wiki/hot.md

$ head -3 /tmp/b4_dryrun/vault/wiki/hot.md
---
title: Current Priorities
voice: gold

$ tail -3 /tmp/b4_dryrun/vault/wiki/hot.md
                                                     # blank line
- MIO »OBSERVER« press digest — always read + communicate to Director.
- Subscription renewal notices — Baker-critical (auto-renewal failure breaks Baker).
```

regen-stderr was empty (exit 0 on both `--check` and write paths).

### §2 — Singleton CI guard

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
EXIT=0
```

### §3 — Compile-clean

```
$ .venv-b3/bin/python3 -c "import py_compile; \
      py_compile.compile('scripts/triaga_to_priorities.py', doraise=True); \
      py_compile.compile('tests/test_triaga_to_priorities.py', doraise=True)"
OK
```

---

## Lane discipline

- ✅ `outputs/dashboard.py` — UNTOUCHED.
- ✅ `orchestrator/cortex_runner.py` — UNTOUCHED.
- ✅ `triggers/` — UNTOUCHED.
- ✅ `kbl/` — UNTOUCHED.
- ✅ `baker-vault/slugs.yml` — UNTOUCHED (separate-repo PR; converter only
  reads, never writes; the regen script handles slug-registry mutations).
- ✅ `scripts/regen_hot_md.py` — UNTOUCHED (Track 5b is B3's PR #86).
- ✅ No new env var.
- ✅ No new dependency (`yaml` already in `requirements.txt`).

---

## Open questions parked for Director (mirrors the export's own follow-up list)

The converter does NOT resolve these — they remain pending until Director
ratifies. Output `_priorities.yml` reflects the export literally:

1. **Q17 + Q18** emit `slug: private-assets` (bracketed-TBD stripped).
   Director's open follow-up #1 may rewrite to `uk-homes` via a
   `slug_changes:` block in the next Triaga round.
2. **Q19 dropped** (folded into Q33 per `DUPLICATE_FOLDS`). Override-able.
3. **Q23 category** = `pending`. Regen accepts; future ratification will
   replace with `financial`.
4. **Q37 slug** = `philippe-soulier` (Bora-Bora context lives in description).
5. **Q39 slug** = `personal` (raw). Note: `slug_changes.ensure-exists:
   personal-admin` lives in Track 5f bootstrap, not in this converter.

---

## Review path

Tier B — non-cost-bearing scripts work; sibling of B3's PR #86 (already merged).
PR opens → AI Head A structural review → merge per
`_ops/processes/b-code-dispatch-coordination.md`.

## Post-merge consumption (Track 5f bootstrap, owned by AI Head A)

1. Run converter against today's export → write to vault checkout.
2. Hand-edit `slug_changes:` block to match Director's open-follow-up
   resolutions (uk-homes add, personal-admin ensure-exists, etc.).
3. Run `scripts/regen_hot_md.py` → produces `hot.md` + slug retires +
   per-matter `proposed-gold.md` candidates.
4. Open PR on `baker-vault`. Merge after Director ratifies.
