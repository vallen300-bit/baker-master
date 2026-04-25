# BRIEF: HAGENAUER_WIKI_BOOTSTRAP_1 — Director-curated Hagenauer matter wiki seed

**Milestone:** M1 (Wiki stream foundation)
**Roadmap source:** `_ops/processes/cortex3t-roadmap.md` §M1 (added per AI Head A critique M1.1, blocking for M3)
**Estimated time:** ~3–5h
**Complexity:** Medium
**Prerequisites:** M0 KBL_INGEST_ENDPOINT_1 (PR #55 merged), KBL_SCHEMA_1 (PR #52 merged)

---

## Context

M3 (Cortex-3T MVP) ships first cycles on Hagenauer RG7. Without `wiki/matters/hagenauer-rg7/` populated, the first cycle retrieves nothing — Cortex boots into an empty wiki for its only matter.

Existing matter-shape templates: `wiki/matters/oskolkov/` (17 entries, includes `cards/`, `interactions/`, `sub-matters/`) and `wiki/matters/movie/`. Top-level `wiki/hagenauer-rg7/` exists but is signal-page content (one .md per dated event), NOT the matter-shape pattern.

`14_HAGENAUER_MASTER/` (Dropbox) is the source of curated truth: 10 numbered subfolders (Agreements_Contracts, Claims_Against_Hagenauer, Payments_Invoices, Subcontractors, Buyers, Project_Documentation, Reference_Materials, Correspondence, Negotiations_History, Archive) plus working files.

CHANDA #9 (mac-mini-writer): Baker NEVER writes `baker-vault/wiki/` directly. Agent writes flow through `kbl.ingest_endpoint.ingest()` with `voice=gold`, which stages to `vault_scaffolding/live_mirror/v1/<slug>.md`; Mac Mini mirrors to baker-vault.

---

## Problem

`wiki/matters/hagenauer-rg7/` does not exist. M3 dispatch is blocked.

## Solution

Build a **one-shot generator script** `scripts/bootstrap_hagenauer_wiki.py` that:

1. Inspects `wiki/matters/oskolkov/` and `wiki/matters/movie/` to canonicalise the **matter-shape file set** (intersection of files both matters share = required; union of additional files = optional).
2. Emits skeleton `.md` files for `hagenauer-rg7` at a staging path (`vault_scaffolding/live_mirror/v1/matters/hagenauer-rg7/` if it exists; otherwise `outputs/hagenauer_bootstrap/matters/hagenauer-rg7/` with a printed instruction to manually move).
3. Each skeleton includes:
   - Valid VAULT.md §2 7-field frontmatter (`type: matter`, `slug: hagenauer-rg7-<filename-stem>`, `name`, `updated: 2026-04-25`, `author: agent`, `tags: ["hagenauer-rg7"]`, `related: []`, plus optional `voice: gold`).
   - Placeholder body listing the corresponding `14_HAGENAUER_MASTER/` source folders the Director should pull content from (e.g., `_overview.md` body lists `01_Agreements_Contracts/`, `06_Project_Documentation/`).
   - A `[NEEDS_DIRECTOR_CONTENT]` marker so Cortex M3 can detect placeholder vs real content.
4. **Does NOT push to baker-vault.** Generates locally only. Director (or AI Head Tier B) decides whether to copy into baker-vault.

## Architectural ambiguity to flag, NOT resolve

Sub-page slugs (`hagenauer-rg7-overview`, `hagenauer-rg7-financial-facts`) are NOT in `slugs.yml`. `validate_slug_in_registry()` rejects non-canonical matter slugs. **Two possible resolutions, log both in PR description, do not pick:**

(a) Add sub-page slugs to `slugs.yml` (registry inflation; ~10 new entries per matter).
(b) Introduce a new `type: matter-page` distinct from `type: matter`, with format-only slug validation (parent slug + dash + suffix must match canonical matter).

**Action:** Generate skeletons assuming option (a) for now (frontmatter `type: matter`, parent matter slug as a tag). Surface decision-need in ship report. Do **not** call `kbl.ingest_endpoint.ingest()` from this script — generation only.

## Files to modify

- **Create:** `scripts/bootstrap_hagenauer_wiki.py`
- **Create:** `tests/test_bootstrap_hagenauer_wiki.py`
- **Modify:** none

## Files NOT to touch

- `kbl/ingest_endpoint.py` (this brief is generation-only, not ingest path)
- `kbl/slug_registry.py` / `baker-vault/slugs.yml` (registry edits are downstream Tier B)
- `wiki/matters/hagenauer-rg7/` directly in baker-vault (CHANDA #9)
- Any existing `wiki/matters/oskolkov/` or `wiki/matters/movie/` content (read-only reference)

## Risks

- **Schema drift (LONGTERM.md lesson):** Bootstrap script must use `kbl.ingest_endpoint.REQUIRED_FRONTMATTER_KEYS` and `validate_frontmatter()` to validate every emitted skeleton — do not hard-code field names.
- **Ghost generation:** If `vault_scaffolding/live_mirror/v1/` doesn't exist, fail loud with instruction (don't silently create the wrong path).
- **Source material PII:** Skeleton bodies must not embed actual financial figures or counterparty names beyond what is already public in the slug — only reference source folder paths.

---

## Code Brief Standards (mandatory)

- **API version:** No external API. Internal Python module imports only. Validate against `kbl.ingest_endpoint.validate_frontmatter` (current as of M0 PR #55, 2026-04-23).
- **Deprecation check date:** N/A — internal Python code.
- **Fallback:** Script must be idempotent. Re-running on existing staging dir overwrites files only if `--force` flag passed; default: fail with "skeleton exists, pass --force to overwrite".
- **DDL drift check:** No DB writes. Verify by `grep -n "INSERT\|UPDATE\|DELETE" scripts/bootstrap_hagenauer_wiki.py` returns 0 lines.
- **Literal pytest output mandatory:** Ship report MUST include literal `pytest tests/test_bootstrap_hagenauer_wiki.py -v` stdout. No "passes by inspection."

## Verification criteria

1. `python scripts/bootstrap_hagenauer_wiki.py --dry-run` lists files it would emit; emits zero files.
2. `python scripts/bootstrap_hagenauer_wiki.py` emits ≥9 files (the canonical matter-shape set determined from oskolkov∩movie analysis).
3. Each emitted file's frontmatter passes `kbl.ingest_endpoint.validate_frontmatter()` without raising.
4. Re-run without `--force` raises with exit code 1.
5. Re-run with `--force` overwrites cleanly.
6. `pytest tests/test_bootstrap_hagenauer_wiki.py -v` shows ≥6 tests passing.
7. PR description includes the (a)/(b) architectural ambiguity surface for AI Head + RA decision.

## Out of scope

- Populating skeleton bodies with real Hagenauer content (Director / human curation step).
- Pushing to baker-vault (Mac Mini path; manual or follow-on brief).
- Schema extension for sub-page slugs (decision lives outside this brief).
- Ingesting via `kbl.ingest_endpoint.ingest()` (separate downstream brief once schema decision is made).

---

## Branch + PR

- Branch: `hagenauer-wiki-bootstrap-1`
- PR title: `HAGENAUER_WIKI_BOOTSTRAP_1: matter-shape skeleton generator + tests`
- Reviewer: AI Head B (cross-team) per autonomy charter §4

## Co-Authored-By

```
Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```
