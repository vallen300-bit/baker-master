# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1
**Task posted:** 2026-04-22 (Director called "audit" over "patch" after 5th drift bug surfaced in Step 5 stub → Step 6 validate path)
**Status:** OPEN — STEP5_STUB_SCHEMA_CONFORMANCE_AUDIT_1

---

## Context — Director called "audit" over "patch"

All day 2026-04-21 we've played whack-a-mole on Step 5 stub → Step 6 Pydantic path:

| PR | Fix | Drift class |
|----|-----|-------------|
| #30 | raw_content phantom column | column existence |
| #31 | related_matters JSONB cast | column type |
| #32 | finalize_retry_count never migrated | column existence |
| #33 | hot_md_match BOOLEAN → TEXT | column type |
| #34 | yaml.safe_dump for stub frontmatter | encoding |
| #35 | source_id cast to str | producer-vs-schema type |

After PR #35 merged + deployed, first 2 rows through Step 6 hit the **next** layer:

```
ValidationError for SilverFrontmatter:
primary_matter=null with non-empty related_matters is invalid
(per §4.2 invariant — null-matter signal cannot carry cross-links)
```

Plus a **secondary cascade**: `_route_validation_failure` → `_increment_retry_count` → `psycopg2.OperationalError: SSL connection has been closed unexpectedly` → `psycopg2.InterfaceError: connection already closed`. The error handler itself crashes on validation failures, leaving rows silently stranded. Compounds the claim-transactionality stranding bug.

**Director's call:** no more single-bug patches. Run a comprehensive audit that kills the entire class in one sweep. L-effort OK. Done right once.

## Scope — full Step 5 stub → Step 6 validation conformance sweep

### Axis 1: Field-level type conformance
For every field in both stub writer outputs (`_build_skip_inbox_stub`, `_build_stub_only_stub`) and in the FULL_SYNTHESIS path if reachable, compare against `SilverFrontmatter` (kbl/schemas/silver.py:134-152):
- Type match (str vs. int, list vs. scalar, etc.)
- Required vs. optional
- Coercion paths (Pydantic v2 coerces some, not all — document the matrix)
- Enum / Literal constraints (Voice, Author, Vedana, StubStatus, MatterSlug)

### Axis 2: Cross-field invariants
Find every `@model_validator` / `@field_validator` in SilverFrontmatter. Enumerate invariants:
- §4.2: `primary_matter=null` + `related_matters` non-empty → ERROR (this session's blocker)
- Other paired constraints (explore and list)
Confirm each stub writer and the FULL_SYNTHESIS path satisfy ALL invariants for every decision branch.

### Axis 3: Error-handler robustness
`_route_validation_failure` + `_increment_retry_count` + `_bump_retry` in step6_finalize.py. When Pydantic raises on invalid stub input, the current error path tries to write to a connection that was rolled back, causing cascaded `connection already closed`. Fix: either (a) open a fresh short-lived connection for the error-recording write, or (b) defer error accounting to a follow-up outside the transaction boundary.

### Axis 4: Test coverage
Every known-good and known-bad shape from axes 1-3 needs a regression test that:
- Builds the stub dict
- `yaml.safe_dump → yaml.safe_load → SilverFrontmatter.model_validate`
- Asserts pass / expected-error-class
Plus: test the error-handler path with a deliberately-invalid stub to confirm it no longer cascades.

### Axis 5: Missing `signal_id` in Opus prompt
Known latent bug: `kbl/prompts/step5_opus_user.txt` has no `{signal_id}` placeholder. FULL_SYNTHESIS will produce drafts without source_id, relying on Step 6's override (landed in PR #35). Add the placeholder so Opus can set source_id directly; keep the override as belt-and-suspenders.

### Out of scope
- Claim-transactionality / stranding fix (separate brief queued post-Gate-1)
- Bridge, step 1-4, step 7 changes
- SilverFrontmatter schema changes (unless an invariant is genuinely broken — surface to AI Head first)

## Deliverable

- PR on baker-master, branch `step5-stub-schema-conformance-audit-1`, reviewer B3.
- Ship report at `briefs/_reports/B1_step5_stub_schema_conformance_audit_20260422.md`.
- Report sections required:
  - Field conformance matrix (table: field → stub type → schema type → coerces? → notes)
  - Invariant enumeration with per-branch satisfaction proof
  - Error-handler robustness fix summary
  - Test coverage matrix (field × branch × expected outcome)
  - Full `pytest` run output (no "by inspection" — memory rule ratified 2026-04-21)

## Constraints

- **Effort: L (half-day OK).** Comprehensive audit beats another single-line patch.
- Migration-vs-bootstrap DDL rule: N/A for this scope (no columns). If scope expands, apply rule.
- No touch to claim logic, bridge, step1-4, step7.
- Follow `feedback_no_ship_by_inspection.md` — full `pytest` output in the ship report. No skipped runs.
- **Timebox: 4 hours.** If you hit 4h without a ship-ready PR, escalate to AI Head.

## Working dir

`~/bm-b1`. `git checkout main && git pull -q` before starting.

— AI Head
