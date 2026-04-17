"""KBL-A pipeline tick orchestrator — STUB.

Claims one pending signal via FOR UPDATE SKIP LOCKED, flips it to
'classified-deferred', exits. The 8-step processing body (Layer 0 →
Triage → Resolve → Extract → Classify → Opus → Sonnet → Commit) is
KBL-B's job and replaces this stub wholesale.

Heartbeat ownership (R1.S7): this module does NOT write
`mac_mini_heartbeat`. The dedicated kbl.heartbeat LaunchAgent is the
sole owner of that key.
"""

from __future__ import annotations

import logging as _stdlib_logging
import sys

from kbl.db import get_conn
from kbl.logging import emit_log
from kbl.runtime_state import get_state

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


def main() -> int:
    # Circuit-breaker short-circuits (INFO-level messages stay local per
    # R1.S2 — only WARN+ hits PG via emit_log).
    if get_state("anthropic_circuit_open") == "true":
        emit_log(
            "WARN",
            "pipeline_tick",
            None,
            "Anthropic circuit open, skipping API calls this tick",
        )
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

        if signal_id is None:
            return 0  # queue empty — normal exit

        # KBL-A stub: log the claim + mark classified-deferred. KBL-B
        # replaces the body below with real pipeline logic.
        emit_log(
            "WARN",
            "pipeline_tick",
            signal_id,
            "KBL-A stub: signal claimed but no pipeline logic yet (awaiting KBL-B)",
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE signal_queue SET status = 'classified-deferred', "
                    "processed_at = NOW() WHERE id = %s",
                    (signal_id,),
                )
                conn.commit()
        except Exception:
            conn.rollback()
            raise

    return 0


if __name__ == "__main__":
    sys.exit(main())
