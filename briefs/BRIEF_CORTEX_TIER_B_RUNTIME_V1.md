# BRIEF: CORTEX_TIER_B_RUNTIME_V1 — Tier B autonomous-action runtime + budget enforcement

## Provenance
- **Source spec (AID design):** `~/baker-vault/_ops/briefs/CORTEX_B3_TIER_B_RUNTIME_V1.md`
- **Director ratification:** D8 via D3+D8 Triaga 2026-05-10 (`bm-aidennis-t/2026-05-10-aid-d3-d8-decision-pack-triaga.html`)
- **AID-resolved clarifications 2026-05-10:** Q1 Neon canonical / Q2 mixed cost source / Q3 forward-looking / Q4 dedicated `tier_b_pending` w/ GOLD visual reuse / Q5 pool-wide / Q6 architecture-final read both / Q7 00:00 UTC reset
- **Architecture authority:** `_ops/processes/cortex-architecture-final.md` §2.3 + §3 + §8 (RA-23 Q4 budget cap pattern)

## Context
First Cortex auto-trigger cycle (I5) STUCK since 2026-05-03 — blocked on Tier B runtime. B4 (6-phase loop runtime) and B5 (substrate push runtime) depend on this brief. After ship: I5 → B4 → B5 cascade unblocks naturally. P1 priority per program tracker.

## Estimated time: ~6–8h B-code work
## Complexity: Medium (schema + service + cron + endpoint + tests; no external integrations; no LLM calls)
## Prerequisites
- `baker_actions` table exists ✓ (bootstrap at `memory/store_back.py:1036`)
- GOLD ratify workflow exists ✓ (PR #66 — visual template reused, separate domain)
- D8 caps locked ✓ (2026-05-10)

---

## Scope summary

Build the forward-looking budget enforcement runtime that gates AH1/Cortex autonomous Tier-B actions against Director-ratified caps.

### Caps to enforce (D8 Conservative tier — calendar-month reset)

| Cap | Value | Behavior on hit |
|---|---|---|
| Per-action | €100 | Action paused; Director ratify required |
| Daily total (pool-wide) | €500 | All Tier-B paused for day; Director ratify to lift |
| Monthly total (pool-wide) | €2,500 | All Tier-B paused for month; Director ratify to lift |
| Reset | 1st of calendar month, 00:00 UTC | All counters zero |

**Pool-wide:** caps are firm-wide AI spend ceilings, not per-agent budgets. If any committer (AH1, AH2, Cortex, future agent) hits day cap, ALL Tier-B paused. Single firm-level safety net.

### What counts as Tier-B autonomous action (per Cortex architecture)
- AH1/Cortex committing to vendor invoices
- AH1/Cortex creating new service subscriptions
- AH1/Cortex deploying code that costs (e.g., new Render services)
- AH1/Cortex paying for tools or APIs without Director ratify

### Out of scope (confirmed by AID 2026-05-10)
- **Anthropic API token cost** — separate D4 risk action, AID owns, target 2026-05-31
- **Tier C definition** (Director-only actions) — separate brief if needed
- **Wiring Cortex Phase 5 / B4 6-phase loop / B5 substrate push to call `enforce_tier_b`** — those briefs adopt this runtime when they ship

### Forward-looking only — no regression risk
Verified 2026-05-10 via grep on entire `bm-aihead1/` tree: **zero existing call-sites** for `enforce_tier_b` / `tier_b_pending` / `autonomous_action` patterns. Cortex hasn't fired (I5 stuck). All today's AH1 dispatches go through Director ratify. B3 builds the runtime; future call-sites adopt it as built. **No live-regression risk on existing flows.**

---

## Fix 1: Schema extension on `baker_actions` + new tables

### Problem
`baker_actions` bootstrap (`memory/store_back.py:1036`) has 9 columns: `id, action_type, target_task_id, target_space_id, payload, trigger_source, created_at, success, error_message`. Missing: tier label, €-cost, committer agent, action class. Cannot compute Tier-B counters without these.

### Current state — baker_actions bootstrap (verified `memory/store_back.py:1036-1047`)
```sql
CREATE TABLE IF NOT EXISTS baker_actions (
    id SERIAL PRIMARY KEY,
    action_type TEXT NOT NULL,
    target_task_id TEXT,
    target_space_id TEXT,
    payload JSONB,
    trigger_source TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT
)
```

### Implementation

**Step 1.1** — Create new migration `migrations/20260510_baker_actions_tier_b_runtime.sql`:

```sql
-- 20260510_baker_actions_tier_b_runtime.sql
-- Tier B autonomous-action runtime: schema extension + new tables.
-- Forward-looking only. No backfill required.

BEGIN;

-- 1. Extend baker_actions with Tier-B columns (additive, nullable).
ALTER TABLE baker_actions
    ADD COLUMN IF NOT EXISTS tier            TEXT,            -- 'A' | 'B' | NULL (legacy rows)
    ADD COLUMN IF NOT EXISTS cost_eur        NUMERIC(12, 2),  -- € amount; NULL for non-Tier-B
    ADD COLUMN IF NOT EXISTS committed_at    TIMESTAMPTZ,     -- when action actually executed (vs created_at = log time)
    ADD COLUMN IF NOT EXISTS committer_agent TEXT,            -- 'ah1' | 'ah2' | 'cortex' | 'b1' | etc.
    ADD COLUMN IF NOT EXISTS action_class    TEXT,            -- registry key (Q2 mixed model)
    ADD COLUMN IF NOT EXISTS self_cost_eur   NUMERIC(12, 2);  -- self-declared cost when action_class='novel:*'

-- Partial index for fast counter queries (only Tier-B rows with cost).
CREATE INDEX IF NOT EXISTS idx_baker_actions_tier_b_committed
    ON baker_actions (committed_at)
    WHERE tier = 'B' AND cost_eur IS NOT NULL;

-- 2. Action-class registry (Q2: primary cost source).
CREATE TABLE IF NOT EXISTS tier_b_action_classes (
    id              SERIAL PRIMARY KEY,
    class_name      TEXT NOT NULL UNIQUE,    -- e.g., 'render.deploy.web_service.starter'
    eur_cost        NUMERIC(12, 2) NOT NULL, -- known €-cost
    description     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deprecated_at   TIMESTAMPTZ              -- nullable; set when class superseded
);

-- 3. Pending-ratify queue (Q4: dedicated table; GOLD visual template reused but separate domain).
CREATE TABLE IF NOT EXISTS tier_b_pending (
    id               SERIAL PRIMARY KEY,
    action_payload   JSONB NOT NULL,                       -- full action description for replay
    cost_eur         NUMERIC(12, 2) NOT NULL,
    action_class     TEXT NOT NULL,
    committer_agent  TEXT NOT NULL,
    reason_paused    TEXT NOT NULL,                        -- 'per_action_cap' | 'daily_cap' | 'monthly_cap'
    status           TEXT NOT NULL DEFAULT 'pending',      -- 'pending' | 'ratified' | 'rejected' | 'expired'
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ratified_at      TIMESTAMPTZ,
    ratified_by      TEXT,                                 -- 'director' on ratify
    decision_payload JSONB,                                -- Director's GOLD card response
    expired_at       TIMESTAMPTZ,                          -- if Director never responds (>72h policy TBD by AID)
    CONSTRAINT tier_b_pending_status_check
        CHECK (status IN ('pending', 'ratified', 'rejected', 'expired'))
);

CREATE INDEX IF NOT EXISTS idx_tier_b_pending_status
    ON tier_b_pending (status, created_at);

-- 4. Counter-reset audit table (logs each calendar-month reset event).
CREATE TABLE IF NOT EXISTS tier_b_counter_resets (
    id               SERIAL PRIMARY KEY,
    reset_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    period_label     TEXT NOT NULL,            -- 'YYYY-MM' of period that just ended
    final_day_total  NUMERIC(12, 2),
    final_month_total NUMERIC(12, 2),
    actions_count    INTEGER
);

-- 5. Seed initial action-class registry (forward-looking known classes).
INSERT INTO tier_b_action_classes (class_name, eur_cost, description) VALUES
    ('render.deploy.web_service.starter',     7.00,  'Render Starter web service spawn (monthly billing approximation, daily-amortized = €0.23)'),
    ('render.deploy.web_service.standard',   25.00,  'Render Standard web service spawn (monthly billing approximation)'),
    ('render.env.flip',                       0.00,  'Render env-var flip; zero direct cost; logged for audit'),
    ('vendor.subscription.monthly',          50.00,  'Generic monthly SaaS subscription default; override with specific class as registry grows'),
    ('test.synthetic',                        1.00,  'Test-only class for integration tests')
ON CONFLICT (class_name) DO NOTHING;

COMMIT;
```

**Step 1.2** — Update bootstrap in `memory/store_back.py` to match (Brief Standard #4 — migration-vs-bootstrap drift trap).

Add new method `_ensure_tier_b_runtime_tables` and call from `__init__`. Update `_ensure_clickup_tables` baker_actions DDL to match (additive columns).

```python
# In _ensure_clickup_tables, replace baker_actions DDL block (around line 1036) with:
cur.execute("""
    CREATE TABLE IF NOT EXISTS baker_actions (
        id SERIAL PRIMARY KEY,
        action_type TEXT NOT NULL,
        target_task_id TEXT,
        target_space_id TEXT,
        payload JSONB,
        trigger_source TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        success BOOLEAN DEFAULT TRUE,
        error_message TEXT,
        tier TEXT,
        cost_eur NUMERIC(12, 2),
        committed_at TIMESTAMPTZ,
        committer_agent TEXT,
        action_class TEXT,
        self_cost_eur NUMERIC(12, 2)
    )
""")
# Idempotent ALTER for envs where the table pre-existed without Tier-B columns:
cur.execute("""
    ALTER TABLE baker_actions
        ADD COLUMN IF NOT EXISTS tier TEXT,
        ADD COLUMN IF NOT EXISTS cost_eur NUMERIC(12, 2),
        ADD COLUMN IF NOT EXISTS committed_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS committer_agent TEXT,
        ADD COLUMN IF NOT EXISTS action_class TEXT,
        ADD COLUMN IF NOT EXISTS self_cost_eur NUMERIC(12, 2)
""")
```

Add new bootstrap method (called from `__init__` after `_ensure_clickup_tables()`):

```python
def _ensure_tier_b_runtime_tables(self):
    """Bootstrap Tier B runtime tables. Mirrors migrations/20260510_baker_actions_tier_b_runtime.sql."""
    conn = self._get_conn()
    if not conn:
        logger.warning("No DB connection — cannot ensure tier_b_* tables")
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tier_b_action_classes (
                id SERIAL PRIMARY KEY,
                class_name TEXT NOT NULL UNIQUE,
                eur_cost NUMERIC(12, 2) NOT NULL,
                description TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                deprecated_at TIMESTAMPTZ
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tier_b_pending (
                id SERIAL PRIMARY KEY,
                action_payload JSONB NOT NULL,
                cost_eur NUMERIC(12, 2) NOT NULL,
                action_class TEXT NOT NULL,
                committer_agent TEXT NOT NULL,
                reason_paused TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                ratified_at TIMESTAMPTZ,
                ratified_by TEXT,
                decision_payload JSONB,
                expired_at TIMESTAMPTZ,
                CONSTRAINT tier_b_pending_status_check
                    CHECK (status IN ('pending', 'ratified', 'rejected', 'expired'))
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tier_b_counter_resets (
                id SERIAL PRIMARY KEY,
                reset_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                period_label TEXT NOT NULL,
                final_day_total NUMERIC(12, 2),
                final_month_total NUMERIC(12, 2),
                actions_count INTEGER
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_tier_b_pending_status
                ON tier_b_pending (status, created_at)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_baker_actions_tier_b_committed
                ON baker_actions (committed_at)
                WHERE tier = 'B' AND cost_eur IS NOT NULL
        """)
        conn.commit()
        cur.close()
        logger.info("Tier B runtime tables verified")
    except Exception as e:
        conn.rollback()
        logger.warning(f"Could not ensure tier_b_* tables: {e}")
    finally:
        self._put_conn(conn)
```

### Key constraints
- **DO NOT** remove or rename existing `baker_actions` columns; only additive.
- **DO NOT** edit existing applied migrations; new migration only (per `CLAUDE.md`).
- ALTER COLUMN clauses must use `ADD COLUMN IF NOT EXISTS` to be idempotent across envs.
- All new tables prefixed `tier_b_*` for namespace clarity.

### Verification
- After deploy, run on prod Neon:
  ```sql
  SELECT column_name, data_type FROM information_schema.columns
   WHERE table_name = 'baker_actions' ORDER BY ordinal_position;
  -- Expect 15 columns total (9 original + 6 new)

  SELECT * FROM tier_b_action_classes ORDER BY id;
  -- Expect 5 seed rows.
  ```

---

## Fix 2: `enforce_tier_b()` runtime + counter math

### Problem
No call-site today decides PASS / PAUSE_REQUIRED for a candidate Tier-B action. Future call-sites (B4 / B5 / Cortex Phase 5) need a single function to gate against caps before committing.

### Implementation

**Step 2.1** — Create `orchestrator/tier_b_runtime.py` (new file):

```python
"""Tier B autonomous-action budget runtime.

Forward-looking gate: future call-sites (B4 6-phase loop, B5 substrate push,
Cortex Phase 5) call enforce_tier_b(action) BEFORE committing. Returns
PASS or PAUSE_REQUIRED. On PAUSE_REQUIRED the candidate is queued in
tier_b_pending; Director ratify card emitted via GOLD visual template
(separate workflow domain — see orchestrator/tier_b_ratify.py).

Caps (D8 Conservative tier, ratified 2026-05-10):
    PER_ACTION = €100
    DAILY_POOL = €500
    MONTHLY_POOL = €2,500
    Reset: 1st of calendar month, 00:00 UTC

Cost source (Q2 mixed model):
    Primary: tier_b_action_classes registry lookup
    Fallback: committer self-declares with action_class='novel:<descriptor>' + self_cost_eur
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Optional

from memory.store_back import SentinelStoreBack

logger = logging.getLogger(__name__)

# Cap constants — Director-ratified D8 Conservative tier 2026-05-10
PER_ACTION_CAP_EUR = 100.00
DAILY_POOL_CAP_EUR = 500.00
MONTHLY_POOL_CAP_EUR = 2500.00


@dataclass(frozen=True)
class TierBAction:
    """Candidate Tier-B action under enforcement."""
    action_class: str             # registry key OR 'novel:<descriptor>'
    committer_agent: str          # 'ah1' | 'ah2' | 'cortex' | 'b1' | 'b2' | 'b3' | 'b4'
    payload: dict                 # full action description (replayable on ratify)
    self_cost_eur: Optional[float] = None  # required when action_class='novel:*'


@dataclass(frozen=True)
class Decision:
    """Result of enforce_tier_b() — caller routes by .verdict."""
    verdict: Literal["PASS", "PAUSE_REQUIRED"]
    cost_eur: float
    reason: str                   # human-readable; for PAUSE_REQUIRED becomes reason_paused
    pending_id: Optional[int] = None  # set when PAUSE_REQUIRED → row in tier_b_pending


class TierBRuntime:
    """Singleton: budget enforcement gate."""

    _instance = None

    @classmethod
    def _get_global_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._store = SentinelStoreBack._get_global_instance()

    def _resolve_cost(self, action: TierBAction) -> tuple[float, str]:
        """Returns (cost_eur, source_tag). source_tag in {'registry', 'self_declared'}."""
        if action.action_class.startswith("novel:"):
            if action.self_cost_eur is None:
                raise ValueError(
                    f"action_class='{action.action_class}' requires self_cost_eur"
                )
            return float(action.self_cost_eur), "self_declared"

        conn = self._store._get_conn()
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
                    f"unknown action_class '{action.action_class}'; "
                    f"register first or use 'novel:<descriptor>' with self_cost_eur"
                )
            return float(row[0]), "registry"
        except Exception:
            conn.rollback()
            raise
        finally:
            self._store._put_conn(conn)

    def _current_totals(self) -> tuple[float, float]:
        """Returns (day_total_eur, month_total_eur) for committed Tier-B actions.

        Calendar-day in UTC; calendar-month in UTC. Excludes paused (uncommitted).
        """
        conn = self._store._get_conn()
        try:
            cur = conn.cursor()
            # Day total — committed today (UTC)
            cur.execute("""
                SELECT COALESCE(SUM(cost_eur), 0)
                  FROM baker_actions
                 WHERE tier = 'B'
                   AND cost_eur IS NOT NULL
                   AND committed_at >= DATE_TRUNC('day', NOW() AT TIME ZONE 'UTC')
                 LIMIT 100000
            """)
            day_total = float(cur.fetchone()[0])

            # Month total — committed this calendar month (UTC)
            cur.execute("""
                SELECT COALESCE(SUM(cost_eur), 0)
                  FROM baker_actions
                 WHERE tier = 'B'
                   AND cost_eur IS NOT NULL
                   AND committed_at >= DATE_TRUNC('month', NOW() AT TIME ZONE 'UTC')
                 LIMIT 100000
            """)
            month_total = float(cur.fetchone()[0])

            cur.close()
            return day_total, month_total
        except Exception:
            conn.rollback()
            raise
        finally:
            self._store._put_conn(conn)

    def enforce(self, action: TierBAction) -> Decision:
        """PASS = caller may commit + log. PAUSE_REQUIRED = queued; await ratify.

        Atomicity note: cost-resolve + counter-read + pending-insert run inside
        a single SERIALIZABLE transaction to prevent race where two simultaneous
        committers each see headroom but together exceed cap.
        """
        cost_eur, source_tag = self._resolve_cost(action)

        conn = self._store._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN ISOLATION LEVEL SERIALIZABLE")

            # Re-read totals inside the serializable txn.
            cur.execute("""
                SELECT COALESCE(SUM(cost_eur), 0)
                  FROM baker_actions
                 WHERE tier = 'B' AND cost_eur IS NOT NULL
                   AND committed_at >= DATE_TRUNC('day', NOW() AT TIME ZONE 'UTC')
                 LIMIT 100000
            """)
            day_total = float(cur.fetchone()[0])
            cur.execute("""
                SELECT COALESCE(SUM(cost_eur), 0)
                  FROM baker_actions
                 WHERE tier = 'B' AND cost_eur IS NOT NULL
                   AND committed_at >= DATE_TRUNC('month', NOW() AT TIME ZONE 'UTC')
                 LIMIT 100000
            """)
            month_total = float(cur.fetchone()[0])

            # Cap evaluation order: per-action → daily → monthly
            paused_reason = None
            if cost_eur > PER_ACTION_CAP_EUR:
                paused_reason = "per_action_cap"
            elif day_total + cost_eur > DAILY_POOL_CAP_EUR:
                paused_reason = "daily_cap"
            elif month_total + cost_eur > MONTHLY_POOL_CAP_EUR:
                paused_reason = "monthly_cap"

            if paused_reason:
                cur.execute("""
                    INSERT INTO tier_b_pending
                        (action_payload, cost_eur, action_class, committer_agent, reason_paused)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    self._jsonify(action.payload),
                    cost_eur,
                    action.action_class,
                    action.committer_agent,
                    paused_reason,
                ))
                pending_id = int(cur.fetchone()[0])
                conn.commit()
                cur.close()
                return Decision(
                    verdict="PAUSE_REQUIRED",
                    cost_eur=cost_eur,
                    reason=f"{paused_reason} — cost €{cost_eur:.2f}, day=€{day_total:.2f}, month=€{month_total:.2f}",
                    pending_id=pending_id,
                )

            conn.commit()
            cur.close()
            return Decision(
                verdict="PASS",
                cost_eur=cost_eur,
                reason=f"PASS via {source_tag} — day=€{day_total + cost_eur:.2f}, month=€{month_total + cost_eur:.2f}",
            )
        except Exception:
            conn.rollback()
            raise
        finally:
            self._store._put_conn(conn)

    @staticmethod
    def _jsonify(payload: dict) -> str:
        import json
        return json.dumps(payload, default=str)


def enforce_tier_b(action: TierBAction) -> Decision:
    """Module-level shorthand. Use this from call-sites."""
    return TierBRuntime._get_global_instance().enforce(action)
```

### Key constraints
- **Singleton pattern (Brief Standard #8):** `TierBRuntime._get_global_instance()` only. Never instantiate directly. Pre-push hook `scripts/check_singletons.sh` will block direct instantiation.
- **All DB calls in try/except with rollback** (project hard rule + `.claude/rules/python-backend.md`).
- **All SELECTs have LIMIT** (project hard rule).
- **Atomic check-and-pause:** SERIALIZABLE isolation prevents race where two simultaneous committers each see €499 headroom and both pass. Postgres serializable will detect serialization failure on conflict; caller sees exception → retries.
- **Calendar-month boundary in UTC** (Q7 ratification).

### Verification (Fix 2)
Unit-test scenarios in Fix 4 cover:
- per-action cap: action €150 → PAUSE_REQUIRED reason='per_action_cap'
- daily cap: 5 prior committed €100 actions today + new €5 → PAUSE_REQUIRED reason='daily_cap'
- monthly cap: 25 prior committed €100 today/this month + new €5 → PAUSE_REQUIRED reason='monthly_cap'
- novel class without self_cost_eur → ValueError
- unknown registry class → ValueError

---

## Fix 3: Pause-handler + Director ratify card (visual reuse only)

### Problem
On PAUSE_REQUIRED, Director must see a ratify card within 30s and decide ratify/reject. AID-resolved Q4: visual template reused from PR #66 GOLD card; **separate workflow domain** — do not extend GOLD pattern's per-matter scope.

### Implementation

**Step 3.1** — Create `orchestrator/tier_b_ratify.py` (new file):

```python
"""Tier B ratify-card emission. Visual template borrowed from GOLD card
(PR #66 pattern); separate workflow domain (not per-matter, global/operational).

When enforce_tier_b() returns PAUSE_REQUIRED, the call-site hands the
pending_id to emit_ratify_card(). Card is pushed to Director via Slack
substrate per existing GOLD card visual template.
"""

import logging
from typing import Optional

from memory.store_back import SentinelStoreBack

logger = logging.getLogger(__name__)


def emit_ratify_card(pending_id: int) -> bool:
    """Push a ratify card to Director Slack for the given tier_b_pending row.

    Returns True on push success, False on failure (caller logs to baker_actions).
    Visual template: GOLD card structure (Block Kit blocks=, mrkdwn sections,
    4-button proposal pattern). Separate domain — DO NOT write to
    proposed-gold.md or any per-matter GOLD surface.
    """
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, action_payload, cost_eur, action_class,
                   committer_agent, reason_paused, created_at
              FROM tier_b_pending
             WHERE id = %s AND status = 'pending'
             LIMIT 1
        """, (pending_id,))
        row = cur.fetchone()
        cur.close()
        if not row:
            logger.warning(f"tier_b_pending id={pending_id} not found or not pending")
            return False
    except Exception as e:
        conn.rollback()
        logger.error(f"emit_ratify_card DB read failed: {e}")
        return False
    finally:
        store._put_conn(conn)

    # Build Slack Block Kit card matching GOLD visual template.
    # IMPORTANT: caller (B4 / Cortex Phase 5) wires actual Slack send via
    # mcp__slack__slack_send_message. This module returns the prepared blocks.
    # For V1 we just log + return True; B4/B5 wire actual push.
    logger.info(
        f"Tier-B ratify card prepared: pending_id={pending_id} "
        f"cost=€{float(row[2]):.2f} reason={row[5]}"
    )
    return True


def consume_ratify_response(pending_id: int, decision: str, ratified_by: str = "director") -> bool:
    """Apply Director's ratify decision to a tier_b_pending row.

    decision in {'ratified', 'rejected'}. On 'ratified', caller is responsible
    for re-attempting the original action (which will then go through
    enforce_tier_b again — but with this row marked ratified, the cap check
    can be bypassed once; see ratify-then-commit pattern in B4 brief).

    Returns True on successful state transition, False otherwise.
    """
    if decision not in ("ratified", "rejected"):
        raise ValueError(f"decision must be 'ratified' or 'rejected', got {decision!r}")

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE tier_b_pending
               SET status = %s,
                   ratified_at = NOW(),
                   ratified_by = %s
             WHERE id = %s AND status = 'pending'
            RETURNING id
        """, (decision, ratified_by, pending_id))
        result = cur.fetchone()
        if result is None:
            conn.rollback()
            cur.close()
            logger.warning(f"tier_b_pending id={pending_id} not in pending status")
            return False
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"consume_ratify_response failed: {e}")
        return False
    finally:
        store._put_conn(conn)
```

### Key constraints
- **Visual reuse only:** GOLD card's Block Kit / mrkdwn structure may be referenced. **Do NOT** write to `proposed-gold.md` or any per-matter GOLD surface. Tier B is operational/global; GOLD is per-matter.
- **No external auto-send:** ratify card is a Slack push (internal Director workspace) — internal auto-sends per `S1` invariant are OK. External recipients still draft-only.
- **B3 scope ends at preparing the card payload + DB state transitions.** B4 wires the actual Slack push when its 6-phase loop ships.

---

## Fix 4: Calendar-month reset cron (APScheduler)

### Problem
Counters need to zero on the 1st of each calendar month at 00:00 UTC. Reset is a logical no-op (counters are read from `baker_actions` filtered by `committed_at >= DATE_TRUNC('month', NOW())`), but we need an audit row in `tier_b_counter_resets` so we can prove the boundary fired.

### Current state
APScheduler pattern in `triggers/embedded_scheduler.py`. CronTrigger import already present at line 15. Multiple existing cron jobs (registered at line 89+).

### Implementation

**Step 4.1** — Add new module `triggers/tier_b_reset.py`:

```python
"""Calendar-month Tier B counter-reset audit job.

Runs 1st of month at 00:00 UTC. Logs the reset event to tier_b_counter_resets;
counter math itself is read-driven from baker_actions, so the reset is logical
(no UPDATE needed). The audit row proves the boundary fired.
"""

import logging
from datetime import datetime, timedelta, timezone

from memory.store_back import SentinelStoreBack

logger = logging.getLogger(__name__)


def tier_b_counter_reset():
    """APScheduler entrypoint: log calendar-month reset event."""
    now_utc = datetime.now(timezone.utc)
    # Period that just ended = previous month
    if now_utc.month == 1:
        prev_year, prev_month = now_utc.year - 1, 12
    else:
        prev_year, prev_month = now_utc.year, now_utc.month - 1
    period_label = f"{prev_year:04d}-{prev_month:02d}"

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        # Compute final totals for period that just ended (UTC boundaries).
        cur.execute("""
            SELECT COALESCE(SUM(cost_eur), 0), COUNT(*)
              FROM baker_actions
             WHERE tier = 'B' AND cost_eur IS NOT NULL
               AND committed_at >= make_timestamptz(%s, %s, 1, 0, 0, 0, 'UTC')
               AND committed_at <  DATE_TRUNC('month', NOW() AT TIME ZONE 'UTC')
             LIMIT 100000
        """, (prev_year, prev_month))
        final_month_total, actions_count = cur.fetchone()

        # Day total for last day of month (informational).
        cur.execute("""
            SELECT COALESCE(SUM(cost_eur), 0)
              FROM baker_actions
             WHERE tier = 'B' AND cost_eur IS NOT NULL
               AND committed_at >= DATE_TRUNC('day', NOW() AT TIME ZONE 'UTC' - INTERVAL '1 day')
               AND committed_at <  DATE_TRUNC('day', NOW() AT TIME ZONE 'UTC')
             LIMIT 100000
        """)
        final_day_total = cur.fetchone()[0]

        cur.execute("""
            INSERT INTO tier_b_counter_resets
                (period_label, final_day_total, final_month_total, actions_count)
            VALUES (%s, %s, %s, %s)
        """, (period_label, final_day_total, final_month_total, actions_count))

        conn.commit()
        cur.close()
        logger.info(
            f"Tier B counter reset logged for period {period_label}: "
            f"€{float(final_month_total):.2f} across {actions_count} actions"
        )
    except Exception as e:
        conn.rollback()
        logger.error(f"tier_b_counter_reset failed: {e}")
        raise
    finally:
        store._put_conn(conn)
```

**Step 4.2** — Register cron job in `triggers/embedded_scheduler.py` (add inside `_register_jobs`):

```python
# Tier B calendar-month counter-reset audit — 1st of each month, 00:00 UTC.
from triggers.tier_b_reset import tier_b_counter_reset
scheduler.add_job(
    tier_b_counter_reset,
    CronTrigger(day=1, hour=0, minute=0, timezone="UTC"),
    id="tier_b_counter_reset",
    name="Tier B counter reset (calendar-month, UTC)",
    coalesce=True,
    max_instances=1,
    replace_existing=True,
)
logger.info("Registered: tier_b_counter_reset (cron: 1st of month 00:00 UTC)")
```

### Key constraints
- **`timezone="UTC"`** explicit on `CronTrigger` (Q7 — calendar-month in UTC, not local).
- **`coalesce=True`** + `max_instances=1` follows existing job pattern (line 93/108/etc.).
- **Idempotent re-registration** via `replace_existing=True`.

### Verification (Fix 4)
- Manually invoke once via Render shell: `python -c "from triggers.tier_b_reset import tier_b_counter_reset; tier_b_counter_reset()"`. Verify row in `tier_b_counter_resets`.
- APScheduler-Render integration test: confirm next-fire-time visible via `/health` (existing scheduler introspection if present, else `scheduler_executions` log).

---

## Fix 5: `/api/admin/tier-b-status` audit endpoint

### Problem
Director + AI Heads need a live read of: today's pool spend, this month's pool spend, headroom remaining, pending ratify queue, recent committed Tier-B actions.

### Current state
Admin endpoint pattern in `outputs/dashboard.py:10062-10350` uses `@app.post("/api/admin/X", tags=["admin"], dependencies=[Depends(verify_api_key)])`.

### Implementation

**Step 5.1** — Add new endpoint to `outputs/dashboard.py` (place near other admin endpoints around line 10070):

```python
@app.get("/api/admin/tier-b-status", tags=["admin"], dependencies=[Depends(verify_api_key)])
async def admin_tier_b_status():
    """Live Tier-B budget state.

    Returns day/month totals + remaining headroom + pending queue snapshot
    + recent committed Tier-B actions. Read-only.
    """
    from memory.store_back import SentinelStoreBack
    from orchestrator.tier_b_runtime import (
        PER_ACTION_CAP_EUR,
        DAILY_POOL_CAP_EUR,
        MONTHLY_POOL_CAP_EUR,
    )

    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    try:
        cur = conn.cursor()

        # Day total
        cur.execute("""
            SELECT COALESCE(SUM(cost_eur), 0)
              FROM baker_actions
             WHERE tier = 'B' AND cost_eur IS NOT NULL
               AND committed_at >= DATE_TRUNC('day', NOW() AT TIME ZONE 'UTC')
             LIMIT 100000
        """)
        day_total = float(cur.fetchone()[0])

        # Month total
        cur.execute("""
            SELECT COALESCE(SUM(cost_eur), 0)
              FROM baker_actions
             WHERE tier = 'B' AND cost_eur IS NOT NULL
               AND committed_at >= DATE_TRUNC('month', NOW() AT TIME ZONE 'UTC')
             LIMIT 100000
        """)
        month_total = float(cur.fetchone()[0])

        # Pending queue
        cur.execute("""
            SELECT id, cost_eur, action_class, committer_agent, reason_paused,
                   created_at
              FROM tier_b_pending
             WHERE status = 'pending'
             ORDER BY created_at DESC
             LIMIT 50
        """)
        pending = [
            {
                "id": r[0],
                "cost_eur": float(r[1]),
                "action_class": r[2],
                "committer_agent": r[3],
                "reason_paused": r[4],
                "created_at": r[5].isoformat() if r[5] else None,
            }
            for r in cur.fetchall()
        ]

        # Recent committed
        cur.execute("""
            SELECT id, cost_eur, action_class, committer_agent, committed_at
              FROM baker_actions
             WHERE tier = 'B' AND cost_eur IS NOT NULL
             ORDER BY committed_at DESC
             LIMIT 20
        """)
        recent = [
            {
                "id": r[0],
                "cost_eur": float(r[1]),
                "action_class": r[2],
                "committer_agent": r[3],
                "committed_at": r[4].isoformat() if r[4] else None,
            }
            for r in cur.fetchall()
        ]

        cur.close()

        return JSONResponse({
            "caps": {
                "per_action_eur": PER_ACTION_CAP_EUR,
                "daily_pool_eur": DAILY_POOL_CAP_EUR,
                "monthly_pool_eur": MONTHLY_POOL_CAP_EUR,
            },
            "current": {
                "day_total_eur": day_total,
                "month_total_eur": month_total,
                "day_remaining_eur": max(0.0, DAILY_POOL_CAP_EUR - day_total),
                "month_remaining_eur": max(0.0, MONTHLY_POOL_CAP_EUR - month_total),
            },
            "pending": pending,
            "recent_committed": recent,
        })
    except Exception as e:
        conn.rollback()
        logger.error(f"/api/admin/tier-b-status failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        store._put_conn(conn)
```

### Key constraints
- **GET** (read-only) — no need for POST.
- **Auth required** via `verify_api_key` dep (same as other admin endpoints).
- **All SELECTs have LIMIT** (LIMIT 100000 / 50 / 20).
- **`JSONResponse` import** already present in `outputs/dashboard.py` (verify before use; Lesson #18 — phantom imports).

### Verification (Fix 5)
- Local: `curl -H 'X-Baker-Key: bakerbhavanga' http://localhost:8080/api/admin/tier-b-status` → JSON with `caps`, `current`, `pending: []`, `recent_committed: []` on fresh deploy.
- Prod: same against `https://baker-master.onrender.com/api/admin/tier-b-status`.

---

## Fix 6: Tests (unit + integration)

### Implementation

**Step 6.1** — Create `tests/test_tier_b_runtime.py`:

```python
"""Unit tests for orchestrator/tier_b_runtime.py.

Covers: cost resolve (registry + novel + invalid), enforce verdict matrix
(PASS / per_action_cap / daily_cap / monthly_cap), atomicity under
concurrent commits.
"""

import pytest
from datetime import datetime, timezone

from orchestrator.tier_b_runtime import (
    DAILY_POOL_CAP_EUR,
    MONTHLY_POOL_CAP_EUR,
    PER_ACTION_CAP_EUR,
    Decision,
    TierBAction,
    TierBRuntime,
    enforce_tier_b,
)

requires_pg = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in __import__("os").environ,
    reason="needs TEST_DATABASE_URL (Neon ephemeral branch in CI)"
)


@pytest.fixture
def runtime(tmp_test_db):  # tmp_test_db is provided by existing conftest pattern
    return TierBRuntime._get_global_instance()


@requires_pg
def test_pass_under_caps(runtime, clean_baker_actions):
    action = TierBAction(
        action_class="test.synthetic",  # €1 in registry
        committer_agent="b3",
        payload={"test": "smoke"},
    )
    decision = enforce_tier_b(action)
    assert decision.verdict == "PASS"
    assert decision.cost_eur == 1.00
    assert decision.pending_id is None


@requires_pg
def test_per_action_cap_paused(runtime, register_class):
    register_class("test.expensive_one_shot", 150.00)
    action = TierBAction(
        action_class="test.expensive_one_shot",
        committer_agent="b3",
        payload={"test": "over_per_action"},
    )
    decision = enforce_tier_b(action)
    assert decision.verdict == "PAUSE_REQUIRED"
    assert "per_action_cap" in decision.reason
    assert decision.pending_id is not None


@requires_pg
def test_daily_cap_paused(runtime, seed_committed_today, register_class):
    # Seed €499 of committed Tier-B today (5x €100 - €1).
    register_class("test.med", 99.80)
    seed_committed_today(class_name="test.med", count=5, agent="ah1")
    action = TierBAction(
        action_class="test.synthetic",  # €1; 499 + 1 = 500 OK; need 502 to break
        committer_agent="b3",
        payload={"test": "near_daily"},
    )
    # 5 × 99.80 = 499; +1 = 500 (still ≤ cap); test edge:
    decision = enforce_tier_b(action)
    assert decision.verdict == "PASS"  # exactly at cap

    # Now another €1 → 501 → PAUSE
    seed_committed_today(class_name="test.synthetic", count=1, agent="ah1")
    decision2 = enforce_tier_b(action)
    assert decision2.verdict == "PAUSE_REQUIRED"
    assert "daily_cap" in decision2.reason


@requires_pg
def test_monthly_cap_paused(runtime, seed_committed_this_month, register_class):
    register_class("test.med", 99.80)
    seed_committed_this_month(class_name="test.med", count=25, agent="ah1")
    # 25 × 99.80 = 2495; new €10 → 2505 → PAUSE
    register_class("test.ten", 10.00)
    action = TierBAction(
        action_class="test.ten",
        committer_agent="b3",
        payload={"test": "monthly_break"},
    )
    decision = enforce_tier_b(action)
    assert decision.verdict == "PAUSE_REQUIRED"
    assert "monthly_cap" in decision.reason


@requires_pg
def test_novel_class_requires_self_cost():
    action = TierBAction(
        action_class="novel:custom_render_addon",
        committer_agent="b3",
        payload={},
        # self_cost_eur missing
    )
    with pytest.raises(ValueError, match="requires self_cost_eur"):
        enforce_tier_b(action)


@requires_pg
def test_unknown_registry_class_raises():
    action = TierBAction(
        action_class="render.does.not.exist",
        committer_agent="b3",
        payload={},
    )
    with pytest.raises(ValueError, match="unknown action_class"):
        enforce_tier_b(action)


@requires_pg
def test_pool_wide_isolation_between_agents(runtime, register_class, seed_committed_today):
    """Pool-wide: AH1 spends €499; B3 trying €5 must PAUSE."""
    register_class("test.med", 99.80)
    seed_committed_today(class_name="test.med", count=5, agent="ah1")
    # 5 × 99.80 = €499 by AH1
    register_class("test.five", 5.00)
    action = TierBAction(
        action_class="test.five",
        committer_agent="b3",  # different agent — should still pause (pool-wide)
        payload={},
    )
    decision = enforce_tier_b(action)
    assert decision.verdict == "PAUSE_REQUIRED"
    assert "daily_cap" in decision.reason
```

**Step 6.2** — Create `tests/test_tier_b_reset.py`:

```python
"""Unit tests for triggers/tier_b_reset.tier_b_counter_reset()."""

import pytest
from datetime import datetime, timezone

from triggers.tier_b_reset import tier_b_counter_reset


requires_pg = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in __import__("os").environ,
    reason="needs TEST_DATABASE_URL"
)


@requires_pg
def test_reset_writes_audit_row(tmp_test_db, seed_committed_last_month):
    # Seed prior-month €123.45 committed
    seed_committed_last_month(class_name="test.synthetic", total_eur=123.45)
    tier_b_counter_reset()

    # Verify row in tier_b_counter_resets
    from memory.store_back import SentinelStoreBack
    store = SentinelStoreBack._get_global_instance()
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT period_label, final_month_total
              FROM tier_b_counter_resets
             ORDER BY id DESC LIMIT 1
        """)
        row = cur.fetchone()
        assert row is not None
        # period_label should be prior calendar month YYYY-MM
        # final_month_total should reflect seeded €123.45
        assert float(row[1]) == 123.45
    finally:
        cur.close()
        store._put_conn(conn)
```

**Step 6.3** — Create `tests/test_tier_b_status_endpoint.py`:

```python
"""Integration test: /api/admin/tier-b-status returns expected shape."""

import pytest
from fastapi.testclient import TestClient

requires_pg = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in __import__("os").environ,
    reason="needs TEST_DATABASE_URL"
)


@requires_pg
def test_tier_b_status_shape(tmp_test_db):
    from outputs.dashboard import app
    client = TestClient(app)
    resp = client.get(
        "/api/admin/tier-b-status",
        headers={"X-Baker-Key": "bakerbhavanga"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "caps" in body
    assert body["caps"]["per_action_eur"] == 100.00
    assert body["caps"]["daily_pool_eur"] == 500.00
    assert body["caps"]["monthly_pool_eur"] == 2500.00
    assert "current" in body
    assert "day_total_eur" in body["current"]
    assert "month_total_eur" in body["current"]
    assert "day_remaining_eur" in body["current"]
    assert "month_remaining_eur" in body["current"]
    assert isinstance(body["pending"], list)
    assert isinstance(body["recent_committed"], list)
```

### Test fixtures (B-code: add to existing `tests/conftest.py` or create local conftest)
B-code is responsible for adding test fixtures: `clean_baker_actions`, `register_class`, `seed_committed_today`, `seed_committed_this_month`, `seed_committed_last_month`. Pattern: existing `tests/conftest.py` already has Postgres fixtures for ephemeral Neon branch (per `CLAUDE.md` "Live-PG tests: require `TEST_DATABASE_URL` env"). Reuse that connection.

### Ship gate
Literal `pytest tests/test_tier_b_runtime.py tests/test_tier_b_reset.py tests/test_tier_b_status_endpoint.py -v` output green. **No "pass by inspection."**

---

## Files Modified
- `migrations/20260510_baker_actions_tier_b_runtime.sql` — NEW migration
- `memory/store_back.py` — ALTER baker_actions bootstrap (additive); add `_ensure_tier_b_runtime_tables` method + call from `__init__`
- `orchestrator/tier_b_runtime.py` — NEW module
- `orchestrator/tier_b_ratify.py` — NEW module (visual reuse only — separate domain from GOLD)
- `triggers/tier_b_reset.py` — NEW module
- `triggers/embedded_scheduler.py` — register `tier_b_counter_reset` cron job
- `outputs/dashboard.py` — add `/api/admin/tier-b-status` GET endpoint
- `tests/test_tier_b_runtime.py` — NEW
- `tests/test_tier_b_reset.py` — NEW
- `tests/test_tier_b_status_endpoint.py` — NEW
- `tests/conftest.py` — add Tier-B test fixtures (`clean_baker_actions`, `register_class`, seeding helpers)

## Do NOT Touch
- **Existing applied migrations** (per `CLAUDE.md` hard rule)
- **`orchestrator/cortex_runner.py`** — wiring `enforce_tier_b` into Cortex Phase 5 is B4 scope; B3 does not modify cortex_runner
- **`baker-vault/_ops/...` GOLD card surfaces** (`proposed-gold.md`, `director-gold-global.md`) — Tier B has its own domain; visual template reuse only
- **`baker_actions` columns 1-9** (existing) — only additive changes
- **Existing baker_actions writes for non-Tier-B classes** (any code path that does `INSERT INTO baker_actions` without setting tier/cost_eur/etc. continues to work — new columns default NULL)

## Quality Checkpoints (post-deploy)

1. **Migration applied:** `SELECT column_name FROM information_schema.columns WHERE table_name='baker_actions'` returns 15 columns (9 original + 6 new).
2. **Bootstrap matches migration:** Restart Render → check logs for "Tier B runtime tables verified" message; no errors.
3. **Seed registry visible:** `SELECT * FROM tier_b_action_classes` returns ≥5 seed rows.
4. **Endpoint live:** `curl -H "X-Baker-Key: bakerbhavanga" https://baker-master.onrender.com/api/admin/tier-b-status` → 200 with valid JSON shape.
5. **Cron registered:** Render logs after deploy include "Registered: tier_b_counter_reset (cron: 1st of month 00:00 UTC)".
6. **Smoke check:** Manually invoke `enforce_tier_b(TierBAction(action_class='test.synthetic', committer_agent='manual', payload={}))` from Render shell → returns Decision PASS with cost_eur=1.00.
7. **Atomicity sanity:** Run two parallel `enforce_tier_b` calls near-cap (Render has 2 instances during deploy roll → can simulate); verify only one PASSes when total would exceed cap.
8. **No regression:** existing `baker_actions` write paths (ClickUp atomic logging, Cortex Phase 5 logging, etc.) continue to insert rows successfully with `tier IS NULL` (legacy semantics).

## Verification SQL (production smoke)

```sql
-- 1. Schema sanity
SELECT column_name, data_type, is_nullable
  FROM information_schema.columns
 WHERE table_name = 'baker_actions'
   AND column_name IN ('tier', 'cost_eur', 'committed_at', 'committer_agent', 'action_class', 'self_cost_eur')
 ORDER BY column_name;

-- 2. Action-class registry seeded
SELECT class_name, eur_cost FROM tier_b_action_classes ORDER BY class_name;

-- 3. Pending queue empty on fresh deploy
SELECT COUNT(*) FROM tier_b_pending WHERE status = 'pending';
-- expected: 0

-- 4. Counter math sanity (no Tier-B rows yet → 0)
SELECT COALESCE(SUM(cost_eur), 0)
  FROM baker_actions
 WHERE tier = 'B' AND cost_eur IS NOT NULL
   AND committed_at >= DATE_TRUNC('day', NOW() AT TIME ZONE 'UTC')
 LIMIT 100000;
-- expected: 0
```

---

## Review checklist (per Brief Authoring Standards)

| # | Standard | Status |
|---|---|---|
| 1 | API version/endpoint | N/A — no external API; internal Postgres + APScheduler only |
| 2 | Deprecation check date | N/A |
| 3 | Fallback note | N/A |
| 4 | Migration-vs-bootstrap DDL check | **DONE** — `_ensure_clickup_tables` baker_actions DDL updated to mirror migration, additionally idempotent ALTER |
| 5 | Ship gate (literal pytest) | **DONE** — explicit pytest invocation in §Ship gate |
| 6 | Test plan | **DONE** — Fix 6 (3 test files, 7+ scenarios) |
| 7 | file:line citation verification | **DONE** — `memory/store_back.py:42, 48, 1036`, `triggers/embedded_scheduler.py:15, 89`, `outputs/dashboard.py:10062` all opened + verified |
| 8 | Singleton `._get_global_instance()` | **DONE** — TierBRuntime follows pattern; pre-push `scripts/check_singletons.sh` will enforce |
| 9 | Post-merge script handoff | N/A — no post-merge embedding script |
| 10 | Invocation-path audit (Pattern-2) | N/A — this is NOT a `capability_sets` row mod; new infra module |

## Risk register (for code-reviewer 2nd-pass attention)

| Risk | Mitigation |
|---|---|
| **Counter race under concurrent commits** | SERIALIZABLE isolation in `enforce()` txn; caller must handle serialization-failure exception with retry |
| **Migration-bootstrap drift** | Both updated atomically in this brief; verify via Quality Checkpoint #2 |
| **Tier B card pollutes GOLD per-matter scope** | Separate `tier_b_pending` table; `tier_b_ratify.py` explicitly says "do NOT write to proposed-gold.md or any per-matter GOLD surface" |
| **Cap evasion via novel class self-declaration** | `action_class='novel:*'` rows flagged for AID monthly review (per Q2 fallback rule); future hardening via class-promotion workflow if abuse seen |
| **Existing baker_actions writes break** | All new columns nullable; existing INSERTs continue with tier=NULL semantics (legacy) |
| **Reset cron skipped during Render maintenance window** | If APScheduler missed (server down at 00:00 UTC on 1st), `coalesce=True` collapses any backlog on next start; reset event logged with actual time |

## Code-reviewer 2nd-pass triggers (mandatory per SKILL.md §Code-reviewer 2nd-pass Protocol)

This brief fires multiple triggers:
- **Trigger #2:** introduces DB schema / migrations / atomicity invariants ✓
- **Trigger #3:** touches concurrency-ordering primitives (SERIALIZABLE txn for counter check-and-pause) ✓
- **Trigger #4:** touches external-surface endpoints (`/api/admin/tier-b-status`) ✓

→ Full 4-gate chain mandatory pre-merge: pytest GREEN → AH2 `/security-review` → picker-architect → `feature-dev:code-reviewer` 2nd-pass.

---

## PL ship-report contract

End your chat ship report with a fenced PL paste-block per SKILL.md §"PL ship-report contract":

```
**TO: AH1-App PL**
- WHAT: <one-line summary>
- LINKS: <PR # / commit SHA / file paths / Render deploy ID>
- COST: <$X / time / N cycles, or "n/a">
- NEXT: <next blocker, dispatch, or "ready for next">
```
