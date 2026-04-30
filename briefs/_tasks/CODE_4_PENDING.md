# CODE_4 — IN_REVIEW (CORTEX_CONFIG_DIRECTIVES_SCHEMA_1 — Brief 4)

**Status:** IN_REVIEW — REQUEST_CHANGES — 2026-04-30
**PR:** https://github.com/vallen300-bit/baker-master/pull/125 (`b4/cortex-config-directives-schema`)
**Brief:** `briefs/BRIEF_CORTEX_CONFIG_DIRECTIVES_SCHEMA_1.md`
**Builder:** B4
**Reviewer:** AI Head A architect-review pass via `code-architecture-reviewer` subagent. AI Head B cross-lane ratify will chain on top after patch.

## Verdict — REQUEST CHANGES

Same class of spec-vs-reality bug as the architect-review pass on PR #111 caught earlier today (`store.conn` non-existent attribute + sweep-status filter excluded approved/rejected/modified). Schema migration, partial unique index, bootstrap-script integration are clean and Brief-3-ready. The CRITICAL is single-line; HIGHs are surgical.

Full architect comment on PR #125 (issuecomment-4353812482).

## Required patches (CRITICAL + 2 HIGH; MEDIUM optional)

### 1. CRITICAL — `scripts/migrate_directives_for_existing_matters.py:73`

`load_active_matters` uses `description` as `name` fallback when slugs.yml row has no `name:` key. Real `~/baker-vault/slugs.yml` v16 has **zero `name:` keys** across 36 rows. Description-as-name produces YAML-breaking frontmatter (live repro on active `uk-homes`: `yaml.ScannerError: mapping values are not allowed here`, line 3 col 57). Wet-run silently writes broken YAML.

**Fix:**

```python
name = row.get("name") or " ".join(w.capitalize() for w in slug.split("-"))
out.append({"slug": slug, "name": str(name)[:80], "status": status})
```

Slug-derived title is ugly but parseable. Director can hand-edit display names later.

### 2. HIGH — `orchestrator/cortex_directives.py:117-119` (defense-in-depth)

`provision_directive_schema` writes content directly without ever calling `validate_frontmatter`. Mirrors the gap. Bake validation into the function as an invariant so any future caller (this migrator, Brief 3 Reflector consumers, any new path) can't silently corrupt files.

**Fix:** before `target.write_text(content)`, parse the frontmatter region (mirror `_extract_frontmatter` from `scripts/bootstrap_matter.py:557-558`) and call `validate_frontmatter` on the parsed dict. Raise on failure so the caller gets a per-matter loud error.

### 3. HIGH — `tests/test_migrate_directives.py` regression test

Existing fixtures hand-craft slugs.yml with 1-2-char descriptions (`"A1"`, `"Gamma"`) and never omit the `name:` key. That's why pytest stayed green despite the CRITICAL. Add a regression test that:

- points the migrator at a fixture mimicking real `slugs.yml` shape (no `name:` field on any row, real-world descriptions including ones with `: ` and apostrophes),
- asserts every emitted file passes `validate_frontmatter`.

With fix #1, this test passes. Without it, the test catches the description-fallback bug pre-merge.

### 4. MEDIUM — `_global` slug caveat (not blocking; for Brief 3 awareness)

Add a one-liner comment near the top of `migrations/20260430_cortex_directives.sql` noting that `matter_slug='_global'` is accepted by this schema but bypasses `KEBAB_SLUG_RE` used elsewhere (`kbl/ingest_endpoint.py:35` + `scripts/bootstrap_matter.py:33`). Brief 3 must special-case `_global` in citation parsing or extend the regex.

## Patch ritual

Same branch (`b4/cortex-config-directives-schema`), incremental commits OK, force-push not needed. After patches:

1. Pre-pytest re-checkout ritual.
2. Run the new regression test (must fail before fix #1, pass after).
3. Run full pytest — confirm 41 → 42+ pass, 8 skipped unchanged.
4. Push to existing branch — PR #125 picks up automatically.
5. Comment on PR #125 with grep proof of the four fixes + new pytest output.

## After re-review

- Architect-review pass re-runs against the patched diff.
- AI Head B cross-lane ratify chains on top.
- AI Head A merges.
- Mailbox flips to COMPLETE.

## Trigger-class

TIER A — schema migration + cross-capability state writes. AI Head B cross-lane ratify required pre-merge.

## Companion state (unchanged)

- Brief 4 ships FIRST (Q1 flip); Brief 3 (Phase 6 Reflector) ships AFTER.
- Brisen Desk slug add: baker-vault PR #37 (separate, Director review).
- Desk memory seeds: baker-vault PR #40 (separate, Director review).

## Previous task (closed)

PR #107 (BOOTSTRAP_V2_GOLD_SKIP_1) merged 2026-04-30 with B1 PASS verdict.
