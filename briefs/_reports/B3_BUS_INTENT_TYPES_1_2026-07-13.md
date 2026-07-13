# Ship report — BUS_INTENT_TYPES_1

- **Builder:** b3 (2026-07-13)
- **Dispatch:** lead #10711 (acked/claimed #10713). Brief `~/bm-b3/briefs/BRIEF_BUS_INTENT_TYPES_1.md` @f9a3333a + lead ruling fold @654ff8eb (reply-case = command). Effort: high.
- **Repo/PR:** brisen-lab — [PR #133](https://github.com/vallen300-bit/brisen-lab/pull/133), branch `b3/bus-intent-types-1`, rebased onto post-#130 `origin/main` @661bebd per the sequencing rider (lead GO #10729).
- **Gate:** G1 self-verify PASS → codex bus gate (`review/pr-133`, effort=medium) → lead merge → deploy → deputy live drill + `POST_DEPLOY_AC_VERDICT v1` + HOLD #10422 release.
- **Class:** backend-contract (additive column + server-derive + read-surface exposure). Live fleet drill AC required (compile-clean ≠ done — Lesson #8); deputy-owned post-merge.

## What shipped

A single coarse Command/Event `intent` field, derived server-side from `kind` and stamped on the authoritative `brisen_lab_msg` row exactly as `execute_obligation` is. It is the charter-nameable scope marker ARM's unacked-SLO alarm arms on (releases deputy-codex charter HOLD #10422) and the typed zero-silent-loss marker (asserted on commands, droppable on events).

- **db.py** — `intent TEXT` on `brisen_lab_msg`: CREATE-TABLE column + catalog-guarded idempotent `bootstrap()` ADD COLUMN (brisen-lab has **no** `migrations/` dir — inline bootstrap pattern, codex #3852 F2) + one-shot `kind→intent` backfill `UPDATE ... WHERE intent IS NULL` (nullable, no default → no table rewrite). Plus `m.intent` on the `/delivery/status` telemetry SELECT + cols tuple (additive read-side; WHERE unchanged = `R1_TRACKED_DISPATCH_SQL`).
- **bus.py** — `_derive_intent(kind)` helper co-located with `EXECUTE_OBLIGATION_KINDS`; derived at POST next to `execute_obligation`; added to the INSERT column list + values; echoed on the POST response; serialized on the `/msg` list read + both by-id reads.
- **tests/test_bus_intent_types.py** — 7 tests.

## Reconciliation (the load-bearing constraint — lead #10622)

`VALID_KINDS` / `EXECUTE_OBLIGATION_KINDS` / `_is_delivery_tracked` / `_is_assignment` **untouched**. `intent` is a label, not a gate; strict nesting `assignment ⊂ delivery-tracked ⊂ command` asserted in the no-double-gate unit test. Reply-case = command per lead fold #10665 (obligation-bearing; parent_id set → never an `_is_assignment`, so never double-warned). Client-supplied `intent` is never read → overridden by construction.

## Two brief-vs-repo reconciliations (lead-accepted #10725)

1. Table is `brisen_lab_msg`, not `bus_messages` (brief SQL illustrative).
2. brisen-lab has no `migrations/` dir → the "migration" is the inline catalog-guarded bootstrap ADD COLUMN + backfill, not a new migration file.

## Tests (literal, isolated throwaway local PG)

- `tests/test_bus_intent_types.py` — **7 passed** post-rebase: derivation table (6 kinds + None); strict no-double-gate nesting incl. the reply-case; intent stamped on POST + echoed; client-supplied intent overridden (server wins, verified in stored row); intent on `/msg` list + by-id reads; legacy backfill labels every NULL row (0 left unlabeled); `/delivery/status` surface carries `intent=command`.
- **Full suite: 26 failed / 612 passed / 1 skipped** = **identical to the true post-#130 baseline** (origin/main `bus.py`+`db.py` with the intent test file ignored → 26/612). **Zero new failures.** The 26 are pre-existing autowake / wake-topic-gate / identity module-global-state cross-file isolation failures (documented; each reproduces standalone, unrelated to this additive change). My 7 tests bring the full green run to 619 passed.
- Isolation discipline: every run used a per-run `createdb -h /tmp` / `dropdb` throwaway local Postgres (never the shared Neon test DB) per the shared-test-DB corruption lesson.

## Rebase note

Built pre-#130, held the gate per the rider, rebased onto post-#130 main after lead GO #10729. One conflict (bus.py `/msg` list SELECT): #130 added `COUNT(*) OVER () AS _match_total`, I added `intent` — resolved by keeping both. All other intent insertions auto-merged. Re-verified green post-rebase.

## Done rubric

1. `intent ∈ {command,event}` derived server-side, stamped, client value never trusted ✅
2. additive migration + backfill; existing kinds/gates byte-unchanged; the four named symbols untouched ✅
3. ARM/observability surface exposes the label; no new gate, no double-warning (proven by the nesting test) ✅
4. reply-case resolved with lead (fold #10665), not silently averaged ✅
5. `intent` queryable on `/msg` + `/delivery/status` ✅
6. live drill AC + `POST_DEPLOY_AC_VERDICT v1` + HOLD #10422 release — **post-merge, deputy-owned** ⏳
