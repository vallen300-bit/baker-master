"""BAKER_OS_V2_STEP2_ONWARD_JOURNEY_BLOCKS_2_4_1 — Airside onward journey (blocks 2-4).

The lounge writer (blocks 1/5/6, PRs #458/#459) drove the 20 BB tickets to
``airport_outbound_events`` rows at ``event_state='CLICKUP_WRITTEN'`` (ticket_id scheme
``airport-lounge:v1:<source_ticket_id>``) + a ClickUp task at "to do" in BB-AUK-001
Timetable (list 901524194809). This module continues the journey on that SAME event row:

    BOARDING_POSTED  (T1) — WORK_PACKET posted to the desk over the bus, accept-token issued
    CLAIMED          (T1) — desk replied ``CLAIM <token>``; ClickUp mirrored to "in progress"
    (in-flight)      (T2) — desk STATUS transitions mirror to ClickUp (row stays CLAIMED)
    LANDED           (T3) — desk replied ``LANDED <token>`` + package
    RECEIPT_WRITTEN  (T3) — ClickUp closed + receipt comment + bus RECEIPT proof; journey Closed
    NEEDS_CONTROLLER (T4) — no claim within TTL after one re-nudge

Ships DARK behind ``AIRPORT_BOARDING_FLOW_ENABLED`` (default false); flag-off = total
no-op. Every ClickUp write goes through ``clickup_client`` (BAKER-space guard + 10/cycle
cap); ``BAKER_CLICKUP_READONLY`` short-circuits to a logged no-op. Flight columns stay
NULL (D-23) — journey progress lives on ``event_state`` + ``correlation`` JSON only. The
reply grammar the desk uses is the SOP deliverable (T5); the parser here and that SOP
MUST match verbatim.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from typing import Any, Dict, List, Optional

from orchestrator.airport_ticketing_bridge import (
    _bridge_key,
    _bus_message_id,
    _json_param,
    _request_json,
)
from orchestrator.airport_checkin_reader import (
    _ack,
    _bus_base,
    _fetch_full_body,
    _fetch_inbox,
)
from orchestrator.airport_outbound_connector import (
    _BAKER_SPACE_ID,
    _resolve_clickup_status,
)

logger = logging.getLogger(__name__)

# --- Env gates --------------------------------------------------------------
_ENABLED_ENV = "AIRPORT_BOARDING_FLOW_ENABLED"    # default OFF (merge = no-op)
_READONLY_ENV = "BAKER_CLICKUP_READONLY"          # repo kill switch (dry-run)
_SLUG_ENV = "AIRPORT_BOARDING_READER_SLUG"        # our own bus identity (poster + reader)
_DEFAULT_SLUG = "ticketing-desk"                  # same dispatcher identity as the poster
_POLL_LIMIT_ENV = "AIRPORT_BOARDING_POLL_LIMIT"
_DEFAULT_POLL_LIMIT = 25
_CLAIM_TTL_HOURS_ENV = "AIRPORT_BOARDING_CLAIM_TTL_HOURS"
_DEFAULT_CLAIM_TTL_HOURS = 48
_POST_LIMIT_ENV = "AIRPORT_BOARDING_POST_LIMIT"
_DEFAULT_POST_LIMIT = 100

_LOUNGE_KEY_PREFIX = "airport-lounge:v1:"
_DESK = "baden-baden-desk"
_TRIGGER = "airport_boarding_flow"

# --- Event states (mirror migrations/20260704a_airport_onward_journey.sql) ---
CLICKUP_WRITTEN = "CLICKUP_WRITTEN"     # lounge terminal = onward-journey start
BOARDING_POSTED = "BOARDING_POSTED"
CLAIMED = "CLAIMED"
LANDED = "LANDED"
RECEIPT_WRITTEN = "RECEIPT_WRITTEN"
NEEDS_CONTROLLER = "NEEDS_CONTROLLER"

# --- D-25 in-flight status mirror: desk STATUS token -> canonical ClickUp literal.
# Routed through _resolve_clickup_status(list_id, canonical); for BB-AUK-001 these pass
# through unchanged (the list vocab already carries them), and a future per-list override
# can remap them without touching this module.
_STATUS_CANONICAL = {
    "BLOCKED": "blocked",
    "WAITING": "waiting",
    "UPDATE_REQUIRED": "update required",
}
_CLAIM_STATUS = "in progress"      # CLAIM -> ClickUp in progress
_CLOSE_STATUS = "complete"         # RECEIPT_WRITTEN -> ClickUp complete
_NEEDS_CONTROLLER_STATUS = "update required"   # T4 escalation ClickUp status


# ---------------------------------------------------------------------------
# Env helpers
# ---------------------------------------------------------------------------
def boarding_enabled() -> bool:
    return os.environ.get(_ENABLED_ENV, "false").strip().lower() in {"1", "true", "yes", "on"}


def _readonly() -> bool:
    return os.environ.get(_READONLY_ENV, "").strip().lower() == "true"


def _boarding_slug() -> str:
    return (os.environ.get(_SLUG_ENV) or _DEFAULT_SLUG).strip()


def _poll_limit() -> int:
    try:
        return max(1, min(int(os.environ.get(_POLL_LIMIT_ENV, str(_DEFAULT_POLL_LIMIT))), 100))
    except (TypeError, ValueError):
        return _DEFAULT_POLL_LIMIT


def _post_limit() -> int:
    try:
        return max(1, min(int(os.environ.get(_POST_LIMIT_ENV, str(_DEFAULT_POST_LIMIT))), 500))
    except (TypeError, ValueError):
        return _DEFAULT_POST_LIMIT


def _claim_ttl_hours() -> float:
    try:
        return max(0.0, float(os.environ.get(_CLAIM_TTL_HOURS_ENV, str(_DEFAULT_CLAIM_TTL_HOURS))))
    except (TypeError, ValueError):
        return float(_DEFAULT_CLAIM_TTL_HOURS)


# ---------------------------------------------------------------------------
# Accept token (deterministic; recomputable for verification)
# ---------------------------------------------------------------------------
def accept_token(ev_ticket_id: str) -> str:
    """Deterministic per-ticket accept token. Recomputable, so verification never needs a
    stored secret — a claim reply is authenticated by recomputing this from the row's own
    ticket_id and comparing constant-time."""
    digest = hashlib.sha256(("claim:v1:" + (ev_ticket_id or "")).encode("utf-8")).hexdigest()
    return "claim:v1:" + digest[:20]


def _token_matches(ev_ticket_id: str, presented: str) -> bool:
    import hmac
    return hmac.compare_digest(accept_token(ev_ticket_id), (presented or "").strip())


# ---------------------------------------------------------------------------
# Reply grammar parser (SOP deliverable T5 must match this VERBATIM)
# ---------------------------------------------------------------------------
_CMD_RE = re.compile(r"^\s*(CLAIM|STATUS|LANDED)\b(.*)$", re.IGNORECASE | re.MULTILINE)


def parse_desk_reply(body: str) -> Optional[Dict[str, Any]]:
    """Parse a desk reply into exactly one command, or None (0 or >1 commands = ambiguous;
    never guess). Pure function, never raises. Grammar:

        CLAIM <token>
        STATUS BLOCKED|WAITING|UPDATE_REQUIRED <token> [note...]
        LANDED <token>
        <package: free text after the LANDED line>

    Returns dicts:
        {"kind": "CLAIM",  "token": str}
        {"kind": "STATUS", "state": "BLOCKED|WAITING|UPDATE_REQUIRED", "token": str, "note": str}
        {"kind": "LANDED", "token": str, "package": str}
    """
    if not body:
        return None
    try:
        matches = list(_CMD_RE.finditer(body))
        if len(matches) != 1:
            return None  # 0 = no command; >1 = ambiguous. Both -> leave un-acked, log loud.
        m = matches[0]
        cmd = m.group(1).upper()
        rest = (m.group(2) or "").strip()
        if cmd == "CLAIM":
            parts = rest.split()
            if len(parts) != 1:
                return None  # CLAIM takes exactly a token, nothing else
            return {"kind": "CLAIM", "token": parts[0]}
        if cmd == "STATUS":
            parts = rest.split(maxsplit=2)
            if len(parts) < 2:
                return None
            state = parts[0].upper()
            if state not in _STATUS_CANONICAL:
                return None
            token = parts[1]
            note = parts[2].strip() if len(parts) == 3 else ""
            return {"kind": "STATUS", "state": state, "token": token, "note": note}
        if cmd == "LANDED":
            # token = first word on the LANDED line; package = everything after that line.
            first_line = rest.splitlines()[0] if rest else ""
            tokens = first_line.split()
            if not tokens:
                return None
            token = tokens[0]
            package = body[m.end():].strip()
            # any trailing text on the LANDED line itself (rare) prepends the package
            trailing = " ".join(tokens[1:]).strip()
            if trailing:
                package = (trailing + "\n" + package).strip()
            return {"kind": "LANDED", "token": token, "package": package}
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# DB helpers (guarded transitions on airport_outbound_events)
# ---------------------------------------------------------------------------
def _audit(conn: Any, action_type: str, target_task_id: Optional[str],
           payload: Dict[str, Any], success: bool,
           error_message: Optional[str] = None) -> None:
    """One baker_actions row per bus/ClickUp write, trigger_source airport_boarding_flow."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO baker_actions (action_type, target_task_id, target_space_id, "
            "payload, trigger_source, success, error_message) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (action_type, target_task_id, _BAKER_SPACE_ID, _json_param(payload),
             _TRIGGER, success, error_message),
        )


def _guarded_transition(conn: Any, ev_ticket_id: str, from_state: str, to_state: str,
                        correlation_patch: Optional[Dict[str, Any]] = None) -> bool:
    """Advance a row from exactly ``from_state`` to ``to_state``, merging ``correlation_patch``
    into the JSON. Returns True iff one row moved (wrong-order / missing row -> False, so a
    replayed or out-of-order reply is a safe no-op)."""
    patch = _json_param(correlation_patch or {})
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE airport_outbound_events "
            "SET event_state = %s, correlation = correlation || %s::jsonb, updated_at = NOW() "
            "WHERE ticket_id = %s AND event_state = %s",
            (to_state, patch, ev_ticket_id, from_state),
        )
        return cur.rowcount == 1


def _patch_correlation(conn: Any, ev_ticket_id: str, require_state: str,
                       correlation_patch: Dict[str, Any]) -> bool:
    """Merge a correlation patch WITHOUT advancing state (T2 mirror stays at CLAIMED).
    Guarded on ``require_state`` so a mirror never lands on a non-CLAIMED row."""
    patch = _json_param(correlation_patch or {})
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE airport_outbound_events "
            "SET correlation = correlation || %s::jsonb, updated_at = NOW() "
            "WHERE ticket_id = %s AND event_state = %s",
            (patch, ev_ticket_id, require_state),
        )
        return cur.rowcount == 1


def _row_by_token(conn: Any, token: str) -> Optional[Dict[str, Any]]:
    """Locate the lounge row whose issued accept_token matches. Bounded, indexed on the
    JSON key at read time; token is unique per ticket."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ticket_id, event_state, clickup_list_id, clickup_task_id, "
            "       matter_slug, correlation "
            "FROM airport_outbound_events "
            "WHERE ticket_id LIKE 'airport-lounge:%%' "
            "  AND correlation->>'accept_token' = %s "
            "LIMIT 1",
            (token,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {"ticket_id": row[0], "event_state": row[1], "clickup_list_id": row[2],
            "clickup_task_id": row[3], "matter_slug": row[4], "correlation": row[5] or {}}


def _read_rows_in_state(conn: Any, state: str, limit: int) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ticket_id, message_id, clickup_list_id, clickup_task_id, matter_slug, "
            "       correlation, EXTRACT(EPOCH FROM updated_at) "
            "FROM airport_outbound_events "
            "WHERE ticket_id LIKE 'airport-lounge:%%' AND desk_owner = %s AND event_state = %s "
            "ORDER BY created_at ASC LIMIT %s",
            (_DESK, state, limit),
        )
        rows = cur.fetchall()
    return [{"ticket_id": r[0], "message_id": r[1], "clickup_list_id": r[2],
             "clickup_task_id": r[3], "matter_slug": r[4], "correlation": r[5] or {},
             "updated_ts": float(r[6] or 0)} for r in rows]


# ---------------------------------------------------------------------------
# Bus + ClickUp write primitives (readonly-aware)
# ---------------------------------------------------------------------------
def _get_clickup_client() -> Any:
    from clickup_client import ClickUpClient
    return ClickUpClient()


def _post_bus(recipient: str, body: str, topic: str) -> Dict[str, Any]:
    key = _bridge_key()
    if not key:
        return {"ok": False, "error": "boarding_key_missing"}
    base = _bus_base()
    payload = {"kind": "dispatch", "body": body, "to": [recipient],
               "tier_required": "B", "topic": topic}
    result = _request_json("POST", f"{base}/msg/{recipient}", key=key, payload=payload)
    if result.get("error"):
        return {"ok": False, **result}
    result["ok"] = True
    return result


def _mirror_clickup_status(client: Any, list_id: Optional[str], task_id: Optional[str],
                           canonical: str, comment: Optional[str] = None) -> Dict[str, Any]:
    """Resolve ``canonical`` to the list literal and apply it, plus an optional comment.
    Readonly short-circuits to a logged no-op (matches run_lounge_drain dry-run)."""
    literal = _resolve_clickup_status(list_id, canonical)
    if _readonly():
        logger.warning("boarding DRY-RUN (readonly): WOULD set task %s -> %s (comment=%s)",
                       task_id, literal, bool(comment))
        return {"ok": True, "dry_run": True, "status": literal}
    if not task_id:
        return {"ok": False, "error": "no_task_id"}
    client.update_task(task_id, status=literal)
    if comment:
        client.post_comment(task_id, comment)
    return {"ok": True, "status": literal}


# ---------------------------------------------------------------------------
# T1 — post WORK_PACKETs to the desk (CLICKUP_WRITTEN -> BOARDING_POSTED)
# ---------------------------------------------------------------------------
def _format_work_packet(ev: Dict[str, Any], token: str) -> str:
    corr = ev.get("correlation") or {}
    luggage = corr.get("luggage") or corr.get("luggage_summary") or "(see ClickUp task)"
    if isinstance(luggage, list):
        luggage = "\n".join(f"- {x}" for x in luggage) or "- (none)"
    return (
        f"TO: {_DESK}\n"
        f"FROM: {_boarding_slug()}\n"
        f"RE: WORK_PACKET {ev['ticket_id']}\n\n"
        "WORK_PACKET v1\n"
        f"ticket_ref: {ev['ticket_id']}\n"
        f"clickup_task_id: {ev.get('clickup_task_id')}\n"
        f"clickup_list_id: {ev.get('clickup_list_id')}\n"
        f"matter_slug: {ev.get('matter_slug')}\n"
        f"accept_token: {token}\n"
        "luggage:\n"
        f"{luggage}\n\n"
        "Reply grammar (reply on this thread):\n"
        f"  CLAIM {token}\n"
        f"  STATUS BLOCKED|WAITING|UPDATE_REQUIRED {token} [note]\n"
        f"  LANDED {token}\n"
        "  <package after the LANDED line: state / evidence / asks — free text>"
    )


def run_boarding_poster(conn: Any) -> Dict[str, Any]:
    """T1: post a WORK_PACKET to the desk for each CLICKUP_WRITTEN lounge row and advance it
    to BOARDING_POSTED. Idempotent — a row at BOARDING_POSTED-or-later is never re-posted
    (the CLICKUP_WRITTEN filter excludes it)."""
    posted = errors = 0
    rows = _read_rows_in_state(conn, CLICKUP_WRITTEN, _post_limit())
    for ev in rows:
        ev_id = ev["ticket_id"]
        token = accept_token(ev_id)
        try:
            res = _post_bus(_DESK, _format_work_packet(ev, token), f"boarding/{ev_id}")
            if not res.get("ok"):
                errors += 1
                logger.error("boarding post failed for %s: %s", ev_id, res.get("error"))
                continue
            bus_id = _bus_message_id(res)
            moved = _guarded_transition(
                conn, ev_id, CLICKUP_WRITTEN, BOARDING_POSTED,
                {"accept_token": token, "boarding_bus_id": bus_id,
                 "boarding_posted_ts": ev["updated_ts"], "nudge_count": 0},
            )
            _audit(conn, "airport_boarding.boarding_posted", ev.get("clickup_task_id"),
                   {"ticket_id": ev_id, "bus_id": bus_id, "moved": moved}, success=moved)
            conn.commit()
            if moved:
                posted += 1
        except Exception as e:
            conn.rollback()
            errors += 1
            logger.error("boarding poster hard error for %s: %s", ev_id, e)
            continue
    return {"posted": posted, "errors": errors, "candidates": len(rows)}


# ---------------------------------------------------------------------------
# T1/T2/T3 reader — CLAIM / STATUS / LANDED replies from the desk
# ---------------------------------------------------------------------------
def run_boarding_reader(conn: Any) -> Dict[str, Any]:
    """Read desk replies on our bus inbox; drive CLAIM (T1), STATUS mirror (T2), LANDED
    (T3). Commit BEFORE ACK so a crash re-reads idempotently. Ambiguous / unmatched /
    unauthenticated replies are logged loudly and left UN-ACKed (never silently dropped)."""
    base, key, slug = _bus_base(), _bridge_key(), _boarding_slug()
    if not key:
        return {"ok": False, "reason": "boarding_key_missing"}
    claimed = mirrored = landed = replay = unmatched = bad_token = parsed_none = errors = 0
    client = None if _readonly() else _get_clickup_client()
    if client is not None:
        client.reset_cycle_counter()
    for msg in _fetch_inbox(base, slug, key, _poll_limit()):
        mid = None
        try:
            mid = int(msg["id"])
            sender = str(msg.get("from_terminal") or "").strip()
            if not sender or sender == slug:
                continue
            body = _fetch_full_body(base, mid, key) or str(msg.get("body_preview") or "")
            parsed = parse_desk_reply(body)
            if parsed is None:
                parsed_none += 1
                logger.warning("boarding reader: unparseable/ambiguous reply id=%s from=%s "
                               "(left un-acked)", mid, sender)
                continue
            row = _row_by_token(conn, parsed["token"])
            if row is None:
                unmatched += 1
                logger.warning("boarding reader: no row for token on id=%s (left un-acked)", mid)
                continue
            ev_id = row["ticket_id"]
            if not _token_matches(ev_id, parsed["token"]):
                bad_token += 1
                logger.error("boarding reader: token mismatch id=%s ticket=%s (left un-acked)",
                             mid, ev_id)
                continue

            outcome = _apply_reply(conn, client, row, parsed, sender)
            conn.commit()  # commit BEFORE ack

            if outcome == "claimed":
                claimed += 1; _ack(base, mid, key)
            elif outcome == "mirrored":
                mirrored += 1; _ack(base, mid, key)
            elif outcome == "landed":
                landed += 1; _ack(base, mid, key)
            elif outcome == "replay":
                replay += 1; _ack(base, mid, key)  # idempotent replay: ACK or it re-reads forever
            else:
                # "stale": reply arrived for a row not in the expected state and not a
                # clean replay — leave un-acked, retried/handled next tick.
                errors += 0
                logger.warning("boarding reader: out-of-order %s for %s (state=%s), un-acked",
                               parsed["kind"], ev_id, row["event_state"])
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            errors += 1
            logger.error("boarding reader reply failed id=%s: %s", mid, e)
            continue  # one bad reply never stops the batch
    return {"ok": True, "claimed": claimed, "mirrored": mirrored, "landed": landed,
            "replay": replay, "unmatched": unmatched, "bad_token": bad_token,
            "parsed_none": parsed_none, "errors": errors}


def _apply_reply(conn: Any, client: Any, row: Dict[str, Any], parsed: Dict[str, Any],
                 sender: str) -> str:
    """Apply one authenticated reply. Returns one of:
    claimed | mirrored | landed | replay | stale. ClickUp writes happen BEFORE the state
    advance so a write failure raises and leaves the row un-advanced (retried next tick)."""
    ev_id = row["ticket_id"]
    state = row["event_state"]
    list_id, task_id = row["clickup_list_id"], row["clickup_task_id"]
    kind = parsed["kind"]

    if kind == "CLAIM":
        if state in (CLAIMED, LANDED, RECEIPT_WRITTEN):
            return "replay"  # already claimed-or-later
        if state != BOARDING_POSTED:
            return "stale"
        self_mirror = _mirror_clickup_status(client, list_id, task_id, _CLAIM_STATUS)
        moved = _guarded_transition(conn, ev_id, BOARDING_POSTED, CLAIMED,
                                    {"claimed_by": sender, "claimed": True})
        _audit(conn, "airport_boarding.claimed", task_id,
               {"ticket_id": ev_id, "by": sender, "clickup": self_mirror}, success=moved)
        return "claimed" if moved else "stale"

    if kind == "STATUS":
        if state != CLAIMED:
            return "replay" if state in (LANDED, RECEIPT_WRITTEN) else "stale"
        canonical = _STATUS_CANONICAL[parsed["state"]]
        note = parsed.get("note") or ""
        comment = f"Desk status → {parsed['state']}" + (f": {note}" if note else "")
        mirror = _mirror_clickup_status(client, list_id, task_id, canonical, comment=comment)
        _patch_correlation(conn, ev_id, CLAIMED,
                           {"last_mirrored_status": canonical, "last_mirror_by": sender})
        _audit(conn, "airport_boarding.status_mirrored", task_id,
               {"ticket_id": ev_id, "state": parsed["state"], "clickup": mirror}, success=True)
        return "mirrored"

    if kind == "LANDED":
        if state in (LANDED, RECEIPT_WRITTEN):
            return "replay"
        if state != CLAIMED:
            return "stale"
        moved = _guarded_transition(conn, ev_id, CLAIMED, LANDED,
                                    {"landed_by": sender, "package": parsed.get("package", "")})
        _audit(conn, "airport_boarding.landed", task_id,
               {"ticket_id": ev_id, "by": sender}, success=moved)
        return "landed" if moved else "stale"

    return "stale"


# ---------------------------------------------------------------------------
# T3 — receipt writer (LANDED -> RECEIPT_WRITTEN): close ClickUp + receipt + bus proof
# ---------------------------------------------------------------------------
def run_receipt_writer(conn: Any) -> Dict[str, Any]:
    """For each LANDED row: close the ClickUp task (complete) + receipt comment, post a bus
    RECEIPT proof to the desk, advance to RECEIPT_WRITTEN, and close the source ticket
    (checked_in -> closed). Journey is Closed ONLY when task-closed + receipt-row +
    bus-proof-id all land. Any partial failure leaves the row at LANDED with last_error
    (fail-loud), retried next cycle. Sub-steps recorded in correlation for idempotency."""
    written = errors = 0
    client = None if _readonly() else _get_clickup_client()
    rows = _read_rows_in_state(conn, LANDED, _post_limit())
    for ev in rows:
        ev_id = ev["ticket_id"]
        corr = ev.get("correlation") or {}
        list_id, task_id = ev.get("clickup_list_id"), ev.get("clickup_task_id")
        try:
            # (1) ClickUp close + receipt comment (idempotent: skip if already done)
            if not corr.get("receipt_clickup_done"):
                pkg = corr.get("package") or ""
                receipt = ("RECEIPT — journey closed. Onward-journey package received and "
                           "logged." + (f"\n\nPackage:\n{pkg}" if pkg else ""))
                mirror = _mirror_clickup_status(client, list_id, task_id, _CLOSE_STATUS,
                                                comment=receipt)
                if not mirror.get("ok"):
                    raise RuntimeError(f"clickup close failed: {mirror.get('error')}")
                _patch_correlation(conn, ev_id, LANDED, {"receipt_clickup_done": True})

            # (2) bus RECEIPT proof to the desk (idempotent: skip if id already stored)
            receipt_bus_id = corr.get("receipt_bus_id")
            if not receipt_bus_id and not _readonly():
                res = _post_bus(_DESK, f"RECEIPT v1\nticket_ref: {ev_id}\nstatus: closed\n"
                                       "The onward journey is closed; receipt written to ClickUp.",
                                f"receipt/{ev_id}")
                if not res.get("ok"):
                    raise RuntimeError(f"receipt bus post failed: {res.get('error')}")
                receipt_bus_id = _bus_message_id(res)
                _patch_correlation(conn, ev_id, LANDED, {"receipt_bus_id": receipt_bus_id})

            # (3) advance + close source ticket, only once (1)+(2) are proven
            moved = _guarded_transition(conn, ev_id, LANDED, RECEIPT_WRITTEN,
                                        {"receipt_written": True})
            source_ticket_id = ev_id[len(_LOUNGE_KEY_PREFIX):] if ev_id.startswith(_LOUNGE_KEY_PREFIX) else None
            closed_source = _close_source_ticket(conn, source_ticket_id) if source_ticket_id else False
            _audit(conn, "airport_boarding.receipt_written", task_id,
                   {"ticket_id": ev_id, "receipt_bus_id": receipt_bus_id,
                    "source_ticket_id": source_ticket_id, "source_closed": closed_source},
                   success=moved)
            conn.commit()
            if moved:
                written += 1
        except Exception as e:
            conn.rollback()
            errors += 1
            _park_error(conn, ev_id, str(e))
            logger.error("receipt writer failed for %s (parked at LANDED): %s", ev_id, e)
            continue
    return {"written": written, "errors": errors, "candidates": len(rows)}


def _close_source_ticket(conn: Any, source_ticket_id: str) -> bool:
    """Guarded close of the source airport_tickets row (only from checked_in)."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE airport_tickets SET status = 'closed', updated_at = NOW() "
            "WHERE ticket_id = %s AND status = 'checked_in'",
            (source_ticket_id,),
        )
        return cur.rowcount == 1


def _park_error(conn: Any, ev_ticket_id: str, err: str) -> None:
    """Record last_error on a row without advancing it (fail-loud, retried next cycle)."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE airport_outbound_events SET last_error = %s, updated_at = NOW() "
                "WHERE ticket_id = %s",
                (err[:500], ev_ticket_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()


# ---------------------------------------------------------------------------
# T4 — exception lane: no-claim TTL re-nudge -> NEEDS_CONTROLLER
# ---------------------------------------------------------------------------
def run_boarding_ttl_nudge(conn: Any) -> Dict[str, Any]:
    """BOARDING_POSTED rows past the claim TTL: re-nudge once, then escalate to
    NEEDS_CONTROLLER + ClickUp "update required". Nudge state lives in correlation
    (nudge_count / last_nudged analog), never on flight columns."""
    ttl_hours = _claim_ttl_hours()
    nudged = escalated = errors = 0
    client = None if _readonly() else _get_clickup_client()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ticket_id, clickup_list_id, clickup_task_id, correlation, "
            "       EXTRACT(EPOCH FROM (NOW() - updated_at)) / 3600.0 "
            "FROM airport_outbound_events "
            "WHERE ticket_id LIKE 'airport-lounge:%%' AND desk_owner = %s "
            "  AND event_state = %s "
            "ORDER BY updated_at ASC LIMIT %s",
            (_DESK, BOARDING_POSTED, _post_limit()),
        )
        rows = cur.fetchall()
    for r in rows:
        ev_id, list_id, task_id, corr, age_hours = r[0], r[1], r[2], (r[3] or {}), float(r[4] or 0)
        if age_hours < ttl_hours:
            continue
        nudge_count = int(corr.get("nudge_count") or 0)
        try:
            if nudge_count < 1:
                token = corr.get("accept_token") or accept_token(ev_id)
                res = _post_bus(_DESK, f"NUDGE v1 — WORK_PACKET {ev_id} still unclaimed after "
                                       f"{ttl_hours:.0f}h. Reply: CLAIM {token}", f"boarding/{ev_id}")
                if not res.get("ok"):
                    raise RuntimeError(f"nudge post failed: {res.get('error')}")
                _patch_correlation(conn, ev_id, BOARDING_POSTED,
                                   {"nudge_count": nudge_count + 1})
                _audit(conn, "airport_boarding.nudged", task_id,
                       {"ticket_id": ev_id, "nudge_count": nudge_count + 1}, success=True)
                conn.commit()
                nudged += 1
            else:
                mirror = _mirror_clickup_status(client, list_id, task_id, _NEEDS_CONTROLLER_STATUS,
                                                comment="Escalated to Controller — no desk claim "
                                                        "within TTL after re-nudge.")
                if not mirror.get("ok"):
                    raise RuntimeError(f"escalation clickup failed: {mirror.get('error')}")
                moved = _guarded_transition(conn, ev_id, BOARDING_POSTED, NEEDS_CONTROLLER,
                                            {"escalated": True})
                _audit(conn, "airport_boarding.escalated", task_id,
                       {"ticket_id": ev_id, "clickup": mirror}, success=moved)
                conn.commit()
                if moved:
                    escalated += 1
        except Exception as e:
            conn.rollback()
            errors += 1
            _park_error(conn, ev_id, str(e))
            logger.error("boarding TTL nudge failed for %s: %s", ev_id, e)
            continue
    return {"nudged": nudged, "escalated": escalated, "errors": errors, "candidates": len(rows)}


# ---------------------------------------------------------------------------
# Reconciliation (AC5) — flight-leak + state accounting across the new states
# ---------------------------------------------------------------------------
_ONWARD_STATES = (CLICKUP_WRITTEN, BOARDING_POSTED, CLAIMED, LANDED, RECEIPT_WRITTEN,
                  NEEDS_CONTROLLER)
_TERMINAL_STATES = frozenset({RECEIPT_WRITTEN, NEEDS_CONTROLLER})


def reconcile_onward(conn: Any) -> Dict[str, Any]:
    """Journey reconciliation over the airport-lounge rows:
      - flight_column_leak_count: any lounge row carrying a non-NULL flight column (D-23),
        across ALL states incl. the new ones;
      - by_state: count per state (0 rows in an undefined state is proven by the sum);
      - non_terminal: (ticket_id, state, age_hours) for every row not at a terminal state.
    ``clean`` = no flight leaks AND every row accounted in a known state."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM airport_outbound_events "
            "WHERE ticket_id LIKE 'airport-lounge:%%' AND ("
            "  flight_id IS NOT NULL OR flight_from_state IS NOT NULL "
            "  OR flight_to_state IS NOT NULL OR flight_idempotency_key IS NOT NULL)"
        )
        flight_leaks = int(cur.fetchone()[0])
        cur.execute(
            "SELECT event_state, COUNT(*) FROM airport_outbound_events "
            "WHERE ticket_id LIKE 'airport-lounge:%%' GROUP BY event_state"
        )
        by_state = {s: int(c) for s, c in cur.fetchall()}
        cur.execute(
            "SELECT ticket_id, event_state, "
            "       ROUND(EXTRACT(EPOCH FROM (NOW() - updated_at)) / 3600.0, 1) "
            "FROM airport_outbound_events "
            "WHERE ticket_id LIKE 'airport-lounge:%%' "
            "  AND event_state NOT IN ('RECEIPT_WRITTEN', 'NEEDS_CONTROLLER') "
            "ORDER BY updated_at ASC LIMIT 500"
        )
        non_terminal = [{"ticket_id": r[0], "state": r[1], "age_hours": float(r[2] or 0)}
                        for r in cur.fetchall()]
    undefined = {s: c for s, c in by_state.items() if s not in _ONWARD_STATES}
    clean = flight_leaks == 0 and not undefined
    return {"flight_column_leak_count": flight_leaks, "by_state": by_state,
            "undefined_states": undefined, "non_terminal": non_terminal,
            "non_terminal_count": len(non_terminal), "clean": clean}


# ---------------------------------------------------------------------------
# Operator sweep entry (T1->T4 + reconcile). Gated; flag-off = no-op.
# ---------------------------------------------------------------------------
def _dry_run_plan(conn: Any) -> Dict[str, Any]:
    """AC4 readonly dry-run: NON-MUTATING end-to-end. Reads the current per-state counts +
    reconciliation and reports what a live sweep WOULD do — zero DB / ClickUp / bus writes,
    no bus read, no ACK. Mirrors run_lounge_drain's dry-run 'planned' semantics."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT event_state, COUNT(*) FROM airport_outbound_events "
            "WHERE ticket_id LIKE 'airport-lounge:%%' AND desk_owner = %s GROUP BY event_state",
            (_DESK,),
        )
        counts = {s: int(c) for s, c in cur.fetchall()}
    rec = reconcile_onward(conn)
    plan = {
        "would_post_boarding": counts.get(CLICKUP_WRITTEN, 0),
        "awaiting_claim": counts.get(BOARDING_POSTED, 0),
        "in_flight": counts.get(CLAIMED, 0),
        "would_write_receipt": counts.get(LANDED, 0),
    }
    logger.info("onward-journey DRY-RUN (readonly, non-mutating): plan=%s", plan)
    return {"enabled": True, "dry_run": True, "plan": plan, "by_state": counts,
            "reconciliation": rec}


def run_onward_journey_sweep(conn: Any) -> Dict[str, Any]:
    """One full onward-journey pass. Order: post boarding packets, read desk replies, write
    receipts for landed rows, run the TTL exception lane, reconcile. Flag-gated no-op when
    AIRPORT_BOARDING_FLOW_ENABLED is not set; readonly = non-mutating plan (AC4)."""
    if not boarding_enabled():
        logger.info("onward-journey sweep: AIRPORT_BOARDING_FLOW_ENABLED not set — no-op")
        return {"enabled": False}
    if _readonly():
        return _dry_run_plan(conn)
    report = {
        "enabled": True,
        "dry_run": _readonly(),
        "boarding": run_boarding_poster(conn),
        "reader": run_boarding_reader(conn),
        "receipts": run_receipt_writer(conn),
        "exceptions": run_boarding_ttl_nudge(conn),
        "reconciliation": reconcile_onward(conn),
    }
    return report
