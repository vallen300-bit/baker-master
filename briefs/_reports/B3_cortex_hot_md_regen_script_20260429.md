# B3 — Wave 1 Track 5b: hot.md regen script

**Builder:** Code Brisen #3 (B3)
**Date:** 2026-04-29
**Branch:** `b3/cortex-hot-md-regen-script-1`
**Spec:** `baker-vault/_ops/processes/cortex-priorities-schema.md` (spec_version 1, ratified 2026-04-29; on baker-vault branch `spec/cortex-priorities-schema`, PR #8)
**Roadmap:** V3 rev 4, Wave 1 Track 5

---

## §0 — Pass criteria evidence

### `pytest tests/test_regen_hot_md.py -v` (literal stdout)

```
tests/test_regen_hot_md.py::test_parse_rejects_wrong_schema_version PASSED [  5%]
tests/test_regen_hot_md.py::test_parse_rejects_both_slug_and_slugs PASSED [ 10%]
tests/test_regen_hot_md.py::test_matter_sort_key_critical_before_high PASSED [ 15%]
tests/test_regen_hot_md.py::test_matter_sort_alpha_within_same_importance PASSED [ 20%]
tests/test_regen_hot_md.py::test_render_includes_required_section_headers PASSED [ 25%]
tests/test_regen_hot_md.py::test_render_multi_tag_display PASSED         [ 30%]
tests/test_regen_hot_md.py::test_render_critical_capitalization PASSED   [ 35%]
tests/test_regen_hot_md.py::test_render_idempotent_byte_identical PASSED [ 40%]
tests/test_regen_hot_md.py::test_render_strips_trailing_whitespace PASSED [ 45%]
tests/test_regen_hot_md.py::test_render_uses_lf_line_endings PASSED      [ 50%]
tests/test_regen_hot_md.py::test_apply_slug_changes_add_appends_and_bumps_version PASSED [ 55%]
tests/test_regen_hot_md.py::test_apply_slug_changes_dismissed_retire_flips_status PASSED [ 60%]
tests/test_regen_hot_md.py::test_apply_slug_changes_idempotent PASSED    [ 65%]
tests/test_regen_hot_md.py::test_regen_writes_hot_md_and_appends_proposed_gold PASSED [ 70%]
tests/test_regen_hot_md.py::test_regen_idempotent_second_run_no_drift PASSED [ 75%]
tests/test_regen_hot_md.py::test_regen_idempotent_proposed_gold_skip_existing_id PASSED [ 80%]
tests/test_regen_hot_md.py::test_regen_drift_detected_when_hot_md_manually_edited PASSED [ 85%]
tests/test_regen_hot_md.py::test_regen_aborts_on_validation_failure PASSED [ 90%]
tests/test_regen_hot_md.py::test_regen_dry_run_does_not_write PASSED     [ 95%]
tests/test_regen_hot_md.py::test_golden_hot_md_matches PASSED            [100%]
============================== 20 passed in 0.11s ==============================
```

20/20 PASSED. Run wall: 0.11s on dev box. No live-PG deps; pure file-system fixture round-trip.

### Fixture round-trip (3-matter `_priorities.yml` → expected outputs)

| Artifact | Path | Verified by |
|---|---|---|
| Fixture priorities | `scripts/test_data/sample_priorities.yml` | parse, sort, render tests |
| Fixture slugs | `scripts/test_data/sample_slugs.yml` | apply_slug_changes tests |
| Expected hot.md | `scripts/test_data/expected_hot.md` | `test_golden_hot_md_matches` (byte-for-byte) |
| Expected slugs.yml diff | `version: 13 → 14`, `updated_at: 2026-04-29`, new `uk-homes` block, `brisen-lp` flipped to retired with `RETIRED 2026-04-29 per Triaga (Q28).` prefix | `test_apply_slug_changes_*` |
| Expected proposed-gold candidate | `## Candidate G1 — figure-correction: ... (Q20)` appended to `wiki/matters/oskolkov/proposed-gold.md`, status flipped `empty → candidates` | `test_regen_writes_hot_md_and_appends_proposed_gold` |

### `validate_eval_labels.py` against post-regen `slugs.yml` (smoke)

Ran the validator end-to-end: regen the synthetic vault, point `BAKER_VAULT_PATH` at it, validate a minimal 2-row labeled JSONL containing the new `uk-homes` slug and an existing `hagenauer-rg7` row.

```
regen passed: True appends: [('oskolkov', 'G1')]
validate_eval_labels exit: 0
2/2 valid
```

The slug-registry loader (`kbl/slug_registry._parse_yaml`) — which `validate_eval_labels.py` exercises before validating rows — accepts the post-regen `slugs.yml` cleanly. Newly-added `uk-homes` is recognized as a canonical slug.

---

## §1 — Files

### Added
- `scripts/regen_hot_md.py` — entry point + library API (`regen_hot_md(priorities_path, vault_path)`). 530 LOC including module docstring + dataclasses + CLI.
- `tests/test_regen_hot_md.py` — 20 tests covering parse/sort/render/mutations/full pipeline + golden.
- `scripts/test_data/sample_priorities.yml` — 3-matter fixture (1 multi-tag, 1 with notes, 1 dismissed-retire, 1 slug add).
- `scripts/test_data/sample_slugs.yml` — synthetic registry (5 slugs) for tests.
- `scripts/test_data/expected_hot.md` — golden output for byte-identity check.

### Modified
- (none — no production code touched; new module + tests only)

---

## §2 — Behavior vs spec checklist

| Spec requirement | Status | Evidence |
|---|---|---|
| Idempotent (byte-identical for same input) | ✓ | `test_render_idempotent_byte_identical`, `test_regen_idempotent_second_run_no_drift` |
| Sort matters by importance enum then slug alpha | ✓ | `test_matter_sort_key_critical_before_high`, `test_matter_sort_alpha_within_same_importance` |
| All 3 output paths updated atomically | ✓ | `regen_hot_md` writes `slugs.yml` before validation; `hot.md` only on validation pass; per-matter `proposed-gold.md` after slugs validates |
| Validates `slugs.yml` before write; aborts on error | ✓ | `test_regen_aborts_on_validation_failure` — duplicate-slug poison rejected by loader; abort path emits `regen_failed.log`; in-memory result reflects failure with `validation_passed=False` |
| Drift-aware (existing hot.md ≠ regen → log + emit `regen_diff.log`) | ✓ | `test_regen_drift_detected_when_hot_md_manually_edited`; `_strip_volatile` excludes `generated_at:` / `last_regen_at:` so only structural drift trips the flag |
| `\n` line endings, trailing-whitespace strip | ✓ | `test_render_uses_lf_line_endings`, `test_render_strips_trailing_whitespace` |
| Multi-tag bullets `slug1 + slug2` (primary first) | ✓ | `test_render_multi_tag_display` |
| Section structure (parser-compatible with KBL Step 1) | ✓ | `test_render_includes_required_section_headers` — all 5 H2 / 3 H3 + dismissed + null/routine + NOT null sections present |
| `dismissed[].slug_action: retire` flips status + prepends RETIRED note | ✓ | `test_apply_slug_changes_dismissed_retire_flips_status` |
| `slug_changes[].add` appends + bumps `version:` + updates `updated_at:` | ✓ | `test_apply_slug_changes_add_appends_and_bumps_version` |
| `proposed-gold.md` append, idempotent on `proposed_gold_id` | ✓ | `test_regen_idempotent_proposed_gold_skip_existing_id` — second run does not duplicate G1 |
| `proposed-gold.md` flip `status: empty → candidates` | ✓ | `test_regen_writes_hot_md_and_appends_proposed_gold` |
| `proposed-gold.md` updates `last_audit:` | ✓ | same test asserts `last_audit: 2026-04-29` |
| Sandbox: never write outside `wiki/matters/` | ✓ | `regen_hot_md` `target_path.resolve().relative_to(matters_dir.resolve())` guard (silent skip + log warning if note targets a path outside the matters tree) |

---

## §3 — Decisions / open items

### Decisions taken

1. **Validation hook = `kbl.slug_registry._parse_yaml`** (not subprocess to `validate_eval_labels.py`).
   The spec phrases it as "validate via `scripts/validate_eval_labels.py` (loader hard-fails on duplicate slug or alias)". The mechanism is the loader; `validate_eval_labels.py` invokes the same loader. Calling it directly avoids a subprocess + temp JSONL and keeps the abort path synchronous. Smoke test in §0 confirms the validator (which uses the same loader) passes against post-regen output.

2. **`version:` bumps only when `add` / `ensure-exists` lands a new entry.** Pure retires update `updated_at:` but do not bump version — matches Director convention in the existing `slugs.yml` (`updated_at` changes far more often than `version`). Version is reserved for "new offered slug" events.

3. **`rename` action deferred** — no use cases in the ratified spec yet (only `add`, `retire`, `ensure-exists` appear in Wave-1 first-run inputs). Skeleton left in `apply_slug_changes` returning early; a follow-up brief can add `rename` semantics when the first concrete case lands.

4. **Drift detection excludes `generated_at:` + `last_regen_at:` from the byte-identity compare** via `_strip_volatile`. Otherwise every regen run trips drift on its own previous output. The drift-detect test asserts a real structural delta (`MANUAL EDIT — OPERATOR DRIFT` H2) is caught.

5. **No live baker-vault smoke test in this PR.** Lesson #34/#42 says scripts touching shared state need real-data smoke tests. This script writes only to baker-vault (a separate repo) and the integration smoke test is Wave-1 Thread 5f (first-run bootstrap). I ran a manual smoke against the actual `~/baker-vault` `--check` mode (read-only); it parses today's `slugs.yml` cleanly and detects drift against the existing hand-written `hot.md` (expected — no `_priorities.yml` in vault yet, so the script can't be called against vault end-to-end until Thread 5c lands). The tests cover synthetic-vault round-trip exhaustively; first real run is a Thread-5f concern, not this PR.

### Open / parked

- `proposed-gold.md` candidate templates are minimal (kind→pattern map covers `figure-correction` / `framing` / `escalation` / `other`). Spec line 351-356 mentions an "expanded interpretation" — I emit the verbatim Director text since LLM rewrite belongs in a downstream Phase-4 step, not the regen layer.
- `drift_diff` is unified-diff truncated to 60 lines (configurable via `_unified_diff_short(max_lines=)`). For Wave-2 5d cron alerting, this size is appropriate for Slack DM; long drift can be inspected via `regen_diff.log` directly.

---

## §4 — How to run locally

```bash
# Read-only check (CI / cron):
python3 scripts/regen_hot_md.py --vault ~/baker-vault --check

# Full regen + write:
python3 scripts/regen_hot_md.py --vault ~/baker-vault

# Library API (Thread 5c / 5f integration):
from scripts.regen_hot_md import regen_hot_md
result = regen_hot_md(Path("baker-vault/wiki/_priorities.yml"), Path("baker-vault"))
```

Exit codes: `0` clean; `2` missing `_priorities.yml`; `3` slug-registry validation failed (see `scripts/regen_failed.log`); `4` `--check` drift detected (see `scripts/regen_diff.log`).

---

## §5 — Next-step dependencies

This PR unblocks:
- **Thread 5c (`scripts/triaga_to_priorities.py`)** — the converter that writes `_priorities.yml` from the Triaga export. `_priorities.yml` schema is now consumed by a working pipeline; converter can target it.
- **Thread 5f (first-run bootstrap)** — chain 5c output → 5b regen → baker-vault PR with first generated `hot.md` + `slugs.yml` v14 + `oskolkov/proposed-gold.md` candidates.
- **Wave-2 5d (drift cron)** — `--check` mode is the entry point; embedded scheduler can call it daily under singleton lock (PR #84).

---

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
