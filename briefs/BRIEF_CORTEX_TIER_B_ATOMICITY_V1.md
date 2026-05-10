# BRIEF: CORTEX_TIER_B_ATOMICITY_V1 — Close Tier B pool-wide atomicity gap (Pattern B, reservation-row)

## Context

B3 shipped `CORTEX_TIER_B_RUNTIME_V1` (PR #179, merged 2026-05-10) with a
documented atomicity gap. The PASS path in `enforce_tier_b()` runs inside a
SERIALIZABLE transaction but never WRITES anything — it just commits. Two
concurrent enforcers both reading €499 day-total can both PASS and exceed
the €500 cap, because Postgres SSI sees no rw-anti-dependency conflict (no
overlap between read and write sets).

Director ratified Path A on 2026-05-10: defer closure to B4. Director
ratified Pattern B (reservation-row) + 15-min TTL + atomicity-only scope on
2026-05-10 PM after AH1 scope-correction surface.

Closure is the hard acceptance criterion in `_ops/briefs/_precursor/B4_PRECURSOR_ATOMICITY_CLOSURE.md`.
D5 risk register entry flips to RESOLVED on this brief's merge.

## Estimated time: ~5h
## Complexity: Medium
## Prerequisites: B3's `CORTEX_TIER_B_RUNTIME_V1` (live on `main` since 2026-05-10).

## Scope discipline

In scope:
- Schema extension: `reserved_at` column on `baker_actions` + new partial index
- `tier_b_runtime.py` refactor: PASS path writes reservation row inside SERIALIZABLE
- `Decision` dataclass: new `reservation_id` field
- New module-level: `confirm_tier_b(reservation_id)` + `cancel_tier_b(reservation_id)`
- Sweep job: `tier_b_reservation_sweep` every 5 min via APScheduler; deletes orphans >15 min old
- Tests: existing + new (concurrent-commits load test is the hard ship-gate)
- conftest schema mirror (mirror migration in `_bootstrap_tier_b_schema`)

Out of scope (deferred; do NOT touch):
- Phase 5 V2 audit-log uplift (`cortex_phase5_act.py:220-222`) — separate brief
- Adoption of `enforce_tier_b` at any Cortex Phase 5 call-site — premature
- `cortex-architecture-final.md` §8 Q5 spec reconciliation (60s→180s) — AH1 vault edit, not B-code
- `tier_b_ratify.py` — already shipped; no changes needed

## DB schema verified (Brief Standard #3b)

Pre-flight: `SELECT column_name FROM information_schema.columns WHERE table_name = 'baker_actions'`:
```
id, action_type, target_task_id, target_space_id, payload, trigger_source,
created_at, success, error_message, tier, cost_eur, committed_at,
committer_agent, action_class, self_cost_eur
```
(Last 6 added by `migrations/20260510_baker_actions_tier_b_runtime.sql`. We
add `reserved_at` in this brief — checked NOT already present.)

`tier_b_pending` columns (verified): `id, action_payload, cost_eur,
action_class, committer_agent, reason_paused, status, created_at,
ratified_at, ratified_by, decision_payload, expired_at`.

---

## Fix 1: Migration — add `reserved_at` to baker_actions + cap-read index

### Problem

`baker_actions` has no `reserved_at` column today. We need it to mark
in-flight reservations (PASS path writes a row with `committed_at IS NULL`
+ `reserved_at = NOW()`). The cap-counter SQL must read both committed
rows AND active (un-expired) reservations.

### Implementation

Create `migrations/20260511_baker_actions_reservation.sql`:

```sql
-- 20260511_baker_actions_reservation.sql
-- Pattern B atomicity closure for Tier B runtime: add reserved_at +
-- partial index supporting reservation-aware cap reads.
--
-- BRIEF_CORTEX_TIER_B_ATOMICITY_V1, Director-ratified 2026-05-10.

BEGIN;

ALTER TABLE baker_actions
    ADD COLUMN IF NOT EXISTS reserved_at TIMESTAMPTZ;

-- Index supports the reservation-aware cap read in enforce():
--   ... WHERE tier='B' AND cost_eur IS NOT NULL
--         AND ((committed_at IS NOT NULL AND committed_at >= <bucket>)
--           OR (committed_at IS NULL AND reserved_at >= NOW() - INTERVAL '15 minutes'))
-- We keep the existing idx_baker_actions_tier_b_committed (committed_at)
-- and add a sibling on reserved_at for the second branch of the OR.
CREATE INDEX IF NOT EXISTS idx_baker_actions_tier_b_reserved
    ON baker_actions (reserved_at)
    WHERE tier = 'B' AND cost_eur IS NOT NULL AND committed_at IS NULL;

COMMIT;
```

### Key constraints

- Migration is additive + idempotent (`ADD COLUMN IF NOT EXISTS`).
- No backfill — legacy rows have `reserved_at IS NULL` (never matched by
  reservation-aware reads, only by committed branch).
- Do NOT alter the existing `idx_baker_actions_tier_b_committed` — both
  indices serve different branches of the cap-read OR.

### Verification

After deploy, run:
```sql
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name = 'baker_actions' AND column_name = 'reserved_at';
-- expect: reserved_at | timestamp with time zone

SELECT indexname FROM pg_indexes WHERE tablename = 'baker_actions'
  AND indexname LIKE 'idx_baker_actions_tier_b%';
-- expect both: idx_baker_actions_tier_b_committed, idx_baker_actions_tier_b_reserved
```

---

## Fix 2: conftest schema mirror (test bootstrap)

### Problem

`tests/conftest.py:_bootstrap_tier_b_schema` inlines the same DDL the
migration emits (lesson from B3: ephemeral Neon test branches don't run
the migration chain; conftest mirrors it). If the migration adds a column
but conftest doesn't, the live-PG tests run against a stale schema and
fall over with `column "reserved_at" does not exist`.

### Implementation

Edit `tests/conftest.py:_bootstrap_tier_b_schema` — locate the
`ALTER TABLE baker_actions` DDL block (currently around lines 299-307)
and append `reserved_at`. Also add the new index DDL.

Find this block (starts at `tests/conftest.py:300`):
```python
"""
ALTER TABLE baker_actions
    ADD COLUMN IF NOT EXISTS tier TEXT,
    ADD COLUMN IF NOT EXISTS cost_eur NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS committed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS committer_agent TEXT,
    ADD COLUMN IF NOT EXISTS action_class TEXT,
    ADD COLUMN IF NOT EXISTS self_cost_eur NUMERIC(12, 2)
""",
```

Replace with:
```python
"""
ALTER TABLE baker_actions
    ADD COLUMN IF NOT EXISTS tier TEXT,
    ADD COLUMN IF NOT EXISTS cost_eur NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS committed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS committer_agent TEXT,
    ADD COLUMN IF NOT EXISTS action_class TEXT,
    ADD COLUMN IF NOT EXISTS self_cost_eur NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS reserved_at TIMESTAMPTZ
""",
```

Then immediately after the existing `idx_baker_actions_tier_b_committed`
DDL block, add the new index block:
```python
"""
CREATE INDEX IF NOT EXISTS idx_baker_actions_tier_b_reserved
    ON baker_actions (reserved_at)
    WHERE tier = 'B' AND cost_eur IS NOT NULL AND committed_at IS NULL
""",
```

Also: the inline `CREATE TABLE IF NOT EXISTS baker_actions` block (starts
at `tests/conftest.py:281`) does NOT need updating — it's gated by
`IF NOT EXISTS` and the `ALTER` block adds `reserved_at` whether the
table came from the CREATE branch or already existed.

### Key constraints

- Idempotent — `ADD COLUMN IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`.
- Do NOT remove the existing `idx_baker_actions_tier_b_committed` block.
- Order matters: the ALTER must come BEFORE either index DDL.

### Verification

`pytest tests/test_tier_b_runtime.py -v` — all existing tests still pass
(once Fix 3 lands; until then they may fail on the new INSERT-on-PASS
behavior, which is expected and addressed in Fix 6).

---

## Fix 3: Refactor `tier_b_runtime.py` — Pattern B core

### Problem

Current `enforce()` PASS path commits the SERIALIZABLE txn without
writing anything. SSI sees no rw-anti-dependency, so concurrent enforcers
both pass cap. Closing the gap = make the PASS path INSERT a reservation
row, so SSI catches concurrent readers as a rw-conflict and one retries.

### Current state

`orchestrator/tier_b_runtime.py:139-260` — the `enforce()` method. Lines
178-198 (day/month total reads), lines 200-206 (cap eval), lines 208-235
(PAUSE path), lines 237-246 (PASS path commits + returns). Module
docstring lines 21-28 carries the V1-atomicity-disclaimer + FIXME(B4)
note that must be replaced.

### Implementation

Replace the entire file. Below is the complete new content (copy-paste):

```python
"""Tier B autonomous-action budget runtime.

Forward-looking gate: future call-sites (Cortex Phase 5, B5 substrate
push, autonomous senders) call ``enforce_tier_b(action)`` BEFORE the
external side effect. On PASS the runtime reserves the budget inside a
SERIALIZABLE transaction (writes a ``baker_actions`` row with
``committed_at=NULL`` + ``reserved_at=NOW()``) and returns a
``reservation_id``. Caller performs the side effect, then calls
``confirm_tier_b(reservation_id)`` (success) or
``cancel_tier_b(reservation_id)`` (failure). On PAUSE_REQUIRED the
candidate is queued in ``tier_b_pending``; Director ratify card emitted
via ``orchestrator/tier_b_ratify.py``.

Caps (D8 Conservative tier, Director-ratified 2026-05-10):
    PER_ACTION    = €100
    DAILY_POOL    = €500
    MONTHLY_POOL  = €2,500
    Reset         = 1st of calendar month, 00:00 UTC

Cost source (Q2 mixed model):
    Primary  : ``tier_b_action_classes`` registry lookup
    Fallback : committer self-declares with ``action_class='novel:<descriptor>'``
               + ``self_cost_eur`` (flagged for AID monthly review)

Pool-wide atomicity (V2, Pattern B reservation-row, Director-ratified
2026-05-10 PM):
    PASS path INSERTs a reservation row inside SERIALIZABLE. SSI sees the
    rw-anti-dependency between the cap-read SELECT and the reservation
    INSERT; concurrent enforcers at the same day/month bucket get one
    retried (psycopg2.errors.SerializationFailure surfaces to caller, who
    retries the whole ``enforce_tier_b()`` call — second attempt sees the
    new committed/reserved totals and PAUSEs if cap blown).

    Cap reads count both committed actions AND active reservations (those
    with ``reserved_at`` within the 15-min TTL window). Expired
    reservations are swept by ``triggers/tier_b_reservation_sweep.py``
    every 5 min — caller crash between reserve and confirm/cancel
    eventually releases the budget.

    SerializationFailure idempotency: when SSI aborts a transaction, the
    aborted transaction's writes are never committed by Postgres. Caller
    can safely retry ``enforce_tier_b()`` after catching the exception —
    the retry starts clean (no partial reservation row), reads now-updated
    totals (including the winning enforcer's reservation), and
    re-evaluates the cap. No double-reservation risk.

    Audit trail: cancelled or swept reservations are DELETEd (not
    soft-deleted). Intentional — a reservation that was never confirmed
    represents an autonomous action that NEVER EXECUTED, so an audit row
    would mis-state the historical spend record. The PAUSE_REQUIRED path
    remains audited via ``tier_b_pending``; the PASS-then-confirm path is
    audited via the persisted ``baker_actions`` row (committed_at set).

    Caller contract::

        decision = enforce_tier_b(action)
        if decision.verdict == "PAUSE_REQUIRED":
            return   # ratify card already queued in tier_b_pending
        try:
            actually_execute(...)          # external side effect
            confirm_tier_b(decision.reservation_id)
        except Exception:
            cancel_tier_b(decision.reservation_id)
            raise
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Literal, Optional

import psycopg2.extensions

from memory.store_back import SentinelStoreBack

logger = logging.getLogger(__name__)

# Cap constants — Director-ratified D8 Conservative tier 2026-05-10.
PER_ACTION_CAP_EUR = 100.00
DAILY_POOL_CAP_EUR = 500.00
MONTHLY_POOL_CAP_EUR = 2500.00

# Reservation TTL — Director-ratified 2026-05-10 PM. After this window
# without a confirm_tier_b()/cancel_tier_b() call, the sweep job deletes
# the reservation; budget returns to the pool. Tighter window pressures
# slow callers; looser window ties up cap on caller crash.
RESERVATION_TTL_MINUTES = 15


@dataclass(frozen=True)
class TierBAction:
    """Candidate Tier-B action under enforcement."""

    action_class: str
    committer_agent: str
    payload: dict
    self_cost_eur: Optional[float] = None


@dataclass(frozen=True)
class Decision:
    """Result of ``enforce_tier_b()`` — caller routes by ``verdict``.

    On PASS, ``reservation_id`` is the ``baker_actions.id`` of the row
    just reserved; caller MUST call confirm_tier_b/cancel_tier_b within
    ``RESERVATION_TTL_MINUTES`` or the sweep job will reclaim the budget.

    On PAUSE_REQUIRED, ``pending_id`` is the ``tier_b_pending.id`` row
    waiting on Director ratify.
    """

    verdict: Literal["PASS", "PAUSE_REQUIRED"]
    cost_eur: float
    reason: str
    reservation_id: Optional[int] = None  # set on PASS
    pending_id: Optional[int] = None      # set on PAUSE_REQUIRED


class TierBRuntime:
    """Singleton: budget enforcement gate. Use ``_get_global_instance()``."""

    _instance = None

    @classmethod
    def _get_global_instance(cls) -> "TierBRuntime":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._store = SentinelStoreBack._get_global_instance()

    # ------------------------------------------------------------------
    # Cost resolution
    # ------------------------------------------------------------------

    def _resolve_cost(self, action: TierBAction) -> tuple[float, str]:
        """Resolve (cost_eur, source_tag) for an action.

        ``source_tag`` ∈ {registry, self_declared}. Runs against a separate
        pooled connection at default isolation — NOT inside enforce()'s
        SERIALIZABLE txn. Registry rarely changes during a cycle so the
        read-skew window is acceptable for V1.
        """
        if action.action_class.startswith("novel:"):
            if action.self_cost_eur is None:
                raise ValueError(
                    f"action_class={action.action_class!r} requires self_cost_eur"
                )
            if action.self_cost_eur < 0:
                raise ValueError(
                    f"self_cost_eur must be non-negative (got {action.self_cost_eur}); "
                    f"negative values would bypass daily/monthly cap math"
                )
            return float(action.self_cost_eur), "self_declared"

        conn = self._store._get_conn()
        if conn is None:
            raise RuntimeError("no DB connection — cannot resolve action_class cost")
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT eur_cost FROM tier_b_action_classes "
                "WHERE class_name = %s AND deprecated_at IS NULL "
                "LIMIT 1",
                (action.action_class,),
            )
            row = cur.fetchone()
            cur.close()
            if row is None:
                raise ValueError(
                    f"unknown action_class {action.action_class!r}; "
                    f"register it in tier_b_action_classes or use 'novel:<descriptor>' with self_cost_eur"
                )
            return float(row[0]), "registry"
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            self._store._put_conn(conn)

    # ------------------------------------------------------------------
    # Enforcement (Pattern B reservation-row)
    # ------------------------------------------------------------------

    def enforce(self, action: TierBAction) -> Decision:
        """Decide PASS or PAUSE_REQUIRED.

        Pool-wide atomicity guaranteed by SERIALIZABLE: cap-reads include
        active reservations; PASS path INSERTs a reservation row before
        commit. Concurrent enforcers at the same bucket overlap their
        read+write sets; SSI raises ``SerializationFailure`` on one,
        caller retries the whole ``enforce_tier_b()`` call.
        """
        cost_eur, source_tag = self._resolve_cost(action)

        conn = self._store._get_conn()
        if conn is None:
            raise RuntimeError("no DB connection — cannot enforce Tier-B")
        old_iso = conn.isolation_level
        try:
            conn.set_isolation_level(
                psycopg2.extensions.ISOLATION_LEVEL_SERIALIZABLE
            )
        except Exception:
            # Older psycopg2 / driver edge case — fall back to in-txn SET.
            cur = conn.cursor()
            cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            cur.close()
        try:
            cur = conn.cursor()

            # Day-bucket cap read: committed today OR reserved-and-active.
            cur.execute(
                """
                SELECT COALESCE(SUM(cost_eur), 0)
                  FROM baker_actions
                 WHERE tier = 'B' AND cost_eur IS NOT NULL
                   AND (
                       (committed_at IS NOT NULL
                        AND committed_at >= DATE_TRUNC('day', NOW() AT TIME ZONE 'UTC'))
                    OR (committed_at IS NULL
                        AND reserved_at IS NOT NULL
                        AND reserved_at >= NOW() AT TIME ZONE 'UTC'
                                        - (%s || ' minutes')::interval)
                   )
                 LIMIT 100000
                """,
                (str(RESERVATION_TTL_MINUTES),),
            )
            day_total = float(cur.fetchone()[0])

            # Month-bucket cap read: same pattern, monthly window.
            cur.execute(
                """
                SELECT COALESCE(SUM(cost_eur), 0)
                  FROM baker_actions
                 WHERE tier = 'B' AND cost_eur IS NOT NULL
                   AND (
                       (committed_at IS NOT NULL
                        AND committed_at >= DATE_TRUNC('month', NOW() AT TIME ZONE 'UTC'))
                    OR (committed_at IS NULL
                        AND reserved_at IS NOT NULL
                        AND reserved_at >= NOW() AT TIME ZONE 'UTC'
                                        - (%s || ' minutes')::interval)
                   )
                 LIMIT 100000
                """,
                (str(RESERVATION_TTL_MINUTES),),
            )
            month_total = float(cur.fetchone()[0])

            paused_reason: Optional[str] = None
            if cost_eur > PER_ACTION_CAP_EUR:
                paused_reason = "per_action_cap"
            elif day_total + cost_eur > DAILY_POOL_CAP_EUR:
                paused_reason = "daily_cap"
            elif month_total + cost_eur > MONTHLY_POOL_CAP_EUR:
                paused_reason = "monthly_cap"

            if paused_reason:
                cur.execute(
                    """
                    INSERT INTO tier_b_pending
                        (action_payload, cost_eur, action_class, committer_agent, reason_paused)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        self._jsonify(action.payload),
                        cost_eur,
                        action.action_class,
                        action.committer_agent,
                        paused_reason,
                    ),
                )
                pending_id = int(cur.fetchone()[0])
                conn.commit()
                cur.close()
                return Decision(
                    verdict="PAUSE_REQUIRED",
                    cost_eur=cost_eur,
                    reason=(
                        f"{paused_reason} — cost €{cost_eur:.2f}, "
                        f"day=€{day_total:.2f}, month=€{month_total:.2f}"
                    ),
                    pending_id=pending_id,
                )

            # PASS — write reservation row inside the same SERIALIZABLE txn.
            # Critical: this INSERT is what gives SSI the rw-conflict to detect
            # against a concurrent enforcer's day/month-total SELECT.
            cur.execute(
                """
                INSERT INTO baker_actions
                    (action_type, payload, trigger_source, success,
                     tier, cost_eur, committed_at, reserved_at,
                     committer_agent, action_class,
                     self_cost_eur)
                VALUES (
                    'tier_b_reservation', %s::jsonb, 'tier_b_runtime', TRUE,
                    'B', %s, NULL, NOW() AT TIME ZONE 'UTC',
                    %s, %s,
                    %s
                )
                RETURNING id
                """,
                (
                    self._jsonify(action.payload),
                    cost_eur,
                    action.committer_agent,
                    action.action_class,
                    action.self_cost_eur,
                ),
            )
            reservation_id = int(cur.fetchone()[0])
            conn.commit()
            cur.close()
            return Decision(
                verdict="PASS",
                cost_eur=cost_eur,
                reason=(
                    f"PASS via {source_tag} — reserved €{cost_eur:.2f}; "
                    f"projected day=€{day_total + cost_eur:.2f}, "
                    f"month=€{month_total + cost_eur:.2f}"
                ),
                reservation_id=reservation_id,
            )
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            # Restore the connection's isolation level before returning to the
            # pool so the next caller is not surprised by SERIALIZABLE.
            try:
                conn.set_isolation_level(old_iso)
            except Exception:
                pass
            self._store._put_conn(conn)

    # ------------------------------------------------------------------
    # Reservation lifecycle (Pattern B)
    # ------------------------------------------------------------------

    def confirm(self, reservation_id: int) -> bool:
        """Mark a reservation as committed (post-success).

        Tiny single-row UPDATE — low conflict surface. Returns True iff a
        row was flipped from reserved to committed. Returns False if the
        row was already committed (idempotent retry), was cancelled, or
        was swept (TTL expired before caller called us).
        """
        conn = self._store._get_conn()
        if conn is None:
            raise RuntimeError("no DB connection — cannot confirm reservation")
        try:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE baker_actions
                   SET committed_at = NOW() AT TIME ZONE 'UTC'
                 WHERE id = %s
                   AND committed_at IS NULL
                   AND reserved_at IS NOT NULL
                RETURNING id
                """,
                (reservation_id,),
            )
            row = cur.fetchone()
            conn.commit()
            cur.close()
            if row is None:
                logger.warning(
                    "confirm_tier_b: reservation_id=%s not found or already committed/swept",
                    reservation_id,
                )
                return False
            return True
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            self._store._put_conn(conn)

    def cancel(self, reservation_id: int) -> bool:
        """Release a reservation (post-failure).

        DELETEs the reservation row — budget returns to the pool. Returns
        True iff a row was deleted; False if already committed (caller
        signalled failure too late) or already swept.
        """
        conn = self._store._get_conn()
        if conn is None:
            raise RuntimeError("no DB connection — cannot cancel reservation")
        try:
            cur = conn.cursor()
            cur.execute(
                """
                DELETE FROM baker_actions
                 WHERE id = %s
                   AND committed_at IS NULL
                   AND reserved_at IS NOT NULL
                RETURNING id
                """,
                (reservation_id,),
            )
            row = cur.fetchone()
            conn.commit()
            cur.close()
            if row is None:
                logger.warning(
                    "cancel_tier_b: reservation_id=%s not found or already committed",
                    reservation_id,
                )
                return False
            return True
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            self._store._put_conn(conn)

    @staticmethod
    def _jsonify(payload: dict) -> str:
        return json.dumps(payload, default=str)


def enforce_tier_b(action: TierBAction) -> Decision:
    """Module-level shorthand. Call this from runtime call-sites."""
    return TierBRuntime._get_global_instance().enforce(action)


def confirm_tier_b(reservation_id: int) -> bool:
    """Module-level shorthand — mark reservation committed (post-success)."""
    return TierBRuntime._get_global_instance().confirm(reservation_id)


def cancel_tier_b(reservation_id: int) -> bool:
    """Module-level shorthand — release reservation (post-failure)."""
    return TierBRuntime._get_global_instance().cancel(reservation_id)
```

### Key constraints

- **Do NOT change cap constants** (`PER_ACTION_CAP_EUR`, `DAILY_POOL_CAP_EUR`,
  `MONTHLY_POOL_CAP_EUR`) — Director-ratified D8 values.
- **Do NOT remove `_jsonify`** — used by both PASS and PAUSE paths.
- **Do NOT change `_resolve_cost` body** — only the section after the
  negative-cost guard is intact; the registry lookup branch is unchanged.
- **The PASS-path INSERT must use parameterized values** (psycopg2 `%s`
  substitution) — never f-string the cost_eur or any caller-controlled
  field into the SQL string.
- **TTL constant `RESERVATION_TTL_MINUTES` is sourced from this module** —
  do not parameterize via env var in this brief. (Future tuning can add
  an env override; out of scope for V1.)
- **The cap-read SQL uses `(%s || ' minutes')::interval`** rather than
  `INTERVAL '15 minutes'`. This is so the TTL constant feeds in
  programmatically. Verified syntactically valid: `cast(%s || ' minutes'
  AS interval)`.

### Verification

After Fix 6 lands the new tests, run:
```bash
pytest tests/test_tier_b_runtime.py tests/test_tier_b_atomicity.py -v
```
All existing tests + new concurrent-load test pass.

---

## Fix 4: Sweep job for orphan reservations

### Problem

If a caller crashes between `enforce_tier_b(...)` returning PASS and the
matching `confirm_tier_b()` / `cancel_tier_b()` call, the reservation
row stays in `baker_actions` with `committed_at IS NULL` indefinitely.
Cap-reads count it for the first 15 min (TTL window), then stop seeing
it — but the row sits forever and bloats the table. Sweep job removes
expired orphans.

### Current state

`triggers/tier_b_reset.py` exists for the calendar-month reset audit.
We add a sibling `triggers/tier_b_reservation_sweep.py` and register it
at the embedded scheduler.

### Implementation

Create `triggers/tier_b_reservation_sweep.py`:

```python
"""Tier B reservation sweep — clears orphan reservations past TTL.

Runs every 5 min via APScheduler. Pattern B atomicity (see
``orchestrator/tier_b_runtime.py``) writes ``baker_actions`` rows with
``committed_at=NULL`` + ``reserved_at=NOW()`` on PASS. Caller is expected
to call ``confirm_tier_b()`` or ``cancel_tier_b()`` within
``RESERVATION_TTL_MINUTES`` (15 min). If the caller crashed in the
window, this job removes the orphan so the budget returns to the pool
(it already stopped counting against caps once TTL expired — this just
prevents indefinite row bloat).

Idempotent + bounded: query is LIMITed at 1000 rows per run (worst-case
sweep size is tiny — a busy day might have ~1 orphan).
"""
from __future__ import annotations

import logging

from memory.store_back import SentinelStoreBack
from orchestrator.tier_b_runtime import RESERVATION_TTL_MINUTES

logger = logging.getLogger(__name__)


def tier_b_reservation_sweep() -> int:
    """APScheduler entrypoint: delete expired orphan reservations.

    Returns the row count deleted (for logging / ops visibility).
    """
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    if conn is None:
        logger.error("tier_b_reservation_sweep: no DB connection — skipping")
        return 0
    try:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM baker_actions
             WHERE id IN (
                 SELECT id FROM baker_actions
                  WHERE tier = 'B'
                    AND committed_at IS NULL
                    AND reserved_at IS NOT NULL
                    AND reserved_at < NOW() AT TIME ZONE 'UTC'
                                    - (%s || ' minutes')::interval
                  LIMIT 1000
             )
            RETURNING id
            """,
            (str(RESERVATION_TTL_MINUTES),),
        )
        deleted = cur.fetchall()
        count = len(deleted)
        conn.commit()
        cur.close()
        if count:
            logger.info(
                "tier_b_reservation_sweep: deleted %d orphan reservations "
                "(>%d min old)",
                count, RESERVATION_TTL_MINUTES,
            )
        return count
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(f"tier_b_reservation_sweep failed: {e}")
        raise
    finally:
        store._put_conn(conn)
```

### Register the job at `triggers/embedded_scheduler.py`

Locate the existing `tier_b_counter_reset` registration block (around
lines 1041-1049). Immediately AFTER that block, add the sweep
registration:

```python
    # BRIEF_CORTEX_TIER_B_ATOMICITY_V1: Pattern B sweep.
    # Every 5 min, delete orphan reservations past the 15-min TTL so
    # crashed callers don't leave budget tied up forever.
    from triggers.tier_b_reservation_sweep import tier_b_reservation_sweep
    scheduler.add_job(
        tier_b_reservation_sweep,
        IntervalTrigger(minutes=5),
        id="tier_b_reservation_sweep",
        name="Tier B reservation sweep (orphan reaper)",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    logger.info("Registered: tier_b_reservation_sweep (every 5 min)")
```

### Key constraints

- **`IntervalTrigger` is already imported** at the top of
  `embedded_scheduler.py` — verify the import block contains
  `from apscheduler.triggers.interval import IntervalTrigger`. If
  missing, add it; do NOT add new from-scratch imports.
- **DELETE is bounded** — `LIMIT 1000` inside the subquery prevents
  pathological runaway if something seeds millions of orphans.
- **Wrapped in try/except + `conn.rollback()`** — fault-tolerant per repo
  rule.
- **Log only when count > 0** — avoid noisy "deleted 0 orphans" every
  5 min in production.

### Verification

- `grep -n "tier_b_reservation_sweep" triggers/embedded_scheduler.py` →
  one match (the registration block).
- Render startup log line after deploy:
  `Registered: tier_b_reservation_sweep (every 5 min)`
- After running test cycles that crash mid-reservation, `SELECT COUNT(*)
  FROM baker_actions WHERE tier='B' AND committed_at IS NULL AND
  reserved_at < NOW() - INTERVAL '15 minutes'` should be 0 within 5 min.

---

## Fix 5: Update existing test_tier_b_runtime.py tests

### Problem

Existing tests in `tests/test_tier_b_runtime.py` assert against the V1
`Decision` shape (no `reservation_id`). After Fix 3, PASS Decisions
carry a `reservation_id`; PAUSE_REQUIRED Decisions still carry only
`pending_id`. Existing assertions must be updated.

### Implementation

Edit `tests/test_tier_b_runtime.py`. Three tests need updating; the rest
are unaffected.

**Test 1** — `test_pass_under_caps` (currently at line 37-47):
Old:
```python
def test_pass_under_caps(clean_baker_actions, register_class):
    register_class("test.synthetic", 1.00)
    action = TierBAction(
        action_class="test.synthetic",
        committer_agent="b3",
        payload={"smoke": True},
    )
    decision = enforce_tier_b(action)
    assert decision.verdict == "PASS"
    assert decision.cost_eur == 1.00
    assert decision.pending_id is None
```
New (only the last 3 lines changed):
```python
def test_pass_under_caps(clean_baker_actions, register_class):
    register_class("test.synthetic", 1.00)
    action = TierBAction(
        action_class="test.synthetic",
        committer_agent="b3",
        payload={"smoke": True},
    )
    decision = enforce_tier_b(action)
    assert decision.verdict == "PASS"
    assert decision.cost_eur == 1.00
    assert decision.pending_id is None
    assert decision.reservation_id is not None
    assert isinstance(decision.reservation_id, int)
```

**Test 2** — `test_novel_class_with_self_cost_passes` (currently at
line 134-143): same shape update — add `assert decision.reservation_id
is not None` after the existing `assert decision.cost_eur == 42.00`.

**Test 3** — no test currently asserts `pending_id is None` on PASS in a
form that would break; the existing assertion is correct (PASS still has
pending_id IS None). No change needed beyond Tests 1 and 2.

### Key constraints

- **Do NOT remove** any existing assertions — additive only.
- **Do NOT change** the cap-related tests (`test_per_action_cap_paused`,
  `test_daily_cap_paused`, `test_monthly_cap_paused`,
  `test_pool_wide_isolation_between_agents`, `test_pending_row_persisted_on_pause`)
  — PAUSE-path semantics are unchanged; they continue to assert
  pending_id is not None and reservation_id remains None (the dataclass
  default).
- **The negative-cost / unknown-class tests** raise ValueError before
  any DB write — unchanged.

---

## Fix 6: New tests — concurrent-load + reservation lifecycle + sweep

### Problem

Hard acceptance criterion #3 from the precursor: "Add load test for the
original concurrent-commits scenario: two enforcers at €499 day-total
must NOT both PASS." This is the ship-gate test; if it fails on first
run, atomicity is broken and the brief reverts to design re-think.

Additionally: confirm/cancel lifecycle + sweep job behavior need
coverage.

### Implementation

Create `tests/test_tier_b_atomicity.py`:

```python
"""Live-PG tests for Pattern B atomicity closure.

The headline test is ``test_concurrent_enforcers_one_passes_one_pauses``
— the precursor's hard acceptance criterion. Two enforcers at €499
day-total racing on a €5 candidate: exactly one PASSes, one PAUSEs.

Coverage:
    * PASS path writes a reservation row (committed_at IS NULL,
      reserved_at IS NOT NULL) inside SERIALIZABLE
    * confirm flips committed_at and is idempotent on second call
    * cancel deletes the reservation row and is idempotent
    * sweep removes expired orphans + leaves fresh reservations alone
    * concurrent-load atomicity (THE ship-gate)
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from orchestrator.tier_b_runtime import (
    DAILY_POOL_CAP_EUR,
    RESERVATION_TTL_MINUTES,
    Decision,
    TierBAction,
    cancel_tier_b,
    confirm_tier_b,
    enforce_tier_b,
)


# ----------------------------------------------------------------------
# Reservation row shape
# ----------------------------------------------------------------------


def test_pass_writes_reservation_row(
    clean_baker_actions, register_class, tier_b_test_store,
):
    register_class("test.synthetic", 1.00)
    action = TierBAction(
        action_class="test.synthetic",
        committer_agent="b3",
        payload={"reservation_shape": True},
    )
    decision = enforce_tier_b(action)
    assert decision.verdict == "PASS"
    assert decision.reservation_id is not None

    conn = tier_b_test_store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT tier, cost_eur, committed_at, reserved_at, "
            "       committer_agent, action_class "
            "FROM baker_actions WHERE id = %s",
            (decision.reservation_id,),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        tier_b_test_store._put_conn(conn)
    assert row is not None
    tier, cost, committed_at, reserved_at, agent, klass = row
    assert tier == "B"
    assert float(cost) == 1.00
    assert committed_at is None
    assert reserved_at is not None
    assert agent == "b3"
    assert klass == "test.synthetic"


# ----------------------------------------------------------------------
# confirm / cancel lifecycle
# ----------------------------------------------------------------------


def test_confirm_marks_committed(
    clean_baker_actions, register_class, tier_b_test_store,
):
    register_class("test.synthetic", 1.00)
    decision = enforce_tier_b(TierBAction(
        action_class="test.synthetic", committer_agent="b3", payload={},
    ))
    assert decision.verdict == "PASS"
    assert confirm_tier_b(decision.reservation_id) is True

    conn = tier_b_test_store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT committed_at FROM baker_actions WHERE id = %s",
            (decision.reservation_id,),
        )
        (committed_at,) = cur.fetchone()
        cur.close()
    finally:
        tier_b_test_store._put_conn(conn)
    assert committed_at is not None

    # Idempotent — second confirm returns False (already committed).
    assert confirm_tier_b(decision.reservation_id) is False


def test_cancel_removes_reservation(
    clean_baker_actions, register_class, tier_b_test_store,
):
    register_class("test.synthetic", 1.00)
    decision = enforce_tier_b(TierBAction(
        action_class="test.synthetic", committer_agent="b3", payload={},
    ))
    assert decision.verdict == "PASS"
    assert cancel_tier_b(decision.reservation_id) is True

    conn = tier_b_test_store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM baker_actions WHERE id = %s",
            (decision.reservation_id,),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        tier_b_test_store._put_conn(conn)
    assert row is None  # reservation deleted

    # Idempotent — second cancel returns False (row gone).
    assert cancel_tier_b(decision.reservation_id) is False


def test_cancel_after_confirm_is_noop(
    clean_baker_actions, register_class, tier_b_test_store,
):
    """Cancel after the action committed should NOT delete the row."""
    register_class("test.synthetic", 1.00)
    decision = enforce_tier_b(TierBAction(
        action_class="test.synthetic", committer_agent="b3", payload={},
    ))
    confirm_tier_b(decision.reservation_id)
    assert cancel_tier_b(decision.reservation_id) is False

    conn = tier_b_test_store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT committed_at FROM baker_actions WHERE id = %s",
            (decision.reservation_id,),
        )
        (committed_at,) = cur.fetchone()
        cur.close()
    finally:
        tier_b_test_store._put_conn(conn)
    assert committed_at is not None  # row still committed, intact


# ----------------------------------------------------------------------
# Reservation counts toward cap (TTL window)
# ----------------------------------------------------------------------


def test_reservation_counts_toward_cap_within_ttl(
    clean_baker_actions, register_class,
):
    """Reservation alone (no confirm) blocks a 2nd PASS that would breach cap."""
    register_class("test.big_one", 99.00)
    # First call reserves €99 (no confirm).
    first = enforce_tier_b(TierBAction(
        action_class="test.big_one", committer_agent="ah1", payload={},
    ))
    assert first.verdict == "PASS"

    # Stack reservations until just under €500. 5 × €99 = €495 reserved.
    for _ in range(4):
        d = enforce_tier_b(TierBAction(
            action_class="test.big_one", committer_agent="ah1", payload={},
        ))
        assert d.verdict == "PASS"

    # Sixth call (would push to €594 reserved) → daily cap PAUSE.
    sixth = enforce_tier_b(TierBAction(
        action_class="test.big_one", committer_agent="b3", payload={},
    ))
    assert sixth.verdict == "PAUSE_REQUIRED"
    assert "daily_cap" in sixth.reason


# ----------------------------------------------------------------------
# THE ship-gate: concurrent enforcers at €499 day-total
# ----------------------------------------------------------------------


def test_concurrent_enforcers_one_passes_one_pauses(
    clean_baker_actions, register_class, seed_committed_today,
):
    """Hard acceptance criterion (B4_PRECURSOR §3.3).

    Seed €495 day-total. Two enforcers race a €5 candidate.

      • First-to-commit reaches €500 day-total (at cap, NOT over → PASS).
        Reservation row makes the second enforcer's cap-read see €500.
      • Second-to-commit sees €500 + €5 = €505 > €500 → PAUSE_REQUIRED.

    Pre-Pattern-B failure mode: both enforcers SELECT €495, both eval
    PASS (€500 not > €500), both commit, pool over-spends to €505.
    Pattern B fix: PASS path INSERTs reservation inside SERIALIZABLE; SSI
    rw-conflict on the second commit raises SerializationFailure; retry
    sees the now-€500 reserved total and PAUSEs.

    Seed math: 5 × €99 = €495 committed today (NOT €499 — the cap-eval
    is strict-greater-than, so €499 + €5 = €504 would PAUSE both
    enforcers without ever exercising the race).
    """
    register_class("test.five", 5.00)
    # Seed €495 already committed today: 5 × €99.
    seed_committed_today(
        class_name="test.synthetic", count=5, agent="ah1", eur_cost=99.00,
    )

    decisions: list[Decision] = []
    errors: list[Exception] = []
    barrier = threading.Barrier(2, timeout=10)

    def _race(committer: str) -> None:
        action = TierBAction(
            action_class="test.five",
            committer_agent=committer,
            payload={"committer": committer},
        )
        try:
            # Wait for both threads at the barrier so the SELECTs race.
            barrier.wait()
            # Retry up to 3 times on SerializationFailure — Postgres SSI
            # surfaces it as a deferrable error; caller is expected to
            # retry. Each retry runs a fresh enforce() with fresh reads.
            for attempt in range(3):
                try:
                    decisions.append(enforce_tier_b(action))
                    return
                except Exception as e:
                    if "could not serialize" in str(e).lower() or (
                        e.__class__.__name__ == "SerializationFailure"
                    ):
                        continue
                    raise
            raise RuntimeError("3 SerializationFailure retries exhausted")
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=_race, args=("ah1",))
    t2 = threading.Thread(target=_race, args=("b3",))
    t1.start(); t2.start()
    t1.join(timeout=15); t2.join(timeout=15)

    assert not errors, f"unexpected errors: {errors}"
    assert len(decisions) == 2, f"expected 2 decisions, got {decisions}"

    verdicts = sorted(d.verdict for d in decisions)
    assert verdicts == ["PASS", "PAUSE_REQUIRED"], (
        f"Pattern B atomicity failure: both threads got {verdicts} at "
        f"€495 seeded day-total. Race winner reserves €5 (→ €500 at cap, "
        f"PASS). Loser must see the €500 reserved total and PAUSE. If both "
        f"got PASS, SSI failed to detect the rw-conflict — the brief's "
        f"atomicity argument is invalidated; revert and re-design."
    )

    # The PAUSE should cite daily_cap.
    paused = next(d for d in decisions if d.verdict == "PAUSE_REQUIRED")
    assert "daily_cap" in paused.reason


# ----------------------------------------------------------------------
# Sweep job
# ----------------------------------------------------------------------


def test_sweep_deletes_expired_orphans(
    clean_baker_actions, register_class, tier_b_test_store,
):
    """Sweep removes reservations with reserved_at past TTL."""
    register_class("test.synthetic", 1.00)
    fresh = enforce_tier_b(TierBAction(
        action_class="test.synthetic", committer_agent="b3", payload={},
    ))
    assert fresh.verdict == "PASS"

    # Manually age a 2nd reservation past TTL by direct SQL.
    expired_id = _seed_reserved(
        tier_b_test_store,
        cost_eur=1.00,
        agent="ah1",
        reserved_at_offset_minutes=-(RESERVATION_TTL_MINUTES + 1),
    )

    from triggers.tier_b_reservation_sweep import tier_b_reservation_sweep
    deleted = tier_b_reservation_sweep()
    assert deleted == 1  # only the expired one

    # Fresh reservation untouched.
    conn = tier_b_test_store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM baker_actions WHERE id = %s", (fresh.reservation_id,),
        )
        assert cur.fetchone() is not None
        cur.execute(
            "SELECT id FROM baker_actions WHERE id = %s", (expired_id,),
        )
        assert cur.fetchone() is None
        cur.close()
    finally:
        tier_b_test_store._put_conn(conn)


def test_sweep_leaves_committed_alone(
    clean_baker_actions, register_class, tier_b_test_store,
):
    """Sweep MUST NOT touch committed rows even if they're old."""
    register_class("test.synthetic", 1.00)
    decision = enforce_tier_b(TierBAction(
        action_class="test.synthetic", committer_agent="b3", payload={},
    ))
    confirm_tier_b(decision.reservation_id)

    # Age the committed_at + reserved_at past TTL.
    conn = tier_b_test_store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE baker_actions "
            "   SET reserved_at = NOW() AT TIME ZONE 'UTC' - INTERVAL '1 hour' "
            " WHERE id = %s",
            (decision.reservation_id,),
        )
        conn.commit()
        cur.close()
    finally:
        tier_b_test_store._put_conn(conn)

    from triggers.tier_b_reservation_sweep import tier_b_reservation_sweep
    deleted = tier_b_reservation_sweep()
    assert deleted == 0

    conn = tier_b_test_store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM baker_actions WHERE id = %s", (decision.reservation_id,),
        )
        assert cur.fetchone() is not None
        cur.close()
    finally:
        tier_b_test_store._put_conn(conn)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _seed_reserved(
    store, *, cost_eur: float, agent: str, reserved_at_offset_minutes: int,
) -> int:
    """Insert a reservation row at a specific reserved_at offset.

    Used to seed expired/orphan reservations for sweep tests.
    """
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO baker_actions
                (action_type, payload, trigger_source, success,
                 tier, cost_eur, committed_at, reserved_at,
                 committer_agent, action_class)
            VALUES (
                'tier_b_reservation', '{}'::jsonb, 'test_seed', TRUE,
                'B', %s, NULL,
                (NOW() AT TIME ZONE 'UTC') + (%s || ' minutes')::interval,
                %s, 'test.synthetic'
            )
            RETURNING id
            """,
            (cost_eur, str(reserved_at_offset_minutes), agent),
        )
        new_id = int(cur.fetchone()[0])
        conn.commit()
        cur.close()
    finally:
        store._put_conn(conn)
    return new_id
```

### Key constraints

- **`threading.Barrier(2, timeout=10)`** — without the barrier the two
  threads run sequentially and never race. The barrier guarantees both
  hit `enforce_tier_b()` near-simultaneously. Timeout is the test
  timeout, not the wait.
- **SerializationFailure retry loop** — Postgres surfaces it as a
  `psycopg2.errors.SerializationFailure` (subclass of `OperationalError`).
  The pattern: catch by message-match (`"could not serialize"`) OR
  class-name match. 3 retries is generous for a 2-thread race.
- **`_seed_reserved`** uses `INSERT … RETURNING id` (same shape as
  existing `_seed_committed` in conftest) so the test can target the
  exact row.
- **The ship-gate test asserts `verdicts == ["PASS", "PAUSE_REQUIRED"]`**
  — this is THE check the brief lives or dies on. Read carefully: at
  €499 committed + €5 candidate, the FIRST PASS reserves €5 making total
  €504 (over cap). Therefore the second enforcer MUST see the
  reservation in its cap-read (via SSI ordering) and PAUSE.
  - Edge case: if both threads' SELECTs run before either INSERT
    commits, SSI raises SerializationFailure on the second commit;
    that thread retries; on retry, cap-read sees the committed
    reservation; PAUSEs. Either way, the test passes.
- **Wall-clock budget per test:** ~15s max. The barrier+race+commit
  cycle is ~100ms.

### Verification

```bash
pytest tests/test_tier_b_atomicity.py -v
# Expect 7 passes (assuming TEST_DATABASE_URL or Neon CI key set).
# All other Tier B tests must remain green:
pytest tests/test_tier_b_runtime.py tests/test_tier_b_reset.py -v
```

---

## Files Modified

- `migrations/20260511_baker_actions_reservation.sql` — (NEW) add
  `reserved_at` column + reservation-aware partial index
- `tests/conftest.py` — mirror migration in `_bootstrap_tier_b_schema`
- `orchestrator/tier_b_runtime.py` — Pattern B refactor (Decision +
  enforce + confirm + cancel + module funcs)
- `triggers/tier_b_reservation_sweep.py` — (NEW) sweep job
- `triggers/embedded_scheduler.py` — register sweep job every 5 min
- `tests/test_tier_b_runtime.py` — update 2 PASS-path tests for
  `reservation_id` assertion (additive)
- `tests/test_tier_b_atomicity.py` — (NEW) ship-gate concurrent-load
  test + lifecycle + sweep tests

## Do NOT Touch

- `orchestrator/tier_b_ratify.py` — already shipped; PAUSE_REQUIRED path
  unchanged in this brief
- `orchestrator/cortex_phase5_act.py` — Phase 5 V2 audit-log uplift is
  deferred to a separate brief
- Any `cortex_phase*.py` module — no Cortex changes in this brief
- `tier_b_counter_reset` job and its registration — calendar-month
  reset is unrelated to per-action atomicity
- `migrations/20260510_baker_actions_tier_b_runtime.sql` — already
  applied; never edit applied migrations (CLAUDE.md rule)
- Cap constants `PER_ACTION_CAP_EUR` / `DAILY_POOL_CAP_EUR` /
  `MONTHLY_POOL_CAP_EUR` — Director-ratified D8 values, never change in
  this brief

## Quality Checkpoints

1. Migration applies cleanly on a fresh Neon branch (idempotent rerun
   safe).
2. `pytest tests/test_tier_b_runtime.py tests/test_tier_b_atomicity.py
   tests/test_tier_b_reset.py -v` — all green on live-PG CI.
3. `bash scripts/check_singletons.sh` — no rogue `TierBRuntime()` calls
   introduced. (The existing block at lines 31-42 already covers
   `TierBRuntime`; module-level `confirm_tier_b` / `cancel_tier_b`
   wrappers use the singleton accessor too — verify by grep.)
4. `python3 -c "import py_compile; py_compile.compile('orchestrator/tier_b_runtime.py', doraise=True)"`
   — clean.
5. `python3 -c "import py_compile; py_compile.compile('triggers/tier_b_reservation_sweep.py', doraise=True)"`
   — clean.
6. Render startup logs after deploy include both:
   - `Registered: tier_b_counter_reset (cron: 1st of month 00:00 UTC)`
   - `Registered: tier_b_reservation_sweep (every 5 min)`
7. `/api/admin/tier-b-status` endpoint (shipped in B3) still returns 200
   with the same shape — this brief does not modify the endpoint.
8. Concurrent-load ship-gate test (`test_concurrent_enforcers_one_passes_one_pauses`)
   passes deterministically across 10 consecutive runs:
   ```bash
   for i in 1 2 3 4 5 6 7 8 9 10; do \
     pytest tests/test_tier_b_atomicity.py::test_concurrent_enforcers_one_passes_one_pauses -v \
       || break; \
   done
   ```
9. After deploy, a manual concurrent-call smoke from the Render shell
   produces exactly one PASS + one PAUSE:
   ```python
   from concurrent.futures import ThreadPoolExecutor
   from orchestrator.tier_b_runtime import enforce_tier_b, TierBAction, cancel_tier_b
   # ... pre-seed €499 day-total via the live tier_b_action_classes registry ...
   # ... then race two enforcers ...
   ```
   (See PL ship-report for the exact snippet.)

## Verification SQL

After deploy, while the system is idle, run:
```sql
-- 1. Migration applied
SELECT column_name FROM information_schema.columns
 WHERE table_name = 'baker_actions' AND column_name = 'reserved_at';
-- expect 1 row.

-- 2. Index present
SELECT indexname FROM pg_indexes
 WHERE tablename = 'baker_actions'
   AND indexname = 'idx_baker_actions_tier_b_reserved';
-- expect 1 row.

-- 3. Sweep job currently has nothing to do (clean state)
SELECT COUNT(*) FROM baker_actions
 WHERE tier='B' AND committed_at IS NULL
   AND reserved_at < NOW() AT TIME ZONE 'UTC' - INTERVAL '15 minutes';
-- expect 0.

-- 4. Pre-Cortex-Phase5-adoption, no production reservations exist
SELECT COUNT(*) FROM baker_actions
 WHERE tier='B' AND action_type='tier_b_reservation';
-- expect 0 in current state (Phase 5 V2 not shipped).
```

## Rollback path

If a regression surfaces post-deploy:
1. Revert PR via `gh pr revert <N> --merge`.
2. Migration is additive — the `reserved_at` column + new index can stay
   in place without harm (no consumer beyond this brief).
3. No data corruption risk: reservations written are net-new
   `baker_actions` rows; pre-existing rows are untouched.

## Provenance

- Director ratified Pattern B + 15-min TTL + atomicity-only scope
  2026-05-10 PM (this conversation, after AH1 scope-correction surface).
- B3 ship report + reviewer findings: `briefs/_reports/B3_cortex_tier_b_runtime_v1_20260510.md`.
- Hard acceptance criterion: `_ops/briefs/_precursor/B4_PRECURSOR_ATOMICITY_CLOSURE.md`.
- D5 risk register entry flips RESOLVED on this brief's merge (AID
  action, not B-code).
- RA-23 Q5 60s→180s spec drift is OUT OF SCOPE for this brief
  (separate AH1 vault edit).
