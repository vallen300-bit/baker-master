# BRIEF: CORTEX_3T_FORMALIZE_1A — Cycle persistence + Phase 1/2/6 (sense / load / archive)

**Milestone:** Cortex Stage 2 V1 (Step 15 + Step 17 + part of Step 24 in `_ops/processes/cortex-stage2-v1-tracker.md`)
**Source spec:** `_ops/ideas/2026-04-27-cortex-3t-formalize-spec.md` (RA-22 ratified) + `_ops/processes/cortex-architecture-final.md` (RA-23 ratified)
**Estimated time:** ~12h
**Complexity:** Medium-High
**Trigger class:** MEDIUM (2 Postgres migrations + new orchestrator module + pipeline wiring) → B1 second-pair-review pre-merge per `_ops/ideas/2026-04-24-b1-situational-review-trigger.md`
**Prerequisites:** PR #67 WIKI_LINT_1 ✅ merged 2026-04-27 (`93f7d8e`); Cortex Stage 2 V1 Tasks 1+3+4+5 ✅ DONE (matter cortex-config.md absorbed; wiki/_cortex/ seeds; capability migration; tracker live)
**Companion sub-briefs:** `BRIEF_CORTEX_3T_FORMALIZE_1B` (Phase 3 reasoning) + `BRIEF_CORTEX_3T_FORMALIZE_1C` (Phase 4/5 + scheduler + dry-run + rollback). Director ratified split 2026-04-28.

---

## Context

This is sub-brief **1A of 3** for Cortex Stage 2 V1 build. Director ratified the split into 1A/1B/1C 2026-04-28 to avoid the SPECIALIST-UPGRADE-1 monolithic-brief failure mode (5 features bundled → 19 bugs). 1A is the foundation: schema + runner skeleton + Phase 1/2/6 (the "shell" without the brain). 1B adds Phase 3 reasoning; 1C adds Phase 4/5 proposal + act + scheduler + dry-run + rollback.

1A ships a runner that creates a cycle row on inbound signal, loads matter + curated + recent-activity context, persists per-phase artifacts to Postgres, and archives the cycle (status remains `awaiting_reason` until 1B lands). Pipeline wiring is **stubbed in 1A** — `signal_queue` insert calls a no-op cortex_runner; the live wire happens in 1C after 1B's reasoning is in place.

Anthropic Memory is dead per Director 2026-04-28 — this brief uses Postgres + wiki only.

---

## Problem

Baker has no formal Cortex cycle today. Signals land in `signal_queue`, AO matter routing fires `ao_signal_detector` direct-to-action, but there's no named-phase persistence, no per-cycle cost tracking, no cross-matter generalizable cycle. The chain_runner has a 6-step pipeline that maps almost 1:1 onto Cortex 6 phases but is unnamed and unpersisted. We can't reason about Cortex performance, cost, or improvement loops without cycle records.

## Solution

Build `orchestrator/cortex_runner.py` as a thin wrapper around the existing `chain_runner.maybe_run_chain()` (`outputs/orchestrator/chain_runner.py:688`) that adds named-phase persistence into 2 new Postgres tables (`cortex_cycles` + `cortex_phase_outputs`). Phase 1 (sense) creates the cycle row from a signal. Phase 2 (load) reads matter cortex-config.md (already absorbed in Task 3) + curated/ + entity profiles + recent activity (3 SQL queries). Phase 6 (archive) finalizes cycle status. Phases 3-5 are stub functions that return immediately with status `awaiting_reason` (1B fills 3a/3b/3c; 1C fills 4-5).

A 5-min absolute cycle timeout wraps the entire cycle via `asyncio.wait_for` (per Director RA-23 Q5+ ratification — caps worst-case cascading-specialist exposure to 5 min).

---

## Fix/Feature 1: Migrations — `cortex_cycles` + `cortex_phase_outputs`

### Problem
No persistent record of Cortex reasoning cycles or per-phase artifacts.

### Current State
Tables do not exist. Verified via `SELECT table_name FROM information_schema.tables WHERE table_name IN ('cortex_cycles','cortex_phase_outputs')` → 0 rows.

### Implementation

**Create `migrations/20260428_cortex_cycles.sql`** (DDL verbatim from spec §"What gets built" item 1):

```sql
-- migrate:up
CREATE TABLE IF NOT EXISTS cortex_cycles (
    cycle_id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    matter_slug        TEXT NOT NULL,
    triggered_by       TEXT NOT NULL,
        -- 'signal' / 'director' / 'cron' / 'gold_comment' / 'refresh'
    trigger_signal_id  BIGINT,
    started_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at       TIMESTAMPTZ,
    last_loaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        -- updated on each refresh; used by final-freshness check (1C)
    current_phase      TEXT NOT NULL DEFAULT 'sense'
        CHECK (current_phase IN ('sense','load','reason','propose','act','archive')),
    status             TEXT NOT NULL DEFAULT 'in_flight'
        CHECK (status IN ('in_flight','awaiting_reason','proposed','tier_b_pending','approved','rejected','modified','failed','superseded','abandoned')),
    proposal_id        UUID,
    director_action    TEXT,
        -- 'gold_approved' / 'gold_modified' / 'gold_rejected' / 'refresh_requested'
    feedback_ledger_id BIGINT,
    cost_tokens        INTEGER DEFAULT 0,
    cost_dollars       NUMERIC(10,4) DEFAULT 0,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cortex_cycles_matter_status
    ON cortex_cycles (matter_slug, status, started_at DESC);

-- migrate:down
-- DROP INDEX IF EXISTS idx_cortex_cycles_matter_status;
-- DROP TABLE IF EXISTS cortex_cycles;
```

Note: `awaiting_reason` status added vs the original spec to support the 1A-shipped-without-1B intermediate state. 1B adds `proposed` flow; 1C adds `tier_b_pending`/`approved`/etc.

**Create `migrations/20260428_cortex_phase_outputs.sql`**:

```sql
-- migrate:up
CREATE TABLE IF NOT EXISTS cortex_phase_outputs (
    output_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cycle_id       UUID NOT NULL REFERENCES cortex_cycles(cycle_id) ON DELETE CASCADE,
    phase          TEXT NOT NULL
        CHECK (phase IN ('sense','load','reason','propose','act','archive')),
    phase_order    INT NOT NULL,
    artifact_type  TEXT NOT NULL,
    payload        JSONB NOT NULL,
    citations      JSONB DEFAULT '[]'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cortex_phase_outputs_cycle_phase
    ON cortex_phase_outputs (cycle_id, phase_order);

-- migrate:down
-- DROP INDEX IF EXISTS idx_cortex_phase_outputs_cycle_phase;
-- DROP TABLE IF EXISTS cortex_phase_outputs;
```

### Bootstrap mirror in `memory/store_back.py`

Following the canonical pattern (`_ensure_ai_head_audits_table` etc.), add 2 functions and call them in `__init__` (search for `_ensure_*_table` to find the call list, mirror exactly):

```python
def _ensure_cortex_cycles_table(self, cur) -> None:
    """Bootstrap mirror of migrations/20260428_cortex_cycles.sql.
    Idempotent — safe to run on every startup. Column-for-column with migration."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cortex_cycles (
            cycle_id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            matter_slug        TEXT NOT NULL,
            triggered_by       TEXT NOT NULL,
            trigger_signal_id  BIGINT,
            started_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at       TIMESTAMPTZ,
            last_loaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            current_phase      TEXT NOT NULL DEFAULT 'sense'
                CHECK (current_phase IN ('sense','load','reason','propose','act','archive')),
            status             TEXT NOT NULL DEFAULT 'in_flight'
                CHECK (status IN ('in_flight','awaiting_reason','proposed','tier_b_pending','approved','rejected','modified','failed','superseded','abandoned')),
            proposal_id        UUID,
            director_action    TEXT,
            feedback_ledger_id BIGINT,
            cost_tokens        INTEGER DEFAULT 0,
            cost_dollars       NUMERIC(10,4) DEFAULT 0,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_cortex_cycles_matter_status
            ON cortex_cycles (matter_slug, status, started_at DESC)
    """)


def _ensure_cortex_phase_outputs_table(self, cur) -> None:
    """Bootstrap mirror of migrations/20260428_cortex_phase_outputs.sql."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cortex_phase_outputs (
            output_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            cycle_id       UUID NOT NULL REFERENCES cortex_cycles(cycle_id) ON DELETE CASCADE,
            phase          TEXT NOT NULL
                CHECK (phase IN ('sense','load','reason','propose','act','archive')),
            phase_order    INT NOT NULL,
            artifact_type  TEXT NOT NULL,
            payload        JSONB NOT NULL,
            citations      JSONB DEFAULT '[]'::jsonb,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_cortex_phase_outputs_cycle_phase
            ON cortex_phase_outputs (cycle_id, phase_order)
    """)
```

**EXPLORE step before coding:** Grep `memory/store_back.py` for `_ensure_ai_head_audits_table` to find the canonical call site in `__init__`. Add the two new calls in the same block, in alphabetical order. Use `cur.close()` pattern matching existing functions (no context manager — Lesson #2/#44).

### Migration-vs-bootstrap drift check (LONGTERM.md rule)
B-code MUST run: `diff <(grep -A 20 "CREATE TABLE IF NOT EXISTS cortex_cycles" migrations/20260428_cortex_cycles.sql) <(grep -A 20 "CREATE TABLE IF NOT EXISTS cortex_cycles" memory/store_back.py)` → expect zero column-name/type drift. Repeat for cortex_phase_outputs.

---

## Fix/Feature 2: `orchestrator/cortex_runner.py` skeleton + 5-min absolute timeout

### Problem
No named-phase Cortex runner exists; chain_runner is the closest analogue but has no cycle persistence, no per-phase outputs, no matter-config wiki loading.

### Current State
- `orchestrator/chain_runner.py:688` — `maybe_run_chain(trigger_type, trigger_content, alert_id, alert_title, alert_body, alert_tier, matter_slug) -> ChainResult` (sync). Verified via subagent code map.
- No `orchestrator/cortex_runner.py` exists today (`ls orchestrator/cortex*` returns 0 matches).

### Implementation

Create `orchestrator/cortex_runner.py` as a NEW module (~250 LOC). Skeleton structure:

```python
"""Cortex 3T runner — Stage 2 V1 (sub-brief 1A: cycle skeleton + Phase 1/2/6).

Wraps chain_runner.maybe_run_chain with named-phase persistence into
cortex_cycles + cortex_phase_outputs Postgres tables. 1B adds Phase 3a/3b/3c
(reasoning); 1C adds Phase 4/5 (proposal + act).

Spec: _ops/ideas/2026-04-27-cortex-3t-formalize-spec.md (RA-22)
Architecture: _ops/processes/cortex-architecture-final.md (RA-23)
"""
import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from memory.store_back import SentinelStoreBack

logger = logging.getLogger(__name__)

CYCLE_TIMEOUT_SECONDS = int(os.getenv("CORTEX_CYCLE_TIMEOUT_SECONDS", "300"))  # 5 min absolute (RA-23 Q5+)


@dataclass
class CortexCycle:
    """Mirror of cortex_cycles row + transient phase artifacts during execution."""
    cycle_id: str
    matter_slug: str
    triggered_by: str  # 'signal' / 'director' / 'cron' / 'gold_comment' / 'refresh'
    trigger_signal_id: Optional[int] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    current_phase: str = "sense"
    status: str = "in_flight"
    cost_tokens: int = 0
    cost_dollars: float = 0.0
    # Transient — not persisted on row, used during cycle:
    phase2_load_context: dict = field(default_factory=dict)
    aborted_reason: Optional[str] = None


async def maybe_run_cycle(
    *,
    matter_slug: str,
    triggered_by: str,
    trigger_signal_id: Optional[int] = None,
    director_question: Optional[str] = None,
) -> CortexCycle:
    """Entry point — wraps full cycle in 5-min asyncio.wait_for.

    1A scope: Phase 1 (sense) + Phase 2 (load) + Phase 6 (archive).
    Status terminates at 'awaiting_reason' until 1B lands.
    """
    try:
        return await asyncio.wait_for(
            _run_cycle_inner(
                matter_slug=matter_slug,
                triggered_by=triggered_by,
                trigger_signal_id=trigger_signal_id,
                director_question=director_question,
            ),
            timeout=CYCLE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.error(
            "Cortex cycle timed out after %ds (matter=%s, signal=%s)",
            CYCLE_TIMEOUT_SECONDS, matter_slug, trigger_signal_id,
        )
        # Best-effort cycle-row update to status='failed' on timeout
        try:
            store = SentinelStoreBack()
            conn = store._get_conn()
            cur = conn.cursor()
            cur.execute(
                "UPDATE cortex_cycles SET status='failed', completed_at=NOW() "
                "WHERE matter_slug=%s AND trigger_signal_id=%s AND status='in_flight'",
                (matter_slug, trigger_signal_id),
            )
            conn.commit()
            cur.close()
            store._put_conn(conn)
        except Exception as e:
            logger.error(f"Failed to mark timed-out cycle as failed: {e}")
        # Re-raise so upstream pipeline can handle
        raise


async def _run_cycle_inner(
    *,
    matter_slug: str,
    triggered_by: str,
    trigger_signal_id: Optional[int],
    director_question: Optional[str],
) -> CortexCycle:
    """The real work — split out so asyncio.wait_for can wrap it."""
    cycle = CortexCycle(
        cycle_id=str(uuid.uuid4()),
        matter_slug=matter_slug,
        triggered_by=triggered_by,
        trigger_signal_id=trigger_signal_id,
    )

    # Phase 1 — sense (create cycle row)
    await _phase1_sense(cycle)

    # Phase 2 — load
    cycle.current_phase = "load"
    await _phase2_load(cycle)

    # Phase 3-5 — STUBS in 1A (1B fills 3; 1C fills 4-5)
    cycle.current_phase = "reason"
    cycle.status = "awaiting_reason"
    logger.info(
        "Cortex 1A scope: Phase 3-5 not yet implemented; cycle %s parked at status=awaiting_reason",
        cycle.cycle_id,
    )

    # Phase 6 — archive (always runs, finalizes cycle row)
    cycle.current_phase = "archive"
    await _phase6_archive(cycle)

    return cycle


async def _phase1_sense(cycle: CortexCycle) -> None:
    """Phase 1 — INSERT into cortex_cycles + write a sense artifact row.

    Trusts upstream classification — does NOT re-classify (per architecture §3 step 2).
    """
    store = SentinelStoreBack()
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO cortex_cycles (cycle_id, matter_slug, triggered_by,
                trigger_signal_id, current_phase, status)
            VALUES (%s, %s, %s, %s, 'sense', 'in_flight')
            RETURNING cycle_id
            """,
            (cycle.cycle_id, cycle.matter_slug, cycle.triggered_by, cycle.trigger_signal_id),
        )
        cur.execute(
            """
            INSERT INTO cortex_phase_outputs (cycle_id, phase, phase_order, artifact_type, payload)
            VALUES (%s, 'sense', 1, 'cycle_init', %s::jsonb)
            """,
            (cycle.cycle_id,
             '{"triggered_by": "%s", "matter_slug": "%s"}' % (cycle.triggered_by, cycle.matter_slug)),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        conn.rollback()
        logger.error(f"Phase 1 sense failed for cycle {cycle.cycle_id}: {e}")
        raise
    finally:
        store._put_conn(conn)


async def _phase2_load(cycle: CortexCycle) -> None:
    """Phase 2 — load matter cortex-config + curated knowledge + recent activity.

    Loader functions live in orchestrator/cortex_phase2_loaders.py.
    Persists merged context to cortex_phase_outputs.
    """
    from orchestrator.cortex_phase2_loaders import load_phase2_context

    context = await load_phase2_context(cycle.matter_slug)
    cycle.phase2_load_context = context

    store = SentinelStoreBack()
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        # NOTE: payload is JSONB; psycopg2 auto-converts dict via Json adapter; if not, json.dumps
        import json
        cur.execute(
            """
            INSERT INTO cortex_phase_outputs (cycle_id, phase, phase_order, artifact_type, payload)
            VALUES (%s, 'load', 2, 'phase2_context', %s::jsonb)
            """,
            (cycle.cycle_id, json.dumps(context, default=str)),
        )
        cur.execute(
            "UPDATE cortex_cycles SET current_phase='load', last_loaded_at=NOW() "
            "WHERE cycle_id=%s",
            (cycle.cycle_id,),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        conn.rollback()
        logger.error(f"Phase 2 load failed for cycle {cycle.cycle_id}: {e}")
        raise
    finally:
        store._put_conn(conn)


async def _phase6_archive(cycle: CortexCycle) -> None:
    """Phase 6 — finalize cycle row.

    1A scope: status remains 'awaiting_reason' (1B/1C land Phase 3-5).
    Sets completed_at + final cost_tokens/cost_dollars (1A: zero;
    real cost lands when 1B's reasoning runs).
    """
    store = SentinelStoreBack()
    conn = store._get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO cortex_phase_outputs (cycle_id, phase, phase_order, artifact_type, payload)
            VALUES (%s, 'archive', 6, 'cycle_archive',
                    '{"reason": "1A scope — Phase 3-5 stub; awaiting 1B/1C"}'::jsonb)
            """,
            (cycle.cycle_id,),
        )
        cur.execute(
            """
            UPDATE cortex_cycles
            SET current_phase='archive', completed_at=NOW(),
                cost_tokens=%s, cost_dollars=%s
            WHERE cycle_id=%s
            """,
            (cycle.cost_tokens, cycle.cost_dollars, cycle.cycle_id),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        conn.rollback()
        logger.error(f"Phase 6 archive failed for cycle {cycle.cycle_id}: {e}")
        raise
    finally:
        store._put_conn(conn)
```

### Key Constraints
- **Lesson #2/#3:** every column name verified against the migration above; column types match
- **Lesson #19/#44:** all function calls (`SentinelStoreBack()`, `_get_conn`, `_put_conn`) verified via subagent code map
- Every `except` does `conn.rollback()` (Lesson #1)
- Every SQL parameterized via `%s` (no f-string interpolation)
- 5-min `asyncio.wait_for` is the OUTER wrap (RA-23 Q5+ ratification)
- Phase 6 ALWAYS runs even on early failure — wrap Phase 1-5 in try/except; in `except`, set status='failed' + still call _phase6_archive

---

## Fix/Feature 3: Phase 2 loaders — `orchestrator/cortex_phase2_loaders.py`

### Problem
No unified loader for matter cortex-config + curated knowledge + entity profiles + recent activity exists.

### Current State
- `wiki/matters/<slug>/cortex-config.md` written for `oskolkov` + `movie` in Task 3 (commit `32a370f`)
- `wiki/_cortex/director-gold-global.md` + `cross-matter-patterns.md` + `brisen-style.md` seeded in Task 4 (commit `0203322`)
- `BAKER_VAULT_PATH` env var points at `/Users/dimitry/baker-vault` on Render

### Implementation

Create `orchestrator/cortex_phase2_loaders.py` (~150 LOC):

```python
"""Cortex Phase 2 (load) — unified context loader.

Reads:
- wiki/matters/<slug>/cortex-config.md (matter system prompt + frontmatter)
- wiki/matters/<slug>/state.md (current matter state)
- wiki/matters/<slug>/proposed-gold.md (Director-confirmed insights)
- wiki/matters/<slug>/curated/*.md (prior capability outputs — accumulated)
- wiki/_cortex/director-gold-global.md + cross-matter-patterns.md + brisen-style.md
- recent activity (3 SQL queries, 14d window)
"""
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _vault_root() -> Path:
    return Path(os.getenv("BAKER_VAULT_PATH", "/tmp/baker-vault-missing"))


async def load_phase2_context(matter_slug: str, days: int = 14) -> dict[str, Any]:
    """Loads matter config + curated + entity + recent activity.

    Returns dict with keys:
        matter_config (str), state (str), proposed_gold (str),
        curated (dict[str, str]), cortex_meta (dict[str, str]),
        recent_activity (dict[str, list]).

    Returns empty strings/dicts for missing files (graceful degradation).
    """
    vault = _vault_root()
    if not vault.exists():
        logger.warning(f"BAKER_VAULT_PATH={vault} does not exist; Phase 2 returns empty context")
        return {"warning": "vault_unavailable"}

    matter_dir = vault / "wiki" / "matters" / matter_slug
    if not matter_dir.is_dir():
        logger.warning(f"Matter dir {matter_dir} not found; Phase 2 returns empty matter context")
        # Still return _cortex meta + recent activity
        return {
            "matter_config": "",
            "state": "",
            "proposed_gold": "",
            "curated": {},
            "cortex_meta": _load_cortex_meta(vault),
            "recent_activity": await _load_recent_activity(matter_slug, days),
        }

    return {
        "matter_config": _read_or_empty(matter_dir / "cortex-config.md"),
        "state": _read_or_empty(matter_dir / "state.md"),
        "proposed_gold": _read_or_empty(matter_dir / "proposed-gold.md"),
        "curated": _load_curated_dir(matter_dir / "curated"),
        "cortex_meta": _load_cortex_meta(vault),
        "recent_activity": await _load_recent_activity(matter_slug, days),
    }


def _read_or_empty(p: Path, max_bytes: int = 200_000) -> str:
    """Read .md file; cap at 200KB; return empty if missing or oversize."""
    if not p.is_file():
        return ""
    try:
        size = p.stat().st_size
        if size > max_bytes:
            logger.warning(f"{p} exceeds {max_bytes} bytes ({size}); truncating")
        return p.read_text(encoding="utf-8", errors="replace")[:max_bytes]
    except Exception as e:
        logger.error(f"Failed to read {p}: {e}")
        return ""


def _load_curated_dir(curated_dir: Path) -> dict[str, str]:
    """Load all .md files in curated/ as {filename: content}."""
    if not curated_dir.is_dir():
        return {}
    result = {}
    for f in sorted(curated_dir.glob("*.md")):
        result[f.name] = _read_or_empty(f)
    return result


def _load_cortex_meta(vault: Path) -> dict[str, str]:
    """Load wiki/_cortex/{director-gold-global,cross-matter-patterns,brisen-style}.md."""
    cortex_dir = vault / "wiki" / "_cortex"
    return {
        "director_gold_global": _read_or_empty(cortex_dir / "director-gold-global.md"),
        "cross_matter_patterns": _read_or_empty(cortex_dir / "cross-matter-patterns.md"),
        "brisen_style": _read_or_empty(cortex_dir / "brisen-style.md"),
    }


async def _load_recent_activity(matter_slug: str, days: int) -> dict[str, list]:
    """Director outbound + entity inbound + baker_actions (last N days).

    NOTE: This is a thin wrapper around 3 SQL SELECTs. Matter-keyword + entity
    resolution is delegated to existing helpers in capability_runner.py if
    available, else falls back to ILIKE on matter_slug.
    """
    from memory.store_back import SentinelStoreBack
    DIRECTOR_EMAILS = {"dvallen@brisengroup.com", "vallen300@gmail.com"}

    store = SentinelStoreBack()
    conn = store._get_conn()
    result = {"director_outbound": [], "entity_inbound": [], "baker_actions": []}
    try:
        cur = conn.cursor()
        # Director outbound — sent_emails matching matter slug in subject/body
        cur.execute(
            """
            SELECT subject, to_address, created_at
            FROM sent_emails
            WHERE created_at >= NOW() - INTERVAL '%s days'
              AND (subject ILIKE %s OR body ILIKE %s)
            ORDER BY created_at DESC
            LIMIT 30
            """,
            (days, f"%{matter_slug}%", f"%{matter_slug}%"),
        )
        result["director_outbound"] = [
            {"subject": r[0], "to": r[1], "created_at": r[2].isoformat() if r[2] else None}
            for r in cur.fetchall()
        ]
        # Entity inbound — email_messages where primary_matter matches
        cur.execute(
            """
            SELECT subject, sender_email, received_date
            FROM email_messages
            WHERE received_date >= NOW() - INTERVAL '%s days'
              AND primary_matter = %s
            ORDER BY received_date DESC
            LIMIT 30
            """,
            (days, matter_slug),
        )
        result["entity_inbound"] = [
            {"subject": r[0], "from": r[1], "received_at": r[2].isoformat() if r[2] else None}
            for r in cur.fetchall()
        ]
        # baker_actions on this matter (via target_task_id or payload jsonb match)
        cur.execute(
            """
            SELECT action_type, target_task_id, created_at
            FROM baker_actions
            WHERE created_at >= NOW() - INTERVAL '%s days'
              AND (target_task_id ILIKE %s OR payload::text ILIKE %s)
            ORDER BY created_at DESC
            LIMIT 30
            """,
            (days, f"%{matter_slug}%", f"%{matter_slug}%"),
        )
        result["baker_actions"] = [
            {"action_type": r[0], "target": r[1], "created_at": r[2].isoformat() if r[2] else None}
            for r in cur.fetchall()
        ]
        cur.close()
    except Exception as e:
        conn.rollback()
        logger.error(f"_load_recent_activity failed for {matter_slug}: {e}")
    finally:
        store._put_conn(conn)
    return result
```

### Key Constraints
- **Lesson #1/#42:** every SELECT has LIMIT (30); column names verified (`primary_matter` exists on `email_messages` per `signal_queue` extension migration `20260418`; if not on `email_messages`, B-code MUST verify and adjust to `signal_queue` join — see EXPLORE step below)
- **Vault read failure is graceful** — empty strings/dicts, not exceptions
- 200KB file-size cap prevents OOM on accidentally-huge curated entries

### EXPLORE step before coding (Lesson #44)
B-code MUST verify:
1. `email_messages.primary_matter` column exists (`SELECT column_name FROM information_schema.columns WHERE table_name='email_messages' AND column_name='primary_matter'`). If NOT → adjust query to JOIN through `signal_queue` (which definitively has `primary_matter`).
2. `sent_emails.body` column exists (the alternative is `full_body` — verify before using).
3. `baker_actions.payload` is jsonb (verified True per Task 3 audit row 337 schema query).

---

## Fix/Feature 4: Pipeline wiring stub

### Problem
1A ships the runner but does NOT wire it into the live pipeline. 1C lands the live wire after 1B's reasoning is in place.

### Current State
`triggers/pipeline.py` (or equivalent) inserts rows into `signal_queue` after sentinel classification. No call to `cortex_runner` exists.

### Implementation
Add a NO-OP wrapper in `triggers/pipeline.py` (B-code MUST grep for the canonical signal_queue INSERT call site to determine exact location). The wrapper:

```python
async def _maybe_trigger_cortex(signal_id: int, matter_slug: str | None) -> None:
    """1A scope: stub. 1C lands the live wire.

    Writing this as a stub now ensures the call site exists and 1C can
    flip the env-flag CORTEX_LIVE_PIPELINE to enable.
    """
    if not os.getenv("CORTEX_LIVE_PIPELINE", "false").lower() == "true":
        # 1A default — stub is dormant
        return
    if not matter_slug:
        return
    try:
        from orchestrator.cortex_runner import maybe_run_cycle
        await maybe_run_cycle(
            matter_slug=matter_slug,
            triggered_by="signal",
            trigger_signal_id=signal_id,
        )
    except Exception as e:
        logger.error(f"Cortex cycle trigger failed for signal {signal_id}: {e}")
        # Do NOT re-raise — pipeline must continue regardless
```

Call site: AFTER the `signal_queue` INSERT commits, BEFORE the next signal is processed. B-code MUST identify the exact pipeline.py line via grep.

---

## Files Modified

**Create (4):**
- `migrations/20260428_cortex_cycles.sql`
- `migrations/20260428_cortex_phase_outputs.sql`
- `orchestrator/cortex_runner.py`
- `orchestrator/cortex_phase2_loaders.py`

**Modify (2):**
- `memory/store_back.py` — add `_ensure_cortex_cycles_table` + `_ensure_cortex_phase_outputs_table` + call them in `__init__` block (mirror `_ensure_ai_head_audits_table` pattern)
- `triggers/pipeline.py` — add `_maybe_trigger_cortex` stub wrapper + call site after signal_queue INSERT (env-flag dormant by default)

**Tests (NEW):**
- `tests/test_cortex_runner_phase126.py` — covers Phase 1+2+6 happy path, timeout abort, Phase 1 DB error rollback, Phase 6 always-runs even on Phase 2 fail
- `tests/test_cortex_phase2_loaders.py` — covers vault available/missing, matter dir found/missing, curated dir empty/full, recent activity 3-query happy path with stub DB

## Files NOT to touch

- `orchestrator/chain_runner.py` — Cortex wraps it semantically; no edits in 1A
- `orchestrator/capability_runner.py` — no edits in 1A (1B's Phase 3b uses it as-is)
- `kbl/gold_writer.py` — 1C territory, not 1A
- `outputs/dashboard.py` — Slack endpoint is 1C territory, not 1A
- `triggers/embedded_scheduler.py` — drift APScheduler job is 1C territory
- All `BRIEF_CORTEX_PHASE_*.md` — historical M0 artefact (Director ratified leave-as-is 2026-04-28)

---

## Code Brief Standards (mandatory)

- **API version:** Internal Postgres + FastAPI; no external API changes. psycopg2 + asyncio existing.
- **Deprecation check date:** All referenced functions (`SentinelStoreBack._get_conn`, `chain_runner.maybe_run_chain`) verified active 2026-04-28 via subagent code map.
- **Fallback:** `CORTEX_LIVE_PIPELINE=false` (default) keeps Phase-1-stub dormant. Code ships, doesn't auto-fire. 1C flips the flag after dry-run clean.
- **DDL drift check:** B-code MUST `diff` migration vs bootstrap mirror per Migration-vs-bootstrap rule above. Zero drift required.
- **Literal pytest output mandatory:** Ship report MUST include literal `pytest tests/test_cortex_runner_phase126.py tests/test_cortex_phase2_loaders.py -v` stdout. ≥18 tests expected (Phase 1+2+6 × ~6 cases each). NO "by inspection."
- **Function-signature verification (Lesson #44):** before coding, B-code MUST grep:
  - `def _ensure_ai_head_audits_table` in `memory/store_back.py` to find canonical bootstrap pattern
  - `INSERT INTO signal_queue` in `triggers/pipeline.py` to find Phase 1 wire location
  - `email_messages` columns to confirm `primary_matter` presence

## Verification criteria

1. `pytest tests/test_cortex_runner_phase126.py tests/test_cortex_phase2_loaders.py -v` ≥18 tests pass, 0 regressions in existing test suite.
2. `python3 -c "import py_compile; py_compile.compile('orchestrator/cortex_runner.py', doraise=True); py_compile.compile('orchestrator/cortex_phase2_loaders.py', doraise=True); py_compile.compile('memory/store_back.py', doraise=True); py_compile.compile('triggers/pipeline.py', doraise=True)"` exits 0.
3. Migration runs cleanly on first deploy (Render auto-deploy + bootstrap mirror cover this; verify via `\dt cortex_*` post-deploy → 2 tables).
4. Cortex cycle dry-run from Python REPL: `await maybe_run_cycle(matter_slug='oskolkov', triggered_by='director')` → returns `CortexCycle` with status='awaiting_reason', cycle_id present, 1 row in `cortex_cycles`, 3 rows in `cortex_phase_outputs` (sense + load + archive).
5. Pipeline stub is dormant by default (no cycle row created on signal_queue INSERT unless `CORTEX_LIVE_PIPELINE=true`).
6. 5-min absolute timeout test: stub Phase 2 to sleep 6 min → `asyncio.TimeoutError` raised → cycle row marked status='failed'.
7. Phase 6 always runs: stub Phase 2 to raise → cycle row still has Phase 6 archive output + status='failed' (NOT 'awaiting_reason').

## Quality Checkpoints

1. Migration-vs-bootstrap drift: zero column-name/type difference (Lesson #2 cousin)
2. Every `except` block has `conn.rollback()` (Lesson #1)
3. Every SELECT has LIMIT (Lesson #1)
4. `BAKER_VAULT_PATH` graceful: missing path returns `{"warning": "vault_unavailable"}` (does not crash)
5. `cycle_id` is UUID (verified by Postgres CHECK; psycopg2 returns str)
6. JSONB payload casts use `::jsonb` in INSERT (matches existing pattern)
7. `from orchestrator.cortex_runner import maybe_run_cycle` works from Python REPL post-deploy
8. `triggers/pipeline.py` stub does NOT crash if `cortex_runner` import fails (defensive try/except recommended)
9. No new entries in `requirements.txt`
10. All 4 sub-brief follow-up touchpoints (1B Phase 3, 1C Phase 4-5/scheduler/dry-run/rollback) explicitly noted as out-of-scope in code comments

## Verification SQL

```sql
-- Confirm tables exist post-deploy
SELECT table_name, COUNT(column_name)
FROM information_schema.columns
WHERE table_name IN ('cortex_cycles', 'cortex_phase_outputs')
GROUP BY table_name;
-- Expected: cortex_cycles=15, cortex_phase_outputs=7

-- Confirm a dry-run cycle persisted
SELECT cycle_id, matter_slug, status, current_phase, completed_at
FROM cortex_cycles
WHERE matter_slug='oskolkov'
ORDER BY started_at DESC
LIMIT 5;
-- Expected: status='awaiting_reason', current_phase='archive', completed_at NOT NULL

-- Confirm phase outputs
SELECT phase, phase_order, artifact_type
FROM cortex_phase_outputs
WHERE cycle_id=(SELECT cycle_id FROM cortex_cycles WHERE matter_slug='oskolkov' ORDER BY started_at DESC LIMIT 1)
ORDER BY phase_order;
-- Expected: 3 rows: (sense, 1, cycle_init), (load, 2, phase2_context), (archive, 6, cycle_archive)
```

## Out of scope

- Phase 3 reasoning (1B's territory)
- Phase 4 proposal card / Phase 5 act / GOLD propagation (1C's territory)
- Slack Block Kit posting / `/cortex/cycle/{id}/action` endpoint (1C)
- APScheduler matter-config drift weekly job (1C)
- Step 29 DRY_RUN flag (1C)
- Step 33 rollback script (1C)
- Live pipeline activation (`CORTEX_LIVE_PIPELINE=true`) — 1C decommission step
- Decommission of `ao_signal_detector` / `ao_project_state` — Step 34-35 (post-1C, Director-consult)

## Branch + PR

- Branch: `cortex-3t-formalize-1a`
- PR title: `CORTEX_3T_FORMALIZE_1A: cycle persistence + Phase 1/2/6 (sense/load/archive)`
- Reviewer: B1 second-pair (MEDIUM trigger class) → AI Head B Tier-A merge on APPROVE + `/security-review` skill PASS

## Co-Authored-By

```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
