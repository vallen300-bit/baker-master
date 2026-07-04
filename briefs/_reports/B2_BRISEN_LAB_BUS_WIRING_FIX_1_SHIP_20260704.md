# B2 SHIP REPORT — BRISEN_LAB_BUS_WIRING_FIX_1

**Date:** 2026-07-04
**Worker:** b2 · **Dispatcher:** lead (#5219, ownership confirmed #5225)
**Brief:** baker-master main @0210860 `briefs/_tasks/BRISEN_LAB_BUS_WIRING_FIX_1.md`
**Origin:** BRISEN_LAB_BUS_WIRING_AUDIT_1

## PRs
- **baker-vault #139** — `b2/bus-wiring-registry` @ 7485548 (registry alias source, single file).
- **brisen-lab #92** — `b2/brisen-lab-bus-wiring-fix` @ fec70c9 (regen + code + tests + cleanup script).
- **Merge order: #139 first**, then #92 (regenerated file must match the merged registry).

## What shipped (all four tasks)
- **T1 — post-time recipient validation + alias canonicalization.**
  - Registry (`agent_registry.yml`, PR #139): cowork-ah1+=cowork, origination-desk+=origination,
    ao-desk+=ao, movie-desk+=movie, baden-baden-desk+=[bb, bb-desk, baden-baden]. Alias-only.
  - Regenerated `agent_identity_generated.py` (+`.js` +wake-listener) via the generator — not hand-edited.
  - `bus.py`: `RECIPIENT_CANONICAL` map built from AGENTS + VALID_BUS_SLUGS + SYSTEM_RECIPIENT_SLUGS
    + `*`; `canonical_recipient()`; validation in `_post_msg_inner` after the to_terminals type guard:
    unknown → 400 `unknown_recipient_slug:<slug>`, alias → canonical, order-preserving dedup.
    Bus-disabled agents (brisen-desk) rejected (audit recommendation). `*` broadcast admitted.
- **T2 — daemon+dispatcher authority rows.** `db.py bootstrap()` seeds both at level 0 derived from
  SYSTEM_RECIPIENT_SLUGS (director excluded — already seeded level 3), ON CONFLICT DO NOTHING. Idempotent.
- **T3 — TTL sweep.** `app.py` `_msg_ttl_days()` + `_msg_ttl_sweep_once()` + daily `_msg_ttl_sweep_loop()`
  (registered in `_startup`). Soft-deletes (`deleted_at`) unacked dispatch/broadcast older than
  `BRISEN_LAB_MSG_TTL_DAYS` (default 30). NEVER ratify_required, NEVER director-addressed. otel span + log.
- **T4 — stranded-message cleanup.** `scripts/cleanup_stranded_ghost_msgs.py`: dry-run default / `--apply`;
  canonicalizable ghosts re-addressed in place, dead targets (matter-*, ticketing-desk, brisen) soft-deleted
  with reason, AC5 check printed. No hard deletes. **Runs post-deploy (lead-gated), not yet executed against prod.**
- **Out-of-scope note:** one-line `identity = slug header only; keys decorative` comment at the authz
  resolution site (`authz.py`) — no behavioral change; key/auth model deferred per Director.

## Constraints honored
Additive + reversible; soft-delete only; migration idempotent; reuses generated registry constants (no
inline slug list); regenerated file not hand-edited; all DB calls in try/except.

## Tests (literal pytest, against Neon `TEST_DATABASE_URL_BRISEN_LAB`)
- `tests/test_bus_recipient_validation.py` (AC1 ghost→400 + nothing inserted; AC2 alias→canonical stored;
  disabled-agent reject; multi-recipient reject; wildcard admit; dedup) + `tests/test_msg_ttl_sweep.py`
  (AC4 sweep, safety exclusions, idempotency, env default): **18 passed** (188s).
- Regression (director-block, a3_a8_a9_bus, authz_factory, inbox_read_authz, agent_identity_generated,
  a2_schema): **111 passed** (788s). No regressions.

## Acceptance criteria
- AC1 ✅ ghost → 400, nothing inserted (test).
- AC2 ✅ alias → 200, stored canonical (test).
- AC3 ✅ daemon+dispatcher authority rows seeded level 0, existing untouched (T2 + schema tests green).
- AC4 ✅ TTL sweep expires >30d unacked, leaves <30d + ratify_required untouched (test).
- AC5 ⏳ stranded-msg cleanup ⊆ VALID_BUS_SLUGS ∪ {'*'} — verified post-deploy by the cleanup script.
- AC6 ✅ existing bus tests green + new AC1/AC2/AC4 tests added.
- AC7 ⏳ live POST_DEPLOY_AC_VERDICT on the bus — emitted after merge/deploy/cleanup.

## Post-deploy (after #139 + #92 merge + Render redeploy of brisen-lab)
1. Run `DATABASE_URL=<prod> python3 scripts/cleanup_stranded_ghost_msgs.py` (dry-run) → review plan.
2. Re-run `--apply` → verify AC5 clean.
3. Emit `POST_DEPLOY_AC_VERDICT v1` to lead (AC1/AC2/AC4 code-live + AC5 cleanup result).
