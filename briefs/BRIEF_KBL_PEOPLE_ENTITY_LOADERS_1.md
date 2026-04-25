# BRIEF: KBL_PEOPLE_ENTITY_LOADERS_1 — people.yml + entities.yml loaders, lint, version

**Milestone:** M1 (Wiki stream foundation)
**Roadmap source:** `_ops/processes/cortex3t-roadmap.md` §M1 (renamed from `PEOPLE_ENTITIES_HARDENING` per AI Head A critique M1.2)
**Estimated time:** ~4–6h
**Complexity:** Medium
**Prerequisites:** M0 KBL_SCHEMA_1 (PR #52 merged — templates + slug registries shipped); M0 KBL_INGEST_ENDPOINT_1 (PR #55 merged — chokepoint live)

---

## Context

`kbl/ingest_endpoint.py:97-110` currently performs **format-only** validation on `type=person` and `type=entity` slugs. The TODO is explicit:

```python
# kbl/ingest_endpoint.py:99-101
For type=person/entity, format-only validation (registry loader not yet
shipped — see KBL_PEOPLE_ENTITY_LOADERS_1 follow-on).
```

Without registry loaders, anyone can ingest a `type=person` page with slug `andrey-okolkov` (typo — should be `oskolkov`) and the chokepoint accepts it. This is a known gap that defers to this brief.

`kbl.slug_registry` already exists for matters (consumed by `validate_slug_in_registry`); `people_registry` and `entity_registry` are the missing peers.

`baker-vault/wiki/registries/people.yml` and `baker-vault/wiki/registries/entities.yml` are the canonical source files (per VAULT.md §6 — confirm current path during exploration; if absent in vault, surface as blocker).

---

## Problem

1. No canonical loader for `people.yml` / `entities.yml`. Each call site re-parses YAML ad-hoc → drift risk.
2. Ingest endpoint cannot reject typo'd person/entity slugs.
3. No lint on registry yml structure (missing required fields, duplicate slugs, malformed roles).
4. No version discipline — silent edits to `people.yml` propagate to all readers without breakage signal.

## Solution

Build two parallel modules mirroring the existing `kbl/slug_registry.py` pattern:

### `kbl/people_registry.py`
- `load() -> dict[slug, Person]` — caches at module level; respects `BAKER_VAULT_PATH` env var.
- `is_canonical(slug: str) -> bool`
- `get(slug: str) -> Person | None`
- `version() -> int` — reads `version` from yml top-level frontmatter; raises `RegistryVersionError` if missing.
- `lint(path: Path) -> list[LintIssue]` — pure function, no I/O beyond the supplied path.

### `kbl/entity_registry.py`
- Same API surface as `people_registry`, schema differs (entities have legal-form, jurisdiction, parent_entity).

### Wire into ingest endpoint
- `kbl/ingest_endpoint.py:97-110` `validate_slug_in_registry()`:
  - For `type=person`: call `people_registry.is_canonical(slug)`; raise `KBLIngestError` if not.
  - For `type=entity`: call `entity_registry.is_canonical(slug)`; raise `KBLIngestError` if not.
- Behind a feature flag `KBL_REGISTRY_STRICT` (env var, default `false` for backward compat with any in-flight ingests). PR description must include flip plan.

### Version bump enforcement
- Lint check #1: yml has `version` integer field (start at `1`).
- Tests assert that bumping the version while leaving body unchanged produces a different cache hash (so loaders can invalidate caches downstream).
- No automatic bump — manual discipline tracked via lint warning when content changes without version bump (compares git HEAD~1 yml to current; warning only, not block).

## Files to modify

- **Create:** `kbl/people_registry.py`
- **Create:** `kbl/entity_registry.py`
- **Modify:** `kbl/ingest_endpoint.py` — add registry calls in `validate_slug_in_registry()` behind `KBL_REGISTRY_STRICT` env flag (default off).
- **Create:** `tests/test_people_registry.py`
- **Create:** `tests/test_entity_registry.py`
- **Create:** `tests/test_ingest_endpoint_registry_integration.py`

## Files NOT to touch

- `baker-vault/wiki/registries/people.yml` / `entities.yml` (read-only; vault writes are out of scope).
- `kbl/slug_registry.py` (model reference; do not refactor).
- Frontmatter regex constants in `kbl/ingest_endpoint.py` (separate concern).
- `migrations/` — no DDL.

## Risks

- **DDL drift trap:** N/A — no schema changes. Verify: `grep -rn "ADD COLUMN\|CREATE TABLE" kbl/people_registry.py kbl/entity_registry.py` returns zero lines.
- **Module-level cache race:** Singleton load on first call must be thread-safe (use `threading.Lock` like `slug_registry.py` does, if it does — check first).
- **Default-off feature flag:** If `KBL_REGISTRY_STRICT=false` (default), the loaders are imported and exercised by tests but ingest endpoint behaviour is unchanged. Director flips after observing zero false-rejects in staging.
- **Vault path absent:** If `BAKER_VAULT_PATH` unset OR registry files missing, loaders raise on first use with actionable message; do not silently return empty registry (silent-empty is the worst failure mode — every slug becomes "uncanonical").
- **Testing without vault:** Tests use fixture yml files in `tests/fixtures/registries/`, not the real vault — keep real-vault dependency out of unit tests.

---

## Code Brief Standards (mandatory)

- **API version:** No external API. Internal `kbl.slug_registry`-pattern modules. PyYAML for parse (already in requirements).
- **Deprecation check date:** N/A — internal Python.
- **Fallback:** `KBL_REGISTRY_STRICT=false` (default) keeps current behaviour. Flag-flip in a follow-up Tier B once 24h of telemetry shows zero would-be-rejected ingests in dry-run mode (add a warn-log path for would-reject when flag=false).
- **DDL drift check:** No DB writes. Verify per command above.
- **Literal pytest output mandatory:** Ship report MUST include literal `pytest tests/test_people_registry.py tests/test_entity_registry.py tests/test_ingest_endpoint_registry_integration.py -v` stdout. No "passes by inspection" — explicit memory rule (`feedback_no_ship_by_inspection.md`).

## Verification criteria

1. `pytest tests/test_people_registry.py -v` ≥8 tests pass (load, cache, is_canonical hit/miss, get, version, lint catches missing version, lint catches dup slugs, threading).
2. Same for `test_entity_registry.py` (schema differs slightly).
3. `pytest tests/test_ingest_endpoint_registry_integration.py -v` ≥4 tests:
   - flag off + unregistered person slug → accepted (current behaviour preserved).
   - flag on + unregistered person slug → `KBLIngestError`.
   - flag on + canonical person slug → accepted.
   - flag on + matter type → matter slug check still runs (no regression).
4. `python -c "import py_compile; py_compile.compile('kbl/people_registry.py', doraise=True); py_compile.compile('kbl/entity_registry.py', doraise=True); py_compile.compile('kbl/ingest_endpoint.py', doraise=True)"` exits 0.
5. PR description documents the `KBL_REGISTRY_STRICT` flip plan (when, observability checks, rollback).

## Out of scope

- Editing `people.yml` / `entities.yml` content (Director-curated; out of scope for this brief).
- Schema migration to the 7-field VAULT.md §2 format for people/entity pages (separate brief; this brief is loader+lint only).
- Backfilling missed-rejection alerts for prior accepted-but-typo'd slugs (separate cleanup brief if needed).
- Drift detector for registry corruption (separate `BRIEF_KBL_SCHEMA_DRIFT_DETECTOR` — M1 row 3, blocked on RA scope per critique M1.4).

---

## Branch + PR

- Branch: `kbl-people-entity-loaders-1`
- PR title: `KBL_PEOPLE_ENTITY_LOADERS_1: people + entity registries + ingest wiring (flag-gated)`
- Reviewer: AI Head B (cross-team) per autonomy charter §4

## §6C orchestration note (B-code dispatch coordination)

`KBL_REGISTRY_STRICT` flag flip is a §4-trigger-class change (cross-capability state writes — every ingest call). When flip moves from default-off to default-on, that is the trigger. **This brief ships the off-default mechanism only; flag-flip is a separate Tier B action with B1 situational review.**

## Co-Authored-By

```
Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```
