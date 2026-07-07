#!/usr/bin/env python3
"""C3 gate R3 — Receipts write back.

Run protocol (matrix): complete a ticket action end-to-end.
PASS (lead #5930 Q1a): a receipt is written — airport_outbound_events advances
LANDED -> RECEIPT_WRITTEN, the ClickUp task is closed, and a bus RECEIPT proof is
posted. (The dashboard-render clause was moved to R8 per #5930; D-23 deferral
respected — this row certifies the receipt ROW, not a dashboard pixel.)

Evidence: receipt row id + event_state + correlation (receipt_written /
receipt_bus_id / receipt_clickup_done).

Controlled-run shape: we seed the journey's LANDED precondition directly on
airport_outbound_events (a marked airport-lounge:c3-gate-* row) rather than
driving the full lounge->boarding->claim->land chain (which needs live ClickUp).
run_receipt_writer then executes the real LANDED->RECEIPT_WRITTEN transition with
ClickUp + bus stubbed. That isolates exactly what R3 certifies: the receipt write.
"""
from __future__ import annotations

import json
import os

import c3_lib as c3

DRY = """
Row R3 — Receipts write back.

  seed   airport_outbound_events row  ticket_id=airport-lounge:c3-gate-r3
         event_state=LANDED  desk_owner=<boarding slug>
         correlation={"package": "returned package (c3 gate)"}
  call   airport_boarding_flow.run_receipt_writer(conn)   (ClickUp + bus stubbed)
  EXPECT event_state advances LANDED -> RECEIPT_WRITTEN
         correlation gains receipt_clickup_done + receipt_bus_id + receipt_written
         baker_actions has airport_boarding.receipt_written

Evidence emitted: {receipt_row_id, event_state, correlation}. PASS =
event_state==RECEIPT_WRITTEN and correlation.receipt_written truthy.
"""


def _seed_landed(conn) -> str:
    from orchestrator import airport_boarding_flow as flow

    ev_id = f"airport-lounge:{c3.PREFIX}r3"
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO airport_outbound_events "
            "(ticket_id, message_id, event_state, desk_owner, correlation) "
            "VALUES (%s, %s, %s, %s, %s::jsonb) "
            "ON CONFLICT (ticket_id) DO UPDATE SET event_state = EXCLUDED.event_state, "
            "correlation = EXCLUDED.correlation, updated_at = NOW()",
            (ev_id, f"{c3.PREFIX}r3", flow.LANDED, flow._DESK,
             json.dumps({"package": "returned package (c3 gate)"})),
        )
    conn.commit()
    return ev_id


def run(conn) -> dict:
    from orchestrator import airport_boarding_flow as flow

    os.environ["AIRPORT_BOARDING_FLOW_ENABLED"] = "true"
    os.environ["BAKER_CLICKUP_READONLY"] = os.environ.get("BAKER_CLICKUP_READONLY", "false")
    c3.cleanup(conn)
    ev_id = _seed_landed(conn)

    result = flow.run_receipt_writer(conn)
    ev = c3.outbound_evidence(conn, ev_id)
    corr = ev.get("correlation") if ev else None
    receipted = bool(ev and ev["event_state"] == "RECEIPT_WRITTEN"
                     and isinstance(corr, dict) and corr.get("receipt_written"))
    return {"pass": receipted,
            "evidence": {"receipt_row_id": ev and ev["id"], "event_state": ev and ev["event_state"],
                         "correlation": corr, "writer_result": result},
            "notes": "" if receipted else f"writer_result={result}"}


if __name__ == "__main__":
    c3.main_scaffold("R3", DRY, run)
