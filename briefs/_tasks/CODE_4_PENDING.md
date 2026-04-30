# CODE_4 — PENDING (CORTEX_CONFIG_DIRECTIVES_SCHEMA_1 — Brief 4, learning loop schema)

**Status:** PENDING — dispatched 2026-04-30 by AI Head A (App)
**Brief:** `briefs/BRIEF_CORTEX_CONFIG_DIRECTIVES_SCHEMA_1.md` (now on main, PR #111 merged)
**Builder:** B4
**Reviewer:** B1 second-pair-of-eyes (trigger-class: schema migration + cross-capability state writes)
**Priority:** CRITICAL (Director priority pivot 2026-04-30 — learning loop is priority)
**ETA:** 2026-05-06 (target this sprint; ship the schema + bootstrap hook)

## Task summary

Build the directives schema + per-matter directive registry + helpfulness counters + bootstrap hook. This is Brief 4 of the ACE direction (architect-reviewed, 826 lines spec, post-fix hardening: cross-matter scope check, sweep idempotency transactional wrap, APScheduler primitive specified).

You have direct context from BOOTSTRAP_V2_GOLD_SKIP_1 (PR #107 — gold.md skip) — the schema bootstrap hook here ships into the same `scripts/bootstrap_matter.py` you already worked on.

## Q1 flip ratification

Brief 4 ships FIRST (schema + migration + bootstrap hook), Brief 3 (Reflector consumer) ships AFTER.

## Key spec points (per architect-review pass)

- DB schema: per-matter directives with id format, frontmatter Option C (validator-conformance: type/section/voice/etc).
- Cross-matter citation hardening: WHERE matter_slug = %s scope check; _global-* ids passthrough.
- Sweep idempotency: counter increment + cortex_phase_outputs marker in single transaction (ON CONFLICT DO NOTHING). Brief 4 §3.1 ships supporting partial unique index.
- Bootstrap hook: schema auto-provisions on every new matter via scripts/bootstrap_matter.py (live-organism per Director).
- baker_actions audit row per CLAUDE.md hard rule.

## Dispatch

```
git checkout main && git pull --ff-only origin main
git checkout -b b4/cortex-config-directives-schema
# read briefs/BRIEF_CORTEX_CONFIG_DIRECTIVES_SCHEMA_1.md (826 lines, dense, architect-reviewed)
# implement schema + migration + bootstrap hook + tests
# pre-pytest re-checkout ritual
# PR open with grep proof + pytest output in body
```

## Trigger-class

Cross-capability state writes (DB schema migration + per-matter state). B1 second-pair-of-eyes review BEFORE AI Head A merges.

## Coordination

- Brief 3 build (CORTEX_PHASE6_REFLECTOR_1) is queued for after Brief 4 ships per Q1 flip.
- After Brief 4 ships: AI Head A may dispatch you OR another B-code on Brief 3 build.

## Previous task (closed)

PR #107 (BOOTSTRAP_V2_GOLD_SKIP_1) merged 2026-04-30 with B1 PASS verdict.
