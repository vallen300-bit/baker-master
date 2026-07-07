#!/usr/bin/env python3
"""C3 gate R4 — Nudges stop on landing (D-39b/c).

Run protocol (matrix): land a ticket (proof-typed return), observe the nudge
ladder. PASS: zero nudges after the landed-proof timestamp; the ladder history
shows the stop.

Evidence: nudge log window pre/post landing (baker_actions
airport_boarding.nudged rows + correlation.nudge_count), before and after the
LANDED transition.

Controlled-run shape: seed a BOARDING_POSTED journey whose claim TTL has already
elapsed, run the nudge ladder once (-> one nudge), transition it to LANDED, then
run the ladder again (-> the LANDED row is excluded, zero further nudges).
"""
from __future__ import annotations

import json
import os

import c3_lib as c3

DRY = """
Row R4 — Nudges stop on landing (D-39b/c).

  seed   airport_outbound_events row  ticket_id=airport-lounge:c3-gate-r4
         event_state=BOARDING_POSTED  desk_owner=<boarding slug>
         updated_at = 100h ago  (past the 48h claim TTL)  correlation nudge_count=0
  call   run_boarding_ttl_nudge(conn)   (bus + ClickUp stubbed)
         EXPECT one nudge: correlation.nudge_count -> 1, baker_actions
                airport_boarding.nudged appears
  land   transition the row BOARDING_POSTED -> LANDED (desk proof-typed return)
  call   run_boarding_ttl_nudge(conn) again
         EXPECT zero further nudges (LANDED rows are excluded from the ladder)

Evidence emitted: {nudges_before_landing, nudges_after_landing (must be 0),
nudge_count, ladder_actions}. PASS = >=1 nudge before landing AND 0 after.
"""


def _seed_boarding_posted(conn) -> str:
    from orchestrator import airport_boarding_flow as flow

    ev_id = f"airport-lounge:{c3.PREFIX}r4"
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO airport_outbound_events "
            "(ticket_id, message_id, event_state, desk_owner, correlation, updated_at) "
            "VALUES (%s, %s, %s, %s, %s::jsonb, NOW() - INTERVAL '100 hours') "
            "ON CONFLICT (ticket_id) DO UPDATE SET event_state = EXCLUDED.event_state, "
            "correlation = EXCLUDED.correlation, updated_at = NOW() - INTERVAL '100 hours'",
            (ev_id, f"{c3.PREFIX}r4", flow.BOARDING_POSTED, flow._DESK,
             json.dumps({"nudge_count": 0})),
        )
    conn.commit()
    return ev_id


def _land(conn, ev_id: str) -> None:
    from orchestrator import airport_boarding_flow as flow

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE airport_outbound_events SET event_state = %s, "
            "correlation = correlation || %s::jsonb, updated_at = NOW() "
            "WHERE ticket_id = %s",
            (flow.LANDED, json.dumps({"landed_proof_at": c3.now().isoformat()}), ev_id),
        )
    conn.commit()


def run(conn) -> dict:
    from orchestrator import airport_boarding_flow as flow

    os.environ["AIRPORT_BOARDING_FLOW_ENABLED"] = "true"
    os.environ["BAKER_CLICKUP_READONLY"] = os.environ.get("BAKER_CLICKUP_READONLY", "false")
    c3.cleanup(conn)
    ev_id = _seed_boarding_posted(conn)

    flow.run_boarding_ttl_nudge(conn)
    nudges_before = c3.nudge_actions(conn, ev_id)
    ev_mid = c3.outbound_evidence(conn, ev_id)

    _land(conn, ev_id)
    flow.run_boarding_ttl_nudge(conn)
    nudges_after = c3.nudge_actions(conn, ev_id)

    stopped = len(nudges_before) >= 1 and len(nudges_after) == len(nudges_before)
    return {"pass": stopped,
            "evidence": {"nudges_before_landing": nudges_before,
                         "nudges_after_landing": nudges_after,
                         "nudge_count_mid": (ev_mid or {}).get("correlation"),
                         "delta_after_landing": len(nudges_after) - len(nudges_before)},
            "notes": "" if stopped
            else f"before={len(nudges_before)} after={len(nudges_after)} "
                 "(expected >=1 before, no growth after landing)"}


if __name__ == "__main__":
    c3.main_scaffold("R4", DRY, run)
