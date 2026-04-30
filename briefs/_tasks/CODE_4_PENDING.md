# CODE_4 — PENDING (CORTEX_PHASE6_REFLECTOR_1 — Brief 3, Reflector consumer)

**Status:** PENDING — dispatched 2026-04-30 by AI Head A
**Brief:** `briefs/BRIEF_CORTEX_PHASE6_REFLECTOR_1.md` (929 lines, architect-reviewed; on main per PR #111 merge)
**Builder:** B4
**Reviewer:** B1 second-pair-of-eyes (B4 builder-conflict caveat — Brief 3 consumes Brief 4's schema which B4 just shipped, so a non-builder reviewer is required)
**Priority:** CRITICAL (Director priority pivot 2026-04-30 — learning loop is THE priority; channels-last directive elevated Briefs 3+4)
**Trigger-class:** TIER A — modifies Phase 4 propose-phase prompt + adds new Phase 6 module + new external write surface (vault). AI Head B cross-lane ratify on top of architect-review pass pre-merge.
**ETA:** 2026-05-06 (target this sprint)

## Why B4 again

You shipped Brief 4 just now (PR #125 + post-review fixes PR #127 merged 2026-04-30). The Reflector you're about to build:

- Reads `cortex_phase_outputs` looking for `phase='archive', artifact_type='reflector_complete'` markers — the partial unique idx **you just shipped** is what makes its `INSERT ... ON CONFLICT DO NOTHING` actually idempotent.
- Increments `helpful_count` / `harmful_count` columns on `cortex_directives` — the table **you just shipped**.
- Logs untraceable proposals to `prompt_review_queue` — the table **you just shipped**.

Continuity bonus is real. Builder-conflict caveat handled by routing review to B1.

## Key spec points (verbatim from architect-reviewed brief — re-read in full)

- **§0 simplification preamble** — V1 ships Triaga-only signal source. Cycle-outcome inspector + ClickUp aux deferred to V2 with documented trigger criteria.
- **Q1 flip ratification** — Brief 3 ships AFTER Brief 4 (✅ Brief 4 done; this is the back-half).
- **Q2 counter math** — `helpful / (helpful + harmful)`, 14-day TTL, ignore stale + pending. Director-ratified.
- **Q3 slugs.yml** — runtime-read, filter `status != retired` (matches Brief 4 migrator pattern).
- **A — counter-signal hierarchy** — V1 Triaga only (ClickUp aux V2 if Triaga coverage <50%).
- **B — citation provenance** — counter routing follows directive-id, not write surface.
- **C — Brief 5 contract** — DEFERRED. Brief 3 V1 ships ClickUp write code path env-gated OFF (`REFLECTOR_CLICKUP_WRITE=false` default). Vault write to `proposed-config-deltas.md` is sole active write target. ClickUp infrastructure stays dormant in code; activation pending Brief 5 V2+.
- **Cross-matter citation hardening** — Reflector cites `[directive: <matter>-<topic>-<NNN>]` for matter-scoped or `[directive: _global-<NNN>]` for cross-matter. Schema accepts `matter_slug='_global'` (your Brief 4 `_global` bypass note in `migrations/20260430_cortex_directives.sql` header documents the regex caveat — read it).
- **Sweep idempotency** — counter increment + `cortex_phase_outputs` marker in single transaction. Brief 4's partial unique idx `idx_cortex_phase_outputs_reflector_complete` is the substrate. **Use it.**
- **`baker_actions` audit row** — every Reflector write audits per CLAUDE.md hard rule.
- **Phase 4 propose-prompt edit** — touches `orchestrator/cortex_phase3_synthesizer.py` (loads `synth_prompt` from `capability_sets` table or `_DEFAULT_SYNTH_PROMPT`). Read brief §3.X (TBD precise section) for the exact prompt-template change.

## Dispatch ritual

```
cd ~/bm-b4
git fetch origin
git checkout main
git pull --ff-only origin main
git checkout -b b4/cortex-phase6-reflector
# read briefs/BRIEF_CORTEX_PHASE6_REFLECTOR_1.md (929 lines, dense, architect-reviewed)
# implement Phase 6 module + Phase 4 prompt edit + tests
# pre-pytest re-checkout ritual
# PR open with grep proof + pytest output in body
```

## Architect-review yardstick

Same standard applied to Brief 4 (PR #125 → REQUEST_CHANGES → PR #127 → APPROVE). Specifically watch for:

- **Spec-vs-reality mismatches** — your Brief 4 hit one (slugs.yml has no `name:` keys, only `description`). Brief 3 prompts you about Phase 4 prompt edits — verify the Phase 4 entry point is actually where the brief claims it is. Don't trust the brief's file:line refs blindly; grep first.
- **Counter math edge cases** — denominator zero (helpful=0, harmful=0) — what does `helpful/(helpful+harmful)` return? Decide explicitly (NULL? skip?). Document.
- **Sweep idempotency under retries** — `INSERT ... ON CONFLICT DO NOTHING` against the partial unique idx works for one cycle, but what about cross-cycle reflector runs against the same matter? Read the partial idx WHERE clause carefully.
- **`_global` citation handling** — `KEBAB_SLUG_RE` rejects underscore prefix. Your Brief 4 migration note flagged this. Brief 3 implementer (you) must handle it; don't slip.

## Coordination

- After your push, AI Head A architect-review pass runs (will spawn `code-architecture-reviewer` subagent).
- B1 second-pair-of-eyes review chains (B4 builder-conflict).
- AI Head B cross-lane ratify on top per Tier A.
- AI Head A merges.
- Mailbox flips to COMPLETE.

## Previous task (closed)

Brief 4 (CORTEX_CONFIG_DIRECTIVES_SCHEMA_1) shipped via PR #125 + post-review fixes PR #127, both merged 2026-04-30. Schema, partial unique idx for THIS Brief's reflector sweep, bootstrap hook, run-once migrator all live on main.
