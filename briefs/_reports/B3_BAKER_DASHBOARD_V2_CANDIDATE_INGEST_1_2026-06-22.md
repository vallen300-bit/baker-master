# Ship Report — BAKER_DASHBOARD_V2_CANDIDATE_INGEST_1

**Builder:** B3
**Date:** 2026-06-22
**Branch:** `b3/baker-dashboard-v2-candidate-ingest-1` (off `main` — incl. #405 0e1bc74 + #406 254a4da)
**Dispatch:** bus #3826 + scope-guard addendum #3830 (deputy / codex-arch), both acked
**Merge:** HELD per gate plan — deputy is merge owner this session; do not merge until deputy-codex G-review + deputy cross-lane PASS.

---

## What shipped

V2 "Verified Operating Room" **Tranche 2** — the ingestion/quarantine layer
between "Baker caught something" and "Baker stands behind it". Backend only:
candidate writer + source-trust classifier + dedup + legacy bridges + triage
APIs. No Today UI, no automated verifier, no replacement of alerts/deadlines.

Files:
- `migrations/20260622d_signal_candidates_dedup.sql` — adds `dedup_key` (+ partial
  UNIQUE index), `due_at`, `dismiss_reason` (+ CHECK) to `signal_candidates`.
  Additive/idempotent; new migration (20260622c already applied to prod).
- `orchestrator/candidate_ingest.py` — the single candidate writer + classifier +
  dedup + bridges + triage reads/dismiss + manual promotion.
- `outputs/dashboard.py` — 3 triage endpoints (additive; no rewrite).
- `tests/test_candidate_ingest.py` — 11 pure-logic + 8 live-PG.

---

## Done rubric

**1. Which sources now create candidates?**
A single source-agnostic writer `candidate_ingest.create_candidate(...)` (AC1) is
the call point for every source (email, WhatsApp, Plaud/meeting, calendar,
ClickUp/Todoist, RSS/browser, documents). Live coverage **today** flows through
the legacy bridge: `bridge_alert_to_candidate` / `bridge_deadline_to_candidate`
(+ batch `bridge_pending_alerts` / `bridge_active_deadlines`) route the existing
email/WA/Plaud/calendar-derived alerts and deadlines into candidates (AC3).

**2. Which sources remain legacy-only?**
`alerts` and `deadlines` stay intact as low-level operational feeds — they are
**bridged, not replaced** (NOTE 1: "Do not replace existing alerts/deadlines yet;
bridge them"). Direct per-sentinel candidate writes (modifying the email/WA/Plaud/
calendar extraction call-sites to emit candidates instead of alerts) are a staged
follow-on, correct to do once the verifier + Today actually consume candidates —
doing it now would strand candidates with no consumer while still keeping legacy
alerts flowing. **Flagging this scope read to deputy/codex-arch**: if they want
direct sentinel call-site wiring inside this tranche, say so and I'll extend.

**3. How does the writer enforce the Gemini Pro minimum?**
It REUSES `orchestrator/model_policy.is_allowed_for_trusted` (the live MODEL_LOCK_1
floor) — no second implementation. A barred model (Flash / empty) forces
`source_trust='untrusted_legacy'`, which `can_promote()` refuses (AC2.3). The
`extraction_model` is always stored (AC2.1); provenance is logged via
`model_policy.log_model_provenance`.

**4. How does dedup work?**
Content-based `dedup_key = sha256(normalized_summary | matter_slug | sorted(people)
| due_date)` + a partial `UNIQUE INDEX uq_signal_candidates_dedup`. Creation uses
`INSERT … ON CONFLICT (dedup_key) WHERE dedup_key IS NOT NULL DO NOTHING`, then
returns the existing id on conflict — so repeated quiet-thread/proactive/system
catches and re-bridged legacy rows collapse to one candidate (AC4, AC3.4). The
partial-index inference (matching `WHERE` in the `ON CONFLICT`) follows the
PR #400 lesson.

**5. How are marketing/bulk/system noise classified?**
`classify_source_trust(...)` — deterministic, no model call. `marketing_or_bulk`
and `public_source` are in `LOW_PRIORITY_TRUST` (kept out of Today + low priority);
system/scheduler/clickup/todoist → `internal_system`; rss/browser → `public_source`;
unknown is the fail-safe default.

**6. Which tests prove candidates do not enter Today?**
`test_morning_brief_does_not_read_signal_candidates` — structural assertion that
the `/api/dashboard/morning-brief` function body never references
`signal_candidates` (so candidates cannot leak into Today). The writer only ever
touches `signal_candidates`.

**7. How is raw body leakage prevented?**
`signal_candidates` has no raw-body column; the candidate writer persists a source
pointer (`raw_source_table`, `raw_source_id`) + summary only (AC1 field 10 — "raw
payload pointer, not raw body"). Triage reads use an explicit
`_CANDIDATE_PUBLIC_COLS` allowlist (summary/metadata/source-refs); a test asserts
returned keys ⊆ allowlist and `body` never appears (AC9).

---

## Acceptance criteria

| AC | Status | Evidence |
|----|--------|----------|
| AC1 single candidate writer | PASS | `create_candidate` source-agnostic; all sources call it |
| AC2 trusted model floor | PASS | reuses model_policy; Flash → untrusted_legacy; test proves |
| AC3 legacy bridge w/o bypass | PASS | alert/deadline → candidate; original id preserved; idempotent re-bridge |
| AC4 dedup | PASS | content dedup_key + partial UNIQUE index; idempotency test |
| AC5 source-trust classifier | PASS | 8-value vocab; marketing/bulk low-priority |
| AC6 triage APIs | PASS | GET /api/triage/candidates, POST …/dismiss, POST …/verify-manual |
| AC7 matter-aware filters | PASS | matter/source/type/trust/status/window filters |
| AC8 Today excludes candidates | PASS | structural test on morning-brief |
| AC9 no raw body | PASS | column allowlist; no raw-body column exists |
| AC10 structured dismiss reasons | PASS | 10-value DISMISS_REASONS + DB CHECK |

---

## Scope guards (deputy/codex-arch #3830) — all folded

1. Quarantine-only / no Today consumption — AC8 structural test.
2. Reuse live `model_policy` — imported, not reimplemented.
3. Flash/backfill → `untrusted_legacy`, cannot promote without re-extraction — AC2/AC2.3 tests.
4. No raw body leakage — column allowlist (AC9).
5. Dedup/idempotency not optional — partial UNIQUE index + content key (AC4).
6. **GATE CHECK (mandatory):** `verify-manual` does NOT use a direct
   `create(state='verified')` (which records `actor_type='system'`). It creates
   the shell in `candidate` state, then promotes via `transition_item` with the
   explicit verifier, so the human verifier is recorded in `verification_events`.
   `test_verify_manual_records_human_verifier_in_events` asserts the verification
   event carries `actor_type='director'`/`actor_id='dvallen'` (not `system`), and
   a non-system verifier is required (`verifier_required` rejection). PROVEN.

---

## Test output

`python3.12 -m pytest tests/test_candidate_ingest.py tests/test_verified_items.py`
against isolated local PG 16 (throwaway DB; never the shared brisen-lab test DB):

```
tests/test_candidate_ingest.py ... 19 passed (11 pure-logic + 8 live-PG)
tests/test_verified_items.py  ... 29 passed (regression — no breakage)
============================== 48 passed ==============================
```

Also verified: production `migration_runner.run_pending_migrations` applies
20260622c + 20260622d in order, idempotent re-run returns `[]`, new columns +
unique index present; the 3 triage routes register on app import.

---

## codex G-review #3839 (REQUEST_CHANGES) — folded (commit pending)

Cross-lane gate #3838 PASSED; deputy-codex G-review then raised 2 findings, both fixed on-branch:

- **F1 (HIGH) — verify-manual ignored candidate lifecycle status.** A dismissed
  or already-promoted candidate could still be promoted (duplicate
  `verified_items`, weakened quarantine). Fix: `promote_candidate_manual` now (a)
  rejects any candidate whose status is not `awaiting_verification`
  (`bad_candidate_status`), and (b) **atomically claims** the candidate
  (`UPDATE … SET status='promoted' WHERE id=%s AND status='awaiting_verification'
  RETURNING id`) before creating the verified item — closing the double-submit
  race; the claim is released (reverted to awaiting) if the create/transition
  fails. New tests: `test_verify_manual_refuses_dismissed_candidate`,
  `test_verify_manual_no_double_promote` (asserts exactly one `verified_items`
  row per candidate).
- **F2 (MEDIUM) — `/api/triage/candidates` missing the AC7 created-date window.**
  The service supported `created_after`/`created_before`; the endpoint didn't
  expose them. Fix: added both query params and passed them through. New test:
  `test_list_candidates_created_window`.

Codex positive checks retained: guard #6 design, model-floor reuse, raw-body
allowlist.

Re-run after fixes: `python3.12 -m pytest tests/test_candidate_ingest.py
tests/test_verified_items.py` → **51 passed** (14 pure-logic + 8 live-PG ingest +
29 verified_items regression) against isolated local PG 16.

## Gate

Builder self-test PASS → deputy-codex G-review (MANDATORY, Director-directed) →
deputy cross-lane → **deputy merges** (Director-authorized merge owner this
session). Merge HELD until both gates PASS.
