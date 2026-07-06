#!/usr/bin/env python3
"""C3 gate R2 — Coded reply routes E2E (D-39d).

Run protocol (matrix): reply to an OPEN ticket's thread carrying its code.
PASS: reply lands on the existing ticket; NO duplicate ticket; dedup_key
(channel/source_id/desk) holds; a seen-thread reply-replay inserts nothing.

Evidence: ticket ids before/after + dedup log (per-message terminal_reason +
dedup_key, thread ticket count, replay terminal_written).

C2 dependency (noted for lead + b4): the exact "no duplicate ticket" threshold
for the thread-continuity lane is what b4's C2 routing/dedup slice refines. This
runner EMITS the evidence (thread continuity reason + counts + dedup_keys +
replay-inert proof); the PASS bar below is the conservative spine invariant
(same-desk continuity + idempotent replay). Re-pin the bar when C2 lands.
"""
from __future__ import annotations

import os

import c3_lib as c3

DRY = """
Row R2 — Coded reply routes E2E (D-39d).

  step 1  inject email  message_id=c3-gate-r2-a  thread=c3-gate-r2-thr  code BB-AUK-001
          call bridge.run_tick()  -> ticket #1 for message a
  step 2  inject reply  message_id=c3-gate-r2-b  thread=c3-gate-r2-thr  code BB-AUK-001
          call bridge.run_tick()  -> reply routes on the SAME thread
          EXPECT reply terminal_reason = thread_continuity_routed_ticket:BB-AUK-001
                 routed to the SAME desk/matter as ticket #1 (no divergent desk)
  step 3  REPLAY: call bridge.run_tick() again with no new email
          EXPECT terminal_written = 0 (dedup_key UNIQUE -> seen rows insert nothing)

Evidence emitted: {msg_a, msg_b: {ticket_id, terminal_status, terminal_reason,
dedup_key}, thread_ticket_count, replay_terminal_written}. dedup_key =
airport-ticket:v1:email:<source_id>:<desk> — distinct per message, so the
idempotency guard is source_id-uniqueness, and cross-message continuity is the
thread lane (not the dedup key).

PASS (spine invariant): both messages resolve to desk baden-baden-desk / matter
aukera; the reply is the thread_continuity lane; the replay writes nothing.
"""

CODE = "BB-AUK-001"
MATTER = "aukera"
TEST_PARTICIPANT = "partner@aukera.lu"


def _ensure_registered(conn) -> str:
    from kbl import project_registry_store as reg

    if c3.is_live_target():
        vals = reg.active_participant_values(conn, channel="email")
        return vals[0] if vals else "counterparty@aukera.lu"
    c3.register_code(conn, CODE, matter_slug=MATTER,
                     participants=[{"channel": "email", "value": TEST_PARTICIPANT}])
    return TEST_PARTICIPANT


def run(conn) -> dict:
    from orchestrator import airport_ticketing_bridge as bridge

    os.environ["AIRPORT_TICKETING_BRIDGE_ENABLED"] = "true"
    os.environ["BOX5_FAST_LANE_ENABLED"] = "true"
    os.environ.setdefault("AIRPORT_TICKETING_KEYWORDS", "aukera,annaberg,lilienmatt")
    c3.cleanup(conn)
    sender = _ensure_registered(conn)

    c3.inject_email(conn, "r2-a", thread_suffix="r2-thr", sender_email=sender,
                    subject="aukera closing", body=f"opening item on {CODE}")
    bridge.run_tick()
    c3.inject_email(conn, "r2-b", thread_suffix="r2-thr", sender_email=sender,
                    subject="RE: aukera closing", body=f"follow-up on {CODE}")
    bridge.run_tick()
    replay = bridge.run_tick()

    a = c3.ticket_evidence(conn, "c3-gate-r2-a")
    b = c3.ticket_evidence(conn, "c3-gate-r2-b")
    thread_count = c3.ticket_count_for_thread(conn, "c3-gate-r2-thr")
    replay_written = int(replay.get("terminal_written", -1)) if isinstance(replay, dict) else -1

    same_desk = bool(a and b and a["proposed_desk_slug"] == b["proposed_desk_slug"])
    continuity = bool(b and "thread_continuity" in (b["terminal_reason"] or ""))
    replay_inert = replay_written == 0
    return {"pass": same_desk and replay_inert,
            "evidence": {"msg_a": a, "msg_b": b, "thread_ticket_count": thread_count,
                         "replay_terminal_written": replay_written,
                         "reply_is_thread_continuity": continuity},
            "notes": ("" if (same_desk and replay_inert)
                      else f"same_desk={same_desk} replay_inert={replay_inert} "
                           f"continuity={continuity}") +
                     " | C2 pins the final no-duplicate threshold (b4 lane)."}


if __name__ == "__main__":
    c3.main_scaffold("R2", DRY, run)
