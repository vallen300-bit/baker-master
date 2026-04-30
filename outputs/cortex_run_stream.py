"""CORTEX_MANUAL_INVOKE_1: SSE streaming + rate limit + cost guardrail
helpers for POST /api/cortex/run.

Streaming model: spawn ``maybe_run_cycle`` as a background ``asyncio.Task``.
Poll ``cortex_cycles.current_phase`` + ``cortex_phase_outputs`` row count
every ``POLL_INTERVAL_SECONDS``. Emit SSE events on transitions. Terminal
event when the cycle task resolves (success / timeout / error). The cycle
task continues to completion even if the SSE consumer disconnects — we
never cancel it on the client side.

Pure unit-testable: no FastAPI imports. Endpoint code in
``outputs/dashboard.py`` wraps ``stream_cycle_events`` in a
``StreamingResponse``.

Schema notes (verified 2026-04-29 vs migrations + memory/store_back.py —
Lesson #40 cousin: brief named the wrong table):
    cortex_cycles: cycle_id UUID PK, matter_slug, triggered_by, started_at,
                    status, current_phase, cost_tokens, cost_dollars.
    cortex_phase_outputs: cycle_id FK, phase, phase_order, artifact_type,
                          payload JSONB, created_at — Phase 3b specialist
                          invocations land here with
                          artifact_type='specialist_invocation' (NOT
                          capability_runs, which has no matter_slug column).
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import time
from typing import AsyncIterator, Optional

logger = logging.getLogger(__name__)


POLL_INTERVAL_SECONDS = float(os.environ.get("CORTEX_RUN_POLL_INTERVAL", "0.5"))
RUN_RATE_LIMIT_PER_HOUR = int(os.environ.get("CORTEX_RUN_RATE_LIMIT", "5"))
COST_WARN_SPECIALIST_PER_DAY = int(
    os.environ.get("CORTEX_COST_WARN_SPECIALIST_PER_DAY", "30")
)

# F-1 FIX (PR #88 AI Head B re-review): wall-clock slack subtracted from
# `now()` when ``stream_cycle_events`` captures its cycle anchor. Absorbs
# the small gap between ``asyncio.create_task`` scheduling and Phase 1's
# ``INSERT INTO cortex_cycles`` commit (Phase 1 is local logic + one
# INSERT, well under 2s in practice). Module-level so tests can
# monkeypatch a smaller value to exercise tight concurrent-isolation
# scenarios without a real-time wait. NOT exposed as an env var per
# brief Key Constraint #6 ("DO NOT add a new env var beyond the 3
# declared").
SSE_ANCHOR_SLACK_SECONDS = 2.0

# Surfaces this module accepts as "Director-manual" runs for rate-limit
# accounting. Matches the values the run endpoint and Scan-intent branch
# pass into maybe_run_cycle. Excludes signal-driven cycles (auto-triggered)
# so a busy upstream sentinel cannot lock the Director out of manual runs.
_MANUAL_TRIGGER_VALUES = ("director_manual", "scan_intent")


def _sse(payload: dict) -> str:
    """Format a dict payload as a single SSE ``data:`` line block."""
    return f"data: {json.dumps(payload)}\n\n"


def _get_store():
    """Resolve the SentinelStoreBack singleton via the canonical accessor.

    Lazy import so the helper module stays importable in unit tests that
    monkeypatch the store. CI guard: scripts/check_singletons.sh prohibits
    direct constructor calls; this accessor returns the cached singleton.
    """
    from memory.store_back import SentinelStoreBack
    return SentinelStoreBack._get_global_instance()


def runs_in_last_hour(matter_slug: str) -> int:
    """Count cycles in the last hour for ``matter_slug`` across manual triggers.

    Returns 0 on DB unavailability — fail-open for rate-limit (we'd rather
    let one extra cycle through than 503 the Director when the DB hiccups).
    The cost gate covers the runaway case.
    """
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        return 0
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM cortex_cycles "
            "WHERE matter_slug = %s "
            "AND triggered_by = ANY(%s) "
            "AND started_at > NOW() - INTERVAL '1 hour'",
            (matter_slug, list(_MANUAL_TRIGGER_VALUES)),
        )
        row = cur.fetchone()
        cur.close()
        return int((row or [0])[0])
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("runs_in_last_hour failed matter=%s: %s", matter_slug, e)
        return 0
    finally:
        store._put_conn(conn)


def specialist_calls_today(matter_slug: str) -> int:
    """Count Phase 3 specialist invocations in the last 24h for matter_slug.

    Source: cortex_phase_outputs rows with artifact_type='specialist_invocation',
    joined to cortex_cycles to filter by matter. Returns 0 on DB error
    (cost-warn is best-effort observability — never block the run).
    """
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        return 0
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM cortex_phase_outputs cpo "
            "JOIN cortex_cycles cc ON cc.cycle_id = cpo.cycle_id "
            "WHERE cc.matter_slug = %s "
            "AND cpo.artifact_type = 'specialist_invocation' "
            "AND cpo.created_at > NOW() - INTERVAL '24 hour'",
            (matter_slug,),
        )
        row = cur.fetchone()
        cur.close()
        return int((row or [0])[0])
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error("specialist_calls_today failed matter=%s: %s", matter_slug, e)
        return 0
    finally:
        store._put_conn(conn)


def _snapshot_cycle(
    *,
    matter_slug: str,
    triggered_by: str,
    since_ts: Optional[datetime.datetime] = None,
) -> Optional[dict]:
    """Return one cycle row for (matter_slug, triggered_by) + phase-output count.

    Used by ``stream_cycle_events`` to detect phase transitions and new
    phase-output rows to emit as SSE events. Returns None on DB error or
    when no cycle row exists yet (Phase 1 hasn't committed).

    F-1 FIX (PR #88 AI Head B re-review): when ``since_ts`` is provided,
    filter to cycles started at or after that wall-clock anchor and pick
    the OLDEST such cycle (``ORDER BY started_at ASC LIMIT 1``). This
    disambiguates concurrent same-trigger taps within the rate-limit
    window — each ``stream_cycle_events`` consumer captures its own
    ``sse_anchor`` BEFORE spawning the cycle task, so the oldest cycle
    started after that anchor is its own cycle (not a sibling Director
    tap that overlapped). When ``since_ts`` is None, backward-compat
    behavior is preserved (latest by DESC) — used by tests and any
    future caller that doesn't need disambiguation.

    Note: ``current_phase='act'`` is CHECK-allowed in the DB schema but
    no production code path writes it (Phase 5 jumps directly from
    'propose'/'reason' to 'archive'). SSE never observes 'act' as a
    phase value.
    """
    store = _get_store()
    conn = store._get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        if since_ts is not None:
            cur.execute(
                "SELECT cycle_id, status, current_phase "
                "FROM cortex_cycles "
                "WHERE matter_slug = %s AND triggered_by = %s "
                "AND started_at >= %s "
                "ORDER BY started_at ASC LIMIT 1",
                (matter_slug, triggered_by, since_ts),
            )
        else:
            cur.execute(
                "SELECT cycle_id, status, current_phase "
                "FROM cortex_cycles "
                "WHERE matter_slug = %s AND triggered_by = %s "
                "ORDER BY started_at DESC LIMIT 1",
                (matter_slug, triggered_by),
            )
        row = cur.fetchone()
        if not row:
            cur.close()
            return None
        cycle_id, status, current_phase = row
        cur.execute(
            "SELECT COUNT(*) FROM cortex_phase_outputs WHERE cycle_id = %s",
            (cycle_id,),
        )
        po_row = cur.fetchone()
        cur.close()
        po_count = int((po_row or [0])[0])
        return {
            "cycle_id": str(cycle_id),
            "status": status,
            "current_phase": current_phase,
            "phase_outputs_count": po_count,
        }
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.error(
            "_snapshot_cycle failed matter=%s triggered_by=%s: %s",
            matter_slug, triggered_by, e,
        )
        return None
    finally:
        store._put_conn(conn)


async def stream_cycle_events(
    *,
    matter_slug: str,
    director_question: str,
    triggered_by: str = "director_manual",
) -> AsyncIterator[str]:
    """Spawn ``maybe_run_cycle`` in the background and yield SSE-formatted phase events.

    Yields strings already wrapped in ``data: {...}\\n\\n`` format so the
    consumer (FastAPI ``StreamingResponse``) can pass them through verbatim.

    Disconnect-doesn't-kill-cycle: the cycle ``Task`` is created here and
    awaited via the polling loop. If the consumer disconnects, FastAPI
    closes the generator but the background ``Task`` keeps running on
    Python's event loop until ``maybe_run_cycle`` returns. The cycle's own
    5-min ``asyncio.wait_for`` cap inside ``maybe_run_cycle`` bounds total
    work. ``director_question`` is never logged at INFO level (sensitive
    matter content).
    """
    from orchestrator.cortex_runner import maybe_run_cycle

    # F-1 FIX (PR #88 AI Head B re-review): capture wall-clock anchor BEFORE
    # spawning the cycle task. The 2s slack absorbs the small interval
    # between asyncio.create_task scheduling and Phase 1's INSERT INTO
    # cortex_cycles commit (Phase 1 is local logic + one INSERT, well
    # under 2s in practice). Polling then asks _snapshot_cycle for the
    # OLDEST cycle started at-or-after this anchor — that is THIS
    # consumer's cycle, never a concurrent sibling tap on the same
    # (matter_slug, triggered_by).
    sse_anchor = (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(seconds=SSE_ANCHOR_SLACK_SECONDS)
    )

    yield _sse({
        "type": "started",
        "matter_slug": matter_slug,
        "triggered_by": triggered_by,
        "ts": time.time(),
    })

    cycle_task: asyncio.Task = asyncio.create_task(
        maybe_run_cycle(
            matter_slug=matter_slug,
            triggered_by=triggered_by,
            director_question=director_question,
        )
    )

    last_phase: Optional[str] = None
    last_po_count = 0
    while not cycle_task.done():
        try:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            # Consumer disconnected — leave the cycle task running.
            raise

        snap = _snapshot_cycle(
            matter_slug=matter_slug,
            triggered_by=triggered_by,
            since_ts=sse_anchor,
        )
        if not snap:
            continue

        cur_phase = snap.get("current_phase")
        if cur_phase != last_phase:
            last_phase = cur_phase
            yield _sse({
                "type": "phase_changed",
                "phase": cur_phase,
                "cycle_id": snap.get("cycle_id"),
                "ts": time.time(),
            })

        po_count = int(snap.get("phase_outputs_count") or 0)
        if po_count > last_po_count:
            last_po_count = po_count
            yield _sse({
                "type": "phase_output",
                "count": po_count,
                "cycle_id": snap.get("cycle_id"),
                "ts": time.time(),
            })

    try:
        cycle = await cycle_task
    except asyncio.TimeoutError:
        yield _sse({
            "type": "terminal",
            "status": "timeout",
            "ts": time.time(),
        })
        return
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(
            "cortex_run stream cycle failed matter=%s: %s",
            matter_slug, e,
        )
        yield _sse({
            "type": "terminal",
            "status": "failed",
            "error": str(e)[:200],
            "ts": time.time(),
        })
        return

    yield _sse({
        "type": "terminal",
        "status": getattr(cycle, "status", "unknown"),
        "cycle_id": str(getattr(cycle, "cycle_id", "") or ""),
        "current_phase": getattr(cycle, "current_phase", None),
        "cost_dollars": float(getattr(cycle, "cost_dollars", 0.0) or 0.0),
        "cost_tokens": int(getattr(cycle, "cost_tokens", 0) or 0),
        "aborted_reason": getattr(cycle, "aborted_reason", None),
        "ts": time.time(),
    })
