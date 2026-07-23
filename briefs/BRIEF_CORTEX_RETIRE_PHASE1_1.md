# BRIEF: CORTEX_RETIRE_PHASE1_1 — retire Cortex cycle service (guard, sentinel off, stuck rows closed)

## Context

Director ratified Cortex retirement 2026-07-23 (charter §4 prerogative) — decision memo:
`briefs/_plans/CORTEX_RETIREMENT_MEMO_2026-07-23.md`. Evidence: 38 cycles ever, last 2026-05-20,
64 days zero demand; matter desks + airport process superseded it. Phase 1 = make retirement
explicit and safe WITHOUT code excision (that is Phase 2, separate brief after soak).

### Surface contract: N/A — backend-only retirement guard; no new clickable surface (existing dashboard Cortex panels keep read-only history).

## Estimated time: ~1.5h
## Complexity: Low-Medium
## Prerequisites: none (main @18821644 or later)

## Harness V2

- **Context Contract:** inputs = memo + the route/line map below; outputs = one branch on
  baker-master with guard + sentinel disable + migration + test, receipt with repo+branch+sha.
  Builder reads only the files listed under Files Modified.
- **Task class:** production backend change, reversible (env-flag guard), one repo.
- **Done rubric (done-state class: gated-merge):** AC 1-5 verified by builder + codex gate PASS
  → lead merges → Render deploys → lead runs live 410 probe. Builder-verified alone ≠ done.
- **Gate plan:** codex seat gate, cite repo+branch+sha (never PR numbers); reviewer must curl
  the guarded routes locally (410 body) and run the touched tests, not code-shape only.

## Fix 1: retirement guard on cycle-starting surfaces

### Problem
Cortex is retired by Director decision but three surfaces can still start cycles:
- `POST /api/cortex/trigger` — `outputs/dashboard.py:8188`
- `POST /api/cortex/run` — `outputs/dashboard.py:8244`
- gate-decide fire path — `_cortex_gate_fire_cycle` continuation after `GET /api/cortex/gate/decide` (`outputs/dashboard.py:8976`, fire helper near `:9076`)

### Current State
All three call `orchestrator.cortex_runner.maybe_run_cycle` (`orchestrator/cortex_runner.py:211`).
Read-only routes (`GET /api/cortex/events:7656`, `stats:8113`, `lint:8066`) stay untouched.

### Engineering Craft Gates
- Diagnose: N/A — no bug; decision execution.
- Prototype: N/A — mechanism conventional (env-flag guard).
- TDD: applies — write the test first: guarded POST routes return 410 with body
  `{"detail": "cortex_retired"}` when flag on (default ON); flag off restores old behavior.

### Implementation
1. Add module-level helper in `outputs/dashboard.py` (near other env reads):
   `def _cortex_retired() -> bool: return os.getenv("CORTEX_RETIRED", "true").strip().lower() == "true"`
   — DEFAULT TRUE (retired is the new normal; flag exists only as rollback).
2. At the TOP of `trigger_cortex_cycle`, the `/api/cortex/run` handler, and
   `_cortex_gate_fire_cycle`: if `_cortex_retired()`: raise
   `HTTPException(status_code=410, detail="cortex_retired")` (in `_cortex_gate_fire_cycle`,
   log + return instead of raise — it runs as a background continuation and must never crash a
   response; verify its actual call pattern first and match it).
3. Disable the stuck-cycle sentinel: find where `triggers/cortex_stuck_cycle_sentinel.py` is
   scheduled (grep its import/registration in `outputs/dashboard.py` startup or poller wiring —
   verify, don't assume) and gate its registration on `not _cortex_retired()`.
4. Migration (new file, `migrations/` convention): close the 2 stuck rows —
   `UPDATE cortex_cycles SET status = 'rejected' WHERE status = 'tier_b_pending'` with a
   comment citing the retirement memo. Wrap per migration conventions; LIMIT-free UPDATE is
   acceptable here only because the WHERE is a terminal-state sweep (2 rows verified 2026-07-23);
   state rowcount in receipt.
5. Do NOT touch `orchestrator/cortex_*` modules themselves — Phase 2 scope.

### Key Constraints
- `cortex_cycles` / `cortex_phase_outputs` tables: never dropped, never schema-changed.
- Read routes keep serving history (dashboard panels must not 500).
- All new code paths try/except per repo hard rule; guard failure must fail CLOSED (410).
- No edits to applied migrations — new migration file only.

### Verification
- Local: `curl -X POST .../api/cortex/trigger` → 410 `cortex_retired`; same for `/run`.
- `pytest tests/ -k cortex` green (update any test that asserted trigger success — mark the
  old behavior tests as flag-off variants, don't delete).
- Migration dry-run locally per repo migration flow; rowcount = 2.
- Render restart survival: default-true env read at call time — works with NO env var set.

## Files Modified
- `outputs/dashboard.py` — `_cortex_retired()` helper + 3 guards + sentinel registration gate
- `migrations/<next>_close_stuck_cortex_cycles.sql` (or .py per convention) — 2-row closeout
- `tests/` — new 410 test + flag-off variants of existing trigger tests

## Do NOT Touch
- `orchestrator/cortex_*` — Phase 2
- `migrations/` applied files — append-only
- GET cortex routes — history stays readable
- `baker-vault/` anything

## Quality Checkpoints
1. 410 on all three cycle-starting surfaces, default env (no var set).
2. `CORTEX_RETIRED=false` restores old behavior (rollback path proven by test).
3. Sentinel not registered when retired (no stuck-cycle bus noise).
4. Dashboard Cortex history panels still render (no 500s).
5. Receipt cites repo+branch+sha, ls-remote confirmed, migration rowcount stated.

## Verification SQL
```sql
SELECT status, count(*) FROM cortex_cycles GROUP BY status ORDER BY 2 DESC LIMIT 10;
-- expect: tier_b_pending = 0 after migration; totals otherwise unchanged (38)
```
