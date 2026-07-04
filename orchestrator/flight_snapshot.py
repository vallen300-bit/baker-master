"""BAKER_OS_V2_FLIGHT_SNAPSHOT_BB_AUK_001_1 — read-only per-flight snapshot assembler.

D-24 (2026-07-04): every active flight needs a Director-visible dashboard. Until the
flight lifecycle store exists (D-23), these are READ-ONLY snapshots assembled from
whatever evidence exists today — they must NOT claim authoritative live flight-state.
D-23: ZERO writes anywhere. D-29: no mockup-v3 content reuse; the D-24 field list is
the ratified content contract, layout minimal + clean.

This module is pure read. It fans a `project_code` (e.g. "BB-AUK-001") into the D-24
field contract from five independent evidence sources, each degrading on its own:
  outcome, deadline, current state (derived — labeled), next owner/action, blockers,
  condition precedents, evidence, human nudges, ClickUp refs, ticket/dispatch refs,
  returned-package status, history.
Missing evidence for a field ⇒ an explicit "no data yet" marker — never an invented
value. Every DB read is wrapped so one dead source can't blank the whole snapshot.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import psycopg2.extras

from kbl.db import get_conn
from kbl.project_registry_store import resolve_project_number

logger = logging.getLogger(__name__)

# Explicit "field has no evidence yet" marker — rendered honestly, never a guessed value.
NO_DATA = {"status": "no data yet"}

# Bounded reads everywhere (repo hard rule: never an unbounded query).
_ROW_CAP = 50


def _iso(value: Any) -> Any:
    """Best-effort ISO-format for datetimes; pass through anything else."""
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _fetch(sql: str, params: tuple) -> list[dict]:
    """Run one read-only SELECT and return a list of dicts. Any failure (missing
    table, bad column, dead pool) degrades to [] — a single source never blanks the
    whole snapshot. This module NEVER issues INSERT/UPDATE/DELETE."""
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:  # fault-tolerant read: degrade, don't raise
        logger.warning("flight_snapshot read failed (%s): %s", sql.split()[0:4], e)
        return []


# --------------------------------------------------------------------------
# Per-source readers (each read-only, each degrades independently)
# --------------------------------------------------------------------------

def _project_meta(project_code: str) -> Optional[dict]:
    """resolve_project_number → matter_slug / desk_owner / clickup_list_id / status.
    Returns None if the code is not a registered active project (caller ⇒ 404)."""
    try:
        return resolve_project_number(project_code)
    except Exception as e:
        logger.warning("resolve_project_number failed for %s: %s", project_code, e)
        return None


def _outbound_events(project_code: str) -> list[dict]:
    return _fetch(
        """
        SELECT event_state, ratification_class, flight_id, flight_from_state,
               flight_to_state, clickup_list_id, clickup_task_id, clickup_status,
               clickup_operation, last_error, message_id, thread_id, created_at,
               updated_at
          FROM airport_outbound_events
         WHERE project_code = %s
         ORDER BY created_at DESC
         LIMIT %s
        """,
        (project_code, _ROW_CAP),
    )


def _tickets(matter_slug: Optional[str], flight_label: Optional[str]) -> list[dict]:
    """airport_tickets has no project_code column — link by suspected_matter_slug or
    suspected_flight (both free-text evidence fields)."""
    if not matter_slug and not flight_label:
        return []
    return _fetch(
        """
        SELECT ticket_id, status, direction, source_channel, source_id,
               suspected_matter_slug, suspected_flight, proposed_desk_slug,
               bus_message_id, bus_thread_id, nudge_count, last_nudged_at,
               escalated_at, check_in_outcome, created_at, updated_at
          FROM airport_tickets
         WHERE (suspected_matter_slug = %s OR suspected_flight = %s)
           AND ticket_id NOT LIKE 'airport-outbound:%%'
         ORDER BY created_at DESC
         LIMIT %s
        """,
        (matter_slug, flight_label, _ROW_CAP),
    )


def _deadlines(matter_slug: Optional[str]) -> list[dict]:
    if not matter_slug:
        return []
    return _fetch(
        """
        SELECT id, description, due_date, status, priority, severity,
               assigned_to, obligation_type
          FROM deadlines
         WHERE matter_slug = %s
           AND status IN ('active', 'pending_confirm')
         ORDER BY due_date ASC NULLS LAST
         LIMIT %s
        """,
        (matter_slug, _ROW_CAP),
    )


def _audit_actions(project_code: str) -> list[dict]:
    """baker_actions has no matter column — flight linkage lives in the JSONB payload."""
    return _fetch(
        """
        SELECT action_type, trigger_source, success, created_at, committed_at,
               payload
          FROM baker_actions
         WHERE payload->>'project_code' = %s
         ORDER BY created_at DESC
         LIMIT %s
        """,
        (project_code, _ROW_CAP),
    )


# --------------------------------------------------------------------------
# Field derivations (D-24 contract) — value or explicit NO_DATA, never invented
# --------------------------------------------------------------------------

_BLOCKER_STATES = {"CLICKUP_BLOCKED", "FLIGHT_BLOCKED", "ERROR_RETRY", "NEEDS_CONTROLLER"}
_RETURNED_STATES = {"RATIFICATION_READY", "CLICKUP_WRITTEN", "FLIGHT_PROGRESSED"}


def _derive_current_state(events: list[dict]) -> dict:
    """Derived-from-evidence label ONLY (D-24/D-23: never authoritative live state)."""
    if not events:
        return dict(NO_DATA)
    latest = events[0]
    label = latest.get("flight_to_state") or latest.get("event_state")
    if not label:
        return dict(NO_DATA)
    return {
        "value": label,
        "derivation": "derived from evidence (latest airport_outbound_event); "
                      "NOT authoritative live flight-state",
        "as_of": _iso(latest.get("created_at")),
    }


def _derive_blockers(events: list[dict]) -> Any:
    out = []
    for e in events:
        if e.get("event_state") in _BLOCKER_STATES or e.get("last_error"):
            out.append({
                "state": e.get("event_state"),
                "error": e.get("last_error"),
                "as_of": _iso(e.get("created_at")),
            })
    return out or dict(NO_DATA)


def _derive_next_action(meta: Optional[dict], events: list[dict]) -> dict:
    owner = (meta or {}).get("desk_owner")
    pending = next(
        (e for e in events if e.get("event_state") in _BLOCKER_STATES), None
    )
    if not owner and not pending:
        return dict(NO_DATA)
    return {
        "next_owner": owner or "no data yet",
        "action_hint": (pending or {}).get("event_state", "no data yet"),
        "derivation": "derived from desk registry + latest actionable event",
    }


def _derive_deadline(deadlines: list[dict]) -> Any:
    if not deadlines:
        return dict(NO_DATA)
    d = deadlines[0]
    return {
        "description": d.get("description"),
        "due_date": _iso(d.get("due_date")),
        "status": d.get("status"),
        "priority": d.get("priority"),
        "assigned_to": d.get("assigned_to"),
    }


def _derive_nudges(tickets: list[dict]) -> Any:
    nudged = [t for t in tickets if (t.get("nudge_count") or 0) > 0]
    if not nudged:
        return dict(NO_DATA)
    return [
        {
            "ticket_id": t.get("ticket_id"),
            "nudge_count": t.get("nudge_count"),
            "last_nudged_at": _iso(t.get("last_nudged_at")),
            "escalated_at": _iso(t.get("escalated_at")),
        }
        for t in nudged
    ]


def _derive_clickup_refs(meta: Optional[dict], events: list[dict]) -> Any:
    refs = []
    for e in events:
        if e.get("clickup_task_id") or e.get("clickup_status"):
            refs.append({
                "task_id": e.get("clickup_task_id"),
                "status": e.get("clickup_status"),
                "operation": e.get("clickup_operation"),
                "list_id": e.get("clickup_list_id"),
            })
    list_id = (meta or {}).get("clickup_list_id")
    if not refs and not list_id:
        return dict(NO_DATA)
    return {"list_id": list_id, "task_refs": refs}


def _derive_ticket_refs(tickets: list[dict]) -> Any:
    if not tickets:
        return dict(NO_DATA)
    return [
        {
            "ticket_id": t.get("ticket_id"),
            "status": t.get("status"),
            "direction": t.get("direction"),
            "channel": t.get("source_channel"),
            "bus_message_id": t.get("bus_message_id"),
            "bus_thread_id": t.get("bus_thread_id"),
        }
        for t in tickets
    ]


def _derive_returned_package(events: list[dict]) -> Any:
    rel = [
        {
            "state": e.get("event_state"),
            "ratification_class": e.get("ratification_class"),
            "as_of": _iso(e.get("created_at")),
        }
        for e in events
        if e.get("event_state") in _RETURNED_STATES or e.get("ratification_class")
    ]
    return rel or dict(NO_DATA)


def _derive_evidence(tickets: list[dict], events: list[dict], actions: list[dict]) -> Any:
    refs = []
    for t in tickets:
        if t.get("source_id"):
            refs.append({"kind": "ticket_source", "channel": t.get("source_channel"),
                         "ref": t.get("source_id")})
    for e in events:
        if e.get("message_id"):
            refs.append({"kind": "outbound_event", "ref": e.get("message_id")})
    for a in actions:
        refs.append({"kind": "audit_action", "ref": a.get("action_type"),
                     "as_of": _iso(a.get("created_at"))})
    return refs or dict(NO_DATA)


def _derive_history(events: list[dict], actions: list[dict]) -> Any:
    """Merged recent events + audit actions, newest first."""
    hist = []
    for e in events:
        hist.append({
            "ts": _iso(e.get("created_at")),
            "kind": "outbound_event",
            "detail": e.get("event_state"),
            "flight": f"{e.get('flight_from_state')} -> {e.get('flight_to_state')}"
                      if e.get("flight_to_state") else None,
        })
    for a in actions:
        hist.append({
            "ts": _iso(a.get("created_at")),
            "kind": "audit_action",
            "detail": a.get("action_type"),
            "flight": None,
        })
    hist = [h for h in hist if h["ts"]]
    hist.sort(key=lambda h: h["ts"], reverse=True)
    return hist[:_ROW_CAP] or dict(NO_DATA)


# --------------------------------------------------------------------------
# Public assembler
# --------------------------------------------------------------------------

def build_flight_snapshot(project_code: str) -> Optional[dict]:
    """Assemble the read-only D-24 snapshot for `project_code`.

    Returns None iff the code is not a registered active project (route ⇒ 404).
    Otherwise returns a dict with every D-24 field present (value or an explicit
    "no data yet" marker) plus meta + an assembled-at timestamp. Pure read; each
    evidence source degrades independently so a 0-row / dead source renders cleanly.
    """
    code = (project_code or "").strip()
    if not code:
        return None
    meta = _project_meta(code)
    if not meta:
        return None

    matter_slug = meta.get("matter_slug")
    # suspected_flight is a free-text label; the project_code is the best available key.
    events = _outbound_events(code)
    tickets = _tickets(matter_slug, code)
    deadlines = _deadlines(matter_slug)
    actions = _audit_actions(code)

    return {
        "project_code": code,
        "assembled_at": datetime.now(timezone.utc).isoformat(),
        "authoritative": False,
        "meta": {
            "project_number": meta.get("project_number"),
            "matter_slug": matter_slug,
            "desk_owner": meta.get("desk_owner"),
            "desk_code": meta.get("desk_code"),
            "clickup_list_id": meta.get("clickup_list_id"),
            "registry_status": meta.get("status"),
        },
        "fields": {
            # D-24 field contract, in contract order.
            "outcome": NO_DATA.copy(),  # no ratified outcome store yet — honest.
            "deadline": _derive_deadline(deadlines),
            "current_state": _derive_current_state(events),
            "next_owner_action": _derive_next_action(meta, events),
            "blockers": _derive_blockers(events),
            "condition_precedents": NO_DATA.copy(),  # no CP store yet — honest.
            "evidence": _derive_evidence(tickets, events, actions),
            "human_nudges": _derive_nudges(tickets),
            "clickup_refs": _derive_clickup_refs(meta, events),
            "ticket_dispatch_refs": _derive_ticket_refs(tickets),
            "returned_package_status": _derive_returned_package(events),
            "history": _derive_history(events, actions),
        },
        "counts": {
            "outbound_events": len(events),
            "tickets": len(tickets),
            "deadlines": len(deadlines),
            "audit_actions": len(actions),
        },
    }


def list_registered_flights() -> list[dict]:
    """One-line state for every ACTIVE registered project (index route). Read-only,
    bounded; degrades to [] if the registry is unavailable."""
    rows = _fetch(
        """
        SELECT project_number, desk_owner, matter_slug, status
          FROM project_registry
         WHERE status = 'active'
         ORDER BY project_number
         LIMIT 200
        """,
        (),
    )
    return rows


# --------------------------------------------------------------------------
# Read-only HTML render (D-29: minimal + clean, NO mockup-v3 content reuse)
# --------------------------------------------------------------------------

# Muted McKinsey register (cream paper + deep navy). Template uses __TOKENS__
# filled via .replace() so CSS braces need no f-string escaping.
_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  body { background:#fafaf7; color:#1a1a1a; font-family:Helvetica,Arial,sans-serif;
         margin:0; padding:0 0 60px; }
  .wrap { max-width:960px; margin:0 auto; padding:24px; }
  .banner { background:#5a4a2a; color:#fff; padding:12px 16px; border-radius:4px;
            font-size:13px; line-height:1.5; margin-bottom:24px; }
  h1 { color:#1a3a52; font-size:24px; margin:0 0 4px; letter-spacing:.3px; }
  .sub { color:#666; font-size:13px; margin-bottom:24px; }
  .meta { color:#444; font-size:13px; margin-bottom:24px; }
  .meta span { display:inline-block; margin-right:18px; }
  section { border:1px solid #e3e0d6; border-radius:4px; margin-bottom:14px;
            background:#fff; }
  h2 { background:#f2efe6; color:#1a3a52; font-size:12px; text-transform:uppercase;
       letter-spacing:1px; margin:0; padding:9px 14px; border-bottom:1px solid #e3e0d6; }
  .body { padding:12px 14px; font-size:14px; }
  .nodata { color:#999; font-style:italic; }
  ul { margin:6px 0; padding-left:20px; }
  li { margin:3px 0; }
  .kv { color:#444; } .kv b { color:#1a1a1a; font-weight:600; }
  .derived { color:#8a6d3b; font-size:12px; }
  a { color:#1a3a52; }
  table.idx { border-collapse:collapse; width:100%; font-size:14px; }
  table.idx td, table.idx th { border-bottom:1px solid #eee; padding:7px 10px;
        text-align:left; }
</style></head><body><div class="wrap">
__BODY__
</div></body></html>"""


def _esc(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def _nodata(v: Any) -> bool:
    return isinstance(v, dict) and v.get("status") == "no data yet" and len(v) == 1


def _render_value(v: Any) -> str:
    """Render a field value (NO_DATA marker / dict / list / scalar) as safe HTML."""
    if _nodata(v):
        return '<span class="nodata">no data yet</span>'
    if isinstance(v, list):
        if not v:
            return '<span class="nodata">no data yet</span>'
        items = []
        for it in v:
            if isinstance(it, dict):
                parts = "; ".join(
                    f"<b>{_esc(k)}</b>: {_esc(val)}" for k, val in it.items()
                    if val is not None
                )
                items.append(f'<li class="kv">{parts}</li>')
            else:
                items.append(f"<li>{_esc(it)}</li>")
        return "<ul>" + "".join(items) + "</ul>"
    if isinstance(v, dict):
        rows = []
        for k, val in v.items():
            if val is None:
                continue
            cls = "derived" if k == "derivation" else "kv"
            rows.append(f'<div class="{cls}"><b>{_esc(k)}</b>: {_esc(val)}</div>')
        return "".join(rows) or '<span class="nodata">no data yet</span>'
    return _esc(v)


# D-24 field order + human labels.
_FIELD_LABELS = [
    ("outcome", "Outcome"),
    ("deadline", "Deadline"),
    ("current_state", "Current State (derived)"),
    ("next_owner_action", "Next Owner / Action"),
    ("blockers", "Blockers"),
    ("condition_precedents", "Condition Precedents"),
    ("evidence", "Evidence"),
    ("human_nudges", "Human Nudges"),
    ("clickup_refs", "ClickUp Refs"),
    ("ticket_dispatch_refs", "Ticket / Dispatch Refs"),
    ("returned_package_status", "Returned-Package Status"),
    ("history", "History (newest first)"),
]


def render_snapshot_html(snapshot: dict) -> str:
    """Render a single flight snapshot as a self-contained read-only HTML page."""
    code = _esc(snapshot.get("project_code"))
    meta = snapshot.get("meta", {})
    assembled = _esc(snapshot.get("assembled_at"))
    banner = (
        "READ-ONLY SNAPSHOT — assembled from evidence at "
        f"{assembled}; not authoritative flight state."
    )
    meta_html = (
        f'<span>Matter: <b>{_esc(meta.get("matter_slug"))}</b></span>'
        f'<span>Desk: <b>{_esc(meta.get("desk_owner"))}</b></span>'
        f'<span>Registry: <b>{_esc(meta.get("registry_status"))}</b></span>'
    )
    fields = snapshot.get("fields", {})
    sections = []
    for key, label in _FIELD_LABELS:
        sections.append(
            f'<section><h2>{_esc(label)}</h2>'
            f'<div class="body">{_render_value(fields.get(key))}</div></section>'
        )
    body = (
        f'<div class="banner">{_esc(banner)}</div>'
        f"<h1>Flight {code}</h1>"
        f'<div class="meta">{meta_html}</div>'
        + "".join(sections)
    )
    return _PAGE_TEMPLATE.replace("__TITLE__", f"Flight {code}").replace("__BODY__", body)


def render_index_html(flights: list[dict]) -> str:
    """Render the /flights index — one row per registered active project."""
    if flights:
        rows = "".join(
            "<tr>"
            f'<td><a href="/flights/{_esc(f.get("project_number"))}">'
            f'{_esc(f.get("project_number"))}</a></td>'
            f'<td>{_esc(f.get("desk_owner"))}</td>'
            f'<td>{_esc(f.get("matter_slug"))}</td>'
            f'<td>{_esc(f.get("status"))}</td>'
            "</tr>"
            for f in flights
        )
        table = (
            '<table class="idx"><tr><th>Flight</th><th>Desk</th><th>Matter</th>'
            f"<th>Registry</th></tr>{rows}</table>"
        )
    else:
        table = '<span class="nodata">no registered flights</span>'
    banner = (
        "READ-ONLY SNAPSHOTS — assembled from evidence; not authoritative flight state."
    )
    body = (
        f'<div class="banner">{_esc(banner)}</div>'
        "<h1>Flights</h1>"
        '<div class="sub">Per-flight read-only snapshots (D-24). '
        "Control Tower roll-up is a later surface (D-29).</div>"
        f'<section><h2>Registered Flights</h2><div class="body">{table}</div></section>'
    )
    return _PAGE_TEMPLATE.replace("__TITLE__", "Flights").replace("__BODY__", body)
