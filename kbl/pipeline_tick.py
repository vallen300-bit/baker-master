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


# Staleness guard for the awaiting_* crash-recovery reclaim paths.
# Interval is expressed as a bare SQL literal because psycopg2 does not
# parametrize INTERVAL literals; the value is module-constant so there is
# no injection surface. Value rationale: Step 5's Opus call is the slowest
# step at ~60s; with the R3 retry ladder a single Step 5 run can span up
# to ~180s (3 × 60s). APScheduler's `max_instances=1` already prevents
# overlapping ticks; 15 minutes is a safe margin against any stuck/hung
# primary tick that hasn't yet crashed + been observed. Short enough that
# operator lag is bounded at one sub-hour window, long enough that no
# legitimate mid-flight row ever gets double-claimed.
_AWAITING_ORPHAN_STALE_INTERVAL = "15 minutes"


# Staleness guard for the ``*_running`` crash-recovery reset path. Uses
# the same 15-minute interval rationale as ``_AWAITING_ORPHAN_STALE_INTERVAL``:
# the slowest legitimately-running step is Step 5's Opus R3 ladder at
# ~180s worst case; 15 min is ~5× safety margin. A row sitting at
# ``*_running`` for more than 15 min must have had its worker crash
# mid-step — the scheduler's ``max_instances=1`` prevents overlap, so
# no legitimate tick is still holding the row.
_RUNNING_ORPHAN_STALE_INTERVAL = "15 minutes"

# One SQL statement flips all three ``*_running`` orphan classes back to
# their prior ``awaiting_*`` state in a single pass. PR #39's claim chain
# then picks them up organically on the next tick (or later in the same
# tick if the reset commits before the claim chain runs — see
# ``main()``). Interval is a bare SQL literal; it's a module constant
# with no injection surface. RETURNING clause is present so the caller
# can log affected rows if needed; we rely on ``cur.rowcount`` for the
# count.
_RUNNING_RESET_SQL = f"""
UPDATE signal_queue
   SET status = CASE status
     WHEN 'classify_running' THEN 'awaiting_classify'
     WHEN 'opus_running'     THEN 'awaiting_opus'
     WHEN 'finalize_running' THEN 'awaiting_finalize'
   END
 WHERE status IN ('classify_running', 'opus_running', 'finalize_running')
   AND started_at < NOW() - INTERVAL '{_RUNNING_ORPHAN_STALE_INTERVAL}'
RETURNING id, status
"""


def reset_stale_running_orphans(conn) -> int:
    """Flip stale ``*_running`` rows back to the corresponding
    ``awaiting_*`` state. Returns the number of rows reset.

    Crash-recovery companion to PR #39's claim chain. Where PR #39 handles
    crashes BETWEEN steps (row at ``awaiting_*``), this function handles
    crashes DURING a step (row at ``*_running``). The shape deliberately
    differs from PR #39: instead of per-state claim + dispatch, one SQL
    statement flips all three classes at once, and the reclaimed rows are
    picked up by PR #39's existing ``claim_one_awaiting_*`` chain on the
    same or next tick — no new dispatchers needed.

    Mapping:
        classify_running  → awaiting_classify
        opus_running      → awaiting_opus
        finalize_running  → awaiting_finalize

    Staleness guard: ``started_at < NOW() - INTERVAL '15 minutes'`` — see
    ``_RUNNING_ORPHAN_STALE_INTERVAL`` for rationale. Rows legitimately
    mid-flight inside another tick are filtered out.

    Commit semantics: one commit on success. Caller (``main()``) invokes
    this BEFORE the claim chain so the reset is durable regardless of
    what happens later in the tick — an orphaned row that was just
    reset to ``awaiting_opus`` can be claimed by the same tick's
    ``claim_one_awaiting_opus`` call because the reset has already
    committed.
    """
    with conn.cursor() as cur:
        cur.execute(_RUNNING_RESET_SQL)
        n = cur.rowcount
    conn.commit()
    return n


def claim_one_awaiting_classify(conn) -> int | None:
    """Claim the next ``awaiting_classify`` orphan. Returns signal_id or None.

    Crash-recovery reclaim for Step 3's ``_STATE_NEXT``. A row lands at
    ``awaiting_classify`` when Step 3 successfully committed its extraction
    result but the tick crashed (or Render scaled / restarted) before
    Step 4's ``classify`` ran. Before this function existed, such rows sat
    permanently orphaned — only ``claim_one_signal`` picked anything up,
    and it only considers ``status='pending'``.

    Staleness guard: ``started_at < NOW() - INTERVAL '15 minutes'`` — see
    ``_AWAITING_ORPHAN_STALE_INTERVAL`` for rationale. Prevents claiming a
    row that is legitimately mid-flight inside the primary tick.

    On claim: flips status to ``classify_running`` (Step 4's
    ``_STATE_RUNNING`` lineage). Step 4 itself calls ``_mark_running`` again
    at the top of ``classify()`` — idempotent same-state UPDATE, harmless.

    No budget counter: unlike ``opus_failed`` (a retry state), this is a
    crash-recovery state. Normal pipeline advances forward within one tick;
    only crashes orphan rows here. Reclaim always attempts continuation.

    ``FOR UPDATE SKIP LOCKED`` keeps concurrent ticks safe.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id FROM signal_queue
            WHERE status = 'awaiting_classify'
              AND started_at < NOW() - INTERVAL '{_AWAITING_ORPHAN_STALE_INTERVAL}'
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
            "UPDATE signal_queue SET status = 'classify_running' WHERE id = %s",
            (signal_id,),
        )
        conn.commit()
        return signal_id


def claim_one_awaiting_opus(conn) -> int | None:
    """Claim the next ``awaiting_opus`` orphan. Returns signal_id or None.

    Crash-recovery reclaim for Step 4's ``_STATE_NEXT``. A row lands at
    ``awaiting_opus`` when Step 4 successfully committed its classification
    decision but the tick crashed before Step 5's ``synthesize`` ran.

    Distinct from ``claim_one_opus_failed``: that one handles the
    ``opus_failed`` retry state (produced by Step 6 validation failure)
    and flips ``opus_failed → awaiting_opus``. This one handles the
    ``awaiting_opus`` crash-orphan state (produced by Step 4 success +
    tick crash) and flips ``awaiting_opus → opus_running``. Both can
    coexist; they claim different rows.

    Staleness guard: ``started_at < NOW() - INTERVAL '15 minutes'`` — see
    ``_AWAITING_ORPHAN_STALE_INTERVAL``. Prevents the race where Step 4
    has just committed and Step 5 is about to start in the same tick.

    On claim: flips to ``opus_running`` (Step 5's ``_STATE_RUNNING``).
    Step 5's ``_mark_running`` is an idempotent same-state UPDATE.

    No budget counter — this is a crash-recovery state, not a retry.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id FROM signal_queue
            WHERE status = 'awaiting_opus'
              AND started_at < NOW() - INTERVAL '{_AWAITING_ORPHAN_STALE_INTERVAL}'
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
            "UPDATE signal_queue SET status = 'opus_running' WHERE id = %s",
            (signal_id,),
        )
        conn.commit()
        return signal_id


def claim_one_awaiting_finalize(conn) -> int | None:
    """Claim the next ``awaiting_finalize`` orphan. Returns signal_id or None.

    Crash-recovery reclaim for Step 5's ``_STATE_NEXT``. A row lands at
    ``awaiting_finalize`` when Step 5 successfully committed its Opus draft
    but the tick crashed before Step 6's ``finalize`` ran. This is the
    state AI Head has been manually recovering via ad-hoc UPDATE in
    multiple sessions — PR #38 pattern extended here closes the loop
    programmatically.

    Staleness guard: ``started_at < NOW() - INTERVAL '15 minutes'`` — see
    ``_AWAITING_ORPHAN_STALE_INTERVAL``.

    On claim: flips to ``finalize_running`` (Step 6's ``_STATE_RUNNING``).
    Step 6's ``_mark_running`` is an idempotent same-state UPDATE.

    No budget counter — this is a crash-recovery state, not a retry.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id FROM signal_queue
            WHERE status = 'awaiting_finalize'
              AND started_at < NOW() - INTERVAL '{_AWAITING_ORPHAN_STALE_INTERVAL}'
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
            "UPDATE signal_queue SET status = 'finalize_running' WHERE id = %s",
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


def _process_signal_classify_remote(signal_id: int, conn: Any) -> None:
    """Run Steps 4-5-6 on a reclaimed ``awaiting_classify`` orphan.

    Companion to ``_process_signal_remote``. Entered when
    ``claim_one_awaiting_classify`` has already flipped the row to
    ``classify_running`` — Step 4 therefore starts from a valid
    ``_STATE_RUNNING`` (and its own ``_mark_running`` is an idempotent
    same-state re-set).

    Steps 1-3 are NOT re-run: ``triage_score``, ``primary_matter``,
    ``related_matters``, and the Step 3 extraction columns are already
    populated on the row — running them again would waste LLM tokens and
    risk non-deterministic drift (Step 1 Flash classification is not
    byte-stable across runs).

    Step 7 is NOT run — Render never touches the vault (CHANDA Inv 9).

    Transaction contract mirrors ``_process_signal_remote``: one
    ``conn.commit()`` per successful step, ``conn.rollback()`` on raise,
    step-internal terminal-state commits (Step 4's ``classify_failed``
    flip, Step 5's ``opus_failed`` / ``paused_cost_cap`` flips, Step 6's
    ``finalize_failed`` flip) survive the outer rollback.
    """
    from kbl.steps import step4_classify, step5_opus, step6_finalize

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

    # Step 5 may have parked the signal at ``paused_cost_cap`` or
    # ``opus_failed``. If the row is no longer ``awaiting_finalize``,
    # Step 6 must not run.
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


def _process_signal_opus_remote(signal_id: int, conn: Any) -> None:
    """Run Steps 5-6 on a reclaimed ``awaiting_opus`` crash orphan.

    Shape mirrors ``_process_signal_reclaim_remote`` (Steps 5-6) but
    serves a DIFFERENT class of rows: crash orphans from Step 4's
    success commit, not Step 6 validation failures. The on-claim state
    is ``opus_running`` (via ``claim_one_awaiting_opus``), not
    ``awaiting_opus`` (which was the reclaim pre-flip in PR #38's path).

    Transaction contract: one ``conn.commit()`` per successful step,
    ``conn.rollback()`` on raise, step-internal terminal flips survive.

    No Step 7; no Steps 1-4 re-run.
    """
    from kbl.steps import step5_opus, step6_finalize

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


def _process_signal_finalize_remote(signal_id: int, conn: Any) -> None:
    """Run Step 6 only on a reclaimed ``awaiting_finalize`` crash orphan.

    The narrowest dispatch shape. Step 5 has already committed the
    ``opus_draft_markdown`` that Step 6 needs — re-running Step 5 would
    waste a fresh Opus call. Step 6 picks up its stored draft, validates,
    and either advances to ``awaiting_commit`` (Mac Mini poller picks up)
    or routes back to ``opus_failed`` / ``finalize_failed`` via its usual
    retry-ladder logic.

    Transaction contract: single ``conn.commit()`` on success,
    ``conn.rollback()`` on raise, step-internal terminal flips survive.

    On-claim state is ``finalize_running`` (via
    ``claim_one_awaiting_finalize``). Step 6's ``_mark_running`` is an
    idempotent same-state UPDATE.
    """
    from kbl.steps import step6_finalize

    try:
        step6_finalize.finalize(signal_id, conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


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
        # Crash-recovery reset: flip stale ``*_running`` rows back to
        # ``awaiting_*`` so PR #39's chain can pick them up. This commits
        # before the claim chain runs — a row reset on this pass becomes
        # eligible for ``claim_one_awaiting_*`` in the same tick.
        try:
            n_reset = reset_stale_running_orphans(conn)
        except Exception:
            conn.rollback()
            raise
        if n_reset:
            _local.info(
                "[pipeline_tick] reset %d stale *_running orphan(s) to awaiting_*",
                n_reset,
            )

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

        if reclaim_id is not None:
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

        # Crash-recovery reclaim chain: awaiting_classify / awaiting_opus /
        # awaiting_finalize. Ordered by how early in the pipeline the
        # crash happened — earlier-stage orphans get priority so the row
        # advances stage-by-stage across subsequent ticks rather than
        # leapfrogging. Each dispatch is gated by a 15-min staleness guard
        # on ``started_at`` inside the claim function, so no race with
        # the primary tick.
        try:
            classify_id = claim_one_awaiting_classify(conn)
        except Exception:
            conn.rollback()
            raise

        if classify_id is not None:
            try:
                _process_signal_classify_remote(classify_id, conn)
            except Exception as e:
                emit_log(
                    "ERROR",
                    "pipeline_tick",
                    classify_id,
                    f"unexpected exception in _process_signal_classify_remote: {e}",
                )
                raise
            return 0

        try:
            opus_id = claim_one_awaiting_opus(conn)
        except Exception:
            conn.rollback()
            raise

        if opus_id is not None:
            try:
                _process_signal_opus_remote(opus_id, conn)
            except Exception as e:
                emit_log(
                    "ERROR",
                    "pipeline_tick",
                    opus_id,
                    f"unexpected exception in _process_signal_opus_remote: {e}",
                )
                raise
            return 0

        try:
            finalize_id = claim_one_awaiting_finalize(conn)
        except Exception:
            conn.rollback()
            raise

        if finalize_id is None:
            return 0  # all queues empty — normal exit

        try:
            _process_signal_finalize_remote(finalize_id, conn)
        except Exception as e:
            emit_log(
                "ERROR",
                "pipeline_tick",
                finalize_id,
                f"unexpected exception in _process_signal_finalize_remote: {e}",
            )
            raise

    return 0


if __name__ == "__main__":
    sys.exit(main())
