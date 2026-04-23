"""CHANDA invariant #2 — ledger write atomic with Director action.

Provides a DB transaction context manager that binds a Director-action
primary write and the baker_actions ledger row to ONE transaction.
Either both commit, or both roll back. No silent phantom writes.

Usage:

    from invariant_checks.ledger_atomic import atomic_director_action

    conn = store._get_conn()
    try:
        with atomic_director_action(
            conn,
            action_type="cortex:deadline:ratified",
            payload={"canonical_id": 42, "summary": "Capital call due 2026-05-01"},
            trigger_source="ao_signal_detector",
        ) as cur:
            cur.execute(
                "INSERT INTO cortex_events (...) VALUES (...) RETURNING id",
                (...),
            )
            event_id = cur.fetchone()[0]
        # At this point: either BOTH rows committed, or NEITHER.
    finally:
        store._put_conn(conn)

Semantics:

- Caller provides conn. Context manager yields a cursor.
- Primary write is executed INSIDE the `with` block by the caller.
- On successful exit: context manager INSERTs baker_actions row on the
  same cursor, then commits both writes in one transaction.
- On any exception: context manager calls conn.rollback() and re-raises.
- Caller MUST NOT call conn.commit() or conn.rollback() inside the block.

Design constraints:

- Uses the caller's existing conn — no new pool checkout.
- Preserves and restores conn.autocommit on exit.
- No dependency on StoreBack to avoid import cycles (conn is primitive).
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from typing import Any, Iterator, Optional

logger = logging.getLogger("baker.invariant_checks.ledger_atomic")


@contextmanager
def atomic_director_action(
    conn,
    action_type: str,
    payload: Optional[dict] = None,
    trigger_source: Optional[str] = None,
    target_task_id: Optional[str] = None,
    target_space_id: Optional[str] = None,
) -> Iterator[Any]:
    """Bind primary write + baker_actions ledger row into ONE txn.

    Args:
        conn: psycopg2 connection. Caller owns checkout/checkin.
        action_type: baker_actions.action_type (NOT NULL, <=255 chars).
        payload: JSONB payload for the ledger row. Optional.
        trigger_source: baker_actions.trigger_source (agent id / source id).
        target_task_id: baker_actions.target_task_id (ClickUp task ref etc.).
        target_space_id: baker_actions.target_space_id (ClickUp space ref etc.).

    Yields:
        psycopg2 cursor bound to the conn's active transaction. Caller
        executes the primary write on this cursor.

    Raises:
        RuntimeError: if conn is None.
        Any exception raised by caller's primary write, or by the
        ledger INSERT itself. On any exception: full rollback of BOTH
        writes before re-raising.
    """
    if conn is None:
        raise RuntimeError("ledger_atomic: conn is None")

    prior_autocommit = conn.autocommit
    conn.autocommit = False

    cur = conn.cursor()
    try:
        yield cur
        # Primary write has been executed by caller on `cur`. Now emit
        # the ledger row on the SAME cursor (== same txn) and commit
        # both in one shot.
        cur.execute(
            """
            INSERT INTO baker_actions
                (action_type, target_task_id, target_space_id, payload,
                 trigger_source, success, error_message)
            VALUES (%s, %s, %s, %s::jsonb, %s, TRUE, NULL)
            RETURNING id
            """,
            (
                action_type,
                target_task_id,
                target_space_id,
                json.dumps(payload) if payload else None,
                trigger_source,
            ),
        )
        ledger_id = cur.fetchone()[0]
        conn.commit()
        logger.info(
            "ledger_atomic: %s committed atomically (baker_actions #%d)",
            action_type, ledger_id,
        )
    except Exception:
        try:
            conn.rollback()
        except Exception as rb_err:
            logger.error(
                "ledger_atomic: rollback failed after primary/ledger error: %s",
                rb_err,
            )
        logger.error(
            "ledger_atomic: %s ROLLED BACK (both primary and ledger discarded)",
            action_type,
        )
        raise
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.autocommit = prior_autocommit
