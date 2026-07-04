#!/usr/bin/env python3
"""Operator entry for the BB Airside Lounge backlog drain
(BAKER_OS_V2_STEP2_LOUNGE_WRITER_DRAIN_1, T3).

Runs the lounge drain in repeated cap-bounded cycles until no candidate remains,
then prints the reconciliation readout (0-orphan + flight-NULL proof) as the T3.3
run report. Gated: does nothing unless AIRPORT_LOUNGE_WRITER_ENABLED=true. Honors
BAKER_CLICKUP_READONLY=true for a dry-run (intended writes logged, no ClickUp calls).

Usage (lead, after GO):
    DATABASE_URL=... AIRPORT_LOUNGE_WRITER_ENABLED=true \\
        python3 scripts/run_lounge_drain.py [desk-slug]
Dry-run first (recommended):
    DATABASE_URL=... AIRPORT_LOUNGE_WRITER_ENABLED=true BAKER_CLICKUP_READONLY=true \\
        python3 scripts/run_lounge_drain.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_lounge_drain")


def main() -> int:
    desk = sys.argv[1] if len(sys.argv) > 1 else "baden-baden-desk"

    dsn = os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        logger.error("DATABASE_URL not set — refusing to run")
        return 2

    from orchestrator import airport_lounge_writer as lounge

    if not lounge.lounge_enabled():
        logger.warning("AIRPORT_LOUNGE_WRITER_ENABLED is not true — no-op. Set the flag "
                       "to run the drain.")
        return 0

    import psycopg2

    conn = psycopg2.connect(dsn)
    try:
        cycles = []
        # Cap-bounded passes; stop when a cycle drains nothing new (all remaining are
        # deferred-by-cap-only would keep progressing, so guard on forward progress).
        max_passes = 50
        for i in range(max_passes):
            res = lounge.run_lounge_drain(conn, desk_slug=desk)
            handled = (res["wrote"] + res["parked"] + res["blocked"] + res["dup"]
                       + res["error_retry"] + res["skipped_idempotent"])
            cycles.append({"cycle": i + 1, "wrote": res["wrote"], "parked": res["parked"],
                           "blocked": res["blocked"], "dup": res["dup"],
                           "error_retry": res["error_retry"],
                           "skipped_idempotent": res["skipped_idempotent"],
                           "deferred_cap": res["deferred_cap"],
                           "writes_this_cycle": res.get("writes_this_cycle", 0)})
            logger.info("cycle %d: %s", i + 1, cycles[-1])
            # Done when nothing is left waiting on the cap and nothing new was handled.
            if res["deferred_cap"] == 0:
                break

        rec = lounge.reconcile(conn, desk_slug=desk)
        report = {"desk": desk, "dry_run": lounge._readonly(), "cycles": cycles,
                  "reconciliation": rec}
        print("=== LOUNGE DRAIN RUN REPORT (T3.3) ===")
        print(json.dumps(report, indent=2, default=str))
        if rec["orphan_count"] != 0:
            logger.warning("RECONCILIATION: %d orphan(s) remain — not fully drained",
                           rec["orphan_count"])
            return 1
        if rec["flight_column_leak_count"] != 0:
            logger.error("D-23 VIOLATION: %d lounge row(s) carry a non-NULL flight column",
                         rec["flight_column_leak_count"])
            return 1
        logger.info("reconciliation clean: 0 orphans, 0 flight-column leaks")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
