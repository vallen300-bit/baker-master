# LAB_GLANCE_ZERO_COUNT_FIVE_SEATS_1 — glance reports 0 unacked for 5 seats that have unacked dispatches

**Owner:** b1 · **Dispatcher:** lead · **Date:** 2026-07-20 · **Repo:** brisen-lab
**Class:** bug / diagnose-first (server-side)

## Context

**Context Contract:** read `briefs/_reports/FLEET_WAKE_SMOKE_2026-07-20.md`
finding 1 (+ 07-19 report finding 2), the Lab daemon glance endpoint code and
its unacked/wake-obligation count SQL, and the recipient/alias registry the
query joins against. Nothing else needed.
**Task class:** server-bug, diagnose-before-fix (Matt Pocock Diagnose gate —
no fix commit until root cause is reproduced in a failing test).
**Done-state class:** deterministic — failing test turned green + live AC.
**Gate plan:** codex exact-HEAD gate on cumulative diff; live AC = glance
returns correct non-zero counts for a staged unacked dispatch on each of the
5 seats; POST_DEPLOY_AC_VERDICT to lead.

## Problem

Two consecutive daily smokes (07-19, 07-20): Lab glance returns
`unacked_count=0, wake_obligation_count=0` for **movie-desk,
origination-desk, publisher, researcher, russo-ai** while those seats hold
verifiably unacked `kind=dispatch, execute_obligation=true` rows
(`acknowledged_at: null` via `/msg/{slug}/{id}`; evidence msg #13884).
Consequence: the wake pipeline sees no obligation → no wake fires → seats sit
silent until hand-chased. 07-20 smoke proved it is SERVER-side: controller
now consumes server counts directly, so the zero originates in the Lab glance
query/cache. Same 5 recipients both days = deterministic, recipient-dependent
— prime suspects: recipient-matching in the count SQL (array membership /
alias-vs-slug mismatch), a stale per-recipient cache row, or a filter that
excludes these seats' message kinds.

## Diagnose (mandatory first, commit findings before any fix)

1. Reproduce live: stage an unacked dispatch to one affected + one healthy
   seat; capture glance SQL result vs raw table truth for both.
2. Explain the 5-seat pattern: what do these recipients share (slug format,
   alias table rows, seat class, registration date) that healthy seats don't?
3. Write the failing test that captures the root cause BEFORE fixing.

## Files Modified

- Lab daemon glance endpoint / count query (exact file per diagnosis).
- Regression test alongside existing daemon tests.
- NO controller/listener changes — those layers were proven correct 07-20.

## Verification

- Failing test reproduces the zero-count against seeded rows for an affected
  slug; green after fix.
- Full lab pytest suite green with TEST_DATABASE_URL set — 0 skipped
  (skipped-all is a FAIL per lead's 07-20 gate note).
- Live AC on deployed Lab: staged dispatch → glance non-zero within one poll
  cycle for all 5 seats; wake fires end-to-end on at least one.

## Quality Checkpoints / Acceptance criteria

1. Root-cause note committed (diagnosis, not guess) before the fix commit.
2. All 5 seats show correct counts live; healthy seats unchanged.
3. Codex gate PASS on exact HEAD; POST_DEPLOY_AC_VERDICT posted to lead.
4. If cache-layer: eviction/invalidations covered by test, not manual flush.
