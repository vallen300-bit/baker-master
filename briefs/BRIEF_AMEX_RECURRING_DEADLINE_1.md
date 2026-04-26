# BRIEF_AMEX_RECURRING_DEADLINE_1 — Recurring Deadlines in deadline_manager

**Date:** 2026-04-26
**Source spec:** `_ops/ideas/2026-04-26-amex-recurring-deadline-1.md`
**Author:** AI Head Build-reviewer (promoting from RA spec)
**Director defaults:** Q1/Q3 defaulted to RA recommendations 2026-04-26 ("Your 3 question — you default. I skip"). **Q2 RESOLVED 2026-04-26 PM (RA-21): anchor_date = 3rd of every month.** Q4 remains open — defer to acceptance-test phase, not pre-build.
**Trigger class:** **MEDIUM (DB migration)** → B1 second-pair-of-eyes review required pre-merge per `_ops/ideas/2026-04-24-b1-situational-review-trigger.md`. Builder must NOT be B1.
**Dispatch status:** **DISPATCH-READY** — trigger when B1 or B3 frees from current ships (DEADLINE_EXTRACTOR_QUALITY_1 / BRANCH_HYGIENE_1).

---

## 1. Bottom-line

Extend `orchestrator/deadline_manager.py` to support `recurrence` field. On deadline completion, auto-spawn next instance per recurrence rule.

Anchor case: AmEx payment (deadline #1438) — Director note: "has to be a cron job every month to avoid missing payment."

## 2. Why now

Cat 6 close 2026-04-26 surfaced AmEx as a one-shot deadline that should logically recur monthly. Currently every deadline is one-shot. Director's working pattern requires monthly bills + quarterly tax + annual subs to recur reliably.

Without recurrence, every AmEx month requires manual deadline re-creation → fails on the obvious risk: forgetting. Whole point of Baker's deadline tracker is to NOT forget.

## 3. Architecture

Schema migration on `deadlines` table:

| New field | Type | Default | Purpose |
|---|---|---|---|
| `recurrence` | TEXT | NULL | One of: `null` (one-shot), `monthly`, `weekly`, `quarterly`, `annual`. (cron expressions deferred to V2.) |
| `recurrence_anchor_date` | DATE | NULL | Reference date for recurrence math |
| `recurrence_count` | INT | 0 | Auto-incremented on each respawn (telemetry) |
| `parent_deadline_id` | INT | NULL | FK to original deadline (chain traceability) |

**Behavior:**
- On `mark_completed` for deadline with `recurrence != null` → spawn new row with `due_date = compute_next_due(recurrence, recurrence_anchor_date)`, copy description/priority/slug, increment `recurrence_count`, link `parent_deadline_id`.
- On `mark_dismissed` for recurring → ask Director "dismiss this instance only or stop recurrence?" (default: this instance only).

**Compute logic:**
- monthly: `+1 month from anchor_date` via `dateutil.relativedelta` (handle Feb edge cases)
- weekly: `+7 days`
- quarterly: `+3 months`
- annual: `+1 year`
- cron expressions: V2 (out of scope per Q1 default)

## 4. Director Q's — defaulted

| Q | Default applied |
|---|---|
| Q1: Recurrence values? | **First 4 only (monthly / weekly / quarterly / annual). Cron expressions in V2.** |
| Q2: AmEx anchor date? | **3rd of every month** (Director resolved 2026-04-26 PM via RA-21 — supersedes RA's prior 10th-of-month assumption). |
| Q3: UX for marking recurring vs one-shot? | **Both — checkbox at deadline creation + dashboard "make recurring" action on existing rows** |
| Q4: Other recurring candidates? | **DEFER TO ACCEPTANCE-TEST PHASE** (Director RA-21 2026-04-26 PM: not pre-build). After AmEx (#1438) acceptance-test passes, B-code emits Triaga HTML of current one-shot deadlines that look recurring — Director surveys + ticks; B-code applies one-shot conversion batch. Q4 NOT a build-time blocker. |

## 5. Code Brief Standards

1. **API version:** N/A — internal Baker schema work.
2. **Deprecation check:** confirm `deadline_manager.extract_deadlines()` + `mark_completed()` + `mark_dismissed()` signatures stable at build start.
3. **Fallback note:** if recurrence respawn fails (DB error), log to `deadline_recurrence_failures` table; alert Director via Slack push.
4. **DDL drift check (CRITICAL):** schema migration adds 4 columns to `deadlines`. **Grep `store_back.py` for any `_ensure_deadlines_base` or similar bootstrap.** Migration-vs-bootstrap drift trap (MEMORY.md feedback_migration_bootstrap_drift). Verify column types match between migration + any pre-existing bootstrap. **Block merge until verified.**
5. **Ship gate:** literal `pytest` output. Edge cases mandatory:
   - monthly Feb→March (28/29-day handling)
   - monthly Jan→Feb→March (handle 31st-of-Jan → 28/29-of-Feb → 31st-of-March)
   - quarterly with anchor on 30th (handle Feb)
   - annual leap year
6. **Test plan:** see §7.
7. **file:line citations:** verify every `deadline_manager.py:N` cite by opening file at line N. Brief-document line ≠ source line.
8. **Singleton pattern:** if any singleton class touched (e.g., `SentinelStoreBack`), use `._get_global_instance()` factory.
9. **Post-merge handoff:** schema migration applied via `python3 -m scripts.migrate` (or equivalent). If a backfill script runs against existing deadlines, handoff must include `git pull --rebase origin main` immediately before script invocation.
10. **Invocation-path audit (Amendment H):** N/A — no Pattern-2 capability touched (deadline_manager is infra, not a `client_pm`/`domain`/`meta` capability).

## 6. Definition of done

- [ ] Schema migration applied (4 new columns on `deadlines`); migration-vs-bootstrap verified
- [ ] `compute_next_due()` helper in `deadline_manager.py` with unit tests covering edge cases above
- [ ] `mark_completed` + `mark_dismissed` updated for recurrence respawn / stop logic
- [ ] Idempotency: respawn checks for existing child with same anchor before creating
- [ ] Cap respawn rate at 1/day per parent (silent infinite loop guard); alert Director on cap hit
- [ ] Dashboard UI: checkbox at deadline creation + "make recurring" action on existing rows
- [ ] AmEx (#1438) explicitly converted to monthly recurrence with `recurrence_anchor_date = 2026-05-03` (3rd of next month per Director Q2 resolution) as acceptance test
- [ ] **Post-acceptance:** Triaga HTML of remaining one-shot deadlines that look recurring (per Q4 deferred resolution) → Director surveys + ticks → batch conversion applied
- [ ] Documentation: `deadline_manager` README section on recurrence behavior
- [ ] Slack push on respawn failures via `deadline_recurrence_failures` table

## 7. Test plan

```
pytest tests/test_deadline_recurrence.py -v
# ≥10 tests: 4 recurrence types × edge cases (Feb, leap year, end-of-month) + idempotency + cap-rate + parent-link
pytest tests/ 2>&1 | tail -3
# full-suite no regressions
```

Smoke acceptance:
```
# 1. Apply migration
# 2. Mark AmEx #1438 recurrence=monthly, anchor_date=2026-05-10
# 3. Call mark_completed on a test recurring deadline
# 4. SELECT * FROM deadlines WHERE parent_deadline_id = <test_id>;
# expect: new row, due_date = anchor + 1 month, recurrence_count = 1
```

## 8. Out of scope

- Calendar integration (Google Calendar event creation from recurring) — separate brief
- Recurrence end-date / max-count — V2
- Holiday/business-day adjustments — V2
- Cron expressions — V2 per Q1 default

## 9. Promotion + dispatch path

- AI Head Tier B promotes spec → this brief.
- Dispatch to B3 OR B4 (NOT B1 — B1 reviews per situational-review rule).
- B-code builds, ships PR.
- **B1 review mandatory** before merge (DB migration triggers situational-review rule).
- AI Head + B1 reviews per autonomy charter §4.

## 10. Risk register

| Risk | Mitigation |
|---|---|
| Recurrence respawn race condition | Idempotent: respawn checks for existing child with same anchor before creating |
| Silent infinite loop (misconfigured anchor) | Cap respawn rate 1/day per parent; alert Director on cap hit |
| Director dismisses recurring expecting full stop | Dismiss UX explicitly asks "this instance" vs "stop recurrence" |
| Schema migration drift (migration-vs-bootstrap trap) | §5 #4 mandatory verification before merge |
| AmEx anchor day wrong (3rd resolved 2026-04-26 PM by Director) | Dashboard override on `recurrence_anchor_date` if Director later corrects |

## 11. Authority chain

- Director ratification: 2026-04-26 "C" (Cat 6 close) + default-fallback ("you default. I skip"). Originating note on deadline #1438: "has to be a cron job every month to avoid missing payment."
- Director Q2 resolution 2026-04-26 PM (via RA-21): `anchor_date = 3rd of every month`.
- Director Q4 deferral 2026-04-26 PM (via RA-21): "defer to acceptance-test phase, not pre-build."
- RA-19 spec: `_ops/ideas/2026-04-26-amex-recurring-deadline-1.md`
- AI Head Tier B: this brief + dispatch (DISPATCH-READY, awaiting B1 or B3 to free).
