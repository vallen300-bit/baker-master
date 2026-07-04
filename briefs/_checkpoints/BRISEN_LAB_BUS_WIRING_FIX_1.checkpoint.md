# CHECKPOINT — BRISEN_LAB_BUS_WIRING_FIX_1

attempt: 1
owner: b2 · dispatched_by: lead (#5219, ownership confirmed #5225) · date: 2026-07-04
brief: baker-master main @0210860 briefs/_tasks/BRISEN_LAB_BUS_WIRING_FIX_1.md
repos: baker-vault (registry PR) + brisen-lab (code PR)
work branch: brisen-lab @ b2/brisen-lab-bus-wiring-fix (off origin/main b0fb768)

## What's DONE (code written + tests green)
- T1 (recipient validation + alias canonicalization):
  - baker-vault registry `_ops/registries/agent_registry.yml`: added aliases
    cowork-ah1+=cowork, origination-desk+=origination, ao-desk+=ao, movie-desk+=movie,
    baden-baden-desk+=[bb,bb-desk,baden-baden]. (5 edits, alias-only.)
  - Regenerated agent_identity_generated.py (+.js +wake-listener) via
    scripts/generate_agent_identity_artifacts.py --write. Diff = alias-only, 3 files.
  - bus.py: RECIPIENT_CANONICAL map (built from AGENTS+VALID_BUS_SLUGS+SYSTEM_RECIPIENT_SLUGS,
    +'*' wildcard) + canonical_recipient(); validation block in _post_msg_inner after
    to_terminals type-guard: unknown→400 unknown_recipient_slug:<slug>, alias→canonical,
    order-preserving dedup. Bus-disabled agents (brisen-desk) rejected.
- T2 (authority rows): db.py bootstrap() seeds daemon+dispatcher at level 0 from
  SYSTEM_RECIPIENT_SLUGS (excludes already-seeded director), ON CONFLICT DO NOTHING.
- T3 (TTL sweep): app.py _msg_ttl_days() + _msg_ttl_sweep_once(conn,ttl_days) +
  _msg_ttl_sweep_loop() (daily, otel span, soft-delete via deleted_at); registered in
  _startup. Only kind IN (dispatch,broadcast), never ratify_required, never director-addressed.
  env BRISEN_LAB_MSG_TTL_DAYS default 30.
- T4 (cleanup): scripts/cleanup_stranded_ghost_msgs.py — dry-run default, --apply writes;
  re-address canonicalizable ghosts in place, soft-delete dead targets, AC5 check. NOT yet
  run against prod (runs post-deploy, lead-gated).
- authz.py: one-line "identity = slug header only; keys decorative" comment (out-of-scope note).
- Tests: tests/test_bus_recipient_validation.py (AC1/AC2 +regressions) + tests/test_msg_ttl_sweep.py
  (AC4). 18 passed (188s). Regression suite (director-block/bus/authz/identity/schema) IN PROGRESS.
- All 5 modified .py compile-clean. Canonicalizer verified standalone (64 entries).

## STATUS (2026-07-04): PRs OPEN — awaiting merge + post-deploy
- Regression suite GREEN: 18 new + 111 post-path regression = all passed. Zero regressions.
- baker-vault PR #139 (b2/bus-wiring-registry @7485548) — registry alias source.
- brisen-lab PR #92 (b2/brisen-lab-bus-wiring-fix @fec70c9) — regen + T1-T4 + tests.
- Merge order: #139 FIRST, then #92 (regenerated file must match merged registry).
- Ship report: briefs/_reports/B2_BRISEN_LAB_BUS_WIRING_FIX_1_SHIP_20260704.md · bus ship-post #5229.

## What's LEFT (post-deploy only — after lead merges BOTH + Render redeploys brisen-lab)
1. Run `DATABASE_URL=<prod op://Baker API Keys/DATABASE_URL/credential> python3
   scripts/cleanup_stranded_ghost_msgs.py` (dry-run) → review plan.
2. Re-run with `--apply` → verify AC5 clean (live recipients ⊆ VALID_BUS_SLUGS ∪ {'*'}).
3. Emit POST_DEPLOY_AC_VERDICT v1 to lead (AC1/AC2/AC4 code-live + AC5 cleanup before/after).

## Creds
Test DB: `op read 'op://Baker API Keys/TEST_DATABASE_URL_BRISEN_LAB/credential'` → export
TEST_DATABASE_URL_BRISEN_LAB. (op session expires; use `op read` form, not `op item get`.)
Prod bus DATABASE_URL for T4: op://Baker API Keys/DATABASE_URL/credential.
Run tests: `cd ~/bm-b2/brisen-lab && python3 -m pytest tests/test_bus_recipient_validation.py tests/test_msg_ttl_sweep.py -q`
