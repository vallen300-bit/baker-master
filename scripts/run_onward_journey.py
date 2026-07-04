#!/usr/bin/env python3
"""Operator entry for the BB Airside onward journey — blocks 2-4
(BAKER_OS_V2_STEP2_ONWARD_JOURNEY_BLOCKS_2_4_1).

One sweep of the onward-journey state machine: post WORK_PACKETs to the desk (T1), read
CLAIM/STATUS/LANDED desk replies (T1/T2/T3), write receipts for landed rows (T3), run the
claim-TTL exception lane (T4), then print the reconciliation readout. Gated: does nothing
unless AIRPORT_BOARDING_FLOW_ENABLED=true. Honors BAKER_CLICKUP_READONLY=true for a
non-mutating dry-run (intended ClickUp writes logged, no ClickUp calls; bus posts also
skipped for receipt proof — reader still reads).

Usage (lead, after GO + flag flip):
    DATABASE_URL=... AIRPORT_BOARDING_FLOW_ENABLED=true \\
        python3 scripts/run_onward_journey.py
Dry-run first (recommended — non-mutating end-to-end):
    DATABASE_URL=... AIRPORT_BOARDING_FLOW_ENABLED=true BAKER_CLICKUP_READONLY=true \\
        python3 scripts/run_onward_journey.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("run_onward_journey")


def main() -> int:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        logger.error("DATABASE_URL not set — refusing to run")
        return 2

    from orchestrator import airport_boarding_flow as flow

    if not flow.boarding_enabled():
        logger.warning("AIRPORT_BOARDING_FLOW_ENABLED is not true — no-op. Set the flag "
                       "to run the onward-journey sweep.")
        return 0

    import psycopg2

    conn = psycopg2.connect(dsn)
    try:
        report = flow.run_onward_journey_sweep(conn)
        print("=== ONWARD JOURNEY SWEEP REPORT (blocks 2-4) ===")
        print(json.dumps(report, indent=2, default=str))

        rec = report.get("reconciliation", {})
        if rec.get("flight_column_leak_count"):
            logger.error("D-23 VIOLATION: %d lounge row(s) carry a non-NULL flight column",
                         rec["flight_column_leak_count"])
            return 1
        if rec.get("undefined_states"):
            logger.error("RECONCILIATION: rows in undefined state(s): %s",
                         rec["undefined_states"])
            return 1
        logger.info("reconciliation clean: 0 flight leaks, 0 undefined states, "
                    "%d non-terminal row(s) accounted", rec.get("non_terminal_count", 0))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
