# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2
**Task posted:** 2026-04-21 evening (post PR #34 merge — YAML layer fixed, next layer surfaced)
**Status:** OPEN — STEP5_STUB_SOURCE_ID_TYPE_FIX_1

---

## Context

PR #34 (YAML frontmatter escape) merged + deployed. Recovery flips rolled the 24 Opus-failed rows back into the pipeline. 4 rows successfully advanced from `pending` through Steps 1-5 and landed at `awaiting_finalize`. Step 6 now fails on a **different error class** — Pydantic validation on the finalize input:

```
WARN  finalize           source_id: Input should be a valid string
ERROR pipeline_tick       unexpected exception in _process_signal_remote: connection already closed
```

Zero vault commits. Gate 1 still blocked on Step 6 finalize.

## Root-cause pointer (verify)

`kbl/schemas/silver.py:139` — `SilverFrontmatter.source_id: str` (required, strict).

`kbl/steps/step5_opus.py:425` — stub writer sets:
```python
"source_id": inputs.signal_id,
```

`signal_id` is `int` (SERIAL PRIMARY KEY on `signal_queue.id`). Pydantic v2 with strict mode rejects int-for-str. YAML `safe_dump({...'source_id': 17})` → `source_id: 17` → YAML load → `int` → Pydantic rejects.

This bug was always present but **masked by the earlier YAML parse error** (PR #34 target). Each layer fix reveals the next.

Likely present in both stub writers (`_build_skip_inbox_stub`, `_build_stub_only_stub`) and potentially in the FULL_SYNTHESIS path too — check all three.

## Scope

1. **Fix direction (verify first):** cast `source_id` to `str` at the producer side in Step 5 stub writers — `str(inputs.signal_id)`. Single-word change. Also verify FULL_SYNTHESIS path writes `source_id` as str (Opus output); if not, fix there too.
2. **Schema-side alternative:** if there's a reason signal_id should stay int in the frontmatter, adjust `SilverFrontmatter.source_id` to `int` or union `str | int` with coercion validator. **Not recommended** — frontmatter lives in YAML docs; string form is canonical.
3. **Grep adjacent fields** in the stub dicts for other type mismatches vs. `SilverFrontmatter` schema — the YAML fix also unlocked visibility of these. Any field typed differently at the producer vs. the schema is a ticking bomb.
4. **Regression tests:**
   - Stub writer round-trip: build stub frontmatter → `yaml.safe_dump` → `yaml.safe_load` → `SilverFrontmatter.model_validate(...)` — assert passes for both `_build_skip_inbox_stub` and `_build_stub_only_stub`.
   - Optional: property test with random `signal_id` values (int, large int, 0) — all should produce schema-valid frontmatter.
5. **Connection-already-closed cascade:** this is downstream noise — finalize raises, orchestrator's except path tries to use the connection after rollback closed it. Leave alone for this PR; log-noise cleanup is post-Gate-1.

## Recovery (AI Head handles post-merge)

- 20 rows at `awaiting_finalize` will retry automatically once the fix deploys (Step 6 has built-in retry via `finalize_retry_count`).
- If retry doesn't fire, AI Head flips with a recovery UPDATE (Tier B auth separate).

## Deliverable

- PR on baker-master, branch `step5-stub-source-id-type-fix-1`, reviewer B3.
- Ship report at `briefs/_reports/B2_step5_stub_source_id_type_fix_20260421.md`.
- Include: root-cause confirmation, which stub writers were touched, whether FULL_SYNTHESIS path was affected, regression test output, adjacent-field type audit result.

## Cross-reference

Today's drift cluster now 5 bugs (four column/type + one encoding). This source_id bug is a **6th class: producer-vs-schema type drift**. Add to post-Gate-1 `STEP_SCHEMA_CONFORMANCE_AUDIT_1` — Pydantic model vs. dict-producer type-conformance check would kill this class.

## Constraints

- **XS effort (<30 min).** Single-field cast likely.
- No schema changes to `SilverFrontmatter`.
- No bridge / pipeline_tick / step1-4 changes.
- Migration-vs-bootstrap DDL rule: N/A (no DB columns).
- **Timebox: 30 min.**

## Working dir

`~/bm-b2`. `git checkout main && git pull -q` before starting (last dispatch got confused on feature branch).

— AI Head
