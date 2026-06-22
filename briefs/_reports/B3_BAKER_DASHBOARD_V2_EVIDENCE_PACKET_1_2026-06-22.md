# Ship Report — BAKER_DASHBOARD_V2_EVIDENCE_PACKET_1

**Builder:** B3
**Date:** 2026-06-22
**Branch:** `b3/baker-dashboard-v2-evidence-packet-1` (off `main` @ a174edb)
**PR:** #405 (base `main`) — **MERGE HELD** behind MODEL_LOCK_1 per coordinator
**Commit:** 6c96666
**Dispatch:** bus #3741 + addendum #3748 (deputy / codex-arch), both acked

---

## What shipped

V2 "Verified Operating Room" **Tranche 1** — the durable object model that lets
Baker stand behind a dashboard item. Backend only: schema + service/model layer
+ audited state machine + tests. **No** Today UI, sentinel wiring, or new model
calls (all later tranches).

3 files, +1234 lines:
- `migrations/20260622c_dashboard_v2_evidence_packet.sql`
- `models/verified_items.py`
- `tests/test_verified_items.py`

---

## Done rubric

**1. Which migrations were added?**
One: `20260622c_dashboard_v2_evidence_packet.sql`. Creates `signal_candidates`,
`verified_items`, `verification_events` + 9 indexes (incl. a GIN index on
`verified_items.people` for person-filtered lists). Additive, idempotent
(`IF NOT EXISTS` throughout), runner-safe (single per-file transaction, no
`CREATE INDEX CONCURRENTLY`). Verified against the production runner
(`config.migration_runner.run_pending_migrations`): applies once, re-run returns
`[]` (no drift, no double-apply).

**2. Which service/model functions were added?** (`models/verified_items.py`)
- `create_signal_candidate(...)` — raw-capture staging row.
- `create_verified_item(...)` — durable object (default `state='candidate'`) +
  its creation audit event, atomically.
- `transition_item(item_id, to_state, actor_type, actor_id, …)` — the audited
  core.
- `dismiss_item(...)` / `ratify_item(...)` — thin wrappers over `transition_item`.
- `list_items(state=, matter_slug=, person=, item_type=, limit=)` — filtered read.
- `get_events(item_id)` — audit trail read.
All SQL parameterized; all DB calls wrapped try/except with `rollback()`.

**3. How is every state transition audited?**
`transition_item` runs `SELECT … FOR UPDATE` (read + lock current state) →
`UPDATE verified_items.state` → `INSERT verification_events` → one `commit()`.
A failure rolls back both — there is no code path that mutates state without an
event. Creation also writes a `NULL → candidate` event, so the trail covers
every state the row has ever held. Proven by
`test_audit_and_state_change_share_one_transaction` (state + event count move
together) and the missing-evidence/invalid-transition tests (no half-write —
event count unchanged on rejection).

**4. What required evidence fields block promotion?**
`REQUIRED_EVIDENCE_FIELDS` = `source_refs` (non-empty), `claim`, `confidence`,
`source_trust`, `verification_summary`, `counterargument`. A candidate cannot
enter `verified` if any are missing/blank. Enforced in Python (`transition_item`
fails closed, returns `{"ok": False, "error": "missing_evidence", "detail": […]}`)
**and** by the `verified_items_evidence_packet_required` table CHECK (defence-in-
depth against raw-SQL bypass).

**5. Which tests cover candidate → verified → ratified?**
`test_full_lifecycle_candidate_verified_ratified` — create signal candidate →
create verified_item → promote to verified → ratify (Director), asserting the
3-row ordered audit trail + state/matter/person list filters. Plus
`test_dismiss_with_structured_reason_persists`,
`test_invalid_transition_candidate_to_ratified_rejected`,
`test_promote_blocked_when_evidence_missing`,
`test_db_check_blocks_dismissed_without_reason`,
`test_db_check_blocks_verified_without_evidence`.

**6. How does this avoid overloading `alerts` and `deadlines`?**
Brand-new tables. `verified_items.state` is the V2 verification state; `alerts`
and `deadlines` are untouched (no schema change, no new status values). The
brief's hard rule — "`alerts.status`/`deadlines.status` are not the V2
verification state" — holds: those tables remain low-level operational feeds,
and the V2 contract lives entirely in the new tables.

---

## Acceptance criteria

| AC | Status | Evidence |
|----|--------|----------|
| AC1 additive/idempotent/runner-safe migration | PASS | runner apply + re-apply clean; `IF NOT EXISTS`; no CONCURRENTLY |
| AC2 parameterized storage API (6 fns) | PASS | all 6 present + parameterized + try/except/rollback |
| AC3 transition audit cannot be bypassed | PASS | same-tx FOR UPDATE→UPDATE→INSERT; atomicity test |
| AC4 verified requires evidence packet | PASS | Python gate + table CHECK |
| AC5 ratification actor explicit | PASS | allowlist + non-empty actor_id; candidate→ratified invalid |
| AC6 dismissal reasons structured | PASS | 10-value set; Python gate + table CHECK |
| AC7 source refs internal by default | PASS | no endpoints added; reads return internal refs only |
| AC8 lifecycle + invalid + missing-evidence tests | PASS | see rubric #5 |

---

## Test output

`python3.12 -m pytest tests/test_verified_items.py` (isolated local PG 16 via
throwaway `TEST_DATABASE_URL`):

```
collected 29 items
... 21 pure-logic PASSED, 8 live-PG PASSED ...
============================== 29 passed in 0.27s ==============================
```
(Initial ship was 25; +4 from the codex G-review fold below.)

System python is 3.9 (conftest needs 3.12 syntax) — use `python3.12`. Live-PG
tests gate on `needs_live_pg`; ran against an **isolated** throwaway DB, never
the shared brisen-lab test DB (per standing lesson on concurrent-TRUNCATE
corruption).

---

## codex-arch addendum #3748 — folded

- Model-provenance fields `extraction_model` + `source_model` added to BOTH
  `signal_candidates` and `verified_items`.
- HARD constraint respected: schema **stores** which model ran; this layer
  creates **no** path that promotes Flash-sourced extraction to `verified`
  (promotion gates on evidence completeness, not on a model). The no-Flash
  enforcement bar is left to `MODEL_LOCK_1` (b4 lane) — documented in the
  migration header + module docstring.
- Merge order respected: PR open, **HELD** — no lead-merge request.

---

## codex G-review #3763 (REQUEST_CHANGES) — folded (commit pending)

Both blocking findings fixed on the same branch:

- **Finding 1 — direct `ratified` create bypassed AC5.** `create_verified_item`
  previously allowed `state='ratified'` directly, writing a creation event with
  `actor_type='system'` (an anonymous ratification). Fix: creation is now
  restricted to `CREATE_STATES = {candidate, verified}`; `ratified`/`dismissed`
  are reachable ONLY via `transition_item`, which enforces the ratify-actor
  allowlist (AC5) and the structured dismiss reason (AC6). New tests:
  `test_create_states_vocab`, `test_create_rejects_direct_ratified`,
  `test_create_rejects_direct_dismissed`.
- **Finding 2 — DB CHECK didn't prove `source_refs` is a non-empty array.** The
  old CHECK used `source_refs <> '[]'::jsonb`, which a raw INSERT could satisfy
  with `'{}'::jsonb` or a scalar. Fix: the CHECK now requires a non-empty JSON
  array via a CASE-guarded `jsonb_typeof(source_refs)='array' AND
  jsonb_array_length(source_refs) > 0` (CASE used because Postgres does not
  guarantee AND short-circuits, so `jsonb_array_length` must never run on a
  non-array). New test: `test_db_check_rejects_non_array_source_refs_for_verified`
  (`'{}'`, `'5'`, `'"x"'` each raise CheckViolation).
- **Process note** — ship report is now committed to the PR branch so reviewers
  who aren't party to the bus thread can read it.

Re-run after fixes: `python3.12 -m pytest tests/test_verified_items.py` →
**29 passed** (21 pure-logic + 8 live-PG) against isolated local PG 16.

## Follow-up flagged to lead (out of scope — not fixed here)

`tests/test_migrations.py::test_loop_infrastructure_up_down_round_trip` FAILS
when a live `TEST_DATABASE_URL` is set: the DOWN section of the **pre-existing**
`migrations/20260418_loop_infrastructure.sql` contains prose ("Disaster recovery
only…") that the round-trip's comment-leader stripper turns into invalid SQL —
same class of bug I hit + fixed in my own migration. It is normally masked
because the live test skips without a DB. Not touched (editing applied
migrations is forbidden + out of scope). Lead may want a follow-up brief to move
that prose above the `migrate:down` marker.

Also parked (unrelated): the rebase autostash from the PR #400 arc — a 25-line
append to `tasks/lessons.md` — is preserved at `git stash@{0}` ("autostash") in
this clone, recoverable by the alert-fastfollow session.
