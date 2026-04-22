"""KBL-B pipeline tick orchestrator + per-signal processors.

Two orchestrator variants share the same transaction-boundary contract:

``_process_signal`` (Steps 1-7)
    Full 7-step pipeline — terminal state ``completed``. Used by tests
    and any future same-host run (dev Mac, CI, Step 7 on a non-Render
    host). Not called from Render's tick.

``_process_signal_remote`` (Steps 1-6 only)
    Step 7 runs on Mac Mini via ``kbl.poller`` (direct import of
    ``step7_commit.commit``). On Render we stop at ``awaiting_commit``
    so we never try to open a flock / push without a vault clone
    (CHANDA Inv 9: Mac Mini is single writer to ``~/baker-vault``).
    Terminal states this function can leave the signal in:

        ``routed_inbox``     — Step 1 low-score early return
        ``paused_cost_cap``  — Step 5 cost gate denied
        ``finalize_failed``  — Step 6 3× Opus retries exhausted
        ``awaiting_commit``  — success; Mac Mini poller picks up

    Do not call ``_process_signal_remote`` from Mac Mini — the poller
    already owns Step 7 there, and running this variant would race the
    poller's claim on ``awaiting_commit``.

Transaction boundary contract (Task K YELLOW remediation, 2026-04-19)
---------------------------------------------------------------------

Each step function in ``kbl.steps`` (``triage.triage``,
``resolve.resolve``, ``extract.extract``, ``classify.classify``,
``step5_opus.synthesize``, ``step6_finalize.finalize``,
``step7_commit.commit``) is **caller-owns-commit**: the step performs
all its DB writes (state UPDATE + cost_ledger INSERT + any column
writes) but does NOT call ``conn.commit()``. The caller
(``_process_signal`` / ``_process_signal_remote``) is responsible for:

    1. BEGIN (implicit via psycopg2 default — autocommit=False).
    2. Call the step function.
    3. On successful return: ``conn.commit()`` — state + ledger + column
       writes all land atomically.
    4. On raised exception: ``conn.rollback()`` — no partial writes.
    5. Step functions MAY call ``conn.commit()`` internally ONLY to
       preserve a write across a subsequent raise (terminal-state flips
       in Step 1/4/5/6/7 exception handlers).

This closes the Inv 2 integration-layer gap surfaced in Task K burn-in
audit at ``e300a49``.

Render wiring (APScheduler, 2026-04-19)
---------------------------------------

``main()`` is the scheduler entrypoint. It is env-gated on
``KBL_FLAGS_PIPELINE_ENABLED`` — default ``"false"``, so merging this
module is a no-op until the Director explicitly flips the flag. When
disabled, ``main()`` returns 0 immediately and does NOT claim a signal.
When enabled it runs the two circuit-breaker short-circuits, claims one
pending signal, and hands off to ``_process_signal_remote``. APScheduler
registers the wrapper at 120 s with ``max_instances=1`` — see
``triggers/embedded_scheduler.py``.

Heartbeat ownership (R1.S7): this module does NOT write
``mac_mini_heartbeat``. The dedicated ``kbl.heartbeat`` LaunchAgent is
the sole owner of that key.
"""

from __future__ import annotations

import logging as _stdlib_logging
import os
import sys
from typing import Any

from kbl.db import get_conn
from kbl.logging import check_alert_dedupe, emit_log
from kbl.runtime_state import get_state

# B2.N1: anthropic-circuit-open WARN routes through kbl_alert_dedupe with
# a 15-min bucket so a multi-hour outage doesn't spam kbl_log at 120s cadence.
_CIRCUIT_WARN_BUCKET_MIN = 15

_local = _stdlib_logging.getLogger("kbl.pipeline_tick")


def claim_one_signal(conn) -> int | None:
    """Claim the next pending signal. Returns signal_id or None."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM signal_queue
            WHERE status = 'pending'
            ORDER BY priority DESC, created_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        )
        row = cur.fetchone()
        if not row:
            return None
        signal_id = row[0]
        cur.execute(
            "UPDATE signal_queue SET status = 'processing', started_at = NOW() WHERE id = %s",
            (signal_id,),
        )
        conn.commit()
        return signal_id


def claim_one_opus_failed(conn) -> int | None:
    """Claim the next opus_failed row within retry budget. Returns
    signal_id or None.

    Complements ``claim_one_signal`` — the implementation of the R3
    reclaim contract documented in ``step6_finalize.finalize()`` docstring:

        "opus_failed. pipeline_tick re-queues into Step 5 for the R3 retry"

    Before this existed, every Step 6 validation failure produced a
    permanent orphan at ``status='opus_failed'`` — the design-intent
    reclaim ladder never fired and the operator had to run manual
    ``UPDATE`` statements to flip rows back into the queue.

    Budget guard: ``finalize_retry_count < _MAX_OPUS_REFLIPS`` (imported
    from Step 6). Step 6 already terminal-flips to ``finalize_failed``
    when the count hits the cap, so rows at count==cap never sit at
    ``opus_failed``; this check is defense-in-depth against the race
    where Step 6's terminal flip somehow missed.

    On claim: flips to ``awaiting_opus`` (Step 5's pre-state per
    ``step5_opus._STATE_RUNNING`` lineage). Step 5's internal R3 ladder
    produces a fresh draft which Step 6 re-validates. If Step 6 fails
    again, its existing ``_route_validation_failure`` path bumps
    ``finalize_retry_count`` and routes back to ``opus_failed`` (or
    ``finalize_failed`` on the last reflip).

    ``FOR UPDATE SKIP LOCKED`` keeps concurrent ticks safe. ALTER IF
    NOT EXISTS keeps the call idempotent across environments where
    Step 6 hasn't yet self-healed the column (matches Step 6's pattern
    in ``_fetch_signal_row`` and ``_increment_retry_count``).
    """
    from kbl.steps.step6_finalize import _MAX_OPUS_REFLIPS

    with conn.cursor() as cur:
        cur.execute(
            "ALTER TABLE signal_queue "
            "ADD COLUMN IF NOT EXISTS finalize_retry_count INT NOT NULL DEFAULT 0"
        )
        cur.execute(
            """
            SELECT id FROM signal_queue
            WHERE status = 'opus_failed'
              AND COALESCE(finalize_retry_count, 0) < %s
            ORDER BY priority DESC, created_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """,
            (_MAX_OPUS_REFLIPS,),
        )
        row = cur.fetchone()
        if not row:
            return None
        signal_id = row[0]
        cur.execute(
            "UPDATE signal_queue SET status = 'awaiting_opus' WHERE id = %s",
            (signal_id,),
        )
        conn.commit()
        return signal_id


def _process_signal(signal_id: int, conn: Any) -> None:
    """Run one signal through Steps 1-7 under the tx-boundary contract.

    Full 7-step orchestrator. Terminal state is ``completed`` (post
    vault commit + push). Intermediate status-gated early returns
    handle each step's ``*_failed`` / ``paused_cost_cap`` /
    ``routed_inbox`` exits.

    Contract:
        - Each step function is called with ``conn``. The step writes
          its state + column UPDATEs + any cost_ledger rows, then
          returns.
        - On successful return we ``conn.commit()`` — one commit per
          successful step. One bad step doesn't taint the prior step's
          writes.
        - On raised exception we ``conn.rollback()`` — the exception
          then propagates to the caller. The step's pre-raise internal
          commit (for terminal-state flips — Step 1/4/5/6/7) runs
          outside our rollback because the step already committed that
          fragment.

    Status-based dispatch: each step function is responsible for only
    claiming signals in its pre-state (``awaiting_*``). We call the
    appropriate step for the current signal status and let step-level
    guards handle the claim + run.
    """
    # Deferred imports so this module can be imported without loading
    # the full KBL-B stack (heartbeat test harness etc.).
    from kbl.steps import step1_triage, step2_resolve, step3_extract
    from kbl.steps import step4_classify, step5_opus, step6_finalize
    from kbl.steps import step7_commit

    # Step 1 — triage. Caller-owns-commit boundary.
    try:
        step1_triage.triage(signal_id, conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    # Re-check status: triage may have routed to terminal ``routed_inbox``
    # for low-score signals. If so, the pipeline is done for this signal.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM signal_queue WHERE id = %s", (signal_id,)
        )
        row = cur.fetchone()
    if row is None or row[0] != "awaiting_resolve":
        return

    try:
        step2_resolve.resolve(signal_id, conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    try:
        step3_extract.extract(signal_id, conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    try:
        step4_classify.classify(signal_id, conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    try:
        step5_opus.synthesize(signal_id, conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    # Step 5 may have parked the signal at ``paused_cost_cap`` (cost gate
    # denied) without raising. In that case synthesize() internally
    # committed the pause and returned — Step 6 must not run, since the
    # row's status is no longer ``awaiting_finalize``.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM signal_queue WHERE id = %s", (signal_id,)
        )
        row = cur.fetchone()
    if row is None or row[0] != "awaiting_finalize":
        return

    try:
        step6_finalize.finalize(signal_id, conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    # Step 6 may have parked the signal at ``finalize_failed`` (3 Opus
    # retries exhausted) before raising. If the status is no longer
    # ``awaiting_commit``, Step 7 must not run.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM signal_queue WHERE id = %s", (signal_id,)
        )
        row = cur.fetchone()
    if row is None or row[0] != "awaiting_commit":
        return

    try:
        step7_commit.commit(signal_id, conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    # Signal now sits at ``completed`` (or ``commit_failed`` if Step 7
    # flipped terminal internally). Pipeline is done.


def _process_signal_remote(signal_id: int, conn: Any) -> None:
    """Run one signal through Steps 1-6 under the tx-boundary contract.

    Steps 1-6 only. Step 7 runs on Mac Mini via ``kbl.poller``. Do not
    call from Mac Mini.

    Mirrors ``_process_signal`` exactly through Step 6, then stops —
    leaving the signal at ``awaiting_commit`` (success), or at one of
    the terminal states each step can produce (``routed_inbox``,
    ``paused_cost_cap``, ``finalize_failed``) via the usual
    status-gated early returns.

    Transaction contract is identical to ``_process_signal``: one
    ``conn.commit()`` per successful step, ``conn.rollback()`` on any
    raise, step-internal commits (terminal-state flips) survive.
    """
    # Deferred imports — match ``_process_signal``'s pattern. Step 7 is
    # deliberately NOT imported here: Render has no vault clone and no
    # flock target (CHANDA Inv 9).
    from kbl.steps import step1_triage, step2_resolve, step3_extract
    from kbl.steps import step4_classify, step5_opus, step6_finalize

    # Step 1 — triage.
    try:
        step1_triage.triage(signal_id, conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM signal_queue WHERE id = %s", (signal_id,)
        )
        row = cur.fetchone()
    if row is None or row[0] != "awaiting_resolve":
        return

    try:
        step2_resolve.resolve(signal_id, conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    try:
        step3_extract.extract(signal_id, conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    try:
        step4_classify.classify(signal_id, conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    try:
        step5_opus.synthesize(signal_id, conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM signal_queue WHERE id = %s", (signal_id,)
        )
        row = cur.fetchone()
    if row is None or row[0] != "awaiting_finalize":
        return

    try:
        step6_finalize.finalize(signal_id, conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    # Signal now sits at ``awaiting_commit`` (success — Mac Mini poller
    # picks up) or ``finalize_failed`` (Step 6 internal terminal flip).
    # Either way we stop here; Render never touches Step 7.


def _process_signal_reclaim_remote(signal_id: int, conn: Any) -> None:
    """Run Steps 5-6 only on an opus_failed reclaim. No Steps 1-4.

    Companion to ``_process_signal_remote``. The reclaim path is narrow
    by design: ``primary_matter``, ``triage_score``, and the prior
    ``opus_draft_markdown`` from the first attempt are all still valid
    — Step 5 overwrites ``opus_draft_markdown`` unconditionally on its
    happy path (and on stub routes), so re-running it produces a fresh
    draft for Step 6 to re-validate. Running Step 1 would waste an LLM
    call AND risk a ``primary_matter`` shift that the retry ladder's
    ``finalize_retry_count`` accounting can't model.

    Transaction contract mirrors ``_process_signal_remote``: one
    ``conn.commit()`` per successful step, ``conn.rollback()`` on raise,
    step-internal terminal-state commits (Step 5's ``opus_failed`` /
    ``paused_cost_cap`` flips, Step 6's ``finalize_failed`` flip) survive
    the outer rollback.

    Not called from Mac Mini. Not called directly by ``_process_signal``
    / ``_process_signal_remote`` — ``main()`` dispatches to this only
    after ``claim_one_opus_failed`` returns a row.
    """
    from kbl.steps import step5_opus, step6_finalize

    try:
        step5_opus.synthesize(signal_id, conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    # Step 5 may have parked the signal at ``paused_cost_cap`` or
    # ``opus_failed`` (R3 exhausted again on this reclaim). If the row
    # is no longer ``awaiting_finalize``, Step 6 must not run.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM signal_queue WHERE id = %s", (signal_id,)
        )
        row = cur.fetchone()
    if row is None or row[0] != "awaiting_finalize":
        return

    try:
        step6_finalize.finalize(signal_id, conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    # Signal now sits at ``awaiting_commit`` (success — Mac Mini poller
    # picks up) or ``finalize_failed`` (Step 6 terminal flip — budget
    # exhausted) or ``opus_failed`` (Step 6 re-routed under budget).


def main() -> int:
    """Render scheduler entrypoint. Returns 0 on normal exit (including
    disabled / queue-empty / circuit-open). Non-zero reserved for
    unexpected crashes. Safe to call repeatedly at the configured
    interval — ``claim_one_signal`` uses ``FOR UPDATE SKIP LOCKED`` so
    concurrent ticks (APScheduler + on-demand) cannot double-claim.
    """
    # Opt-in gate: default closed. Director flips
    # KBL_FLAGS_PIPELINE_ENABLED=true on Render to start shadow mode.
    # Any value other than the literal "true" (case-insensitive) keeps
    # the pipeline disabled — no surprises from typos.
    if os.environ.get("KBL_FLAGS_PIPELINE_ENABLED", "false").lower() != "true":
        _local.info("pipeline disabled via KBL_FLAGS_PIPELINE_ENABLED; skipping tick")
        return 0

    # Circuit-breaker short-circuits (INFO-level messages stay local per
    # R1.S2 — only WARN+ hits PG via emit_log).
    if get_state("anthropic_circuit_open") == "true":
        circuit_msg = "Anthropic circuit open, skipping API calls this tick"
        _local.warning("[pipeline_tick] %s", circuit_msg)
        if check_alert_dedupe("pipeline_tick", circuit_msg, _CIRCUIT_WARN_BUCKET_MIN):
            emit_log("WARN", "pipeline_tick", None, circuit_msg)
        return 0

    if get_state("cost_circuit_open") == "true":
        _local.info("Cost cap reached today, skipping until UTC midnight")
        return 0

    with get_conn() as conn:
        try:
            signal_id = claim_one_signal(conn)
        except Exception:
            conn.rollback()
            raise

        if signal_id is not None:
            try:
                _process_signal_remote(signal_id, conn)
            except Exception as e:
                # Step functions own their own rollback/terminal-flip
                # semantics (caller-owns-commit contract). Anything that
                # escapes _process_signal_remote is genuinely unexpected —
                # log at ERROR and let the exception propagate so
                # APScheduler sees the failure and its listener logs it.
                emit_log(
                    "ERROR",
                    "pipeline_tick",
                    signal_id,
                    f"unexpected exception in _process_signal_remote: {e}",
                )
                raise
            return 0

        # Primary queue empty — try the opus_failed reclaim path. This
        # closes the R3-reclaim loop documented in Step 6's finalize()
        # docstring: before this existed, every Step 6 validation failure
        # produced a permanent orphan at ``opus_failed`` and required a
        # manual operator UPDATE to flip back into the queue.
        try:
            reclaim_id = claim_one_opus_failed(conn)
        except Exception:
            conn.rollback()
            raise

        if reclaim_id is None:
            return 0  # both queues empty — normal exit

        try:
            _process_signal_reclaim_remote(reclaim_id, conn)
        except Exception as e:
            emit_log(
                "ERROR",
                "pipeline_tick",
                reclaim_id,
                f"unexpected exception in _process_signal_reclaim_remote: {e}",
            )
            raise

    return 0


if __name__ == "__main__":
    sys.exit(main())
