#!/usr/bin/env python3
"""C3 gate R1 — Fast lane with real participants (D-39a).

Run protocol (matrix): send a test email from a REAL registered participant
carrying an active project code -> ticket fast-lanes; a participant-only email
with NO code routes desk-review, never fast lane.

PASS: case A -> terminal_status FAST_TICKET, reason hard_lane_project_code_
participant_bound:<code>. case B -> terminal_status TICKET (safe_default_desk_
review), NEVER FAST_TICKET.

Evidence: both ticket ids + terminal_status/terminal_reason/confidence.
"""
from __future__ import annotations

import os

import c3_lib as c3

DRY = """
Row R1 — Fast lane with real participants (D-39a). Two controlled cases:

  Case A (fast lane): a REAL registered participant of an ACTIVE project code
    emails carrying that code.
      inject email  message_id=c3-gate-r1-fast  sender=<pilot participant>
                    body references BB-AUK-001
      call          bridge.run_tick()  (BOX5_FAST_LANE_ENABLED=true)
      EXPECT        airport_tickets.terminal_status = FAST_TICKET
                    terminal_reason  = hard_lane_project_code_participant_bound:BB-AUK-001

  Case B (never fast): the same registered participant emails with NO project code.
      inject email  message_id=c3-gate-r1-part  sender=<pilot participant>  no code
      call          bridge.run_tick()
      EXPECT        terminal_status = TICKET   (reason safe_default_desk_review)
                    NOT FAST_TICKET  (participant-only match must not fast-lane)

Evidence emitted (run log): {caseA: {ticket_id, terminal_status, terminal_reason,
confidence}, caseB: {...}} — codex verifies A is FAST_TICKET and B is TICKET.

Target: on the ephemeral Neon branch the registry is SEEDED (synthetic
participant partner@aukera.lu). On the LIVE DB the run uses the REAL registered
BB-AUK-001 participant (read from the registry) — that is what certifies the live
pipeline.
"""

CODE = "BB-AUK-001"
MATTER = "aukera"
TEST_PARTICIPANT = "partner@aukera.lu"


def _pilot_participant(conn) -> str:
    """Real registered participant on live; seed a synthetic one on the test
    branch and return it."""
    from kbl import project_registry_store as reg

    if c3.is_live_target():
        vals = reg.active_participant_values(conn, channel="email")
        if not vals:
            raise SystemExit("R1 live run: no active email participant registered "
                             f"for the pilot — cannot certify fast lane. ({CODE})")
        return vals[0]
    c3.register_code(conn, CODE, matter_slug=MATTER,
                     participants=[{"channel": "email", "value": TEST_PARTICIPANT}])
    return TEST_PARTICIPANT


def run(conn) -> dict:
    from orchestrator import airport_ticketing_bridge as bridge

    os.environ["AIRPORT_TICKETING_BRIDGE_ENABLED"] = "true"
    os.environ["BOX5_FAST_LANE_ENABLED"] = "true"
    os.environ.setdefault("AIRPORT_TICKETING_KEYWORDS", "aukera,annaberg,lilienmatt")
    c3.cleanup(conn)

    sender = _pilot_participant(conn)
    c3.inject_email(conn, "r1-fast", sender_email=sender, subject="aukera funding",
                    body=f"please review {CODE} for closing")
    c3.inject_email(conn, "r1-part", sender_email=sender, subject="aukera update",
                    body="annaberg status update, no project code here")
    bridge.run_tick()

    a = c3.ticket_evidence(conn, "c3-gate-r1-fast")
    b = c3.ticket_evidence(conn, "c3-gate-r1-part")
    pass_a = bool(a and a["terminal_status"] == "FAST_TICKET"
                  and (a["terminal_reason"] or "").startswith(
                      "hard_lane_project_code_participant_bound"))
    pass_b = bool(b and b["terminal_status"] == "TICKET"
                  and b["terminal_status"] != "FAST_TICKET")
    return {"pass": pass_a and pass_b,
            "evidence": {"caseA_fast": a, "caseB_participant_only": b,
                         "participant_used": sender},
            "notes": "" if (pass_a and pass_b)
            else f"pass_a={pass_a} pass_b={pass_b}"}


if __name__ == "__main__":
    c3.main_scaffold("R1", DRY, run)
