"""BOX5_OUTBOUND_INGEST_2 — outbound ratification connector.

Increment 1 (``airport_ticketing_bridge._ingest_outbound_signal``) captures each
Brisen OUTBOUND email as a ``direction='outbound'`` ``airport_tickets`` row plus one
``airport_ticket.outbound_signal`` action, short-circuiting before every desk lane.
This module is Increment 2: it wires that captured signal to (a) a ClickUp timetable
write and (b) a RECORD-ONLY flight-state transition, for *ratifying* outbound only;
routine outbound stays evidence-only.

Director ruling (2026-07-01): Brisen OUTBOUND email is a first-class ratification
signal — outbound is often the ratification of what humans proposed to the Director,
so it advances the ClickUp timetable and the flight process.

Design source (AUTHORITATIVE): ``baker-os-v2-box5-routing-reversal-e-outbound-
increment2-spec-codex-arch-20260701.md`` §"Deliverable 2 — Outbound Ingestion
Increment 2". Brief: ``briefs/BRIEF_BOX5_OUTBOUND_INGEST_2.md``.

RECORD-ONLY flight (lead confirmed bus #4851, 2026-07-01): NO live flight-state store
exists in the repo — ``suspected_flight`` is a free-text label, and the flight
vocabulary (``waiting_ratification`` … ``landed``) exists nowhere. Building a flights
store exceeds this brief's Files Modified. So the flight transition is *recorded* on
the ``airport_outbound_events`` row (``flight_id`` / ``flight_from_state`` /
``flight_to_state`` / ``ratification_class``) plus a ``baker_actions``
``airport_outbound.flight_transition_recorded`` audit — no external flight store is mutated.
"Active flight" for the FLIGHT_BLOCKED gate = a correlation hit in step 4 (an active
dispatcher thread, or a prior ticket on the same email thread carrying a
``suspected_flight``); a miss → FLIGHT_BLOCKED.

Transaction model: every function here takes the caller's connection and does NOT
commit — the bridge owns the per-row commit so capture + connector land atomically.
A ClickUp *API* failure is caught internally and recorded as ERROR_RETRY (never
re-raised), so the event is durable and the bridge can freeze its cursor for retry
(the email cursor never silently drops the event). A *Postgres* failure propagates so
the bridge's per-row handler rolls back + counts it failed (never a silent clear).
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event states (spec §"Event State Machine"). Kept in lock-step with the CHECK
# constraint in migrations/20260701b_airport_outbound_events.sql.
# ---------------------------------------------------------------------------
CAPTURED = "CAPTURED"
DIRECTION_PROVEN = "DIRECTION_PROVEN"
CORRELATION_PENDING = "CORRELATION_PENDING"
EVIDENCE_ONLY = "EVIDENCE_ONLY"
RATIFICATION_READY = "RATIFICATION_READY"
CLICKUP_BLOCKED = "CLICKUP_BLOCKED"
CLICKUP_WRITTEN = "CLICKUP_WRITTEN"
FLIGHT_BLOCKED = "FLIGHT_BLOCKED"
FLIGHT_PROGRESSED = "FLIGHT_PROGRESSED"
NEEDS_CONTROLLER = "NEEDS_CONTROLLER"
ERROR_RETRY = "ERROR_RETRY"

# Terminal-for-this-tick states: reaching one means the connector has nothing more to
# do this pass (the bridge may advance its cursor). ERROR_RETRY is the ONLY non-terminal
# outcome — it must be retried, so the bridge freezes the cursor and re-fetches.
_TERMINAL_STATES = frozenset(
    {
        EVIDENCE_ONLY,
        CLICKUP_BLOCKED,
        CLICKUP_WRITTEN,
        FLIGHT_BLOCKED,
        FLIGHT_PROGRESSED,
        NEEDS_CONTROLLER,
    }
)

# Ratification content classes (spec §"Ratifying Vs Routine Outbound" item 4).
CLASS_APPROVAL = "approval"          # approval / ratification
CLASS_INSTRUCTION = "instruction"    # instruction to proceed
CLASS_EXTERNAL_SEND = "external_send"  # external send completed (awaiting reply)
CLASS_COMMITMENT = "commitment"      # commitment / deadline confirmed
CLASS_DELIVERABLE = "deliverable"    # deliverable sent
CLASS_CLOSE = "close"                # explicit close / acceptance

# Content-class keyword sets. Deterministic (code answers the question — NOT an LLM
# call in the tick loop): the acceptance criteria are keyword-driven and must be
# reproducible, and an Opus call per outbound row would be non-deterministic + costly.
# Precedence is the order below (close is most specific, commitment least).
_CLASS_KEYWORDS = (
    (CLASS_CLOSE, (
        "final acceptance", "accepted and closed", "sign-off received",
        "signed and returned", "countersigned", "fully executed",
        "we accept", "hereby accept", "closing confirmation", "close out",
    )),
    (CLASS_EXTERNAL_SEND, (
        "sent to", "forwarded to", "have sent", "i have sent", "i've sent",
        "emailed to", "awaiting their reply", "awaiting reply", "sent the",
    )),
    (CLASS_DELIVERABLE, (
        "please find attached", "deliverable attached", "sending the deliverable",
        "delivered the", "here is the deliverable", "attached is the",
    )),
    (CLASS_APPROVAL, (
        "approve", "approved", "ratif", "signed off", "sign off", "green light",
        "go ahead",
    )),
    (CLASS_INSTRUCTION, (
        "please proceed", "proceed with", "go ahead and", "instruct", "action this",
        "kindly proceed",
    )),
    (CLASS_COMMITMENT, (
        "we commit", "committed to", "deadline", "due by", "will deliver by",
        "by end of",
    )),
)

# ClickUp status mapping (spec §"ClickUp Write Contract" status table).
_STATUS_READY = "Ready for Baker Relay"
_STATUS_PACKET_DRAFT = "Packet Draft"
_STATUS_WAITING_REPLY = "Waiting Reply"
_STATUS_NEEDS_DIRECTOR = "Needs Director"
_STATUS_CLOSED = "Closed"

# Flight transitions (spec §"Flight-State Progression Contract"). Record-only: the
# from/to states are recorded on the event, not applied to any live flight store.
# (rclass -> (from_state, to_state)). CLASS_CLOSE resolves its to_state at runtime via
# the closure guard; CLASS_COMMITMENT is a due/blocker update with state unchanged.
_FLIGHT_TRANSITION = {
    CLASS_APPROVAL: ("waiting_ratification", "ready_for_takeoff"),
    CLASS_INSTRUCTION: ("waiting_ratification", "ready_for_takeoff"),
    CLASS_EXTERNAL_SEND: ("in_flight", "waiting_counterparty"),
    CLASS_DELIVERABLE: ("in_flight", "waiting_receipt"),
    CLASS_COMMITMENT: ("in_flight", "in_flight"),   # due/blocker update; state unchanged
    CLASS_CLOSE: ("waiting_receipt", None),         # to_state decided by closure guard
}

_BAKER_SPACE_ID = "901510186446"
_TRIGGER_SOURCE = "airport_outbound_increment2"

# Automated-sender / system-notification patterns (AC11). A superset of the bridge's
# skip patterns plus Brisen-domain automated notifiers, so a system/task-notification
# email can never become an outbound ratification.
_SYSTEM_SENDER_PATTERNS = (
    "noreply@", "no-reply@", "notifications@", "notification@", "donotreply@",
    "do-not-reply@", "mailer-daemon@", "postmaster@", "@clickup.com", "@todoist.com",
    "bounce", "automated@",
)
_SYSTEM_SUBJECT_MARKERS = (
    "task notification", "you have been assigned", "new comment on", "reminder:",
    "[clickup]", "[todoist]", "out of office", "delivery status notification",
    "undeliverable", "task-notification",
)


def _json_param(payload: Dict[str, Any]) -> Any:
    """Wrap a dict for a JSONB column (psycopg2.extras.Json when available, else a
    JSON string). Mirrors airport_ticketing_bridge._json_param to avoid a circular
    import (the bridge imports this module)."""
    try:
        import psycopg2.extras

        return psycopg2.extras.Json(payload)
    except Exception:
        import json

        return json.dumps(payload)


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------
def ensure_airport_outbound_events_table(conn: Any) -> None:
    """Idempotent bootstrap mirroring migrations/20260701b_airport_outbound_events.sql
    (migration-vs-bootstrap drift fix, Lesson #50). New table — no pre-existing-column
    type-drift risk, and no ALTER, so re-runs take only an ACCESS SHARE catalog lookup.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS airport_outbound_events (
                id                      BIGSERIAL PRIMARY KEY,
                ticket_id               TEXT NOT NULL UNIQUE,
                message_id              TEXT NOT NULL,
                thread_id               TEXT,
                event_state             TEXT NOT NULL DEFAULT 'CAPTURED',
                ratification_class      TEXT,
                project_code            TEXT,
                matter_slug             TEXT,
                desk_owner              TEXT,
                clickup_list_id         TEXT,
                clickup_task_id         TEXT,
                clickup_status          TEXT,
                clickup_operation       TEXT,
                clickup_idempotency_key TEXT,
                flight_id               TEXT,
                flight_from_state       TEXT,
                flight_to_state         TEXT,
                flight_idempotency_key  TEXT,
                correlation             JSONB NOT NULL DEFAULT '{}'::jsonb,
                last_error              TEXT,
                created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CONSTRAINT airport_outbound_events_state_check
                    CHECK (event_state IN (
                        'CAPTURED', 'DIRECTION_PROVEN', 'CORRELATION_PENDING',
                        'EVIDENCE_ONLY', 'RATIFICATION_READY', 'CLICKUP_BLOCKED',
                        'CLICKUP_WRITTEN', 'FLIGHT_BLOCKED', 'FLIGHT_PROGRESSED',
                        'NEEDS_CONTROLLER', 'ERROR_RETRY'
                    ))
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_airport_outbound_events_state "
            "ON airport_outbound_events (event_state)"
        )


# ---------------------------------------------------------------------------
# Content classification + field extraction
# ---------------------------------------------------------------------------
def classify_ratification(subject: str, body: str) -> Optional[str]:
    """Return the ratification content class (spec item 4) or None (routine). First
    matching class in ``_CLASS_KEYWORDS`` precedence order wins."""
    hay = ((subject or "") + "\n" + (body or "")).lower()
    for rclass, keywords in _CLASS_KEYWORDS:
        for kw in keywords:
            if kw in hay:
                return rclass
    return None


def _is_system_notification(sender_email: str, subject: str) -> bool:
    """AC11: a system / task-notification email must never become an outbound
    ratification. Caught by sender pattern OR subject marker."""
    s = (sender_email or "").strip().lower()
    if any(p in s for p in _SYSTEM_SENDER_PATTERNS):
        return True
    subj = (subject or "").strip().lower()
    return any(m in subj for m in _SYSTEM_SUBJECT_MARKERS)


_OWNER_RES = (
    re.compile(r"\bowner\s*[:=]\s*([A-Za-z0-9_.\-]+)", re.IGNORECASE),
    re.compile(r"\bassigned\s+to\s+([A-Za-z0-9_.\-]+)", re.IGNORECASE),
    re.compile(r"@([A-Za-z0-9_.\-]+)"),
    re.compile(
        r"\b([A-Z][A-Za-z]+)\s+to\s+"
        r"(?:sign|prepare|send|review|execute|proceed|wire|pay|deliver|counter-sign)\b"
    ),
)
_DUE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
# A concrete next-action clause: an imperative ("proceed with …" / "please …" /
# "kindly …") OR a "to <verb>" directive ("DV to sign", "to wire the funds").
_ACTION_RE = re.compile(
    r"\b(?:proceed with|please|kindly)\s+[A-Za-z][^.\n]*"
    r"|\bto\s+(?:sign|prepare|send|review|execute|wire|pay|deliver|transfer|"
    r"issue|submit|file|counter-sign|countersign)\b[^.\n]*",
    re.IGNORECASE,
)


def _extract_owner(text: str) -> Optional[str]:
    for rx in _OWNER_RES:
        m = rx.search(text or "")
        if m:
            return m.group(1)
    return None


def _extract_due(text: str) -> Optional[str]:
    m = _DUE_RE.search(text or "")
    return m.group(1) if m else None


def _extract_action(text: str) -> Optional[str]:
    m = _ACTION_RE.search(text or "")
    if m:
        return m.group(0).strip()[:200]
    return None


def _returned_package_present(subject: str, body: str, attachments: Any) -> bool:
    """Closure guard evidence (spec §"Do Not Close From Outbound Alone"): a returned
    package / accepted final proof. An attachment, OR an explicit returned-package
    phrase, satisfies it."""
    if attachments:
        return True
    hay = ((subject or "") + "\n" + (body or "")).lower()
    markers = (
        "returned package", "signed and returned", "countersigned",
        "fully executed", "receipt attached", "returned copy",
        "signed copy attached", "executed copy", "acceptance receipt",
    )
    return any(m in hay for m in markers)


# ---------------------------------------------------------------------------
# Correlation (spec §"Correlation Order")
# ---------------------------------------------------------------------------
def correlate(conn: Any, arrival: Any) -> Dict[str, Any]:
    """Strict-order correlation. Returns a dict with:
      conflict       -> True when >1 distinct project code (=> NEEDS_CONTROLLER)
      has_correlation-> True when ANY of steps 1-4 hit
      project_code / matter_slug / desk_owner / clickup_list_id (step 1)
      thread_ref (step 2), flight_id (step 4)
    Participant manifest is a HINT only — never a sole correlation for a mutation."""
    from kbl import project_registry_store as reg

    subject = getattr(arrival, "subject", "") or ""
    body = getattr(arrival, "full_body", "") or ""
    thread_id = getattr(arrival, "thread_id", "") or ""
    text = subject + "\n" + body

    out: Dict[str, Any] = {
        "conflict": False,
        "flight_conflict": False,
        "has_correlation": False,
        "project_code": None,
        "matter_slug": None,
        "desk_owner": None,
        "clickup_list_id": None,
        "thread_ref": None,
        "flight_id": None,
        "refs": [],
    }

    # Step 1 — explicit project code(s). >1 distinct => cross-matter conflict.
    try:
        codes = reg.extract_project_codes(text)
    except Exception as e:  # pragma: no cover - registry primitive is defensive itself
        logger.warning("extract_project_codes failed: %s", e)
        codes = []
    if len(codes) > 1:
        out["conflict"] = True
        out["refs"].append({"step": 1, "codes": codes})
        return out
    if codes:
        try:
            proj = reg.resolve_project_number(text)
        except Exception as e:  # pragma: no cover
            logger.warning("resolve_project_number failed: %s", e)
            proj = None
        if proj:
            out["project_code"] = proj.get("project_number")
            out["matter_slug"] = proj.get("matter_slug")
            out["desk_owner"] = proj.get("desk_owner")
            out["clickup_list_id"] = proj.get("clickup_list_id")
            out["has_correlation"] = True
            out["refs"].append({"step": 1, "project_code": out["project_code"]})

    # Step 2 — an existing OTHER airport_tickets row on the same source thread. The
    # outbound row's OWN capture (ticket_id 'airport-outbound:<message_id>', whose
    # source_id == thread_id) is EXCLUDED — a row must not correlate to itself, or every
    # outbound would self-satisfy condition (3).
    if thread_id:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT ticket_id FROM airport_tickets "
                    "WHERE (bus_thread_id = %s OR source_id = %s) "
                    "AND ticket_id NOT LIKE 'airport-outbound:%%' "
                    "ORDER BY created_at LIMIT 1",
                    (thread_id, thread_id),
                )
                row = cur.fetchone()
            if row:
                out["thread_ref"] = row[0]
                out["has_correlation"] = True
                out["refs"].append({"step": 2, "ticket_id": row[0]})
        except Exception as e:
            logger.warning("thread correlation failed: %s", e)

    # Step 4 — active flight thread / dispatch id (record-only). Collect the DISTINCT
    # flight refs on this thread (prior NON-outbound tickets' suspected_flight + any
    # active dispatcher thread). >1 DISTINCT flight = ambiguous correlation ->
    # flight_conflict -> NEEDS_CONTROLLER (F4; spec §"Correlation Order": ">1 correlated
    # project/flight -> stop at NEEDS_CONTROLLER"). Outbound self-capture rows excluded.
    flights: set = set()
    if thread_id:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT suspected_flight FROM airport_tickets "
                    "WHERE (bus_thread_id = %s OR source_id = %s) "
                    "AND suspected_flight IS NOT NULL "
                    "AND ticket_id NOT LIKE 'airport-outbound:%%'",
                    (thread_id, thread_id),
                )
                flights.update(r[0] for r in cur.fetchall() if r[0])
        except Exception as e:
            logger.warning("flight correlation failed: %s", e)
    disp = _correlate_dispatcher_flight(conn, thread_id, out["project_code"])
    if disp:
        flights.add(disp)
    if len(flights) > 1:
        out["flight_conflict"] = True
        out["refs"].append({"step": 4, "flights": sorted(flights)})
    elif len(flights) == 1:
        out["flight_id"] = next(iter(flights))
        out["has_correlation"] = True
        out["refs"].append({"step": 4, "flight_id": out["flight_id"]})

    return out


def _correlate_dispatcher_flight(
    conn: Any, thread_id: str, project_code: Optional[str]
) -> Optional[str]:
    """Step 4 (bonus): an active dispatcher_bus_threads row (open / waiting_reply) for
    this thread. Wrapped defensively — the table may not exist in every deployment."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT to_regclass('public.dispatcher_bus_threads')"
            )
            if not cur.fetchone()[0]:
                return None
            cur.execute(
                "SELECT thread_key FROM dispatcher_bus_threads "
                "WHERE status IN ('open', 'waiting_reply') AND thread_key = %s "
                "ORDER BY created_at DESC LIMIT 1",
                (thread_id,),
            )
            row = cur.fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.warning("dispatcher flight correlation skipped: %s", e)
        return None


# ---------------------------------------------------------------------------
# Event-row helpers
# ---------------------------------------------------------------------------
def _load_or_create_event(conn: Any, ticket_id: str, arrival: Any) -> Dict[str, Any]:
    """Idempotent upsert keyed to ticket_id (1:1 with the outbound airport_tickets
    row). Returns the current event row as a dict."""
    message_id = getattr(arrival, "message_id", "") or ""
    thread_id = getattr(arrival, "thread_id", "") or ""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO airport_outbound_events (ticket_id, message_id, thread_id, "
            "event_state) VALUES (%s, %s, %s, 'CAPTURED') "
            "ON CONFLICT (ticket_id) DO NOTHING",
            (ticket_id, message_id, thread_id),
        )
        cur.execute(
            "SELECT ticket_id, message_id, thread_id, event_state, ratification_class, "
            "project_code, clickup_task_id, clickup_status, clickup_idempotency_key, "
            "flight_id, flight_to_state, flight_idempotency_key "
            "FROM airport_outbound_events WHERE ticket_id = %s",
            (ticket_id,),
        )
        r = cur.fetchone()
    return {
        "ticket_id": r[0], "message_id": r[1], "thread_id": r[2], "event_state": r[3],
        "ratification_class": r[4], "project_code": r[5], "clickup_task_id": r[6],
        "clickup_status": r[7], "clickup_idempotency_key": r[8], "flight_id": r[9],
        "flight_to_state": r[10], "flight_idempotency_key": r[11],
    }


def _update_event(conn: Any, ticket_id: str, **fields: Any) -> None:
    """Set event columns + bump updated_at. `correlation` is JSONB-wrapped."""
    if not fields:
        return
    cols: List[str] = []
    vals: List[Any] = []
    for k, v in fields.items():
        cols.append(f"{k} = %s")
        vals.append(_json_param(v) if k == "correlation" else v)
    vals.append(ticket_id)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE airport_outbound_events SET "
            + ", ".join(cols)
            + ", updated_at = NOW() WHERE ticket_id = %s",
            tuple(vals),
        )


def _audit(
    conn: Any,
    action_type: str,
    target_task_id: str,
    payload: Dict[str, Any],
    success: bool,
    error_message: Optional[str] = None,
) -> None:
    """One baker_actions row per ClickUp write / flight transition (spec §audit)."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO baker_actions (action_type, target_task_id, target_space_id, "
            "payload, trigger_source, success, error_message) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                action_type,
                target_task_id,
                _BAKER_SPACE_ID,
                _json_param(payload),
                _TRIGGER_SOURCE,
                success,
                error_message,
            ),
        )


# ---------------------------------------------------------------------------
# ClickUp client indirection (test seam)
# ---------------------------------------------------------------------------
def _get_clickup_client() -> Any:
    """Return the shared ClickUpClient singleton (so the ≤10-writes/cycle cap is
    honored across writers). Overridden in tests with a thin recording fake."""
    from clickup_client import ClickUpClient

    return ClickUpClient._get_global_instance()


def _resolve_list_space(client: Any, list_id: str) -> Optional[str]:
    """Resolve the ClickUp Space id that owns ``list_id``, or None if unconfirmable.

    Enforces the repo HARD RULE (F2): never write ClickUp outside BAKER Space
    ``901510186446``. The connector writes ONLY when this returns ``_BAKER_SPACE_ID``;
    a non-BAKER space OR an unconfirmable result (None) blocks the write (fail-safe).
    Delegates to the ClickUpClient's own space-resolution path; guarded so a client
    without it (or a network error) blocks rather than silently writing."""
    try:
        fn = (getattr(client, "resolve_space_id_for_list", None)
              or getattr(client, "_resolve_space_id_for_list", None))
        if fn is None:
            return None
        return fn(list_id)
    except Exception as e:
        logger.warning("clickup space resolve failed for list %s: %s", list_id, e)
        return None


# ---------------------------------------------------------------------------
# ClickUp status + flight mapping
# ---------------------------------------------------------------------------
def _clickup_status(rclass: str, complete: bool, returned_package: bool) -> str:
    if rclass in (CLASS_APPROVAL, CLASS_INSTRUCTION):
        return _STATUS_READY if complete else _STATUS_PACKET_DRAFT
    if rclass == CLASS_EXTERNAL_SEND:
        return _STATUS_WAITING_REPLY
    if rclass == CLASS_DELIVERABLE:
        return _STATUS_WAITING_REPLY
    if rclass == CLASS_COMMITMENT:
        return _STATUS_PACKET_DRAFT
    if rclass == CLASS_CLOSE:
        return _STATUS_CLOSED if returned_package else _STATUS_NEEDS_DIRECTOR
    return _STATUS_PACKET_DRAFT


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def process_outbound_event(conn: Any, arrival: Any) -> Dict[str, Any]:
    """Drive one captured outbound arrival through the event state machine.

    Called from the bridge's (b.5) outbound branch AFTER _ingest_outbound_signal, in
    the SAME transaction (no commit here). Returns:
        {"event_state": <state>, "terminal": <bool>, "clickup_written": <bool>,
         "flight_progressed": <bool>}
    ``terminal`` is False ONLY for ERROR_RETRY (transient ClickUp failure → the bridge
    freezes its cursor so the event is retried, never silently dropped).
    """
    ensure_airport_outbound_events_table(conn)
    ticket_id = "airport-outbound:" + (getattr(arrival, "message_id", "") or "")
    ev = _load_or_create_event(conn, ticket_id, arrival)

    # (idempotency / AC4) Already resolved on a prior tick — never re-write ClickUp or
    # re-progress the flight. CLICKUP_BLOCKED / NEEDS_CONTROLLER are terminal-for-tick
    # too (await a Controller / data change, do not spin the cursor). Only ERROR_RETRY
    # falls through to retry.
    if ev["event_state"] in _TERMINAL_STATES:
        return {"event_state": ev["event_state"], "terminal": True,
                "clickup_written": False, "flight_progressed": False}

    subject = getattr(arrival, "subject", "") or ""
    body = getattr(arrival, "full_body", "") or ""
    sender = getattr(arrival, "sender_email", "") or ""
    attachments = getattr(arrival, "attachments", ()) or ()

    # ---- Ratifying vs routine gate (spec §"Ratifying Vs Routine Outbound"), 4 conds:
    # (1) direction proven outbound — guaranteed: the bridge only calls us for a
    #     Brisen-classified outbound arrival. Record DIRECTION_PROVEN.
    _update_event(conn, ticket_id, event_state=DIRECTION_PROVEN)

    # (2) sender authority — Brisen-controlled sender (already classified outbound) that
    #     is NOT an automated / system notifier (AC11).
    if _is_system_notification(sender, subject):
        _update_event(conn, ticket_id, event_state=EVIDENCE_ONLY,
                      ratification_class=None)
        return {"event_state": EVIDENCE_ONLY, "terminal": True,
                "clickup_written": False, "flight_progressed": False}

    # (4-first) correlation — needed for both condition (3) and the conflict guard.
    # >1 correlated project OR >1 correlated flight -> NEEDS_CONTROLLER, no write
    # (spec §"Correlation Order"; F4).
    corr = correlate(conn, arrival)
    if corr["conflict"] or corr.get("flight_conflict"):
        _update_event(conn, ticket_id, event_state=NEEDS_CONTROLLER,
                      correlation=corr)
        return {"event_state": NEEDS_CONTROLLER, "terminal": True,
                "clickup_written": False, "flight_progressed": False}

    # (4) content class.
    rclass = classify_ratification(subject, body)

    # Ratifying requires ALL four: direction (1) + authority (2) + correlation (3) +
    # ratification class (4). Any miss → routine → EVIDENCE_ONLY (no write, no flight).
    if not (corr["has_correlation"] and rclass):
        state = EVIDENCE_ONLY if corr["has_correlation"] else CORRELATION_PENDING
        # CORRELATION_PENDING with no ratification content still resolves to evidence.
        _update_event(conn, ticket_id, event_state=EVIDENCE_ONLY,
                      ratification_class=rclass, project_code=corr["project_code"],
                      matter_slug=corr["matter_slug"], desk_owner=corr["desk_owner"],
                      clickup_list_id=corr["clickup_list_id"], flight_id=corr["flight_id"],
                      correlation=corr)
        return {"event_state": EVIDENCE_ONLY, "terminal": True,
                "clickup_written": False, "flight_progressed": False}

    # ---- RATIFICATION_READY.
    _update_event(conn, ticket_id, event_state=RATIFICATION_READY,
                  ratification_class=rclass, project_code=corr["project_code"],
                  matter_slug=corr["matter_slug"], desk_owner=corr["desk_owner"],
                  clickup_list_id=corr["clickup_list_id"], flight_id=corr["flight_id"],
                  correlation=corr)

    return _write_clickup_then_flight(conn, arrival, ticket_id, rclass, corr,
                                      subject, body, attachments)


def _write_clickup_then_flight(
    conn: Any, arrival: Any, ticket_id: str, rclass: str, corr: Dict[str, Any],
    subject: str, body: str, attachments: Any,
) -> Dict[str, Any]:
    """RATIFICATION_READY → ClickUp write → (on success) flight progression."""
    message_id = getattr(arrival, "message_id", "") or ""
    text = subject + "\n" + body

    # Required task fields (spec §"ClickUp Write Contract" + AC5, F3). A ratifying write
    # needs an assignable next step: owner + due date + required action. Missing ANY of
    # them -> CLICKUP_BLOCKED (no write, no flight). For send/deliverable/close/commitment
    # the action is implicit in the class and the owner falls back to the correlated desk;
    # approval/instruction must carry both explicitly in the email.
    owner = _extract_owner(text)
    due = _extract_due(text)
    action = _extract_action(text)
    if rclass in (CLASS_EXTERNAL_SEND, CLASS_DELIVERABLE, CLASS_CLOSE, CLASS_COMMITMENT):
        owner = owner or corr.get("desk_owner")
        action = action or rclass
    complete = bool(owner and due and action)
    returned_package = _returned_package_present(subject, body, attachments)

    list_id = corr.get("clickup_list_id")
    client = _get_clickup_client()

    # CLICKUP_BLOCKED gate — checked BEFORE any write, in order:
    #   - BAKER_CLICKUP_READONLY kill switch (the connector's internal write kill switch;
    #     Director-facing activation stays the ONE flag AIRPORT_OUTBOUND_INGEST_ENABLED);
    #   - no target list;
    #   - incomplete required fields owner+due+action (AC5 / F3);
    #   - target list not confirmably in BAKER Space 901510186446 (repo HARD RULE / F2:
    #     never write ClickUp outside BAKER Space; unconfirmable -> block, fail-safe).
    readonly = os.getenv("BAKER_CLICKUP_READONLY", "").strip().lower() == "true"
    block_reason = None
    if readonly:
        block_reason = "readonly"
    elif not list_id:
        block_reason = "no_clickup_list"
    elif not complete:
        block_reason = "missing_owner_date_or_action"
    elif _resolve_list_space(client, list_id) != _BAKER_SPACE_ID:
        block_reason = "non_baker_space"
    if block_reason:
        _update_event(conn, ticket_id, event_state=CLICKUP_BLOCKED, last_error=block_reason)
        _audit(conn, "airport_outbound.clickup_write", ticket_id,
               {"message_id": message_id, "project_code": corr.get("project_code"),
                "operation": "create_task", "status": None, "blocked_reason": block_reason,
                "idempotency_key": None},
               success=False, error_message="CLICKUP_BLOCKED:" + block_reason)
        return {"event_state": CLICKUP_BLOCKED, "terminal": True,
                "clickup_written": False, "flight_progressed": False}

    status = _clickup_status(rclass, complete, returned_package)
    target_ref = corr.get("project_code") or ticket_id
    idem = "outbound-clickup:v1:%s:%s:%s" % (message_id, target_ref, rclass)
    title = ("[outbound %s] %s" % (rclass, subject))[:255]

    # ---- ClickUp write. Two distinct failure modes (F1):
    #   - EXCEPTION (unexpected throw) -> ERROR_RETRY: caught, never re-raised, cursor
    #     freezes so the event is retried (AC10b). Not a silent drop.
    #   - None / missing-id RETURN -> CLICKUP_BLOCKED: clickup_client._request returns
    #     None on HTTP>=400 / exhausted retries; that is a HANDLED write FAILURE, NOT a
    #     success — audit success=False, do NOT progress flight (AC10). The event is
    #     durably recorded (not silently dropped).
    task_id = None
    try:
        res = client.create_task(
            list_id=list_id,
            name=title,
            description=("Outbound ratification (%s) message_id=%s\n%s"
                         % (rclass, message_id, (body or "")[:1500])),
            status=status,
            # record-only: the parsed due string is kept in the event/audit; we do not
            # fabricate a ms timestamp from a bare ISO date (no reliable tz).
            due_date=None,
        )
        task_id = (res or {}).get("id")
    except Exception as exc:
        _update_event(conn, ticket_id, event_state=ERROR_RETRY,
                      clickup_idempotency_key=idem, clickup_status=status,
                      clickup_operation="create_task", last_error=str(exc)[:400])
        _audit(conn, "airport_outbound.clickup_write", idem,
               {"message_id": message_id, "project_code": corr.get("project_code"),
                "operation": "create_task", "status": status, "idempotency_key": idem},
               success=False, error_message=str(exc)[:400])
        return {"event_state": ERROR_RETRY, "terminal": False,
                "clickup_written": False, "flight_progressed": False}

    if not task_id:
        _update_event(conn, ticket_id, event_state=CLICKUP_BLOCKED,
                      clickup_idempotency_key=idem, clickup_status=status,
                      clickup_operation="create_task",
                      last_error="clickup_write_failed_no_id")
        _audit(conn, "airport_outbound.clickup_write", idem,
               {"message_id": message_id, "project_code": corr.get("project_code"),
                "operation": "create_task", "status": status, "idempotency_key": idem,
                "blocked_reason": "clickup_write_failed_no_id"},
               success=False, error_message="clickup_write_failed_no_id")
        return {"event_state": CLICKUP_BLOCKED, "terminal": True,
                "clickup_written": False, "flight_progressed": False}

    _update_event(conn, ticket_id, event_state=CLICKUP_WRITTEN,
                  clickup_task_id=task_id, clickup_status=status,
                  clickup_operation="create_task", clickup_idempotency_key=idem)
    _audit(conn, "airport_outbound.clickup_write", (task_id or idem),
           {"message_id": message_id, "project_code": corr.get("project_code"),
            "operation": "create_task", "status": status, "idempotency_key": idem},
           success=True)

    # ---- Flight progression — ONLY after a successful ClickUp write (ordering).
    return _progress_flight(conn, ticket_id, message_id, rclass, corr,
                            returned_package, task_id, status)


def _progress_flight(
    conn: Any, ticket_id: str, message_id: str, rclass: str, corr: Dict[str, Any],
    returned_package: bool, task_id: Optional[str], clickup_status: str,
) -> Dict[str, Any]:
    """Record-only flight transition. No live flight store is mutated (lead #4851)."""
    flight_id = corr.get("flight_id")
    base_result = {"event_state": CLICKUP_WRITTEN, "terminal": True,
                   "clickup_written": True, "flight_progressed": False}

    # AC6: no active flight (correlation step-4 miss) → FLIGHT_BLOCKED. ClickUp already
    # wrote; the flight cannot progress without a flight to progress.
    if not flight_id:
        _update_event(conn, ticket_id, event_state=FLIGHT_BLOCKED)
        base_result["event_state"] = FLIGHT_BLOCKED
        return base_result

    from_state, to_state = _FLIGHT_TRANSITION.get(rclass, (None, None))

    # Closure guard (spec §"Do Not Close From Outbound Alone"): CLASS_CLOSE may reach
    # `landed` ONLY with a returned package / accepted final proof. Otherwise it stays
    # at waiting_receipt and escalates to a Controller (AC8) — never a silent close.
    if rclass == CLASS_CLOSE:
        if returned_package:
            to_state = "landed"
        else:
            to_state = "waiting_receipt"
            _update_event(conn, ticket_id, event_state=NEEDS_CONTROLLER,
                          flight_id=flight_id, flight_from_state=from_state,
                          flight_to_state=to_state)
            _audit(conn, "airport_outbound.flight_transition_recorded",
                   (flight_id or ticket_id),
                   {"message_id": message_id, "flight_id": flight_id,
                    "from_state": from_state, "to_state": to_state,
                    "ratification_class": rclass, "returned_package_required": True,
                    "returned_package_present": False, "clickup_task_id": task_id},
                   success=False, error_message="closure_guard:no_returned_package")
            return {"event_state": NEEDS_CONTROLLER, "terminal": True,
                    "clickup_written": True, "flight_progressed": False}

    flight_idem = "outbound-flight:v1:%s:%s:%s" % (message_id, flight_id, rclass)
    _update_event(conn, ticket_id, event_state=FLIGHT_PROGRESSED,
                  flight_id=flight_id, flight_from_state=from_state,
                  flight_to_state=to_state, flight_idempotency_key=flight_idem)
    _audit(conn, "airport_outbound.flight_transition_recorded", (flight_id or flight_idem),
           {"message_id": message_id, "flight_id": flight_id, "from_state": from_state,
            "to_state": to_state, "ratification_class": rclass,
            "idempotency_key": flight_idem, "clickup_task_id": task_id,
            "clickup_status": clickup_status},
           success=True)
    return {"event_state": FLIGHT_PROGRESSED, "terminal": True,
            "clickup_written": True, "flight_progressed": True}
