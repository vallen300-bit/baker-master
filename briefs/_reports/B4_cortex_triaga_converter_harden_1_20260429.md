# SHIP REPORT — B4 / CORTEX_TRIAGA_CONVERTER_HARDEN_1

**Date:** 2026-04-29
**Builder:** B4 (`~/bm-b4`)
**Branch:** `b4/cortex-triaga-converter-harden-1`
**Wave:** 1 follow-up to Track-5c (PR #87 `triaga_to_priorities.py`)
**Driven by:** B3 ship report `briefs/_reports/B3_wave1_5f_bootstrap_20260429.md` §2 + live failing input `/Users/dimitry/baker-vault/wiki/_priorities.yml`
**Trigger class:** Tier B (parser-quality fix; no live-cycle / cost surface touched)

---

## What shipped

Three sharp-edge fixes to `scripts/triaga_to_priorities.py` flagged by B3 in
the Wave-1 5f bootstrap (PR #11 on baker-vault). Plus a small follow-up to
`scripts/regen_hot_md.py` so the new `pending_slug_review[]` section surfaces
in `hot.md` for Director attention.

| Bug | Affected Q-IDs | Fix |
|---|---|---|
| 1 — em-dash split bleeds bracket suffix into slug | Q17, Q18, Q37 | New `_split_slug_from_description()` anchors on bracket close (`]`) when the slug-field starts with `[`, instead of bisecting on the first ` — `. Bracket-suffix regex (`— slug TBD`, `— see note`) is now greedy past trailing prose. |
| 2 — `/` always splits slug field | Q30, Q31, Q41 | `/` now splits ONLY when (a) every slash-token matches `^[a-z0-9][a-z0-9-]+$` AND (b) a `canonical_slugs` set is supplied AND (c) every token is in that set. Otherwise `/` is treated as prose; the field stays a single literal slug. RA-23 declares `+` the canonical multi-slug separator. |
| 3 — non-canonical slug emission unchecked | Q17, Q18, Q30, Q31, Q41 | New `pending_slug_review[]` top-level YAML section. After normalization, every emitted slug is checked against the supplied `canonical_slugs` set; mismatches still emit in the matter row (converter never blocks) but ALSO record `{triaga_ref, slug, section, raw_slug_field}` in `pending_slug_review[]`. New `CANONICAL_SLUG_LOOSE` module flag (default False) and `--canonical-slug-loose` CLI flag bypass population while regen learns to consume the new section. |

### Files modified

- `scripts/triaga_to_priorities.py` (+135 LOC, −12)
  - New `_split_slug_from_description()` helper.
  - Replaced `_HEADER_LINE_RE` (now a 2-group capture; bisection delegated to helper).
  - Replaced `_TBD_BRACKET_RE` with `_BRACKET_OUTER_RE` + `_BRACKET_SUFFIX_RE` + `_strip_bracket_suffix()` helper (consumes trailing prose past the sentinel).
  - `normalize_slug_field()` reordered: combined-slug override first, bracket-strip second, `+`-split always, `/`-split only when shape + registry agree.
  - New `_validate_canonical_slugs()` walks emitted slugs and builds `pending_slug_review[]`.
  - `to_priorities_dict()` + `triaga_export_to_priorities()` accept `canonical_slugs=` + `canonical_slug_loose=`.
  - CLI: `--registry path/to/slugs.yml` + `--canonical-slug-loose`. `--registry` lazy-imports `kbl.slug_registry._parse_yaml`.
- `scripts/regen_hot_md.py` (+15 LOC) — new `## Pending slug review` section in `hot.md`, between dismissed + null-routine. Empty case writes `(none)`.
- `scripts/test_data/expected_hot.md` (+4 lines) — golden fixture refreshed for new section.
- `tests/test_triaga_to_priorities.py` (+220 LOC) — 9 new tests + 2 updated (existing `test_multi_slug_slash_separator` replaced by 3 finer-grained tests reflecting the new `/`-split policy).
- `scripts/test_data/triaga_export_q17_q18_q30_q31_q37.md` (NEW, 25 lines) — trimmed reproducer covering all 3 bugs simultaneously.

### What was NOT touched

- `kbl/slug_registry.py` — read-only consumer.
- `outputs/dashboard.py`, `orchestrator/`, `triggers/`, migrations — UNTOUCHED.
- `baker-vault/slugs.yml` — separate-repo PR only; converter only reads.
- The schema spec at `baker-vault/_ops/processes/cortex-priorities-schema.md`
  needs a follow-up update documenting the `pending_slug_review[]` section.
  Per CLAUDE.md hard rule, vault-side docs require a separate-repo PR — flagged
  for AI Head A (parked at end of report).

---

## §0 — Pass criteria evidence (literal stdout, no inspection-only)

### Test suite — 25 passed (16 prior + 9 new) in 0.05s

```
$ .venv-b3/bin/pytest tests/test_triaga_to_priorities.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0 -- /Users/dimitry/bm-b3/.venv-b3/bin/python3.12
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b4
plugins: langsmith-0.7.33, anyio-4.13.0
collecting ... collected 25 items

tests/test_triaga_to_priorities.py::test_sample_fixture_roundtrip PASSED [  4%]
tests/test_triaga_to_priorities.py::test_zero_dismissed_emits_empty_list PASSED [  8%]
tests/test_triaga_to_priorities.py::test_multi_slug_plus_separator PASSED [ 12%]
tests/test_triaga_to_priorities.py::test_multi_slug_plus_with_spaces PASSED [ 16%]
tests/test_triaga_to_priorities.py::test_slash_no_split_without_registry PASSED [ 20%]
tests/test_triaga_to_priorities.py::test_slash_splits_only_when_registry_confirms_all_tokens PASSED [ 24%]
tests/test_triaga_to_priorities.py::test_slash_does_not_split_when_one_token_missing_from_registry PASSED [ 28%]
tests/test_triaga_to_priorities.py::test_q33_nvidia_corinthia_combined_slug PASSED [ 32%]
tests/test_triaga_to_priorities.py::test_combined_slug_override_can_be_disabled PASSED [ 36%]
tests/test_triaga_to_priorities.py::test_q19_folds_into_q33 PASSED       [ 40%]
tests/test_triaga_to_priorities.py::test_dup_fold_can_be_disabled PASSED [ 44%]
tests/test_triaga_to_priorities.py::test_q37_bora_bora_bracket_strips_to_philippe_soulier PASSED [ 48%]
tests/test_triaga_to_priorities.py::test_bracketed_see_note_stripped PASSED [ 52%]
tests/test_triaga_to_priorities.py::test_malformed_missing_meta_line_raises PASSED [ 56%]
tests/test_triaga_to_priorities.py::test_malformed_unknown_status_raises PASSED [ 60%]
tests/test_triaga_to_priorities.py::test_malformed_active_missing_when_raises PASSED [ 64%]
tests/test_triaga_to_priorities.py::test_unknown_when_raises PASSED      [ 68%]
tests/test_triaga_to_priorities.py::test_q17_uk_homes_bracket_em_dash PASSED [ 72%]
tests/test_triaga_to_priorities.py::test_q18_uk_homes_bracket_em_dash PASSED [ 76%]
tests/test_triaga_to_priorities.py::test_q37_bora_bora_bracket PASSED    [ 80%]
tests/test_triaga_to_priorities.py::test_q30_slash_no_split PASSED       [ 84%]
tests/test_triaga_to_priorities.py::test_q31_slash_no_split PASSED       [ 88%]
tests/test_triaga_to_priorities.py::test_non_canonical_slug_routes_to_pending_review PASSED [ 92%]
tests/test_triaga_to_priorities.py::test_harden_repro_fixture_clean_extraction PASSED [ 96%]
tests/test_triaga_to_priorities.py::test_chain_converter_output_feeds_regen PASSED [100%]

============================== 25 passed in 0.05s ==============================
```

Brief asked for "16 + 6 = 22"; actual count is 25 because the existing
`test_multi_slug_slash_separator` (which asserted the old aggressive-split
behavior) is now wrong-by-design and was decomposed into 3 finer tests
covering the new `/`-split policy:
`test_slash_no_split_without_registry`, `test_slash_splits_only_when_registry_confirms_all_tokens`,
and `test_slash_does_not_split_when_one_token_missing_from_registry`. The
6 named tests from the brief are all present + green:
`test_q17_uk_homes_bracket_em_dash`, `test_q18_uk_homes_bracket_em_dash`,
`test_q37_bora_bora_bracket`, `test_q30_slash_no_split`,
`test_q31_slash_no_split`, `test_non_canonical_slug_routes_to_pending_review`.

### Sibling regen suite — no regression

```
$ .venv-b3/bin/pytest tests/test_triaga_to_priorities.py tests/test_regen_hot_md.py
45 passed in 0.10s
```

`test_regen_hot_md.py::test_golden_hot_md_matches` re-validates against
`scripts/test_data/expected_hot.md` after the new `## Pending slug review`
section (empty `(none)` case) was added to the fixture. Idempotence /
byte-identity / drift-detection / slug-mutation tests all still green.

### Singleton CI guard

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
EXIT=0
```

### Compile-clean

```
$ .venv-b3/bin/python3 -c "import py_compile; \
    py_compile.compile('scripts/triaga_to_priorities.py', doraise=True); \
    py_compile.compile('scripts/regen_hot_md.py', doraise=True); \
    py_compile.compile('tests/test_triaga_to_priorities.py', doraise=True)"
OK
```

---

## §1 — Real-world dry-run + diff against live `_priorities.yml`

### Re-run on actual ratified export with `--registry`

```
$ rm -rf /tmp/b4_harden && mkdir -p /tmp/b4_harden/vault/wiki
$ cp /Users/dimitry/baker-vault/slugs.yml /tmp/b4_harden/vault/slugs.yml
$ .venv-b3/bin/python3 scripts/triaga_to_priorities.py \
    --export "/Users/dimitry/Vallen Dropbox/Dimitry vallen/_01_INBOX_FROM_CLAUDE/2026-04-29-b1-brisen-triage-ratified-export.md" \
    --out /tmp/b4_harden/vault/wiki/_priorities.yml \
    --registry /Users/dimitry/baker-vault/slugs.yml -v
2026-04-29 23:47:38,131 WARNING non-canonical slug emitted: triaga_ref=Q17 slug='private-assets' section=matters
2026-04-29 23:47:38,131 WARNING non-canonical slug emitted: triaga_ref=Q18 slug='private-assets' section=matters
2026-04-29 23:47:38,131 WARNING non-canonical slug emitted: triaga_ref=Q30 slug='tax / lana' section=matters
2026-04-29 23:47:38,131 WARNING non-canonical slug emitted: triaga_ref=Q41 slug='orbit / amir' section=matters
2026-04-29 23:47:38,131 WARNING non-canonical slug emitted: triaga_ref=Q31 slug='tax / cbp' section=dismissed
OK: wrote /tmp/b4_harden/vault/wiki/_priorities.yml (40 items: 30 Active · 5 Completed · 5 Dismissed · 1 Partial · 5 pending review)
```

### Chain test — regen accepts hardened output, no drift

```
$ .venv-b3/bin/python3 scripts/regen_hot_md.py --vault /tmp/b4_harden/vault --check
OK: no drift; slug registry validates
EXIT=0

$ .venv-b3/bin/python3 scripts/regen_hot_md.py --vault /tmp/b4_harden/vault
OK: hot.md rewritten (30 matters); slugs.yml mutations: 0; proposed-gold appends: 0
EXIT=0

$ wc -c /tmp/b4_harden/vault/wiki/hot.md
    4910 /tmp/b4_harden/vault/wiki/hot.md
```

### `## Pending slug review` section as rendered into `hot.md`

```
## Pending slug review (non-canonical slugs awaiting Director ratification)

- **private-assets** (Q17, matters) (raw: `[private-assets — slug TBD]`) — Director: confirm slug or assign canonical.
- **private-assets** (Q18, matters) (raw: `[private-assets — slug TBD]`) — Director: confirm slug or assign canonical.
- **tax / lana** (Q30, matters) — Director: confirm slug or assign canonical.
- **orbit / amir** (Q41, matters) — Director: confirm slug or assign canonical.
- **tax / cbp** (Q31, dismissed) — Director: confirm slug or assign canonical.
```

### Diff against current `/Users/dimitry/baker-vault/wiki/_priorities.yml`

The 6 affected line groups (Q17 / Q18 / Q30 / Q31 / Q37 / Q41) all clean up
under the hardened parser; a new `pending_slug_review:` section is added so
regen + Director both see the non-canonicals.

```diff
@@ -103,19 +103,19 @@
   triaga_ref: Q16
   description: Answer BDO questions re Cap Ferrat villa restructuring
   notes: []
-- slug: '[private-assets'
+- slug: private-assets
   when: 4w
   importance: high
   category: financial
   triaga_ref: Q17
-  description: slug TBD] — Barclays UK mortgage renewal form issued
+  description: Barclays UK mortgage renewal form issued
   notes: []
-- slug: '[private-assets'
+- slug: private-assets
   when: urgent
   importance: high
   category: financial
   triaga_ref: Q18
-  description: slug TBD] — Barclays UK valuer discrepancy — Strutt Parker vs Monaco
+  description: Barclays UK valuer discrepancy — Strutt Parker vs Monaco
   notes: []
@@ -166,9 +166,7 @@
   triaga_ref: Q29
   description: Capital-call planning matter
   notes: []
-- slugs:
-  - tax
-  - lana
+- slug: tax / lana
   when: asap
   importance: high
   category: active-deal
@@ -205,12 +203,12 @@
   triaga_ref: Q36
   description: Evaluate cooperation with MO Prague current owners
   notes: []
-- slug: '[philippe-soulier'
+- slug: philippe-soulier
   when: not-urgent
   importance: low
   category: origination
   triaga_ref: Q37
-  description: slug TBD] — Bora-Bora pipeline
+  description: Bora-Bora pipeline
   notes: []
@@ -230,9 +228,7 @@
   triaga_ref: Q39
   description: Swiss passport application — Claude Laport, Geneva
   notes: []
-- slugs:
-  - orbit
-  - amir
+- slug: orbit / amir
   when: 4w
   importance: medium
   category: origination
@@ -249,9 +245,7 @@
   reason: Director dismissed (Q28).
   dismissed_at: '2026-04-29'
 - triaga_ref: Q31
-  slugs:
-  - tax
-  - cbp
+  slug: tax / cbp
   reason: Director dismissed (Q31).
   dismissed_at: '2026-04-29'
@@ -283,6 +277,27 @@
   slug: constantinos
   completed_at: '2026-04-29'
   summary: AO transfer dispatch coordination
+pending_slug_review:
+- triaga_ref: Q17
+  slug: private-assets
+  section: matters
+  raw_slug_field: '[private-assets — slug TBD]'
+- triaga_ref: Q18
+  slug: private-assets
+  section: matters
+  raw_slug_field: '[private-assets — slug TBD]'
+- triaga_ref: Q30
+  slug: tax / lana
+  section: matters
+  raw_slug_field: tax / lana
+- triaga_ref: Q41
+  slug: orbit / amir
+  section: matters
+  raw_slug_field: orbit / amir
+- triaga_ref: Q31
+  slug: tax / cbp
+  section: dismissed
+  raw_slug_field: tax / cbp
@@ -298,3 +313,4 @@
   completed_count: 5
   dismissed_count: 5
   partial_count: 1
+  pending_slug_review_count: 5
```

Note: B3's bootstrap output had Q41 `orbit / amir` and Q31 `tax / cbp`
emitted as 2-element `slugs:` lists (the Bug-2 split). Hardened output
keeps them as single literal slugs and routes both to `pending_slug_review`.
Q37 was previously already in `slugs.yml` (canonical at version 13) so it
does NOT appear in pending review; only the description / slug fields
clean up. Q17 / Q18 `private-assets` and Q30 `lana` and Q41 `amir` etc.
are flagged in pending review for Director to ratify the canonical name
in the next Triaga round (slug_changes block).

---

## §2 — Lane discipline

- ✅ `outputs/dashboard.py` — UNTOUCHED.
- ✅ `orchestrator/`, `triggers/`, `kbl/` — UNTOUCHED.
- ✅ `migrations/` — UNTOUCHED.
- ✅ `baker-vault/slugs.yml` — UNTOUCHED (separate-repo PR; converter only reads).
- ✅ No new env var. `--registry` is opt-in; no `BAKER_VAULT_PATH` requirement
  added to the converter (lazy-imports `kbl.slug_registry._parse_yaml` and
  passes a path explicitly, bypassing the global cache + env-var resolution).
- ✅ No new dependency.
- ✅ Singleton-pattern CI guard clean.

---

## §3 — Open / parked

### Spec follow-up (vault-side, AI Head A's lane)

`baker-vault/_ops/processes/cortex-priorities-schema.md` (spec_version 1)
needs a follow-up section documenting:

1. New top-level `pending_slug_review[]` array — fields: `triaga_ref`,
   `slug`, `section` (one of `matters` / `dismissed` / `completed`),
   `raw_slug_field`.
2. New provenance count `provenance.pending_slug_review_count`.
3. `regen_hot_md.py` surfaces this section as `## Pending slug review`
   in `hot.md` between dismissed and null-routine.

Per repo CLAUDE.md hard rule, this is a separate-repo PR. Parked for
AI Head A to open as a follow-up alongside the post-merge 5f re-run.

### B3's optional 5c follow-ups also addressed

B3 ship report §2 also flagged "stop splitting on `/` when the left token
equals a known category name". The new `/`-split policy is stricter than
that: `/` splits only when EVERY token is a known canonical slug AND of
canonical shape, regardless of whether any token happens to also be a
category name. Equivalent or stricter; same outcome on Q30 / Q31 / Q41.

### Post-merge action (AI Head A)

1. Re-run B3's Wave-1 5f bootstrap pipeline against this PR's hardened converter:
   ```
   triaga_to_priorities.py --registry slugs.yml → wiki/_priorities.yml
   regen_hot_md.py → wiki/hot.md
   ```
2. Open follow-up `baker-vault` PR refreshing `wiki/_priorities.yml`
   (Q17, Q18, Q30, Q31, Q37, Q41 cleaned) + `wiki/hot.md` (description
   fields no longer carry bracket-suffix bleed; new pending-review section
   visible).
3. Open separate-repo PR on `baker-vault` updating
   `_ops/processes/cortex-priorities-schema.md` per §3 above.

---

## §4 — Review path

Tier B — parser hardening only; no live-cycle / cost surface touched.
PR opens → AI Head A structural review → merge per
`_ops/processes/b-code-dispatch-coordination.md`.
