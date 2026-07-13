# CHECKPOINT — BUS_INTENT_TYPES_1

attempt: 1
seat: b3 (fresh low-context seat, dispatch #10711, claimed bus #10713)
branch: b3/bus-intent-types-1 (created off origin/main @79ae875, brisen-lab; pushed)
created: 2026-07-13
updated: 2026-07-13

## Brief id
BUS_INTENT_TYPES_1 — brief `~/bm-b3/briefs/BRIEF_BUS_INTENT_TYPES_1.md` @f9a3333a on main
+ lead ruling fold @654ff8eb (reply-case = command, not deferred; regression included).
Dispatch: lead bus #10711 (acked #10711, claimed #10713). Effort: high. Repo: brisen-lab.

## STATUS: REBASED + GREEN + PR OPENED — awaiting codex bus gate → lead merge
- brisen-lab PR #133 (branch `b3/bus-intent-types-1` @cdd3e0c, rebased onto post-#130
  origin/main @661bebd per lead GO #10729). Force-pushed.
- SEQUENCING RIDER CLEARED (#10729): #130 merged @661bebd. Rebase had ONE conflict (bus.py
  /msg list SELECT: #130 added `COUNT(*) OVER () AS _match_total`, I added `intent` — kept
  both). All other intent insertions auto-merged.
- G1 self-verify PASS post-rebase: 7/7 new intent tests green on isolated throwaway PG; full
  suite 26 failed/612 passed = IDENTICAL to the true post-#130 baseline (origin/main
  bus.py+db.py, intent test file ignored → 26/612). Zero new failures. The 26 are pre-existing
  autowake/wake-topic/identity module-global-state cross-file isolation failures.
- Ship report: briefs/_reports/B3_BUS_INTENT_TYPES_1_2026-07-13.md.

## What's built (all additive; label, not a gate)
- db.py: `intent TEXT` on brisen_lab_msg — CREATE TABLE col + catalog-guarded idempotent
  bootstrap() ADD COLUMN (brisen-lab has NO migrations/ dir, codex #3852 F2) + one-shot
  backfill UPDATE (kind→intent CASE). Nullable, no default → no table rewrite.
- db.py: `m.intent` added to the /delivery/status telemetry SELECT + cols tuple (additive
  read-side; WHERE unchanged = R1_TRACKED_DISPATCH_SQL, no new gate).
- bus.py: `_derive_intent(kind)` helper co-located with EXECUTE_OBLIGATION_KINDS; derived at
  POST next to execute_obligation; added to INSERT column list + values; echoed on POST
  response; serialized on /msg list read + both by-id reads.
- tests/test_bus_intent_types.py (7 tests).

## Reconciliation honored (lead #10622 "reconcile, don't double-gate")
VALID_KINDS / EXECUTE_OBLIGATION_KINDS / _is_delivery_tracked / _is_assignment UNTOUCHED.
Strict nesting assignment ⊂ delivery-tracked ⊂ command asserted in the no-double-gate unit
test. Reply-case = command per fold #10665 (obligation-bearing; never an _is_assignment).

## Two brief-vs-repo reconciliations surfaced to lead (not silently picked)
1. Table is `brisen_lab_msg`, not `bus_messages` (brief's SQL was illustrative).
2. brisen-lab has NO migrations/ dir → the "migration" is the inline catalog-guarded
   bootstrap ADD COLUMN + backfill (repo convention), not a new migration file.

## Next concrete step
Wait for lead to signal b1 #130 merged. THEN: `git fetch origin main` → rebase
b3/bus-intent-types-1 onto post-#130 main → re-apply the intent derive + INSERT-block
changes against b1's rewritten region → re-run 7/7 intent tests + full suite on isolated
throwaway PG (confirm still baseline) → open brisen-lab PR → request codex bus gate
(effort=medium) → lead merge → deploy → deputy live drill + POST_DEPLOY_AC_VERDICT v1 +
confirm HOLD #10422 release. Ship report: briefs/_reports/B3_BUS_INTENT_TYPES_1_2026-07-13.md
(write on PR open).

## Test-DB note
Local Postgres on /tmp:5432. Isolated throwaway DB: `createdb -h /tmp <db>`,
`TEST_DATABASE_URL=postgresql://localhost/<db>?host=/tmp`, run, `dropdb -h /tmp <db>`.
NOT the shared Neon test DB. Baseline dirty count = 26 pre-existing autowake/identity
isolation failures — diff against that (adding the new test file shifts collection order
and can surface a 27th flaky autowake failure; that is NOT a regression — proven by the
--ignore=tests/test_bus_intent_types.py run returning 26/603).

## Claim discipline
Successor claims by the `attempt:`-bump commit on THIS checkpoint. If `attempt` already
bumped by another session, stand down. At `attempt >= 3`, stop resuming + escalate to lead
with this path + last error.
