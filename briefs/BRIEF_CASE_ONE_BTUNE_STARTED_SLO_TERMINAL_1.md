# BRIEF: CASE_ONE_BTUNE_STARTED_SLO_TERMINAL_1 — started-SLO must key on `started`, not `acked`, for command-kind

> **⚠️ SUPERSEDES (flip flagged, not silent — Mnilax surface-don't-average; lead #11076):** This brief INVERTS the "acked = terminal SUCCESS" position — my own earlier triage rec (i) and lead's ratified **#11023 item-4**. On the merits the E11 argument wins: ack ≠ execution; `started_at` is the delivery model's own success marker (`db.py:673`); treating `acked` as terminal would blind the semantic evaluator to exactly the P5 silent-leg class it exists to catch. Lead ratified the flip (#11076); **#11023 item-4 wording is hereby superseded.** Because this reverses a ratified decision, it ships **kill-switch-OFF behind a stepped arming ladder** (see Rollout), never a silent day-one flip.
>
> **Companion prerequisite (HARD gate):** the `BRISEN_LAB_OBLIGATION_STARTED_TERMINAL=1` flip is hard-gated on `CLIENT_STARTED_EMISSION_1` (client drain/check-inbox path must emit `started_at` on dispatch pickup; owner b1). Today 367/487 delivery rows are acked-not-started **because clients almost never emit `started`** — so a default-ON flip would read those as OPEN on day one = instant E15. See Rollout ladder + `BRIEF_CLIENT_STARTED_EMISSION_1.md`.

## Context
Deputy delivery-backlog triage (lead #11022 item 4). Two findings converge:
1. The obligation / unacked-SLO alarm treats a message as terminally satisfied the moment `acknowledged_at` is set (acked). But the delivery model's own definition of success is *reached `started` within the started-SLA* (`db.py:673` — "delivered ≙ reached `started` within SLA; else `undelivered`"). An **acked-but-never-started** command-kind obligation is therefore counted as fulfilled while the work never began — the "silent leg" failure class (P5 legs sat ~38m/~77m un-executed).
2. Item-3 finding (deputy #11062): PR #557 fixed only the client false-empty-on-503; it did **not** cover the `delivered_at`-NULL receipt-write drops. `delivered_at` is NULLABLE (`db.py:674`); ~11/18 "undelivered" rows were acked-but-no-receipt. Any receipt-based counting undercounts silently.

This is a **tuning** brief (lead's standing P2 rider: tune on live data before ENFORCE flip), not a new subsystem. It sharpens the alarm predicate so "done" means *work started*, and makes the no-receipt case honest.

## Estimated time: ~3h
## Complexity: Medium
## Prerequisites: P5 delivery-confirmation loop merged (it is — brisen-lab `brisen_lab_delivery` table live: `delivered_at`/`started_at`/`acknowledged_at`/`escalated_at`/`delivery_state`/`sla_state`). Command/Event intent-types (P4) additive on `kind`; this brief is consistent with `EXECUTE_OBLIGATION_KINDS = {dispatch, ratify_required}`.

## Baker Agent Vault Rails
Relevant rails: bus-and-lanes (obligation/SLO alarm predicate), verification-surfaces (semantic_delivery_evaluator + /api/semantic_delivery + arm_alarm_check), memory-and-lessons (E11 obligation-split, E15 alarm-fatigue).
Ignore unrelated rails: standing-contract, build-command-center, skills-and-playbooks, loop-runner — untouched.

## Harness V2

**Task class:** correctness/tuning fix (production, brisen-lab bus daemon). Not a net-new subsystem — a predicate change + a reporting bucket on the existing P5 delivery-confirmation loop.

**Context Contract:**
- **Repo/scope:** brisen-lab only (`semantic_delivery_evaluator.py`, `app.py` obligation readers, `db.py` index-add). Baker-master untouched.
- **Inputs the builder starts from:** the live `brisen_lab_delivery` table (delivered_at/started_at/acknowledged_at/escalated_at/delivery_state/sla_state) + the SLA config functions in `bus.py` (`_delivery_started_sla_s`=900s, `_delivery_ack_sla_s`=300s). No schema change to the table.
- **Outputs:** (Fix 1) command-kind obligation-open predicate keyed on `started_at`/`escalated_at`, not `acknowledged_at`; (Fix 2) a distinct `receipt_missing` reporting bucket. Both behind `BRISEN_LAB_OBLIGATION_STARTED_TERMINAL` kill switch.
- **Out of contract (do NOT touch):** badge/unacked indexes (`brisen_lab_msg_unacked`, `idx_msg_open_ratifies`), ack-SLA rewake path, `mark_delivery_started_sync` escalation guard, the receipt WRITE path (→ separate `RECEIPT_WRITE_DURABILITY_1`).
- **Reconcile with P4.2:** dispatch-warning gates on `kind=assignment`; this brief is the *obligation-closed* judgment. Different predicates, no double-gate.

**Done rubric / done-state class (deterministic):**
1. Unit: acked-un-started-past-SLA **command** row counts as OPEN obligation (fails today → passes).
2. Unit: acked+started command row = green.
3. Unit: acked **Event**-kind (broadcast/alert) NOT counted as obligation.
4. Unit: `ratify_required` Director open-Q count unchanged (regression guard on the untouched acked index).
5. Unit: acked+no-receipt row appears in `receipt_missing` bucket, distinct + non-zero.
6. Kill switch: `BRISEN_LAB_OBLIGATION_STARTED_TERMINAL=0` reverts to legacy predicate (test both states).
7. Suite: no new failures vs the 27-fail brisen-lab baseline.
8. Live: `POST_DEPLOY_AC_VERDICT` — `GET /api/semantic_delivery` reflects a real acked-un-started command leg as open, not green (with the switch ON in a drill env; merge state is OFF).
9. **Flip precondition (lead #11076):** before any `=1` flip, the live open-obligation count under the new predicate is ≤ the lead-agreed threshold (target ~0 acked-not-started once `CLIENT_STARTED_EMISSION_1` is live). This is a *rollout-ladder gate*, not a build-time test — the builder ships the query that measures it; lead reads it before GO.

**Gate plan:** G1 builder self-verify (rubric items 1–8) → codex correctness review (cross-vendor; codex seats lifted #9711) → lead PASS → lead merges **switch OFF** → Render deploy → **deputy** runs the live drill + posts `POST_DEPLOY_AC_VERDICT v1` (deputy is named bus-health owner). Rubric item 9 + the `=1` flip are gated later by the Rollout ladder, each step lead-GO'd.

### Rollout — stepped arming ladder (each step = explicit lead GO; lead #11076)
1. **A-clear** the ~88 never-acked-but-shipped overhang (queue item 5, HELD for lead sign-off) — clean the legacy baseline first.
2. **Merge this brief switch-OFF**; arm ENFORCE on the *legacy* acked-based predicate (no behaviour change vs today, just the reader plumbed through the shared predicate + `receipt_missing` bucket live).
3. **`CLIENT_STARTED_EMISSION_1` ships** (companion, owner b1) — clients emit `started_at` on dispatch pickup.
4. **Live acked-not-started population drains to ~0** (rubric item 9 ≤ threshold) as real `started` signals flow.
5. **Flip `BRISEN_LAB_OBLIGATION_STARTED_TERMINAL=1`** — HARD-gated on steps 3+4. Only now does `acked`-terminal actually invert on the live alarm.

---

## Fix 1: started-SLO / obligation predicate keys on `started`, not `acked`, for command-kind

### Problem
Every open-obligation predicate keys on `acknowledged_at IS NULL`. Once a command-kind message is acked, it exits the open set and the SLO alarm treats it as terminal SUCCESS — even if `started_at` is still NULL and the started-SLA (900s) has blown. Result: an obligation that was *accepted but never executed* reads as green. This is precisely E11 (obligation-split): ack ≠ execution.

### Current State
Predicate call sites keying on `acknowledged_at IS NULL` (brisen-lab):
- `app.py:345` / `app.py:380` / `app.py:401` — open-dispatch snapshot writer.
- `app.py:504`, `app.py:1570`, `app.py:2034`, `app.py:2279` — obligation / bus-health / semantic-seat-oldest-age readers.
- `db.py:769` — `brisen_lab_msg_unacked` partial index; `db.py:761` — `idx_msg_open_ratifies` (ratify-specific).
- `semantic_delivery_evaluator.py` — the DB-anchored `obligations` check consumed by `/api/semantic_delivery` (`app.py:2294`), which `arm_semantic_poll.sh` → `arm_alarm_check.sh` fires on.

Delivery state machine (`db.py:1160` `stamp_delivery_ack_sync` sets `acknowledged_at`; `db.py:1183` `mark_delivery_started_sync` sets `started_at`, COALESCE-guarded + `escalated_at IS NULL`-guarded so a late start cannot un-do an escalation — `db.py:1185-1196`). True terminal = `started_at` set within `_delivery_started_sla_s()` (900s), else `escalated_at` (dead-lettered). `delivered_at` NULLABLE.

### Engineering Craft Gates
- **Diagnose:** applies. Feedback loop = a throwaway Postgres DB (`createdb`, `TEST_DATABASE_URL=postgresql://localhost:5432/<db>`, `dropdb`) seeded with one command-kind row that is acked but `started_at IS NULL` past the started-SLA. Hypotheses, ranked: (1) obligation reader counts it green because predicate = `acknowledged_at IS NULL` [most likely — confirmed by grep]; (2) semantic evaluator's `obligations` check inherits the same predicate; (3) the arm alarm marker therefore never fires on un-started legs. Probe/regression: a test asserting the obligation count includes an acked-but-un-started-past-SLA command row.
- **Prototype:** N/A — the state machine + SLA config already exist; this is a predicate change, no design uncertainty.
- **TDD/verification:** applies. Public seam = `/api/semantic_delivery` verdict + the obligation-count reader. First vertical test: seed acked-un-started-past-SLA command row → assert it appears as an open/undelivered obligation (fails today). Second: an acked-AND-started command row → assert green. Third (Event-kind): an acked broadcast/alert → assert NOT counted (command-kind only).

### Implementation
Introduce a single shared "open obligation" predicate and route the command-kind SLO/obligation readers through it. Do **not** change the badge/refresh unacked-count (that is a distinct UI concern — see Constraints).

1. Define the obligation-open predicate as: a **command-kind** (`execute_obligation = TRUE`, i.e. `kind ∈ {dispatch, ratify_required}`) delivery row is an OPEN obligation while it has **not reached `started`** and has **not been terminally escalated**:
   ```sql
   -- open command obligation = accepted-or-not, but work not yet started and not escalated
   WHERE execute_obligation = TRUE
     AND started_at IS NULL
     AND escalated_at IS NULL
     AND deleted_at IS NULL
   ```
   Rationale: `started_at` is the delivery model's own success marker (`db.py:673`); `escalated_at` is the terminal-failure marker (already dead-lettered → out of the actionable-open set, so the alarm does not double-count E15). `ratify_required` rows still ALSO surface via `idx_msg_open_ratifies` (acked-based) for the Director open-Q count — keep that; it answers a different question ("awaiting Director ratification") and must not change.
2. Update the `obligations` reader in `semantic_delivery_evaluator.py` (and the `app.py:2279`/`2034` obligation readers it mirrors) to this predicate, joining `brisen_lab_msg` → `brisen_lab_delivery` on `(msg_id, recipient)`. Command-kind ONLY; Event-kind (`ack`/`broadcast`/`ratify_decision`/`alert`) is never an obligation.
3. Keep the **ack-SLA rewake** (300s, `_delivery_ack_sla_s`) exactly as-is — that path is correct (un-acked → rewake). This brief only fixes the *terminal-success / obligation-closed* judgment, which must require `started`.

### Key Constraints
- **Command-kind ONLY** (plan v3 #10397 zero-silent-loss; ARM charter v1.1a). Never gate on Event-kind — that is E15 alarm-fatigue.
- **Additive, non-regressive.** Do NOT touch `brisen_lab_msg_unacked` (`db.py:769`) or `idx_msg_open_ratifies` (`db.py:761`) — badge counts + Director open-Q count stay acked-based. New predicate needs its own partial index if a seq scan appears: `WHERE execute_obligation = TRUE AND started_at IS NULL AND escalated_at IS NULL AND deleted_at IS NULL`.
- **ENV KILL SWITCH — DEFAULT OFF AT MERGE** (`BRISEN_LAB_OBLIGATION_STARTED_TERMINAL`, unset/`0` = legacy acked-based predicate; `1` = new `started`-based predicate). **Merges OFF.** Rationale (lead #11076): 367/487 live rows are acked-not-started because clients almost never emit `started_at` yet — a default-ON flip would read those as OPEN day one = instant E15, the exact failure tune-before-arm exists to prevent. The `=1` flip happens only at the end of the Rollout ladder, each step lead-GO'd, and is HARD-gated on `CLIENT_STARTED_EMISSION_1`. Reversible via Render env PUT without redeploy.
- Every query has a LIMIT; every `except` does `conn.rollback()`; reuse `db_gate.db_call`.

### Verification
- Unit: the 3 seeded-row tests above (acked-un-started-past-SLA command = open; acked+started command = green; acked Event = not counted).
- Live probe: `GET /api/semantic_delivery` with `X-Terminal-Key` on a DB that has a known acked-but-un-started command leg → verdict must reflect it as an open obligation, not green.

---

## Fix 2: honest accounting for `delivered_at`-NULL (no-receipt) rows — fold of item-3

### Problem
`delivered_at` is NULLABLE (`db.py:674`); acked-but-no-receipt rows exist (~11/18 of the P5 "undelivered" set). Any surface that counts "delivered" off `delivered_at IS NOT NULL` silently undercounts these as failures, while the started/acked path may separately count them green — an inconsistency between the two signals.

### Current State
`record_delivery_receipts_sync` (`db.py:1079`) writes `delivered_at`; under F-503/E1 (recycled-conn ack-no-op + 503 flap) the receipt write can be dropped while the ack still lands. So `acknowledged_at IS NOT NULL AND delivered_at IS NULL` is a real, reachable state.

### Engineering Craft Gates
- **Diagnose:** applies. Same throwaway-DB loop. Hypothesis: the divergence is (acked ✓, receipt ✗) rows. Probe: seed one such row; assert the delivery-health surface labels it explicitly (not silently green, not silently failed).
- **Prototype:** N/A. **TDD:** applies — one seeded acked+no-receipt row, assert an explicit `no_receipt` classification.

### Implementation
1. In the delivery-health / semantic `undelivered` reader, classify `acknowledged_at IS NOT NULL AND delivered_at IS NULL` as a distinct `receipt_missing` bucket (not "undelivered", not "delivered"). Surface the count; do not let it vanish into either terminal.
2. This is a *reporting-honesty* fix, not a receipt-write repair. The write-path repair (why the receipt drops under F-503) is a **separate** brief — recommend a follow-up `RECEIPT_WRITE_DURABILITY_1` (retry/verify the receipt write on the F-503 recycled-conn path). Flag it to lead; do not fold the repair here (scope discipline — Mnilax surface-don't-blend).

### Key Constraints
- Fix 2 is read/report-only. No change to the write path in this brief.
- LIMIT + rollback as above.

### Verification
- Unit: seeded acked+no-receipt row surfaces in the `receipt_missing` bucket with a non-zero count.
- Live: delivery-health surface shows the bucket distinctly from delivered/undelivered.

---

## Files Modified
- `semantic_delivery_evaluator.py` — obligation predicate → `started`-based, command-kind only (Fix 1); `receipt_missing` bucket (Fix 2).
- `app.py` — obligation readers (`~2034`, `~2279`) routed through the shared predicate; delivery-health `receipt_missing` surface.
- `db.py` — new partial index for the `started`-based obligation predicate if needed; NO change to existing indexes/tables (additive only).
- `tests/` — the 3 Fix-1 tests + the Fix-2 test.

## Do NOT Touch
- `db.py:769` `brisen_lab_msg_unacked` + `db.py:761` `idx_msg_open_ratifies` — badge + Director open-Q counts stay acked-based (different question).
- The ack-SLA rewake path (`_delivery_ack_sla_s`, 300s) — correct as-is.
- `mark_delivery_started_sync` escalation guard (`db.py:1190-1196`) — exactly-once invariant, do not weaken.
- The receipt WRITE path — separate `RECEIPT_WRITE_DURABILITY_1` follow-up.

## Quality Checkpoints
1. Acked-but-un-started-past-SLA command row reads as an OPEN obligation (was green).
2. Acked + started command row reads green.
3. Acked Event-kind (broadcast/alert) is NEVER counted as an obligation.
4. `ratify_required` Director open-Q count unchanged (still acked-based).
5. `receipt_missing` bucket is distinct and non-zero on the seeded row.
6. `BRISEN_LAB_OBLIGATION_STARTED_TERMINAL=0` cleanly reverts to legacy predicate.
7. No new failures vs the 27-fail brisen-lab baseline (pre-existing autowake/identity env).

## Verification SQL
```sql
-- open command obligations under the new predicate (should include acked-un-started-past-SLA)
SELECT COUNT(*) FROM brisen_lab_delivery d
WHERE d.execute_obligation = TRUE
  AND d.started_at IS NULL
  AND d.escalated_at IS NULL
  AND d.deleted_at IS NULL
LIMIT 1000;

-- receipt_missing bucket (acked, no receipt)
SELECT COUNT(*) FROM brisen_lab_delivery d
WHERE d.acknowledged_at IS NOT NULL
  AND d.delivered_at IS NULL
  AND d.deleted_at IS NULL
LIMIT 1000;
```

## Related finding (non-blocking; lead #11073) — default-flight fallback mints real-matter tickets from infra emails
During item-2 triage, the BB-AUK-001 escalation (#10554/#10597/#10653) resolved to **mis-routes**: `[ARM OUT-OF-BAND RECOVERY/ALARM]` canary + fire-drill emails from Director's own mailbox were minted as *aukera-annaberg-financing* tickets under the **global-default flight env** (same default-fallback family as b1's #10236, email path this time). Fix direction (a separate brief, not this one — scope discipline): infra-sender/subject filter *upstream* of ticket mint, OR default unmatched infra traffic to a **review lane** instead of a real matter flight. Recommend spinning `DEFAULT_FLIGHT_INFRA_FILTER_1` (owner: whoever owns the ticket-mint path). Not a delivery-SLO concern; noted here per lead's append instruction so it is not lost.

## Companion brief (this arc): `CLIENT_STARTED_EMISSION_1`
Authored alongside this amendment (owner **b1** — owns the #557 client read-contract context). Client drain/check-inbox path emits `started_at` on dispatch pickup so `started`-based obligation-closing has a real signal to read. **The `=1` flip in this brief's Rollout ladder is HARD-gated on it.** See `BRIEF_CLIENT_STARTED_EMISSION_1.md`.

## Routing
Lead reviews → deputy-codex builds (cross-vendor gate: codex correctness) per B-code lane; **merges switch-OFF**, `=1` flip deferred to the Rollout ladder. Command-kind-only scope reconciles with P4.2 (dispatch-warning on `kind=assignment`) — do NOT double-gate; this predicate is the *obligation-closed* judgment, P4.2 is the *dispatch-warning* judgment. Follow-ups spun out (flagged to lead, NOT in this brief): `RECEIPT_WRITE_DURABILITY_1` (receipt write-path repair), `CLIENT_STARTED_EMISSION_1` (companion prerequisite, owner b1), `DEFAULT_FLIGHT_INFRA_FILTER_1` (ticket-mint infra filter).
