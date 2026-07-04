"""BAKER_OS_V2_STEP2_LOUNGE_WRITER_DRAIN_1 — Airside Lounge writer + backlog drain.

Boarding is not completion. A checked-in ``airport_tickets`` row (a passenger who
cleared the gate: ``check_in_outcome IN ('VALID','URGENT')``) currently dead-ends —
there is NO onward row in ``airport_outbound_events`` (0 rows today) and no ClickUp
task, so the desk never sees the work. This module is the *lounge*: it walks each
checked-in VALID/URGENT ticket onto a ClickUp task + a durable
``airport_outbound_events`` row, idempotently, with a visible exception lane so nothing
is silently discarded.

Design source (AUTHORITATIVE): Baker OS V2 step-2 BB-desk onward-journey pilot spec
(Director-ratified D-30, 2026-07-04). Brief: ``briefs/_tasks/
BAKER_OS_V2_STEP2_LOUNGE_WRITER_DRAIN_1.md`` — scope blocks 1 (lounge writer) + 5
(exception lane) + 6 (backlog drain).

This EXTENDS the Box-5 outbound connector (``airport_outbound_connector``) and reuses
its ``airport_outbound_events`` table + ClickUp space-guard + audit patterns. The lounge
writer is a SIBLING lane, distinguished by:
  - event ``ticket_id`` scheme ``airport-lounge:<source_ticket_id>`` (the connector uses
    ``airport-outbound:<message_id>``) — the two lanes never collide on the UNIQUE key;
  - trigger_source ``airport_lounge_writer`` on every ``baker_actions`` audit row;
  - flight columns stay **NULL** (D-23: no flight lifecycle store exists yet; a lounge
    row terminates at ``CLICKUP_WRITTEN`` / an exception state — no flight transition).

Sequencing rulings honored (Controller-confirmed, D-23 / D-28 / D-29): no flight state,
no new intake (drains already-checked-in tickets only), ClickUp is Surface 1 (no
dashboard wiring).

Transaction model: the drain OWNS its connection and commits per ticket, so a failure
mid-drain never rolls back completed writes and every ClickUp task's event row is
durable (mirrors the bridge's per-row commit ownership). A ClickUp *API* failure is
caught and recorded (ERROR_RETRY / CLICKUP_BLOCKED), never re-raised — the ticket is
durably dispositioned, never silently dropped.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import logging

# Reuse the connector's event-table bootstrap, space guard, JSON wrapper, and the
# BAKER Space id — single-source, no drift between the two lanes writing one table.
from orchestrator.airport_outbound_connector import (
    ensure_airport_outbound_events_table,
    _resolve_list_space,
    _json_param,
    _BAKER_SPACE_ID,
    CLICKUP_WRITTEN,
    CLICKUP_BLOCKED,
    EVIDENCE_ONLY,
    NEEDS_CONTROLLER,
    ERROR_RETRY,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Activation + write-cap constants
# ---------------------------------------------------------------------------
_ENABLED_ENV = "AIRPORT_LOUNGE_WRITER_ENABLED"   # default OFF (merge = no-op)
_READONLY_ENV = "BAKER_CLICKUP_READONLY"         # repo kill switch (dry-run)
_LOUNGE_TRIGGER = "airport_lounge_writer"
_LOUNGE_KEY_PREFIX = "airport-lounge:"           # distinct from airport-outbound:
_MAX_WRITES_PER_CYCLE = 10                        # ClickUp hard cap (repo rule)

# The desk being drained by this pilot. A single-entry map today (BB desk → its
# BB-AUK-001 Timetable list); a config-table design is a later brief if more desks/lists
# onboard. A desk absent from the map → exception lane (no_target_list), never a silent
# write to the wrong place.
_DESK_LIST_MAP = {
    "baden-baden-desk": "901524194809",   # BB-AUK-001 Timetable (BAKER Space)
}

# BB-AUK-001 Timetable vocab (canary-proven, see connector _PER_LIST_STATUS_MAP):
# to do, planning, in progress, at risk, update required, on hold, waiting, blocked,
# complete, cancelled. The lounge writer uses three of them.
_STATUS_NEW = "to do"                 # fresh checked-in ticket, ready for the desk
_STATUS_PARKED = "update required"    # exception lane: desk must resolve before onward
_STATUS_BLOCKED = "blocked"           # hard block that still had a writable list

# ClickUp priority ints: 1=urgent, 2=high, 3=normal, 4=low.
_PRIORITY_URGENT = 1
_PRIORITY_HIGH = 2
_PRIORITY_NORMAL = 3

# Disposition actions (pure-planning output, before any DB/ClickUp side effect).
ACT_WRITE = "write"   # create ClickUp task + CLICKUP_WRITTEN event row
ACT_PARK = "park"     # exception lane: parking-status ClickUp task + NEEDS_CONTROLLER
ACT_BLOCK = "block"   # cannot route (no list): event-row-only CLICKUP_BLOCKED, loud log
ACT_DUP = "dup"       # duplicate of an earlier ticket in the batch: no new ClickUp task


def lounge_enabled() -> bool:
    return os.environ.get(_ENABLED_ENV, "false").strip().lower() in {"1", "true", "yes", "on"}


def _readonly() -> bool:
    return os.environ.get(_READONLY_ENV, "").strip().lower() == "true"


def event_ticket_id(source_ticket_id: str) -> str:
    return _LOUNGE_KEY_PREFIX + (source_ticket_id or "")


def _idem_key(source_ticket_id: str) -> str:
    return "airport-lounge:v1:" + (source_ticket_id or "")


# ---------------------------------------------------------------------------
# Test seam: ClickUp client indirection (monkeypatched in tests on THIS module).
# ---------------------------------------------------------------------------
def _get_clickup_client() -> Any:
    """Return the shared ClickUpClient singleton (so the ≤10-writes/cycle cap is honored
    across writers). Overridden in tests with a thin recording fake."""
    from clickup_client import ClickUpClient

    return ClickUpClient._get_global_instance()


# ---------------------------------------------------------------------------
# Pure planning (no DB, no ClickUp) — unit-testable per brief.
# ---------------------------------------------------------------------------
def _priority_for(ticket: Dict[str, Any]) -> int:
    if ticket.get("check_in_outcome") == "URGENT" or ticket.get("urgency_hint") == "urgent":
        return _PRIORITY_URGENT
    if ticket.get("urgency_hint") == "high":
        return _PRIORITY_HIGH
    return _PRIORITY_NORMAL


def classify_disposition(ticket: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[str], str]:
    """Pure single-ticket disposition (before dup-scan). Returns
    ``(action, list_id, status, reason)``.

    - No desk→list mapping ⇒ ACT_BLOCK (``no_target_list``): cannot write anywhere, so
      the ticket is recorded as an event-row-only block, never silently dropped.
    - A resolvable list but NO ``matter_slug`` ⇒ ACT_PARK (``no_matter_slug``): routing
      is unclear, so it lands on a visible ``update required`` parking task for the desk.
    - Otherwise ACT_WRITE with the fresh ``to do`` status.
    """
    desk = ticket.get("proposed_desk_slug") or ""
    list_id = _DESK_LIST_MAP.get(desk)
    if not list_id:
        return ACT_BLOCK, None, None, "no_target_list"
    if not (ticket.get("suspected_matter_slug") or "").strip():
        return ACT_PARK, list_id, _STATUS_PARKED, "no_matter_slug"
    return ACT_WRITE, list_id, _STATUS_NEW, "checked_in"


def plan_drain(ticket_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pure drain plan (no side effects). Given checked-in ticket rows:

    1. **Pre-drain dup scan (D-28 guard):** group by ``source_id`` (the source message
       identity). The FIRST ticket in each group (urgent-first, then oldest) is the
       primary; the rest become ACT_DUP with ``dup_of`` = the primary's ticket_id — one
       ClickUp task per real message, extras marked, never a duplicate task.
    2. **Urgent-first ordering:** URGENT check-in outcome (and urgent hint) sort ahead of
       VALID, then oldest ``created_ts`` first for stable draining.

    Returns an ordered list of plan dicts:
      ``{ticket, action, list_id, status, reason, dup_of}``.
    """
    def _urgent_rank(t: Dict[str, Any]) -> int:
        return 0 if (t.get("check_in_outcome") == "URGENT"
                     or t.get("urgency_hint") == "urgent") else 1

    ordered = sorted(
        ticket_rows,
        key=lambda t: (_urgent_rank(t), t.get("created_ts") or 0, t.get("ticket_id") or ""),
    )

    seen_source: Dict[str, str] = {}   # source_id -> primary ticket_id
    plan: List[Dict[str, Any]] = []
    for t in ordered:
        src = t.get("source_id") or ""
        if src and src in seen_source:
            plan.append({"ticket": t, "action": ACT_DUP, "list_id": None,
                         "status": None, "reason": "dup_source_message",
                         "dup_of": seen_source[src]})
            continue
        action, list_id, status, reason = classify_disposition(t)
        if src:
            seen_source[src] = t.get("ticket_id") or ""
        plan.append({"ticket": t, "action": action, "list_id": list_id,
                     "status": status, "reason": reason, "dup_of": None})
    return plan


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def read_checked_in_tickets(conn: Any, desk_slug: str) -> List[Dict[str, Any]]:
    """Checked-in VALID/URGENT tickets for ``desk_slug`` (the drain candidates). LIMIT
    keeps the read bounded (repo rule); a backlog far past the cap simply drains over
    more cycles."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ticket_id, source_id, thread_id, proposed_desk_slug, "
            "       suspected_matter_slug, urgency_hint, check_in_outcome, ticket, "
            "       EXTRACT(EPOCH FROM created_at) "
            "FROM airport_tickets "
            "WHERE proposed_desk_slug = %s "
            "  AND check_in_outcome IN ('VALID','URGENT') "
            "ORDER BY created_at ASC "
            "LIMIT 500",
            (desk_slug,),
        )
        rows = cur.fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({
            "ticket_id": r[0], "source_id": r[1], "thread_id": r[2],
            "proposed_desk_slug": r[3], "suspected_matter_slug": r[4],
            "urgency_hint": r[5], "check_in_outcome": r[6],
            "ticket_payload": r[7] or {}, "created_ts": float(r[8] or 0),
        })
    return out


def _existing_disposition(conn: Any, ev_ticket_id: str) -> Optional[str]:
    """Return the event_state of an existing lounge row for this source ticket, or None.
    Idempotency gate (AC2): a row that already exists is never re-written."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT event_state FROM airport_outbound_events WHERE ticket_id = %s",
            (ev_ticket_id,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def _write_event(conn: Any, ev_ticket_id: str, **fields: Any) -> None:
    """Idempotent upsert of a lounge event row keyed on ticket_id. ``correlation`` is
    JSONB-wrapped. message_id is NOT NULL in the table, so callers always pass it."""
    fields.setdefault("event_state", CLICKUP_WRITTEN)
    cols = ["ticket_id"]
    vals: List[Any] = [ev_ticket_id]
    updates: List[str] = []
    for k, v in fields.items():
        cols.append(k)
        vals.append(_json_param(v) if k == "correlation" else v)
        updates.append(f"{k} = EXCLUDED.{k}")
    placeholders = ", ".join(["%s"] * len(cols))
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO airport_outbound_events (" + ", ".join(cols) + ") "
            "VALUES (" + placeholders + ") "
            "ON CONFLICT (ticket_id) DO UPDATE SET "
            + ", ".join(updates) + ", updated_at = NOW()",
            tuple(vals),
        )


def _audit(conn: Any, action_type: str, target_task_id: Optional[str],
           payload: Dict[str, Any], success: bool,
           error_message: Optional[str] = None) -> None:
    """One baker_actions row per lounge write / block, trigger_source
    ``airport_lounge_writer`` (distinct from the connector's increment2 source)."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO baker_actions (action_type, target_task_id, target_space_id, "
            "payload, trigger_source, success, error_message) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (action_type, target_task_id, _BAKER_SPACE_ID, _json_param(payload),
             _LOUNGE_TRIGGER, success, error_message),
        )


# ---------------------------------------------------------------------------
# Per-ticket execution
# ---------------------------------------------------------------------------
def _correlation_json(ticket: Dict[str, Any], reason: str,
                      dup_of: Optional[str] = None,
                      ttl_renudge: bool = False) -> Dict[str, Any]:
    corr: Dict[str, Any] = {
        "source": "lounge_writer",
        "source_ticket_id": ticket.get("ticket_id"),
        "check_in_outcome": ticket.get("check_in_outcome"),
        "urgency_hint": ticket.get("urgency_hint"),
        "reason": reason,
    }
    if dup_of:
        corr["dup_of"] = dup_of
    if ttl_renudge:
        # The actual re-nudge scheduler is NOT built in this brief — the marker is
        # recorded and logged loudly so a parked ticket is visibly awaiting follow-up.
        corr["ttl_renudge_pending"] = True
    return corr


def _task_title(ticket: Dict[str, Any]) -> str:
    payload = ticket.get("ticket_payload") or {}
    subj = ""
    if isinstance(payload, dict):
        subj = payload.get("subject") or payload.get("originator") or ""
    outcome = ticket.get("check_in_outcome") or "VALID"
    return ("[%s] %s" % (outcome, subj or ticket.get("ticket_id") or "checked-in ticket"))[:255]


def _task_description(ticket: Dict[str, Any], reason: str) -> str:
    payload = ticket.get("ticket_payload") or {}
    why = ""
    if isinstance(payload, dict):
        why = "; ".join(payload.get("why_ticketed") or []) if payload.get("why_ticketed") else ""
    return (
        "Airside lounge onward-journey task.\n"
        "source_ticket_id=%s\ncheck_in_outcome=%s\nmatter=%s\nreason=%s\n%s"
        % (ticket.get("ticket_id"), ticket.get("check_in_outcome"),
           ticket.get("suspected_matter_slug"), reason, why)
    )[:3000]


def _disposition_one(conn: Any, plan_item: Dict[str, Any], readonly: bool) -> Dict[str, Any]:
    """Execute ONE planned disposition. Owns no commit — the drain loop commits per
    ticket. Returns a result dict incl. ``clickup_write_attempted`` so the drain can
    count against the ≤10/cycle cap accurately."""
    ticket = plan_item["ticket"]
    action = plan_item["action"]
    ev_id = event_ticket_id(ticket.get("ticket_id") or "")
    message_id = (ticket.get("source_id") or ticket.get("ticket_id") or "")
    thread_id = ticket.get("thread_id")
    desk = ticket.get("proposed_desk_slug")
    matter = ticket.get("suspected_matter_slug")
    list_id = plan_item.get("list_id")
    reason = plan_item.get("reason") or ""

    base = {"ticket_id": ticket.get("ticket_id"), "event_id": ev_id,
            "action": action, "clickup_write_attempted": False,
            "clickup_written": False, "event_state": None}

    # Idempotency (AC2): an existing lounge row is never re-written, no duplicate task.
    existing = _existing_disposition(conn, ev_id)
    if existing is not None:
        base["event_state"] = existing
        base["skipped_idempotent"] = True
        return base

    # ACT_DUP — duplicate source message: record, no ClickUp task (D-28).
    if action == ACT_DUP:
        _write_event(conn, ev_id, message_id=message_id, thread_id=thread_id,
                     event_state=EVIDENCE_ONLY, desk_owner=desk, matter_slug=matter,
                     correlation=_correlation_json(ticket, reason, dup_of=plan_item.get("dup_of")))
        base["event_state"] = EVIDENCE_ONLY
        return base

    # ACT_BLOCK — no routable list: event-row-only block, loud log, nothing discarded.
    if action == ACT_BLOCK:
        logger.warning("lounge: ticket %s BLOCKED (%s) — no ClickUp task written",
                       ticket.get("ticket_id"), reason)
        _write_event(conn, ev_id, message_id=message_id, thread_id=thread_id,
                     event_state=CLICKUP_BLOCKED, desk_owner=desk, matter_slug=matter,
                     clickup_list_id=list_id, last_error=reason,
                     correlation=_correlation_json(ticket, reason))
        base["event_state"] = CLICKUP_BLOCKED
        return base

    # ACT_WRITE / ACT_PARK both attempt a ClickUp task (park = parking status).
    status = plan_item.get("status") or _STATUS_NEW
    is_park = action == ACT_PARK
    idem = _idem_key(ticket.get("ticket_id") or "")

    # Kill switch / dry-run: log the intended write, record a BLOCKED event row (durable
    # disposition, truthful reconciliation), never call ClickUp.
    if readonly:
        logger.warning("lounge DRY-RUN (readonly): WOULD create ClickUp task list=%s "
                       "status=%s title=%r for ticket %s",
                       list_id, status, _task_title(ticket), ticket.get("ticket_id"))
        _write_event(conn, ev_id, message_id=message_id, thread_id=thread_id,
                     event_state=CLICKUP_BLOCKED, desk_owner=desk, matter_slug=matter,
                     clickup_list_id=list_id, clickup_status=status,
                     clickup_operation="create_task", clickup_idempotency_key=idem,
                     last_error="readonly",
                     correlation=_correlation_json(ticket, reason, ttl_renudge=is_park))
        _audit(conn, "airport_lounge.clickup_write", None,
               {"ticket_id": ticket.get("ticket_id"), "list_id": list_id,
                "status": status, "operation": "create_task", "dry_run": True,
                "idempotency_key": idem}, success=False, error_message="readonly_dry_run")
        base["event_state"] = CLICKUP_BLOCKED
        return base

    client = _get_clickup_client()

    # Space guard (repo HARD RULE F2): never write ClickUp outside BAKER Space.
    if _resolve_list_space(client, list_id) != _BAKER_SPACE_ID:
        logger.warning("lounge: ticket %s BLOCKED (non_baker_space) list=%s",
                       ticket.get("ticket_id"), list_id)
        _write_event(conn, ev_id, message_id=message_id, thread_id=thread_id,
                     event_state=CLICKUP_BLOCKED, desk_owner=desk, matter_slug=matter,
                     clickup_list_id=list_id, last_error="non_baker_space",
                     correlation=_correlation_json(ticket, "non_baker_space"))
        _audit(conn, "airport_lounge.clickup_write", None,
               {"ticket_id": ticket.get("ticket_id"), "list_id": list_id,
                "blocked_reason": "non_baker_space"}, success=False,
               error_message="non_baker_space")
        base["event_state"] = CLICKUP_BLOCKED
        return base

    base["clickup_write_attempted"] = True
    task_id = None
    try:
        res = client.create_task(
            list_id=list_id,
            name=_task_title(ticket),
            description=_task_description(ticket, reason),
            status=status,
            priority=_priority_for(ticket),
        )
        task_id = (res or {}).get("id")
    except Exception as exc:
        # Transient ClickUp failure → ERROR_RETRY (durable, retried next cycle), never
        # re-raised, never a silent drop.
        logger.warning("lounge: ticket %s ClickUp create_task raised: %s",
                       ticket.get("ticket_id"), exc)
        _write_event(conn, ev_id, message_id=message_id, thread_id=thread_id,
                     event_state=ERROR_RETRY, desk_owner=desk, matter_slug=matter,
                     clickup_list_id=list_id, clickup_status=status,
                     clickup_operation="create_task", clickup_idempotency_key=idem,
                     last_error=str(exc)[:400],
                     correlation=_correlation_json(ticket, reason))
        _audit(conn, "airport_lounge.clickup_write", idem,
               {"ticket_id": ticket.get("ticket_id"), "list_id": list_id,
                "status": status, "operation": "create_task"}, success=False,
               error_message=str(exc)[:400])
        base["event_state"] = ERROR_RETRY
        return base

    if not task_id:
        # HTTP>=400 / exhausted retries → clickup_client._request returns None: a HANDLED
        # write FAILURE, recorded as CLICKUP_BLOCKED (not success), never dropped.
        logger.warning("lounge: ticket %s ClickUp write returned no id (blocked)",
                       ticket.get("ticket_id"))
        _write_event(conn, ev_id, message_id=message_id, thread_id=thread_id,
                     event_state=CLICKUP_BLOCKED, desk_owner=desk, matter_slug=matter,
                     clickup_list_id=list_id, clickup_status=status,
                     clickup_operation="create_task", clickup_idempotency_key=idem,
                     last_error="clickup_write_failed_no_id",
                     correlation=_correlation_json(ticket, reason))
        _audit(conn, "airport_lounge.clickup_write", idem,
               {"ticket_id": ticket.get("ticket_id"), "list_id": list_id,
                "status": status, "blocked_reason": "clickup_write_failed_no_id"},
               success=False, error_message="clickup_write_failed_no_id")
        base["event_state"] = CLICKUP_BLOCKED
        return base

    # Success. ACT_PARK → NEEDS_CONTROLLER (parked, awaiting desk); ACT_WRITE →
    # CLICKUP_WRITTEN. Both wrote a visible ClickUp task. Flight columns stay NULL (D-23).
    final_state = NEEDS_CONTROLLER if is_park else CLICKUP_WRITTEN
    _write_event(conn, ev_id, message_id=message_id, thread_id=thread_id,
                 event_state=final_state, desk_owner=desk, matter_slug=matter,
                 clickup_list_id=list_id, clickup_task_id=task_id, clickup_status=status,
                 clickup_operation="create_task", clickup_idempotency_key=idem,
                 correlation=_correlation_json(ticket, reason, ttl_renudge=is_park))
    _audit(conn, "airport_lounge.clickup_write", task_id,
           {"ticket_id": ticket.get("ticket_id"), "list_id": list_id, "status": status,
            "operation": "create_task", "parked": is_park, "idempotency_key": idem},
           success=True)
    base["clickup_written"] = True
    base["event_state"] = final_state
    base["clickup_task_id"] = task_id
    return base


# ---------------------------------------------------------------------------
# Drain entry point
# ---------------------------------------------------------------------------
def run_lounge_drain(conn: Any, desk_slug: str = "baden-baden-desk",
                     cap: int = _MAX_WRITES_PER_CYCLE) -> Dict[str, Any]:
    """Drain checked-in VALID/URGENT tickets for ``desk_slug`` onto ClickUp + event rows.

    ONE cycle: processes planned tickets urgent-first, honoring the ≤``cap`` ClickUp
    writes/cycle hard rule (only ACT_WRITE/ACT_PARK count — dup/block/idempotent-skip do
    not call ClickUp). Tickets past the cap are DEFERRED (no event row) and drain on the
    next call — call repeatedly until ``remaining == 0``. Idempotent: an already-written
    ticket is skipped on re-run, so re-draining never duplicates a task.

    Flag-off (``AIRPORT_LOUNGE_WRITER_ENABLED`` != true) ⇒ no-op (AC: merge is inert).
    ``BAKER_CLICKUP_READONLY=true`` ⇒ dry-run: intended writes logged, no ClickUp calls.
    """
    result: Dict[str, Any] = {
        "enabled": lounge_enabled(), "desk": desk_slug, "dry_run": _readonly(),
        "candidates": 0, "wrote": 0, "parked": 0, "blocked": 0, "dup": 0,
        "error_retry": 0, "skipped_idempotent": 0, "deferred_cap": 0,
        "cap": cap, "dispositions": [],
    }
    if not result["enabled"]:
        logger.info("lounge drain: flag OFF — no-op")
        return result

    ensure_airport_outbound_events_table(conn)
    conn.commit()

    tickets = read_checked_in_tickets(conn, desk_slug)
    result["candidates"] = len(tickets)
    plan = plan_drain(tickets)
    readonly = _readonly()

    writes_this_cycle = 0
    for item in plan:
        # Cap gate: only ClickUp-writing actions consume the budget. A would-be write
        # past the cap is DEFERRED (left with no event row) for the next cycle.
        will_write = item["action"] in (ACT_WRITE, ACT_PARK) and not readonly
        if will_write and writes_this_cycle >= cap:
            result["deferred_cap"] += 1
            continue
        try:
            r = _disposition_one(conn, item, readonly)
            conn.commit()
        except Exception as exc:
            # python-backend rule: rollback before any further query. The ticket keeps no
            # event row this cycle (retried next call) — surfaced, not swallowed silently.
            conn.rollback()
            logger.error("lounge drain: ticket %s failed hard: %s",
                         item["ticket"].get("ticket_id"), exc)
            result["error_retry"] += 1
            continue

        if r.get("skipped_idempotent"):
            result["skipped_idempotent"] += 1
        elif r["event_state"] == CLICKUP_WRITTEN:
            result["wrote"] += 1
        elif r["event_state"] == NEEDS_CONTROLLER:
            result["parked"] += 1
        elif r["event_state"] == CLICKUP_BLOCKED:
            result["blocked"] += 1
        elif r["event_state"] == EVIDENCE_ONLY:
            result["dup"] += 1
        elif r["event_state"] == ERROR_RETRY:
            result["error_retry"] += 1

        if r.get("clickup_write_attempted") and not readonly:
            writes_this_cycle += 1
        result["dispositions"].append(
            {"ticket_id": r["ticket_id"], "state": r["event_state"],
             "action": r["action"]})

    result["writes_this_cycle"] = writes_this_cycle
    logger.info("lounge drain cycle: candidates=%d wrote=%d parked=%d blocked=%d "
                "dup=%d error_retry=%d skipped=%d deferred_cap=%d",
                result["candidates"], result["wrote"], result["parked"],
                result["blocked"], result["dup"], result["error_retry"],
                result["skipped_idempotent"], result["deferred_cap"])
    return result


# ---------------------------------------------------------------------------
# Reconciliation (T3.3 / AC1 + AC5)
# ---------------------------------------------------------------------------
# Literal SQL kept as module constants so the ship report and the live readout use the
# EXACT same queries (no drift between doc and proof).
ORPHAN_SQL = (
    "SELECT t.ticket_id "
    "FROM airport_tickets t "
    "LEFT JOIN airport_outbound_events e "
    "  ON e.ticket_id = 'airport-lounge:' || t.ticket_id "
    "WHERE t.proposed_desk_slug = %s "
    "  AND t.check_in_outcome IN ('VALID','URGENT') "
    "  AND e.ticket_id IS NULL"
)

FLIGHT_NULL_SQL = (
    "SELECT count(*) FROM airport_outbound_events "
    "WHERE ticket_id LIKE 'airport-lounge:%%' "
    "  AND (flight_id IS NOT NULL OR flight_from_state IS NOT NULL "
    "       OR flight_to_state IS NOT NULL OR flight_idempotency_key IS NOT NULL)"
)


def reconcile(conn: Any, desk_slug: str = "baden-baden-desk") -> Dict[str, Any]:
    """Prove the drain: (a) 0 checked-in VALID/URGENT tickets without a lounge onward
    row (AC1), (b) 0 lounge rows with any non-NULL flight column (AC5 / D-23)."""
    with conn.cursor() as cur:
        cur.execute(ORPHAN_SQL, (desk_slug,))
        orphans = [r[0] for r in cur.fetchall()]
        cur.execute(FLIGHT_NULL_SQL)
        flight_leak = cur.fetchone()[0]
    return {"orphans": orphans, "orphan_count": len(orphans),
            "flight_column_leak_count": int(flight_leak)}
